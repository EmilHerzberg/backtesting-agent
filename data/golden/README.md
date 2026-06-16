# Golden snapshots

Frozen parquet OHLCV snapshots for deterministic demo runs.

Phase 2 will land at least one snapshot here so `python run_backtest.py --preset quick`
is reproducible bit-for-bit (yfinance silently revises historical bars; the snapshot
solves it).

Format: `<symbol>_<interval>_<start>_<end>.parquet` (e.g. `AAPL_1d_2020-01-01_2023-12-31.parquet`).
