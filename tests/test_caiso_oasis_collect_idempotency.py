from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import caiso_oasis_collect as collector

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_NAME = "sld_fcst_2026-10-30_2026-10-30.zip"


class CollectorIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(REPO_ROOT / "data" / "raw" / "caiso", self.root / "raw")
        records = []
        source_manifest = REPO_ROOT / "data" / "caiso_collection_manifest.jsonl"
        for line in source_manifest.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                relative = Path(record["file"]).relative_to(Path("data/raw/caiso"))
                record["file"] = str(self.root / "raw" / relative)
                records.append(record)
        self.manifest = self.root / "manifest.jsonl"
        self.manifest.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
        self.sample = self.root / "raw" / "sld_fcst" / SAMPLE_NAME

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_collector(self, *extra: str) -> int:
        old_argv = sys.argv
        sys.argv = ["caiso_oasis_collect.py", "--sample-only", "--reports", "load",
                    "--out", str(self.root / "raw"), "--manifest", str(self.manifest),
                    "--sleep-seconds", "0", "--retries", "0", *extra]
        try:
            return collector.main()
        finally:
            sys.argv = old_argv

    def run_verify(self) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([
            sys.executable, str(REPO_ROOT / "scripts" / "verify_caiso_forecasts.py"),
            "--root", str(self.root / "raw"), "--manifest", str(self.manifest),
            "--report", str(self.root / "report.md"), "--start-date", "2023-11-01",
            "--end-date", "2026-10-31", "--allow-known-missing",
        ], cwd=REPO_ROOT, env=env, text=True, capture_output=True, check=False)

    def test_existing_sample_is_verified_then_repeat_is_idempotent(self) -> None:
        self.assertEqual(self.run_verify().returncode, 0)
        before_hash = hashlib.sha256(self.sample.read_bytes()).hexdigest()
        before_lines = self.manifest.read_text(encoding="utf-8").splitlines()
        with patch.object(collector, "fetch_to_temp", side_effect=AssertionError("existing ZIP must not be downloaded")):
            self.assertEqual(self.run_collector(), 0)
        self.assertEqual(before_hash, hashlib.sha256(self.sample.read_bytes()).hexdigest())
        after_lines = self.manifest.read_text(encoding="utf-8").splitlines()
        self.assertEqual(before_lines, after_lines)
        paths = [json.loads(line)["file"] for line in after_lines]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(self.run_verify().returncode, 0)

    def test_existing_file_without_manifest_record_is_registered_once(self) -> None:
        records = [json.loads(line) for line in self.manifest.read_text(encoding="utf-8").splitlines()]
        records = [record for record in records if record["file"] != str(self.sample)]
        self.manifest.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
        with patch.object(collector, "fetch_to_temp", side_effect=AssertionError("existing ZIP must not be downloaded")):
            self.assertEqual(self.run_collector(), 0)
        records = [json.loads(line) for line in self.manifest.read_text(encoding="utf-8").splitlines()]
        matching = [record for record in records if record["file"] == str(self.sample)]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["action"], "registered_existing")
        self.assertEqual(self.run_verify().returncode, 0)

    def test_manifest_mismatch_fails_without_mutating_zip(self) -> None:
        before_hash = hashlib.sha256(self.sample.read_bytes()).hexdigest()
        records = [json.loads(line) for line in self.manifest.read_text(encoding="utf-8").splitlines()]
        for record in records:
            if record["file"] == str(self.sample):
                record["sha256"] = "0" * 64
        self.manifest.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
        with patch.object(collector, "fetch_to_temp", side_effect=AssertionError("manifest mismatch must not download")):
            self.assertEqual(self.run_collector(), 1)
        self.assertEqual(before_hash, hashlib.sha256(self.sample.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
