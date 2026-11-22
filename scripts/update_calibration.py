#!/usr/bin/env python3
"""用最近 N 个已出分提交日重估中午常数偏移，写 calibration.json。

在 D 日实际价入库（fetch + rebuild 之后）再跑本脚本，次日预测前
predict_and_submit 会读取校准表并把偏移加到中午 10-15 时。
冷启动（有效天数不足 7）可用 --extra-residuals 预填历史同季回测残差
（CSV 列：day,hour,resid）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from em.calibration import fit_midday_offset  # noqa: E402
from em.io import load_panel  # noqa: E402

PROCESS_ROOT = ROOT / "deepseek过程文件" / "05_中间数据"
DEFAULT_SUBS = PROCESS_ROOT / "submissions"
DEFAULT_PANEL = PROCESS_ROOT / "panel_inference.csv.gz"
LOOKBACK_DAYS = 14


def collect_residuals(submissions_dir: Path, panel: pd.DataFrame) -> pd.DataFrame:
    """扫描提交目录，用面板真实价算 (pred - actual)。"""
    empty = pd.DataFrame(columns=["day", "hour", "resid"])
    if not submissions_dir.exists():
        return empty
    panel_days = panel[["day", "hour", "y"]].copy()
    panel_days["day"] = pd.to_datetime(panel_days["day"]).dt.normalize()
    rows: list[pd.DataFrame] = []
    for sub in sorted(submissions_dir.glob("*/predictions.csv")):
        day = pd.Timestamp(sub.parent.name)
        if pd.isna(day):
            continue
        day = day.normalize()
        pred = pd.read_csv(sub)
        actual = panel_days[panel_days["day"] == day]
        if actual.empty or "price" not in pred.columns:
            continue
        joined = pred.merge(actual, on="hour", how="inner")
        if joined.empty:
            continue
        joined["resid"] = pd.to_numeric(joined["price"], errors="coerce") - pd.to_numeric(
            joined["y"], errors="coerce"
        )
        joined["day"] = day
        rows.append(joined[["day", "hour", "resid"]])
    if not rows:
        return empty
    return pd.concat(rows, ignore_index=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submissions-dir", type=Path, default=DEFAULT_SUBS)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--lookback-days", type=int, default=LOOKBACK_DAYS)
    parser.add_argument("--extra-residuals", type=Path, default=None,
                        help="预填的历史残差 CSV（day,hour,resid），用于冷启动")
    args = parser.parse_args(argv)

    panel = load_panel(str(args.panel))
    residuals = collect_residuals(args.submissions_dir, panel)
    if args.extra_residuals is not None and args.extra_residuals.exists():
        extra = pd.read_csv(args.extra_residuals, parse_dates=["day"])
        extra["day"] = extra["day"].dt.normalize()
        residuals = pd.concat([extra[["day", "hour", "resid"]], residuals], ignore_index=True)
    if residuals.empty:
        recent = residuals
    else:
        residuals = residuals.sort_values("day").drop_duplicates(["day", "hour"], keep="last")
        cutoff = residuals["day"].max() - pd.Timedelta(days=args.lookback_days)
        recent = residuals[residuals["day"] >= cutoff]
    offset, info = fit_midday_offset(recent)
    payload = {"offset": offset, "lookback_days": args.lookback_days, **info}
    out = args.out or (args.submissions_dir / "calibration.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
