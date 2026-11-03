"""W2 的验收测试：回测与模型接口必须满足 docs/建模契约_v1.md。"""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from em import contracts as C
from em.testing import make_synthetic_panel

try:
    _spec = importlib.util.find_spec("em.backtest.harness")
except ModuleNotFoundError:
    _spec = None
if _spec is None:
    pytest.skip("W2 回测模块尚未合并", allow_module_level=True)

from em.backtest import harness, metrics  # noqa: E402
from em.models.lgbm import LGBMModel  # noqa: E402
from em.models.naive import NaiveD1  # noqa: E402
from em.models.ridge import RidgeModel  # noqa: E402


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return make_synthetic_panel(n_days=180, start="2024-01-01", seed=11)


def test_daily_rmse_hand_computed():
    y = np.array([[1.0, 2.0], [3.0, 4.0]])
    p = np.array([[1.0, 3.0], [3.0, 6.0]])
    got = metrics.daily_rmse(y, p)
    np.testing.assert_allclose(got, [np.sqrt(0.5), np.sqrt(2.0)])


def test_summarize_daily_rmse():
    got = metrics.summarize_daily_rmse(np.array([1.0, 2.0, 3.0, 4.0]), crash_threshold=3.5)
    assert got["n_days"] == 4
    assert got["mean"] == pytest.approx(2.5)
    assert got["median"] == pytest.approx(2.5)
    assert got["max"] == pytest.approx(4.0)
    assert got["p90"] == pytest.approx(3.7)
    assert got["crash_days"] == 1
    assert got["crash_rate"] == pytest.approx(0.25)


def test_bootstrap_constant_diff():
    got = metrics.paired_block_bootstrap(np.ones(30), block=7, n_boot=200, seed=0)
    assert got["mean"] == pytest.approx(1.0)
    assert got["lo"] == pytest.approx(1.0)
    assert got["hi"] == pytest.approx(1.0)
    assert got["p_two_sided"] == pytest.approx(0.0)


def test_monthly_walk_forward_no_leakage(panel: pd.DataFrame):
    res = harness.monthly_walk_forward(
        panel, NaiveD1, ["p_lag1"],
        pd.Timestamp("2024-04-01"), pd.Timestamp("2024-06-30"),
    )
    assert list(res.predictions.columns) == ["day", "hour", "y", "pred", "model"]
    assert list(res.folds.columns) == [
        "model", "train_start", "train_end", "test_start", "test_end", "n_train", "n_test"
    ]
    assert len(res.folds) == 3
    assert (res.folds["train_end"] < res.folds["test_start"]).all()
    assert res.predictions["pred"].notna().all()
    assert res.predictions["day"].between(pd.Timestamp("2024-04-01"), pd.Timestamp("2024-06-30")).all()
    merged = res.predictions.merge(panel[["day", "hour", "p_lag1"]], on=["day", "hour"], how="left")
    np.testing.assert_allclose(merged["pred"], merged["p_lag1"], equal_nan=True)


def test_fixed_window_no_leakage(panel: pd.DataFrame):
    res = harness.fixed_window(
        panel, NaiveD1, ["p_lag1"],
        pd.Timestamp("2024-05-01"), pd.Timestamp("2024-05-14"),
    )
    assert len(res.folds) == 1
    assert res.folds.loc[0, "train_end"] < res.folds.loc[0, "test_start"]
    assert res.predictions["day"].min() == pd.Timestamp("2024-05-01")
    assert res.predictions["day"].max() == pd.Timestamp("2024-05-14")


def test_ridge_smoke(panel: pd.DataFrame):
    train = panel[panel["day"] < pd.Timestamp("2024-05-01")]
    test = panel[(panel["day"] >= pd.Timestamp("2024-05-01")) & (panel["day"] <= pd.Timestamp("2024-05-14"))]
    model = RidgeModel(alpha=10.0).fit(train[list(C.BASE_FEATURES)], train["y"])
    pred = model.predict(test[list(C.BASE_FEATURES)])
    assert pred.shape == (len(test),)
    assert np.isfinite(pred).all()


def test_lgbm_smoke(panel: pd.DataFrame):
    train = panel[panel["day"] < pd.Timestamp("2024-05-01")]
    test = panel[(panel["day"] >= pd.Timestamp("2024-05-01")) & (panel["day"] <= pd.Timestamp("2024-05-14"))]
    model = LGBMModel({"n_estimators": 40, "n_jobs": 1}).fit(train[list(C.BASE_FEATURES)], train["y"])
    pred = model.predict(test[list(C.BASE_FEATURES)])
    assert pred.shape == (len(test),)
    assert np.isfinite(pred).all()
