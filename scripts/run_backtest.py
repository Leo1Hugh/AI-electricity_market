#!/usr/bin/env python3
"""运行 W2 回测并写出可复现的报告产物。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from em.backtest.harness import BacktestResult, fixed_window, monthly_walk_forward
from em.backtest.metrics import summarize_daily_rmse
from em.contracts import (
    ANNUAL_BACKTEST_END,
    ANNUAL_BACKTEST_START,
    BASE_FEATURES,
    FEATURES,
    WINTER_WINDOWS,
)
from em.io import load_panel
from em.models import LGBMModel, NaiveD1, NaiveD7, NaiveMean7, RidgeModel


MODEL_FACTORIES: dict[str, Callable[[], object]] = {
    "naive_d1": NaiveD1,
    "naive_d7": NaiveD7,
    "naive_mean7": NaiveMean7,
    "ridge": RidgeModel,
    "lgbm": LGBMModel,
}


def _parse_models(value: str) -> list[str]:
    """解析模型名列表并拒绝未知模型。"""
    names = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not names:
        raise ValueError("--models 不能为空")
    unknown = [name for name in names if name not in MODEL_FACTORIES]
    if unknown:
        raise ValueError(f"未知模型: {unknown}; 可选值: {sorted(MODEL_FACTORIES)}")
    if len(set(names)) != len(names):
        raise ValueError("--models 不应包含重复模型")
    return names


def _parse_features(value: str) -> list[str]:
    """解析 base、all 或逗号分隔的列名。"""
    key = value.strip().lower()
    if key == "base":
        return list(BASE_FEATURES)
    if key == "all":
        return list(FEATURES)
    columns = [item.strip() for item in value.split(",") if item.strip()]
    if not columns:
        raise ValueError("--features 不能为空")
    unknown = [column for column in columns if column not in FEATURES]
    if unknown:
        raise ValueError(f"未知特征列: {unknown}")
    if len(set(columns)) != len(columns):
        raise ValueError("--features 不应包含重复列")
    return columns


def _daily_metrics(result: BacktestResult) -> pd.DataFrame:
    """从逐小时预测按日计算 RMSE。"""
    rows: list[dict[str, object]] = []
    for (model, day), group in result.predictions.groupby(["model", "day"], sort=True):
        y = pd.to_numeric(group["y"], errors="coerce").to_numpy(dtype=float)
        pred = pd.to_numeric(group["pred"], errors="coerce").to_numpy(dtype=float)
        valid = np.isfinite(y) & np.isfinite(pred)
        if not valid.any():
            rmse = float("nan")
        else:
            rmse = float(np.sqrt(np.mean((y[valid] - pred[valid]) ** 2)))
        rows.append({"day": pd.Timestamp(day), "model": str(model), "rmse": rmse})
    return pd.DataFrame(rows, columns=["day", "model", "rmse"])


def _run_one(
    panel: pd.DataFrame,
    model_name: str,
    features: list[str],
    mode: str,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> list[BacktestResult]:
    """执行一个模型在指定窗口或窗口组上的回测。"""
    factory = MODEL_FACTORIES[model_name]
    if mode == "annual":
        return [
            monthly_walk_forward(
                panel,
                factory,
                features,
                start or ANNUAL_BACKTEST_START,
                end or ANNUAL_BACKTEST_END,
            )
        ]
    if mode == "fixed":
        if start is None or end is None:
            raise ValueError("fixed 模式必须提供 --start 和 --end")
        return [fixed_window(panel, factory, features, start, end)]
    if mode == "winter":
        return [
            fixed_window(panel, factory, features, window_start, window_end)
            for window_start, window_end in WINTER_WINDOWS
        ]
    raise ValueError(f"未知 mode: {mode}")


def _write_outputs(
    out_root: Path,
    run_id: str,
    model_names: list[str],
    results: list[tuple[str, BacktestResult]],
    mode: str,
    features: list[str],
) -> Path:
    """写出五个契约要求的回测文件。"""
    out_dir = out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=False)
    prediction_frames = [result.predictions for _, result in results]
    fold_frames = [result.folds for _, result in results]
    predictions = pd.concat(prediction_frames, ignore_index=True)
    predictions = predictions[["day", "hour", "y", "pred", "model"]].sort_values(
        ["model", "day", "hour"], kind="stable"
    )
    predictions.to_csv(out_dir / "predictions.csv", index=False)
    daily_frames: list[pd.DataFrame] = []
    for _, result in results:
        daily_frames.append(_daily_metrics(result))
    daily = pd.concat(daily_frames, ignore_index=True)
    daily = daily.sort_values(["model", "day"], kind="stable").reset_index(drop=True)
    daily.to_csv(out_dir / "daily_metrics.csv", index=False)
    folds = pd.concat(fold_frames, ignore_index=True)
    folds = folds[
        ["model", "train_start", "train_end", "test_start", "test_end", "n_train", "n_test"]
    ]
    folds.to_csv(out_dir / "folds.csv", index=False)

    summaries: dict[str, dict[str, object]] = {}
    for model in model_names:
        values = daily.loc[daily["model"] == model, "rmse"].to_numpy(dtype=float)
        summaries[model] = summarize_daily_rmse(values)
    metrics = {
        "run_id": run_id,
        "mode": mode,
        "features": features,
        "models": summaries,
    }
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, allow_nan=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"# Backtest {run_id}",
        "",
        f"mode: `{mode}`",
        "",
        "| model | mean | median | max | p90 | crash_rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in model_names:
        summary = summaries[model]
        lines.append(
            f"| {model} | {summary['mean']:.6g} | {summary['median']:.6g} | "
            f"{summary['max']:.6g} | {summary['p90']:.6g} | {summary['crash_rate']:.6g} |"
        )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_dir


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", required=True, help="panel.csv.gz 路径")
    parser.add_argument("--mode", choices=("annual", "fixed", "winter"), required=True)
    parser.add_argument("--models", required=True, help="逗号分隔的模型名")
    parser.add_argument("--features", default="base", help="base、all 或逗号分隔列名")
    parser.add_argument("--start", help="回测开始日期")
    parser.add_argument("--end", help="回测结束日期")
    parser.add_argument("--out", default="reports/backtests", help="输出根目录")
    return parser


def main(argv: list[str] | None = None) -> int:
    """运行 CLI；失败时向 stderr 打印原因并返回非零。"""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        model_names = _parse_models(args.models)
        features = _parse_features(args.features)
        if args.mode == "annual" and ((args.start is None) != (args.end is None)):
            raise ValueError("annual 模式的 --start 和 --end 必须同时提供")
        start = pd.Timestamp(args.start) if args.start else None
        end = pd.Timestamp(args.end) if args.end else None
        panel_path = Path(args.panel)
        if not panel_path.exists():
            raise FileNotFoundError(f"panel 文件不存在: {panel_path}")
        panel = load_panel(panel_path)
        if panel.empty:
            raise ValueError("panel 为空")
        results: list[tuple[str, BacktestResult]] = []
        for model_name in model_names:
            for result in _run_one(panel, model_name, features, args.mode, start, end):
                results.append((model_name, result))
        if not results or all(result.predictions.empty for _, result in results):
            raise ValueError("没有产生任何预测")
        if any(
            not np.isfinite(result.predictions["pred"].to_numpy(dtype=float)).all()
            for _, result in results
        ):
            raise ValueError("预测含 NaN/inf")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        tag = "_".join(model_names)
        out_dir = _write_outputs(Path(args.out), f"{stamp}-{tag}", model_names, results, args.mode, features)
        print(out_dir)
        return 0
    except Exception as exc:  # CLI 应把用户可修复原因变成非零退出
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
