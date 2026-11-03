"""美国市场假日和日历特征。"""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from em.contracts import CALENDAR_FEATURES


_HOLIDAY_YEARS = tuple(range(2022, 2029))


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> pd.Timestamp:
    """返回某月第 n 个指定星期几。"""
    first = pd.Timestamp(year=year, month=month, day=1)
    offset = (weekday - first.weekday()) % 7
    return first + pd.Timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> pd.Timestamp:
    """返回某月最后一个指定星期几。"""
    if month == 12:
        first_next = pd.Timestamp(year=year + 1, month=1, day=1)
    else:
        first_next = pd.Timestamp(year=year, month=month + 1, day=1)
    last = first_next - pd.Timedelta(days=1)
    return last - pd.Timedelta(days=(last.weekday() - weekday) % 7)


def _nominal_holidays(year: int) -> list[pd.Timestamp]:
    """返回指定年份的未观察美国市场假日。"""
    return [
        pd.Timestamp(year=year, month=1, day=1),
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _last_weekday(year, 5, 0),  # Memorial Day
        pd.Timestamp(year=year, month=6, day=19),  # Juneteenth
        pd.Timestamp(year=year, month=7, day=4),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 10, 0, 2),  # Columbus Day
        pd.Timestamp(year=year, month=11, day=11),
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        pd.Timestamp(year=year, month=12, day=25),
    ]


def _observed(day: pd.Timestamp) -> pd.Timestamp:
    """按周末观察规则返回市场休市日。"""
    if day.weekday() == 5:  # Saturday -> Friday
        return day - pd.Timedelta(days=1)
    if day.weekday() == 6:  # Sunday -> Monday
        return day + pd.Timedelta(days=1)
    return day


def us_market_holidays(years: Iterable[int]) -> set[pd.Timestamp]:
    """返回这些年（含观察日）的美国市场假日集合，日期已 normalize。"""
    result: set[pd.Timestamp] = set()
    for year in sorted({int(year) for year in years}):
        result.update(_observed(day).normalize() for day in _nominal_holidays(year))
    return result


def calendar_features(days: pd.DatetimeIndex) -> pd.DataFrame:
    """返回与 days 对齐的日历特征，列顺序严格遵循契约。"""
    days = pd.DatetimeIndex(pd.to_datetime(days)).normalize()
    holidays = us_market_holidays(_HOLIDAY_YEARS)
    holiday_values = np.array(sorted(holidays), dtype="datetime64[ns]")

    is_holiday = np.array([day in holidays for day in days], dtype=np.int8)
    previous = days - pd.Timedelta(days=1)
    following = days + pd.Timedelta(days=1)
    if len(holiday_values):
        day_values = days.to_numpy(dtype="datetime64[ns]")
        distance = np.abs(day_values[:, None] - holiday_values[None, :]).astype(
            "timedelta64[D]"
        ).astype(np.int64)
        d_to_holiday = np.minimum(distance.min(axis=1), 30).astype(np.int64)
    else:  # pragma: no cover - the fixed holiday universe is non-empty
        d_to_holiday = np.full(len(days), 30, dtype=np.int64)

    thanksgiving = {
        _nth_weekday(year, 11, 3, 4) for year in _HOLIDAY_YEARS
    }
    black_friday = {day + pd.Timedelta(days=1) for day in thanksgiving}

    dow = days.day_of_week.to_numpy(dtype=np.int64)
    values: dict[str, np.ndarray] = {
        "dow": dow,
        "month": days.month.to_numpy(dtype=np.int64),
        "doy": days.day_of_year.to_numpy(dtype=np.int64),
        "is_weekend": (dow >= 5).astype(np.int8),
        "is_holiday": is_holiday,
        "d_to_holiday": d_to_holiday,
        "is_thanksgiving": np.array(
            [day in thanksgiving for day in days], dtype=np.int8
        ),
        "is_black_friday": np.array(
            [day in black_friday for day in days], dtype=np.int8
        ),
        "is_pre_holiday": np.array(
            [day in holidays for day in following], dtype=np.int8
        ),
        "is_post_holiday": np.array(
            [day in holidays for day in previous], dtype=np.int8
        ),
    }
    return pd.DataFrame({name: values[name] for name in CALENDAR_FEATURES}, index=days)
