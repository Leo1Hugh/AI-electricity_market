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


def _write_cached_panel(tmp_path, *, complete: bool):
    panel = make_synthetic_panel(n_days=90 if complete else 89, start="2024-01-01", seed=25)
    process_root = tmp_path / "process"
    process_root.mkdir(parents=True)
    panel_path = process_root / "panel_inference.csv.gz"
    save_panel(panel, panel_path)
    return process_root, panel_path


def test_refresh_failure_uses_complete_cached_panel(tmp_path, monkeypatch) -> None:
    process_root, _ = _write_cached_panel(tmp_path, complete=True)
    monkeypatch.setattr(predict_and_submit, "PROCESS_ROOT", process_root)
    monkeypatch.setattr(
        predict_and_submit,
        "prepare_inputs",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("simulated fetch failure")),
    )
    out_dir = tmp_path / "submissions"
    code = predict_and_submit.main(
        ["--as-of", "2024-03-30", "--refresh-data", "--out-dir", str(out_dir)]
    )
    assert code == 0
    metadata = json.loads((out_dir / "2024-03-30" / "metadata.json").read_text())
    assert metadata["data_stale"] is True
    assert metadata["fallback"] is True
    assert metadata["naive_only"] is False
    assert "refresh failed" in metadata["fallback_reason"]
    assert len((out_dir / "2024-03-30" / "predictions.csv").read_text().splitlines()) == 25


def test_refresh_failure_missing_day_uses_naive_only(tmp_path, monkeypatch) -> None:
    process_root, _ = _write_cached_panel(tmp_path, complete=False)
    monkeypatch.setattr(predict_and_submit, "PROCESS_ROOT", process_root)
    monkeypatch.setattr(
        predict_and_submit,
        "prepare_inputs",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("simulated rebuild failure")),
    )
    out_dir = tmp_path / "submissions"
    code = predict_and_submit.main(
        ["--as-of", "2024-03-30", "--refresh-data", "--out-dir", str(out_dir)]
    )
    assert code == 0
    metadata = json.loads((out_dir / "2024-03-30" / "metadata.json").read_text())
    assert metadata["data_stale"] is True
    assert metadata["fallback"] is True
    assert metadata["naive_only"] is True
    predictions = (out_dir / "2024-03-30" / "predictions.csv").read_text().splitlines()
    assert len(predictions) == 25


def test_refresh_and_cache_failure_returns_nonzero(tmp_path, monkeypatch, capsys) -> None:
    process_root = tmp_path / "process"
    monkeypatch.setattr(predict_and_submit, "PROCESS_ROOT", process_root)
    monkeypatch.setattr(
        predict_and_submit,
        "prepare_inputs",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("all sources unavailable")),
    )
    code = predict_and_submit.main(
        ["--as-of", "2024-03-30", "--refresh-data", "--out-dir", str(tmp_path / "out")]
    )
    assert code == 1
    assert "refresh failed" in capsys.readouterr().err
