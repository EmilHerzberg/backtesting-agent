"""Tests for ATS-1767/1769/1770 — Reporter + numeric-token scan."""

import pytest

from src.backend.ai.research.reporter import (
    NumericClaimError,
    ReportSection,
    ResearchReport,
    assert_no_numeric_claims,
    scan_for_numeric_claims,
)


class TestNumericTokenScan:
    def test_detects_digits(self):
        found = scan_for_numeric_claims("The Sharpe was 1.2")
        assert len(found) > 0

    def test_detects_percent(self):
        found = scan_for_numeric_claims("Return of 25%")
        assert len(found) > 0

    def test_detects_currency(self):
        found = scan_for_numeric_claims("Costs $500 per trade")
        assert len(found) > 0

    def test_allows_template_vars(self):
        found = scan_for_numeric_claims("The Sharpe was {{metrics.sharpe}}")
        assert len(found) == 0

    def test_clean_text_passes(self):
        found = scan_for_numeric_claims(
            "The strategy shows strong momentum characteristics with "
            "reasonable risk profile and consistent trade generation."
        )
        assert len(found) == 0

    def test_assert_raises_on_numeric(self):
        with pytest.raises(NumericClaimError):
            assert_no_numeric_claims("Sharpe of 1.5", "test_slot")

    def test_assert_passes_clean(self):
        assert_no_numeric_claims("No numbers here", "test_slot")


class TestResearchReport:
    def test_validate_finds_empty_sections(self):
        report = ResearchReport()
        errors = report.validate()
        assert len(errors) > 0

    def test_validate_passes_with_content(self):
        report = ResearchReport()
        for name in ResearchReport.MANDATORY_SECTIONS:
            section = getattr(report, name)
            section.narrative = "Some qualitative assessment"
        errors = report.validate()
        assert len(errors) == 0

    def test_validate_narratives_catches_numbers(self):
        report = ResearchReport()
        report.strategy_identity.narrative = "Strategy with Sharpe 1.5"
        with pytest.raises(NumericClaimError):
            report.validate_narratives()

    def test_validate_narratives_passes_clean(self):
        report = ResearchReport()
        report.strategy_identity.narrative = "A momentum strategy on large caps"
        report.validate_narratives()  # should not raise

    def test_mandatory_sections_list(self):
        assert "strategy_identity" in ResearchReport.MANDATORY_SECTIONS
        assert "critic_notes" in ResearchReport.MANDATORY_SECTIONS
        assert "limitations" in ResearchReport.MANDATORY_SECTIONS
