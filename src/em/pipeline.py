"""最终提交模型的训练、预测、校验和整体回退逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from .contracts import BASE_FEATURES, EXOG_FEATURES, HOURS, PRICE_LAG_FEATURES
from .ensemble import mean_ensemble, shrink_to_naive
from .models.lgbm import LGBMModel
from .models.mtlasso import MultiTaskLassoModel
from .models.naive import NaiveD1
from .models.ridge import RidgeModel


FINAL_MODEL = "shrink3_0.8"


@dataclass
class PipelineResult:
    """一次 D 日预测的结果和可审计元数据。"""

    predictions: pd.DataFrame
    metadata: dict[str, object]


def _normalise_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """复制并规范面板键，不修改调用者传入的对象。"""
    if not isinstance(panel, pd.DataFrame):
        raise TypeError("panel 必须是 pandas.DataFrame")
    required = {"day", "hour", "y", *BASE_FEATURES}
    missing = sorted(required.difference(panel.columns))
    if missing:
        raise ValueError(f"panel 缺少列: {missing}")
    frame = panel.copy()
    frame["day"] = pd.to_datetime(frame["day"], errors="coerce").dt.normalize()
    if frame["day"].isna().any():
        raise ValueError("panel.day 含无效日期")
    frame["hour"] = pd.to_numeric(frame["hour"], errors="coerce")
    if frame["hour"].isna().any() or not np.equal(
        frame["hour"].to_numpy(dtype=float),
        np.floor(frame["hour"].to_numpy(dtype=float)),
    ).all():
        raise ValueError("panel.hour 必须为整数")
    frame["hour"] = frame["hour"].astype(int)
    if not frame["hour"].isin(HOURS).all():
        raise ValueError("panel.hour 必须在 1..24")
    if frame.duplicated(["day", "hour"]).any():
        raise ValueError("panel 的 (day, hour) 主键重复")
    frame["y"] = pd.to_numeric(frame["y"], errors="coerce")
    return frame.sort_values(["day", "hour"], kind="stable").reset_index(drop=True)


def prepare_inference(
    panel: pd.DataFrame,
    as_of: object,
) -> tuple[pd.DataFrame, pd.DataFrame, list[int]]:
    """按 D 日切分训练集，并把 D 日重建为完整 24 小时网格。"""
    frame = _normalise_panel(panel)
    day = pd.Timestamp(as_of).normalize()
    if pd.isna(day):
        raise ValueError("as_of 不能为 NaT")
    train = frame[(frame["day"] < day) & frame["y"].notna()].copy()
    if train.empty:
        raise ValueError(f"D 日之前没有可用训练目标: {day.date()}")
    observed = frame.loc[frame["day"] == day].copy()
    observed_hours = set(observed["hour"].astype(int))
    missing_hours = [hour for hour in HOURS if hour not in observed_hours]
    template = pd.DataFrame({"day": day, "hour": list(HOURS)})
    test = template.merge(observed, on=["day", "hour"], how="left", suffixes=("", "_observed"))
    for column in frame.columns:
        if column not in {"day", "hour"} and f"{column}_observed" in test.columns:
            test[column] = test[f"{column}_observed"]
            test = test.drop(columns=[f"{column}_observed"])
        elif column not in {"day", "hour", "y"} and column not in test.columns:
            test[column] = np.nan
    if "y" not in test.columns:
        test["y"] = np.nan
    return train, test.loc[:, frame.columns], missing_hours


def _placeholder_frame(test: pd.DataFrame, pred: np.ndarray, model: str) -> pd.DataFrame:
    """将一维预测包装成 ensemble 所需的有限占位目标框。"""
    values = np.asarray(pred, dtype=float).reshape(-1)
    if len(values) != len(test):
        raise ValueError(f"{model} 预测长度错误: got {len(values)}, expected {len(test)}")
    if not np.isfinite(values).all():
        raise ValueError(f"{model} 产生了 NaN/inf")
    return pd.DataFrame(
        {
            "day": test["day"].to_numpy(),
            "hour": test["hour"].to_numpy(dtype=int),
            # D 日真实目标未知；ensemble 只需要一致的有限占位目标。
            "y": np.zeros(len(test), dtype=float),
            "pred": values,
            "model": model,
        }
    )


def _recent_same_hour_mean(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """计算 D 日之前最近七个日历日的同小时价格均值。"""
    recent_days = sorted(train["day"].unique())[-7:]
    recent = train[train["day"].isin(recent_days)]
    means = recent.groupby("hour")["y"].mean()
    return test["hour"].map(means).to_numpy(dtype=float)


def fallback_naive_prediction(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """按 D 日 lag1、七日同小时均值顺序生成最终回退预测。"""
    values = pd.to_numeric(test["p_lag1"], errors="coerce").to_numpy(
        dtype=float, copy=True
    )
    recent = _recent_same_hour_mean(train, test)
    unresolved = ~np.isfinite(values)
    values[unresolved] = recent[unresolved]
    if not np.isfinite(values).all():
        raise ValueError("fallback naive 仍无法为所有 24 小时生成有限预测")
    return values


def _d_feature_missing(test: pd.DataFrame) -> dict[str, list[int]]:
    """检查 D 日 27 个非日历特征，返回列到缺失小时的映射。"""
    missing: dict[str, list[int]] = {}
    for column in (*PRICE_LAG_FEATURES, *EXOG_FEATURES):
        values = pd.to_numeric(test[column], errors="coerce").to_numpy(dtype=float)
        hours = [
            int(hour)
            for hour, value in zip(test["hour"], values)
            if not np.isfinite(value)
        ]
        if hours:
            missing[column] = hours
    return missing


def naive_only_prediction(
    panel: pd.DataFrame,
    as_of: object,
    *,
    data_sha256: str | None = None,
    reason: str | None = None,
    data_stale: bool = True,
) -> PipelineResult:
    """在 D 日面板行缺失时仅用历史价格生成 24 点 naive 预测。"""
    frame = _normalise_panel(panel)
    day = pd.Timestamp(as_of).normalize()
    train = frame[(frame["day"] < day) & frame["y"].notna()].copy()
    if train.empty:
        raise ValueError(f"naive-only 没有 D 日之前的历史价格: {day.date()}")
    latest_day = train["day"].max()
    lag = train[train["day"] == latest_day].set_index("hour")["y"]
    recent = _recent_same_hour_mean(train, pd.DataFrame({"hour": list(HOURS)}))
    prices = pd.Series(list(HOURS), dtype="int64").map(lag).to_numpy(dtype=float, copy=True)
    missing = ~np.isfinite(prices)
    prices[missing] = recent[missing]
    if not np.isfinite(prices).all():
        raise ValueError("naive-only 无法为 24 个小时生成有限价格")
    predictions = pd.DataFrame({"day": day, "hour": list(HOURS), "price": prices})
    validation = validate_predictions(predictions, train=train, as_of=day)
    if not validation["ok"]:
        raise ValueError(f"naive-only 校验失败: {validation['errors']}")
    metadata: dict[str, object] = {
        "as_of": str(day.date()),
        "model": "naive_only",
        "base_model": FINAL_MODEL,
        "feature_set": "NAIVE_ONLY",
        "train_end": str(latest_day.date()),
        "data_sha256": data_sha256,
        "fallback": True,
        "fallback_reason": reason or "naive-only cache fallback",
        "naive_only": True,
        "data_stale": bool(data_stale),
        "component_status": {"naive_only": "ok"},
        "validation": validation,
    }
    return PipelineResult(predictions=predictions, metadata=metadata)


def validate_predictions(
    predictions: pd.DataFrame,
    *,
    train: pd.DataFrame,
    as_of: object,
) -> dict[str, object]:
    """校验 24 点结构、有限值和最近 30 日范围。"""
    day = pd.Timestamp(as_of).normalize()
    errors: list[str] = []
    frame = predictions.copy()
    required = {"day", "hour", "price"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        errors.append(f"缺少列: {missing}")
    if not errors:
        frame["day"] = pd.to_datetime(frame["day"], errors="coerce").dt.normalize()
        frame["hour"] = pd.to_numeric(frame["hour"], errors="coerce")
        frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
        if len(frame) != 24:
            errors.append(f"行数={len(frame)}，应为 24")
        if set(frame["hour"].dropna().astype(int)) != set(HOURS):
            errors.append("hour 不是 1..24 的完整集合")
        if frame["hour"].duplicated().any():
            errors.append("hour 重复")
        if not np.isfinite(frame["price"].to_numpy(dtype=float)).all():
            errors.append("price 含 NaN/inf")
        if not (frame["day"] == day).all():
            errors.append("day 与 as_of 不一致")

    recent = train[train["day"] >= day - pd.Timedelta(days=30)]["y"].to_numpy(dtype=float)
    range_warning = False
    lower = upper = None
    if np.isfinite(recent).any() and not errors:
        lower = float(np.nanmin(recent) - 50.0)
        upper = float(np.nanmax(recent) + 100.0)
        values = frame["price"].to_numpy(dtype=float)
        range_warning = bool((values < lower).any() or (values > upper).any())
    return {
        "ok": not errors,
        "errors": errors,
        "n_rows": int(len(frame)),
        "hours": sorted(frame["hour"].dropna().astype(int).tolist()) if "hour" in frame else [],
        "finite": bool("price" in frame and np.isfinite(frame["price"].to_numpy(dtype=float)).all()),
        "range_warning": range_warning,
        "range_lower": lower,
        "range_upper": upper,
    }


def run_pipeline(
    panel: pd.DataFrame,
    as_of: object,
    *,
    data_sha256: str | None = None,
) -> PipelineResult:
    """训练冻结的四模型组合并生成 D 日 24 点预测。"""
    day = pd.Timestamp(as_of).normalize()
    train, test, missing_hours = prepare_inference(panel, day)
    component_status: dict[str, str] = {}
    fallback = bool(missing_hours)
    fallback_reason: list[str] = []
    if missing_hours:
        fallback_reason.append(f"D 日缺少小时: {missing_hours}")

    feature_missing = _d_feature_missing(test)
    if feature_missing:
        prices = fallback_naive_prediction(train, test)
        predictions = pd.DataFrame(
            {"day": day, "hour": list(HOURS), "price": np.asarray(prices, dtype=float)}
        )
        validation = validate_predictions(predictions, train=train, as_of=day)
        if not validation["ok"]:
            raise ValueError(f"D 日特征不完整后的 naive fallback 校验失败: {validation['errors']}")
        return PipelineResult(
            predictions=predictions,
            metadata={
                "as_of": str(day.date()),
                "model": "naive_fallback",
                "base_model": FINAL_MODEL,
                "feature_set": "BASE_FEATURES",
                "train_end": str(train["day"].max().date()),
                "data_sha256": data_sha256,
                "fallback": True,
                "fallback_reason": f"D 日特征不完整: {sorted(feature_missing)}",
                "feature_missing": {"columns": sorted(feature_missing), "hours": feature_missing},
                "component_status": {"fallback": "naive"},
                "validation": validation,
            },
        )

    try:
        if fallback:
            raise ValueError("D 日小时网格不完整")
        ridge = RidgeModel(alpha=10.0).fit(train.loc[:, list(BASE_FEATURES)], train["y"])
        ridge_frame = _placeholder_frame(
            test, ridge.predict(test.loc[:, list(BASE_FEATURES)]), "ridge"
        )
        component_status["ridge"] = "ok"

        lgbm = LGBMModel().fit(train.loc[:, list(BASE_FEATURES)], train["y"])
        lgbm_frame = _placeholder_frame(
            test, lgbm.predict(test.loc[:, list(BASE_FEATURES)]), "lgbm"
        )
        component_status["lgbm"] = "ok"

        mtlasso = MultiTaskLassoModel(alpha=0.1, max_iter=5000).fit(
            train, BASE_FEATURES
        )
        mtlasso_out = mtlasso.predict(test)
        mtlasso_out = mtlasso_out.sort_values(["day", "hour"], kind="stable")
        mtlasso_frame = _placeholder_frame(
            test,
            mtlasso_out["pred"].to_numpy(dtype=float),
            "mtlasso",
        )
        component_status["mtlasso"] = "ok"

        naive_model = NaiveD1().fit(train.loc[:, list(BASE_FEATURES)], train["y"])
        naive_frame = _placeholder_frame(
            test, naive_model.predict(test.loc[:, list(BASE_FEATURES)]), "naive_d1"
        )
        component_status["naive_d1"] = "ok"

        mean3 = mean_ensemble([ridge_frame, lgbm_frame, mtlasso_frame], name="mean3")
        final = shrink_to_naive(mean3, naive_frame, weight=0.8, name=FINAL_MODEL)
        prices = final["pred"].to_numpy(dtype=float)
    except Exception as exc:
        fallback = True
        fallback_reason.append(f"组件失败，整体回退 naive: {type(exc).__name__}: {exc}")
        prices = fallback_naive_prediction(train, test)
        component_status["fallback"] = "naive"

    predictions = pd.DataFrame(
        {"day": day, "hour": list(HOURS), "price": np.asarray(prices, dtype=float)}
    )
    validation = validate_predictions(predictions, train=train, as_of=day)
    if not validation["ok"]:
        fallback = True
        fallback_reason.append("最终预测结构校验失败，重新使用 naive fallback")
        predictions["price"] = fallback_naive_prediction(train, test)
        validation = validate_predictions(predictions, train=train, as_of=day)
    if not validation["ok"]:
        raise ValueError(f"fallback 后预测仍未通过校验: {validation['errors']}")

    metadata: dict[str, object] = {
        "as_of": str(day.date()),
        "model": "naive_fallback" if fallback else FINAL_MODEL,
        "base_model": FINAL_MODEL,
        "feature_set": "BASE_FEATURES",
        "train_end": str(train["day"].max().date()),
        "data_sha256": data_sha256,
        "fallback": bool(fallback),
        "fallback_reason": "; ".join(fallback_reason) if fallback_reason else None,
        "feature_missing": {"columns": [], "hours": {}},
        "component_status": component_status,
        "validation": validation,
    }
    if pd.Timestamp(train["day"].max()) >= day:
        raise AssertionError("训练集最大日期必须严格早于 as_of")
    return PipelineResult(predictions=predictions, metadata=metadata)
