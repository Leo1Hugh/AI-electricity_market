"""Metrics used by the electricity-market backtests."""

from __future__ import annotations

import numpy as np


def daily_rmse(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    """Compute one RMSE per day along the hour axis.

    NaN observations are ignored.  A day with no finite paired observations
    produces ``NaN``; this allows missing days to be carried through to a
    later summary without turning the whole result into an exception.
    """
    true = np.asarray(y_true, dtype=float)
    pred = np.asarray(y_pred, dtype=float)
    if true.shape != pred.shape:
        raise ValueError("y_true and y_pred must have the same shape")
    if true.ndim != 2:
        raise ValueError("y_true and y_pred must be two-dimensional")

    # Only paired finite values contribute.  In particular, a missing target
    # or prediction does not count as an error for the day.
    valid = np.isfinite(true) & np.isfinite(pred)
    sqerr = (true - pred) ** 2
    sqerr = np.where(valid, sqerr, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        result = np.sqrt(np.nanmean(sqerr, axis=1))
    # np.nanmean emits a warning for empty rows but returns the desired NaN.
    return np.asarray(result, dtype=float)


def summarize_daily_rmse(daily: np.ndarray, crash_threshold: float = 20.0) -> dict:
    """Summarize daily RMSE values using NaN-safe statistics."""
    values = np.asarray(daily, dtype=float).reshape(-1)
    if not np.isfinite(crash_threshold):
        raise ValueError("crash_threshold must be finite")
    valid = values[np.isfinite(values)]
    n_days = int(valid.size)
    if n_days == 0:
        return {
            "n_days": 0,
            "mean": float("nan"),
            "median": float("nan"),
            "max": float("nan"),
            "p90": float("nan"),
            "crash_days": 0,
            "crash_rate": float("nan"),
        }
    crash_days = int(np.count_nonzero(valid > crash_threshold))
    return {
        "n_days": n_days,
        "mean": float(np.mean(valid)),
        "median": float(np.median(valid)),
        "max": float(np.max(valid)),
        # NumPy's default percentile method is the required linear method.
        "p90": float(np.percentile(valid, 90)),
        "crash_days": crash_days,
        "crash_rate": float(crash_days / n_days),
    }


def paired_block_bootstrap(
    diff: np.ndarray,
    block: int = 7,
    n_boot: int = 10000,
    seed: int = 0,
) -> dict:
    """Circular paired block bootstrap for a sequence of daily differences."""
    values = np.asarray(diff, dtype=float).reshape(-1)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return {
            "mean": float("nan"),
            "lo": float("nan"),
            "hi": float("nan"),
            "p_two_sided": float("nan"),
        }
    if not isinstance(block, (int, np.integer)) or block <= 0:
        raise ValueError("block must be a positive integer")
    if not isinstance(n_boot, (int, np.integer)) or n_boot <= 0:
        raise ValueError("n_boot must be a positive integer")

    n = values.size
    n_blocks = int(np.ceil(n / block))
    rng = np.random.default_rng(seed)
    # Draw all starts at once, then gather circular blocks.  This preserves
    # adjacency inside each block while allowing blocks to wrap at the ends.
    starts = rng.integers(0, n, size=(n_boot, n_blocks))
    offsets = np.arange(block)
    indices = (starts[..., None] + offsets) % n
    samples = values[indices].reshape(n_boot, n_blocks * block)[:, :n]
    bs_means = samples.mean(axis=1)

    p_le = float(np.mean(bs_means <= 0.0))
    p_ge = float(np.mean(bs_means >= 0.0))
    return {
        "mean": float(np.mean(values)),
        "lo": float(np.percentile(bs_means, 2.5)),
        "hi": float(np.percentile(bs_means, 97.5)),
        "p_two_sided": float(min(1.0, 2.0 * min(p_le, p_ge))),
    }
