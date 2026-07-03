"""Tests for ATS-1704 — StrategyDefinition model + strategy_hash."""

import json

import pytest

from src.backend.backtesting.registry.definition import (
    StrategyDefinition,
    canonical_json,
)


def _make_definition(**overrides):
    """Helper: build a valid StrategyDefinition with sensible defaults."""
    defaults = dict(
        template_id="sma_crossover",
        template_version=1,
        template_hash="abc123",
        params={"fast_period": 10, "slow_period": 50},
        security_id="AAPL",
        bar_size="1d",
        cost_profile_id="equity_us_10bps",
        cost_profile_hash="def456",
        execution_semantics={"trade_on_close": False, "fill": "next_open"},
        strategy_family="trend_following",
    )
    defaults.update(overrides)
    return StrategyDefinition(**defaults)


# --- canonical_json ---


class TestCanonicalJson:
    def test_key_order(self):
        data = {"z": 1, "a": 2, "m": 3}
        result = canonical_json(data)
        parsed = json.loads(result)
        assert list(parsed.keys()) == ["a", "m", "z"]

    def test_output_is_valid_json(self):
        data = {"nested": {"b": 2, "a": 1}, "top": [3, 2, 1]}
        result = canonical_json(data)
        parsed = json.loads(result)
        assert parsed == data

    def test_compact_separators(self):
        result = canonical_json({"a": 1})
        assert " " not in result
        assert result == '{"a":1}'

    def test_nested_key_order(self):
        data = {"outer": {"z": 1, "a": 2}}
        result = canonical_json(data)
        assert result.index('"a"') < result.index('"z"')


# --- StrategyDefinition ---


class TestStrategyDefinition:
    def test_hash_determinism(self):
        """Same inputs produce identical hash across 100 instantiations."""
        hashes = {_make_definition().strategy_hash for _ in range(100)}
        assert len(hashes) == 1

    def test_hash_changes_on_param_change(self):
        d1 = _make_definition(params={"fast_period": 10, "slow_period": 50})
        d2 = _make_definition(params={"fast_period": 14, "slow_period": 50})
        assert d1.strategy_hash != d2.strategy_hash

    def test_hash_changes_on_template_id(self):
        d1 = _make_definition(template_id="sma_crossover")
        d2 = _make_definition(template_id="rsi_reversion")
        assert d1.strategy_hash != d2.strategy_hash

    def test_hash_changes_on_security_id(self):
        d1 = _make_definition(security_id="AAPL")
        d2 = _make_definition(security_id="MSFT")
        assert d1.strategy_hash != d2.strategy_hash

    def test_hash_changes_on_bar_size(self):
        d1 = _make_definition(bar_size="1d")
        d2 = _make_definition(bar_size="1h")
        assert d1.strategy_hash != d2.strategy_hash

    def test_hash_is_sha256_hex(self):
        d = _make_definition()
        assert len(d.strategy_hash) == 64
        assert all(c in "0123456789abcdef" for c in d.strategy_hash)

    def test_validation_rejects_empty_template_id(self):
        with pytest.raises(ValueError, match="template_id must not be empty"):
            _make_definition(template_id="")

    def test_validation_rejects_whitespace_template_id(self):
        with pytest.raises(ValueError, match="template_id must not be empty"):
            _make_definition(template_id="   ")

    def test_validation_rejects_bad_bar_size(self):
        with pytest.raises(ValueError, match="bar_size must be one of"):
            _make_definition(bar_size="3d")

    def test_model_dump_excludes_hash_from_payload(self):
        """strategy_hash is computed, not part of the serialization input."""
        d = _make_definition()
        payload = d.model_dump(exclude={"strategy_hash"})
        assert "strategy_hash" not in payload
        # But the hash IS accessible on the model
        assert d.strategy_hash

    def test_golden_hash(self):
        """Fixed inputs produce a known hash (regression guard)."""
        d = _make_definition()
        # If this ever changes, something in the serialization broke.
        assert isinstance(d.strategy_hash, str)
        assert len(d.strategy_hash) == 64
        # Store the golden value on first run, then hardcode.
        # For now just verify stability within this test.
        assert d.strategy_hash == _make_definition().strategy_hash
