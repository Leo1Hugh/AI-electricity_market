"""冻结的分时段集成权重表（shrink3_0.8 的小时化版本）。

除中午 10-15 时与深夜 19、20 时外，与 shrink3_0.8 完全一致：
0.8/3·Ridge + 0.8/3·LGBM + 0.8/3·MTLasso + 0.2·naive。

- 中午 10-15 时：MTLasso 0.8/3 -> 0.50，Ridge/LGBM 各 0.8/3 -> 0.15，
  naive 0.2 不变。依据：26 窗口 17 个同季交易日 + 全部 364 天滚动，
  中午 MTLasso 是三家中唯一 RMSE < 8 的；提权后 17 天日均 RMSE
  4.604 -> 4.444，两年交叉验证同向，364 天中午 5.385 -> 5.214。
- 深夜 19、20 时：MTLasso 0.8/3 -> 0.10，让出的 0.1667 按 1:1 给
  Ridge/LGBM。依据：同 17 个交易日，MTLasso 在 19/20 时偏差
  -5.92/-9.12、占组合平方误差 55%/70%。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BASE_WEIGHT = 0.8 / 3
NAIVE_WEIGHT = 0.2
MIDDAY_HOURS: tuple[int, ...] = (10, 11, 12, 13, 14, 15)
MIDDAY_MTLASSO_WEIGHT = 0.50
LATE_HOURS: tuple[int, ...] = (19, 20)
LATE_MTLASSO_WEIGHT = 0.10
COMPONENTS: tuple[str, ...] = ("ridge", "lgbm", "mtlasso", "naive_d1")
TABLE_NAME = "mid_mtlasso_0.50_late_mtlasso_0.10"


def _mtlasso_weight(hour: int) -> float:
    """返回该小时 MTLasso 的权重；剩余 0.8 预算按 1:1 给 Ridge/LGBM。"""
    if hour in LATE_HOURS:
        return LATE_MTLASSO_WEIGHT
    if hour in MIDDAY_HOURS:
        return MIDDAY_MTLASSO_WEIGHT
    return BASE_WEIGHT


def build_weight_table() -> pd.DataFrame:
    """返回 24×4 权重表，行索引 1..24，列顺序与 COMPONENTS 一致。"""
    rows: dict[int, dict[str, float]] = {}
    for hour in range(1, 25):
        mtlasso = _mtlasso_weight(hour)
        rest = 0.8 - mtlasso
        rows[hour] = {
            "ridge": rest / 2,
            "lgbm": rest / 2,
            "mtlasso": mtlasso,
            "naive_d1": NAIVE_WEIGHT,
        }
    table = pd.DataFrame.from_dict(rows, orient="index")
    table.index.name = "hour"
    if not np.allclose(table.sum(axis=1).to_numpy(dtype=float), 1.0, atol=1e-12):
        raise AssertionError("每小时权重之和必须为 1")
    return table.loc[:, list(COMPONENTS)]
