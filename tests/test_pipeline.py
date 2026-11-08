"""最终提交 pipeline 的截止、确定性和 fallback 测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

import em.pipeline as pipeline
from em.pipeline import prepare_inference, run_pipeline
from em.testing import make_synthetic_panel


def test_training_cutoff_and_determinism() -> None:
    panel = make_synthetic_panel(n_days=90, start="2024-01-01", seed=21)
    as_of = pd.Timestamp("2024-03-30")
    train, test, missing = prepare_inference(panel, as_of)
    assert train["day"].max() < as_of
    assert len(test) == 24
    assert missing == []
    first = run_pipeline(panel, as_of)
    second = run_pipeline(panel, as_of)
    np.testing.assert_allclose(first.predictions["price"], second.predictions["price"])
    assert first.metadata["train_end"] < str(as_of.date())
    assert first.metadata["model"] == "shrink3_0.8"
    assert len(first.predictions) == 24
    assert np.isfinite(first.predictions["price"]).all()


def test_component_failure_falls_back_to_naive(monkeypatch) -> None:
    panel = make_synthetic_panel(n_days=90, start="2024-01-01", seed=22)

    class BrokenMTLasso:
        def __init__(self, *args, **kwargs):
            pass

        def fit(self, *args, **kwargs):
            raise RuntimeError("simulated mtlasso failure")

    monkeypatch.setattr(pipeline, "MultiTaskLassoModel", BrokenMTLasso)
    result = run_pipeline(panel, "2024-03-30")
    assert result.metadata["fallback"] is True
    assert "组件失败" in result.metadata["fallback_reason"]
    assert result.metadata["model"] == "naive_fallback"
    assert result.metadata["base_model"] == "shrink3_0.8"
    assert result.metadata["component_status"]["fallback"] == "naive"
    assert len(result.predictions) == 24
    assert np.isfinite(result.predictions["price"]).all()


def test_missing_hours_trigger_fallback_and_restore_24_points() -> None:
    panel = make_synthetic_panel(n_days=90, start="2024-01-01", seed=23)
    as_of = pd.Timestamp("2024-03-30")
    panel = panel.loc[
        ~((panel["day"] == as_of) & panel["hour"].isin([3, 4, 5]))
    ].copy()
    result = run_pipeline(panel, as_of)
    assert result.metadata["fallback"] is True
    assert result.metadata["model"] == "naive_fallback"
    assert "feature_missing" in result.metadata
    assert list(result.predictions["hour"]) == list(range(1, 25))
    assert result.metadata["validation"]["ok"] is True


def test_incomplete_d_features_trigger_structured_naive_fallback() -> None:
    panel = make_synthetic_panel(n_days=90, start="2024-01-01", seed=26)
    as_of = pd.Timestamp("2024-03-30")
    panel.loc[(panel["day"] == as_of) & (panel["hour"] <= 24), "load_caiso"] = np.nan
    result = run_pipeline(panel, as_of)
    assert result.metadata["fallback"] is True
    assert result.metadata["model"] == "naive_fallback"
    assert "load_caiso" in result.metadata["feature_missing"]["columns"]
    assert result.metadata["feature_missing"]["hours"]
    expected = panel.loc[(panel["day"] == as_of), "p_lag1"].to_numpy(dtype=float)
    np.testing.assert_allclose(result.predictions["price"], expected)


def test_all_d_features_missing_uses_recent_mean() -> None:
    panel = make_synthetic_panel(n_days=90, start="2024-01-01", seed=27)
    as_of = pd.Timestamp("2024-03-30")
    d_rows = panel["day"] == as_of
    for column in pipeline.PRICE_LAG_FEATURES + pipeline.EXOG_FEATURES:
        panel.loc[d_rows, column] = np.nan
    result = run_pipeline(panel, as_of)
    assert result.metadata["model"] == "naive_fallback"
    assert len(result.predictions) == 24
    assert np.isfinite(result.predictions["price"]).all()
