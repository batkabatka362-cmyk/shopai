"""Regression tests for the 10 stub/fake-data cleanups.

Each test pins the new HONEST behaviour of code that previously
returned hardcoded mock data, fake hash-derived stock numbers,
or "would_execute"-style success envelopes that hid real failures.
The intent of every test is to fail loudly if the fake data ever
sneaks back in via a refactor, merge accident, or "convenience"
revert.

Cleanups covered:

  1. ``execution/fulfillment/auto_fulfill.py``       — hardcoded shipping ETA table
  2. ``engines/order_management/inventory_checker.py`` — MD5(sku) → stock-level fake
  3. ``platforms/amazon.py``                          — SP-API stub returning ``"would_update"``
  4. ``core/bridge/shopify_bridge.py``                — silent ``_mock_*`` data fallback
  5. ``data_pipeline/store/data_provider.py``         — silent ``_mock_*`` data fallback
  6. ``core/intelligence/chat_ai.py``                 — regex-based fake "AI" replies
  7. ``engines/auto_research/search_executor.py``     — hardcoded simulated search corpus
  8. ``engines/social_media/hashtag_generator.py``    — hand-picked fake volume scores
  9. ``engines/autonomous_execution/action_dispatcher.py`` — fake ``"dispatched"`` envelope
 10. ``execution/smart_executor.py``                  — dry-run that always returned ``success=True``
"""
from __future__ import annotations

import tempfile

import pytest


# ─────────────────────────────────────────────────────────────
# 1. fulfillment — shipping ETA must come from an adapter, not
#    a hardcoded country → days table
# ─────────────────────────────────────────────────────────────

class TestFulfillmentNoHardcodedETA:
    def test_no_shipping_days_field(self):
        from execution.fulfillment.auto_fulfill import FulfillmentAutomation
        ff = FulfillmentAutomation()
        result = ff.process_orders(
            [{
                "id": "o1",
                "total_price": 50,
                "financial_status": "paid",
                "line_items": [],
                "shipping_address": {"country_code": "US"},
            }],
            [],
        )
        first = result["results"][0]
        # Pre-cleanup: ``shipping_days = 3`` for US/CA, 7 for EU,
        # 10 otherwise. Field is gone now.
        assert "shipping_days" not in first

    def test_shipping_rate_source_adapter_required(self):
        from execution.fulfillment.auto_fulfill import FulfillmentAutomation
        ff = FulfillmentAutomation()
        result = ff.process_orders(
            [{
                "id": "o1",
                "total_price": 50,
                "financial_status": "paid",
                "line_items": [],
                "shipping_address": {"country_code": "DE"},
            }],
            [],
        )
        first = result["results"][0]
        assert first["shipping_rate_source"] == "adapter_required"
        assert first["shipping_country"] == "DE"

    def test_no_country_table_lookup(self):
        """No matter what country comes in, no ETA is returned —
        the table is gone."""
        from execution.fulfillment.auto_fulfill import FulfillmentAutomation
        ff = FulfillmentAutomation()
        for cc in ("US", "CA", "GB", "AU", "DE", "FR", "JP", "ZZ", ""):
            result = ff.process_orders(
                [{
                    "id": "o1",
                    "total_price": 50,
                    "financial_status": "paid",
                    "line_items": [],
                    "shipping_address": {"country_code": cc},
                }],
                [],
            )
            assert "shipping_days" not in result["results"][0]


# ─────────────────────────────────────────────────────────────
# 2. inventory checker — no MD5(sku)-derived stock fakes
# ─────────────────────────────────────────────────────────────

class TestInventoryCheckerNoFakeStock:
    def test_unknown_when_no_stock_levels(self):
        from engines.order_management.inventory_checker import check_inventory
        result = check_inventory([{"sku": "ANY-SKU", "quantity": 5}])
        # Pre-cleanup: returned ``reserved=True`` with a fake
        # quantity 5..500 derived from md5(sku). Now: unknown.
        assert result["status"] == "success"
        assert result["all_in_stock"] is False
        assert len(result["unknown"]) == 1
        assert result["unknown"][0]["sku"] == "ANY-SKU"
        assert result["unknown"][0]["reason"] == "stock_not_supplied"
        assert result["reservations"][0]["reserved"] is False

    def test_uses_supplied_stock_levels(self):
        from engines.order_management.inventory_checker import check_inventory
        result = check_inventory(
            [{"sku": "A", "quantity": 3}, {"sku": "B", "quantity": 100}],
            stock_levels={"A": 5, "B": 50},
        )
        assert result["all_in_stock"] is False
        a = next(r for r in result["reservations"] if r["sku"] == "A")
        b = next(r for r in result["reservations"] if r["sku"] == "B")
        assert a["reserved"] is True
        assert b["reserved"] is False
        assert any(s["sku"] == "B" for s in result["shortages"])

    def test_no_md5_simulator_in_module(self):
        """Pin: the simulator helper is gone."""
        import engines.order_management.inventory_checker as ic
        assert not hasattr(ic, "_simulate_stock_level")

    def test_deterministic_unknowns_dont_collapse_into_in_stock(self):
        """Two SKUs with different hashes used to produce
        different fake stock numbers. Now both must be unknown."""
        from engines.order_management.inventory_checker import check_inventory
        result = check_inventory(
            [{"sku": "alpha", "quantity": 1}, {"sku": "beta", "quantity": 1}],
        )
        assert len(result["unknown"]) == 2


# ─────────────────────────────────────────────────────────────
# 3. Amazon SP-API — every operation must raise, not silently
#    return "would_update"
# ─────────────────────────────────────────────────────────────

class TestAmazonAdapterStub:
    def test_get_listings_raises(self):
        from platforms.amazon import AmazonAdapter, AmazonNotImplementedError
        a = AmazonAdapter()
        a.configure("rt", "cid", "cs")
        with pytest.raises(AmazonNotImplementedError) as exc:
            a.get_listings()
        assert exc.value.status == "adapter_required"
        assert exc.value.operation == "get_listings"

    def test_get_orders_raises(self):
        from platforms.amazon import AmazonAdapter, AmazonNotImplementedError
        a = AmazonAdapter()
        a.configure("rt", "cid", "cs")
        with pytest.raises(AmazonNotImplementedError):
            a.get_orders()

    def test_update_price_raises_not_would_update(self):
        from platforms.amazon import AmazonAdapter, AmazonNotImplementedError
        a = AmazonAdapter()
        a.configure("rt", "cid", "cs")
        with pytest.raises(AmazonNotImplementedError):
            a.update_price("B0XYZ", 19.99)

    def test_update_inventory_raises_not_would_update(self):
        from platforms.amazon import AmazonAdapter, AmazonNotImplementedError
        a = AmazonAdapter()
        a.configure("rt", "cid", "cs")
        with pytest.raises(AmazonNotImplementedError):
            a.update_inventory("SKU-1", 10)

    def test_amazon_not_implemented_is_subclass(self):
        from platforms.amazon import AmazonNotImplementedError
        assert issubclass(AmazonNotImplementedError, NotImplementedError)


# ─────────────────────────────────────────────────────────────
# 4. ShopifyBridge — no silent mock dataset
# ─────────────────────────────────────────────────────────────

class TestShopifyBridgeNoMockFallback:
    def test_fetch_products_raises_when_unavailable(self):
        from core.bridge.shopify_bridge import (
            ShopifyBridge, ShopifyBridgeUnavailable,
        )
        sb = ShopifyBridge()
        with pytest.raises(ShopifyBridgeUnavailable) as exc:
            sb.fetch_products()
        assert exc.value.resource == "products"

    def test_fetch_orders_raises_when_unavailable(self):
        from core.bridge.shopify_bridge import (
            ShopifyBridge, ShopifyBridgeUnavailable,
        )
        sb = ShopifyBridge()
        with pytest.raises(ShopifyBridgeUnavailable):
            sb.fetch_orders()

    def test_fetch_customers_raises_when_unavailable(self):
        from core.bridge.shopify_bridge import (
            ShopifyBridge, ShopifyBridgeUnavailable,
        )
        sb = ShopifyBridge()
        with pytest.raises(ShopifyBridgeUnavailable):
            sb.fetch_customers()

    def test_no_mock_helpers_remain(self):
        """Pin: ``_mock_products / orders / customers`` are gone."""
        from core.bridge.shopify_bridge import ShopifyBridge
        for name in ("_mock_products", "_mock_orders", "_mock_customers"):
            assert not hasattr(ShopifyBridge, name), (
                f"ShopifyBridge.{name} should have been deleted"
            )


# ─────────────────────────────────────────────────────────────
# 5. DataProvider — no silent mock dataset
# ─────────────────────────────────────────────────────────────

class TestDataProviderNoMockFallback:
    def _make_provider(self):
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        from data_pipeline.store.data_provider import DataProvider
        db = ShopAIDatabase(tempfile.mktemp(suffix=".db"))
        sm = StoreManager(db)
        return DataProvider(sm)

    def test_get_data_for_engine_returns_empty_source(self):
        dp = self._make_provider()
        data = dp.get_data_for_engine("pricing")
        # Pre-cleanup: source="mock" with 5 fake products.
        assert data["source"] == "empty"
        assert data["products"] == []
        assert data["order_data"] == []
        assert data["customer_data"] == []

    def test_get_products_returns_empty_list(self):
        dp = self._make_provider()
        # Pre-cleanup: ``[] -> _mock_products()`` swap.
        assert dp.get_products() == []

    def test_get_orders_returns_empty_list(self):
        dp = self._make_provider()
        assert dp.get_orders() == []

    def test_get_customers_returns_empty_list(self):
        dp = self._make_provider()
        assert dp.get_customers() == []

    def test_no_mock_helpers_remain(self):
        from data_pipeline.store.data_provider import DataProvider
        for name in ("_mock_products", "_mock_orders", "_mock_customers"):
            assert not hasattr(DataProvider, name), (
                f"DataProvider.{name} should have been deleted"
            )

    def test_no_alice_kim_leak(self):
        """The mock dataset shipped a ``"Alice Kim"`` customer.
        Make sure it can't sneak back via any code path."""
        dp = self._make_provider()
        for getter_name in ("get_customers",):
            customers = getattr(dp, getter_name)()
            assert not any(
                isinstance(c, dict) and "Alice Kim" in str(c.get("name", ""))
                for c in customers
            )


# ─────────────────────────────────────────────────────────────
# 6. ChatAI — no regex intent rules, no canned replies
# ─────────────────────────────────────────────────────────────

class TestChatAIPlaceholderOnly:
    def test_returns_adapter_required(self):
        from core.intelligence.chat_ai import ChatAI
        out = ChatAI().respond("where is my order?")
        assert out["status"] == "adapter_required"
        assert out["adapter"] == "chat_ai"
        # Pre-cleanup this returned a canned shipping/order template
        # — must be empty now so the adapter layer owns the reply.
        assert out["response"] == ""
        assert out["intent"] == "unknown"

    def test_no_regex_intent_handlers(self):
        """Each old handler returned a hardcoded template — none of
        them should be addressable as ChatAI methods anymore."""
        from core.intelligence.chat_ai import ChatAI
        for name in (
            "_handle_order_status", "_handle_shipping",
            "_handle_returns", "_handle_recommendation",
            "_handle_pricing", "_handle_discount",
            "_handle_contact", "_handle_greeting",
            "_handle_thanks", "_handle_unknown",
            "_detect_intent", "_intent_confidence",
        ):
            assert not hasattr(ChatAI, name), (
                f"ChatAI.{name} should have been removed"
            )

    def test_no_canned_template_strings(self):
        """The 'shipping info' / 'return policy' template strings
        are gone."""
        import core.intelligence.chat_ai as mod
        import inspect
        src = inspect.getsource(mod)
        forbidden = (
            "Standard shipping: 5-7 business days",
            "30-day hassle-free returns",
            "WELCOME10",
        )
        for f in forbidden:
            assert f not in src, (
                f"chat_ai.py still contains canned template {f!r}"
            )

    def test_echoes_message_and_context(self):
        from core.intelligence.chat_ai import ChatAI
        out = ChatAI().respond("hello", {"customer_id": "c123"})
        assert out["message"] == "hello"
        assert out["context"]["customer_id"] == "c123"


# ─────────────────────────────────────────────────────────────
# 7. SearchExecutor — no simulated corpus
# ─────────────────────────────────────────────────────────────

class TestSearchExecutorNoSimulatedCorpus:
    def test_returns_empty(self):
        from engines.auto_research.search_executor import execute_searches
        out = execute_searches([{"text": "pricing strategy"}])
        # Pre-cleanup: returned 5 fake hits from the hardcoded
        # ``_SIMULATED_CORPUS``. Now: empty.
        assert out == []

    def test_returns_empty_for_many_queries(self):
        from engines.auto_research.search_executor import execute_searches
        out = execute_searches([
            {"text": "competitive landscape"},
            {"text": "consumer spending"},
            {"text": "pricing optimization"},
        ])
        assert out == []

    def test_corpus_constant_removed(self):
        import engines.auto_research.search_executor as se
        # The corpus and the simulator helper must both be gone.
        assert not hasattr(se, "_SIMULATED_CORPUS")
        assert not hasattr(se, "_simulate_search")

    def test_no_example_com_urls_in_source(self):
        import inspect
        import engines.auto_research.search_executor as se
        src = inspect.getsource(se)
        # The fake hits all used example.com domains. None should
        # appear in production code (only allowed in docstring
        # comments which we strip below by checking actual data
        # literals).
        for fake_url in (
            "https://example.com/market-overview",
            "https://reports.example.org/competitive-landscape",
            "https://retailnews.example.net/innovation",
        ):
            assert fake_url not in src


# ─────────────────────────────────────────────────────────────
# 8. Hashtag generator — no fake volume scores
# ─────────────────────────────────────────────────────────────

class TestHashtagGeneratorNoFakeVolume:
    def test_volume_score_is_none_for_all(self):
        from engines.social_media.hashtag_generator import generate_hashtags
        out = generate_hashtags(
            platforms=["instagram"],
            products=[{"category": "fashion"}],
            brand={"name": "TestBrand"},
            goal="engagement",
            platform_analyses=[{"platform": "instagram", "hashtag_limit": 10}],
        )
        ranked = out["hashtag_sets"][0]["ranked"]
        assert ranked
        for entry in ranked:
            # Pre-cleanup: each entry had a hand-picked decimal
            # 0.40-0.99 from ``_VOLUME_SCORES``.
            assert entry["volume_score"] is None
            assert "tag" in entry

    def test_constants_removed(self):
        import engines.social_media.hashtag_generator as hg
        assert not hasattr(hg, "_VOLUME_SCORES")
        assert not hasattr(hg, "_DEFAULT_VOLUME")


# ─────────────────────────────────────────────────────────────
# 9. Action dispatcher — no fake "dispatched" success
# ─────────────────────────────────────────────────────────────

class TestActionDispatcherAdapterRequired:
    def test_non_dry_run_returns_adapter_required(self):
        from engines.autonomous_execution.action_dispatcher import dispatch_actions
        out = dispatch_actions(
            actions=[{"type": "api_call", "target": "shopify", "params": {}}],
            execution_config={"dry_run": False},
        )
        first = out["result"]["dispatched"][0]
        # Pre-cleanup: ``status = "dispatched"`` with fake result.
        assert first["status"] == "adapter_required"
        assert first["result"]["reason"].startswith("action_dispatcher does not execute")

    def test_dry_run_still_marks_dry_run(self):
        from engines.autonomous_execution.action_dispatcher import dispatch_actions
        out = dispatch_actions(
            actions=[{"type": "api_call", "target": "shopify", "params": {"k": 1}}],
            execution_config={"dry_run": True},
        )
        first = out["result"]["dispatched"][0]
        assert first["status"] == "dry_run"
        assert first["result"]["would_execute"] is True
        assert first["result"]["params_count"] == 1

    def test_unsupported_type_still_skipped(self):
        from engines.autonomous_execution.action_dispatcher import dispatch_actions
        out = dispatch_actions(
            actions=[{"type": "unicorn_dance", "target": "?"}],
            execution_config={},
        )
        first = out["result"]["dispatched"][0]
        assert first["status"] == "skipped"

    def test_progress_tracker_counts_pending_separately(self):
        """Pin the consumer wiring: progress_tracker must NOT
        count adapter_required as completed."""
        from engines.autonomous_execution.progress_tracker import track_progress
        dispatched = [
            {"action": {"id": "a1"}, "status": "adapter_required"},
            {"action": {"id": "a2"}, "status": "dry_run"},
        ]
        out = track_progress(
            action_dispatcher_data={"dispatched": dispatched},
        )
        result = out["result"]
        assert result["completed"] == 1  # only the dry_run
        assert result["pending"] == 1
        assert result["failed"] == 0

    def test_result_validator_pending_bucket(self):
        """Pin the consumer wiring: result_validator surfaces
        adapter_required actions in a separate ``pending`` list."""
        from engines.autonomous_execution.result_validator import validate_results
        dispatched = [
            {"action": {"id": "a1"}, "status": "adapter_required",
             "result": {"foo": 1}},
            {"action": {"id": "a2"}, "status": "dry_run",
             "result": {"bar": 2}},
        ]
        out = validate_results(
            action_dispatcher_data={"dispatched": dispatched},
            error_handler_data={},
            progress_tracker_data={},
        )
        result = out["result"]
        assert len(result["executed"]) == 1
        assert len(result["pending"]) == 1
        assert result["pending"][0]["status"] == "adapter_required"


# ─────────────────────────────────────────────────────────────
# 10. Smart executor dry_run — no automatic success
# ─────────────────────────────────────────────────────────────

class TestSmartExecutorDryRunValidates:
    def test_empty_action_type_fails(self):
        from execution.smart_executor import SmartExecutor
        out = SmartExecutor()._execute_dry_run({"type": ""})
        # Pre-cleanup: always success=True even for empty type.
        assert out["validated"] is False
        assert out["success"] is False
        assert out["would_execute"] is False
        assert "missing_type" in out["validation_errors"]

    def test_non_dict_params_fails(self):
        from execution.smart_executor import SmartExecutor
        out = SmartExecutor()._execute_dry_run({"type": "x", "params": "not_a_dict"})
        assert out["validated"] is False
        assert "params_not_dict" in out["validation_errors"]

    def test_valid_action_passes(self):
        from execution.smart_executor import SmartExecutor
        out = SmartExecutor()._execute_dry_run(
            {"type": "price_update", "params": {"sku": "X"}},
        )
        assert out["validated"] is True
        assert out["success"] is True
        assert out["would_execute"] is True
        assert out["validation_errors"] == []

    def test_action_with_no_params_passes(self):
        from execution.smart_executor import SmartExecutor
        out = SmartExecutor()._execute_dry_run({"type": "price_update"})
        assert out["validated"] is True
