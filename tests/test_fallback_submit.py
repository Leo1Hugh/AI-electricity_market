"""无网络的独立 naive fallback 测试。"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts import fallback_submit


def _history() -> pd.DataFrame:
    rows = []
    for day in pd.date_range("2026-10-20", "2026-10-29", freq="D"):
        for hour in range(1, 25):
            if day == pd.Timestamp("2026-10-29") and hour == 3:
                continue
            if day == pd.Timestamp("2026-10-28") and hour == 4:
                continue
            rows.append({"opr_dt": day.date(), "opr_hr": hour, "price": float(day.day + hour)})
    return pd.DataFrame(rows)


def test_fallback_has_24_hours_and_uses_recent_mean():
    source = _history()
    predictions, metadata = fallback_submit.build_fallback(source.rename(columns={"opr_dt": "day", "opr_hr": "hour", "price": "price_value"}), "2026-10-30")
    assert list(predictions.columns) == ["day", "hour", "price"]
    assert len(predictions) == 24
    assert predictions["hour"].tolist() == list(range(1, 25))
    assert predictions["price"].notna().all()
    # 2026-10-29 hour 3 is absent, so the seven-day mean path is used.
    expected = np.mean([day.day + 3 for day in pd.date_range("2026-10-23", "2026-10-28")])
    assert predictions.loc[predictions["hour"] == 3, "price"].iloc[0] == pytest.approx(expected)
    assert metadata["source_counts"]["recent_7d_mean"] >= 1


def test_missing_all_history_raises():
    source = pd.DataFrame({"day": [pd.Timestamp("2026-10-29")], "hour": [1], "price_value": [1.0]})
    with pytest.raises(ValueError, match="hour=2"):
        fallback_submit.build_fallback(source, "2026-10-30")


def test_cli_writes_schema_and_metadata(tmp_path: Path):
    hourly = tmp_path / "hourly.csv.gz"
    _history().to_csv(hourly, index=False, compression="gzip")
    out_dir = tmp_path / "submissions"
    assert fallback_submit.main(
        ["--as-of", "2026-10-30", "--hourly", str(hourly), "--out-dir", str(out_dir)]
    ) == 0
    target = out_dir / "2026-10-30"
    predictions = pd.read_csv(target / "predictions.csv")
    metadata = json.loads((target / "metadata.json").read_text(encoding="utf-8"))
    assert list(predictions.columns) == ["day", "hour", "price"]
    assert len(predictions) == 24
    assert metadata["model"] == "naive_fallback"
    assert metadata["validation"]["finite"] is True


def test_no_formal_pipeline_or_model_imports():
    tree = ast.parse(Path("scripts/fallback_submit.py").read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(name.startswith("em.pipeline") or name.startswith("em.models") for name in imports)


def test_dry_run_does_not_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    out_dir = tmp_path / "submissions"
    assert fallback_submit.main(["--as-of", "2026-10-30", "--out-dir", str(out_dir), "--dry-run"]) == 0
    assert "would_write" in capsys.readouterr().out
    assert not out_dir.exists()
