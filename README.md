# Backtesting Agent

An AI agent that stress-tests trading strategies — pulls multi-source market data,
runs walk-forward validation with realistic costs, optimizes parameters with Optuna,
and (planned) has an LLM analyst that critiques results and proposes the next experiment.

> **Status:** skeleton only — code is being extracted from a private monorepo in phases.
> See `EXTRACTION-PLAN.md` for what lands when.

## Planned features

- **9 data providers** behind one cached, aggregated abstraction (Yahoo, Alpha Vantage,
  Polygon, Finnhub, Twelve Data, Tiingo, CoinGecko, Alpaca, frozen snapshots)
- **Deterministic reproducibility** via frozen parquet snapshots (yfinance silently
  revises historical bars; this solves it)
- **Walk-forward validation** (expanding / rolling windows, overfitting detection)
- **Optuna hyperparameter optimization** (composite objectives, pruning, timeouts)
- **Realistic cost modeling** — commission + spread + slippage
- **Parallel execution** via `ProcessPoolExecutor`
- **5 built-in strategies** — SMA cross, RSI mean-reversion, Bollinger breakout, MACD, multi-indicator
- **Next.js dashboard** — ranking, trial detail with equity / drawdown / monthly heatmap,
  parameter heatmaps, asset×strategy matrix, batch waterfall (planned Phase 3)

## Repo layout

```
backtesting-agent/
├── src/backtesting_agent/
│   ├── shared/        # BarInterval, slim Settings
│   ├── db/            # SQLAlchemy Base + PriceCacheDB
│   ├── marketdata/    # 9-provider abstraction, cache, quality, windowing
│   ├── engine/        # runner, optimizer, walk_forward, parallel, metrics
│   ├── indicators/    # trend / momentum / volatility / volume + registry
│   ├── strategies/    # SMA, RSI, Bollinger, MACD, multi-indicator
│   ├── costs/         # commission, spread, slippage, sizing
│   ├── results/       # ResultStore, ResultQuery, RegimeAnalyzer
│   ├── config/        # YAML schema, presets
│   └── analysis/      # cost sensitivity
├── api/               # thin FastAPI for the dashboard demo
├── frontend/          # Next.js dashboard (12 pages)
├── data/golden/       # frozen parquet snapshots for deterministic demo runs
└── tests/
```

## Quickstart (once Phase 2 lands)

```bash
pip install -e ".[dev]"
python run_backtest.py --preset quick
```

## License

MIT.
