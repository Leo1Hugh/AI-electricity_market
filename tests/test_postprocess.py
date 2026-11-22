"""P1 Δnetload 后处理（netload_delta_v1）的单元与接线测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from em.io import save_panel
from em.pipeline import FINAL_MODEL, PipelineResult
from em.postprocess import (
    NETLOAD_DELTA_BETA,
    NETLOAD_DELTA_CAP,
    NETLOAD_DELTA_GAMMA,
    apply_netload_delta_correction,
)
from em.testing import make_synthetic_panel
from scripts import predict_and_submit

D = pd.Timestamp("2026-11-23")
HOURS = list(range(1, 25))


def _panel(prev: dict[int, float], cur: dict[int, float]) -> pd.DataFrame:
    rows = [(D - pd.Timedelta(days=1), h, prev[h]) for h in HOURS]
    rows += [(D, h, cur[h]) for h in HOURS]
    return pd.DataFrame(rows, columns=["day", "hour", "netload"])


def _predictions(prices: list[float] | None = None) -> pd.DataFrame:
    if prices is None:
        prices = [100.0] * 24
    return pd.DataFrame({"day": [D] * 24, "hour": HOURS, "price": prices})


# ---- 常量回归（用户拍板 γ 0.6 → 0.8）----


def test_constants_gamma_is_0_8() -> None:
    assert NETLOAD_DELTA_GAMMA == 0.8
    assert NETLOAD_DELTA_BETA == pytest.approx(0.0009701782955731652)
    assert NETLOAD_DELTA_CAP == 8.0


# ---- 纯函数：数学 / 截断 / 缺测 / 不可变 ----


def test_correction_applies_gamma_beta_times_netload_delta() -> None:
    prev = {h: 1000.0 for h in HOURS}
    cur = {h: 1000.0 + 100.0 * h for h in HOURS}  # d_nl = +100h
    panel = _panel(prev, cur)
    adjusted, info = apply_netload_delta_correction(_predictions(), panel)

    for h in HOURS:
        d_nl = cur[h] - prev[h]
        expected = 100.0 + np.clip(
            NETLOAD_DELTA_GAMMA * NETLOAD_DELTA_BETA * d_nl,
            -NETLOAD_DELTA_CAP,
            NETLOAD_DELTA_CAP,
        )
        got = float(adjusted.loc[adjusted["hour"] == h, "price"].iloc[0])
        assert got == pytest.approx(expected)
    assert info["n_hours"] == 24
    assert info["n_skipped"] == 0


def test_correction_caps_at_limit() -> None:
    prev = {h: 0.0 for h in HOURS}
    cur = {h: 1_000_000.0 for h in HOURS}  # Δnetload 巨大 → 截断到 +cap
    panel = _panel(prev, cur)
    adjusted, _ = apply_netload_delta_correction(_predictions(), panel)

    for h in HOURS:
        got = float(adjusted.loc[adjusted["hour"] == h, "price"].iloc[0])
        assert got == pytest.approx(100.0 + NETLOAD_DELTA_CAP)


def test_correction_skips_missing_netload_delta() -> None:
    prev = {h: 1000.0 for h in HOURS}
    cur = {h: 1100.0 for h in HOURS}
    cur[12] = np.nan  # D 日 hour 12 的净负荷缺测
    panel = _panel(prev, cur)
    adjusted, info = apply_netload_delta_correction(_predictions(), panel)

    for h in HOURS:
        got = float(adjusted.loc[adjusted["hour"] == h, "price"].iloc[0])
        if h == 12:
            assert got == pytest.approx(100.0)  # 缺测 → 不修正
        else:
            d_nl = cur[h] - prev[h]
            expected = 100.0 + NETLOAD_DELTA_GAMMA * NETLOAD_DELTA_BETA * d_nl
            assert got == pytest.approx(expected)
    assert info["n_skipped"] == 1


def test_correction_does_not_mutate_input() -> None:
    prev = {h: 1000.0 for h in HOURS}
    cur = {h: 1100.0 for h in HOURS}
    panel = _panel(prev, cur)
    pred = _predictions()
    original = pred["price"].copy()
    apply_netload_delta_correction(pred, panel)
    assert pred["price"].tolist() == original.tolist()  # 入参未被原地修改


# ---- 接线：只在冻结模型上生效 ----


def test_postprocess_applies_on_frozen_model(tmp_path) -> None:
    panel = make_synthetic_panel(n_days=90, start="2026-10-01", seed=7)
    panel_path = tmp_path / "panel.csv.gz"
    save_panel(panel, panel_path)

    result = PipelineResult(
        predictions=_predictions(),
        metadata={"model": FINAL_MODEL, "as_of": str(D.date()), "fallback": False},
    )
    result = predict_and_submit._apply_postprocess(result, panel_path)

    pp = result.metadata["postprocess"]
    assert pp["applied"] is True
    assert pp["name"] == "netload_delta_v1"
    assert pp["gamma"] == 0.8
    assert pp["beta"] == pytest.approx(0.0009701782955731652)
    assert pp["n_skipped"] == 0
    assert (result.predictions["price"].to_numpy() != np.full(24, 100.0)).any()



def test_postprocess_skips_naive_model(tmp_path) -> None:
    panel = make_synthetic_panel(n_days=90, start="2026-10-01", seed=7)
    panel_path = tmp_path / "panel.csv.gz"
    save_panel(panel, panel_path)

    result = PipelineResult(
        predictions=_predictions(),
        metadata={"model": "naive_only", "as_of": str(D.date()), "fallback": True},
    )
    result = predict_and_submit._apply_postprocess(result, panel_path)

    pp = result.metadata["postprocess"]
    assert pp["applied"] is False
    assert result.predictions["price"].tolist() == [100.0] * 24  # 原样
