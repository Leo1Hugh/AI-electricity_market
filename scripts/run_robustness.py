#!/usr/bin/env python3
"""运行多窗口稳健性回测并生成候选对比与最终模型卡。"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from em.backtest.harness import BacktestResult, fixed_window, fixed_window_daily  # noqa: E402
from em.backtest.metrics import summarize_daily_rmse  # noqa: E402
from em.contracts import BASE_FEATURES, FEATURES, WINTER_WINDOWS  # noqa: E402
from em.ensemble import mean_ensemble, shrink_to_naive  # noqa: E402
from em.io import load_panel  # noqa: E402
from em.models.lgbm import LGBMModel  # noqa: E402
from em.models.mtlasso import MultiTaskLassoModel  # noqa: E402
from em.models.naive import NaiveD1  # noqa: E402
from em.models.ridge import RidgeModel  # noqa: E402


BASE_START = pd.Timestamp("2024-11-01")
BASE_END = pd.Timestamp("2026-10-31")
WINDOW_DAYS = 14
STEP_DAYS = 28
CRASH_THRESHOLD = 20.0
SHRINK_WEIGHTS: tuple[float, ...] = (0.5, 0.6, 0.7, 0.8)
BASE_CANDIDATES: tuple[str, ...] = ("naive_d1", "ridge", "lgbm", "mtlasso")


@dataclass(frozen=True)
class WindowSpec:
    """一个不重叠的 14 天评估窗口。"""

    start: pd.Timestamp
    end: pd.Timestamp

    @property
    def label(self) -> str:
        """返回稳定的窗口标签。"""
        return f"{self.start.date()}..{self.end.date()}"


@dataclass
class WindowRun:
    """一个窗口的基础预测、候选预测和排除日信息。"""

    window: WindowSpec
    candidates: dict[str, pd.DataFrame]
    metrics: pd.DataFrame
    excluded_days: list[pd.Timestamp]
    mtlasso_warnings: int


def generate_windows(
    start: object = BASE_START,
    end: object = BASE_END,
    *,
    window_days: int = WINDOW_DAYS,
    step_days: int = STEP_DAYS,
) -> list[WindowSpec]:
    """按固定步长生成不重叠窗口，最后一个窗口不得越过 ``end``。"""
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    if start_ts > end_ts:
        raise ValueError("start 不能晚于 end")
    if window_days <= 0 or step_days < window_days:
        raise ValueError("window_days 必须为正且 step_days 不得小于窗口长度")
    windows: list[WindowSpec] = []
    cursor = start_ts
    delta = pd.Timedelta(days=window_days - 1)
    step = pd.Timedelta(days=step_days)
    while cursor + delta <= end_ts:
        windows.append(WindowSpec(cursor, cursor + delta))
        cursor += step
    if not windows:
        raise ValueError("给定日期范围内没有完整窗口")
    for previous, current in zip(windows, windows[1:]):
        if current.start <= previous.end:
            raise AssertionError("稳健性窗口发生重叠")
        if current.start - previous.start != step:
            raise AssertionError("窗口步长不符合契约")
    return windows


def _normalise_prediction(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    """校验预测框并统一键、数值类型。"""
    required = {"day", "hour", "y", "pred", "model"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{name} 缺少列: {missing}")
    out = frame.loc[:, ["day", "hour", "y", "pred", "model"]].copy()
    out["day"] = pd.to_datetime(out["day"], errors="coerce").dt.normalize()
    out["hour"] = pd.to_numeric(out["hour"], errors="coerce")
    out["y"] = pd.to_numeric(out["y"], errors="coerce")
    out["pred"] = pd.to_numeric(out["pred"], errors="coerce")
    if out[["day", "hour", "y", "pred"]].isna().any().any():
        raise ValueError(f"{name} 含 NaN 或无效键")
    if not np.isfinite(out[["hour", "y", "pred"]].to_numpy(dtype=float)).all():
        raise ValueError(f"{name} 含 NaN/inf")
    if not np.equal(out["hour"].to_numpy(dtype=float), np.floor(out["hour"])).all():
        raise ValueError(f"{name}.hour 必须为整数")
    out["hour"] = out["hour"].astype(int)
    if out.duplicated(["day", "hour"]).any():
        raise ValueError(f"{name} 的 (day, hour) 键重复")
    return out.sort_values(["day", "hour"], kind="stable").reset_index(drop=True)


def common_key_predictions(
    predictions: Mapping[str, pd.DataFrame],
    *,
    expected_days: Iterable[object] | None = None,
) -> tuple[dict[str, pd.DataFrame], list[pd.Timestamp]]:
    """裁剪到所有预测共同的完整键，并返回被排除的日期。"""
    if not predictions:
        raise ValueError("predictions 不能为空")
    frames = {
        name: _normalise_prediction(frame, name) for name, frame in predictions.items()
    }
    key_sets = [set(zip(frame["day"], frame["hour"])) for frame in frames.values()]
    common_keys = set.intersection(*key_sets)
    if not common_keys:
        raise ValueError("预测没有共同 key set")
    raw_keys = pd.DataFrame(sorted(common_keys), columns=["day", "hour"])
    valid_days = set(
        raw_keys.groupby("day", sort=False)
        .filter(
            lambda group: len(group) == 24
            and set(group["hour"].astype(int)) == set(range(1, 25))
        )["day"]
    )
    common_keys = {
        (day, hour) for day, hour in common_keys if day in valid_days
    }
    if not common_keys:
        raise ValueError("预测没有共同的完整日 key set")
    common_days = {pd.Timestamp(day) for day, _ in common_keys}
    if expected_days is None:
        expected = sorted({pd.Timestamp(day) for frame in frames.values() for day in frame["day"]})
    else:
        expected = sorted({pd.Timestamp(day).normalize() for day in expected_days})
    excluded = [day for day in expected if day not in common_days]
    keys = pd.DataFrame(sorted(common_keys), columns=["day", "hour"])
    result: dict[str, pd.DataFrame] = {}
    for name, frame in frames.items():
        subset = frame.merge(keys, on=["day", "hour"], how="inner", validate="one_to_one")
        subset = subset.sort_values(["day", "hour"], kind="stable").reset_index(drop=True)
        if len(subset) != len(keys):
            raise AssertionError(f"{name} 未覆盖共同 key set")
        counts = subset.groupby("day", sort=False).size()
        if not counts.eq(24).all():
            raise AssertionError(f"{name} 的共同 key set 含非完整日")
        result[name] = subset
    return result, excluded


def build_candidates(
    base: Mapping[str, pd.DataFrame],
    *,
    weights: Sequence[float] = SHRINK_WEIGHTS,
) -> dict[str, pd.DataFrame]:
    """从统一 key set 的四个基础预测生成所有候选。"""
    required = set(BASE_CANDIDATES)
    missing = sorted(required.difference(base))
    if missing:
        raise ValueError(f"基础预测缺少模型: {missing}")
    frames = {name: _normalise_prediction(frame, name) for name, frame in base.items()}
    naive = frames["naive_d1"]
    ridge = frames["ridge"]
    lgbm = frames["lgbm"]
    mtlasso = frames["mtlasso"]
    candidates: dict[str, pd.DataFrame] = {
        "naive_d1": naive,
        "ridge": ridge,
        "lgbm": lgbm,
        "mtlasso": mtlasso,
        "mean2": mean_ensemble([ridge, lgbm], name="mean2"),
        "mean3": mean_ensemble([ridge, lgbm, mtlasso], name="mean3"),
    }
    for weight in weights:
        label = f"{float(weight):g}"
        candidates[f"shrink2_{label}"] = shrink_to_naive(
            candidates["mean2"], naive, weight=float(weight), name=f"shrink2_{label}"
        )
        candidates[f"shrink3_{label}"] = shrink_to_naive(
            candidates["mean3"], naive, weight=float(weight), name=f"shrink3_{label}"
        )
    return candidates


def daily_metrics(
    prediction: pd.DataFrame,
    *,
    crash_threshold: float = CRASH_THRESHOLD,
) -> dict[str, object]:
    """按日计算 RMSE 汇总，口径为 24 点日 RMSE。"""
    frame = _normalise_prediction(prediction, "prediction")
    rows: list[float] = []
    for _, group in frame.groupby("day", sort=True):
        if len(group) != 24:
            raise ValueError("daily_metrics 要求每个日期恰好 24 行")
        y = group["y"].to_numpy(dtype=float)
        pred = group["pred"].to_numpy(dtype=float)
        rows.append(float(np.sqrt(np.mean((y - pred) ** 2))))
    return summarize_daily_rmse(np.asarray(rows, dtype=float), crash_threshold=crash_threshold)


def _window_metric_row(
    window: WindowSpec,
    candidate: str,
    prediction: pd.DataFrame | None,
    excluded_days: Sequence[pd.Timestamp],
    *,
    warning_count: int = 0,
    status: str = "ok",
) -> dict[str, object]:
    """构造窗口级指标行。"""
    worst_day = ""
    if prediction is None:
        summary = {"n_days": 0, "mean": np.nan, "median": np.nan, "max": np.nan, "p90": np.nan, "crash_days": 0, "crash_rate": np.nan}
    else:
        normalised = _normalise_prediction(prediction, "prediction")
        daily_values = normalised.groupby("day", sort=True).apply(
            lambda group: float(np.sqrt(np.mean((group["y"].to_numpy(dtype=float) - group["pred"].to_numpy(dtype=float)) ** 2)))
        )
        worst_day = str(pd.Timestamp(daily_values.idxmax()).date())
        summary = summarize_daily_rmse(daily_values.to_numpy(dtype=float), crash_threshold=CRASH_THRESHOLD)
    return {
        "window": window.label,
        "window_start": window.start,
        "window_end": window.end,
        "candidate": candidate,
        "status": status,
        "n_days": summary["n_days"],
        "excluded_days": len(excluded_days),
        "worst_day": worst_day,
        "mean": summary["mean"],
        "median": summary["median"],
        "max": summary["max"],
        "p90": summary["p90"],
        "crash_days": summary["crash_days"],
        "crash_rate": summary["crash_rate"],
        "mtlasso_convergence_warnings": warning_count,
    }


def aggregate_window_metrics(window_metrics: pd.DataFrame) -> pd.DataFrame:
    """聚合窗口级指标，保留可由窗口数据独立重算的列。"""
    window_metrics = window_metrics.copy()
    if "crash_rate" not in window_metrics.columns:
        window_metrics["crash_rate"] = np.where(
            window_metrics["n_days"].to_numpy(dtype=float) > 0,
            window_metrics["crash_days"].to_numpy(dtype=float)
            / window_metrics["n_days"].to_numpy(dtype=float),
            np.nan,
        )
    if "mtlasso_convergence_warnings" not in window_metrics.columns:
        window_metrics["mtlasso_convergence_warnings"] = 0
    required = {"candidate", "status", "mean", "max", "p90", "crash_days", "n_days"}
    missing = sorted(required.difference(window_metrics.columns))
    if missing:
        raise ValueError(f"window_metrics 缺少列: {missing}")
    rows: list[dict[str, object]] = []
    for candidate, group in window_metrics.groupby("candidate", sort=True):
        valid = group[(group["status"] == "ok") & np.isfinite(group["mean"].to_numpy(dtype=float))]
        if valid.empty:
            rows.append({
                "candidate": candidate,
                "status": "未运行",
                "n_windows": 0,
                "n_days": 0,
                "window_mean_mean": np.nan,
                "window_mean_median": np.nan,
                "worst_window_mean": np.nan,
                "window_mean_p90": np.nan,
                "single_day_max": np.nan,
                "single_day_max_p90": np.nan,
                "crash_windows": 0,
                "mean_crash_rate": np.nan,
                "convergence_warnings": int(group["mtlasso_convergence_warnings"].sum()),
            })
            continue
        window_means = valid["mean"].to_numpy(dtype=float)
        maxima = valid["max"].to_numpy(dtype=float)
        crashes = valid["crash_days"].to_numpy(dtype=float)
        rows.append({
            "candidate": candidate,
            "status": "ok" if len(valid) == len(group) else "部分运行",
            "n_windows": int(len(valid)),
            "n_days": int(valid["n_days"].sum()),
            "window_mean_mean": float(np.mean(window_means)),
            "window_mean_median": float(np.median(window_means)),
            "worst_window_mean": float(np.max(window_means)),
            "window_mean_p90": float(np.percentile(window_means, 90)),
            "single_day_max": float(np.max(maxima)),
            "single_day_max_p90": float(np.percentile(maxima, 90)),
            "crash_windows": int(np.count_nonzero(crashes > 0)),
            "mean_crash_rate": float(np.average(valid["crash_rate"], weights=valid["n_days"])) if valid["n_days"].sum() else np.nan,
            "convergence_warnings": int(group["mtlasso_convergence_warnings"].sum()),
        })
    return pd.DataFrame(rows)


def _complexity(candidate: str) -> tuple[int, float]:
    """返回候选复杂度和收缩权重，用于接近时的保守 tie-break。"""
    if candidate == "naive_d1":
        return (0, 0.0)
    if candidate in {"ridge", "lgbm", "mtlasso"}:
        return (1, 0.0)
    if candidate == "mean2":
        return (2, 0.0)
    if candidate == "mean3":
        return (3, 0.0)
    if candidate.startswith("shrink2_"):
        return (2, float(candidate.split("_", 1)[1]))
    if candidate.startswith("shrink3_"):
        return (3, float(candidate.split("_", 1)[1]))
    return (99, 0.0)


def choose_final_candidate(summary: pd.DataFrame) -> str:
    """按最差窗口/最差日/崩盘优先规则选择一个候选。"""
    required = {"candidate", "status", "worst_window_mean", "single_day_max", "crash_windows", "window_mean_mean", "window_mean_p90"}
    missing = sorted(required.difference(summary.columns))
    if missing:
        raise ValueError(f"summary 缺少列: {missing}")
    eligible = summary[(summary["status"] == "ok") & np.isfinite(summary["worst_window_mean"].to_numpy(dtype=float))].copy()
    if eligible.empty:
        raise ValueError("没有可选择的完整运行候选")
    eligible = eligible.sort_values(
        ["crash_windows", "worst_window_mean", "single_day_max", "window_mean_mean", "window_mean_p90", "candidate"],
        kind="stable",
    )
    best = eligible.iloc[0]
    close = eligible[
        (eligible["worst_window_mean"] - float(best["worst_window_mean"])).abs() < 0.1
    ]
    if len(close) > 1:
        close = close.assign(_complexity=close["candidate"].map(lambda value: _complexity(str(value))))
        close = close.sort_values(["_complexity", "candidate"], kind="stable")
        return str(close.iloc[0]["candidate"])
    return str(best["candidate"])


def _row_factory(candidate: str) -> Callable[[], object]:
    """返回逐行模型工厂。"""
    factories: dict[str, Callable[[], object]] = {
        "naive_d1": NaiveD1,
        "ridge": RidgeModel,
        "lgbm": LGBMModel,
    }
    return factories[candidate]


def run_window(
    panel: pd.DataFrame,
    window: WindowSpec,
    features: Sequence[str],
    *,
    run_mtlasso: bool = True,
    mtlasso_alpha: float = 0.1,
    mtlasso_max_iter: int = 20000,
) -> WindowRun:
    """运行一个窗口的基础模型、统一 key set 和全部候选。"""
    raw: dict[str, pd.DataFrame] = {}
    for name in ("naive_d1", "ridge", "lgbm"):
        result = fixed_window(panel, _row_factory(name), features, window.start, window.end)
        raw[name] = result.predictions
    warnings_count = 0
    if run_mtlasso:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ConvergenceWarning)
            result_daily = fixed_window_daily(
                panel,
                lambda: MultiTaskLassoModel(alpha=mtlasso_alpha, max_iter=mtlasso_max_iter),
                features,
                window.start,
                window.end,
            )
        warnings_count = sum(issubclass(item.category, ConvergenceWarning) for item in caught)
        raw["mtlasso"] = result_daily.predictions
    expected_days = pd.date_range(window.start, window.end, freq="D")
    if run_mtlasso:
        common, excluded = common_key_predictions(raw, expected_days=expected_days)
        candidates = build_candidates(common)
        metrics = pd.DataFrame([
            _window_metric_row(
                window,
                name,
                frame,
                excluded,
                warning_count=warnings_count if name == "mtlasso" else 0,
            )
            for name, frame in candidates.items()
        ])
    else:
        common, excluded = common_key_predictions(raw, expected_days=expected_days)
        candidates = {
            name: frame for name, frame in build_candidates({**common, "mtlasso": common["naive_d1"]}).items()
            if name in {"naive_d1", "ridge", "lgbm", "mean2"} or name.startswith("shrink2_")
        }
        metrics_rows = [
            _window_metric_row(window, name, frame, excluded)
            for name, frame in candidates.items()
        ]
        for name in ("mtlasso", "mean3", *(f"shrink3_{float(weight):g}" for weight in SHRINK_WEIGHTS)):
            metrics_rows.append(_window_metric_row(window, name, None, excluded, status="未运行"))
        metrics = pd.DataFrame(metrics_rows)
    return WindowRun(window, candidates, metrics, excluded, warnings_count)


def run_mtlasso_grid(
    panel: pd.DataFrame,
    features: Sequence[str],
    *,
    alphas: Sequence[float] = (0.03, 0.1, 0.3),
    max_iter: int = 20000,
) -> pd.DataFrame:
    """在两个历史冬季窗口上记录 MTLasso 小网格和收敛警告。"""
    rows: list[dict[str, object]] = []
    for window_start, window_end in WINTER_WINDOWS:
        window = WindowSpec(pd.Timestamp(window_start), pd.Timestamp(window_end))
        for alpha in alphas:
            warning_count = 0
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", ConvergenceWarning)
                    result = fixed_window_daily(
                        panel,
                        lambda alpha=float(alpha): MultiTaskLassoModel(
                            alpha=alpha, max_iter=max_iter
                        ),
                        features,
                        window.start,
                        window.end,
                    )
                warning_count = sum(
                    issubclass(item.category, ConvergenceWarning) for item in caught
                )
                metric = daily_metrics(result.predictions)
                rows.append(
                    {
                        "window": window.label,
                        "alpha": float(alpha),
                        "status": "ok",
                        **metric,
                        "convergence_warnings": warning_count,
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "window": window.label,
                        "alpha": float(alpha),
                        "status": f"失败: {exc}",
                        "n_days": 0,
                        "mean": np.nan,
                        "median": np.nan,
                        "max": np.nan,
                        "p90": np.nan,
                        "crash_days": 0,
                        "crash_rate": np.nan,
                        "convergence_warnings": warning_count,
                    }
                )
    return pd.DataFrame(rows)


def _candidate_order() -> list[str]:
    """返回报告中的稳定候选顺序。"""
    return [
        "naive_d1",
        "ridge",
        "lgbm",
        "mtlasso",
        "mean2",
        "mean3",
        *(f"shrink2_{float(weight):g}" for weight in SHRINK_WEIGHTS),
        *(f"shrink3_{float(weight):g}" for weight in SHRINK_WEIGHTS),
    ]


def _write_reports(
    output_dir: Path,
    windows: Sequence[WindowSpec],
    window_metrics: pd.DataFrame,
    summary: pd.DataFrame,
    selected: str,
    *,
    features: Sequence[str],
) -> tuple[Path, Path]:
    """写出稳健性报告和最终模型卡。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_order = _candidate_order()
    summary_ordered = summary.set_index("candidate").reindex(candidate_order).reset_index()
    summary_ordered.to_csv(output_dir / "summary.csv", index=False)
    lines = [
        "# W2-R3 稳健性报告",
        "",
        "所有窗口均从 `day < window_start` 的历史数据训练，测试窗口为连续 14 个日历日；指标为逐日 24 点 RMSE。",
        "",
        f"窗口范围：{windows[0].start.date()} 至 {windows[-1].end.date()}，共 {len(windows)} 个不重叠窗口。",
        f"所有候选使用同一个完整日 key set；本次每窗口排除日数合计 {int(window_metrics.groupby('window')['excluded_days'].first().sum())}，逐窗口数值见 `window_metrics.csv`。",
        "",
        "## 跨窗口汇总（[已验证-计算]）",
        "",
        "| candidate | n_windows | mean(window mean) | median(window mean) | worst window mean | window mean p90 | max(single-day max) | p90(single-day max) | crash windows | status |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for _, row in summary_ordered.iterrows():
        if pd.isna(row["window_mean_mean"]):
            lines.append(f"| {row['candidate']} | 0 | 未运行 | 未运行 | 未运行 | 未运行 | 未运行 | 未运行 | 0 | {row['status']} |")
            continue
        lines.append(
            f"| {row['candidate']} | {int(row['n_windows'])} | {row['window_mean_mean']:.6g} | "
            f"{row['window_mean_median']:.6g} | {row['worst_window_mean']:.6g} | {row['window_mean_p90']:.6g} | "
            f"{row['single_day_max']:.6g} | {row['single_day_max_p90']:.6g} | {int(row['crash_windows'])} | {row['status']} |"
        )
    lines.extend(["", "## 最差窗口", ""])
    for candidate in candidate_order:
        group = window_metrics[(window_metrics["candidate"] == candidate) & (window_metrics["status"] == "ok")]
        if group.empty:
            lines.append(f"- `{candidate}`：未运行。")
            continue
        worst = group.loc[group["mean"].idxmax()]
        max_day = group.loc[group["max"].idxmax()]
        lines.append(
            f"- `{candidate}`：最差窗口 `{worst['window']}` mean={worst['mean']:.6g}；"
            f"窗口内最大日 RMSE={max_day['max']:.6g}（{max_day['worst_day']}，窗口 {max_day['window']}）。"
        )
    lines.extend(["", f"选择候选：`{selected}`（选择规则见模型卡）。", ""])
    report_text = "\n".join(lines)
    report_path = output_dir / "robustness_report.md"
    report_path.write_text(report_text, encoding="utf-8")

    selected_row = summary_ordered.loc[summary_ordered["candidate"] == selected].iloc[0]
    selected_window_metrics = window_metrics[
        (window_metrics["candidate"] == selected) & (window_metrics["status"] == "ok")
    ]
    selected_worst_day = selected_window_metrics.loc[
        selected_window_metrics["max"].idxmax(), "worst_day"
    ]
    card_lines = [
        "# W2-R3 最终模型卡",
        "",
        f"最终候选：**`{selected}`**。该选择基于 2024-11-01 至 2026-10-31 的历史窗口，未使用比赛窗口 2026-11-23 至 2026-12-06。",
        "",
        "## 配置",
        "",
        f"- 特征集：`{len(features)}` 列（默认 BASE_FEATURES）。",
        "- 训练截止：每个评估窗口严格使用 `day < window_start` 的数据；部署时沿用同一截止规则。",
        "- 预测口径：每个测试日 24 点，价格单位 USD/MWh。",
        "- MTLasso 小网格：alpha ∈ {0.03, 0.1, 0.3}，max_iter=20000；两个历史冬季窗口的结果与 ConvergenceWarning 计数见 `mtlasso_grid.csv`。",
        "- Naive fallback：`NaiveD1` 依次回退 `p_lag2`、`p_lagmean7`、`p_lag7`；仍无有限值则报错。",
        "",
        "## 跨窗口指标（[已验证-计算]）",
        "",
        f"- 窗口数：{int(selected_row['n_windows'])}；窗口 mean 的均值/中位数：{selected_row['window_mean_mean']:.6g} / {selected_row['window_mean_median']:.6g}。",
        f"- 最差窗口 mean：{selected_row['worst_window_mean']:.6g}；窗口 mean p90：{selected_row['window_mean_p90']:.6g}。",
        f"- 单日 max 的最大值/p90：{selected_row['single_day_max']:.6g} / {selected_row['single_day_max_p90']:.6g}。",
        f"- 最差单日：{selected_worst_day}（RMSE={selected_row['single_day_max']:.6g}）。",
        f"- 崩盘窗口数（窗口内任一天 RMSE > {CRASH_THRESHOLD:g}）：{int(selected_row['crash_windows'])}。",
        "",
        "## 选择理由",
        "",
        "选择顺序为：先比较崩盘窗口数、最差窗口 mean 和最差单日，再比较跨窗口 mean 与 p90；若关键指标差异小于 0.1，选择更简单且更偏向 naive 的候选。",
        f"本轮最终选中 `{selected}`；其余候选的逐窗口数据和排除日数见 `window_metrics.csv`。",
        "",
        "## 已知风险（[解读-未验证]）",
        "",
        "- 每个窗口只有 14 个测试日，跨窗口统计仍可能受少数尖峰影响。",
        "- MTLasso 对 alpha、标准化和收敛条件敏感；报告记录了 ConvergenceWarning 次数。",
        "- SP15 历史数据存在事后修订，且假日和极端价格会放大窗口间波动。",
        "",
    ]
    card_path = output_dir / "final_model_card.md"
    card_path.write_text("\n".join(card_lines), encoding="utf-8")
    root_reports = _ROOT / "reports"
    if output_dir.resolve() != root_reports.resolve():
        (root_reports / "robustness_report.md").write_text(report_text, encoding="utf-8")
        (root_reports / "final_model_card.md").write_text("\n".join(card_lines), encoding="utf-8")
    return report_path, card_path


def run_robustness(
    panel: pd.DataFrame,
    output_dir: str | Path,
    *,
    features: Sequence[str] = BASE_FEATURES,
    start: object = BASE_START,
    end: object = BASE_END,
    run_mtlasso_all: bool = True,
) -> dict[str, object]:
    """运行全部稳健性窗口并写出机器可读与 Markdown 产物。"""
    windows = generate_windows(start, end)
    if len(windows) < 20:
        raise AssertionError(f"窗口数量不足 20: {len(windows)}")
    output_path = Path(output_dir)
    mtlasso_grid = run_mtlasso_grid(panel, list(features))
    output_path.mkdir(parents=True, exist_ok=True)
    mtlasso_grid.to_csv(output_path / "mtlasso_grid.csv", index=False)
    runs: list[WindowRun] = []
    all_predictions: list[pd.DataFrame] = []
    for index, window in enumerate(windows):
        run_mtlasso = run_mtlasso_all or index in {0, 1, 5, 10, 15, 20, 25}
        result = run_window(panel, window, list(features), run_mtlasso=run_mtlasso)
        runs.append(result)
        for candidate, prediction in result.candidates.items():
            frame = prediction.copy()
            frame.insert(0, "window", window.label)
            frame.insert(1, "candidate", candidate)
            all_predictions.append(frame)
    window_metrics = pd.concat([run.metrics for run in runs], ignore_index=True)
    window_metrics.to_csv(output_path / "window_metrics.csv", index=False)
    if all_predictions:
        pd.concat(all_predictions, ignore_index=True).to_csv(output_path / "predictions.csv", index=False)
    summary = aggregate_window_metrics(window_metrics)
    selected = choose_final_candidate(summary)
    summary.to_json(output_path / "summary.json", orient="records", force_ascii=False, indent=2)
    metrics_payload = {
        "n_windows": len(windows),
        "window_start": str(windows[0].start.date()),
        "window_end": str(windows[-1].end.date()),
        "selected": selected,
        "candidates": summary.replace({np.nan: None}).to_dict(orient="records"),
        "mtlasso_grid": mtlasso_grid.replace({np.nan: None}).to_dict(orient="records"),
    }
    (output_path / "metrics.json").write_text(json.dumps(metrics_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path, card_path = _write_reports(output_path, windows, window_metrics, summary, selected, features=list(features))
    return {
        "windows": windows,
        "window_metrics": window_metrics,
        "summary": summary,
        "selected": selected,
        "report": report_path,
        "model_card": card_path,
        "mtlasso_grid": mtlasso_grid,
    }


def _parse_features(value: str) -> list[str]:
    """解析 base、all 或显式特征列。"""
    key = value.strip().lower()
    if key == "base":
        return list(BASE_FEATURES)
    if key == "all":
        return list(FEATURES)
    columns = [part.strip() for part in value.split(",") if part.strip()]
    if not columns or any(column not in FEATURES for column in columns):
        raise ValueError("--features 含未知列或为空")
    if len(set(columns)) != len(columns):
        raise ValueError("--features 不应包含重复列")
    return columns


def build_parser() -> argparse.ArgumentParser:
    """构建稳健性 CLI。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", required=True, help="panel.csv.gz 路径")
    parser.add_argument("--out", required=True, help="稳健性产物目录")
    parser.add_argument("--features", default="base", help="base、all 或显式列名")
    parser.add_argument("--sample-mtlasso", action="store_true", help="仅运行允许的 MTLasso 抽样窗口")
    return parser


def main(argv: list[str] | None = None) -> int:
    """运行 CLI，失败时打印原因并返回非零。"""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        panel_path = Path(args.panel)
        if not panel_path.exists():
            raise FileNotFoundError(f"panel 文件不存在: {panel_path}")
        panel = load_panel(panel_path)
        if panel.empty:
            raise ValueError("panel 为空")
        result = run_robustness(
            panel,
            args.out,
            features=_parse_features(args.features),
            run_mtlasso_all=not args.sample_mtlasso,
        )
        print(result["selected"])
        print(result["report"])
        print(result["model_card"])
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
