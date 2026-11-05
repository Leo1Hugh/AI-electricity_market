"""Naive 春季缺小时回退测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from em.models.naive import NaiveD1, NaiveD7, NaiveMean7


def test_naive_d1_falls_back_in_declared_order() -> None:
    frame = pd.DataFrame(
        {
            "p_lag1": [np.nan, np.inf, 3.0],
            "p_lag2": [12.0, np.nan, 2.0],
            "p_lagmean7": [11.0, 10.0, 1.0],
            "p_lag7": [9.0, 8.0, 0.0],
        }
    )
    np.testing.assert_allclose(NaiveD1().predict(frame), [12.0, 10.0, 3.0])


@pytest.mark.parametrize("model", [NaiveD1(), NaiveD7(), NaiveMean7()])
def test_naive_raises_when_all_candidates_missing(model) -> None:
    frame = pd.DataFrame(
        {
            "p_lag1": [np.nan],
            "p_lag2": [np.nan],
            "p_lag7": [np.nan],
            "p_lagmean7": [np.nan],
        }
    )
    with pytest.raises(ValueError, match="NaN/inf"):
        model.predict(frame)
