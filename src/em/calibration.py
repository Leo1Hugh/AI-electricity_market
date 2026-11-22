"""中午水平偏差校正（方案 B：只在 10-15 时加一个常数偏移）。

估计口径：用「最近 14 个已出分日」中，同一冻结模型自身的样本外残差
(pred - actual) 在 10-15 时的均值，取负号即为要加的偏移。
三道保险（26 窗口滚动验证的结论）：
1. 符号门：只在"模型系统性偏低"时抬价；残差为正（模型偏高）则不加。
2. 上限：单次最多 3.0 USD/MWh，防止旧窗口残差异常时无界外推。
3. 死区与最少天数：有效天数不足 7 天或 |offset| < 0.5 时不校正。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIDDAY_HOURS: tuple[int, ...] = (10, 11, 12, 13, 14, 15)
MIN_DAYS = 7
MAX_ABS_OFFSET = 3.0
MIN_ABS_OFFSET = 0.5
CORRECTION_NAME = "midday_bias_v1"


def fit_midday_offset(
    residuals: pd.DataFrame,
    *,
    hours: tuple[int, ...] = MIDDAY_HOURS,
    min_days: int = MIN_DAYS,
    cap: float = MAX_ABS_OFFSET,
    deadband: float = MIN_ABS_OFFSET,
) -> tuple[float, dict]:
    """从样本外残差（resid = pred - actual）估计中午常数偏移。

    返回 (offset, info)；符号门把负残差转为正偏移、正残差直接置 0，
    并封顶到 cap。有效天数不足或偏移落在死区内时返回 0.0 且不校正。
    """
    required = {"day", "hour", "resid"}
    missing = sorted(required.difference(residuals.columns))
    if missing:
        raise ValueError(f"residuals 缺少列: {missing}")
    frame = residuals.loc[residuals["hour"].isin(list(hours))].copy()
    frame["day"] = pd.to_datetime(frame["day"], errors="coerce").dt.normalize()
    frame["resid"] = pd.to_numeric(frame["resid"], errors="coerce")
    frame = frame[frame["day"].notna() & np.isfinite(frame["resid"])]
    n_days = int(frame["day"].nunique())
    info: dict[str, object] = {"n_days": n_days, "n_rows": int(len(frame))}
    if n_days < min_days:
        return 0.0, {**info, "applied": False, "reason": f"有效天数 {n_days} < {min_days}"}
    mean_resid = float(frame["resid"].mean())
    raw = -mean_resid
    offset = float(np.clip(raw, 0.0, cap))  # 符号门 + 上限
    info = {**info, "mean_resid": mean_resid}
    if raw < 0:
        return 0.0, {**info, "applied": False, "reason": "残差为正（模型偏高），符号门跳过"}
    if offset < deadband:
        return 0.0, {**info, "applied": False, "reason": f"offset {offset:.2f} 在死区内"}
    return offset, {**info, "applied": True}


def apply_hourly_offset(
    predictions: pd.DataFrame,
    offset: float,
    *,
    hours: tuple[int, ...] = MIDDAY_HOURS,
) -> pd.DataFrame:
    """把常数偏移加到指定小时的 price 上；offset 为 0 时返回副本。"""
    required = {"day", "hour", "price"}
    missing = sorted(required.difference(predictions.columns))
    if missing:
        raise ValueError(f"predictions 缺少列: {missing}")
    frame = predictions.copy()
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce").astype(float)
    if offset:
        mask = frame["hour"].astype(int).isin(list(hours))
        frame.loc[mask, "price"] = frame.loc[mask, "price"] + float(offset)
    if not np.isfinite(frame["price"].to_numpy(dtype=float)).all():
        raise ValueError("校正后 price 含 NaN/inf")
    return frame
