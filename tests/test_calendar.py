"""日历特征的关键口径测试。"""

from __future__ import annotations

import pandas as pd

from em.contracts import CALENDAR_FEATURES
from em.data.calendar import calendar_features, us_market_holidays


def test_observed_new_year_crosses_year_boundary():
    holidays = us_market_holidays([2022, 2023])
    assert pd.Timestamp("2021-12-31") in holidays
    assert pd.Timestamp("2023-01-02") in holidays


def test_calendar_columns_and_thanksgiving_window():
    days = pd.date_range("2024-11-27", periods=3, freq="D")
    features = calendar_features(days)
    assert list(features.columns) == list(CALENDAR_FEATURES)
    assert features.loc[pd.Timestamp("2024-11-28"), "is_holiday"] == 1
    assert features.loc[pd.Timestamp("2024-11-28"), "is_thanksgiving"] == 1
    assert features.loc[pd.Timestamp("2024-11-29"), "is_black_friday"] == 1
    assert features.loc[pd.Timestamp("2024-11-27"), "is_pre_holiday"] == 1
    assert features.loc[pd.Timestamp("2024-11-29"), "is_post_holiday"] == 1


def test_distance_is_nonnegative_and_capped():
    days = pd.date_range("2024-01-01", periods=366, freq="D")
    features = calendar_features(days)
    assert features["d_to_holiday"].between(0, 30).all()
    assert features["d_to_holiday"].max() == 30
