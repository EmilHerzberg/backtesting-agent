"""ATS-1736/1737 — Synthetic OHLCV generation for leakage canary.

Two variants:
1. Zero-drift random walk with volatility matching
2. Block bootstrap preserving vol clustering
Both produce structurally valid OHLCV: high >= max(open, close), low <= min(open, close).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def generate_random_walk_ohlcv(
    real_df: pd.DataFrame,
    n_paths: int = 100,
    seed: int = 42,
) -> list[pd.DataFrame]:
    """Generate zero-drift, vol-matched random walk OHLCV paths.

    Args:
        real_df: Real OHLCV DataFrame (needs Close column + DatetimeIndex).
        n_paths: Number of synthetic paths to generate.
        seed: RNG seed for reproducibility.

    Returns:
        List of n_paths DataFrames, each with valid OHLCV structure.
    """
    rng = np.random.default_rng(seed)
    close = real_df["Close"].dropna().values.astype(np.float64)

    if len(close) < 2:
        return []

    # Match volatility of real returns.
    real_returns = np.diff(np.log(close))
    vol = np.std(real_returns)
    n_bars = len(close)

    # Real intrabar ranges for OHLCV structure.
    real_high_pct = ((real_df["High"] / real_df["Close"]) - 1).dropna().values
    real_low_pct = (1 - (real_df["Low"] / real_df["Close"])).dropna().values
    real_open_pct = ((real_df["Open"] / real_df["Close"].shift(1)) - 1).dropna().values
    real_volume = real_df["Volume"].dropna().values

    paths = []
    for i in range(n_paths):
        # Zero-drift random walk in log space.
        log_returns = rng.normal(0.0, vol, n_bars - 1)
        log_prices = np.zeros(n_bars)
        log_prices[0] = np.log(close[0])
        log_prices[1:] = log_prices[0] + np.cumsum(log_returns)
        syn_close = np.exp(log_prices)

        # Build valid OHLCV structure.
        syn_open = np.empty(n_bars)
        syn_open[0] = syn_close[0] * (1 + rng.choice(real_open_pct[:min(len(real_open_pct), n_bars)]))
        for j in range(1, n_bars):
            syn_open[j] = syn_close[j - 1] * (1 + rng.choice(real_open_pct[:min(len(real_open_pct), n_bars)]))

        high_add = np.abs(rng.choice(real_high_pct[:min(len(real_high_pct), n_bars)], n_bars))
        low_sub = np.abs(rng.choice(real_low_pct[:min(len(real_low_pct), n_bars)], n_bars))

        syn_high = np.maximum(syn_open, syn_close) * (1 + high_add)
        syn_low = np.minimum(syn_open, syn_close) * (1 - low_sub)

        # Ensure structural validity.
        syn_high = np.maximum(syn_high, np.maximum(syn_open, syn_close))
        syn_low = np.minimum(syn_low, np.minimum(syn_open, syn_close))
        syn_low = np.maximum(syn_low, 0.01)  # no negative prices

        syn_volume = rng.permutation(real_volume[:n_bars]) if len(real_volume) >= n_bars else rng.integers(1000, 100000, n_bars)

        df = pd.DataFrame({
            "Open": syn_open,
            "High": syn_high,
            "Low": syn_low,
            "Close": syn_close,
            "Volume": syn_volume.astype(np.int64),
        }, index=real_df.index[:n_bars])

        paths.append(df)

    return paths


def generate_block_bootstrap_ohlcv(
    real_df: pd.DataFrame,
    n_paths: int = 100,
    block_len: int = 20,
    seed: int = 42,
) -> list[pd.DataFrame]:
    """Block bootstrap: shuffle blocks of returns, reconstruct prices.

    Preserves fat tails and vol clustering within blocks while
    destroying exploitable temporal structure across blocks.

    Args:
        real_df: Real OHLCV DataFrame.
        n_paths: Number of synthetic paths.
        block_len: Length of each block (trading days).
        seed: RNG seed.

    Returns:
        List of n_paths DataFrames with valid OHLCV structure.
    """
    rng = np.random.default_rng(seed)
    close = real_df["Close"].dropna().values.astype(np.float64)

    if len(close) < block_len + 1:
        return []

    log_returns = np.diff(np.log(close))
    n_returns = len(log_returns)
    n_blocks = n_returns // block_len

    if n_blocks < 2:
        return []

    # Split returns into blocks.
    blocks = [log_returns[i * block_len:(i + 1) * block_len] for i in range(n_blocks)]
    remainder = log_returns[n_blocks * block_len:]

    # Real intrabar structure.
    real_high_pct = np.abs(((real_df["High"] / real_df["Close"]) - 1).dropna().values)
    real_low_pct = np.abs((1 - (real_df["Low"] / real_df["Close"])).dropna().values)
    real_volume = real_df["Volume"].dropna().values
    n_bars = len(close)

    paths = []
    for i in range(n_paths):
        # Shuffle blocks, reconstruct.
        shuffled_idx = rng.permutation(n_blocks)
        shuffled_returns = np.concatenate([blocks[j] for j in shuffled_idx])
        if len(remainder) > 0:
            shuffled_returns = np.concatenate([shuffled_returns, remainder])

        # Trim or pad to match original length.
        shuffled_returns = shuffled_returns[:n_returns]

        log_prices = np.zeros(n_bars)
        log_prices[0] = np.log(close[0])
        log_prices[1:len(shuffled_returns) + 1] = log_prices[0] + np.cumsum(shuffled_returns)
        if len(shuffled_returns) + 1 < n_bars:
            log_prices[len(shuffled_returns) + 1:] = log_prices[len(shuffled_returns)]

        syn_close = np.exp(log_prices)

        # Build OHLCV.
        syn_open = np.empty(n_bars)
        syn_open[0] = syn_close[0]
        syn_open[1:] = syn_close[:-1] * (1 + rng.normal(0, 0.001, n_bars - 1))

        high_add = rng.choice(real_high_pct[:min(len(real_high_pct), n_bars)], n_bars)
        low_sub = rng.choice(real_low_pct[:min(len(real_low_pct), n_bars)], n_bars)

        syn_high = np.maximum(syn_open, syn_close) * (1 + np.abs(high_add))
        syn_low = np.minimum(syn_open, syn_close) * (1 - np.abs(low_sub))
        syn_high = np.maximum(syn_high, np.maximum(syn_open, syn_close))
        syn_low = np.minimum(syn_low, np.minimum(syn_open, syn_close))
        syn_low = np.maximum(syn_low, 0.01)

        syn_volume = rng.permutation(real_volume[:n_bars]) if len(real_volume) >= n_bars else rng.integers(1000, 100000, n_bars)

        df = pd.DataFrame({
            "Open": syn_open,
            "High": syn_high,
            "Low": syn_low,
            "Close": syn_close,
            "Volume": syn_volume.astype(np.int64),
        }, index=real_df.index[:n_bars])

        paths.append(df)

    return paths
