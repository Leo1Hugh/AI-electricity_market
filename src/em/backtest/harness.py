"""按时间切分的回测执行器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Fold:
    """一次训练/测试折的元数据。"""

    model: str
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    n_train: int
    n_test: int


@dataclass
class BacktestResult:
    """回测预测和折信息。"""

    predictions: pd.DataFrame
    folds: pd.DataFrame


_FOLD_COLUMNS = [
    "model",
    "train_start",
    "train_end",
    "test_start",
    "test_end",
    "n_train",
    "n_test",
]
_PREDICTION_COLUMNS = ["day", "hour", "y", "pred", "model"]


def _as_timestamp(value: object, name: str) -> pd.Timestamp:
    """将日期参数转换为不带时区、按日归一化的时间戳。"""
    try:
        ts = pd.Timestamp(value)
    except Exception as exc:  # pragma: no cover - pandas 提供具体错误信息
        raise ValueError(f"{name} 不是有效日期: {value!r}") from exc
    if pd.isna(ts):
        raise ValueError(f"{name} 不能为 NaT")
    # 面板契约使用当地日历日；日期比较不应受时分秒影响。
    return ts.tz_localize(None).normalize() if ts.tzinfo is not None else ts.normalize()


def _prepare_panel(panel: pd.DataFrame, features: Sequence[str]) -> pd.DataFrame:
    """检查并标准化面板，不改变调用者传入的对象。"""
    if not isinstance(panel, pd.DataFrame):
        raise TypeError("panel 必须是 pandas.DataFrame")
    required = {"day", "hour", "y", *features}
    missing = sorted(required.difference(panel.columns))
    if missing:
        raise ValueError(f"panel 缺少列: {missing}")
    if not features:
        raise ValueError("features 不能为空")
    out = panel.copy()
    day = pd.to_datetime(out["day"], errors="coerce")
    if day.isna().any():
        raise ValueError("panel.day 含无效日期")
    # 统一为无时区日历日，避免字符串/时分秒导致边界漂移。
    if getattr(day.dt, "tz", None) is not None:
        day = day.dt.tz_localize(None)
    out["day"] = day.dt.normalize()
    if out["day"].duplicated().any() and out.duplicated(["day", "hour"]).any():
        raise ValueError("panel 的 (day, hour) 主键重复")
    return out.sort_values(["day", "hour"], kind="stable").reset_index(drop=True)


def _model_name(model: object) -> str:
    """获取模型名称，优先使用协议要求的 ``name`` 属性。"""
    name = getattr(model, "name", None)
    return str(name) if name is not None else type(model).__name__


def _run_fold(
    panel: pd.DataFrame,
    model_factory: Callable[[], object],
    features: Sequence[str],
    train_cutoff: pd.Timestamp,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
) -> tuple[pd.DataFrame, Fold]:
    """训练并执行一个时间折。"""
    train = panel[(panel["day"] < train_cutoff) & panel["y"].notna()]
    test = panel[
        (panel["day"] >= test_start)
        & (panel["day"] <= test_end)
        & panel["y"].notna()
    ]
    if train.empty:
        raise ValueError(
            f"训练集为空: train_end < {train_cutoff.date()}，无法执行回测折"
        )
    if test.empty:
        raise ValueError(f"测试集为空: {test_start.date()}..{test_end.date()}")

    train_keys = set(zip(train["day"], train["hour"]))
    test_keys = set(zip(test["day"], test["hour"]))
    if train_keys.intersection(test_keys):
        raise AssertionError("训练集与测试集的 (day, hour) 发生重叠")

    model = model_factory()
    if model is None:
        raise ValueError("model_factory() 返回了 None")
    fitted = model.fit(train.loc[:, list(features)], train["y"])
    # 兼容返回 self 和就地 fit 返回 None 的实现；协议实现通常返回 self。
    if fitted is not None:
        model = fitted
    raw_pred = np.asarray(model.predict(test.loc[:, list(features)]), dtype=float)
    if raw_pred.ndim != 1:
        raw_pred = raw_pred.reshape(-1)
    if len(raw_pred) != len(test):
        raise ValueError(
            f"模型预测长度错误: got {len(raw_pred)}, expected {len(test)}"
        )
    if not np.isfinite(raw_pred).all():
        raise ValueError(f"模型 {_model_name(model)} 产生了 NaN/inf 预测")

    model_name = _model_name(model)
    pred = test.loc[:, ["day", "hour", "y"]].copy()
    pred["pred"] = raw_pred
    pred["model"] = model_name
    pred = pred.sort_values(["day", "hour"], kind="stable")

    fold = Fold(
        model=model_name,
        train_start=pd.Timestamp(train["day"].min()),
        train_end=pd.Timestamp(train["day"].max()),
        test_start=test_start,
        test_end=test_end,
        n_train=int(len(train)),
        n_test=int(len(test)),
    )
    if not fold.train_end < fold.test_start:
        raise AssertionError("train_end 必须严格早于 test_start")
    return pred, fold


def _result(predictions: list[pd.DataFrame], folds: list[Fold]) -> BacktestResult:
    """拼接各折结果并固定列顺序。"""
    if predictions:
        pred = pd.concat(predictions, ignore_index=True)
        pred = pred.loc[:, _PREDICTION_COLUMNS].sort_values(
            ["day", "hour"], kind="stable"
        ).reset_index(drop=True)
    else:  # 仅用于类型完整性；正常调用会在 _run_fold 中报空集
        pred = pd.DataFrame(columns=_PREDICTION_COLUMNS)
    if folds:
        fold_df = pd.DataFrame([f.__dict__ for f in folds], columns=_FOLD_COLUMNS)
    else:
        fold_df = pd.DataFrame(columns=_FOLD_COLUMNS)
    return BacktestResult(predictions=pred, folds=fold_df)


def monthly_walk_forward(
    panel: pd.DataFrame,
    model_factory: Callable[[], object],
    features: Iterable[str],
    start: object,
    end: object,
) -> BacktestResult:
    """按月滚动训练并预测，训练集严格截止于测试月首日之前。"""
    feature_list = list(features)
    frame = _prepare_panel(panel, feature_list)
    start_ts = _as_timestamp(start, "start")
    end_ts = _as_timestamp(end, "end")
    if start_ts > end_ts:
        raise ValueError("start 不能晚于 end")

    first_month = start_ts.to_period("M")
    last_month = end_ts.to_period("M")
    periods = pd.period_range(first_month, last_month, freq="M")
    predictions: list[pd.DataFrame] = []
    folds: list[Fold] = []
    for period in periods:
        month_start = period.start_time.normalize()
        month_end = period.end_time.normalize()
        test_start = max(start_ts, month_start)
        test_end = min(end_ts, month_end)
        pred, fold = _run_fold(
            frame,
            model_factory,
            feature_list,
            train_cutoff=month_start,
            test_start=test_start,
            test_end=test_end,
        )
        predictions.append(pred)
        folds.append(fold)
    return _result(predictions, folds)


def fixed_window(
    panel: pd.DataFrame,
    model_factory: Callable[[], object],
    features: Iterable[str],
    window_start: object,
    window_end: object,
) -> BacktestResult:
    """在一个固定日期窗口上训练一次并预测。"""
    feature_list = list(features)
    frame = _prepare_panel(panel, feature_list)
    start_ts = _as_timestamp(window_start, "window_start")
    end_ts = _as_timestamp(window_end, "window_end")
    if start_ts > end_ts:
        raise ValueError("window_start 不能晚于 window_end")
    pred, fold = _run_fold(
        frame,
        model_factory,
        feature_list,
        train_cutoff=start_ts,
        test_start=start_ts,
        test_end=end_ts,
    )
    return _result([pred], [fold])
