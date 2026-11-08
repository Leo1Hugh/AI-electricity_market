#!/usr/bin/env python3
"""构建 D 日推理面板、运行冻结模型并写出本地提交文件。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from em.io import load_hourly, load_panel, save_panel  # noqa: E402
from em.pipeline import (  # noqa: E402
    FINAL_MODEL,
    PipelineResult,
    naive_only_prediction,
    run_pipeline,
)


PROCESS_ROOT = ROOT / "deepseek过程文件" / "05_中间数据"
DEFAULT_OUT = PROCESS_ROOT / "submissions"
RAW_ROOT = ROOT / "data" / "raw" / "caiso"
PRICE_ROOT = ROOT / "data" / "CAISO"
MANIFEST = ROOT / "data" / "caiso_collection_manifest.jsonl"


def sha256(path: Path) -> str:
    """计算文件 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(path: Path) -> Path:
    """将相对路径解析到仓库根目录。"""
    return path if path.is_absolute() else ROOT / path


def _write_hourly_copy(source: Path, target: Path) -> Path:
    """把缓存 hourly 复制到过程目录，不触碰 work/hourly.csv.gz。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def _refresh_and_rebuild_hourly(as_of: date, target: Path) -> Path:
    """刷新最近七天并在过程目录重建 hourly。"""
    from scripts.fetch_daily import main as fetch_main
    from scripts.rebuild_hourly import _write_deterministic, rebuild

    code = fetch_main(
        [
            "--as-of",
            as_of.isoformat(),
            "--days",
            "7",
            "--root",
            str(RAW_ROOT),
            "--manifest",
            str(MANIFEST),
            "--refresh",
        ]
    )
    if code:
        raise RuntimeError(f"daily fetch 失败，退出码 {code}")
    frame, _ = rebuild(RAW_ROOT, PRICE_ROOT)
    if frame.empty:
        raise ValueError("hourly 重建结果为空")
    _write_deterministic(frame, target)
    return target


def _build_panel_inference(hourly_path: Path, as_of: pd.Timestamp, panel_path: Path) -> Path:
    """使用 W1 builder 构建包含 D 日的过程面板。"""
    import em.data.panel as panel_module

    hourly = load_hourly(hourly_path)
    original_end = panel_module.TRAIN_END
    panel_module.TRAIN_END = max(original_end, as_of)
    try:
        panel = panel_module.build_panel(hourly)
    finally:
        panel_module.TRAIN_END = original_end
    if not (panel["day"] == as_of).any():
        raise ValueError(f"构建面板不包含 as_of={as_of.date()}；请先刷新数据")
    save_panel(panel, panel_path)
    return panel_path


def prepare_inputs(as_of: pd.Timestamp, *, refresh_data: bool) -> tuple[Path, Path]:
    """准备过程目录中的 hourly 与 panel 文件。"""
    PROCESS_ROOT.mkdir(parents=True, exist_ok=True)
    hourly_path = PROCESS_ROOT / "hourly_inference.csv.gz"
    panel_path = PROCESS_ROOT / "panel_inference.csv.gz"
    if refresh_data:
        _refresh_and_rebuild_hourly(as_of.date(), hourly_path)
    elif not hourly_path.exists():
        source = ROOT / "work" / "hourly.csv.gz"
        if not source.exists():
            raise FileNotFoundError(f"缓存 hourly 不存在: {source}")
        _write_hourly_copy(source, hourly_path)
    _build_panel_inference(hourly_path, as_of, panel_path)
    return hourly_path, panel_path


def _cached_panel(path: Path, as_of: pd.Timestamp) -> tuple[pd.DataFrame, bool]:
    """读取缓存 panel，并判断是否含 D 日完整 24 点。"""
    if not path.exists():
        raise FileNotFoundError(f"缓存 panel 不存在: {path}")
    panel = load_panel(path)
    day_rows = panel[panel["day"] == as_of]
    complete = len(day_rows) == 24 and set(day_rows["hour"].astype(int)) == set(range(1, 25))
    return panel, complete


def _stale_cached_result(
    as_of: pd.Timestamp,
    refresh_error: Exception,
    out_dir: Path,
) -> tuple[PipelineResult, Path]:
    """在刷新失败时从缓存面板运行冻结模型或 naive-only。"""
    panel_path = PROCESS_ROOT / "panel_inference.csv.gz"
    panel, has_day = _cached_panel(panel_path, as_of)
    reason = f"refresh failed: {type(refresh_error).__name__}: {refresh_error}"
    digest = sha256(panel_path)
    if has_day:
        result = run_pipeline(panel, as_of, data_sha256=digest)
        result.metadata["data_stale"] = True
        result.metadata["fallback"] = True
        result.metadata["fallback_reason"] = reason
        result.metadata["naive_only"] = False
        return result, panel_path
    result = naive_only_prediction(
        panel,
        as_of,
        data_sha256=digest,
        reason=reason + "; cached panel lacks as_of, naive-only fallback",
        data_stale=True,
    )
    return result, panel_path


def _write_submission(result: PipelineResult, out_dir: Path, panel_path: Path) -> Path:
    """写出 predictions.csv、metadata.json 和 submission.json。"""
    submission_dir = out_dir / str(result.metadata["as_of"])
    submission_dir.mkdir(parents=True, exist_ok=True)
    result.predictions.to_csv(submission_dir / "predictions.csv", index=False)
    metadata = dict(result.metadata)
    metadata["data_sha256"] = sha256(panel_path)
    (submission_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    submission = {
        "day": result.metadata["as_of"],
        "model": FINAL_MODEL,
        "predictions": result.predictions[["hour", "price"]].to_dict(orient="records"),
    }
    (submission_dir / "submission.json").write_text(
        json.dumps(submission, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return submission_dir


def build_parser() -> argparse.ArgumentParser:
    """构建提交 CLI。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, type=date.fromisoformat, help="America/Los_Angeles 运行日")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--refresh-data", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行提交流程；dry-run 只打印计划，不写盘。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    as_of = pd.Timestamp(args.as_of).normalize()
    if args.dry_run:
        print(
            json.dumps(
                {
                    "as_of": str(as_of.date()),
                    "model": FINAL_MODEL,
                    "refresh_data": bool(args.refresh_data),
                    "out_dir": str(_resolve(args.out_dir)),
                    "would_write": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    try:
        if args.refresh_data:
            try:
                _, panel_path = prepare_inputs(as_of, refresh_data=True)
                panel = load_panel(panel_path)
                result = run_pipeline(panel, as_of, data_sha256=sha256(panel_path))
                result.metadata.setdefault("data_stale", False)
                result.metadata.setdefault("naive_only", False)
            except Exception as refresh_error:
                try:
                    result, panel_path = _stale_cached_result(as_of, refresh_error, _resolve(args.out_dir))
                except Exception as cache_error:
                    # Last attempt: rebuild from the immutable work hourly cache.
                    try:
                        _, panel_path = prepare_inputs(as_of, refresh_data=False)
                        panel = load_panel(panel_path)
                        result = run_pipeline(panel, as_of, data_sha256=sha256(panel_path))
                        result.metadata["data_stale"] = True
                        result.metadata["fallback"] = True
                        result.metadata["fallback_reason"] = (
                            f"refresh failed: {refresh_error}; cache fallback failed: {cache_error}; "
                            "used work/hourly cache"
                        )
                        result.metadata.setdefault("naive_only", False)
                    except Exception as work_error:
                        raise RuntimeError(
                            f"refresh failed: {refresh_error}; cache failed: {cache_error}; "
                            f"work/hourly fallback failed: {work_error}"
                        ) from work_error
        else:
            _, panel_path = prepare_inputs(as_of, refresh_data=False)
            panel = load_panel(panel_path)
            result = run_pipeline(panel, as_of, data_sha256=sha256(panel_path))
            result.metadata.setdefault("data_stale", False)
            result.metadata.setdefault("naive_only", False)
        submission_dir = _write_submission(result, _resolve(args.out_dir), panel_path)
        print(json.dumps({"submission_dir": str(submission_dir), **result.metadata}, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
