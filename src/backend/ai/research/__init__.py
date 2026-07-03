"""Quantbt autonomous research loop — Strategist, Orchestrator, state machine.

Key components:
- run_research(): One-call entry point (START -> RESULT)
- research_loop(): Core state machine
- RuleBasedStrategist: No-LLM strategy proposer
- RuleBasedOrchestrator: Pluggable meta-decision maker
- AdversarialCritic: Rule-based (or LLM) adversarial reviewer
- ResearchExecutor: Backtest engine wrapper
- ResearchGatekeeper: Quality gate pipeline wrapper
"""
