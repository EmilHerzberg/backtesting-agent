from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Standalone backtesting-agent settings.

    Slimmed from the full platform: no auth/broker/IBKR. Just the database
    URL, optional market-data provider keys (the engine falls back to
    keyless Yahoo when absent), and the determinism toggle.
    """

    # Database
    database_url: str = "sqlite+aiosqlite:///data/backtest_agent.db"

    # Optional market-data provider keys (Yahoo + CoinGecko are keyless).
    alpha_vantage_api_key: str = ""
    polygon_api_key: str = ""
    twelve_data_api_key: str = ""
    finnhub_api_key: str = ""
    tiingo_api_key: str = ""

    # Reproducibility: when true, fetches route to the frozen snapshot store.
    backtest_determinism_mode: bool = False

    # CORS (Phase 3 API).
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
