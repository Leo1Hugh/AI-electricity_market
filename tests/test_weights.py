"""分时段权重表的回归锁：只有中午 10-15 时与深夜 19、20 时偏离 shrink3_0.8 口径。"""

from __future__ import annotations

import numpy as np
import pytest

from em.weights import (
    BASE_WEIGHT,
    COMPONENTS,
    LATE_HOURS,
    LATE_MTLASSO_WEIGHT,
    MIDDAY_HOURS,
    MIDDAY_MTLASSO_WEIGHT,
    NAIVE_WEIGHT,
    TABLE_NAME,
    build_weight_table,
)


def test_weight_table_shape_and_unit_rows() -> None:
    table = build_weight_table()
    assert list(table.columns) == list(COMPONENTS)
    assert list(table.index) == list(range(1, 25))
    np.testing.assert_allclose(table.sum(axis=1).to_numpy(dtype=float), 1.0, atol=1e-12)
    assert TABLE_NAME == "mid_mtlasso_0.50_late_mtlasso_0.10"


def test_weight_table_matches_shrink3_0_8_outside_special_hours() -> None:
    """除 10-15 与 19、20 时外，权重必须与 0.8/3 + 0.2 naive 完全一致。"""
    table = build_weight_table()
    for hour in range(1, 25):
        row = table.loc[hour]
        if hour in MIDDAY_HOURS:
            assert row["mtlasso"] == pytest.approx(MIDDAY_MTLASSO_WEIGHT)
            assert row["ridge"] == pytest.approx(0.15)
            assert row["lgbm"] == pytest.approx(0.15)
            assert row["naive_d1"] == pytest.approx(NAIVE_WEIGHT)
        elif hour in LATE_HOURS:
            assert row["mtlasso"] == pytest.approx(LATE_MTLASSO_WEIGHT)
            assert row["ridge"] == pytest.approx(0.35)
            assert row["lgbm"] == pytest.approx(0.35)
            assert row["naive_d1"] == pytest.approx(NAIVE_WEIGHT)
        else:
            assert row["mtlasso"] == pytest.approx(BASE_WEIGHT)
            assert row["ridge"] == pytest.approx(BASE_WEIGHT)
            assert row["lgbm"] == pytest.approx(BASE_WEIGHT)
            assert row["naive_d1"] == pytest.approx(NAIVE_WEIGHT)
