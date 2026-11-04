#!/usr/bin/env python3
"""在年度和历史冬季窗口比较四个模型及三种集成。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import reduce
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from em.backtest.harness import (  # noqa: E402
    BacktestResult,
    fixed_window,
    fixed_window_daily,
    monthly_walk_forward,
    monthly_walk_forward_daily,
)
from em.backtest.metrics import summarize_daily_rmse  # noqa: E402
from em.contracts import (  # noqa: E402
    ANNUAL_BACKTEST_END,
    ANNUAL_BACKTEST_START,
    BASE_FEATURES,
    FEATURES,
    WINTER_WINDOWS,
)
from em.ensemble import mean_ensemble, shrink_to_naive  # noqa: E402
from em.io import load_panel  # noqa: E402
from em.models.lgbm import LGBMModel  # noqa: E402
from em.models.mtlasso import MultiTaskLassoModel  # noqa: E402
from em.models.naive import NaiveD1  # noqa: E402
from em.models.ridge import RidgeModel  # noqa: E402


@dataclass
class _Record:
    """一个模型在一个窗口上的预测和折信息。"""

    model: str
    window: str
    result: BacktestResult


ROW_FACTORIES: dict[str, Callable[[], object]] = {
    "naive_d1": NaiveD1,
    "ridge": RidgeModel,
    "lgbm": LGBMModel,
}


def _daily_factory() -> MultiTaskLassoModel:
    """创建日级模型；固定参数保证 CLI 可复现。"""
    return MultiTaskLassoModel(alpha=0.1, max_iter=5000)


def _parse_features(value: str) -> list[str]:
    """解析 base、all 或显式特征列。"""
    key = value.strip().lower()
    if key == "base":
        return list(BASE_FEATURES)
    if key == "all":
        return list(FEATURES)
    columns = [part.strip() for part in value.split(",") if part.strip()]
    if not columns:
        raise ValueError("--features 不能为空")
    unknown = [column for column in columns if column not in FEATURES]
    if unknown:
        raise ValueError(f"未知特征列: {unknown}")
    if len(set(columns)) != len(columns):
        raise ValueError("--features 不应包含重复列")
    return columns


def _run_model(
    panel: pd.DataFrame,
    model: str,
    features: list[str],
    mode: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> list[_Record]:
    """运行一个基础模型并返回一个或两个窗口的结果。"""
    if model in ROW_FACTORIES:
        factory = ROW_FACTORIES[model]
        runner = monthly_walk_forward if mode == "annual" else fixed_window
    elif model == "mtlasso":
        factory = _daily_factory
        runner = monthly_walk_forward_daily if mode == "annual" else fixed_window_daily
    else:
        raise ValueError(f"未知模型: {model}")
    if mode == "annual":
        result = runner(
            panel,
            factory,
            features,
            start or ANNUAL_BACKTEST_START,
            end or ANNUAL_BACKTEST_END,
        )
        return [_Record(model, "annual", result)]
    if mode == "winter":
        records: list[_Record] = []
        for window_start, window_end in WINTER_WINDOWS:
            result = runner(panel, factory, features, window_start, window_end)
            label = f"{window_start.date()}..{window_end.date()}"
            records.append(_Record(model, label, result))
        return records
    raise ValueError(f"未知 mode: {mode}")


def _common_key_frames(frames: Iterable[pd.DataFrame]) -> list[pd.DataFrame]:
    """将基础预测裁到所有模型共有的键，供严格集成使用。"""
    items = [frame.copy() for frame in frames]
    if not items:
        raise ValueError("没有预测可供集成")
    key_sets = [set(zip(frame["day"], frame["hour"])) for frame in items]
    common = reduce(set.intersection, key_sets)
    if not common:
        raise ValueError("四个模型没有共同的测试键")
    keys = pd.DataFrame(sorted(common), columns=["day", "hour"])
    out: list[pd.DataFrame] = []
    for frame in items:
        subset = frame.merge(keys, on=["day", "hour"], how="inner", validate="one_to_one")
        subset = subset.sort_values(["day", "hour"], kind="stable").reset_index(drop=True)
        if len(subset) != len(keys):
            raise ValueError("模型预测键裁剪失败")
        out.append(subset)
    return out


def _integrate(records: list[_Record]) -> list[_Record]:
    """对一个窗口的四个基础结果构建 mean2、mean3、shrink。"""
    by_name = {record.model: record for record in records}
    required = ["naive_d1", "ridge", "lgbm", "mtlasso"]
    missing = [name for name in required if name not in by_name]
    if missing:
        raise ValueError(f"集成缺少基础模型: {missing}")
    naive_raw = by_name["naive_d1"].result.predictions
    ridge_raw = by_name["ridge"].result.predictions
    lgbm_raw = by_name["lgbm"].result.predictions
    mtlasso_raw = by_name["mtlasso"].result.predictions
    # mean2 does not depend on MTLasso and therefore retains every key shared
    # by Ridge/LightGBM, including a spring missing-hour day.  mean3 and its
    # shrink variant require the stricter common set of all four models.
    ridge2, lgbm2 = _common_key_frames([ridge_raw, lgbm_raw])
    mean2 = mean_ensemble([ridge2, lgbm2], name="mean2")
    naive, ridge, lgbm, mtlasso = _common_key_frames(
        [naive_raw, ridge_raw, lgbm_raw, mtlasso_raw]
    )
    mean3 = mean_ensemble([ridge, lgbm, mtlasso], name="mean3")
    shrunk = shrink_to_naive(mean3, naive, weight=0.7, name="shrink")
    template = by_name["ridge"].result.folds.copy()

    def result_for(frame: pd.DataFrame, name: str) -> _Record:
        folds = template.copy()
        folds["model"] = name
        return _Record(name, by_name["ridge"].window, BacktestResult(frame, folds))

    return [result_for(mean2, "mean2"), result_for(mean3, "mean3"), result_for(shrunk, "shrink")]


def _run_all(
    panel: pd.DataFrame,
    features: list[str],
    mode: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> list[_Record]:
    """运行四个基础模型和三种集成。"""
    records: list[_Record] = []
    for model in ("naive_d1", "ridge", "lgbm", "mtlasso"):
        records.extend(_run_model(panel, model, features, mode, start, end))
    integrated: list[_Record] = []
    for window in sorted({record.window for record in records}):
        integrated.extend(_integrate([record for record in records if record.window == window]))
    return records + integrated


def _daily_metrics(record: _Record) -> pd.DataFrame:
    """从逐小时预测计算逐日 24 点 RMSE。"""
    rows: list[dict[str, object]] = []
    for day, group in record.result.predictions.groupby("day", sort=True):
        y = pd.to_numeric(group["y"], errors="coerce").to_numpy(dtype=float)
        pred = pd.to_numeric(group["pred"], errors="coerce").to_numpy(dtype=float)
        valid = np.isfinite(y) & np.isfinite(pred)
        rmse = float(np.sqrt(np.mean((y[valid] - pred[valid]) ** 2))) if valid.any() else float("nan")
        rows.append({"window": record.window, "day": pd.Timestamp(day), "model": record.model, "rmse": rmse})
    return pd.DataFrame(rows, columns=["window", "day", "model", "rmse"])


def _write_outputs(out_root: Path, mode: str, records: list[_Record], features: list[str]) -> Path:
    """写出 predictions、daily_metrics、folds、metrics 和 summary 五件产物。"""
    if not records:
        raise ValueError("没有产生任何预测")
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    out_dir = out_root / f"{stamp}-compare"
    out_dir.mkdir(parents=True, exist_ok=False)
    prediction_frames = []
    fold_frames = []
    daily_frames = []
    summaries: dict[str, dict[str, dict[str, object]]] = {}
    for record in records:
        pred = record.result.predictions.loc[:, ["day", "hour", "y", "pred", "model"]].copy()
        prediction_frames.append(pred)
        fold = record.result.folds.copy()
        fold["window"] = record.window
        fold_frames.append(fold)
        daily = _daily_metrics(record)
        daily_frames.append(daily)
        values = daily["rmse"].to_numpy(dtype=float)
        summaries.setdefault(record.window, {})[record.model] = summarize_daily_rmse(values)
    pd.concat(prediction_frames, ignore_index=True).sort_values(
        ["model", "day", "hour"], kind="stable"
    ).to_csv(out_dir / "predictions.csv", index=False)
    pd.concat(daily_frames, ignore_index=True).sort_values(
        ["window", "model", "day"], kind="stable"
    ).to_csv(out_dir / "daily_metrics.csv", index=False)
    fold_output = pd.concat(fold_frames, ignore_index=True)
    fold_columns = [
        "model",
        "train_start",
        "train_end",
        "test_start",
        "test_end",
        "n_train",
        "n_test",
    ]
    # Keep the BacktestResult contract stable; the window label remains in
    # daily_metrics.csv and summary.md for winter-mode separation.
    fold_output.loc[:, fold_columns].to_csv(out_dir / "folds.csv", index=False)
    model_payload: dict[str, object]
    if mode == "annual" and "annual" in summaries:
        model_payload = summaries["annual"]
    else:
        model_payload = summaries
    payload = {"run_id": out_dir.name, "mode": mode, "features": features, "models": model_payload}
    (out_dir / "metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=True) + "\n", encoding="utf-8"
    )
    lines = [
        f"# Model comparison {out_dir.name}",
        "",
        f"mode: `{mode}`; metrics are mean daily 24-hour RMSE (USD/MWh)",
        "",
        "| window | model | mean | median | max | p90 | crash_rate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for window in sorted(summaries):
        for model in ("naive_d1", "ridge", "lgbm", "mtlasso", "mean2", "mean3", "shrink"):
            if model not in summaries[window]:
                continue
            summary = summaries[window][model]
            lines.append(
                f"| {window} | {model} | {summary['mean']:.6g} | {summary['median']:.6g} | "
                f"{summary['max']:.6g} | {summary['p90']:.6g} | {summary['crash_rate']:.6g} |"
            )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_dir


def build_parser() -> argparse.ArgumentParser:
    """构建比较 CLI。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", required=True, help="panel.csv.gz 路径")
    parser.add_argument("--mode", choices=("annual", "winter"), required=True)
    parser.add_argument("--out", default="reports/backtests", help="输出目录")
    parser.add_argument("--features", default="base", help="base、all 或逗号分隔特征")
    parser.add_argument("--start", help="可选的年度起始日")
    parser.add_argument("--end", help="可选的年度结束日")
    return parser


def main(argv: list[str] | None = None) -> int:
    """运行比较；错误打印到 stderr 并返回非零。"""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        path = Path(args.panel)
        if not path.exists():
            raise FileNotFoundError(f"panel 文件不存在: {path}")
        panel = load_panel(path)
        if panel.empty:
            raise ValueError("panel 为空")
        features = _parse_features(args.features)
        start = pd.Timestamp(args.start) if args.start else None
        end = pd.Timestamp(args.end) if args.end else None
        if (start is None) != (end is None):
            raise ValueError("--start 和 --end 必须同时提供")
        records = _run_all(panel, features, args.mode, start, end)
        for record in records:
            if record.result.predictions.empty:
                raise ValueError(f"{record.model} 产生空预测")
            if not np.isfinite(record.result.predictions["pred"].to_numpy(dtype=float)).all():
                raise ValueError(f"{record.model} 预测含 NaN/inf")
        out_dir = _write_outputs(Path(args.out), args.mode, records, features)
        print(out_dir)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
