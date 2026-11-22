"""中午常数偏移的拟合与施加逻辑测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from em.calibration import (
    MAX_ABS_OFFSET,
    MIDDAY_HOURS,
    MIN_DAYS,
    apply_hourly_offset,
    fit_midday_offset,
)


def _residuals(days: int, mean_resid: float) -> pd.DataFrame:
    dates = pd.date_range("2025-11-01", periods=days, freq="D")
    rows = [{"day": day, "hour": hour, "resid": mean_resid} for day in dates for hour in range(1, 25)]
    return pd.DataFrame(rows)


def test_fit_requires_minimum_days() -> None:
    offset, info = fit_midday_offset(_residuals(MIN_DAYS - 1, -5.0))
    assert offset == 0.0
    assert info["applied"] is False


def test_fit_returns_negated_mean() -> None:
    offset, info = fit_midday_offset(_residuals(14, -2.5))
    assert offset == pytest.approx(2.5)
    assert info["applied"] is True


def test_fit_sign_gate_ignores_overprediction() -> None:
    """模型偏高（残差为正）时不加正偏移。"""
    offset, _ = fit_midday_offset(_residuals(14, 4.0))
    assert offset == 0.0


def test_fit_caps_large_offsets() -> None:
    offset, _ = fit_midday_offset(_residuals(14, -9.0))
    assert offset == pytest.approx(MAX_ABS_OFFSET)


def test_fit_deadband() -> None:
    offset, _ = fit_midday_offset(_residuals(14, -0.2))
    assert offset == 0.0


def test_apply_only_changes_midday_hours_and_keeps_input() -> None:
    pred = pd.DataFrame(
        {"day": pd.to_datetime(["2025-11-20"] * 24), "hour": np.arange(1, 25), "price": 50.0}
    )
    out = apply_hourly_offset(pred, 2.0)
    changed = out["hour"].isin(MIDDAY_HOURS)
    np.testing.assert_allclose(out.loc[changed, "price"], 52.0)
    np.testing.assert_allclose(out.loc[~changed, "price"], 50.0)
    np.testing.assert_allclose(pred["price"], 50.0)


def test_apply_zero_offset_is_identity() -> None:
    pred = pd.DataFrame(
        {"day": pd.to_datetime(["2025-11-20"] * 24), "hour": np.arange(1, 25), "price": 50.0}
    )
    out = apply_hourly_offset(pred, 0.0)
    np.testing.assert_allclose(out["price"], 50.0)


def test_apply_rejects_missing_columns() -> None:
    pred = pd.DataFrame({"day": pd.to_datetime(["2025-11-20"] * 24), "hour": np.arange(1, 25)})
    with pytest.raises(ValueError, match="缺少列"):
        apply_hourly_offset(pred, 1.0)
