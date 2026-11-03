"""契约自身的自检；不依赖 W1/W2 的实现。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from em import contracts as C
from em.io import validate_panel
from em.testing import make_synthetic_panel


def test_contract_version():
    assert C.CONTRACT_VERSION == "1.0.0"


def test_feature_counts_and_order():
    assert len(C.PRICE_LAG_FEATURES) == 14
    assert len(C.EXOG_FEATURES) == 13
    assert len(C.CALENDAR_FEATURES) == 10
    assert len(C.CROSS_FEATURES) == 48
    assert len(C.BASE_FEATURES) == 37
    assert len(C.FEATURES) == 85
    assert len(C.PANEL_COLUMNS) == 88
    assert len(set(C.FEATURES)) == 85
    assert list(C.FEATURES) == list(C.BASE_FEATURES) + list(C.CROSS_FEATURES)


def test_panel_columns_exact():
    assert list(C.PANEL_COLUMNS[:3]) == ["day", "hour", "y"]
    assert list(C.PANEL_COLUMNS) == list(C.KEYS) + [C.TARGET] + list(C.FEATURES)


def test_synthetic_panel_is_valid():
    panel = make_synthetic_panel(n_days=40, seed=7)
    summary = validate_panel(panel)
    assert summary["rows"] == 40 * 24
    assert summary["days"] == 40
    assert summary["feature_count"] == 85
    assert summary["target_notna"] == 40 * 24


def test_validate_rejects_missing_column():
    panel = make_synthetic_panel(n_days=10).drop(columns=["p_lag3"])
    with pytest.raises(ValueError, match="列不符合契约"):
        validate_panel(panel)


def test_validate_rejects_inf():
    panel = make_synthetic_panel(n_days=10)
    panel.loc[0, "load_caiso"] = np.inf
    with pytest.raises(ValueError, match="inf"):
        validate_panel(panel)


def test_validate_rejects_duplicate_key():
    panel = make_synthetic_panel(n_days=10)
    panel = pd.concat([panel, panel.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="重复"):
        validate_panel(panel)
