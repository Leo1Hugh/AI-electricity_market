"""面板 / 原始表的读写与契约校验。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import (
    FEATURES,
    HOURLY_PATH,
    KEYS,
    PANEL_COLUMNS,
    PANEL_PATH,
    TARGET,
)


def load_hourly(path: str | Path = HOURLY_PATH) -> pd.DataFrame:
    """读取 work/hourly.csv.gz，返回带 datetime64 的 opr_dt。"""
    df = pd.read_csv(path)
    df["opr_dt"] = pd.to_datetime(df["opr_dt"]).dt.normalize()
    df["opr_hr"] = df["opr_hr"].astype("int64")
    if "ts_utc" in df.columns:
        df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    return df


def load_panel(path: str | Path = PANEL_PATH) -> pd.DataFrame:
    """读取 panel.csv.gz，保证 day 是 datetime64、hour 是 int64。"""
    df = pd.read_csv(path)
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    df["hour"] = df["hour"].astype("int64")
    return df


def validate_panel(
    panel: pd.DataFrame,
    *,
    exact_columns: bool = True,
    full_grid: bool = False,
) -> dict[str, object]:
    """校验面板是否满足契约；不满足就抛 ValueError。

    返回一个摘要 dict，供 CLI 打印和报告引用。
    """
    if panel.empty:
        raise ValueError("panel 为空")

    if exact_columns:
        missing = [c for c in PANEL_COLUMNS if c not in panel.columns]
        extra = [c for c in panel.columns if c not in PANEL_COLUMNS]
        if missing or extra:
            raise ValueError(
                f"列不符合契约: missing={missing[:10]} extra={extra[:10]}"
            )

    if panel.duplicated(list(KEYS)).any():
        dup = panel.loc[panel.duplicated(list(KEYS), keep=False), list(KEYS)]
        raise ValueError(f"(day, hour) 重复: {dup.head().to_dict('records')}")

    if not pd.api.types.is_datetime64_any_dtype(panel["day"]):
        raise ValueError("day 必须是 datetime64")

    hour = panel["hour"]
    if not hour.between(1, 24).all():
        raise ValueError(f"hour 越界: {sorted(hour.unique())[:5]}")

    values = panel[list(FEATURES)].to_numpy(dtype="float64", na_value=np.nan)
    if np.isinf(values).any():
        bad = np.argwhere(np.isinf(values))[0]
        raise ValueError(f"特征含 inf: row={bad[0]} col={FEATURES[bad[1]]}")

    n_target = int(panel[TARGET].notna().sum())
    if n_target == 0:
        raise ValueError("y 全为 NaN")

    if full_grid:
        counts = panel.groupby("day")["hour"].nunique()
        if not (counts == 24).all():
            raise ValueError(f"非完整 24 点日: {counts[counts != 24].head().to_dict()}")

    return {
        "rows": int(len(panel)),
        "days": int(panel["day"].nunique()),
        "hours": int(panel["hour"].nunique()),
        "target_notna": n_target,
        "feature_count": len(FEATURES),
        "day_min": str(panel["day"].min().date()),
        "day_max": str(panel["day"].max().date()),
        "missing_by_feature": {
            c: int(panel[c].isna().sum()) for c in FEATURES if panel[c].isna().any()
        },
    }


def save_panel(panel: pd.DataFrame, path: str | Path = PANEL_PATH) -> Path:
    """按契约校验后写出 gzip CSV；day 写为 YYYY-MM-DD。"""
    validate_panel(panel)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = panel.copy()
    out["day"] = out["day"].dt.strftime("%Y-%m-%d")
    out.to_csv(path, index=False, compression="gzip")
    return path
