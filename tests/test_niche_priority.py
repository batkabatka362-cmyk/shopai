"""Tests for engines._niche_priority."""
from __future__ import annotations

from engines._niche_priority import (
    merge_with_base, niche_cluster_focus, supported_niches,
)


class TestNicheClusterFocus:

    def test_unknown_niche_returns_empty(self):
        assert niche_cluster_focus("unknown") == []

    def test_none_returns_empty(self):
        assert niche_cluster_focus(None) == []

    def test_empty_string_returns_empty(self):
        assert niche_cluster_focus("") == []

    def test_general_returns_empty(self):
        """`general` niche means no override; use base."""
        assert niche_cluster_focus("general") == []

    def test_beauty_returns_visual_clusters_first(self):
        focus = niche_cluster_focus("beauty")
        assert focus[0] == "merchandising"
        assert "content" in focus
        assert "retention" in focus

    def test_tech_returns_quality_first(self):
        focus = niche_cluster_focus("tech")
        assert focus[0] == "quality"

    def test_food_returns_fulfillment_first(self):
        focus = niche_cluster_focus("food")
        assert focus[0] == "fulfillment"

    def test_case_insensitive(self):
        a = niche_cluster_focus("Beauty")
        b = niche_cluster_focus("beauty")
        assert a == b


class TestMergeWithBase:

    def test_no_niche_returns_base(self):
        base = ["acquisition", "quality"]
        assert merge_with_base(base, None) == base
        assert merge_with_base(base, "") == base
        assert merge_with_base(base, "general") == base

    def test_unknown_niche_returns_base(self):
        base = ["acquisition", "quality"]
        assert merge_with_base(base, "unknown") == base

    def test_niche_first_then_base(self):
        base = ["acquisition", "pricing"]
        result = merge_with_base(base, "beauty")
        # Beauty list starts with merchandising
        assert result[0] == "merchandising"
        # Base clusters still appear at the end
        assert "acquisition" in result
        assert "pricing" in result

    def test_dedup_preserves_first_occurrence(self):
        # Base contains a cluster also in niche list
        base = ["merchandising", "acquisition"]
        result = merge_with_base(base, "beauty")
        # merchandising appears only once
        assert result.count("merchandising") == 1
        # And FROM the niche position (first)
        assert result.index("merchandising") < result.index("acquisition")


class TestSupportedNiches:

    def test_includes_documented_niches(self):
        niches = supported_niches()
        for expected in ("beauty", "fashion", "home", "tech", "food"):
            assert expected in niches

    def test_general_excluded(self):
        # `general` has no preferences -> not "supported"
        niches = supported_niches()
        assert "general" not in niches
