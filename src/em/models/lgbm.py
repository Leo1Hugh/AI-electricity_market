"""LightGBM 回归模型封装。"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor


_DEFAULT_PARAMS: dict[str, Any] = {
    "n_estimators": 700,
    "learning_rate": 0.03,
    "num_leaves": 15,
    "min_child_samples": 40,
    "subsample": 0.9,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "random_state": 0,
    "verbose": -1,
    "n_jobs": 1,
}


class LGBMModel:
    """使用 LightGBM 的逐行回归模型。"""

    name = "lgbm"

    def __init__(self, params: Mapping[str, Any] | None = None) -> None:
        """初始化 LightGBM 参数，传入参数覆盖默认值。"""
        self.params: dict[str, Any] = dict(_DEFAULT_PARAMS)
        if params is not None:
            self.params.update(dict(params))
        self._columns: list[str] | None = None
        self._model: LGBMRegressor | None = None

    @staticmethod
    def _numeric_frame(X: pd.DataFrame) -> pd.DataFrame:
        """转换为浮点特征，并把无穷值视作缺失。"""
        frame = X.copy()
        for col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        return frame.replace([np.inf, -np.inf], np.nan).astype(float)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "LGBMModel":
        """仅用训练集拟合 LightGBM。"""
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
        self._columns = [str(c) for c in frame.columns]
        self._model = LGBMRegressor(**self.params)
        self._model.fit(frame, target)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """对输入行生成有限的一维预测。"""
        if self._model is None or self._columns is None:
            raise RuntimeError("模型尚未 fit")
        if not isinstance(X, pd.DataFrame):
            raise TypeError("X 必须是 pandas.DataFrame")
        frame = self._numeric_frame(X).reindex(columns=self._columns)
        pred = np.asarray(self._model.predict(frame), dtype=float).reshape(-1)
        if not np.isfinite(pred).all():
            raise ValueError("LightGBM 产生了非有限预测")
        return pred
