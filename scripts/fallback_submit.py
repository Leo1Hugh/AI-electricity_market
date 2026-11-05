#!/usr/bin/env python3
"""独立的 24 点 naive 兜底提交器。

脚本只读取本地 hourly 或 panel 缓存，不联网，也不依赖正式模型流水线。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
HOURS = tuple(range(1, 25))
LOCAL_TZ = ZoneInfo("America/Los_Angeles")
DEFAULT_HOURLY = ROOT / "work" / "hourly.csv.gz"


def sha256(path: Path) -> str:
    """计算输入缓存的 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(path: Path) -> Path:
    """把相对路径解析到仓库根目录。"""
    return path if path.is_absolute() else ROOT / path


def _read_source(hourly: Path | None, panel: Path | None) -> tuple[pd.DataFrame, Path, str]:
    """读取 hourly 或 panel，并返回统一的历史价格表。"""
    if hourly is not None:
        hourly = _resolve(hourly)
    if panel is not None:
        panel = _resolve(panel)
    if hourly is not None and hourly.exists():
        frame = pd.read_csv(hourly)
        if not {"opr_dt", "opr_hr", "price"}.issubset(frame.columns):
            raise ValueError("hourly 必须包含 opr_dt、opr_hr、price")
        frame["day"] = pd.to_datetime(frame["opr_dt"], errors="coerce").dt.normalize()
        frame["hour"] = pd.to_numeric(frame["opr_hr"], errors="coerce")
        frame["price_value"] = pd.to_numeric(frame["price"], errors="coerce")
        return frame[["day", "hour", "price_value"]], hourly, "hourly"
    if panel is not None and panel.exists():
        frame = pd.read_csv(panel)
        if not {"day", "hour", "y"}.issubset(frame.columns):
            raise ValueError("panel 必须包含 day、hour、y")
        frame["day"] = pd.to_datetime(frame["day"], errors="coerce").dt.normalize()
        frame["hour"] = pd.to_numeric(frame["hour"], errors="coerce")
        frame["price_value"] = pd.to_numeric(frame["y"], errors="coerce")
        return frame[["day", "hour", "price_value"]], panel, "panel"
    candidates = [str(path) for path in (hourly, panel) if path is not None]
    raise FileNotFoundError(f"找不到 hourly/panel 缓存: {candidates}")


def _normalise_history(frame: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """保留 D 之前的有效价格，并按日期/小时去重。"""
    out = frame.copy()
    out["day"] = pd.to_datetime(out["day"], errors="coerce").dt.normalize()
    out["hour"] = pd.to_numeric(out["hour"], errors="coerce")
    out["price_value"] = pd.to_numeric(out["price_value"], errors="coerce")
    out = out[out["day"].notna() & out["hour"].isin(HOURS)]
    out = out[out["day"] < as_of]
    out = out[out["price_value"].notna() & np.isfinite(out["price_value"])]
    out["hour"] = out["hour"].astype(int)
    return out.sort_values(["day", "hour"], kind="stable").drop_duplicates(
        ["day", "hour"], keep="last"
    )


def _lookup(history: pd.DataFrame, day: pd.Timestamp, hour: int) -> float | None:
    """读取一个日期/小时价格。"""
    values = history.loc[(history["day"] == day) & (history["hour"] == hour), "price_value"]
    if values.empty:
        return None
    value = float(values.iloc[-1])
    return value if np.isfinite(value) else None


def _predict_one(history: pd.DataFrame, as_of: pd.Timestamp, hour: int) -> tuple[float, str]:
    """按 lag1、七日均值、最近可用日顺序生成一个价格。"""
    lag1 = _lookup(history, as_of - pd.Timedelta(days=1), hour)
    if lag1 is not None:
        return lag1, "p_lag1"

    recent_days = [as_of - pd.Timedelta(days=offset) for offset in range(1, 8)]
    recent = history[history["day"].isin(recent_days) & history["hour"].eq(hour)]
    recent_values = recent["price_value"].to_numpy(dtype=float)
    recent_values = recent_values[np.isfinite(recent_values)]
    if len(recent_values):
        return float(np.mean(recent_values)), "recent_7d_mean"

    available = history[history["hour"].eq(hour)].sort_values("day", ascending=False)
    if not available.empty:
        value = float(available.iloc[0]["price_value"])
        if np.isfinite(value):
            return value, "most_recent_available"
    raise ValueError(f"hour={hour} 没有可用历史价格")


def build_fallback(
    source: pd.DataFrame,
    as_of: object,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """从本地价格历史生成 D 日 24 点预测和来源统计。"""
    day = pd.Timestamp(as_of).normalize()
    if pd.isna(day):
        raise ValueError("as_of 不能为 NaT")
    history = _normalise_history(source, day)
    if history.empty:
        raise ValueError(f"{day.date()} 之前没有有效价格")
    rows: list[dict[str, object]] = []
    sources: Counter[str] = Counter()
    for hour in HOURS:
        value, source_name = _predict_one(history, day, hour)
        rows.append({"day": str(day.date()), "hour": hour, "price": value})
        sources[source_name] += 1
    predictions = pd.DataFrame(rows, columns=["day", "hour", "price"])
    metadata = {
        "as_of": str(day.date()),
        "model": "naive_fallback",
        "source_counts": dict(sources),
        "fallback_reason": "independent local naive path",
        "n_rows": len(predictions),
        "hours": list(HOURS),
        "finite": bool(np.isfinite(predictions["price"].to_numpy(dtype=float)).all()),
    }
    return predictions, metadata


def _write_output(
    predictions: pd.DataFrame,
    metadata: dict[str, Any],
    source_path: Path,
    source_name: str,
    out_dir: Path,
) -> Path:
    """写出预测、元数据和统一提交 JSON。"""
    target = _resolve(out_dir) / str(metadata["as_of"])
    target.mkdir(parents=True, exist_ok=True)
    metadata = dict(metadata)
    metadata.update(
        {
            "source": source_name,
            "source_path": str(source_path),
            "data_sha256": sha256(source_path),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "validation": {
                "n_rows": int(len(predictions)),
                "hours": sorted(predictions["hour"].astype(int).tolist()),
                "finite": bool(np.isfinite(predictions["price"].to_numpy(dtype=float)).all()),
            },
        }
    )
    predictions.to_csv(target / "predictions.csv", index=False)
    (target / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    submission = {
        "day": metadata["as_of"],
        "model": "naive_fallback",
        "predictions": predictions[["hour", "price"]].to_dict(orient="records"),
    }
    (target / "submission.json").write_text(
        json.dumps(submission, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return target


def main(argv: list[str] | None = None) -> int:
    """执行独立 fallback CLI。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, type=lambda value: pd.Timestamp(value).date())
    parser.add_argument("--hourly", type=Path, default=DEFAULT_HOURLY)
    parser.add_argument("--panel", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    as_of = pd.Timestamp(args.as_of).normalize()
    if args.dry_run:
        print(json.dumps({"as_of": str(as_of.date()), "model": "naive_fallback", "would_write": False}, ensure_ascii=False))
        return 0
    try:
        source, source_path, source_name = _read_source(args.hourly, args.panel)
        predictions, metadata = build_fallback(source, as_of)
        output = _write_output(predictions, metadata, source_path, source_name, args.out_dir)
        print(json.dumps({"output_dir": str(output), **metadata}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
