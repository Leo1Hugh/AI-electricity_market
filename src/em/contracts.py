"""冻结的建模契约 v1（2026-11-03）。

本文件是 W1（数据）与 W2（模型）之间唯一的接口定义。
任何字段增删、改名、口径变化，必须先改本文件并升版本号，
再同步 docs/建模契约_v1.md 与两边任务书；禁止口头约定。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

CONTRACT_VERSION = "1.0.0"

# ---------------------------------------------------------------- 路径
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
WORK_DIR = ROOT / "work"
REPORTS_DIR = ROOT / "reports"

HOURLY_PATH = WORK_DIR / "hourly.csv.gz"
PANEL_PATH = PROCESSED_DIR / "panel.csv.gz"

# ---------------------------------------------------------------- 时间与颗粒度
HOURS: tuple[int, ...] = tuple(range(1, 25))
KEYS: tuple[str, ...] = ("day", "hour")
TARGET = "y"

TRAIN_START = pd.Timestamp("2023-11-01")
TRAIN_END = pd.Timestamp("2026-10-31")
COMPETITION_START = pd.Timestamp("2026-11-23")
COMPETITION_END = pd.Timestamp("2026-12-06")

# 两个"同款"历史冬季窗口，用于模型选择（训练只用窗口之前的数据）
WINTER_WINDOWS: tuple[tuple[pd.Timestamp, pd.Timestamp], ...] = (
    (pd.Timestamp("2024-11-23"), pd.Timestamp("2024-12-06")),
    (pd.Timestamp("2025-11-23"), pd.Timestamp("2025-12-06")),
)

ANNUAL_BACKTEST_START = pd.Timestamp("2025-11-01")
ANNUAL_BACKTEST_END = pd.Timestamp("2026-10-31")

# 已知缺测：CAISO OASIS 在这三天对 SP15 Solar/Wind 返回 no-data
MISSING_RENEWABLE_DAYS: tuple[pd.Timestamp, ...] = (
    pd.Timestamp("2024-03-09"),
    pd.Timestamp("2025-03-08"),
    pd.Timestamp("2026-03-07"),
)

# 秋季回拨的 25 小时日（OPR_HR=25 必须丢弃，不参与 24 点建模）
DST_FALLBACK_DAYS: tuple[pd.Timestamp, ...] = (
    pd.Timestamp("2023-11-05"),
    pd.Timestamp("2024-11-03"),
    pd.Timestamp("2025-11-02"),
)

# 春季跳过的 23 小时日（OPR_HR=3 缺失，面板保留该行且 y 为 NaN）
DST_SPRING_DAYS: tuple[pd.Timestamp, ...] = (
    pd.Timestamp("2024-03-10"),
    pd.Timestamp("2025-03-09"),
    pd.Timestamp("2026-03-08"),
)

# ---------------------------------------------------------------- 特征分组
PRICE_LAG_FEATURES: tuple[str, ...] = (
    "p_lag1", "p_lag2", "p_lag3", "p_lag4", "p_lag5", "p_lag6", "p_lag7",
    "p_lagmean7", "p_lagstd7",
    "p_lag1_prev", "p_lag1_next",
    "p_lag1_daymean", "p_lag1_daymax", "p_lag1_daymin",
)

EXOG_FEATURES: tuple[str, ...] = (
    "load_caiso", "load_sce", "load_sdge",
    "solar", "wind",
    "netload", "nl_ratio", "nl_ramp",
    "nl_daymean", "nl_daymax",
    "sol_sum", "sol_ratio",
    "load_ramp",
)

CALENDAR_FEATURES: tuple[str, ...] = (
    "dow", "month", "doy", "is_weekend",
    "is_holiday", "d_to_holiday",
    "is_thanksgiving", "is_black_friday",
    "is_pre_holiday", "is_post_holiday",
)

CROSS_FEATURES: tuple[str, ...] = (
    tuple(f"x_p1_{h}" for h in HOURS)
    + tuple(f"x_nl_{h}" for h in HOURS)
)

BASE_FEATURES: tuple[str, ...] = (
    PRICE_LAG_FEATURES + EXOG_FEATURES + CALENDAR_FEATURES
)
FEATURES: tuple[str, ...] = BASE_FEATURES + CROSS_FEATURES

FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "price_lag": PRICE_LAG_FEATURES,
    "exog": EXOG_FEATURES,
    "calendar": CALENDAR_FEATURES,
    "cross": CROSS_FEATURES,
    "base": BASE_FEATURES,
    "all": FEATURES,
}

PANEL_COLUMNS: tuple[str, ...] = KEYS + (TARGET,) + FEATURES

# 从 work/hourly.csv.gz 建面板时必须用到的列
REQUIRED_HOURLY_COLUMNS: tuple[str, ...] = (
    "opr_dt", "opr_hr", "price",
    "load_caiso", "load_sce", "load_sdge",
    "ren_solar", "ren_wind",
)

# 契约自检：分组不重叠、无重复、总数固定
assert len(set(FEATURES)) == len(FEATURES), "特征名重复"
assert len(set(PRICE_LAG_FEATURES)) == len(PRICE_LAG_FEATURES)
assert len(PRICE_LAG_FEATURES) == 14
assert len(EXOG_FEATURES) == 13
assert len(CALENDAR_FEATURES) == 10
assert len(CROSS_FEATURES) == 48
assert len(BASE_FEATURES) == 37
assert len(FEATURES) == 85
assert len(PANEL_COLUMNS) == 88
