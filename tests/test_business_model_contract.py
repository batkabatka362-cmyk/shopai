"""Contract tests for core.contracts.business_model.

Phase 1: these enums are pure metadata — no runtime behaviour
depends on them yet. Tests verify:

  * Enum members + canonical string values
  * String round-trip (``from_string`` ↔ ``.value``)
  * LaunchGoal backward compat — no-arg + kwargs still work
  * LaunchGoal accepts + stores the new fields
  * RiskLevel.rank() gives monotonic escalation
  * Policy helper ``requires_owner_approval`` matches the doc
"""
from __future__ import annotations

import pytest

from core.contracts import BusinessModel, Channel, RiskLevel


# ── BusinessModel ────────────────────────────────────────


class TestBusinessModel:
    def test_four_members(self):
        assert len(BusinessModel) == 4

    def test_canonical_values(self):
        assert BusinessModel.DROPSHIPPING.value == "dropshipping"
        assert BusinessModel.OWN_PRODUCTS.value == "own_products"
        assert BusinessModel.DIGITAL.value == "digital"
        assert BusinessModel.PARTNERSHIP.value == "partnership"

    def test_string_subclass_equality(self):
        """str, Enum subclass — raw string compare still works
        so legacy call sites don't break."""
        assert BusinessModel.DROPSHIPPING == "dropshipping"

    def test_from_string_case_insensitive(self):
        assert (
            BusinessModel.from_string("Dropshipping")
            is BusinessModel.DROPSHIPPING
        )
        assert (
            BusinessModel.from_string("DIGITAL")
            is BusinessModel.DIGITAL
        )

    def test_from_string_hyphen_underscore(self):
        assert (
            BusinessModel.from_string("own-products")
            is BusinessModel.OWN_PRODUCTS
        )

    def test_from_string_empty_returns_default(self):
        assert (
            BusinessModel.from_string("")
            is BusinessModel.DROPSHIPPING
        )

    def test_from_string_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown business model"):
            BusinessModel.from_string("kickstarter")

    def test_human_label(self):
        assert (
            BusinessModel.DROPSHIPPING.human_label()
            == "Dropshipping"
        )
        assert (
            BusinessModel.PARTNERSHIP.human_label()
            == "Partnership / affiliate"
        )


# ── Channel ──────────────────────────────────────────────


class TestChannel:
    def test_four_members(self):
        assert len(Channel) == 4

    def test_canonical_values(self):
        assert Channel.PAID_ADS.value == "paid_ads"
        assert Channel.CONTENT.value == "content"
        assert Channel.SEO.value == "seo"
        assert Channel.COMMUNITY.value == "community"

    def test_from_string_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown channel"):
            Channel.from_string("smoke signals")

    def test_human_label(self):
        assert Channel.PAID_ADS.human_label() == "Paid ads"
        assert Channel.SEO.human_label() == "Search / SEO"


# ── RiskLevel ────────────────────────────────────────────


class TestRiskLevel:
    def test_four_levels(self):
        assert len(RiskLevel) == 4

    def test_rank_monotonic(self):
        ranks = [
            RiskLevel.LOW.rank(),
            RiskLevel.MEDIUM.rank(),
            RiskLevel.HIGH.rank(),
            RiskLevel.CRITICAL.rank(),
        ]
        assert ranks == [0, 1, 2, 3]

    def test_requires_approval_low_never(self):
        assert not RiskLevel.LOW.requires_owner_approval()
        assert not RiskLevel.LOW.requires_owner_approval(
            auto_approve=True,
        )

    def test_requires_approval_medium_gated_by_auto_approve(self):
        assert RiskLevel.MEDIUM.requires_owner_approval(
            auto_approve=False,
        )
        assert not RiskLevel.MEDIUM.requires_owner_approval(
            auto_approve=True,
        )

    def test_requires_approval_high_critical_always(self):
        """HIGH + CRITICAL must never auto-approve, regardless of
        the auto_approve flag."""
        for level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            for auto in (False, True):
                assert level.requires_owner_approval(
                    auto_approve=auto,
                ), f"{level} should never auto-approve"

    def test_from_string_default_is_medium(self):
        """Medium is the safe default — high enough to flag
        uncertain actions but not so high every placeholder
        triggers the queue."""
        assert (
            RiskLevel.from_string("") is RiskLevel.MEDIUM
        )


# ── LaunchGoal backward compat + new fields ─────────────


class TestLaunchGoal:
    def test_no_arg_still_works(self):
        """Every existing call site uses LaunchGoal() with a
        source arg and no business_model; defaults must match
        Deguar's current cell so behaviour is identical."""
        from workflows.launch.context import LaunchGoal
        g = LaunchGoal()
        assert g.business_model is BusinessModel.DROPSHIPPING
        assert g.channel is Channel.PAID_ADS

    def test_legacy_fields_unchanged(self):
        """The 11 existing fields keep their defaults — smoke
        test covers ad_budget_day, margin_floor, copy_tone."""
        from workflows.launch.context import LaunchGoal
        g = LaunchGoal()
        assert g.ad_budget_day == 20.0
        assert g.margin_floor == 0.30
        assert g.copy_tone == "friendly"
        assert g.ad_kill_roas == 1.5

    def test_new_fields_settable(self):
        from workflows.launch.context import LaunchGoal
        g = LaunchGoal(
            business_model=BusinessModel.DIGITAL,
            channel=Channel.COMMUNITY,
        )
        assert g.business_model is BusinessModel.DIGITAL
        assert g.channel is Channel.COMMUNITY

    def test_source_kind_unchanged(self):
        """New fields don't perturb the existing source_kind()
        logic — regression guard for the most-called method
        on the struct."""
        from workflows.launch.context import LaunchGoal
        assert LaunchGoal(
            alibaba_url="https://a.com",
        ).source_kind() == "alibaba"
        assert LaunchGoal(
            supplier_sku="CJ123",
        ).source_kind() == "supplier_sku"
        assert LaunchGoal(
            manual_payload={"title": "x"},
        ).source_kind() == "manual"
        assert LaunchGoal().source_kind() == "manual"


# ── LLM prompt soft-updates ─────────────────────────────


class TestPromptInterpolation:
    """The two hard-coded ``dropshipping`` strings in
    ``decision_brain.py`` and ``model_coordinator.py`` should now
    interpolate the model label. Verified by reading the source
    (these LLM codepaths need live adapters to run — too slow
    + network-bound for a unit test)."""

    def test_decision_brain_interpolates_model_label(self):
        from pathlib import Path
        src = (
            Path(__file__).resolve().parents[1]
            / "core" / "brain" / "decision_brain.py"
        ).read_text()
        # Legacy hard-coded string no longer present
        assert 'managing a dropshipping store' not in src
        # New interpolation present
        assert "managing a {model_label} store" in src

    def test_model_coordinator_interpolates_model_label(self):
        from pathlib import Path
        src = (
            Path(__file__).resolve().parents[1]
            / "core" / "brain" / "model_coordinator.py"
        ).read_text()
        assert 'for dropshipping. Score' not in src
        assert "for {model_label}. Score" in src
