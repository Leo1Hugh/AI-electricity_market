"""日级 MultiTaskLasso 模型测试。"""

from __future__ import annotations

import numpy as np

from em.models.mtlasso import MultiTaskLassoModel
from em.testing import make_synthetic_panel


def test_mtlasso_returns_24_rows_per_day_and_is_deterministic() -> None:
    panel = make_synthetic_panel(n_days=100, start="2024-01-01", seed=7)
    train = panel[panel["day"] < "2024-03-01"]
    test = panel[panel["day"] >= "2024-03-01"].head(48)
    first = MultiTaskLassoModel(alpha=0.1).fit(train, ["p_lag1", "load_caiso"])
    pred1 = first.predict(test)
    second = MultiTaskLassoModel(alpha=0.1).fit(train, ["p_lag1", "load_caiso"])
    pred2 = second.predict(test)
    assert list(pred1.columns) == ["day", "hour", "pred"]
    assert pred1.groupby("day").size().eq(24).all()
    assert np.isfinite(pred1["pred"]).all()
    np.testing.assert_allclose(pred1["pred"], pred2["pred"])


def test_mtlasso_does_not_use_test_rows_for_fill_statistics() -> None:
    panel = make_synthetic_panel(n_days=100, start="2024-01-01", seed=8)
    train = panel[panel["day"] < "2024-03-01"].copy()
    test = panel[panel["day"] >= "2024-03-01"].copy()
    # A value only in the test period must not alter the fitted model.
    test.loc[:, "load_caiso"] = 1e9
    model = MultiTaskLassoModel(alpha=0.1).fit(train, ["p_lag1", "load_caiso"])
    pred = model.predict(test.head(24))
    assert len(pred) == 24
    assert np.isfinite(pred["pred"]).all()


def test_mtlasso_missing_predict_column_uses_training_median() -> None:
    panel = make_synthetic_panel(n_days=90, start="2024-01-01", seed=9)
    train = panel[panel["day"] < "2024-03-01"]
    test = panel[panel["day"] >= "2024-03-01"].head(24).drop(columns=["load_caiso"])
    model = MultiTaskLassoModel(alpha=0.1).fit(train, ["p_lag1", "load_caiso"])
    pred = model.predict(test)
    assert len(pred) == 24
    assert np.isfinite(pred["pred"]).all()
