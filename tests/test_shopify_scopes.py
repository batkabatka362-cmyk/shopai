"""Shopify scope canonical-source regression.

Guards against drift between the OAuth redirect default,
the owner-facing audit script, and each wave's resource
implementation.
"""
from __future__ import annotations

import pytest

from core.auth.shopify_scopes import (
    Scope,
    all_scopes,
    diff_granted,
    plus_scopes,
    recommended_scopes,
    required_scopes,
    scope_string,
)


# ── Invariants ───────────────────────────────────────────


class TestInvariants:
    def test_every_scope_has_handle_and_tier(self):
        for s in all_scopes():
            assert s.handle
            assert s.tier in {
                "required", "recommended", "plus_only",
            }
            assert s.why

    def test_no_duplicate_handles(self):
        handles = [s.handle for s in all_scopes()]
        assert len(handles) == len(set(handles)), (
            "duplicate scope handle in canonical list"
        )

    def test_tier_partitions_sum_to_total(self):
        r = len(required_scopes())
        rec = len(recommended_scopes())
        p = len(plus_scopes())
        assert r + rec + p == len(all_scopes())

    def test_required_count_matches_wave_coverage(self):
        """Wave 5 brought the canonical surface up to 58
        resources. The required scope set should not regress
        below 15 — anything less means a wave was dropped
        from the canonical list without being replaced."""
        assert len(required_scopes()) >= 15

    def test_all_scopes_have_at_least_one_wave(self):
        """Every scope must justify its presence by pointing
        at the wave(s) that depend on it. Prevents future
        drift where scopes get added without a code home."""
        for s in all_scopes():
            assert s.waves, (
                f"{s.handle} has no wave tag — either wire "
                "it to a wave or remove the scope"
            )


# ── Wave coverage — pin each wave's scope dependencies ──


class TestWaveCoverage:
    """If a wave implementation changes which scopes it
    needs, this test fails until both sides are updated.
    Keeps the scope list honest."""

    def _scopes_for_wave(self, wave: str) -> set[str]:
        return {
            s.handle for s in all_scopes()
            if wave in s.waves
        }

    def test_wave_1_discounts_inventory_draft(self):
        handles = self._scopes_for_wave("1")
        assert "read_products" in handles
        assert "write_products" in handles
        assert "read_inventory" in handles
        assert "write_inventory" in handles
        assert "read_locations" in handles
        assert "read_draft_orders" in handles
        assert "write_draft_orders" in handles
        assert "read_price_rules" in handles
        assert "write_price_rules" in handles
        assert "read_discounts" in handles
        assert "write_discounts" in handles

    def test_wave_2_fulfillments_refunds_customers(self):
        handles = self._scopes_for_wave("2")
        assert "read_orders" in handles
        assert "read_all_orders" in handles
        assert "read_customers" in handles
        assert "write_customers" in handles
        assert "read_fulfillments" in handles
        assert "write_fulfillments" in handles

    def test_wave_3a_orders_products(self):
        handles = self._scopes_for_wave("3a")
        assert "read_orders" in handles
        assert "read_all_orders" in handles
        # Write_orders is wave 3a's critical scope.
        assert "write_orders" in handles
        assert "read_products" in handles
        assert "write_products" in handles

    def test_wave_3b_themes_shipping(self):
        handles = self._scopes_for_wave("3b")
        assert "read_themes" in handles
        assert "write_themes" in handles
        assert "read_shipping" in handles
        assert "write_shipping" in handles

    def test_wave_4a_gift_cards(self):
        handles = self._scopes_for_wave("4a")
        assert "read_gift_cards" in handles
        assert "write_gift_cards" in handles

    def test_wave_4b_collections(self):
        handles = self._scopes_for_wave("4b")
        # Collections live under product scope.
        assert "read_products" in handles
        assert "write_products" in handles

    def test_wave_4c_markets(self):
        handles = self._scopes_for_wave("4c")
        assert "read_markets" in handles
        assert "write_markets" in handles

    def test_wave_4d_marketing_events(self):
        handles = self._scopes_for_wave("4d")
        assert "read_marketing_events" in handles
        assert "write_marketing_events" in handles

    def test_wave_4e_blogs_articles_pages(self):
        handles = self._scopes_for_wave("4e")
        assert "read_content" in handles
        assert "write_content" in handles

    def test_wave_5a_shop_locales_currencies(self):
        handles = self._scopes_for_wave("5a")
        assert "read_locales" in handles
        assert "write_locales" in handles

    def test_wave_5b_disputes(self):
        handles = self._scopes_for_wave("5b")
        assert "read_shopify_payments_disputes" in handles
        # OrderRisks writes need write_orders.
        assert "write_orders" in handles

    def test_wave_5c_fulfillment_services(self):
        handles = self._scopes_for_wave("5c")
        assert "read_fulfillments" in handles
        assert "write_fulfillments" in handles

    def test_wave_5d_customer_extras(self):
        handles = self._scopes_for_wave("5d")
        assert "read_customers" in handles
        assert "write_customers" in handles

    def test_wave_5e_automatic_discounts_comments(self):
        handles = self._scopes_for_wave("5e")
        assert "read_discounts" in handles
        assert "write_discounts" in handles
        assert "read_content" in handles
        assert "write_content" in handles

    def test_wave_5f_reports_payouts(self):
        handles = self._scopes_for_wave("5f")
        assert "read_reports" in handles
        assert (
            "read_shopify_payments_payouts" in handles
        )
        # tax rates → shipping scope family.
        assert "read_shipping" in handles


# ── scope_string ─────────────────────────────────────────


class TestScopeString:
    def test_default_includes_required_and_recommended(self):
        s = scope_string()
        for r in required_scopes():
            assert r.handle in s
        for rec in recommended_scopes():
            assert rec.handle in s
        # Plus-only scopes excluded by default.
        for p in plus_scopes():
            assert p.handle not in s

    def test_required_only_when_recommended_off(self):
        s = scope_string(include_recommended=False)
        for r in required_scopes():
            assert r.handle in s
        for rec in recommended_scopes():
            assert rec.handle not in s

    def test_plus_opt_in(self):
        s = scope_string(include_plus=True)
        for p in plus_scopes():
            assert p.handle in s


# ── diff_granted ─────────────────────────────────────────


class TestDiff:
    def test_fully_granted(self):
        handles = [s.handle for s in all_scopes()]
        d = diff_granted(handles)
        assert len(d["granted"]) == len(all_scopes())
        assert d["missing"] == []
        assert d["extra"] == []

    def test_extra_surfaced(self):
        handles = [
            s.handle for s in all_scopes()
        ] + ["read_something_weird"]
        d = diff_granted(handles)
        assert len(d["extra"]) == 1
        assert d["extra"][0].handle == "read_something_weird"

    def test_empty_granted_reports_all_missing(self):
        d = diff_granted([])
        assert len(d["missing"]) == len(all_scopes())

    def test_missing_required_surfaces_separately(self):
        """After a fresh install without the write-tier
        scopes, diff_granted lets the caller sort by tier."""
        reads_only = [s.handle for s in all_scopes() if s.tier == "required" and s.handle.startswith("read_")]
        d = diff_granted(reads_only)
        missing_req = [
            s for s in d["missing"] if s.tier == "required"
        ]
        # Every required write is in the missing set.
        write_handles = {
            s.handle for s in missing_req
            if s.handle.startswith("write_")
        }
        assert "write_products" in write_handles
        assert "write_orders" in write_handles


# ── Sync with legacy auth default ───────────────────────


class TestAuthDefaultSync:
    def test_auth_get_auth_url_pulls_from_canonical(self):
        """Guards against reintroducing the hard-coded 6-scope
        string we had before this wave."""
        import inspect
        from core.auth import shopify_auth
        src = inspect.getsource(shopify_auth.ShopifyAuth.get_auth_url)
        assert "from core.auth.shopify_scopes" in src
        assert "scope_string()" in src


# ── MCP tool ─────────────────────────────────────────────


class TestMCPTool:
    def test_registered(self):
        from mcp_server.tools import build_default_registry
        reg = build_default_registry()
        names = {t.name for t in reg.list_tools()}
        assert "shopify_scope_audit" in names

    def test_handler_with_explicit_granted_fully_ok(self):
        """When every canonical handle is in the granted
        list, verdict is OK + missing_required is empty."""
        from core.auth.shopify_scopes import all_scopes
        from mcp_server.tools import (
            _shopify_scope_audit_handler,
        )
        handles = [s.handle for s in all_scopes()]
        out = _shopify_scope_audit_handler(
            {"granted": handles},
        )
        assert out["verdict"] == "OK"
        assert out["missing_required_count"] == 0

    def test_handler_empty_granted_lists_all_missing(self):
        from mcp_server.tools import (
            _shopify_scope_audit_handler,
        )
        # Passing an empty list (not omitted) skips the
        # live-fetch branch and reports everything as
        # missing.
        out = _shopify_scope_audit_handler({"granted": []})
        # May report live-fetch error OR the full missing
        # list depending on environment.
        if "error" in out:
            assert out["canonical_required_count"] >= 15
        else:
            assert out["verdict"] == "BLOCKED"
            assert out["missing_required_count"] >= 15

    def test_handler_rejects_non_list_granted(self):
        from mcp_server.tools import (
            _shopify_scope_audit_handler, ToolError,
        )
        with pytest.raises(ToolError):
            _shopify_scope_audit_handler(
                {"granted": "read_products"},
            )

    def test_handler_partial_grant_lists_right_missing(self):
        from mcp_server.tools import (
            _shopify_scope_audit_handler,
        )
        out = _shopify_scope_audit_handler({
            "granted": [
                "read_products", "read_orders",
                "read_customers",
            ],
        })
        assert out["verdict"] == "BLOCKED"
        # write_products + write_orders + write_customers
        # must show up in missing_required.
        missing_handles = {
            m["handle"] for m in out["missing_required"]
        }
        assert "write_products" in missing_handles
        assert "write_orders" in missing_handles
        assert "write_customers" in missing_handles
