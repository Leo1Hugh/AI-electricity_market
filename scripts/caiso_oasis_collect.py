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


def load_manifest(path: Path) -> tuple[list[dict[str, object]], dict[str, dict[str, object]], list[str]]:
    if not path.exists():
        return [], {}, []
    records: list[dict[str, object]] = []
    by_path: dict[str, dict[str, object]] = {}
    problems: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"manifest line {line_number} is invalid JSON: {exc}")
            continue
        file_name = record.get("file")
        if not isinstance(file_name, str) or not file_name:
            problems.append(f"manifest line {line_number} has no file path")
            continue
        records.append(record)
        if file_name in by_path:
            problems.append(f"manifest contains duplicate file path: {file_name}")
        else:
            by_path[file_name] = record
    return records, by_path, problems


def manifest_matches(record: dict[str, object], expected: dict[str, object], actual_sha: str,
                     check_file: bool = True) -> list[str]:
    fields = ("file", "query_url", "queryname", "market_run_id", "region_parameter",
              "local_start_date", "local_end_date_exclusive", "utc_start", "utc_end")
    if not check_file:
        fields = tuple(field for field in fields if field != "file")
    problems = [f"manifest field {field} differs" for field in fields if record.get(field) != expected.get(field)]
    if record.get("sha256") != actual_sha:
        problems.append("manifest SHA-256 differs from the existing file")
    return problems


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

    _, manifest_by_path, manifest_problems = load_manifest(args.manifest)
    manifest_by_query: dict[str, dict[str, object]] = {}
    for manifest_record in manifest_by_path.values():
        query = manifest_record.get("query_url")
        if isinstance(query, str) and query:
            if query in manifest_by_query:
                manifest_problems.append(f"manifest contains duplicate query URL: {query}")
            else:
                manifest_by_query[query] = manifest_record
    for file_name in manifest_by_path:
        if not Path(file_name).exists():
            manifest_problems.append(f"manifest references missing file: {file_name}")
    if manifest_problems:
        for problem in manifest_problems:
            print(f"ERROR: {problem}", flush=True)
        return 1

    failures = 0
    new_records: list[dict[str, object]] = []
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
            existing_record = manifest_by_path.get(str(path)) or manifest_by_query.get(url)
            existing_record_path = Path(str(existing_record.get("file"))) if existing_record else path
            if path.exists():
                try:
                    members, response_problem = validate_zip(path)
                    actual_sha = sha256(path)
                    record.update({"bytes": path.stat().st_size,
                                   "sha256": actual_sha, "zip_members": members})
                    if existing_record is not None:
                        problems = manifest_matches(existing_record, record, actual_sha,
                                                    check_file=existing_record_path == path)
                        if response_problem and existing_record.get("status") != "error":
                            problems.append("manifest status does not describe the existing error response")
                        if not response_problem and existing_record.get("status") not in {"ok", "skipped_existing"}:
                            problems.append("manifest status does not describe the existing CSV response")
                        if problems:
                            failures += 1
                            print(f"ERROR: {path}: {'; '.join(problems)}", flush=True)
                        elif existing_record.get("status") == "error":
                            failures += 1
                            print(f"ERROR: {path}: existing manifest record is an unresolved collection error", flush=True)
                    else:
                        record.update({"status": "error" if response_problem else "skipped_existing",
                                       "action": "registered_existing"})
                        if response_problem:
                            failures += 1
                            record["error"] = response_problem
                        new_records.append(record)
                        manifest_by_path[str(path)] = record
                        manifest_by_query[url] = record
                except Exception as exc:
                    failures += 1
                    print(f"ERROR: existing file validation failed for {path}: {exc}", flush=True)
                time.sleep(args.sleep_seconds)
                continue
            if existing_record is not None:
                if existing_record_path.exists():
                    try:
                        members, response_problem = validate_zip(existing_record_path)
                        actual_sha = sha256(existing_record_path)
                        problems = manifest_matches(existing_record, record, actual_sha, check_file=False)
                        if response_problem and existing_record.get("status") != "error":
                            problems.append("manifest status does not describe the existing error response")
                        if not response_problem and existing_record.get("status") not in {"ok", "skipped_existing"}:
                            problems.append("manifest status does not describe the existing CSV response")
                        if existing_record.get("status") == "error":
                            problems.append("existing manifest record is an unresolved collection error")
                        if problems:
                            failures += 1
                            print(f"ERROR: {existing_record_path}: {'; '.join(problems)}", flush=True)
                    except Exception as exc:
                        failures += 1
                        print(f"ERROR: existing manifest file validation failed for {existing_record_path}: {exc}", flush=True)
                else:
                    failures += 1
                    print(f"ERROR: manifest references missing target; refusing to download: {path}", flush=True)
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
                new_records.append(record)
                manifest_by_path[str(path)] = record
                manifest_by_query[url] = record
            except Exception as exc:
                failures += 1
                print(f"ERROR: {path}: {exc}", flush=True)
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
            time.sleep(args.sleep_seconds)
    if new_records:
        with args.manifest.open("a", encoding="utf-8") as mf:
            for record in new_records:
                mf.write(json.dumps(record, ensure_ascii=False) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
