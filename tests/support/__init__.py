"""Shared verification-harness support for the quant-review remediation (Phase 0, ATS-1794).

A €0, offline, deterministic test harness for the research loop + backtest core:

- `mock_provider.MockProvider` — an `IAIProvider` test double that records every call, returns
  canned JSON, and meters zero cost. Asserts zero LLM calls for `rule_based` (RUN-7) and lets
  `ai_assisted`/`full_ai` wiring be tested without a real key or network (AIR-2/3/4).
- `frozen_data` — deterministic synthetic OHLCV (the DataProvider shape) + a `fetch_fn` factory
  so backtests are bit-reproducible and offline (RUN-6).
- `factories` — register the mock provider in the runtime registry; seed a verified user + provider
  and mint a JWT for later API-layer tests.

Every remediation fix is proved by a regression test tagged `@pytest.mark.finding("<ID>")` that runs
on this harness at €0. See docs/reviews/REMEDIATION-PLAN.md.
"""
