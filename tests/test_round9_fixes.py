"""W963-129: regression tests for Round 9 adversarial
review fixes.

Round 9 confirmed 12 bugs across W963-123..128. This
file covers the 5 highest-priority ones shipped in
W963-129:

  #4/#11/#12: HIGH/money. StoreManager.find_by_shop_url
              + has_store + add_store collision check
              only scanned in-memory _store_credentials,
              never hydrated from DB. Fresh process
              (webhook handler, CLI subcommand) had
              empty cache + all per-store routing
              silently fell through to env-default
              credentials.

  #7:         HIGH. is_configured() called
              _resolve_credentials() with no try/except;
              W963-124's raise-on-unknown-sid propagated
              out of router list-comprehensions, crashing
              routing for EVERY adapter not just the
              targeted one.

  Each test pins the post-fix behaviour so a future
  regression breaks loudly.
"""
from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest


# ── DB-backed find_by_shop_url ────────────────────────────


class TestFindByShopUrlDBFallback:
    """Round-9 #4/#11/#12: find_by_shop_url must fall
    back to DB when in-memory cache is empty."""

    def test_finds_db_store_when_cache_empty(self):
        from data_pipeline.store.store_manager import (
            StoreManager,
        )

        # Mock DB returning a persisted store_a
        mock_db = MagicMock()
        mock_db.list_stores.return_value = [{
            "store_id": "store_a",
            "shop_url": "store-a.myshopify.com",
        }]
        sm = StoreManager(db=mock_db)
        # In-memory cache is empty (fresh process)
        assert sm._store_credentials == {}
        # But find_by_shop_url consults DB + finds it
        assert sm.find_by_shop_url(
            "store-a.myshopify.com",
        ) == "store_a"

    def test_cache_hit_skips_db_call(self):
        """When in-memory cache hits, DB is NOT
        consulted (fast path)."""
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        mock_db = MagicMock()
        sm = StoreManager(db=mock_db)
        with sm._lock:
            sm._store_credentials["store_x"] = {
                "shop_url": "x.myshopify.com",
                "api_key": "k",
                "client_id": "",
                "client_secret": "",
            }
        result = sm.find_by_shop_url("x.myshopify.com")
        assert result == "store_x"
        # DB never consulted -- cache hit short-circuits
        mock_db.list_stores.assert_not_called()

    def test_db_failure_returns_empty(self):
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        mock_db = MagicMock()
        mock_db.list_stores.side_effect = RuntimeError(
            "test: db down",
        )
        sm = StoreManager(db=mock_db)
        # No crash; just no match
        assert sm.find_by_shop_url(
            "anything.myshopify.com",
        ) == ""


class TestHasStoreDBFallback:
    """Round-9: has_store also needs DB fallback so the
    W963-124 hard-fail doesn't fire for stores that exist
    in the DB but aren't in the per-process cache."""

    def test_db_store_returns_true(self):
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        mock_db = MagicMock()
        mock_db.list_stores.return_value = [
            {"store_id": "store_a"},
        ]
        sm = StoreManager(db=mock_db)
        # Cache empty but DB has store_a -> True
        assert sm.has_store("store_a") is True

    def test_unknown_returns_false(self):
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        mock_db = MagicMock()
        mock_db.list_stores.return_value = []
        sm = StoreManager(db=mock_db)
        assert sm.has_store("never_added") is False

    def test_empty_returns_false(self):
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        sm = StoreManager()
        assert sm.has_store("") is False
        assert sm.has_store(None) is False


class TestAddStoreCollisionDBAware:
    """Round-9 #5: add_store collision check must use DB,
    not in-memory cache. A fresh process inviting a
    colliding store_id must be REFUSED at the registration
    point, not silently allowed through to bite later."""

    def test_collision_detected_via_db(self):
        from data_pipeline.store.store_manager import (
            StoreManager,
        )

        # DB already contains store_a from a prior CLI
        # session
        mock_db = MagicMock()
        mock_db.list_stores.return_value = [
            {"store_id": "store_a"},
        ]
        mock_db.add_store.return_value = {"ok": True}

        sm = StoreManager(db=mock_db)
        # Cache is empty -- but the guard now consults DB
        result = sm.add_store(
            "store-a", "x.myshopify.com", api_key="key",
        )
        assert "error" in result
        # The error explains the collision
        assert "collides with existing" in result["error"]
        # add_store on the DB should NOT have been called
        mock_db.add_store.assert_not_called()


# ── is_configured swallow ─────────────────────────────────


class TestIsConfiguredSwallowNotConfigured:
    """Round-9 #7: is_configured() must catch
    AdapterNotConfigured and return False instead of
    propagating. Registry calls is_configured in list
    comprehensions + sort-key lambdas where an exception
    crashes routing for every adapter, not just the
    targeted one."""

    def test_unknown_sid_returns_false_not_raises(
        self, monkeypatch,
    ):
        from core.adapters.shopify.risk import (
            ShopifyRiskAdapter,
        )
        from core.context import active_store
        from core.adapters.config import reset_config

        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_URL", "env.myshopify.com",
        )
        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_KEY", "env_token",
        )
        reset_config()

        # StoreManager has NO record of unknown_sid
        mock_sm = MagicMock()
        mock_sm.has_store.return_value = False
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
            return_value=mock_sm,
        ):
            adapter = ShopifyRiskAdapter()
            # is_configured under active_store(unknown_sid)
            # must NOT propagate the AdapterNotConfigured
            # from _resolve_credentials.
            with active_store("definitely_unknown_sid"):
                result = adapter.is_configured()
        assert result is False

    def test_known_sid_returns_true(self, monkeypatch):
        from core.adapters.shopify.risk import (
            ShopifyRiskAdapter,
        )
        from core.context import active_store
        from core.adapters.config import reset_config

        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_URL", "env.myshopify.com",
        )
        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_KEY", "env_token",
        )
        reset_config()

        mock_sm = MagicMock()
        mock_sm.has_store.return_value = True
        mock_sm.get_credentials.return_value = {
            "shop_url": "store_a.myshopify.com",
            "api_key": "store_a_token",
        }
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
            return_value=mock_sm,
        ):
            adapter = ShopifyRiskAdapter()
            with active_store("store_a"):
                assert adapter.is_configured() is True

    def test_no_active_store_returns_true(
        self, monkeypatch,
    ):
        """Single-store empire (no active_store) keeps
        working as before."""
        from core.adapters.shopify.risk import (
            ShopifyRiskAdapter,
        )
        from core.adapters.config import reset_config

        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_URL", "env.myshopify.com",
        )
        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_KEY", "env_token",
        )
        reset_config()
        adapter = ShopifyRiskAdapter()
        assert adapter.is_configured() is True


class TestPnLSortPositiveBandFix:
    """Round-9 #8: compute_fleet_snapshot tiebreaker must
    surface HIGHEST-margin store first within positive-
    profit bands (THRIVING/HEALTHY/BREAKEVEN). Pre-fix
    used s.profit_usd ascending which inverted it for
    positive-profit -- a $100 store sorted before a
    $10000 store within the THRIVING band."""

    def test_thriving_highest_profit_first(
        self, tmp_path, monkeypatch,
    ):
        import json, time
        from unittest.mock import MagicMock, patch
        from engines.per_store_costs import recorder as cr
        from engines.per_store_pnl import (
            PnLState, compute_fleet_snapshot,
        )

        live = tmp_path / "per_store_costs.jsonl"
        archive = (
            tmp_path / "per_store_costs.archive.jsonl"
        )
        monkeypatch.setattr(cr, "DATA_PATH", live)
        monkeypatch.setattr(cr, "ARCHIVE_PATH", archive)
        from engines.per_store_costs import query as qmod
        monkeypatch.setattr(qmod, "DATA_PATH", live)
        monkeypatch.setattr(
            qmod, "ARCHIVE_PATH", archive,
        )

        # Two stores, both spending $1, both highly
        # profitable. store_big earns $10000, store_small
        # earns $100. Both -> THRIVING (margin >> 66%).
        now = time.time()
        live.parent.mkdir(parents=True, exist_ok=True)
        with open(live, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": now,
                "store_id": "store_small",
                "adapter": "openai",
                "capability": "chat",
                "cost_usd": 1.0,
                "ok": True,
            }) + "\n")
            f.write(json.dumps({
                "ts": now,
                "store_id": "store_big",
                "adapter": "openai",
                "capability": "chat",
                "cost_usd": 1.0,
                "ok": True,
            }) + "\n")

        def fake_attr(
            *args, window_hours=168.0, store_id=None,
            **kwargs,
        ):
            fake = MagicMock()
            if store_id == "store_big":
                fake.total_revenue_in_window = 10000.0
                fake.attributed_revenue = 8000.0
            elif store_id == "store_small":
                fake.total_revenue_in_window = 100.0
                fake.attributed_revenue = 80.0
            else:
                fake.total_revenue_in_window = 0.0
                fake.attributed_revenue = 0.0
            return fake

        with patch(
            "data_pipeline.store.store_manager.StoreManager",
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = [
                {"store_id": "store_small"},
                {"store_id": "store_big"},
            ]
            with patch(
                "engines._revenue_attribution."
                "attribute_revenue",
                side_effect=fake_attr,
            ):
                snaps = compute_fleet_snapshot()

        thriving = [
            s for s in snaps
            if s.state == PnLState.THRIVING
        ]
        assert len(thriving) == 2
        # HIGHEST profit surfaces first (post-fix)
        assert thriving[0].store_id == "store_big"
        assert thriving[0].profit_usd > thriving[1].profit_usd
        assert thriving[1].store_id == "store_small"

    def test_losing_still_biggest_loss_first(
        self, tmp_path, monkeypatch,
    ):
        """Round-9 #8 fix must NOT regress the W963-124
        LOSING-first behaviour. Verify biggest LOSS still
        surfaces first."""
        import json, time
        from unittest.mock import MagicMock, patch
        from engines.per_store_costs import recorder as cr
        from engines.per_store_pnl import (
            PnLState, compute_fleet_snapshot,
        )

        live = tmp_path / "per_store_costs.jsonl"
        archive = (
            tmp_path / "per_store_costs.archive.jsonl"
        )
        monkeypatch.setattr(cr, "DATA_PATH", live)
        monkeypatch.setattr(cr, "ARCHIVE_PATH", archive)
        from engines.per_store_costs import query as qmod
        monkeypatch.setattr(qmod, "DATA_PATH", live)
        monkeypatch.setattr(
            qmod, "ARCHIVE_PATH", archive,
        )

        # store_big spends $5005, store_tiny $10. Both
        # have $5 revenue -> both LOSING.
        now = time.time()
        live.parent.mkdir(parents=True, exist_ok=True)
        with open(live, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": now,
                "store_id": "store_big",
                "adapter": "openai",
                "capability": "chat",
                "cost_usd": 5005.0,
                "ok": True,
            }) + "\n")
            f.write(json.dumps({
                "ts": now,
                "store_id": "store_tiny",
                "adapter": "openai",
                "capability": "chat",
                "cost_usd": 10.0,
                "ok": True,
            }) + "\n")

        def fake_attr(
            *args, window_hours=168.0, store_id=None,
            **kwargs,
        ):
            fake = MagicMock()
            fake.total_revenue_in_window = 5.0
            fake.attributed_revenue = 5.0
            return fake

        with patch(
            "data_pipeline.store.store_manager.StoreManager",
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = [
                {"store_id": "store_big"},
                {"store_id": "store_tiny"},
            ]
            with patch(
                "engines._revenue_attribution."
                "attribute_revenue",
                side_effect=fake_attr,
            ):
                snaps = compute_fleet_snapshot()

        # Biggest loser (-$5000) still surfaces first
        assert snaps[0].store_id == "store_big"
        assert snaps[0].profit_usd == -5000.0


class TestForecasterColdStart:
    """Round-9 #1: cold-start rate divisor must use the
    actual data span, not the nominal sample window. A
    store burning $5 in 1h against $10 cap should be
    flagged CRITICAL, not IMMINENT."""

    def test_cold_start_critical_not_imminent(
        self, tmp_path, monkeypatch,
    ):
        import json, time
        from engines.per_store_costs import recorder as cr
        from engines.per_store_quota.forecast import (
            ForecastVerdict, forecast_to_cap,
        )

        live = tmp_path / "per_store_costs.jsonl"
        archive = (
            tmp_path / "per_store_costs.archive.jsonl"
        )
        monkeypatch.setattr(cr, "DATA_PATH", live)
        monkeypatch.setattr(cr, "ARCHIVE_PATH", archive)
        from engines.per_store_costs import query as qmod
        monkeypatch.setattr(qmod, "DATA_PATH", live)
        monkeypatch.setattr(
            qmod, "ARCHIVE_PATH", archive,
        )

        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        # Cold-start: $5 burned 30 minutes ago (single
        # spike) against $10 cap. Actual span = 30 min;
        # nominal sample = 6h. Real rate is $10/h not
        # $5/6h.
        now = time.time()
        live.parent.mkdir(parents=True, exist_ok=True)
        with open(live, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": now - 1800,
                "store_id": "store_a",
                "adapter": "openai",
                "capability": "chat",
                "cost_usd": 5.0,
                "ok": True,
            }) + "\n")
        snap = forecast_to_cap(
            "store_a", adapter="openai",
            sample_hours=6.0,
        )
        # 5/0.5h = $10/h, headroom $5 -> h_to_cap=0.5
        # which is <=4h -> CRITICAL (not IMMINENT)
        assert snap.verdict == ForecastVerdict.CRITICAL
        assert snap.hours_to_cap < 4.0


class TestForecasterArchive:
    """Round-9 #3: forecast must consult archive log so
    post-rotation reads don't return false NO_RATE."""

    def test_archive_events_counted(
        self, tmp_path, monkeypatch,
    ):
        import json, time
        from engines.per_store_costs import recorder as cr
        from engines.per_store_quota.forecast import (
            ForecastVerdict, forecast_to_cap,
        )

        live = tmp_path / "per_store_costs.jsonl"
        archive = (
            tmp_path / "per_store_costs.archive.jsonl"
        )
        monkeypatch.setattr(cr, "DATA_PATH", live)
        monkeypatch.setattr(cr, "ARCHIVE_PATH", archive)
        from engines.per_store_costs import query as qmod
        monkeypatch.setattr(qmod, "DATA_PATH", live)
        monkeypatch.setattr(
            qmod, "ARCHIVE_PATH", archive,
        )

        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "10",
        )
        # Simulate post-rotation: live empty, archive
        # has $8 spent in last 24h
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text("", encoding="utf-8")
        with open(archive, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.time() - 3600,
                "store_id": "store_a",
                "adapter": "openai",
                "capability": "chat",
                "cost_usd": 8.0,
                "ok": True,
            }) + "\n")
        snap = forecast_to_cap(
            "store_a", adapter="openai",
            sample_hours=6.0,
        )
        # Spend should be picked up from archive
        assert snap.spend_so_far_usd == 8.0
        # 80% used -> CRITICAL via near-exhaustion guard
        assert snap.verdict == ForecastVerdict.CRITICAL


class TestRouterRobustToUnknownSid:
    """Round-9 #7 blast radius: even when ONE adapter
    raises during _resolve_credentials, the router's
    list comprehensions over is_configured must not
    crash. We probe this by calling is_configured on
    multiple Shopify adapter classes in sequence under
    an unknown active_store -- all must return False
    not raise."""

    def test_multiple_adapters_no_raise(
        self, monkeypatch,
    ):
        from core.adapters.shopify.risk import (
            ShopifyRiskAdapter,
        )
        from core.adapters.shopify.inventory import (
            ShopifyInventoryAdapter,
        )
        from core.adapters.shopify.fulfillment import (
            ShopifyFulfillmentAdapter,
        )
        from core.context import active_store
        from core.adapters.config import reset_config

        monkeypatch.delenv(
            "SHOPAI_SHOPIFY_URL", raising=False,
        )
        monkeypatch.delenv(
            "SHOPAI_SHOPIFY_KEY", raising=False,
        )
        reset_config()

        mock_sm = MagicMock()
        mock_sm.has_store.return_value = False
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
            return_value=mock_sm,
        ):
            # Simulate router-style list comprehension
            with active_store("unknown_sid"):
                results = [
                    cls().is_configured()
                    for cls in (
                        ShopifyRiskAdapter,
                        ShopifyInventoryAdapter,
                        ShopifyFulfillmentAdapter,
                    )
                ]
        # Every adapter returns False, no exception
        assert all(r is False for r in results)
