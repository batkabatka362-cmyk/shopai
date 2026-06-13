"""W963-124: regression tests for Round 8 adversarial-
review fixes.

Round 8 confirmed 7 bugs in the W963-115..122 per-store
substrate. This file covers the two highest-priority
fixes shipped in W963-124:

  #1: HIGH/money. core/adapters/shopify/_base.py:168.
      Unknown active_store(sid) silently routed
      mutations to env-default store. Now hard-fails.

  #5: MEDIUM/operator-decision. engines/per_store_pnl/
      snapshot.py compute_fleet_snapshot sort tiebreaker.
      Previously surfaced LEAST losing store first.
      Now surfaces BIGGEST loss first.

Each test pins the post-fix behavior so a future
regression breaks loudly.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from core.adapters.errors import AdapterNotConfigured


# ── Round 8 #1: active_store unknown-sid hard-fail ────────


class TestActiveStoreUnknownSidHardFail:
    """When active_store(sid) is set but sid is NOT
    registered in StoreManager, the adapter must raise
    AdapterNotConfigured -- NOT silently route to env
    defaults."""

    def test_unknown_sid_raises_adapter_not_configured(
        self, monkeypatch,
    ):
        from core.adapters.shopify.risk import (
            ShopifyRiskAdapter,
        )
        from core.context import active_store
        from core.adapters.config import reset_config

        # Env defaults present (would silently route here
        # pre-fix)
        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_URL",
            "env_default.myshopify.com",
        )
        monkeypatch.setenv(
            "SHOPAI_SHOPIFY_KEY", "env_default_token",
        )
        reset_config()

        fake_sm = MagicMock()
        fake_sm.has_store.return_value = False
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
            return_value=fake_sm,
        ):
            adapter = ShopifyRiskAdapter()
            with active_store("unknown_sid"):
                with pytest.raises(
                    AdapterNotConfigured,
                ) as exc:
                    adapter._resolve_credentials()
        assert "unknown_sid" in str(exc.value)
        # Error message guides operator to fix
        assert "shopai store add" in str(exc.value)

    def test_known_sid_resolves_per_store_creds(
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

        fake_sm = MagicMock()
        fake_sm.has_store.return_value = True
        fake_sm.get_credentials.return_value = {
            "shop_url": "store_a.myshopify.com",
            "api_key": "store_a_token",
        }
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
            return_value=fake_sm,
        ):
            adapter = ShopifyRiskAdapter()
            with active_store("store_a"):
                shop, tok = adapter._resolve_credentials()
        # Per-store creds resolved (no env leak)
        assert shop == "store_a.myshopify.com"
        assert tok == "store_a_token"

    def test_no_active_store_uses_env_fallback(
        self, monkeypatch,
    ):
        """Without active_store, env fallback is the
        intended path. has_store check should NOT fire."""
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
        shop, tok = adapter._resolve_credentials()
        assert shop == "env.myshopify.com"
        assert tok == "env_token"

    def test_store_manager_db_error_falls_back(
        self, monkeypatch,
    ):
        """Other StoreManager errors (e.g. DB unavail)
        should still fall through to env fallback. Only
        the unknown-sid path is hard-failed."""
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

        # StoreManager() raises on instantiation
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
            side_effect=RuntimeError("test: db down"),
        ):
            adapter = ShopifyRiskAdapter()
            with active_store("store_a"):
                shop, tok = adapter._resolve_credentials()
        # Env fallback used
        assert shop == "env.myshopify.com"
        assert tok == "env_token"


class TestStoreManagerHasStore:
    """W963-124: new StoreManager.has_store(sid) API."""

    def test_returns_false_for_empty(self):
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        sm = StoreManager()
        assert sm.has_store("") is False

    def test_returns_false_for_none(self):
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        sm = StoreManager()
        assert sm.has_store(None) is False

    def test_returns_false_for_unregistered_sid(self):
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        sm = StoreManager()
        assert sm.has_store(
            "definitely_not_a_real_store_id_xyz",
        ) is False


# ── Round 8 #5: LOSING store sort order ───────────────────


class TestBudgetParseSentinel:
    """W963-125 round-8 #3 + #4: budget parse must
    distinguish UNSET (None) from UNLIMITED (0.0)."""

    def test_typo_returns_none_not_zero(self):
        from engines.per_store_quota.budget_config import (
            _parse_amount,
        )
        # Pre-fix returned 0.0 (silently uncapped). Now
        # returns None so resolver falls through.
        assert _parse_amount("garbage") is None
        assert _parse_amount("xyz123") is None

    def test_thousands_separator_now_parses(self):
        from engines.per_store_quota.budget_config import (
            _parse_amount,
        )
        # Pre-fix silently uncapped on '1,000' typo
        assert _parse_amount("1,000") == 1000.0
        assert _parse_amount("$1,000.50") == 1000.50

    def test_explicit_unlimited_returns_zero(self):
        from engines.per_store_quota.budget_config import (
            _parse_amount,
        )
        assert _parse_amount("unlimited") == 0.0
        assert _parse_amount("none") == 0.0

    def test_explicit_unset_returns_none(self):
        from engines.per_store_quota.budget_config import (
            _parse_amount,
        )
        assert _parse_amount("unset") is None
        assert _parse_amount("") is None
        assert _parse_amount(None) is None

    def test_per_store_unlimited_short_circuits(
        self, monkeypatch,
    ):
        """W963-125 round-8 #3: level 1 ('unlimited' at
        per-store-per-adapter) must short-circuit the
        chain so fleet caps do NOT apply to that store
        + adapter."""
        from engines.per_store_quota import resolve_cap

        monkeypatch.setenv(
            "SHOPAI_DAILY_BUDGET_USD", "100",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "unlimited",
        )
        # Level 1 says unlimited -> 0.0 returned
        assert resolve_cap(
            store_id="store_a", adapter="openai",
        ) == 0.0
        # Other adapter for same store still hits fleet
        assert resolve_cap(
            store_id="store_a", adapter="anthropic",
        ) == 100.0


class TestSidCollisionGuard:
    """W963-125 round-8 #2: add_store refuses sids that
    normalise to a key already registered."""

    def test_sid_normalises_to_same_env_detects(self):
        from core.adapters._per_store_credentials import (
            sid_normalises_to_same_env,
        )
        # Different sids that normalise the same
        assert sid_normalises_to_same_env(
            "store-a", "store_a",
        ) is True
        # Same sid -> no collision
        assert sid_normalises_to_same_env(
            "store_a", "store_a",
        ) is False
        # Distinct sids
        assert sid_normalises_to_same_env(
            "store_a", "store_b",
        ) is False

    def test_sid_normalises_empty_returns_false(self):
        from core.adapters._per_store_credentials import (
            sid_normalises_to_same_env,
        )
        assert sid_normalises_to_same_env(
            "", "store_a",
        ) is False
        assert sid_normalises_to_same_env(
            "store_a", "",
        ) is False


class TestCostFilterFleetAlias:
    """W963-125 round-8 #7: costs_total / costs_by_adapter
    accept '(fleet)' as an alias for empty store_id (the
    display key costs_by_store uses for empty-sid
    events)."""

    def test_costs_total_accepts_fleet_label(
        self, tmp_path, monkeypatch,
    ):
        import json, time
        from engines.per_store_costs import recorder as cr
        from engines.per_store_costs.query import (
            costs_total,
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

        live.parent.mkdir(parents=True, exist_ok=True)
        with open(live, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.time(),
                "store_id": "",  # fleet
                "adapter": "openai",
                "capability": "chat",
                "cost_usd": 5.0,
                "ok": True,
            }) + "\n")

        # Filter with '(fleet)' should join on the
        # empty-store events
        out = costs_total(store_id="(fleet)")
        assert out["total_calls"] == 1
        assert out["total_cost_usd"] == 5.0


class TestAutopauseFleetArmCollision:
    """W963-126 round-8 #6: when a domain is armed
    fleet-wide, the per-store disarm is a no-op. The
    bridge must surface that honestly rather than
    silently fail."""

    def test_fleet_armed_surfaces_clear_error(
        self, tmp_path, monkeypatch,
    ):
        import json, time
        from engines.per_store_costs import recorder as cr
        from engines.per_store_quota import maybe_autopause

        live = tmp_path / "per_store_costs.jsonl"
        archive = tmp_path / "per_store_costs.archive.jsonl"
        monkeypatch.setattr(cr, "DATA_PATH", live)
        monkeypatch.setattr(cr, "ARCHIVE_PATH", archive)
        from engines.per_store_costs import query as qmod
        monkeypatch.setattr(qmod, "DATA_PATH", live)
        monkeypatch.setattr(qmod, "ARCHIVE_PATH", archive)

        # Seed: store_a over cap
        monkeypatch.setenv(
            "SHOPAI_QUOTA_AUTOPAUSE", "1",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "5",
        )
        live.parent.mkdir(parents=True, exist_ok=True)
        with open(live, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.time(),
                "store_id": "store_a",
                "adapter": "openai",
                "capability": "chat",
                "cost_usd": 50.0,
                "ok": True,
            }) + "\n")

        # Mock: is_armed returns True for fleet entries
        # (store_id="") for the spend domains
        from unittest.mock import patch
        with patch(
            "core.automation.autonomy_armed.is_armed",
            side_effect=lambda d, store_id="":
                store_id == "",
        ), patch(
            "core.automation.autonomy_armed.disarm",
        ) as mock_disarm:
            report = maybe_autopause()

        # disarm was NOT called for fleet-armed domains
        assert mock_disarm.call_count == 0
        # Every action carries the clear error
        for action in report.actions:
            assert "fleet-wide arm" in action.error
            assert "shopai autonomy-disarm" in action.error
            assert action.applied is False

    def test_per_store_armed_disarms_normally(
        self, tmp_path, monkeypatch,
    ):
        """When the domain is armed PER-STORE (not
        fleet-wide), the bridge disarms normally without
        the fleet-collision warning."""
        import json, time
        from engines.per_store_costs import recorder as cr
        from engines.per_store_quota import maybe_autopause

        live = tmp_path / "per_store_costs.jsonl"
        archive = tmp_path / "per_store_costs.archive.jsonl"
        monkeypatch.setattr(cr, "DATA_PATH", live)
        monkeypatch.setattr(cr, "ARCHIVE_PATH", archive)
        from engines.per_store_costs import query as qmod
        monkeypatch.setattr(qmod, "DATA_PATH", live)
        monkeypatch.setattr(qmod, "ARCHIVE_PATH", archive)

        monkeypatch.setenv(
            "SHOPAI_QUOTA_AUTOPAUSE", "1",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_DAILY_BUDGET_USD",
            "5",
        )
        live.parent.mkdir(parents=True, exist_ok=True)
        with open(live, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.time(),
                "store_id": "store_a",
                "adapter": "openai",
                "capability": "chat",
                "cost_usd": 50.0,
                "ok": True,
            }) + "\n")

        # Mock: is_armed returns False for fleet entries
        # (per-store-only arms)
        from unittest.mock import patch
        with patch(
            "core.automation.autonomy_armed.is_armed",
            return_value=False,
        ), patch(
            "core.automation.autonomy_armed.disarm",
            return_value=True,
        ) as mock_disarm:
            report = maybe_autopause()

        # disarm called per-store as expected
        assert mock_disarm.call_count > 0
        for call in mock_disarm.call_args_list:
            assert call.kwargs.get(
                "store_id",
            ) == "store_a"
        # No fleet-collision errors
        for action in report.actions:
            assert "fleet-wide arm" not in action.error
            assert action.applied is True


class TestLosingSortOrder:
    """compute_fleet_snapshot must surface the BIGGEST
    losing store first, not the smallest. The empire +
    daily-brief top_losers slice depends on this order
    for operator attention."""

    def test_biggest_loss_sorts_first(self, tmp_path, monkeypatch):
        """Two LOSING stores: -$5 and -$5000. The
        snapshot order must show -$5000 first so the
        operator sees the biggest bleeder."""
        import json, time
        from engines.per_store_costs import recorder as cr
        from engines.per_store_pnl import (
            compute_fleet_snapshot,
        )

        # Isolated cost log
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

        # Seed: store_big spent $5005, store_tiny $10
        live.parent.mkdir(parents=True, exist_ok=True)
        with open(live, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.time(),
                "store_id": "store_big",
                "adapter": "openai",
                "capability": "chat",
                "cost_usd": 5005.0,
                "ok": True,
            }) + "\n")
            f.write(json.dumps({
                "ts": time.time(),
                "store_id": "store_tiny",
                "adapter": "openai",
                "capability": "chat",
                "cost_usd": 10.0,
                "ok": True,
            }) + "\n")

        # Both have $5 revenue -> both LOSING.
        # store_big: profit = -5000
        # store_tiny: profit = -5
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
                {"store_id": "store_tiny"},
                {"store_id": "store_big"},
            ]
            with patch(
                "engines._revenue_attribution."
                "attribute_revenue",
                side_effect=fake_attr,
            ):
                snaps = compute_fleet_snapshot()

        # StorePnLSnapshot is per-store (no adapter slot)
        assert len(snaps) == 2
        # BIGGEST loser (store_big with -$5000) MUST be
        # first
        assert snaps[0].store_id == "store_big"
        assert snaps[0].profit_usd == -5000.0
        # Smaller loser comes after
        assert snaps[1].store_id == "store_tiny"
        assert snaps[1].profit_usd == -5.0

    def test_empire_top_losers_is_biggest_first(
        self, tmp_path, monkeypatch,
    ):
        """End-to-end: empire dashboard's top_losers
        block should list the worst stores first."""
        import json, time
        from engines.per_store_costs import recorder as cr
        from engines.per_store_pnl import (
            compute_fleet_snapshot,
        )

        live = tmp_path / "per_store_costs.jsonl"
        archive = tmp_path / "per_store_costs.archive.jsonl"
        monkeypatch.setattr(cr, "DATA_PATH", live)
        monkeypatch.setattr(cr, "ARCHIVE_PATH", archive)
        from engines.per_store_costs import query as qmod
        monkeypatch.setattr(qmod, "DATA_PATH", live)
        monkeypatch.setattr(
            qmod, "ARCHIVE_PATH", archive,
        )

        live.parent.mkdir(parents=True, exist_ok=True)
        with open(live, "w", encoding="utf-8") as f:
            for sid, cost in (
                ("store_a", 10.0),    # -5
                ("store_b", 5000.0),  # -4995 (worst)
                ("store_c", 100.0),   # -95
            ):
                f.write(json.dumps({
                    "ts": time.time(),
                    "store_id": sid,
                    "adapter": "openai",
                    "capability": "chat",
                    "cost_usd": cost,
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
                {"store_id": "store_a"},
                {"store_id": "store_b"},
                {"store_id": "store_c"},
            ]
            with patch(
                "engines._revenue_attribution."
                "attribute_revenue",
                side_effect=fake_attr,
            ):
                snaps = compute_fleet_snapshot()

        # The top_losers slice the dashboard takes is
        # losing[:3] from the sorted snapshots.
        losing_totals = [
            s for s in snaps
            if s.state.value == "losing"
        ]
        top_3 = losing_totals[:3]
        store_ids_order = [s.store_id for s in top_3]
        # Worst first: store_b (-$4995), then store_c
        # (-$95), then store_a (-$5)
        assert store_ids_order == [
            "store_b", "store_c", "store_a",
        ]
