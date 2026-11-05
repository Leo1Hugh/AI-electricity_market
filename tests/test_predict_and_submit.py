"""提交 CLI 的 dry-run 和落盘 smoke 测试。"""

from __future__ import annotations

import json

from em.io import save_panel
from em.testing import make_synthetic_panel
from scripts import predict_and_submit


def test_dry_run_does_not_write(tmp_path, capsys) -> None:
    out_dir = tmp_path / "submissions"
    code = predict_and_submit.main(
        ["--as-of", "2024-03-30", "--out-dir", str(out_dir), "--dry-run"]
    )
    assert code == 0
    assert not out_dir.exists()
    assert "would_write" in capsys.readouterr().out


def test_cli_smoke_writes_three_submission_files(tmp_path, monkeypatch) -> None:
    panel = make_synthetic_panel(n_days=90, start="2024-01-01", seed=24)
    panel_path = tmp_path / "panel.csv.gz"
    save_panel(panel, panel_path)
    hourly_path = tmp_path / "hourly.csv.gz"
    hourly_path.write_bytes(b"synthetic-hourly")
    monkeypatch.setattr(
        predict_and_submit,
        "prepare_inputs",
        lambda as_of, refresh_data: (hourly_path, panel_path),
    )
    out_dir = tmp_path / "submissions"
    code = predict_and_submit.main(["--as-of", "2024-03-30", "--out-dir", str(out_dir)])
    assert code == 0
    submission_dir = out_dir / "2024-03-30"
    assert (submission_dir / "predictions.csv").exists()
    assert (submission_dir / "metadata.json").exists()
    assert (submission_dir / "submission.json").exists()
    metadata = json.loads((submission_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["model"] == "shrink3_0.8"
    assert metadata["validation"]["ok"] is True
