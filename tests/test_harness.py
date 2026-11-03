"""W2 回测 harness 的单元测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from em.contracts import BASE_FEATURES
from em.backtest.harness import fixed_window, monthly_walk_forward
from em.models.naive import NaiveD1
from em.models.ridge import RidgeModel
from em.testing import make_synthetic_panel


def test_monthly_walk_forward_no_leakage() -> None:
    """月滚动应有三个折且训练截止日早于测试起点。"""
    panel = make_synthetic_panel(n_days=180, start="2024-01-01", seed=11)
    result = monthly_walk_forward(
        panel,
        NaiveD1,
        ["p_lag1"],
        "2024-04-01",
        "2024-06-30",
    )
    assert list(result.predictions.columns) == ["day", "hour", "y", "pred", "model"]
    assert list(result.folds.columns) == [
        "model", "train_start", "train_end", "test_start", "test_end", "n_train", "n_test"
    ]
    assert len(result.folds) == 3
    assert (result.folds["train_end"] < result.folds["test_start"]).all()
    assert np.isfinite(result.predictions["pred"]).all()
    merged = result.predictions.merge(panel[["day", "hour", "p_lag1"]], on=["day", "hour"])
    np.testing.assert_allclose(merged["pred"], merged["p_lag1"])


def test_fixed_window_one_fold() -> None:
    """固定窗口只训练一个折并覆盖闭区间。"""
    panel = make_synthetic_panel(n_days=180, start="2024-01-01", seed=11)
    result = fixed_window(panel, NaiveD1, ["p_lag1"], "2024-05-01", "2024-05-14")
    assert len(result.folds) == 1
    assert result.folds.loc[0, "train_end"] < result.folds.loc[0, "test_start"]
    assert result.predictions["day"].min() == pd.Timestamp("2024-05-01")
    assert result.predictions["day"].max() == pd.Timestamp("2024-05-14")


def test_ridge_handles_nan_features() -> None:
    """Ridge 的填充和标准化只能从训练集学习且能处理 NaN。"""
    panel = make_synthetic_panel(n_days=180, start="2024-01-01", seed=11)
    train = panel[panel["day"] < pd.Timestamp("2024-05-01")].copy()
    test = panel[panel["day"] >= pd.Timestamp("2024-05-01")].head(24).copy()
    train.loc[train.index[0], BASE_FEATURES[0]] = np.nan
    test.loc[test.index[0], BASE_FEATURES[1]] = np.nan
    pred = RidgeModel().fit(train[list(BASE_FEATURES)], train["y"]).predict(test[list(BASE_FEATURES)])
    assert pred.shape == (len(test),)
    assert np.isfinite(pred).all()
