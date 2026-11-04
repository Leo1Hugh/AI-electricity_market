"""Minimal checks for the leakage audit report and static scanner."""

from __future__ import annotations

from pathlib import Path

from scripts import audit_leakage


def test_static_scan_and_panel_input_pass():
    checks = audit_leakage._static_scan(Path.cwd())
    checks.append(audit_leakage._panel_input_check(Path.cwd()))
    assert checks
    assert all(check.passed for check in checks), checks


def test_report_mentions_accepted_history_limitation(tmp_path: Path):
    checks = [audit_leakage.Check("synthetic", True, "ok")]
    report = audit_leakage._render(checks, tmp_path / "hourly.csv.gz")
    assert "没有可证明的版本发布时间" in report
    assert "synthetic" in report
