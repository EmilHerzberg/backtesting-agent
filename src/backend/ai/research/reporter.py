"""ATS-1767/1768/1769/1770 — Reporter agent + numeric-token scan.

Produces qualitative report prose only. All numbers must come from the
result store via template bindings. The Reporter cannot fabricate numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ── Numeric-token scan (ATS-1769) ─────────────────────────────────────

# Patterns that indicate a numeric claim in free text.
_NUMERIC_PATTERNS = [
    re.compile(r"\d+\.?\d*"),              # digits, decimals
    re.compile(r"\d+%"),                   # percentages
    re.compile(r"[\$€£¥]\d+"),             # currency + digits
    re.compile(r"\d+\.\d+x"),              # multipliers like 2.5x
]

# Template variable pattern to exclude: {{binding_name}}. H28: only a BINDING IDENTIFIER is carved out
# (starts with a letter/underscore, then word chars/dots) — NOT arbitrary {{...}} content. The old
# `\{\{[^}]+\}\}` stripped any double-braced text before scanning, so an LLM emitting `{{1.2}}` (or
# `{{Sharpe was 1.2}}`) shipped digits straight past the digit-free-report guarantee.
# H28 residual (Phase-4 review): the carve-out is DIGIT-FREE — the real report bindings (metrics.sharpe,
# benchmark.buy_hold_return, …) contain no digits, so allowing digits after the first char let
# identifier-shaped-but-digit-bearing tokens ({{x2}}, {{year2020}}, {{sharpe_252}}) slip past the scan.
_TEMPLATE_VAR = re.compile(r"\{\{[a-zA-Z_][a-zA-Z_.]*\}\}")


class NumericClaimError(Exception):
    """Raised when free-text contains numeric claims."""
    pass


def scan_for_numeric_claims(text: str) -> list[str]:
    """Find numeric tokens in text that aren't template variables.

    Returns list of found numeric strings. Empty list = clean.
    """
    # Remove template variables first.
    cleaned = _TEMPLATE_VAR.sub("", text)

    found = []
    for pattern in _NUMERIC_PATTERNS:
        matches = pattern.findall(cleaned)
        found.extend(matches)

    return found


def assert_no_numeric_claims(text: str, slot_name: str = "narrative") -> None:
    """Raise NumericClaimError if text contains numeric tokens."""
    claims = scan_for_numeric_claims(text)
    if claims:
        raise NumericClaimError(
            f"Numeric claims found in {slot_name}: {claims[:5]}. "
            "Numbers must come from template bindings, not free text."
        )


# ── Report template (ATS-1770) ────────────────────────────────────────

@dataclass
class ReportSection:
    """One section of a research report."""

    title: str
    numeric_fields: dict[str, Any] = field(default_factory=dict)
    narrative: str = ""


@dataclass
class ResearchReport:
    """Full research report with template-bound numbers + qualitative prose."""

    strategy_identity: ReportSection = field(default_factory=lambda: ReportSection(title="Strategy Identity"))
    hypothesis: ReportSection = field(default_factory=lambda: ReportSection(title="Research Hypothesis"))
    benchmark_comparison: ReportSection = field(default_factory=lambda: ReportSection(title="Benchmark Comparison"))
    gate_outcomes: ReportSection = field(default_factory=lambda: ReportSection(title="Gate Outcomes"))
    dsr_analysis: ReportSection = field(default_factory=lambda: ReportSection(title="DSR Analysis"))
    critic_notes: ReportSection = field(default_factory=lambda: ReportSection(title="Critic Notes"))
    limitations: ReportSection = field(default_factory=lambda: ReportSection(title="Limitations"))
    oos_status: ReportSection = field(default_factory=lambda: ReportSection(title="OOS Status"))

    MANDATORY_SECTIONS = [
        "strategy_identity", "hypothesis", "benchmark_comparison",
        "gate_outcomes", "critic_notes", "limitations",
    ]

    def validate(self) -> list[str]:
        """Check all mandatory sections have content. Returns list of errors."""
        errors = []
        for section_name in self.MANDATORY_SECTIONS:
            section = getattr(self, section_name, None)
            if section is None:
                errors.append(f"Missing section: {section_name}")
            elif not section.numeric_fields and not section.narrative:
                errors.append(f"Empty section: {section_name}")
        return errors

    def validate_narratives(self) -> None:
        """Scan all narrative slots for numeric claims."""
        for section_name in self.MANDATORY_SECTIONS:
            section = getattr(self, section_name, None)
            if section and section.narrative:
                assert_no_numeric_claims(section.narrative, section_name)
