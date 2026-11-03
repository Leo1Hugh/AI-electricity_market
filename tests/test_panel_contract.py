"""W1 的验收测试：面板必须满足 docs/建模契约_v1.md。"""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from em import contracts as C
from em.io import load_hourly

try:
    _spec = importlib.util.find_spec("em.data.panel")
except ModuleNotFoundError:
    _spec = None
if _spec is None:
    pytest.skip("W1 面板模块尚未合并", allow_module_level=True)

from em.data import panel as panel_mod  # noqa: E402


@pytest.fixture(scope="module")
def hourly() -> pd.DataFrame:
    return load_hourly()


@pytest.fixture(scope="module")
def panel(hourly: pd.DataFrame) -> pd.DataFrame:
    return panel_mod.build_panel(hourly)


def _piv(df: pd.DataFrame, col: str) -> pd.DataFrame:
    return df.pivot(index="day", columns="hour", values=col).sort_index()


def test_shape_and_keys(panel: pd.DataFrame):
    assert len(panel) == 1096 * 24
    assert panel["day"].nunique() == 1096
    assert not panel.duplicated(["day", "hour"]).any()
    assert sorted(panel["hour"].unique()) == list(range(1, 25))
    assert panel["day"].min() == C.TRAIN_START
    assert panel["day"].max() == C.TRAIN_END


def test_columns_exact(panel: pd.DataFrame):
    assert list(panel.columns) == list(C.PANEL_COLUMNS)
    assert str(panel["day"].dtype).startswith("datetime64")


def test_lag1_and_lag7(panel: pd.DataFrame):
    p = _piv(panel, "y")
    lag1 = _piv(panel, "p_lag1")
    lag7 = _piv(panel, "p_lag7")
    np.testing.assert_allclose(lag1.iloc[1:].to_numpy(), p.shift(1).iloc[1:].to_numpy(), equal_nan=True)
    np.testing.assert_allclose(lag7.iloc[7:].to_numpy(), p.shift(7).iloc[7:].to_numpy(), equal_nan=True)


def test_cross_hour_p1(panel: pd.DataFrame):
    for hh in (1, 5, 24):
        a = panel[panel["hour"] == hh].sort_values("day")["p_lag1"].to_numpy()
        b = panel[panel["hour"] == 12].sort_values("day")[f"x_p1_{hh}"].to_numpy()
        np.testing.assert_allclose(a, b, equal_nan=True)


def test_netload_identity(panel: pd.DataFrame):
    expected = panel["load_caiso"] - panel["solar"] - panel["wind"]
    np.testing.assert_allclose(panel["netload"].to_numpy(), expected.to_numpy(), equal_nan=True)


def test_nl_ramp(panel: pd.DataFrame):
    pivot = _piv(panel, "netload")
    ramp = _piv(panel, "nl_ramp")
    np.testing.assert_allclose(ramp.iloc[:, 1:].to_numpy(), (pivot.iloc[:, 1:] - pivot.iloc[:, :-1]).to_numpy(), equal_nan=True)


def test_dst_spring_missing_hour(panel: pd.DataFrame):
    for d in C.DST_SPRING_DAYS:
        sub = panel[panel["day"] == d]
        assert len(sub) == 24
        assert sub.loc[sub["hour"] == 3, "y"].isna().all(), f"{d} HE3 应为 NaN"


def test_dst_fallback_hour25_dropped(panel: pd.DataFrame):
    for d in C.DST_FALLBACK_DAYS:
        sub = panel[panel["day"] == d]
        assert len(sub) == 24
        assert 25 not in set(sub["hour"])


def test_missing_renewables(panel: pd.DataFrame):
    for d in C.MISSING_RENEWABLE_DAYS:
        sub = panel[panel["day"] == d]
        assert len(sub) == 24
        for col in ("solar", "wind", "netload", "nl_ratio"):
            assert sub[col].isna().all(), f"{d} {col} 应保留 NaN"


def test_holiday_flags(panel: pd.DataFrame):
    def row(d: str, h: int = 12) -> pd.Series:
        return panel[(panel["day"] == pd.Timestamp(d)) & (panel["hour"] == h)].iloc[0]

    thanksgiving = row("2024-11-28")
    assert thanksgiving["is_holiday"] == 1
    assert thanksgiving["is_thanksgiving"] == 1

    black_friday = row("2024-11-29")
    assert black_friday["is_black_friday"] == 1
    assert black_friday["is_post_holiday"] == 1

    eve = row("2024-11-27")
    assert eve["is_pre_holiday"] == 1

    normal = row("2024-11-20")
    assert normal["is_holiday"] == 0
    assert normal["is_thanksgiving"] == 0
    assert normal["is_black_friday"] == 0


def test_d_to_holiday_cap(panel: pd.DataFrame):
    assert panel["d_to_holiday"].between(0, 30).all()
    assert panel["d_to_holiday"].max() == 30


def test_no_inf(panel: pd.DataFrame):
    values = panel[list(C.FEATURES)].to_numpy(dtype="float64", na_value=np.nan)
    assert not np.isinf(values).any()


def test_truncated_rebuild_has_same_features(hourly: pd.DataFrame, panel: pd.DataFrame):
    """只用 <=D 的原始数据重算，D 日特征必须与全量面板完全一致（无未来信息）。"""
    for d in (pd.Timestamp("2024-03-09"), pd.Timestamp("2025-11-23")):
        sub = hourly[hourly["opr_dt"] <= d]
        rebuilt = panel_mod.build_panel(sub)
        a = panel[panel["day"] == d][list(C.FEATURES)].reset_index(drop=True)
        b = rebuilt[rebuilt["day"] == d][list(C.FEATURES)].reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b, check_dtype=False, check_exact=False, rtol=0, atol=1e-9)
