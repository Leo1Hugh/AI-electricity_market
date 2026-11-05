"""比较 CLI 的合成面板 smoke 测试。"""

from __future__ import annotations

import json

from em.testing import make_synthetic_panel
from scripts import run_compare


def test_compare_writes_five_outputs(tmp_path) -> None:
    panel = make_synthetic_panel(n_days=180, start="2024-01-01", seed=13)
    panel_path = tmp_path / "panel.csv.gz"
    panel.to_csv(panel_path, index=False, compression="gzip")
    out_root = tmp_path / "out"
    code = run_compare.main(
        [
            "--panel",
            str(panel_path),
            "--mode",
            "annual",
            "--start",
            "2024-04-01",
            "--end",
            "2024-06-30",
            "--out",
            str(out_root),
            "--features",
            "base",
        ]
    )
    assert code == 0
    run_dir = next(out_root.iterdir())
    for name in ("predictions.csv", "daily_metrics.csv", "folds.csv", "metrics.json", "summary.md"):
        assert (run_dir / name).exists()
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert set(metrics["models"]) == {
        "naive_d1", "ridge", "lgbm", "mtlasso", "mean2", "mean3", "shrink"
    }
