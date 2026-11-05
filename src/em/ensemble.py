"""严格按 (day, hour) 对齐的模型集成与收缩工具。"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


_COLUMNS = ["day", "hour", "y", "pred", "model"]
_KEYS = ["day", "hour"]


def _normalise(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    """校验并规范化单个预测框。"""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{label} 必须是 pandas.DataFrame")
    missing = [column for column in _COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} 缺少列: {missing}")
    out = frame.loc[:, _COLUMNS].copy()
    out["day"] = pd.to_datetime(out["day"], errors="coerce").dt.normalize()
    out["hour"] = pd.to_numeric(out["hour"], errors="coerce")
    out["y"] = pd.to_numeric(out["y"], errors="coerce")
    out["pred"] = pd.to_numeric(out["pred"], errors="coerce")
    if out[["day", "hour", "y", "pred"]].isna().any().any():
        raise ValueError(f"{label} 含 NaN 或无效键")
    if not np.isfinite(out[["hour", "y", "pred"]].to_numpy(dtype=float)).all():
        raise ValueError(f"{label} 含 NaN/inf")
    if not np.equal(out["hour"].to_numpy(dtype=float), np.floor(out["hour"])).all():
        raise ValueError(f"{label}.hour 必须为整数")
    out["hour"] = out["hour"].astype(int)
    if out.duplicated(_KEYS).any():
        raise ValueError(f"{label} 的 (day, hour) 键重复")
    return out.sort_values(_KEYS, kind="stable").reset_index(drop=True)


def _aligned_frames(
    predictions: Sequence[pd.DataFrame],
) -> list[pd.DataFrame]:
    """校验多个预测框具有完全相同的键和目标。"""
    if not predictions:
        raise ValueError("predictions 不能为空")
    frames = [_normalise(frame, f"predictions[{index}]") for index, frame in enumerate(predictions)]
    keys = frames[0][_KEYS]
    y = frames[0]["y"].to_numpy(dtype=float)
    for index, frame in enumerate(frames[1:], start=1):
        if not frame[_KEYS].equals(keys):
            raise ValueError(f"predictions[{index}] 与首个预测键不一致")
        if not np.array_equal(frame["y"].to_numpy(dtype=float), y, equal_nan=False):
            raise ValueError(f"predictions[{index}] 的 y 与首个预测不一致")
    return frames


def mean_ensemble(
    predictions: Sequence[pd.DataFrame],
    weights: Sequence[float] | None = None,
    name: str = "mean",
) -> pd.DataFrame:
    """对严格对齐的多个预测做归一化加权平均。"""
    frames = _aligned_frames(predictions)
    if weights is None:
        raw_weights = np.ones(len(frames), dtype=float)
    else:
        raw_weights = np.asarray(list(weights), dtype=float)
        if raw_weights.ndim != 1 or len(raw_weights) != len(frames):
            raise ValueError("weights 长度必须与 predictions 一致")
        if not np.isfinite(raw_weights).all() or (raw_weights < 0).any():
            raise ValueError("weights 必须是非负有限数")
    total = float(raw_weights.sum())
    if total <= 0:
        raise ValueError("weights 之和必须大于 0")
    normalised = raw_weights / total
    pred = np.zeros(len(frames[0]), dtype=float)
    for weight, frame in zip(normalised, frames):
        pred += weight * frame["pred"].to_numpy(dtype=float)
    if not np.isfinite(pred).all():
        raise ValueError("集成预测含 NaN/inf")
    result = frames[0].loc[:, ["day", "hour", "y"]].copy()
    result["pred"] = pred
    result["model"] = str(name)
    return result.loc[:, _COLUMNS]


def shrink_to_naive(
    pred: pd.DataFrame,
    naive: pd.DataFrame,
    weight: float = 0.7,
    name: str = "shrunk",
) -> pd.DataFrame:
    """将一个模型按 ``weight`` 收缩到 naive 预测。"""
    if not np.isfinite(weight) or not 0 <= weight <= 1:
        raise ValueError("weight 必须在 [0, 1] 内且有限")
    model, baseline = _aligned_frames([pred, naive])
    values = weight * model["pred"].to_numpy(dtype=float) + (1 - weight) * baseline[
        "pred"
    ].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("收缩预测含 NaN/inf")
    result = model.loc[:, ["day", "hour", "y"]].copy()
    result["pred"] = values
    result["model"] = str(name)
    return result.loc[:, _COLUMNS]
