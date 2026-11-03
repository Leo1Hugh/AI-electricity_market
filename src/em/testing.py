"""测试用的合成面板；不参与生产路径。"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from .contracts import HOURS, PANEL_COLUMNS


def _day_stat(a: np.ndarray, fn) -> np.ndarray:
    """按天统计后广播回 (n_days, 24)，前 7 天留 NaN。"""
    nd, nh = a.shape
    out = np.full(nd, np.nan)
    out[7:] = fn(a[7:], axis=1)
    return np.repeat(out[:, None], nh, axis=1)


def make_synthetic_panel(
    n_days: int = 240,
    start: str = "2024-01-01",
    seed: int = 0,
) -> pd.DataFrame:
    """生成一张列名/顺序完全符合契约的合成面板，供 W2 离线自测。"""
    rng = np.random.default_rng(seed)
    days = pd.date_range(start, periods=n_days, freq="D")
    hours = np.arange(1, 25)
    nd, nh = n_days, len(hours)
    t = np.arange(nd)[:, None]
    h = hours[None, :]

    level = 35.0 + 8.0 * np.sin(2 * np.pi * (h - 1) / 24 - 1.1)
    level = level + 5.0 * np.sin(2 * np.pi * t / 7)
    y = level + rng.normal(0, 4, (nd, nh))

    lag = {}
    for k in range(1, 8):
        a = np.full((nd, nh), np.nan)
        a[k:, :] = y[:-k, :]
        lag[k] = a

    cols: dict[str, np.ndarray] = {}
    for k in range(1, 8):
        cols[f"p_lag{k}"] = lag[k]
    stack = np.stack([lag[k] for k in range(1, 8)], axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        cols["p_lagmean7"] = np.nanmean(stack, axis=0)
        cols["p_lagstd7"] = np.nanstd(stack, axis=0)

    prev = np.full((nd, nh), np.nan)
    prev[:, 1:] = lag[1][:, :-1]
    prev[:, 0] = lag[1][:, 23]
    nxt = np.full((nd, nh), np.nan)
    nxt[:, :-1] = lag[1][:, 1:]
    nxt[:, 23] = lag[1][:, 0]
    cols["p_lag1_prev"] = prev
    cols["p_lag1_next"] = nxt
    cols["p_lag1_daymean"] = _day_stat(lag[1], np.nanmean)
    cols["p_lag1_daymax"] = _day_stat(lag[1], np.nanmax)
    cols["p_lag1_daymin"] = _day_stat(lag[1], np.nanmin)

    load = (
        24000
        + 3000 * np.sin(2 * np.pi * (h - 1) / 24 - 0.5)
        + 2500 * np.sin(2 * np.pi * t / 7)
        + rng.normal(0, 300, (nd, nh))
    )
    solar = np.clip(1800 * np.sin(np.pi * (h - 8) / 12), 0, None)
    solar = solar * (1 + 0.1 * rng.normal(size=(nd, 1)))
    wind = np.clip(600 + 200 * rng.normal(size=(nd, nh)), 0, None)
    netload = load - solar - wind

    cols["load_caiso"] = load
    cols["load_sce"] = 0.45 * load + rng.normal(0, 100, (nd, nh))
    cols["load_sdge"] = 0.09 * load + rng.normal(0, 30, (nd, nh))
    cols["solar"] = solar
    cols["wind"] = wind
    cols["netload"] = netload
    cols["nl_ratio"] = netload / load
    ramp = np.empty((nd, nh))
    ramp[:, 1:] = netload[:, 1:] - netload[:, :-1]
    ramp[:, 0] = netload[:, 0] - netload[:, 23]
    cols["nl_ramp"] = ramp
    cols["nl_daymean"] = np.repeat(netload.mean(axis=1)[:, None], nh, axis=1)
    cols["nl_daymax"] = np.repeat(netload.max(axis=1)[:, None], nh, axis=1)
    sol_sum = solar.sum(axis=1)
    cols["sol_sum"] = np.repeat(sol_sum[:, None], nh, axis=1)
    cols["sol_ratio"] = np.repeat((sol_sum / load.mean(axis=1))[:, None], nh, axis=1)
    lramp = np.empty((nd, nh))
    lramp[:, 1:] = load[:, 1:] - load[:, :-1]
    lramp[:, 0] = load[:, 0] - load[:, 23]
    cols["load_ramp"] = lramp

    dow = np.repeat(days.weekday.values[:, None], nh, axis=1)
    month = np.repeat(days.month.values[:, None], nh, axis=1)
    doy = np.repeat(days.dayofyear.values[:, None], nh, axis=1)
    cols["dow"] = dow
    cols["month"] = month
    cols["doy"] = doy
    cols["is_weekend"] = (dow >= 5).astype(int)
    cols["is_holiday"] = np.zeros((nd, nh), dtype=int)
    cols["d_to_holiday"] = np.full((nd, nh), 30, dtype=int)
    cols["is_thanksgiving"] = np.zeros((nd, nh), dtype=int)
    cols["is_black_friday"] = np.zeros((nd, nh), dtype=int)
    cols["is_pre_holiday"] = np.zeros((nd, nh), dtype=int)
    cols["is_post_holiday"] = np.zeros((nd, nh), dtype=int)

    for hh in HOURS:
        cols[f"x_p1_{hh}"] = np.repeat(lag[1][:, hh - 1][:, None], nh, axis=1)
        cols[f"x_nl_{hh}"] = np.repeat(netload[:, hh - 1][:, None], nh, axis=1)

    data: dict[str, object] = {
        "day": np.repeat(days.values, nh),
        "hour": np.tile(hours, nd),
        "y": y.ravel(),
    }
    for name, arr in cols.items():
        data[name] = np.asarray(arr).ravel()

    out = pd.DataFrame(data)
    return out[list(PANEL_COLUMNS)].sort_values(list(("day", "hour"))).reset_index(drop=True)
