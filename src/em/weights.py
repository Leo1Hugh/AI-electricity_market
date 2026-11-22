"""冻结的分时段集成权重表（shrink3_0.8 的小时化版本）。

除 19、20 时外，与 shrink3_0.8 完全一致：
0.8/3·Ridge + 0.8/3·LGBM + 0.8/3·MTLasso + 0.2·naive。
19、20 时把 MTLasso 的权重从 0.8/3 降到 0.10，让出的 0.1667 按 1:1
分给 Ridge 与 LGBM，naive 权重不变。

依据：work/weight_analysis/windows26_predictions.csv.gz 的 17 个同季
交易日（2024-11-29..12-06、2025-11-28..12-06），MTLasso 在 19、20 时
偏差 -5.92/-9.12 USD、占组合平方误差 55%/70%；降权后 17 天日均 RMSE
4.705 -> 4.604，2024/2025 两个年份块都改善。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BASE_WEIGHT = 0.8 / 3
NAIVE_WEIGHT = 0.2
LATE_HOURS: tuple[int, ...] = (19, 20)
LATE_MTLASSO_WEIGHT = 0.10
COMPONENTS: tuple[str, ...] = ("ridge", "lgbm", "mtlasso", "naive_d1")
TABLE_NAME = "late_mtlasso_0.10"


def build_weight_table() -> pd.DataFrame:
    """返回 24×4 权重表，行索引 1..24，列顺序与 COMPONENTS 一致。"""
    rows: dict[int, dict[str, float]] = {}
    for hour in range(1, 25):
        mtlasso = LATE_MTLASSO_WEIGHT if hour in LATE_HOURS else BASE_WEIGHT
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
