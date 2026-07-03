"""Tests for ONE_WEEK BarInterval + AssetClass.INDEX (ATS-128, ATS-129)."""

from __future__ import annotations

from src.backend.shared.types import AssetClass, BarInterval


class TestBarIntervalOneWeek:
    def test_one_week_in_enum(self):
        assert BarInterval.ONE_WEEK == "1wk"

    def test_yahoo_map_has_one_week(self):
        from src.backend.marketdata.provider import _YF_INTERVAL_MAP
        assert _YF_INTERVAL_MAP[BarInterval.ONE_WEEK] == "1wk"

    def test_alpha_vantage_map_has_weekly(self):
        from src.backend.marketdata.provider import _AV_INTERVAL_MAP
        assert _AV_INTERVAL_MAP[BarInterval.ONE_WEEK] == "weekly"


class TestAssetClassIndex:
    def test_index_in_enum(self):
        assert AssetClass.INDEX == "INDEX"
        assert AssetClass.INDEX in list(AssetClass)
