from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Auth
    secret_key: str = "dev-secret-key-change-in-production"
    access_token_expire_minutes: int = 60

    # Account-settings Phase 1 — encryption-at-rest for stored AI API keys.
    # A Fernet key (base64, from `Fernet.generate_key()`); empty = encryption disabled (plaintext fallback).
    ai_key_encryption_key: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///data/trading.db"

    # Broker
    broker_mode: str = "mock"  # "mock" or "ibkr"
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497
    ibkr_client_id: int = 1
    ibkr_account_id: str = ""

    # LLM Providers (Event-Context Pipeline)
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
    xai_api_key: str = ""
    dashscope_api_key: str = ""
    zhipu_api_key: str = ""
    openrouter_api_key: str = ""

    # Azure OpenAI (enterprise alternative)
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_deployment_name: str = ""

    # Data Providers
    alpha_vantage_api_key: str = ""
    polygon_api_key: str = ""
    twelve_data_api_key: str = ""
    finnhub_api_key: str = ""
    tiingo_api_key: str = ""

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
