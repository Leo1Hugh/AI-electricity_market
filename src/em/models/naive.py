"""基于价格滞后特征的基线模型。"""

from __future__ import annotations

import numpy as np
import pandas as pd


class _NaiveBase:
    """只读取一个面板特征的无参数基线。"""

    feature: str
    name: str
    fallbacks: tuple[str, ...] = ()

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "_NaiveBase":
        """无参数模型无需训练，返回自身。"""
        if self.feature not in X.columns:
            raise KeyError(f"缺少特征列: {self.feature}")
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """返回指定滞后特征，缺失值按模型顺序回退。"""
        if self.feature not in X.columns:
            raise KeyError(f"缺少特征列: {self.feature}")
        values = pd.to_numeric(X[self.feature], errors="coerce").to_numpy(
            dtype=float, copy=True
        ).reshape(-1)
        unresolved = ~np.isfinite(values)
        for fallback in self.fallbacks:
            if not unresolved.any():
                break
            if fallback not in X.columns:
                continue
            candidate = pd.to_numeric(X[fallback], errors="coerce").to_numpy(
                dtype=float, copy=False
            ).reshape(-1)
            usable = unresolved & np.isfinite(candidate)
            values[usable] = candidate[usable]
            unresolved = ~np.isfinite(values)
        if not np.isfinite(values).all():
            raise ValueError(
                f"{self.name} 的主特征和回退特征仍含 NaN/inf: "
                f"{int((~np.isfinite(values)).sum())} 行"
            )
        return values


class NaiveD1(_NaiveBase):
    """用前一日同小时价格预测。"""

    feature = "p_lag1"
    name = "naive_d1"
    fallbacks = ("p_lag2", "p_lagmean7", "p_lag7")


class NaiveD7(_NaiveBase):
    """用前七日同小时价格预测。"""

    feature = "p_lag7"
    name = "naive_d7"
    fallbacks = ("p_lagmean7", "p_lag1")


class NaiveMean7(_NaiveBase):
    """用前七日同小时价格均值预测。"""

    feature = "p_lagmean7"
    name = "naive_mean7"
    fallbacks = ("p_lag7", "p_lag1")
