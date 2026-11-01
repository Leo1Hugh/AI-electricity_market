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
import os
import re
import tempfile
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


def response_error(path: Path) -> str | None:
    """Return a CAISO XML error description, if the ZIP has no CSV response."""
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if not info.filename.lower().endswith(".xml"):
                continue
            text = zf.read(info).decode("utf-8", errors="replace")
            code = re.search(r"<m:ERR_CODE>([^<]+)", text)
            desc = re.search(r"<m:ERR_DESC>([^<]+)", text)
            if code or desc:
                return f"CAISO XML error {code.group(1) if code else 'unknown'}: {desc.group(1) if desc else 'unknown'}"
    return None


def validate_zip(path: Path) -> tuple[list[dict[str, object]], str | None]:
    """Validate ZIP integrity and return CSV metadata plus a response error."""
    with zipfile.ZipFile(path) as zf:
        bad_member = zf.testzip()
        if bad_member:
            raise ValueError(f"corrupt ZIP member: {bad_member}")
    members = zip_summary(path)
    if members:
        return members, None
    return [], response_error(path) or "response ZIP contained no CSV member"


def fetch_to_temp(url: str, directory: Path, retries: int, timeout: int) -> tuple[int, Path]:
    """Download to a same-directory temporary file; never touch the final path."""
    fd, temp_name = tempfile.mkstemp(prefix=".caiso-response-", suffix=".zip", dir=directory)
    temp_path = Path(temp_name)
    os.close(fd)
    last: Exception | None = None
    try:
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "AI-electricity_market/1.0"})
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    payload = response.read()
                    status = getattr(response, "status", 200)
                temp_path.write_bytes(payload)
                return status, temp_path
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
                if attempt < retries:
                    time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"download failed after {retries + 1} attempts: {last}")
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


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
    p.add_argument("--refresh-existing", action="store_true",
                   help="attempt a new response for existing paths, but never replace them")
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

    failures = 0
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
            if path.exists() and not args.refresh_existing:
                try:
                    members, response_problem = validate_zip(path)
                    record.update({"status": "skipped_existing",
                                   "bytes": path.stat().st_size,
                                   "sha256": sha256(path),
                                   "zip_members": members})
                    if response_problem:
                        failures += 1
                        record.update({"status": "error", "error": response_problem})
                except Exception as exc:
                    failures += 1
                    record.update({"status": "error", "error": f"existing file validation failed: {exc}"})
                mf.write(json.dumps(record, ensure_ascii=False) + "\n")
                mf.flush()
                time.sleep(args.sleep_seconds)
                continue
            temp_path: Path | None = None
            try:
                status, temp_path = fetch_to_temp(url, path.parent, args.retries, args.timeout)
                members, response_problem = validate_zip(temp_path)
                try:
                    os.link(temp_path, path)
                except FileExistsError as exc:
                    raise FileExistsError(f"target already exists; refusing to overwrite: {path}") from exc
                record.update({"http_status": status,
                               "status": "ok" if not response_problem else "error",
                               "bytes": path.stat().st_size,
                               "sha256": sha256(path),
                               "zip_members": members})
                if response_problem:
                    failures += 1
                    record["error"] = response_problem
            except Exception as exc:
                failures += 1
                record.update({"status": "error", "error": str(exc)})
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
            mf.write(json.dumps(record, ensure_ascii=False) + "\n")
            mf.flush()
            time.sleep(args.sleep_seconds)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
