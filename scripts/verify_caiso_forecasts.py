#!/usr/bin/env python3
"""Verify CAISO forecast ZIPs and write a reviewable Markdown report."""

from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

LOAD_REGIONS = {"CA ISO-TAC", "SCE-TAC", "SDGE-TAC"}
RENEWABLES = {"Solar", "Wind"}


def clean(row: dict[str, str]) -> dict[str, str]:
    return {str(k).strip().upper(): (v or "").strip() for k, v in row.items() if k is not None}


def first(row: dict[str, str], *names: str) -> str:
    for name in names:
        if row.get(name.upper(), ""):
            return row[name.upper()]
    return ""


def parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        else:
            return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def iter_rows(path: Path):
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".csv"):
                continue
            text = zf.read(info).decode("utf-8-sig", errors="replace")
            for row in csv.DictReader(io.StringIO(text)):
                yield info.filename, clean(row)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path("data/raw/caiso"))
    p.add_argument("--manifest", type=Path, default=Path("data/caiso_collection_manifest.jsonl"))
    p.add_argument("--report", type=Path, default=Path("data/caiso_validation_report.md"))
    p.add_argument("--start-date", type=date.fromisoformat, default=date(2023, 11, 1))
    p.add_argument("--end-date", type=date.fromisoformat, default=date(2026, 10, 31))
    args = p.parse_args()
    files = sorted(args.root.rglob("*.zip"))
    targets = {args.start_date + timedelta(days=i) for i in range((args.end_date - args.start_date).days + 1)}
    manifest_rows = []
    if args.manifest.exists():
        manifest_rows = [json.loads(line) for line in args.manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    manifest_errors = [row for row in manifest_rows if row.get("status") != "ok"]
    region_counts: Counter[str] = Counter()
    renewable_counts: Counter[str] = Counter()
    series_dates: defaultdict[str, set[date]] = defaultdict(set)
    date_counts: defaultdict[str, Counter[date]] = defaultdict(Counter)
    seen: defaultdict[str, set[str]] = defaultdict(set)
    nulls: Counter[str] = Counter()
    anomalies: list[str] = []
    examples: list[dict[str, str]] = []
    rows_total = 0

    for path in files:
        is_renew = "ren" in path.name.lower()
        for member, row in iter_rows(path):
            rows_total += 1
            region = first(row, "REGION", "TAC_AREA", "TAC_AREA_NAME", "RESOURCE_NAME")
            hub = first(row, "TRADING_HUB")
            renewable = first(row, "RENEWABLE_TYPE", "RENEWABLE_FUEL_TYPE")
            market = first(row, "MARKET_RUN_ID", "MARKET_TYPE")
            start = parse_utc(first(row, "INTERVALSTARTTIME_GMT", "INTERVAL_START_GMT"))
            end = parse_utc(first(row, "INTERVALENDTIME_GMT", "INTERVAL_END_GMT"))
            opr_text = first(row, "OPR_DT", "OP_DATE", "OPR_DATE")
            try:
                opr_dt = date.fromisoformat(opr_text[:10]) if opr_text else None
            except ValueError:
                opr_dt = None
            if is_renew and hub == "SP15" and renewable in RENEWABLES:
                key = f"renewable:{hub}:{renewable}"
                renewable_counts[renewable] += 1
            elif not is_renew and region in LOAD_REGIONS:
                key = f"load:{region}"
                region_counts[region] += 1
            else:
                # Other TAC areas/hubs remain in the raw ZIP but are not part
                # of the requested target-series checks.
                continue
            if opr_dt in targets:
                series_dates[key].add(opr_dt)
                date_counts[key][opr_dt] += 1
            if start is None or end is None or (end - start).total_seconds() != 3600:
                anomalies.append(f"{path}:{member}: interval {start} -> {end}")
            if start is not None:
                stamp = start.isoformat()
                if stamp in seen[key]:
                    anomalies.append(f"{path}:{member}: duplicate {key} UTC start {stamp}")
                seen[key].add(stamp)
            if not market:
                nulls["MARKET_RUN_ID/MARKET_TYPE"] += 1
            if start is None:
                nulls["INTERVALSTARTTIME_GMT"] += 1
            if opr_dt is None:
                nulls["OPR_DT/OP_DATE"] += 1
            if not first(row, "MW", "VALUE", "FORECAST", "LOAD_FORECAST", "RENEWABLE_FORECAST"):
                nulls["forecast_value"] += 1
            if len(examples) < 8 and key != "other":
                examples.append(row)

    lines = ["# CAISO 预测数据核验报告", "",
             f"- 核验时间（UTC）：{datetime.now(timezone.utc).isoformat()}",
             f"- 目标日期（加州当地交易日）：{args.start_date} 至 {args.end_date}",
             f"- ZIP 文件数：{len(files)}；总 CSV 记录数：{rows_total}",
             f"- manifest 记录：{len(manifest_rows)}；失败/无 CSV 响应：{len(manifest_errors)}",
             "- 原始响应保留：是；脚本不插值、不以实际值替代预测值。", "",
             "## 记录统计", "", "### 负荷预测（SLD_FCST，DAM）", ""]
    lines += [f"- `{k}`：{v} 行" for k, v in sorted(region_counts.items())]
    lines += ["", "### SP15 风光预测（SLD_REN_FCST，DAM）", ""]
    lines += [f"- `{k}`：{v} 行" for k, v in sorted(renewable_counts.items())]
    lines += ["", "## 核验结果", "",
              f"- 区间长度异常或重复 UTC 开始时间：{len(anomalies)} 条",
              f"- 关键字段缺失计数：{dict(nulls) if nulls else '无'}",
              "- 时间戳：保留 CAISO 原始 GMT/UTC 字段；真实顺序按 UTC 开始时间检查。",
              "- 夏令时：不强制每天 24 行；回拨日的 `OPR_HR=25` 应由 UTC 时间确认第二次 HE02。",
              "- 地域口径：`CA ISO-TAC`、`SCE-TAC`、`SDGE-TAC` 是 TAC 区域，并不自动等同于 SP15；本报告不计算净负荷。",
              "- 风光筛选：仅计入 `TRADING_HUB=SP15` 且 `RENEWABLE_TYPE` 为 `Solar` 或 `Wind` 的返回行。",
              "- 历史可用时间未验证：下载时间、ZIP 时间和 schema/version 字段不视为预测发布时间，也不证明没有未来信息泄漏。", "",
              "## 夏令时日期行数（目标序列）", ""]
    dst_dates = [date(2024, 3, 10), date(2024, 11, 3), date(2025, 3, 9), date(2025, 11, 2), date(2026, 3, 8), date(2026, 11, 1)]
    target_keys = sorted(set(series_dates) - {"other"})
    for dst in dst_dates:
        if dst not in targets:
            continue
        values = "; ".join(f"{key}={date_counts[key].get(dst, 0)}" for key in target_keys)
        lines.append(f"- `{dst}`：{values}")
    lines += ["", "## manifest 失败或无数据响应", ""]
    if manifest_errors:
        for row in manifest_errors:
            lines.append(f"- `{row.get('local_start_date')}..{row.get('local_end_date_exclusive')}` `{row.get('queryname')}`：{row.get('error', '未注明原因')}；原始响应：`{row.get('file')}`")
    else:
        lines.append("- 无")
    lines += [
              "",
              "## 目标日期覆盖", ""]
    for key, values in sorted(series_dates.items()):
        missing = sorted(targets - values)
        missing_text = [d.isoformat() for d in missing[:10]]
        lines.append(f"- `{key}`：{len(values)}/{len(targets)} 个目标日期；缺失示例：{missing_text or '无'}")
    lines += ["", "## 代表性返回字段", "", "```json", json.dumps(examples, ensure_ascii=False, indent=2), "```", "",
              "## 缺失与限制", "",
              "按 manifest 对请求失败、无记录日期、区域不适用和字段缺失分别复核。未出现的目标日期不会自动插值；需要根据对应 ZIP 的响应内容判断是源数据缺失还是报表不适用。"]
    if anomalies:
        lines += ["", "## 异常样例", "", "```text", *anomalies[:100], "```"]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"verified {len(files)} ZIP files; report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
