"""Wave 98: end-to-end integration test for shopai onboard.

Unit tests in test_onboarding_wizard.py mock every downstream
boundary (launch_orchestrator, launch_audit, sync_service,
go_live_check). That's fast but misses wiring bugs -- the stage
chain might pass data correctly between mocks while still
breaking with the real implementations.

This integration test uses:
  - REAL ``ShopAIDatabase(":memory:")``  (full SQLite schema)
  - REAL ``StoreManager``                 (CRUD + niche update)
  - STUBBED Shopify HTTP boundary         (no live API calls)

The wizard's stage chain, retry loop, credential gating, and
final-verdict logic all exercise their real implementations
against a real local store row.

Trust anchor: if any layer above StoreManager breaks the
contract the wizard depends on, THIS test fails first.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch

from data_pipeline.store.db import ShopAIDatabase
from data_pipeline.store.store_manager import StoreManager
from engines.store_setup.onboarding_wizard import onboard_store


@pytest.fixture
def real_sm():
    """Real StoreManager backed by an in-memory SQLite."""
    db = ShopAIDatabase(":memory:")
    return StoreManager(db=db)


@pytest.fixture
def stubbed_shopify():
    """Stub every Shopify-boundary call the wizard hits.

    test_connection -> always succeed
    launch_orchestrator.launch_store -> returns happy checklist
    launch_audit.audit_store -> returns ready_to_launch=True
    SyncService.sync_store -> 5 products / 0 orders
    _go_live_check -> ready_to_go_live
    """
    with patch(
        "engines.store_setup.launch_orchestrator.launch_store",
        return_value={
            "ready_to_launch": True,
            "checklist": [
                {"step": "policies", "ok": True, "applied": 5},
                {"step": "pages", "ok": True, "applied": 4},
                {"step": "discount", "ok": True, "applied": 1},
                {"step": "collections", "ok": True, "applied": 4},
            ],
        },
    ) as launch_mock, patch(
        "engines.store_setup.launch_audit.audit_store",
        return_value={
            "ready_to_launch": True,
            "completion_pct": 100,
            "manual_admin_gaps": [],
            "launch_closeable_gaps": [],
            "next_action": "",
            "checks": [],
        },
    ) as audit_mock, patch(
        "data_pipeline.store.sync_service.SyncService",
    ) as sync_cls, patch(
        "engines._go_live_check.run_go_live_check",
        return_value=[],
    ), patch(
        "engines._go_live_check.summarize",
        return_value={
            "verdict": "ready_to_go_live",
            "pass": 9, "warn": 0, "fail": 0, "total": 9,
        },
    ):
        sync_cls.return_value.sync_store.return_value = {
            "products": 5, "orders": 0,
        }
        yield {
            "launch": launch_mock,
            "audit": audit_mock,
            "sync": sync_cls,
        }


class TestE2EFreshStore:
    """Full chain against a fresh store_id with stubbed Shopify."""

    def test_register_writes_row_to_real_db(
        self, real_sm, stubbed_shopify,
    ):
        result = onboard_store(
            store_id="acme",
            shop_url="acme.myshopify.com",
            api_key="shpat_test",
            name="ACME Beauty",
            store_manager=real_sm,
        )
        # Register stage success
        reg = next(
            s for s in result.stages if s.name == "register"
        )
        assert reg.status == "success"
        # Real DB row exists
        row = real_sm.get_store("acme")
        assert row is not None
        assert row["shop_url"] == "acme.myshopify.com"

    def test_full_chain_ready_verdict(
        self, real_sm, stubbed_shopify,
    ):
        # Pass operator-supplied niche so the niche_detect
        # stage skips (otherwise the real detector runs against
        # empty in-memory products + warns no_data).
        with patch.object(
            real_sm, "test_connection",
            return_value={
                "connected": True,
                "shop": "acme.myshopify.com",
                "error": "",
            },
        ):
            result = onboard_store(
                store_id="acme",
                shop_url="acme.myshopify.com",
                api_key="shpat_test",
                niche="beauty",
                store_manager=real_sm,
            )
        assert result.final_verdict == "ready"
        # All 9 stages present
        names = [s.name for s in result.stages]
        assert names == [
            "register", "verify_creds", "sync", "niche_detect",
            "launch", "verify_launch", "relaunch_retry",
            "go_live", "schedule",
        ]
        # Schedule emitted a real template
        sched = next(
            s for s in result.stages if s.name == "schedule"
        )
        assert sched.data["platform"] in ("cron", "windows-task")

    def test_operator_niche_persists_to_db(
        self, real_sm, stubbed_shopify,
    ):
        with patch.object(
            real_sm, "test_connection",
            return_value={"connected": True, "shop": "a", "error": ""},
        ):
            onboard_store(
                store_id="acme",
                shop_url="acme.myshopify.com",
                api_key="shpat_test",
                niche="beauty",
                store_manager=real_sm,
            )
        # Real row carries the niche
        row = real_sm.get_store("acme")
        assert row["niche"] == "beauty"


class TestE2ECredsFailurePropagation:
    """Wave 93: verify_creds failure must propagate through
    the real chain, skipping every network-dependent stage."""

    def test_bad_creds_skip_sync_niche_launch_retry_verify(
        self, real_sm,
    ):
        # test_connection returns connected=False
        with patch.object(
            real_sm, "test_connection",
            return_value={
                "connected": False,
                "error": "401 unauthorized",
            },
        ):
            result = onboard_store(
                store_id="bad_creds",
                shop_url="bad.myshopify.com",
                api_key="not_a_real_token",
                store_manager=real_sm,
            )
        assert result.final_verdict == "failed"
        # Register still succeeded (DB write)
        assert real_sm.get_store("bad_creds") is not None
        # Network-dependent stages all skipped
        for name in (
            "sync", "niche_detect", "launch",
            "verify_launch", "relaunch_retry",
        ):
            stage = next(
                s for s in result.stages if s.name == name
            )
            assert stage.status == "skipped", (
                f"{name} should skip on bad creds"
            )
        # Local-only stages still ran
        for name in ("go_live", "schedule"):
            stage = next(
                s for s in result.stages if s.name == name
            )
            assert stage.status != "skipped"


class TestE2EDuplicateStoreId:
    """Real DB-level concern: re-running onboard with the same
    store_id should not crash the wizard. The register stage's
    outcome depends on StoreManager.add_store's duplicate
    semantics."""

    def test_re_onboard_same_store_id_does_not_crash(
        self, real_sm, stubbed_shopify,
    ):
        # First pass
        with patch.object(
            real_sm, "test_connection",
            return_value={"connected": True, "shop": "x", "error": ""},
        ):
            first = onboard_store(
                store_id="dup",
                shop_url="dup.myshopify.com",
                api_key="t",
                store_manager=real_sm,
            )
            # Second pass with the same store_id
            second = onboard_store(
                store_id="dup",
                shop_url="dup.myshopify.com",
                api_key="t",
                store_manager=real_sm,
            )
        # Wizard runs to completion both times. Register's
        # status may be success or warn depending on the DB's
        # duplicate semantics; what matters is the wizard
        # doesn't crash + the chain finishes.
        assert first.stages[-1].name == "schedule"
        assert second.stages[-1].name == "schedule"


class TestE2ERetryUpgradesVerifyLaunch:
    """Wave 95 invariant: when retry closes ALL gaps, the
    upstream verify_launch stage gets upgraded warn->success.
    Tested with real chaining (no mocks of the wizard itself)."""

    def test_retry_closes_all_gaps_upgrades_verify_launch(
        self, real_sm,
    ):
        # First audit warns; second audit (after retry's
        # re-run of launch_store) is clean.
        audits = iter([
            {
                "ready_to_launch": False,
                "completion_pct": 70,
                "manual_admin_gaps": [],
                "launch_closeable_gaps": ["active_discounts"],
                "next_action": "",
                "checks": [],
            },
            {
                "ready_to_launch": True,
                "completion_pct": 100,
                "manual_admin_gaps": [],
                "launch_closeable_gaps": [],
                "next_action": "",
                "checks": [],
            },
        ])
        with patch.object(
            real_sm, "test_connection",
            return_value={"connected": True, "shop": "r", "error": ""},
        ), patch(
            "engines.store_setup.launch_orchestrator.launch_store",
            return_value={
                "ready_to_launch": True, "checklist": [],
            },
        ), patch(
            "engines.store_setup.launch_audit.audit_store",
            side_effect=lambda **kw: next(audits),
        ), patch(
            "engines._go_live_check.run_go_live_check",
            return_value=[],
        ), patch(
            "engines._go_live_check.summarize",
            return_value={
                "verdict": "ready_to_go_live",
                "pass": 9, "warn": 0, "fail": 0, "total": 9,
            },
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls:
            sync_cls.return_value.sync_store.return_value = {
                "products": 5, "orders": 0,
            }
            result = onboard_store(
                store_id="retry_test",
                shop_url="r.myshopify.com",
                api_key="t",
                niche="beauty",  # bypass niche_detect warn
                store_manager=real_sm,
            )
        # Retry stage closed the gap
        retry = next(
            s for s in result.stages
            if s.name == "relaunch_retry"
        )
        assert retry.status == "success"
        assert retry.data["gaps_closed"] == ["active_discounts"]
        # Upstream verify_launch upgraded
        vl = next(
            s for s in result.stages
            if s.name == "verify_launch"
        )
        assert vl.status == "success"
        assert "after retry" in vl.detail
        # Final verdict is ready (no remaining warnings)
        assert result.final_verdict == "ready"
