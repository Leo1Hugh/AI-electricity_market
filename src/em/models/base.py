"""回归模型接口。"""

from __future__ import annotations

from typing import Protocol, Sequence

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


class DailyModel(Protocol):
    """以交易日为样本、同时输出 24 个小时预测的模型协议。"""

    name: str

    def fit(self, panel: pd.DataFrame, features: Sequence[str]) -> "DailyModel":
        """仅使用训练面板拟合模型并返回自身。"""
        ...

    def predict(self, panel: pd.DataFrame) -> pd.DataFrame:
        """返回包含 day、hour、pred 三列的 24 小时预测。"""
        ...
