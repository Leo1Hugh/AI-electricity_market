"""集成和 naive 收缩测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from em.ensemble import hourly_ensemble, mean_ensemble, shrink_to_naive


def _frame(values: list[float], model: str, y: list[float] | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "day": pd.to_datetime(["2024-01-01"] * len(values)),
            "hour": np.arange(1, len(values) + 1),
            "y": values if y is None else y,
            "pred": values,
            "model": model,
        }
    )


def test_mean_ensemble_normalizes_weights() -> None:
    y = [0.0, 0.0]
    left = _frame([1.0, 3.0], "left", y)
    right = _frame([5.0, 7.0], "right", y)
    got = mean_ensemble([left, right], weights=[1.0, 3.0])
    np.testing.assert_allclose(got["pred"], [4.0, 6.0])
    assert (got["model"] == "mean").all()


def test_shrink_and_strict_y_alignment() -> None:
    y = [0.0, 0.0]
    pred = _frame([10.0, 20.0], "pred", y)
    naive = _frame([2.0, 4.0], "naive", y)
    got = shrink_to_naive(pred, naive, weight=0.7)
    np.testing.assert_allclose(got["pred"], [7.6, 15.2])
    bad = naive.copy()
    bad.loc[0, "y"] = 99.0
    with pytest.raises(ValueError, match="y"):
        mean_ensemble([pred, bad])


def test_ensemble_rejects_missing_alignment() -> None:
    left = _frame([1.0, 3.0], "left", [0.0, 0.0])
    right = _frame([5.0], "right", [0.0])
    with pytest.raises(ValueError, match="键不一致"):
        mean_ensemble([left, right])


def _uniform_weight_table(*values: float) -> pd.DataFrame:
    """构造 24 行完全相同、4 列的权重表。"""
    return pd.DataFrame(
        np.tile(np.asarray(list(values), dtype=float), (24, 1)),
        index=np.arange(1, 25),
        columns=["r", "l", "m", "n"],
    )


def test_hourly_ensemble_with_default_table_matches_shrink3_0_8() -> None:
    """回归锁：均匀权重表必须与 0.8·mean3 + 0.2·naive 完全一致。"""
    y = [0.0] * 24
    ridge = _frame([1.0] * 24, "r", y)
    lgbm = _frame([3.0] * 24, "l", y)
    mtlasso = _frame([5.0] * 24, "m", y)
    naive = _frame([7.0] * 24, "n", y)
    expected = shrink_to_naive(mean_ensemble([ridge, lgbm, mtlasso]), naive, weight=0.8)
    got = hourly_ensemble(
        [ridge, lgbm, mtlasso, naive],
        _uniform_weight_table(0.8 / 3, 0.8 / 3, 0.8 / 3, 0.2),
    )
    np.testing.assert_allclose(got["pred"], expected["pred"])


def test_hourly_ensemble_changes_only_late_hours() -> None:
    """只允许改 19、20 时；其余小时必须保持 shrink3_0.8 口径。"""
    y = [0.0] * 24
    ridge = _frame([1.0] * 24, "r", y)
    lgbm = _frame([3.0] * 24, "l", y)
    mtlasso = _frame([5.0] * 24, "m", y)
    naive = _frame([7.0] * 24, "n", y)
    table = _uniform_weight_table(0.8 / 3, 0.8 / 3, 0.8 / 3, 0.2)
    table.loc[[19, 20]] = [0.35, 0.35, 0.10, 0.20]
    got = hourly_ensemble([ridge, lgbm, mtlasso, naive], table)
    base = shrink_to_naive(mean_ensemble([ridge, lgbm, mtlasso]), naive, weight=0.8)
    unchanged = ~got["hour"].isin([19, 20]).to_numpy()
    np.testing.assert_allclose(got.loc[unchanged, "pred"], base.loc[unchanged, "pred"])
    np.testing.assert_allclose(
        got.loc[got["hour"].isin([19, 20]), "pred"].to_numpy(dtype=float),
        [0.35 * 1.0 + 0.35 * 3.0 + 0.10 * 5.0 + 0.2 * 7.0] * 2,
    )


def test_hourly_ensemble_rejects_rows_that_do_not_sum_to_one() -> None:
    y = [0.0] * 24
    frames = [_frame([float(index)] * 24, str(index), y) for index in range(4)]
    table = _uniform_weight_table(0.8 / 3, 0.8 / 3, 0.8 / 3, 0.2)
    table.loc[19, "m"] = 0.5
    with pytest.raises(ValueError, match="之和必须为 1"):
        hourly_ensemble(frames, table)


def test_hourly_ensemble_rejects_missing_hours() -> None:
    y = [0.0] * 24
    frames = [_frame([float(index)] * 24, str(index), y) for index in range(4)]
    table = _uniform_weight_table(0.8 / 3, 0.8 / 3, 0.8 / 3, 0.2).drop(23)
    with pytest.raises(ValueError, match="1..24"):
        hourly_ensemble(frames, table)
