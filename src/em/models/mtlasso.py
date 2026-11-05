"""日级 MultiTaskLasso 模型。

该模型把每个交易日视为一个样本，把每个输入特征在 24 个小时的值
展开为一行，并同时回归该日的 24 个价格。所有缺失值统计量都只从
``fit`` 收到的训练面板学习。
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import MultiTaskLasso
from sklearn.preprocessing import StandardScaler


_HOURS: tuple[int, ...] = tuple(range(1, 25))


class MultiTaskLassoModel:
    """使用 24 输出 MultiTaskLasso 的日级回归模型。"""

    name = "mtlasso"

    def __init__(self, alpha: float = 0.1, max_iter: int = 5000) -> None:
        """初始化正则化强度和最大迭代次数。"""
        if not np.isfinite(alpha) or alpha < 0:
            raise ValueError("alpha 必须是非负有限数")
        if int(max_iter) <= 0:
            raise ValueError("max_iter 必须为正整数")
        self.alpha = float(alpha)
        self.max_iter = int(max_iter)
        self._features: list[str] | None = None
        self._columns: list[str] | None = None
        self._fill_values: pd.Series | None = None
        self._scaler: StandardScaler | None = None
        self._model: MultiTaskLasso | None = None

    @staticmethod
    def _normalise_panel(
        panel: pd.DataFrame,
        features: Sequence[str],
        *,
        require_target: bool,
    ) -> pd.DataFrame:
        """检查面板键并转换特征为数值列。"""
        if not isinstance(panel, pd.DataFrame):
            raise TypeError("panel 必须是 pandas.DataFrame")
        feature_list = [str(feature) for feature in features]
        if not feature_list:
            raise ValueError("features 不能为空")
        missing = [feature for feature in feature_list if feature not in panel.columns]
        if missing:
            raise ValueError(f"panel 缺少特征列: {missing}")
        required = {"day", "hour"}
        if require_target:
            required.add("y")
        missing = sorted(required.difference(panel.columns))
        if missing:
            raise ValueError(f"panel 缺少列: {missing}")

        frame = panel.copy()
        day = pd.to_datetime(frame["day"], errors="coerce")
        if day.isna().any():
            raise ValueError("panel.day 含无效日期")
        if getattr(day.dt, "tz", None) is not None:
            day = day.dt.tz_localize(None)
        frame["day"] = day.dt.normalize()
        hour = pd.to_numeric(frame["hour"], errors="coerce")
        if hour.isna().any() or not np.isfinite(hour.to_numpy(dtype=float)).all():
            raise ValueError("panel.hour 含无效值")
        if not np.equal(hour.to_numpy(dtype=float), np.floor(hour.to_numpy(dtype=float))).all():
            raise ValueError("panel.hour 必须为整数")
        frame["hour"] = hour.astype(int)
        invalid_hours = sorted(set(frame["hour"]) - set(_HOURS))
        if invalid_hours:
            raise ValueError(f"panel.hour 超出 1..24: {invalid_hours}")
        if frame.duplicated(["day", "hour"]).any():
            raise ValueError("panel 的 (day, hour) 主键重复")
        for feature in feature_list:
            frame[feature] = pd.to_numeric(frame[feature], errors="coerce")
            frame[feature] = frame[feature].replace([np.inf, -np.inf], np.nan)
        if require_target:
            frame["y"] = pd.to_numeric(frame["y"], errors="coerce")
            frame["y"] = frame["y"].replace([np.inf, -np.inf], np.nan)
        return frame.sort_values(["day", "hour"], kind="stable").reset_index(drop=True)

    @staticmethod
    def _feature_matrix(panel: pd.DataFrame, features: Sequence[str]) -> pd.DataFrame:
        """将逐小时面板展开为每日一行的特征矩阵。"""
        days = pd.DatetimeIndex(sorted(panel["day"].unique()))
        matrices: list[pd.DataFrame] = []
        for feature in features:
            pivot = panel.pivot(index="day", columns="hour", values=feature)
            pivot = pivot.reindex(index=days, columns=_HOURS)
            pivot.columns = [f"{feature}_{hour}" for hour in _HOURS]
            matrices.append(pivot)
        if not matrices:
            return pd.DataFrame(index=days)
        return pd.concat(matrices, axis=1).astype(float)

    @staticmethod
    def _target_matrix(panel: pd.DataFrame) -> pd.DataFrame:
        """将目标价格展开为每日 24 输出。"""
        days = pd.DatetimeIndex(sorted(panel["day"].unique()))
        target = panel.pivot(index="day", columns="hour", values="y")
        return target.reindex(index=days, columns=_HOURS).astype(float)

    def fit(self, panel: pd.DataFrame, features: Sequence[str]) -> "MultiTaskLassoModel":
        """仅用 24 个目标完整的训练日拟合模型。"""
        feature_list = [str(feature) for feature in features]
        frame = self._normalise_panel(panel, feature_list, require_target=True)
        x_daily = self._feature_matrix(frame, feature_list)
        y_daily = self._target_matrix(frame)
        complete = y_daily.notna().all(axis=1)
        if not complete.any():
            raise ValueError("训练面板没有 y 完整的 24 小时交易日")
        x_train = x_daily.loc[complete].copy()
        y_train = y_daily.loc[complete].to_numpy(dtype=float)
        fill_values = x_train.median(axis=0, skipna=True)
        fill_values = fill_values.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        filled = x_train.fillna(fill_values)
        scaler = StandardScaler()
        scaled = scaler.fit_transform(filled.to_numpy(dtype=float))
        model = MultiTaskLasso(alpha=self.alpha, max_iter=self.max_iter)
        model.fit(scaled, y_train)

        self._features = feature_list
        self._columns = list(x_daily.columns)
        self._fill_values = fill_values.reindex(self._columns).fillna(0.0)
        self._scaler = scaler
        self._model = model
        return self

    def predict(self, panel: pd.DataFrame) -> pd.DataFrame:
        """对每个输入交易日输出 24 个有限预测值。"""
        if (
            self._features is None
            or self._columns is None
            or self._fill_values is None
            or self._scaler is None
            or self._model is None
        ):
            raise RuntimeError("模型尚未 fit")
        # 预测面板可能省略训练时存在的某些特征；按契约将整列视作缺失，
        # 后续由训练集学习到的中位数填充，而不是从测试集重新估计。
        if not isinstance(panel, pd.DataFrame):
            raise TypeError("panel 必须是 pandas.DataFrame")
        predict_panel = panel.copy()
        for feature in self._features:
            if feature not in predict_panel.columns:
                predict_panel[feature] = np.nan
        frame = self._normalise_panel(predict_panel, self._features, require_target=False)
        x_daily = self._feature_matrix(frame, self._features).reindex(columns=self._columns)
        if x_daily.empty:
            return pd.DataFrame(columns=["day", "hour", "pred"])
        filled = x_daily.fillna(self._fill_values)
        scaled = self._scaler.transform(filled.to_numpy(dtype=float))
        raw = np.asarray(self._model.predict(scaled), dtype=float)
        if raw.ndim == 1:
            raw = raw.reshape(1, -1)
        if raw.shape != (len(x_daily), 24):
            raise ValueError(f"MTLasso 输出形状错误: {raw.shape}")
        if not np.isfinite(raw).all():
            raise ValueError("MTLasso 产生了 NaN/inf 预测")
        days = pd.DatetimeIndex(x_daily.index)
        result = pd.DataFrame(
            {
                "day": np.repeat(days.to_numpy(), len(_HOURS)),
                "hour": np.tile(np.asarray(_HOURS, dtype=int), len(days)),
                "pred": raw.reshape(-1),
            }
        )
        return result.sort_values(["day", "hour"], kind="stable").reset_index(drop=True)
