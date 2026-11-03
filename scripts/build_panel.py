#!/usr/bin/env python3
"""构建并校验 CAISO 小时面板。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from em.contracts import (  # noqa: E402
    MISSING_RENEWABLE_DAYS,
    PANEL_COLUMNS,
    REPORTS_DIR,
)
from em.data.panel import build_panel  # noqa: E402
from em.io import load_hourly, save_panel, validate_panel  # noqa: E402


def _sha256(path: Path) -> str:
    """计算文件 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_report(
    input_path: Path,
    output_path: Path,
    panel: pd.DataFrame,
    summary: dict[str, object],
    digest: str,
) -> None:
    """生成面板构建报告。"""
    report_path = REPORTS_DIR / "panel_build_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    missing_rows = "\n".join(
        f"| `{column}` | {int(panel[column].isna().sum())} |" for column in PANEL_COLUMNS
    )
    known = "\n".join(
        f"- `{day.date()}`：solar/wind 源数据缺测，按契约保留 NaN。"
        for day in MISSING_RENEWABLE_DAYS
    )
    command = "python scripts/build_panel.py --input " + str(input_path) + " --output " + str(output_path)
    report = f"""# Panel build report

## Command

`{command}`

## Input

- SHA-256: `{digest}`
- Path: `{input_path}`

## Output summary

- Rows: {summary['rows']}
- Days: {summary['days']}
- Columns: {len(panel.columns)}
- Target non-null: {summary['target_notna']}
- Date range: {summary['day_min']} to {summary['day_max']}

## Missing values by column

| Column | Missing |
|---|---:|
{missing_rows}

## Known missing dates

{known}

`netload = load_caiso - solar - wind` is retained as a proxy feature; the load and SP15 renewable forecasts do not share an identical geographic scope.
"""
    report_path.write_text(report, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """执行读入、构建、校验、保存和报告生成。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    output_path = args.output if args.output.is_absolute() else ROOT / args.output

    digest = _sha256(input_path)
    hourly = load_hourly(input_path)
    panel = build_panel(hourly)
    summary = validate_panel(panel, full_grid=True)
    save_panel(panel, output_path)
    _write_report(args.input, args.output, panel, summary, digest)
    print(
        json.dumps(
            {
                "rows": summary["rows"],
                "days": summary["days"],
                "cols": len(panel.columns),
                "target_notna": summary["target_notna"],
                "missing": summary["missing_by_feature"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
