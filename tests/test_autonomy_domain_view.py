"""Tests for core.automation.autonomy_domain_view (Wave 332-336)."""
from __future__ import annotations

from core.automation.autonomy_domain_view import (
    DomainView,
    _DOMAIN_ALIASES,
    _DOMAIN_META,
    list_domains,
    resolve_domain,
    run_autonomy_domain_view,
)


class TestResolveDomain:

    def test_canonical_keys(self):
        for key in [
            "customer_support_refund",
            "marketing_budget",
            "fulfillment",
            "inventory",
            "discount_cleanup",
            "order_followup",
            "product_seo",
        ]:
            assert resolve_domain(key) == key

    def test_short_aliases(self):
        assert resolve_domain("refund") == (
            "customer_support_refund"
        )
        assert resolve_domain("marketing") == (
            "marketing_budget"
        )
        assert resolve_domain("budget") == (
            "marketing_budget"
        )
        assert resolve_domain("cleanup") == "discount_cleanup"
        assert resolve_domain("followup") == "order_followup"
        assert resolve_domain("seo") == "product_seo"

    def test_unknown_returns_none(self):
        assert resolve_domain("not-a-domain") is None
        assert resolve_domain("") is None

    def test_normalises_dashes(self):
        # `discount-cleanup` should resolve same as
        # `discount_cleanup`
        assert resolve_domain("discount-cleanup") == (
            "discount_cleanup"
        )

    def test_case_insensitive(self):
        assert resolve_domain("Refund") == (
            "customer_support_refund"
        )
        assert resolve_domain("MARKETING") == (
            "marketing_budget"
        )

    def test_strips_whitespace(self):
        assert resolve_domain("  refund  ") == (
            "customer_support_refund"
        )


class TestListDomains:

    def test_returns_7_canonical_keys(self):
        keys = list_domains()
        assert len(keys) == 7
        assert "customer_support_refund" in keys
        assert "product_seo" in keys


class TestCatalogIntegrity:

    def test_aliases_all_point_to_canonical(self):
        canonical = set(_DOMAIN_META.keys())
        for alias, target in _DOMAIN_ALIASES.items():
            assert target in canonical, (alias, target)

    def test_every_canonical_is_self_alias(self):
        for key in _DOMAIN_META.keys():
            assert _DOMAIN_ALIASES.get(key) == key


class TestRunAutonomyDomainView:

    def test_unknown_returns_not_found(self):
        v = run_autonomy_domain_view("not-real")
        assert isinstance(v, DomainView)
        assert not v.found
        assert v.domain == "not-real"

    def test_known_domain_returns_view(self):
        v = run_autonomy_domain_view("refund")
        assert v.found
        assert v.domain == "customer_support_refund"

    def test_view_has_verdict(self):
        v = run_autonomy_domain_view("refund")
        assert v.verdict
        assert isinstance(v.paused, bool)

    def test_view_includes_env_knobs(self):
        v = run_autonomy_domain_view("refund")
        # refund domain has 7 env knobs registered in Pattern T
        assert v.env_knobs_total == 7

    def test_view_includes_wiring(self):
        v = run_autonomy_domain_view("refund")
        assert v.wiring_cls in {"ok", "warn", "fail", ""}

    def test_window_hours_filter_does_not_crash(self):
        v = run_autonomy_domain_view(
            "refund", window_hours=72.0,
        )
        assert v.found

    def test_store_filter_does_not_crash(self):
        v = run_autonomy_domain_view(
            "refund", store_id="store-xyz",
        )
        assert v.found


class TestDataclass:

    def test_default(self):
        v = DomainView(domain="x")
        assert not v.found
        assert v.verdict == ""
        assert v.paused is False
        assert v.applied_count == 0
        assert v.recent_events_count == 0
        assert v.sample_events == []
        assert v.env_knobs == []
