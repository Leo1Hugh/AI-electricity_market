"""P1 后处理：Δnetload 修正层（不改契约、不改主模型）。

在冻结模型输出上叠加一层线性修正::

    price[h] += clip(γ · β · Δnetload[h], −cap, +cap)

其中 Δnetload[h] = netload(D,h) − netload(D−1,h)。面板里的 netload 由日前负荷/风光
预报构成（sld_fcst / sld_ren_fcst 的 DAM 预报），D 日与 D−1 日都只用 D−1 10:00 前
已发布的日前预报值，不使用任何 D 日实际值。

β=0.00097 是 2024+2025 同季（11-08~12-06）合并估计的**冻结模型残差系数**
（doubao过程文件/分析结果/beta_robust.json）；γ=0.8 为拍板倍数，截断 ±8 USD/MWh
为纯保险（0.6x 下命中率 0%，见 correction_engineering.json）。
换模型必须重估 β，禁止直接复用。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

POSTPROCESS_NAME = "netload_delta_v1"
NETLOAD_DELTA_BETA = 0.0009701782955731652
NETLOAD_DELTA_GAMMA = 0.8
NETLOAD_DELTA_CAP = 8.0


def _netload_delta(panel: pd.DataFrame, day: pd.Timestamp) -> pd.Series:
    """返回 D 日逐小时 Δnetload = netload(D,h) − netload(D−1,h)，按 hour 索引升序。"""
    prev = day - pd.Timedelta(days=1)
    cur = (
        panel.loc[panel["day"] == day, ["hour", "netload"]]
        .drop_duplicates("hour")
        .set_index("hour")["netload"]
    )
    before = (
        panel.loc[panel["day"] == prev, ["hour", "netload"]]
        .drop_duplicates("hour")
        .set_index("hour")["netload"]
    )
    return (cur - before).sort_index()


def apply_netload_delta_correction(
    predictions: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    beta: float = NETLOAD_DELTA_BETA,
    gamma: float = NETLOAD_DELTA_GAMMA,
    cap: float = NETLOAD_DELTA_CAP,
) -> tuple[pd.DataFrame, dict]:
    """对 predictions 施加 Δnetload 修正，返回 (修正后 predictions, 归因信息)。

    入参 predictions 需含 day/hour/price 列；panel 需含 day/hour/netload 列。
    Δnetload 缺测的小时不做修正（价格保持原样）。不改动入参。
    """
    frame = predictions.copy()
    day = pd.Timestamp(frame["day"].iloc[0]).normalize()
    delta = _netload_delta(panel, day).reindex(frame["hour"].astype(int))
    delta_np = delta.to_numpy(dtype=float)

    raw = gamma * beta * delta_np
    adj = np.clip(raw, -cap, cap)
    finite = np.isfinite(delta_np)
    adj = np.where(finite, adj, 0.0)

    frame["price"] = frame["price"].to_numpy(dtype=float) + adj
    info: dict[str, object] = {
        "beta": beta,
        "gamma": gamma,
        "cap": cap,
        "n_hours": int(len(frame)),
        "n_skipped": int((~finite).sum()),
    }
    return frame, info
