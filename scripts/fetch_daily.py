#!/usr/bin/env python3
"""Fetch a small, auditable CAISO revision window.

The batch collector in :mod:`caiso_oasis_collect` deliberately refuses to
overwrite an existing response.  This entry point is for the daily run: it
can refresh the latest seven local trading days while preserving the previous
ZIP and appending an immutable JSONL manifest record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

try:  # Works both as ``python scripts/fetch_daily.py`` and as a package import.
    from scripts.caiso_oasis_collect import (
        fetch_to_temp,
        local_midnight_utc,
        query_url,
        response_error,
        zip_summary,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI form.
    from caiso_oasis_collect import (  # type: ignore[no-redef]
        fetch_to_temp,
        local_midnight_utc,
        query_url,
        response_error,
        zip_summary,
    )


LOCAL_TZ = ZoneInfo("America/Los_Angeles")
DEFAULT_ROOT = Path("data/raw/caiso")
DEFAULT_MANIFEST = Path("data/caiso_collection_manifest.jsonl")


@dataclass(frozen=True)
class Job:
    """One report request for an inclusive local-date window."""

    report: str
    subdir: str
    start: date
    end: date
    url: str
    path: Path


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _window(as_of: date, days: int) -> tuple[date, date]:
    """Return the inclusive local-date window ending at ``as_of``."""
    if days < 1:
        raise ValueError("--days must be positive")
    return as_of - timedelta(days=days - 1), as_of


def _jobs(as_of: date, days: int, root: Path) -> list[Job]:
    """Build the three report requests without touching the filesystem."""
    start, end = _window(as_of, days)
    utc_start = local_midnight_utc(start)
    utc_end = local_midnight_utc(end + timedelta(days=1))
    reports: tuple[tuple[str, str, dict[str, str]], ...] = (
        (
            "PRC_LMP",
            "prc_lmp",
            {"node": "TH_SP15_GEN-APND", "version": "12"},
        ),
        ("SLD_FCST", "sld_fcst", {}),
        ("SLD_REN_FCST", "sld_ren_fcst", {}),
    )
    jobs: list[Job] = []
    for report, subdir, extra in reports:
        url = query_url(report, utc_start, utc_end, **extra)
        path = root / subdir / f"{report.lower()}_{start}_{end}.zip"
        jobs.append(Job(report, subdir, start, end, url, path))
    return jobs


def _validate_response(path: Path) -> list[dict[str, object]]:
    """Validate a downloaded ZIP and return its CSV member summaries."""
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise ValueError(f"corrupt ZIP member: {bad_member}")
    members = zip_summary(path)
    error = response_error(path)
    if not members:
        raise ValueError(error or "response ZIP contained no CSV member")
    if error:
        raise ValueError(error)
    return members


def _row_count(members: Iterable[dict[str, object]]) -> int:
    """Count CSV records represented by ``zip_summary`` output."""
    return sum(int(item.get("rows", 0) or 0) for item in members)


def _archive(path: Path, root: Path, report: str) -> Path:
    """Move an old response to its UTC-timestamped revision directory."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = root / "revisions" / report.lower() / timestamp
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / path.name
    os.replace(path, destination)
    return destination


def _manifest_record(
    job: Job,
    *,
    status: str,
    action: str,
    http_status: int | None,
    digest: str,
    rows: int,
    old_digest: str | None = None,
    new_digest: str | None = None,
    archived_file: Path | None = None,
) -> dict[str, object]:
    """Create the stable, append-only manifest shape used by this pipeline."""
    record: dict[str, object] = {
        "time": datetime.now(timezone.utc).isoformat(),
        "query_url": job.url,
        "queryname": job.report,
        "start": job.start.isoformat(),
        "end": job.end.isoformat(),
        "local_start_date": job.start.isoformat(),
        "local_end_date_exclusive": (job.end + timedelta(days=1)).isoformat(),
        "file": job.path.as_posix(),
        "status": status,
        "http_status": http_status,
        "sha256": digest,
        "rows": rows,
        "action": action,
    }
    if old_digest is not None:
        record["old_sha256"] = old_digest
    if new_digest is not None:
        record["new_sha256"] = new_digest
    if archived_file is not None:
        record["archived_file"] = archived_file.as_posix()
    return record


def _append_manifest(path: Path, records: Iterable[dict[str, object]]) -> None:
    """Append records to JSONL, preserving all previous history."""
    records = list(records)
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _process_job(job: Job, *, refresh: bool, retries: int = 3, timeout: int = 60) -> dict[str, object]:
    """Download, validate, atomically install, and describe one report."""
    job.path.parent.mkdir(parents=True, exist_ok=True)
    existing = job.path if job.path.exists() else None
    if existing is not None and not refresh:
        try:
            members = _validate_response(existing)
        except Exception:
            # A non-refresh run is explicitly a no-write skip.  Preserve the
            # file byte-for-byte even when an older manifest did not contain
            # enough metadata to validate its response here.
            members = []
        digest = sha256(existing)
        return _manifest_record(
            job,
            status="skipped",
            action="skipped",
            http_status=None,
            digest=digest,
            rows=_row_count(members),
        )

    status_code, temporary = fetch_to_temp(job.url, job.path.parent, retries=retries, timeout=timeout)
    archived: Path | None = None
    try:
        members = _validate_response(temporary)
        new_digest = sha256(temporary)
        old_digest = sha256(existing) if existing is not None else None
        if existing is not None and refresh:
            archived = _archive(existing, job.path.parent.parent, job.report)
        try:
            os.replace(temporary, job.path)
        except Exception:
            if archived is not None and not job.path.exists():
                os.replace(archived, job.path)
                archived = None
            raise
        return _manifest_record(
            job,
            status="ok",
            action="replaced" if old_digest is not None else "created",
            http_status=status_code,
            digest=new_digest,
            rows=_row_count(members),
            old_digest=old_digest,
            new_digest=new_digest if old_digest is not None else None,
            archived_file=archived,
        )
    finally:
        temporary.unlink(missing_ok=True)


def _default_as_of() -> date:
    """Return today's date in the CAISO trading timezone."""
    return datetime.now(LOCAL_TZ).date()


def main(argv: list[str] | None = None) -> int:
    """Run the daily fetch CLI and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--refresh", action="store_true", help="archive and replace existing ZIPs")
    parser.add_argument("--dry-run", action="store_true", help="print requests without writing files")
    args = parser.parse_args(argv)
    as_of = args.as_of or _default_as_of()
    try:
        jobs = _jobs(as_of, args.days, args.root)
    except ValueError as exc:
        parser.error(str(exc))

    if args.dry_run:
        for job in jobs:
            operation = "would replace" if job.path.exists() and args.refresh else (
                "would skip" if job.path.exists() else "would download"
            )
            print(f"{job.report}: {job.url}")
            print(f"  {operation}: {job.path}")
        return 0

    records: list[dict[str, object]] = []
    failures = 0
    for job in jobs:
        try:
            record = _process_job(job, refresh=args.refresh)
            records.append(record)
            print(f"{job.report}: {record['action']} {job.path}")
        except Exception as exc:
            failures += 1
            print(f"ERROR {job.report}: {exc}")
    _append_manifest(args.manifest, records)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
