"""基于价格滞后特征的基线模型。"""

from __future__ import annotations

import numpy as np
import pandas as pd


class _NaiveBase:
    """只读取一个面板特征的无参数基线。"""

    feature: str
    name: str

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "_NaiveBase":
        """无参数模型无需训练，返回自身。"""
        if self.feature not in X.columns:
            raise KeyError(f"缺少特征列: {self.feature}")
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """返回指定滞后特征，保持输入行顺序。"""
        if self.feature not in X.columns:
            raise KeyError(f"缺少特征列: {self.feature}")
        return X[self.feature].to_numpy(dtype=float, copy=True).reshape(-1)


class NaiveD1(_NaiveBase):
    """用前一日同小时价格预测。"""

    feature = "p_lag1"
    name = "naive_d1"


class NaiveD7(_NaiveBase):
    """用前七日同小时价格预测。"""

    feature = "p_lag7"
    name = "naive_d7"


class NaiveMean7(_NaiveBase):
    """用前七日同小时价格均值预测。"""

    feature = "p_lagmean7"
    name = "naive_mean7"
