"""Tests for ``core.capability_registry``.

The registry is the foundation layer for AGI-style use of
ShopAI's substrate. These tests lock in the schema +
find/query contract so future iterations (planner, daily-
brief, LLM context blocks) can rely on stable behaviour.

Coverage:
  - Capability dataclass: required fields + serialisation
  - Registry: register / overwrite / clear / get / all
  - find() filters: kind / tag / closes_audit / composes_with / query
  - Empty/None filters skip silently
  - Bootstrap is idempotent + reset_for_tests works
  - Launch-chain batch registers expected entries
"""
from __future__ import annotations

import pytest

from core.capability_registry import (
    Capability,
    CapabilityKind,
    get_registry,
    register_capability,
)
from core.capability_registry.bootstrap import (
    ensure_registered,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Wipe the registry before each test so cases don't
    bleed into each other."""
    reset_for_tests()
    yield
    reset_for_tests()


def _make(name: str, **kw) -> Capability:
    """Minimal valid capability with overrides."""
    defaults = dict(
        kind=CapabilityKind.ENGINE,
        description="...",
        when_to_use="...",
        module_path=f"x.y:{name}",
    )
    defaults.update(kw)
    return Capability(name=name, **defaults)


class TestCapabilityDataclass:

    def test_required_fields_only(self):
        cap = _make("a")
        assert cap.name == "a"
        assert cap.kind == CapabilityKind.ENGINE
        # Optional fields default to empty
        assert cap.inputs == {}
        assert cap.outputs == {}
        assert cap.tags == []
        assert cap.audit_checks_closed == []

    def test_to_dict_serialises(self):
        cap = _make(
            "x",
            tags=["a", "b"],
            audit_checks_closed=["k"],
            inputs={"foo": "bar"},
        )
        d = cap.to_dict()
        assert d["name"] == "x"
        assert d["tags"] == ["a", "b"]
        assert d["audit_checks_closed"] == ["k"]
        assert d["inputs"] == {"foo": "bar"}
        # to_dict returns COPIES, not aliases (defensive)
        d["tags"].append("c")
        assert cap.tags == ["a", "b"]


class TestRegisterAndRead:

    def test_register_and_get(self):
        register_capability(_make("alpha"))
        r = get_registry()
        cap = r.get("alpha")
        assert cap is not None
        assert cap.name == "alpha"

    def test_get_missing_returns_none(self):
        assert get_registry().get("nope") is None

    def test_register_overwrites_by_name(self):
        register_capability(_make("dup", description="v1"))
        register_capability(_make("dup", description="v2"))
        cap = get_registry().get("dup")
        assert cap.description == "v2"
        assert get_registry().count() == 1

    def test_empty_name_raises(self):
        with pytest.raises(ValueError):
            register_capability(_make(""))

    def test_clear_wipes(self):
        register_capability(_make("a"))
        register_capability(_make("b"))
        assert get_registry().count() == 2
        get_registry().clear()
        assert get_registry().count() == 0

    def test_all_sorted_alphabetically(self):
        register_capability(_make("zebra"))
        register_capability(_make("alpha"))
        register_capability(_make("mango"))
        names = [c.name for c in get_registry().all()]
        assert names == ["alpha", "mango", "zebra"]


class TestFind:

    def _seed(self):
        register_capability(_make(
            "writer-a",
            kind=CapabilityKind.APPLIER,
            tags=["launch"],
            audit_checks_closed=["legal_policies"],
            description="writes legal policies",
        ))
        register_capability(_make(
            "writer-b",
            kind=CapabilityKind.APPLIER,
            tags=["post-launch"],
            audit_checks_closed=["active_products"],
            description="seeds products",
        ))
        register_capability(_make(
            "engine-a",
            kind=CapabilityKind.ENGINE,
            tags=["design"],
            description="store design engine",
            when_to_use="use for mobile design",
        ))

    def test_filter_by_kind(self):
        self._seed()
        appliers = get_registry().find(
            kind=CapabilityKind.APPLIER,
        )
        assert {c.name for c in appliers} == {
            "writer-a", "writer-b",
        }

    def test_filter_by_tag(self):
        self._seed()
        launch_caps = get_registry().find(tag="launch")
        assert [c.name for c in launch_caps] == ["writer-a"]

    def test_filter_by_audit_check(self):
        self._seed()
        caps = get_registry().find(
            closes_audit="active_products",
        )
        assert [c.name for c in caps] == ["writer-b"]

    def test_filter_by_query_matches_description(self):
        self._seed()
        caps = get_registry().find(query="policies")
        assert "writer-a" in [c.name for c in caps]

    def test_filter_by_query_matches_when_to_use(self):
        self._seed()
        caps = get_registry().find(query="mobile")
        assert [c.name for c in caps] == ["engine-a"]

    def test_filter_combined_filters_AND(self):
        self._seed()
        caps = get_registry().find(
            kind=CapabilityKind.APPLIER,
            tag="launch",
        )
        assert [c.name for c in caps] == ["writer-a"]

    def test_no_filters_returns_all(self):
        self._seed()
        caps = get_registry().find()
        assert len(caps) == 3

    def test_empty_query_skipped(self):
        self._seed()
        caps = get_registry().find(query="   ")
        assert len(caps) == 3

    def test_composes_with_filter(self):
        register_capability(_make(
            "a", composes_with=["b"],
        ))
        register_capability(_make(
            "c", composes_with=["d", "e"],
        ))
        results = get_registry().find(composes_with="b")
        assert [c.name for c in results] == ["a"]


class TestBootstrap:

    def test_idempotent(self):
        ensure_registered()
        count1 = get_registry().count()
        ensure_registered()
        count2 = get_registry().count()
        assert count1 == count2
        assert count1 > 0

    def test_reset_for_tests_clears(self):
        ensure_registered()
        assert get_registry().count() > 0
        reset_for_tests()
        assert get_registry().count() == 0

    def test_launch_chain_capabilities_registered(self):
        """The first batch (launch chain) registers known
        names. This test locks in the inventory so renames
        / removals are caught."""
        ensure_registered()
        names = set(get_registry().names())
        expected_subset = {
            "launch_store", "audit_store",
            "post_launch_enrich",
            "enrich_seo", "apply_seo",
            "enrich_descriptions", "apply_descriptions",
            "generate_policies", "apply_policies",
            "generate_pages", "apply_pages",
            "generate_welcome_discount",
            "apply_welcome_discount",
            "generate_starter_collections",
            "apply_starter_collections",
            "generate_starter_products",
            "apply_starter_products",
            "upload_brand_assets",
            "apply_design", "store_design_engine",
        }
        missing = expected_subset - names
        assert not missing, (
            f"launch-chain batch missing: {missing}"
        )

    def test_launch_chain_audit_links(self):
        """Each writer in the launch chain declares which
        launch_audit check it closes. The audit-side of the
        loop relies on this."""
        ensure_registered()
        r = get_registry()
        # apply_policies closes legal_policies
        assert "legal_policies" in r.get(
            "apply_policies",
        ).audit_checks_closed
        # apply_starter_products closes active_products
        assert "active_products" in r.get(
            "apply_starter_products",
        ).audit_checks_closed
        # upload_brand_assets closes brand_assets
        assert "brand_assets" in r.get(
            "upload_brand_assets",
        ).audit_checks_closed
        # apply_design closes design_tokens
        assert "design_tokens" in r.get(
            "apply_design",
        ).audit_checks_closed

    def test_orchestrator_closes_multiple_checks(self):
        ensure_registered()
        cap = get_registry().get("launch_store")
        assert cap is not None
        # launch_store can close up to 7 audit checks
        assert len(cap.audit_checks_closed) >= 5

    def test_analytics_batch_registered(self):
        """The fourth batch (analytics / financial /
        competitive / strategy / ops) locks in the
        remaining operator surface."""
        ensure_registered()
        names = set(get_registry().names())
        expected = {
            # Financial
            "accounting", "cash_flow", "cashflow_simulator",
            "profit_optimization",
            "profitability_calculator",
            "ltv_cac_dashboard",
            # Analytics
            "conversion_tracking", "customer_effort_score",
            "customer_behavior_simulator", "forecasting",
            "data_collection", "data_enrichment",
            # Competitive
            "competitor_analysis",
            "competitor_ad_intelligence",
            "competitor_monitor",
            "competitor_reaction_simulator",
            "competitor_social",
            # Strategy + Ops
            "campaign_strategy", "dropshipping",
            "gift_card", "returns_management",
            "warranty", "upsell",
        }
        missing = expected - names
        assert not missing, (
            f"analytics batch missing: {missing}"
        )

    def test_registry_at_target_size(self):
        """Smoke: after all batches, registry has ~85
        entries covering the operator-merchant surface."""
        ensure_registered()
        assert get_registry().count() >= 80

    def test_marketing_batch_registered(self):
        """The third batch (marketing / content / ops /
        customer-facing engines) locks in the broader
        operator surface."""
        ensure_registered()
        names = set(get_registry().names())
        expected = {
            # Acquisition
            "ad_creative_generator", "email_marketing",
            "trend_detection", "trend_discovery",
            # Conversion
            "ab_testing", "checkout_optimizer", "chatbot",
            # Content + brand
            "content_generation", "brand_voice_enforcer",
            "brand_visual", "brand_positioning",
            # Customer-facing
            "customer_service", "customer_support",
            "customer_segmentation", "review_management",
            # Operations
            "inventory", "order_management",
            "order_quality", "shipping_optimization",
            "fraud_detection", "subscription",
            # Supply
            "supplier", "supplier_discovery",
            "supplier_communication", "wholesale_b2b",
            # Reporting
            "email_reporter",
        }
        missing = expected - names
        assert not missing, (
            f"marketing batch missing: {missing}"
        )

    def test_engines_batch_post_launch_engines_registered(self):
        """The second batch (post-launch operational
        engines) locks in the Phase 6 writeback set + the
        recovery / retention engines."""
        ensure_registered()
        names = set(get_registry().names())
        expected = {
            "loyalty", "discount_strategy",
            "dynamic_pricing", "tag_management",
            "affiliate", "product_lifecycle",
            "cart_recovery", "browse_recovery",
            "churn_prediction",
            "bundle", "cross_sell",
            "cohort_analysis", "customer_journey",
            "audience_targeting", "demand_analysis",
            "catalog", "competition_analyzer",
        }
        missing = expected - names
        assert not missing, (
            f"engines batch missing: {missing}"
        )
