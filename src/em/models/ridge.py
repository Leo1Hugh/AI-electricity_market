"""带训练集统计量填充和标准化的 Ridge 回归模型。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler


class RidgeModel:
    """中位数填充、标准化后拟合 Ridge 的逐行模型。"""

    name = "ridge"

    def __init__(self, alpha: float = 10.0) -> None:
        """初始化模型。"""
        self.alpha = float(alpha)
        self._columns: list[str] | None = None
        self._fill_values: pd.Series | None = None
        self._scaler: StandardScaler | None = None
        self._model: Ridge | None = None

    @staticmethod
    def _numeric_frame(X: pd.DataFrame) -> pd.DataFrame:
        """转换为浮点特征，并把无穷值视作缺失。"""
        frame = X.copy()
        for col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        return frame.replace([np.inf, -np.inf], np.nan).astype(float)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "RidgeModel":
        """仅用训练集学习中位数、标准化参数和 Ridge 系数。"""
        if not isinstance(X, pd.DataFrame):
            raise TypeError("X 必须是 pandas.DataFrame")
        if len(X) != len(y):
            raise ValueError("X 与 y 行数不一致")
        frame = self._numeric_frame(X)
        target = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
        valid = np.isfinite(target)
        if not valid.any():
            raise ValueError("训练目标没有有限值")
        frame = frame.loc[valid].reset_index(drop=True)
        target = target[valid]
        medians = frame.median(axis=0, skipna=True)
        medians = medians.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        filled = frame.fillna(medians)
        self._columns = [str(c) for c in frame.columns]
        self._fill_values = medians
        self._scaler = StandardScaler()
        scaled = self._scaler.fit_transform(filled.to_numpy(dtype=float))
        self._model = Ridge(alpha=self.alpha)
        self._model.fit(scaled, target)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """使用拟合时的训练集统计量生成有限的一维预测。"""
        if self._model is None or self._scaler is None or self._columns is None or self._fill_values is None:
            raise RuntimeError("模型尚未 fit")
        if not isinstance(X, pd.DataFrame):
            raise TypeError("X 必须是 pandas.DataFrame")
        frame = self._numeric_frame(X).reindex(columns=self._columns)
        filled = frame.fillna(self._fill_values)
        scaled = self._scaler.transform(filled.to_numpy(dtype=float))
        pred = np.asarray(self._model.predict(scaled), dtype=float).reshape(-1)
        if not np.isfinite(pred).all():
            raise ValueError("Ridge 产生了非有限预测")
        return pred
