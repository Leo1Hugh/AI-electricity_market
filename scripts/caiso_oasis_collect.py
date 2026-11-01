#!/usr/bin/env python3
"""Download CAISO OASIS day-ahead forecast ZIP files.

Responses are kept unchanged and described in a JSONL manifest. The script
does not fill missing intervals or combine CAISO TAC regions.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_URL = "https://oasis.caiso.com/oasisapi/SingleZip"
LOCAL_TZ = ZoneInfo("America/Los_Angeles")
LOAD_REGIONS = ("CA ISO-TAC", "SCE-TAC", "SDGE-TAC")


def local_midnight_utc(d: date) -> datetime:
    return datetime.combine(d, dt_time.min, LOCAL_TZ).astimezone(timezone.utc)


def oasis_time(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H:%M-0000")


def query_url(queryname: str, start: datetime, end: datetime, **extra: str) -> str:
    params = {"queryname": queryname, "market_run_id": "DAM", "resultformat": "6",
              "startdatetime": oasis_time(start), "enddatetime": oasis_time(end),
              "version": "1", **extra}
    return BASE_URL + "?" + urllib.parse.urlencode(params)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def zip_summary(path: Path) -> list[dict[str, object]]:
    out = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".csv"):
                continue
            text = zf.read(info).decode("utf-8-sig", errors="replace")
            rows = list(csv.DictReader(io.StringIO(text)))
            out.append({"member": info.filename, "bytes": info.file_size,
                        "rows": len(rows),
                        "fields": list(rows[0].keys()) if rows else []})
    return out


def fetch(url: str, path: Path, retries: int, timeout: int) -> tuple[int, str]:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AI-electricity_market/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = response.read()
                status = getattr(response, "status", 200)
            path.write_bytes(payload)
            return status, "ok"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt < retries:
                # OASIS can briefly return throttling/5xx responses; retry
                # with a bounded pause rather than issuing a tight loop.
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"download failed after {retries + 1} attempts: {last}")


def batches(start: date, end_exclusive: date, batch_days: int):
    cur = start
    while cur < end_exclusive:
        nxt = min(cur + timedelta(days=batch_days), end_exclusive)
        yield cur, nxt
        cur = nxt


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start-date", type=date.fromisoformat, default=date(2023, 11, 1))
    p.add_argument("--end-date", type=date.fromisoformat, default=date(2026, 10, 31), help="inclusive local date")
    p.add_argument("--batch-days", type=int, default=30)
    p.add_argument("--out", type=Path, default=Path("data/raw/caiso"))
    p.add_argument("--manifest", type=Path, default=Path("data/caiso_collection_manifest.jsonl"))
    p.add_argument("--sample-only", action="store_true")
    p.add_argument("--sample-date", type=date.fromisoformat, default=date(2026, 10, 30))
    p.add_argument("--reports", choices=("all", "load", "renewable"), default="all")
    p.add_argument("--sleep-seconds", type=float, default=1.0)
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--timeout", type=int, default=120)
    args = p.parse_args()
    if args.batch_days < 1:
        p.error("--batch-days must be positive")
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.sample_only:
        ranges = [(args.sample_date, args.sample_date + timedelta(days=1))]
    else:
        ranges = list(batches(args.start_date, args.end_date + timedelta(days=1), args.batch_days))
    jobs = []
    for start_d, end_d in ranges:
        # SLD_FCST returns all TAC areas; filter target TAC_AREA_NAME values locally.
        if args.reports in ("all", "load"):
            jobs.append(("SLD_FCST", None, start_d, end_d))
        # SLD_REN_FCST returns all hubs and renewable types; filter SP15 locally.
        if args.reports in ("all", "renewable"):
            jobs.append(("SLD_REN_FCST", None, start_d, end_d))

    with args.manifest.open("a", encoding="utf-8") as mf:
        for index, (report, region, start_d, end_d) in enumerate(jobs, 1):
            start, end = local_midnight_utc(start_d), local_midnight_utc(end_d)
            url = query_url(report, start, end, **({"region": region} if region else {}))
            stem = f"{report.lower()}_{start_d}_{end_d - timedelta(days=1)}"
            if region:
                stem += "_" + region.lower().replace(" ", "_")
            path = args.out / report.lower() / f"{stem}.zip"
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {"requested_at_utc": datetime.now(timezone.utc).isoformat(),
                      "query_url": url, "queryname": report, "market_run_id": "DAM",
                      "region_parameter": region, "local_start_date": start_d.isoformat(),
                      "local_end_date_exclusive": end_d.isoformat(),
                      "utc_start": start.isoformat(), "utc_end": end.isoformat(),
                      "file": str(path), "status": "pending"}
            print(f"[{index}/{len(jobs)}] {url}", flush=True)
            try:
                status, result = fetch(url, path, args.retries, args.timeout)
                members = zip_summary(path)
                record.update({"http_status": status, "status": result,
                               "bytes": path.stat().st_size, "sha256": sha256(path),
                               "zip_members": members})
                if not members:
                    record.update({"status": "error",
                                   "error": "response ZIP contained no CSV member; inspect XML error/no-data response"})
            except Exception as exc:
                record.update({"status": "error", "error": str(exc)})
                if path.exists():
                    path.unlink()
            mf.write(json.dumps(record, ensure_ascii=False) + "\n")
            mf.flush()
            time.sleep(args.sleep_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
