"""回归模型接口。"""

from __future__ import annotations

from typing import Protocol

import numpy as np
import pandas as pd


class Regressor(Protocol):
    """逐行回归模型的最小协议。"""

    name: str

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "Regressor":
        """在训练集上拟合模型并返回自身。"""
        ...

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """对输入行生成一维预测。"""
        ...
