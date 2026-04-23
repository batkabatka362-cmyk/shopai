"""Unit tests for core/system/risk_gate.py."""
from __future__ import annotations

import pytest

from core.contracts import RiskLevel
from core.system import risk_gate


# ── classify() ────────────────────────────────────────────


class TestClassifyBaseLevels:
    def test_low_action(self):
        assert risk_gate.classify("metafield_write") == RiskLevel.LOW
        assert risk_gate.classify("tag_add") == RiskLevel.LOW
        assert risk_gate.classify("page_create") == RiskLevel.LOW

    def test_medium_action(self):
        assert (
            risk_gate.classify("product_publish") == RiskLevel.MEDIUM
        )
        assert (
            risk_gate.classify("image_upload") == RiskLevel.MEDIUM
        )
        assert (
            risk_gate.classify("webhook_subscribe")
            == RiskLevel.MEDIUM
        )

    def test_high_action(self):
        assert (
            risk_gate.classify("discount_code_create")
            == RiskLevel.HIGH
        )
        assert (
            risk_gate.classify("supplier_order_place")
            == RiskLevel.HIGH
        )
        assert (
            risk_gate.classify("product_delete") == RiskLevel.HIGH
        )

    def test_critical_action(self):
        assert (
            risk_gate.classify("live_execution_toggle")
            == RiskLevel.CRITICAL
        )
        assert (
            risk_gate.classify("policy_rewrite")
            == RiskLevel.CRITICAL
        )
        assert (
            risk_gate.classify("theme_publish") == RiskLevel.CRITICAL
        )

    def test_unknown_action_defaults_to_medium(self):
        """Unknown = safe middle — force owner to see it rather
        than silently auto-approve."""
        assert (
            risk_gate.classify("quantum_entangle_products")
            == RiskLevel.MEDIUM
        )


# ── Escalation rules ────────────────────────────────────


class TestPriceChangeEscalation:
    def test_small_price_change_stays_medium(self):
        assert (
            risk_gate.classify(
                "price_change", {"delta_pct": 3.0},
            )
            == RiskLevel.MEDIUM
        )

    def test_10_pct_escalates_to_high(self):
        assert (
            risk_gate.classify(
                "price_change", {"delta_pct": 10.0},
            )
            == RiskLevel.HIGH
        )

    def test_negative_large_change_escalates(self):
        """A 20% drop is as risky as a 20% rise — abs()."""
        assert (
            risk_gate.classify(
                "price_change", {"delta_pct": -20.0},
            )
            == RiskLevel.HIGH
        )

    def test_garbage_delta_pct_treated_as_zero(self):
        """Non-numeric delta shouldn't crash the gate."""
        assert (
            risk_gate.classify(
                "price_change", {"delta_pct": "not a number"},
            )
            == RiskLevel.MEDIUM
        )

    def test_missing_payload_treats_as_zero(self):
        assert (
            risk_gate.classify("price_change", {})
            == RiskLevel.MEDIUM
        )


class TestAdBudgetEscalation:
    def test_low_test_budget_high(self):
        """$20/day test campaign — HIGH (commits money)."""
        assert (
            risk_gate.classify(
                "ad_campaign_create",
                {"daily_budget_usd": 20.0},
            )
            == RiskLevel.HIGH
        )

    def test_above_100_escalates_to_critical(self):
        assert (
            risk_gate.classify(
                "ad_campaign_create",
                {"daily_budget_usd": 150.0},
            )
            == RiskLevel.CRITICAL
        )

    def test_500_plus_critical(self):
        assert (
            risk_gate.classify(
                "ad_budget_set",
                {"daily_budget_usd": 1000.0},
            )
            == RiskLevel.CRITICAL
        )

    def test_string_budget_treated_as_zero(self):
        assert (
            risk_gate.classify(
                "ad_budget_set",
                {"daily_budget_usd": "twenty bucks"},
            )
            == RiskLevel.HIGH  # base level since budget=0
        )


class TestInventoryEscalation:
    def test_small_drawdown_medium(self):
        assert (
            risk_gate.classify(
                "inventory_update", {"delta_units": -10},
            )
            == RiskLevel.MEDIUM
        )

    def test_large_drawdown_escalates(self):
        assert (
            risk_gate.classify(
                "inventory_update", {"delta_units": -500},
            )
            == RiskLevel.HIGH
        )

    def test_positive_stock_bump_stays_medium(self):
        assert (
            risk_gate.classify(
                "inventory_update", {"delta_units": 1000},
            )
            == RiskLevel.MEDIUM
        )


# ── is_auto_approved() policy ────────────────────────────


class TestAutoApprovePolicy:
    def test_low_always_auto(self):
        for auto in (False, True):
            for live in (False, True):
                assert risk_gate.is_auto_approved(
                    RiskLevel.LOW,
                    auto_approve=auto, live_execution=live,
                ), "LOW should always auto-approve"

    def test_medium_requires_both_flags(self):
        assert not risk_gate.is_auto_approved(
            RiskLevel.MEDIUM,
            auto_approve=False, live_execution=True,
        )
        assert not risk_gate.is_auto_approved(
            RiskLevel.MEDIUM,
            auto_approve=True, live_execution=False,
        )
        assert risk_gate.is_auto_approved(
            RiskLevel.MEDIUM,
            auto_approve=True, live_execution=True,
        )

    def test_high_never_auto(self):
        for auto in (False, True):
            for live in (False, True):
                assert not risk_gate.is_auto_approved(
                    RiskLevel.HIGH,
                    auto_approve=auto, live_execution=live,
                )

    def test_critical_never_auto(self):
        for auto in (False, True):
            for live in (False, True):
                assert not risk_gate.is_auto_approved(
                    RiskLevel.CRITICAL,
                    auto_approve=auto, live_execution=live,
                )


# ── Introspection helpers ───────────────────────────────


class TestIntrospection:
    def test_known_actions_sorted(self):
        actions = risk_gate.known_actions()
        assert actions == sorted(actions)
        assert len(actions) >= 30  # we've classified 30+

    def test_known_actions_cover_4_levels(self):
        """Every level should have at least 3 classified
        actions — if one level ends up empty, the taxonomy
        stopped being informative."""
        from collections import Counter
        levels = Counter(
            risk_gate.classify(a) for a in risk_gate.known_actions()
        )
        for level in RiskLevel:
            assert levels[level] >= 3, f"{level} has {levels[level]} actions"

    def test_describe_each_level(self):
        for level in RiskLevel:
            desc = risk_gate.describe(level)
            assert desc  # non-empty
            assert len(desc) >= 20  # actually informative
