"""Tests for ATS-1720/1721/1722 — Provider capability registry."""

import pytest

from src.backend.backtesting.registry.capabilities import (
    ProviderCapability,
    get_bias_flags,
    get_capability,
    reset_cache,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_cache()
    yield
    reset_cache()


class TestProviderCapability:
    def test_load_capabilities(self):
        cap = get_capability("yfinance")
        assert isinstance(cap, ProviderCapability)

    def test_yfinance_flagged(self):
        cap = get_capability("yfinance")
        assert cap.survivorship_bias_risk is True
        assert cap.research_conclusion_allowed is False
        assert cap.provider_class == "prototype_only"

    def test_eodhd_full_capability(self):
        cap = get_capability("eodhd")
        assert cap.supports_delisted is True
        assert cap.supports_pit_membership is True
        assert cap.research_conclusion_allowed is True
        assert cap.survivorship_bias_risk is False

    def test_unknown_provider_gets_conservative(self):
        cap = get_capability("some_unknown_provider")
        assert cap.survivorship_bias_risk is True
        assert cap.research_conclusion_allowed is False

    def test_bias_flags_yfinance(self):
        flags = get_bias_flags("yfinance")
        assert flags["survivorship_bias"] is True
        assert flags["point_in_time"] is False
        assert flags["research_conclusion_allowed"] is False

    def test_bias_flags_eodhd(self):
        flags = get_bias_flags("eodhd")
        assert flags["survivorship_bias"] is False
        assert flags["point_in_time"] is True
        assert flags["research_conclusion_allowed"] is True

    def test_model_validation(self):
        cap = ProviderCapability(supports_delisted=True)
        assert cap.supports_delisted is True
        assert cap.survivorship_bias_risk is True  # default
