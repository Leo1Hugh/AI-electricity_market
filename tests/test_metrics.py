"""W2 指标的单元测试。"""

from __future__ import annotations

import numpy as np
import pytest

from em.backtest.metrics import daily_rmse, paired_block_bootstrap, summarize_daily_rmse


def test_daily_rmse_hand_computed() -> None:
    """逐日 RMSE 应沿小时轴聚合。"""
    y = np.array([[1.0, 2.0], [3.0, 4.0]])
    pred = np.array([[1.0, 3.0], [3.0, 6.0]])
    np.testing.assert_allclose(daily_rmse(y, pred), [np.sqrt(0.5), np.sqrt(2.0)])


def test_daily_rmse_all_nan_day() -> None:
    """没有有效配对观测的日期应为 NaN。"""
    y = np.array([[np.nan, np.nan], [1.0, 2.0]])
    pred = np.array([[1.0, 2.0], [1.0, 4.0]])
    got = daily_rmse(y, pred)
    assert np.isnan(got[0])
    assert got[1] == pytest.approx(np.sqrt(2.0))


def test_summarize_daily_rmse() -> None:
    """汇总统计包含线性插值 p90 和崩盘比例。"""
    got = summarize_daily_rmse(np.array([1.0, 2.0, 3.0, 4.0]), crash_threshold=3.5)
    assert got == {
        "n_days": 4,
        "mean": pytest.approx(2.5),
        "median": pytest.approx(2.5),
        "max": pytest.approx(4.0),
        "p90": pytest.approx(3.7),
        "crash_days": 1,
        "crash_rate": pytest.approx(0.25),
    }


def test_bootstrap_constant_diff() -> None:
    """常数差异的循环块 bootstrap 置信区间应退化为该常数。"""
    got = paired_block_bootstrap(np.ones(30), block=7, n_boot=200, seed=0)
    assert got["mean"] == pytest.approx(1.0)
    assert got["lo"] == pytest.approx(1.0)
    assert got["hi"] == pytest.approx(1.0)
    assert got["p_two_sided"] == pytest.approx(0.0)


def test_bootstrap_validates_arguments() -> None:
    """非法块长和空样本应有明确结果。"""
    with pytest.raises(ValueError):
        paired_block_bootstrap(np.arange(3), block=0)
    empty = paired_block_bootstrap(np.array([np.nan]))
    assert empty["mean"] != empty["mean"]
