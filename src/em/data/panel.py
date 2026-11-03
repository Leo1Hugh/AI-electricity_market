"""从 hourly 原始表构建契约规定的长表面板。"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from em.contracts import (
    CALENDAR_FEATURES,
    FEATURES,
    HOURS,
    PANEL_COLUMNS,
    REQUIRED_HOURLY_COLUMNS,
    TARGET,
    TRAIN_END,
    TRAIN_START,
)
from em.data.calendar import calendar_features


def _pivot(frame: pd.DataFrame, column: str, days: pd.DatetimeIndex) -> pd.DataFrame:
    """将一个小时字段整理为连续日历日 × 24 小时矩阵。"""
    return frame.pivot(index="opr_dt", columns="opr_hr", values=column).reindex(
        index=days, columns=HOURS
    )


def _nan_day_stat(matrix: pd.DataFrame, operation: str) -> np.ndarray:
    """按天计算统计量并广播到小时；全缺测日仍为 NaN。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        if operation == "mean":
            series = matrix.mean(axis=1)
        elif operation == "std":
            series = matrix.std(axis=1, ddof=0)
        elif operation == "max":
            series = matrix.max(axis=1)
        elif operation == "min":
            series = matrix.min(axis=1)
        else:  # pragma: no cover
            raise ValueError(f"未知日统计量: {operation}")
    return np.repeat(series.to_numpy(dtype=float)[:, None], len(HOURS), axis=1)


def _safe_divide(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    """逐元素相除，将零分母和无效结果保留为 NaN。"""
    out = np.full_like(np.asarray(numerator, dtype=float), np.nan, dtype=float)
    np.divide(numerator, denominator, out=out, where=np.isfinite(denominator) & (denominator != 0))
    return out


def build_panel(hourly: pd.DataFrame) -> pd.DataFrame:
    """纯函数：不读文件、不写文件、不修改入参。"""
    missing = [column for column in REQUIRED_HOURLY_COLUMNS if column not in hourly.columns]
    if missing:
        raise ValueError(f"hourly 缺少必需列: {missing}")
    if hourly.empty:
        raise ValueError("hourly 为空")

    frame = hourly.copy(deep=True)
    frame["opr_dt"] = pd.to_datetime(frame["opr_dt"], errors="raise").dt.normalize()
    frame["opr_hr"] = pd.to_numeric(frame["opr_hr"], errors="raise").astype("int64")
    frame = frame.loc[frame["opr_hr"].between(1, 24)].copy()
    frame = frame.drop_duplicates(subset=["opr_dt", "opr_hr"], keep="last")
    if frame.empty:
        raise ValueError("hourly 没有 1..24 小时数据")

    first_day = frame["opr_dt"].min()
    last_day = frame["opr_dt"].max()
    days = pd.date_range(first_day, last_day, freq="D")
    days = days[(days >= TRAIN_START) & (days <= TRAIN_END)]
    if len(days) == 0:
        raise ValueError("hourly 与训练日期范围没有交集")

    price = _pivot(frame, "price", days)
    load_caiso = _pivot(frame, "load_caiso", days)
    load_sce = _pivot(frame, "load_sce", days)
    load_sdge = _pivot(frame, "load_sdge", days)
    solar = _pivot(frame, "ren_solar", days)
    wind = _pivot(frame, "ren_wind", days)
    netload = load_caiso - solar - wind

    matrices: dict[str, np.ndarray] = {}
    lag_matrices: dict[int, pd.DataFrame] = {}
    for k in range(1, 8):
        lag_matrices[k] = price.shift(k)
        matrices[f"p_lag{k}"] = lag_matrices[k].to_numpy(dtype=float)

    lag_stack = np.stack([lag_matrices[k].to_numpy(dtype=float) for k in range(1, 8)])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        matrices["p_lagmean7"] = np.nanmean(lag_stack, axis=0)
        matrices["p_lagstd7"] = np.nanstd(lag_stack, axis=0, ddof=0)

    lag1 = lag_matrices[1].to_numpy(dtype=float)
    matrices["p_lag1_prev"] = np.roll(lag1, 1, axis=1)
    matrices["p_lag1_next"] = np.roll(lag1, -1, axis=1)
    matrices["p_lag1_daymean"] = _nan_day_stat(lag_matrices[1], "mean")
    matrices["p_lag1_daymax"] = _nan_day_stat(lag_matrices[1], "max")
    matrices["p_lag1_daymin"] = _nan_day_stat(lag_matrices[1], "min")

    load_arr = load_caiso.to_numpy(dtype=float)
    sce_arr = load_sce.to_numpy(dtype=float)
    sdge_arr = load_sdge.to_numpy(dtype=float)
    solar_arr = solar.to_numpy(dtype=float)
    wind_arr = wind.to_numpy(dtype=float)
    nl_arr = netload.to_numpy(dtype=float)
    matrices["load_caiso"] = load_arr
    matrices["load_sce"] = sce_arr
    matrices["load_sdge"] = sdge_arr
    matrices["solar"] = solar_arr
    matrices["wind"] = wind_arr
    matrices["netload"] = nl_arr
    matrices["nl_ratio"] = _safe_divide(nl_arr, load_arr)
    matrices["nl_ramp"] = nl_arr - np.roll(nl_arr, 1, axis=1)
    matrices["nl_daymean"] = _nan_day_stat(netload, "mean")
    matrices["nl_daymax"] = _nan_day_stat(netload, "max")
    sol_sum = solar.sum(axis=1, skipna=True).to_numpy(dtype=float).copy()
    sol_sum[solar.isna().all(axis=1).to_numpy()] = np.nan
    load_mean = load_caiso.mean(axis=1, skipna=True).to_numpy(dtype=float)
    matrices["sol_sum"] = np.repeat(sol_sum[:, None], len(HOURS), axis=1)
    matrices["sol_ratio"] = np.repeat(_safe_divide(sol_sum, load_mean)[:, None], len(HOURS), axis=1)
    matrices["load_ramp"] = load_arr - np.roll(load_arr, 1, axis=1)

    cal = calendar_features(days)
    for name in CALENDAR_FEATURES:
        matrices[name] = np.repeat(cal[name].to_numpy(dtype=float)[:, None], len(HOURS), axis=1)

    for hh in HOURS:
        matrices[f"x_p1_{hh}"] = np.repeat(lag1[:, hh - 1][:, None], len(HOURS), axis=1)
        matrices[f"x_nl_{hh}"] = np.repeat(nl_arr[:, hh - 1][:, None], len(HOURS), axis=1)

    data: dict[str, object] = {
        "day": np.repeat(days.to_numpy(), len(HOURS)),
        "hour": np.tile(np.asarray(HOURS, dtype=np.int64), len(days)),
        TARGET: price.to_numpy(dtype=float).ravel(),
    }
    for name in FEATURES:
        data[name] = matrices[name].ravel()
    panel = pd.DataFrame(data, columns=PANEL_COLUMNS)
    panel["day"] = pd.to_datetime(panel["day"]).dt.normalize()
    panel["hour"] = panel["hour"].astype("int64")
    return panel.sort_values(["day", "hour"]).reset_index(drop=True)
