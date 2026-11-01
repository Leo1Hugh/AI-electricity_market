#!/usr/bin/env python3
"""Failing-closed validation for CAISO day-ahead forecast ZIP archives."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Los_Angeles")
LOAD_REGIONS = {"CA ISO-TAC", "SCE-TAC", "SDGE-TAC"}
RENEWABLES = {"Solar", "Wind"}
TARGET_KEYS = {"load:CA ISO-TAC", "load:SCE-TAC", "load:SDGE-TAC", "renewable:SP15:Solar", "renewable:SP15:Wind"}
KNOWN_MISSING = {
    "renewable:SP15:Solar": {date(2024, 3, 9), date(2025, 3, 8), date(2026, 3, 7)},
    "renewable:SP15:Wind": {date(2024, 3, 9), date(2025, 3, 8), date(2026, 3, 7)},
}
ACCEPTED_MANIFEST_STATUSES = {"ok", "skipped_existing"}


def clean(row):
    return {str(k).strip().upper(): (v or "").strip() for k, v in row.items() if k is not None}


def first(row, *names):
    for name in names:
        if row.get(name.upper(), ""):
            return row[name.upper()]
    return ""


def parse_utc(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def local_midnight_utc(day):
    return datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ).astimezone(timezone.utc)


def expected_hours(day):
    return int((local_midnight_utc(day + timedelta(days=1)) - local_midnight_utc(day)).total_seconds() // 3600)


def expected_opr_hours(day):
    count = expected_hours(day)
    if count == 23:
        return [1, 2, *range(4, 25)]
    if count == 25:
        return [1, 2, 25, *range(3, 25)]
    return list(range(1, 25)) if count == 24 else []


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_rows(path):
    with zipfile.ZipFile(path) as zf:
        bad_member = zf.testzip()
        if bad_member:
            raise zipfile.BadZipFile(f"corrupt member: {bad_member}")
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".csv"):
                continue
            text = zf.read(info).decode("utf-8-sig", errors="replace")
            for row in csv.DictReader(io.StringIO(text)):
                yield info.filename, clean(row)


def key_for(row, is_renewable):
    if is_renewable:
        hub, renewable = first(row, "TRADING_HUB"), first(row, "RENEWABLE_TYPE", "RENEWABLE_FUEL_TYPE")
        return f"renewable:{hub}:{renewable}" if hub == "SP15" and renewable in RENEWABLES else None
    region = first(row, "REGION", "TAC_AREA", "TAC_AREA_NAME", "RESOURCE_NAME")
    return f"load:{region}" if region in LOAD_REGIONS else None


def known_missing_intersects(record):
    if record.get("queryname") != "SLD_REN_FCST":
        return False
    try:
        start = date.fromisoformat(str(record["local_start_date"]))
        end = date.fromisoformat(str(record["local_end_date_exclusive"]))
    except (KeyError, ValueError):
        return False
    covered = {start + timedelta(days=i) for i in range((end - start).days)}
    return bool(covered & set().union(*KNOWN_MISSING.values()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data/raw/caiso"))
    parser.add_argument("--manifest", type=Path, default=Path("data/caiso_collection_manifest.jsonl"))
    parser.add_argument("--report", type=Path, default=Path("data/caiso_validation_report.md"))
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2023, 11, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, default=date(2026, 10, 31))
    parser.add_argument("--allow-known-missing", action="store_true",
                        help="accept only the documented three SP15 Solar/Wind missing dates")
    args = parser.parse_args()
    targets = {args.start_date + timedelta(days=i)
               for i in range((args.end_date - args.start_date).days + 1)}
    files = sorted(args.root.rglob("*.zip"))
    manifest_rows = []
    if args.manifest.exists():
        manifest_rows = [json.loads(line) for line in args.manifest.read_text(encoding="utf-8").splitlines() if line.strip()]

    anomalies = []
    examples = []
    rows_total = 0
    series_counts = Counter()
    series_dates = defaultdict(set)
    date_rows = defaultdict(lambda: defaultdict(list))
    seen = defaultdict(set)
    manifest_paths = []
    manifest_errors = []

    for record in manifest_rows:
        path = Path(str(record.get("file", "")))
        manifest_paths.append(path)
        status = record.get("status")
        if status not in ACCEPTED_MANIFEST_STATUSES:
            manifest_errors.append(record)
            if not (args.allow_known_missing and known_missing_intersects(record)):
                anomalies.append(f"manifest non-success status: {path} ({status})")
        if not path.exists():
            anomalies.append(f"manifest file missing: {path}")
        elif not record.get("sha256"):
            anomalies.append(f"manifest SHA-256 missing: {path}")
        elif sha256(path) != record["sha256"]:
            anomalies.append(f"manifest SHA-256 mismatch: {path}")
    if len(manifest_paths) != len(set(manifest_paths)):
        anomalies.append("manifest contains duplicate file paths")
    listed = {p.resolve() for p in manifest_paths if p.exists()}
    anomalies.extend(f"ZIP is not listed in manifest: {path}" for path in files if path.resolve() not in listed)

    for path in files:
        is_renewable = "sld_ren_fcst" in {part.lower() for part in path.parts}
        try:
            for member, row in iter_rows(path):
                rows_total += 1
                key = key_for(row, is_renewable)
                if key is None:
                    continue
                series_counts[key] += 1
                expected_label, expected_item = (("Renewable Forecast Day Ahead", "RENEW_FCST_DA_MW")
                                                 if is_renewable else ("Demand Forecast Day Ahead", "SYS_FCST_DA_MW"))
                if first(row, "MARKET_RUN_ID", "MARKET_TYPE") != "DAM":
                    anomalies.append(f"{path}:{member}: target {key} is not DAM")
                if first(row, "LABEL") != expected_label:
                    anomalies.append(f"{path}:{member}: {key} LABEL is not {expected_label}")
                if first(row, "XML_DATA_ITEM", "DATA_ITEM") != expected_item:
                    anomalies.append(f"{path}:{member}: {key} XML_DATA_ITEM is not {expected_item}")
                mw_text = first(row, "MW", "VALUE", "FORECAST", "LOAD_FORECAST", "RENEWABLE_FORECAST")
                try:
                    if not math.isfinite(float(mw_text)):
                        raise ValueError
                except (TypeError, ValueError):
                    anomalies.append(f"{path}:{member}: {key} MW is not finite numeric: {mw_text!r}")
                start = parse_utc(first(row, "INTERVALSTARTTIME_GMT", "INTERVAL_START_GMT"))
                end = parse_utc(first(row, "INTERVALENDTIME_GMT", "INTERVAL_END_GMT"))
                if start is None or end is None or end - start != timedelta(hours=1):
                    anomalies.append(f"{path}:{member}: {key} invalid UTC interval {start} -> {end}")
                    continue
                local = start.astimezone(LOCAL_TZ)
                opr_text = first(row, "OPR_DT", "OP_DATE", "OPR_DATE")
                try:
                    opr_day = date.fromisoformat(opr_text[:10])
                except ValueError:
                    anomalies.append(f"{path}:{member}: {key} invalid OPR_DT {opr_text!r}")
                    continue
                if local.date() != opr_day:
                    anomalies.append(f"{path}:{member}: {key} OPR_DT does not match local UTC date")
                try:
                    opr_hr = int(first(row, "OPR_HR"))
                except ValueError:
                    anomalies.append(f"{path}:{member}: {key} invalid OPR_HR")
                    continue
                if opr_hr not in set(range(1, 25)) | {25}:
                    anomalies.append(f"{path}:{member}: {key} invalid OPR_HR {opr_hr}")
                if opr_day in targets:
                    series_dates[key].add(opr_day)
                    date_rows[key][opr_day].append((start, opr_hr))
                if start in seen[key]:
                    anomalies.append(f"{path}:{member}: duplicate {key} UTC start {start.isoformat()}")
                seen[key].add(start)
                if len(examples) < 8:
                    examples.append(row)
        except (zipfile.BadZipFile, OSError) as exc:
            anomalies.append(f"cannot read ZIP {path}: {exc}")

    for key in sorted(TARGET_KEYS):
        if series_counts[key] == 0:
            anomalies.append(f"missing target series: {key}")
        missing = targets - series_dates[key]
        accepted = KNOWN_MISSING.get(key, set()) if args.allow_known_missing else set()
        unexpected = missing - accepted
        if unexpected:
            anomalies.append(f"{key} missing unaccepted dates: {sorted(d.isoformat() for d in unexpected)}")
        for day in sorted(targets - accepted):
            observed = date_rows[key].get(day, [])
            expected_count = expected_hours(day)
            if len(observed) != expected_count:
                anomalies.append(f"{key} {day} has {len(observed)} rows; expected {expected_count}")
            starts = [item[0] for item in sorted(observed)]
            expected_start = local_midnight_utc(day)
            expected_starts = [expected_start + timedelta(hours=i) for i in range(expected_count)]
            if starts != expected_starts:
                anomalies.append(f"{key} {day} UTC start sequence does not match local timezone boundaries")
            opr_hours = [item[1] for item in sorted(observed)]
            if opr_hours != expected_opr_hours(day):
                anomalies.append(f"{key} {day} OPR_HR sequence {opr_hours} != {expected_opr_hours(day)}")

    dst_dates = [date(2023, 11, 5), date(2024, 3, 10), date(2024, 11, 3),
                 date(2025, 3, 9), date(2025, 11, 2), date(2026, 3, 8), date(2026, 11, 1)]
    report_lines = [
        "# CAISO 预测数据核验报告", "",
        f"- 核验时间（UTC）：{datetime.now(timezone.utc).isoformat()}",
        f"- 目标日期（加州当地交易日）：{args.start_date} 至 {args.end_date}",
        f"- ZIP 文件数：{len(files)}；总 CSV 记录数：{rows_total}",
        f"- manifest 记录：{len(manifest_rows)}；非成功状态记录：{len(manifest_errors)}",
        f"- `--allow-known-missing`：{'启用' if args.allow_known_missing else '未启用'}", "",
        "## 目标记录统计", "",
    ]
    report_lines += [f"- `{key}`：{series_counts[key]} 行；{len(series_dates[key])}/{len(targets)} 个目标日期" for key in sorted(TARGET_KEYS)]
    report_lines += ["", "## 字段与时间核验", "",
                     "- 目标行要求 `MARKET_RUN_ID=DAM`、日前预测 LABEL/XML_DATA_ITEM、有限数值 MW。",
                     "- UTC 开始/结束时间必须相差一小时，并与 `OPR_DT` 的 America/Los_Angeles 当地日期一致。",
                     "- 每个目标序列按 UTC 开始时间检查缺失、重复、小时数和 OPR_HR 顺序。",
                     "- 历史可用时间未验证：下载时间、ZIP 时间和 schema/version 不证明预测发布时间或无未来信息泄漏。", "",
                     "## 夏令时日期", ""]
    for day in dst_dates:
        if day in targets:
            report_lines.append(f"- `{day}`：期望 {expected_hours(day)} 小时；" + "; ".join(
                f"{key}={len(date_rows[key].get(day, []))}" for key in sorted(TARGET_KEYS)))
    report_lines += ["", "## 已知缺失", "",
                     "- SP15 Solar/Wind：2024-03-09、2025-03-08、2026-03-07。CAISO 原始响应为 `ERR_CODE=1000 No data returned for the specified selection`；未插值、未使用实际值或其他区域数据。",
                     "- 只有显式使用 `--allow-known-missing` 才接受上述缺失；任何其他缺失仍会使程序返回非零。", "",
                     "## manifest 错误记录", ""]
    if manifest_errors:
        report_lines.extend(f"- `{row.get('local_start_date')}..{row.get('local_end_date_exclusive')}` `{row.get('queryname')}`：{row.get('error', '未注明原因')}；文件 `{row.get('file')}`" for row in manifest_errors)
    else:
        report_lines.append("- 无")
    report_lines += ["", "## 代表性字段", "", "```json", json.dumps(examples, ensure_ascii=False, indent=2), "```", "", "## 未通过项目", ""]
    report_lines += [f"- {item}" for item in anomalies[:200]] if anomalies else ["- 无"]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"verified {len(files)} ZIP files; anomalies={len(anomalies)}; report={args.report}")
    return 1 if anomalies else 0


if __name__ == "__main__":
    raise SystemExit(main())
