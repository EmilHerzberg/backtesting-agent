#!/usr/bin/env python3
"""Convenience entry point for the backtesting CLI.

Usage::

    python run_backtest.py --preset quick
    python run_backtest.py --config src/backend/backtesting/config/examples/full.yaml
    python run_backtest.py --asset AAPL MSFT --strategy SMACrossover --trials 200
"""

from src.backend.backtesting.cli import main

if __name__ == "__main__":
    main()
