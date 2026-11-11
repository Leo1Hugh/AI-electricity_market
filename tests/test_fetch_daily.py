"""Tests for the daily refresh boundary without making HTTP requests."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from scripts import fetch_daily


def _zip(path: Path, text: str = "a,b\n1,2\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("response.csv", text)


def _job(tmp_path: Path) -> fetch_daily.Job:
    return fetch_daily._jobs(fetch_daily.date(2026, 11, 24), 7, tmp_path)[0]


def test_refresh_archives_old_and_appends_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    job = _job(tmp_path)
    job.path.parent.mkdir(parents=True)
    job.path.write_bytes(b"old-response")
    new_zip = tmp_path / "new.zip"
    _zip(new_zip, "a,b\n9,8\n")

    def fake_fetch(url, directory, retries, timeout):
        target = Path(directory) / ".mock-response.zip"
        target.write_bytes(new_zip.read_bytes())
        return 200, target

    monkeypatch.setattr(fetch_daily, "fetch_to_temp", fake_fetch)
    old_digest = fetch_daily.sha256(job.path)
    record = fetch_daily._process_job(job, refresh=True)

    assert record["action"] == "replaced"
    assert record["old_sha256"] == old_digest
    assert record["new_sha256"] == fetch_daily.sha256(job.path)
    archived = list((tmp_path / "revisions" / "prc_lmp").rglob(job.path.name))
    assert len(archived) == 1
    assert archived[0].read_bytes() == b"old-response"
    assert job.path.read_bytes() == new_zip.read_bytes()


def test_failed_download_keeps_old_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    job = _job(tmp_path)
    job.path.parent.mkdir(parents=True)
    original = b"keep-this-byte-for-byte"
    job.path.write_bytes(original)

    def fail_fetch(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(fetch_daily, "fetch_to_temp", fail_fetch)
    with pytest.raises(RuntimeError, match="network down"):
        fetch_daily._process_job(job, refresh=True)
    assert job.path.read_bytes() == original
    assert not (tmp_path / "revisions").exists()


def test_existing_without_refresh_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    job = _job(tmp_path)
    job.path.parent.mkdir(parents=True)
    _zip(job.path)

    def should_not_fetch(*args, **kwargs):
        raise AssertionError("skip must not make an HTTP request")

    monkeypatch.setattr(fetch_daily, "fetch_to_temp", should_not_fetch)
    record = fetch_daily._process_job(job, refresh=False)
    assert record["action"] == "skipped"
    assert record["status"] == "skipped"


def test_dry_run_does_not_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    root = tmp_path / "raw"
    manifest = tmp_path / "manifest.jsonl"
    assert fetch_daily.main(
        ["--as-of", "2026-11-24", "--days", "7", "--root", str(root), "--manifest", str(manifest), "--dry-run"]
    ) == 0
    output = capsys.readouterr().out
    assert output.count("https://oasis.caiso.com/oasisapi/SingleZip?") == 3
    assert not root.exists()
    assert not manifest.exists()


def test_prc_lmp_uses_version12_without_lmp_type(tmp_path: Path):
    job = _job(tmp_path)
    params = parse_qs(urlparse(job.url).query)
    assert params["version"] == ["12"]
    assert params["node"] == ["TH_SP15_GEN-APND"]
    assert "lmp_type" not in params
