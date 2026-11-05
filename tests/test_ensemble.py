"""集成和 naive 收缩测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from em.ensemble import mean_ensemble, shrink_to_naive


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
