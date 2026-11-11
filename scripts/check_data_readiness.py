#!/usr/bin/env python3
"""只读核验 CAISO 日前价格、负荷和 SP15 风光数据是否齐全。"""

from __future__ import annotations

import argparse
import csv
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    from scripts.caiso_oasis_collect import local_midnight_utc, query_url
except ModuleNotFoundError:  # pragma: no cover - CLI invocation from scripts/.
    from caiso_oasis_collect import local_midnight_utc, query_url  # type: ignore[no-redef]


LOCAL_TZ = ZoneInfo("America/Los_Angeles")
TARGET_LOADS = ("CA ISO-TAC", "SCE-TAC", "SDGE-TAC")
TARGET_RENEWABLES = ("Solar", "Wind")


class ReadinessError(RuntimeError):
    """网络或响应格式错误。"""


def _clean(row: dict[str, str]) -> dict[str, str]:
    """规范 OASIS CSV 字段名和值。"""
    return {str(key).strip().upper(): (value or "").strip() for key, value in row.items() if key is not None}


def _first(row: dict[str, str], *names: str) -> str:
    """读取第一个存在且非空的字段。"""
    for name in names:
        value = row.get(name.upper(), "")
        if value:
            return value
    return ""


def _download(url: str, timeout: int = 60) -> bytes:
    """下载响应到内存，不创建任何仓库文件。"""
    request = urllib.request.Request(url, headers={"User-Agent": "AI-electricity_market-readiness/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        raise ReadinessError(f"network error: {exc}") from exc


def _rows(payload: bytes) -> list[dict[str, str]]:
    """解析 CSV；空 CSV 或只有错误 XML 的响应视为尚无数据。"""
    try:
        rows: list[dict[str, str]] = []
        has_csv = False
        has_error_xml = False
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise ReadinessError(f"corrupt ZIP member: {bad_member}")
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if info.filename.lower().endswith(".xml"):
                    text = archive.read(info).decode("utf-8", errors="strict")
                    has_error_xml |= "ERR_CODE" in text or "ERR_DESC" in text
                if info.filename.lower().endswith(".csv"):
                    has_csv = True
                    text = archive.read(info).decode("utf-8-sig", errors="strict")
                    rows.extend(_clean(row) for row in csv.DictReader(io.StringIO(text)))
        if not has_csv and not has_error_xml:
            raise ReadinessError("response ZIP contained no CSV or CAISO error XML")
        return rows
    except (zipfile.BadZipFile, UnicodeError, csv.Error, OSError) as exc:
        raise ReadinessError(f"invalid response format: {exc}") from exc


def _hours(rows: list[dict[str, str]], *, day: date, predicate) -> tuple[int, str | None]:
    """统计目标日期的唯一 OPR_HR 和最新 OPR_DT。"""
    selected: set[int] = set()
    dates: list[date] = []
    for row in rows:
        if not predicate(row):
            continue
        try:
            row_day = date.fromisoformat(_first(row, "OPR_DT", "OP_DATE", "OPR_DATE")[:10])
            hour = int(_first(row, "OPR_HR"))
        except (TypeError, ValueError):
            continue
        dates.append(row_day)
        if row_day == day and 1 <= hour <= 24:
            selected.add(hour)
    latest = max(dates).isoformat() if dates else None
    return len(selected), latest


def check_once(as_of: date, *, timeout: int = 60) -> dict[str, object]:
    """执行一次三报表核验并返回可序列化结果。"""
    d_minus_1 = as_of - timedelta(days=1)
    results: dict[str, object] = {}
    errors: list[str] = []
    queries = {
        "PRC_LMP": (
            local_midnight_utc(as_of - timedelta(days=7)),
            local_midnight_utc(as_of),
            {"version": "12", "node": "TH_SP15_GEN-APND"},
        ),
        "SLD_FCST": (
            local_midnight_utc(as_of),
            local_midnight_utc(as_of + timedelta(days=1)),
            {},
        ),
        "SLD_REN_FCST": (
            local_midnight_utc(as_of),
            local_midnight_utc(as_of + timedelta(days=1)),
            {},
        ),
    }
    for report, (start, end, extra) in queries.items():
        url = query_url(report, start, end, **extra)
        try:
            rows = _rows(_download(url, timeout=timeout))
            if report == "PRC_LMP":
                predicate = lambda row: (
                    _first(row, "MARKET_RUN_ID", "MARKET_TYPE") == "DAM"
                    and _first(row, "LMP_TYPE") == "LMP"
                    and _first(row, "NODE", "NODE_ID", "NODE_ID_XML") == "TH_SP15_GEN-APND"
                )
                count, latest = _hours(rows, day=d_minus_1, predicate=predicate)
                expected = {"D-1": d_minus_1.isoformat()}
                results[report] = {"url": url, "hours": count, "latest_opr_dt": latest, "expected": expected, "ready": count == 24}
            elif report == "SLD_FCST":
                per_region: dict[str, int] = {}
                latest = None
                for region in TARGET_LOADS:
                    predicate = lambda row, region=region: (
                        _first(row, "MARKET_RUN_ID", "MARKET_TYPE") == "DAM"
                        and _first(row, "TAC_AREA_NAME", "TAC_AREA", "REGION", "RESOURCE_NAME") == region
                        and (_first(row, "XML_DATA_ITEM", "DATA_ITEM") in {"", "SYS_FCST_DA_MW"})
                    )
                    count, region_latest = _hours(rows, day=as_of, predicate=predicate)
                    per_region[region] = count
                    latest = max(filter(None, [latest, region_latest]), default=None)
                results[report] = {"url": url, "hours": per_region, "latest_opr_dt": latest, "expected": as_of.isoformat(), "ready": all(value == 24 for value in per_region.values())}
            else:
                per_type: dict[str, int] = {}
                latest = None
                for renewable in TARGET_RENEWABLES:
                    predicate = lambda row, renewable=renewable: (
                        _first(row, "MARKET_RUN_ID", "MARKET_TYPE") == "DAM"
                        and _first(row, "TRADING_HUB") == "SP15"
                        and _first(row, "RENEWABLE_TYPE", "RENEWABLE_FUEL_TYPE") == renewable
                        and (_first(row, "XML_DATA_ITEM", "DATA_ITEM") in {"", "RENEW_FCST_DA_MW"})
                    )
                    count, type_latest = _hours(rows, day=as_of, predicate=predicate)
                    per_type[renewable] = count
                    latest = max(filter(None, [latest, type_latest]), default=None)
                results[report] = {"url": url, "hours": per_type, "latest_opr_dt": latest, "expected": as_of.isoformat(), "ready": all(value == 24 for value in per_type.values())}
        except ReadinessError as exc:
            errors.append(f"{report}: {exc}")
            results[report] = {"url": url, "ready": False, "error": str(exc)}
    ready = not errors and all(bool(item.get("ready")) for item in results.values() if isinstance(item, dict))
    return {
        "as_of": as_of.isoformat(),
        "ready": ready,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "reports": results,
        "errors": errors,
    }


def _until(value: str) -> datetime:
    """解析带时区的 until，未带时区时按加州时间解释。"""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    """执行 once 或 watch 预检。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=300.0)
    parser.add_argument("--until", type=str, default=None)
    args = parser.parse_args(argv)
    if args.once and args.watch:
        parser.error("--once 与 --watch 不能同时使用")
    if args.watch and not args.until:
        parser.error("--watch 需要 --until")
    if args.interval <= 0:
        parser.error("--interval 必须为正数")
    if not args.watch:
        try:
            result = check_once(args.as_of)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["ready"] else (1 if result["errors"] else 2)
        except ReadinessError as exc:
            print(json.dumps({"as_of": args.as_of.isoformat(), "ready": False, "checked_at": datetime.now(timezone.utc).isoformat(), "errors": [str(exc)]}, ensure_ascii=False))
            return 1

    deadline = _until(args.until)
    while True:
        try:
            result = check_once(args.as_of)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
            if result["ready"]:
                return 0
            if datetime.now(timezone.utc) >= deadline:
                return 2 if not result["errors"] else 1
        except ReadinessError as exc:
            result = {"as_of": args.as_of.isoformat(), "ready": False, "checked_at": datetime.now(timezone.utc).isoformat(), "errors": [str(exc)]}
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if datetime.now(timezone.utc) >= deadline:
                return 1
        remaining = max(0.0, (deadline - datetime.now(timezone.utc)).total_seconds())
        if remaining <= 0:
            return 2
        # 分段等待仍须满足 interval；不能每 30 秒重新发起一次查询。
        next_poll = time.monotonic() + min(args.interval, remaining)
        while True:
            wait = min(
                next_poll - time.monotonic(),
                (deadline - datetime.now(timezone.utc)).total_seconds(),
            )
            if wait <= 0:
                break
            time.sleep(min(wait, 30.0))


if __name__ == "__main__":
    raise SystemExit(main())
