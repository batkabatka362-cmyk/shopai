"""Tests for core.automation.autonomy_fire (Wave 816)."""
from __future__ import annotations

from core.automation.autonomy_fire import (
    FireResult,
    _DOMAIN_APPLIERS,
    fire,
    known_domains,
)


class TestKnownDomains:

    def test_returns_10_domains(self):
        assert len(known_domains()) == 10

    def test_returns_sorted(self):
        ks = known_domains()
        assert ks == sorted(ks)

    def test_includes_shipping_alert(self):
        # 10th domain shipped W756-810
        assert "shipping_alert" in known_domains()

    def test_includes_substrate_only_domains(self):
        for d in (
            "fulfillment", "inventory", "discount_cleanup",
            "order_followup", "product_seo",
            "customer_outreach", "catalog_quality",
            "shipping_alert",
        ):
            assert d in known_domains()


class TestDomainAppliers:

    def test_every_entry_is_2_tuple(self):
        for d, entry in _DOMAIN_APPLIERS.items():
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            mod_path, fn_name = entry
            assert mod_path.startswith("engines.")
            assert fn_name.startswith("apply_")

    def test_every_applier_is_importable(self):
        # Smoke each entry -- if a path / name drifts, we want
        # the audit to catch it here, not at runtime.
        import importlib
        for domain, (mod_path, fn_name) in _DOMAIN_APPLIERS.items():
            mod = importlib.import_module(mod_path)
            fn = getattr(mod, fn_name, None)
            assert callable(fn), (domain, mod_path, fn_name)


class TestFireDryRun:

    def test_unknown_domain(self):
        r = fire("nope", [{}])
        assert not r.ok
        assert "unknown" in r.error
        assert not r.invoked

    def test_known_domain_dry_run_succeeds(self):
        r = fire("shipping_alert", [{"order_id": "x"}])
        assert r.ok
        assert r.dry_run
        assert not r.invoked
        assert r.payload_size == 1

    def test_empty_payload_dry_run(self):
        r = fire("inventory", [])
        assert r.ok
        assert r.payload_size == 0

    def test_dry_run_does_not_call_applier(self):
        # If dry_run actually called the applier, the result
        # would have events or invoked=True. It must not.
        r = fire("catalog_quality", [{"product_id": "p1"}])
        assert r.dry_run
        assert not r.invoked
        assert r.events == []


class TestFireLive:

    def test_substrate_domain_empty_payload_returns_empty(self):
        # Substrate appliers short-circuit on empty payload --
        # autonomy-smoke already exercises this. Phase 38 makes
        # it operator-invocable.
        r = fire("shipping_alert", [], dry_run=False)
        assert r.invoked
        assert r.ok
        assert r.events == []
        assert r.duration_ms >= 0.0


class TestFireResult:

    def test_ok_when_no_error(self):
        r = FireResult(
            domain="x", dry_run=True, payload_size=0,
        )
        assert r.ok

    def test_not_ok_with_error(self):
        r = FireResult(
            domain="x", dry_run=True, payload_size=0,
            error="boom",
        )
        assert not r.ok
