"""W2-R3 稳健性窗口、聚合和选择逻辑测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.run_robustness import (
    aggregate_window_metrics,
    build_candidates,
    choose_final_candidate,
    common_key_predictions,
    generate_windows,
)


def _prediction(value: float, days: int = 2, model: str = "model") -> pd.DataFrame:
    date_index = pd.date_range("2024-11-01", periods=days, freq="D")
    return pd.DataFrame(
        {
            "day": np.repeat(date_index, 24),
            "hour": np.tile(np.arange(1, 25), days),
            "y": 0.0,
            "pred": value,
            "model": model,
        }
    )


def test_generate_windows_are_non_overlapping_and_complete() -> None:
    windows = generate_windows()
    assert len(windows) >= 20
    assert all((window.end - window.start).days == 13 for window in windows)
    assert all(
        current.start - previous.start == pd.Timedelta(days=28)
        for previous, current in zip(windows, windows[1:])
    )
    assert all(current.start > previous.end for previous, current in zip(windows, windows[1:]))
    assert windows[-1].end <= pd.Timestamp("2026-10-31")


def test_common_key_predictions_excludes_whole_missing_days() -> None:
    full = _prediction(1.0, days=3, model="a")
    partial_day = full[full["day"] != pd.Timestamp("2024-11-02")].copy()
    common, excluded = common_key_predictions(
        {"a": full, "b": partial_day},
        expected_days=pd.date_range("2024-11-01", periods=3),
    )
    assert excluded == [pd.Timestamp("2024-11-02")]
    assert set(common["a"]["day"]) == {
        pd.Timestamp("2024-11-01"),
        pd.Timestamp("2024-11-03"),
    }
    assert all(frame.groupby("day").size().eq(24).all() for frame in common.values())


def test_build_candidates_contains_weight_grid_and_formula() -> None:
    base = {
        name: _prediction(value, model=name)
        for name, value in {
            "naive_d1": 2.0,
            "ridge": 4.0,
            "lgbm": 6.0,
            "mtlasso": 8.0,
        }.items()
    }
    candidates = build_candidates(base)
    assert "mean2" in candidates and "mean3" in candidates
    assert {name for name in candidates if name.startswith("shrink2_")} == {
        "shrink2_0.5", "shrink2_0.6", "shrink2_0.7", "shrink2_0.8"
    }
    assert {name for name in candidates if name.startswith("shrink3_")} == {
        "shrink3_0.5", "shrink3_0.6", "shrink3_0.7", "shrink3_0.8"
    }
    np.testing.assert_allclose(candidates["mean2"]["pred"], 5.0)
    np.testing.assert_allclose(candidates["shrink2_0.5"]["pred"], 3.5)
    assert {len(frame) for frame in candidates.values()} == {48}


def test_aggregate_window_metrics_is_recomputable() -> None:
    rows = pd.DataFrame(
        [
            {"candidate": "a", "status": "ok", "n_days": 14, "mean": 1.0, "median": 1.0, "max": 3.0, "p90": 2.0, "crash_days": 0, "crash_rate": 0.0},
            {"candidate": "a", "status": "ok", "n_days": 14, "mean": 2.0, "median": 2.0, "max": 5.0, "p90": 4.0, "crash_days": 1, "crash_rate": 1 / 14},
            {"candidate": "b", "status": "未运行", "n_days": 0, "mean": np.nan, "median": np.nan, "max": np.nan, "p90": np.nan, "crash_days": 0, "crash_rate": np.nan},
        ]
    )
    summary = aggregate_window_metrics(rows)
    a = summary.loc[summary["candidate"] == "a"].iloc[0]
    assert a["n_windows"] == 2
    assert a["window_mean_mean"] == 1.5
    assert a["worst_window_mean"] == 2.0
    assert a["single_day_max"] == 5.0
    assert a["crash_windows"] == 1
    assert summary.loc[summary["candidate"] == "b", "status"].item() == "未运行"


def test_selection_prioritises_crash_and_worst_window() -> None:
    summary = pd.DataFrame(
        [
            {"candidate": "mean3", "status": "ok", "worst_window_mean": 5.0, "single_day_max": 30.0, "crash_windows": 1, "window_mean_mean": 4.0, "window_mean_p90": 5.0},
            {"candidate": "shrink2_0.7", "status": "ok", "worst_window_mean": 5.2, "single_day_max": 20.0, "crash_windows": 0, "window_mean_mean": 4.5, "window_mean_p90": 5.2},
        ]
    )
    assert choose_final_candidate(summary) == "shrink2_0.7"
