"""提交 CLI 的 dry-run 和落盘 smoke 测试。"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

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
    assert metadata["model"] == predict_and_submit.FINAL_MODEL
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
    submission = json.loads((out_dir / "2024-03-30" / "submission.json").read_text())
    assert submission["model"] == predict_and_submit.FINAL_MODEL
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
    submission = json.loads((out_dir / "2024-03-30" / "submission.json").read_text())
    assert submission["model"] == "naive_only"
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


def test_no_refresh_missing_day_uses_cached_naive_only(tmp_path, monkeypatch) -> None:
    process_root, _ = _write_cached_panel(tmp_path, complete=False)
    monkeypatch.setattr(predict_and_submit, "PROCESS_ROOT", process_root)
    monkeypatch.setattr(
        predict_and_submit,
        "prepare_inputs",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cached panel lacks D")),
    )
    out_dir = tmp_path / "submissions"
    code = predict_and_submit.main(
        ["--as-of", "2024-03-30", "--out-dir", str(out_dir)]
    )
    assert code == 0
    metadata = json.loads((out_dir / "2024-03-30" / "metadata.json").read_text())
    assert metadata["naive_only"] is True
    assert metadata["model"] == "naive_only"


def test_refresh_fetch_uses_30_day_window(tmp_path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_fetch(argv):
        calls.append(list(argv))
        return 0

    def fake_rebuild(raw_root, price_root):
        return pd.DataFrame({"opr_dt": ["2026-10-30"], "opr_hr": [1]}), {}

    def fake_write(frame, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"hourly")

    import scripts.fetch_daily as fetch_daily
    import scripts.rebuild_hourly as rebuild_hourly

    monkeypatch.setattr(fetch_daily, "main", fake_fetch)
    monkeypatch.setattr(rebuild_hourly, "rebuild", fake_rebuild)
    monkeypatch.setattr(rebuild_hourly, "_write_deterministic", fake_write)
    target = tmp_path / "hourly_inference.csv.gz"
    predict_and_submit._refresh_and_rebuild_hourly(date(2026, 10, 30), target)
    assert calls
    assert calls[0][calls[0].index("--days") + 1] == "30"
    assert target.read_bytes() == b"hourly"


def test_file_invocation_adds_repo_root_to_syspath(tmp_path) -> None:
    """P0 回归：以 ``python scripts/predict_and_submit.py`` 方式启动（仓库根不在
    sys.path）时，脚本顶层必须把仓库根加入 sys.path，使 ``from scripts.fetch_daily
    import main`` / ``from scripts.rebuild_hourly import ...`` 可用，而不是抛
    ``ModuleNotFoundError`` 后被上层吞成 naive 回退。"""
    root = Path(predict_and_submit.__file__).resolve().parents[1]
    script = root / "scripts" / "predict_and_submit.py"

    probe = "\n".join(
        [
            "import sys, pathlib, importlib.util",
            "script = pathlib.Path(sys.argv[1])",
            "scripts_dir = str(script.parent)",
            # 复刻文件方式启动：sys.path[0] 是 scripts/，且排除 CWD（仓库根）。
            "sys.path = [scripts_dir] + [p for p in sys.path if p not in ('', '.', scripts_dir)]",
            # 以文件方式加载真实脚本（其顶层应把仓库根与 src/ 加进 sys.path）。
            "spec = importlib.util.spec_from_file_location('predict_and_submit', script)",
            "module = importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(module)",
            "root = str(script.parent.parent)",
            "assert root in sys.path, '仓库根未加入 sys.path'",
            # 文件方式启动下，这两个包导入必须可用（P0 的核心断言）。
            "import scripts.fetch_daily",
            "import scripts.rebuild_hourly",
            "print('P0_OK')",
        ]
    )

    proc = subprocess.run(
        [sys.executable, "-c", probe, str(script)],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "P0_OK" in proc.stdout

