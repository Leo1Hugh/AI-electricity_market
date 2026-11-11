#!/usr/bin/env python3
"""独立的 24 点 naive 兜底提交器。

脚本只读取本地 hourly 或 panel 缓存，不联网，也不依赖正式模型流水线。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
HOURS = tuple(range(1, 25))
LOCAL_TZ = ZoneInfo("America/Los_Angeles")
DEFAULT_HOURLY = ROOT / "work" / "hourly.csv.gz"
DEFAULT_PROCESS_HOURLY = ROOT / "deepseek过程文件" / "05_中间数据" / "hourly_inference.csv.gz"
DEFAULT_PROCESS_PANEL = ROOT / "deepseek过程文件" / "05_中间数据" / "panel_inference.csv.gz"


class StaleSourceError(RuntimeError):
    """输入缓存早于允许的陈旧阈值。"""


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
    if hourly is None and panel is None:
        candidates = [
            (DEFAULT_PROCESS_HOURLY, "hourly"),
            (DEFAULT_PROCESS_PANEL, "panel"),
            (DEFAULT_HOURLY, "hourly"),
        ]
        for candidate, kind in candidates:
            if candidate.exists():
                if kind == "hourly":
                    hourly = candidate
                else:
                    panel = candidate
                break
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


def _source_latest_day(source: pd.DataFrame, as_of: pd.Timestamp) -> pd.Timestamp | None:
    """返回 D 之前、具有有限价格的最新日期。"""
    frame = source.copy()
    frame["day"] = pd.to_datetime(frame["day"], errors="coerce").dt.normalize()
    frame["price_value"] = pd.to_numeric(frame["price_value"], errors="coerce")
    valid = frame["day"].notna() & (frame["day"] < as_of) & frame["price_value"].notna()
    valid &= np.isfinite(frame["price_value"])
    if not valid.any():
        return None
    return pd.Timestamp(frame.loc[valid, "day"].max()).normalize()


def _check_staleness(source: pd.DataFrame, as_of: pd.Timestamp, *, allow_stale: bool) -> tuple[pd.Timestamp | None, bool]:
    """执行 D-1/D-2 陈旧门并返回最新日期和 stale 标志。"""
    latest = _source_latest_day(source, as_of)
    threshold = as_of - pd.Timedelta(days=2)
    normal = as_of - pd.Timedelta(days=1)
    stale = latest is None or latest < normal
    if latest is not None and latest >= normal:
        return latest, False
    if latest is not None and latest == threshold:
        print(f"WARNING: 数据只到 D-2 ({latest.date()})，将用 D-2 价格兜底。", file=sys.stderr)
        return latest, True
    latest_text = "无有效日期" if latest is None else str(latest.date())
    message = f"数据陈旧：最新 day={latest_text}，要求 >= {threshold.date()}；确认后可用 --allow-stale"
    if not allow_stale:
        raise StaleSourceError(message)
    print(f"WARNING: {message}", file=sys.stderr)
    return latest, True


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
    source_latest_day: pd.Timestamp | None,
    source_stale: bool,
    allow_stale: bool,
) -> Path:
    """写出预测、元数据和统一提交 JSON。"""
    target = _resolve(out_dir) / str(metadata["as_of"])
    target.mkdir(parents=True, exist_ok=True)
    metadata = dict(metadata)
    metadata.update(
        {
            "source": source_name,
            "source_path": str(source_path),
            "source_latest_day": None if source_latest_day is None else str(source_latest_day.date()),
            "source_stale": bool(source_stale),
            "allow_stale": bool(allow_stale),
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
    parser.add_argument("--hourly", type=Path, default=None)
    parser.add_argument("--panel", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--allow-stale", action="store_true", help="确认后允许使用早于 D-2 的缓存")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    as_of = pd.Timestamp(args.as_of).normalize()
    if args.dry_run:
        print(json.dumps({"as_of": str(as_of.date()), "model": "naive_fallback", "would_write": False}, ensure_ascii=False))
        return 0
    try:
        source, source_path, source_name = _read_source(args.hourly, args.panel)
        source_latest_day, source_stale = _check_staleness(source, as_of, allow_stale=args.allow_stale)
        predictions, metadata = build_fallback(source, as_of)
        output = _write_output(
            predictions,
            metadata,
            source_path,
            source_name,
            args.out_dir,
            source_latest_day,
            source_stale,
            args.allow_stale,
        )
        display_metadata = dict(metadata)
        display_metadata.update(
            {
                "source_path": str(source_path),
                "source_latest_day": None if source_latest_day is None else str(source_latest_day.date()),
                "source_stale": bool(source_stale),
                "allow_stale": bool(args.allow_stale),
            }
        )
        print(json.dumps({"output_dir": str(output), **display_metadata}, ensure_ascii=False))
        return 0
    except StaleSourceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
