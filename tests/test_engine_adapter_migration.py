"""Tests for the Phase 2 engine consumer migration.

Verifies that three engines that previously had ``adapter_required``
placeholders now route through the ``SmartRouter``:

  * ``engines/order_management/inventory_checker.py``
      → ``Capability.SHOPIFY_FETCH_PRODUCTS``
  * ``engines/order_management/fraud_screener.py``
      → ``Capability.SHOPIFY_ASSESS_RISK`` (combined with the
        existing local heuristic)
  * ``core/intelligence/chat_ai.py``
      → ``Capability.CHAT_COMPLETE``

Each migration is **additive**: when no adapter is configured
the engine still behaves the way the cleanup pinned (no fake
data, ``unknown`` items, ``adapter_required`` envelope, etc.).
When an adapter IS wired, the engine returns real data from
the router.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
    get_registry,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)
from core.adapters.errors import AdapterError, AdapterUnavailable


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Reset every adapter singleton between tests so cycles
    don't leak."""
    for var in (
        "GROQ_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY",
        "MISTRAL_API_KEY", "OPENROUTER_API_KEY", "HUGGINGFACE_API_KEY",
        "OLLAMA_BASE_URL", "SHOPAI_SHOPIFY_URL", "SHOPAI_SHOPIFY_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


# ── Test fixture: in-process fake adapters ──────────────────


class _FakeInventoryAdapter(BaseAdapter):
    """Stand-in for ShopifyInventoryAdapter that returns
    pre-canned per-SKU data without touching the network."""

    name = "fake_inventory"
    category = AdapterCategory.SHOPIFY_NATIVE
    capabilities = {Capability.SHOPIFY_FETCH_PRODUCTS}
    priority = 100

    def __init__(self, stock_map: dict[str, int]) -> None:
        super().__init__()
        self._stock = stock_map

    def is_configured(self) -> bool:
        return True

    def _execute(self, capability, params):
        sku = params.get("sku")
        if sku in self._stock:
            return AdapterResult.success(
                adapter=self.name,
                capability=capability.value,
                data={
                    "sku": sku,
                    "found": True,
                    "tracked": True,
                    "total": self._stock[sku],
                    "by_location": [],
                },
            )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"sku": sku, "found": False, "total": 0},
        )


class _FakeRiskAdapter(BaseAdapter):
    """Stand-in for ShopifyRiskAdapter that returns a fixed
    risk score for any order."""

    name = "fake_risk"
    category = AdapterCategory.SHOPIFY_NATIVE
    capabilities = {Capability.SHOPIFY_ASSESS_RISK}
    priority = 100

    def __init__(
        self,
        score: float = 0.85,
        recommendation: str = "cancel",
    ) -> None:
        super().__init__()
        self._score = score
        self._reco = recommendation

    def is_configured(self) -> bool:
        return True

    def _execute(self, capability, params):
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "order_id": params.get("order_id", ""),
                "found": True,
                "risk_level": "HIGH" if self._score >= 0.7 else "MEDIUM",
                "score": self._score,
                "recommendation": self._reco,
                "facts": [{"description": "test fact",
                           "sentiment": "NEGATIVE"}],
                "protect_eligible": True,
            },
        )


class _FakeChatAdapter(BaseAdapter):
    """Stand-in LLM adapter that always returns the same reply."""

    name = "fake_chat"
    category = AdapterCategory.LLM
    capabilities = {Capability.CHAT_COMPLETE}
    priority = 100

    def __init__(self, reply: str = "Sure, let me help!") -> None:
        super().__init__()
        self._reply = reply

    def is_configured(self) -> bool:
        return True

    def _execute(self, capability, params):
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"text": self._reply},
            model="fake-1.0",
            tokens_in=10,
            tokens_out=5,
        )


# ── inventory_checker.py ────────────────────────────────────


class TestInventoryCheckerMigration:
    def test_explicit_stock_levels_bypass_adapter(self):
        """When the caller passes a stock_levels dict, the
        adapter must NOT be called. This preserves the
        cleanup behaviour."""
        from engines.order_management.inventory_checker import check_inventory
        # Register a fake that would EXPLODE if called
        class _Boom(BaseAdapter):
            name = "boom_inv"
            category = AdapterCategory.SHOPIFY_NATIVE
            capabilities = {Capability.SHOPIFY_FETCH_PRODUCTS}
            def is_configured(self): return True
            def _execute(self, c, p):
                raise AssertionError("adapter must not be called")
        get_registry().register(_Boom())

        result = check_inventory(
            [{"sku": "ABC", "quantity": 3}],
            stock_levels={"ABC": 5},
        )
        assert result["all_in_stock"] is True
        assert result["reservations"][0]["reserved"] is True

    def test_explicit_empty_dict_skips_adapter(self):
        """An EXPLICIT empty dict means "no adapter, please" —
        used by tests + offline cycles."""
        from engines.order_management.inventory_checker import check_inventory
        class _Boom(BaseAdapter):
            name = "boom_inv"
            category = AdapterCategory.SHOPIFY_NATIVE
            capabilities = {Capability.SHOPIFY_FETCH_PRODUCTS}
            def is_configured(self): return True
            def _execute(self, c, p):
                raise AssertionError("adapter must not be called")
        get_registry().register(_Boom())

        result = check_inventory(
            [{"sku": "ABC", "quantity": 3}],
            stock_levels={},
        )
        assert result["all_in_stock"] is False
        assert len(result["unknown"]) == 1

    def test_none_triggers_adapter_lookup(self):
        """When stock_levels is None, the engine must query the
        adapter and use the returned values."""
        from engines.order_management.inventory_checker import check_inventory
        get_registry().register(_FakeInventoryAdapter({"ABC": 100, "XYZ": 2}))

        result = check_inventory([
            {"sku": "ABC", "quantity": 5},
            {"sku": "XYZ", "quantity": 5},  # shortage
        ])

        # ABC reserved, XYZ shortage
        assert result["all_in_stock"] is False
        abc = next(r for r in result["reservations"] if r["sku"] == "ABC")
        xyz = next(r for r in result["reservations"] if r["sku"] == "XYZ")
        assert abc["reserved"] is True
        assert xyz["reserved"] is False
        assert any(s["sku"] == "XYZ" for s in result["shortages"])
        assert result["unknown"] == []

    def test_none_with_no_adapter_falls_back_to_unknown(self):
        """No adapter configured → cleanup behaviour: every SKU
        is ``unknown``. Real cycle running on a fresh box hits
        this code path before the operator wires Shopify."""
        from engines.order_management.inventory_checker import check_inventory
        result = check_inventory([{"sku": "ANY", "quantity": 1}])
        assert result["all_in_stock"] is False
        assert len(result["unknown"]) == 1
        assert result["unknown"][0]["reason"] == "stock_not_supplied"

    def test_partial_adapter_resolution(self):
        """Adapter resolves SOME SKUs but not others — the
        unresolved ones become ``unknown``, NOT shortages."""
        from engines.order_management.inventory_checker import check_inventory
        get_registry().register(_FakeInventoryAdapter({"KNOWN": 10}))

        result = check_inventory([
            {"sku": "KNOWN", "quantity": 5},
            {"sku": "MISSING", "quantity": 5},
        ])
        # KNOWN is reserved, MISSING is unknown (not a shortage)
        known = next(r for r in result["reservations"] if r["sku"] == "KNOWN")
        assert known["reserved"] is True
        assert any(u["sku"] == "MISSING" for u in result["unknown"])

    def test_no_md5_simulator(self):
        """The MD5 simulator function must stay deleted, even
        after the adapter wiring."""
        import engines.order_management.inventory_checker as ic
        assert not hasattr(ic, "_simulate_stock_level")


# ── fraud_screener.py ───────────────────────────────────────


class TestFraudScreenerMigration:
    def test_no_order_id_runs_heuristic_only(self):
        """When the order has no Shopify ID, the engine runs
        only the local heuristic — same as the cleanup
        behaviour."""
        from engines.order_management.fraud_screener import screen_for_fraud
        result = screen_for_fraud({
            "total_price": 50,
            "email": "real@example.com",
            "customer": {"orders_count": 10},
        })
        assert result["status"] == "success"
        assert "shopify_risk" not in result
        assert result["heuristic_score"] == result["risk_score"]

    def test_heuristic_alone_flags_high_value_new_customer(self):
        """The legitimate heuristic signals are preserved
        through the migration."""
        from engines.order_management.fraud_screener import screen_for_fraud
        result = screen_for_fraud({
            "total_price": 600,
            "email": "fake@gmail.com",
            "customer": {"orders_count": 0},
        })
        assert "high_value_new_customer" in result["flags"]
        assert result["heuristic_score"] >= 0.3

    def test_with_order_id_combines_with_shopify(self):
        """Adapter score wins when it's higher than the
        heuristic — Shopify sees signals we don't."""
        from engines.order_management.fraud_screener import screen_for_fraud
        get_registry().register(
            _FakeRiskAdapter(score=0.95, recommendation="cancel"),
        )

        result = screen_for_fraud({
            "id": "12345",
            "total_price": 50,           # heuristic would say LOW
            "customer": {"orders_count": 10},
        })

        assert "shopify_risk" in result
        assert result["shopify_risk"]["score"] == 0.95
        assert result["shopify_risk"]["recommendation"] == "cancel"
        # Combined score is the MAX → 0.95
        assert result["risk_score"] == 0.95
        assert result["risk_level"] == "high"
        assert result["recommendation"] == "reject"
        assert "shopify_risk_cancel" in result["flags"]

    def test_heuristic_wins_when_higher(self):
        """If the local heuristic catches a brand-new pattern
        that Shopify hasn't trained on yet, the heuristic
        wins. The migration must NOT throw away local signal
        in favour of the adapter."""
        from engines.order_management.fraud_screener import screen_for_fraud
        get_registry().register(
            _FakeRiskAdapter(score=0.10, recommendation="accept"),
        )

        result = screen_for_fraud({
            "id": "1",
            "total_price": 6000,            # extremely high
            "email": "fake@gmail.com",      # free email
            "customer": {"orders_count": 0},  # new customer
            "shipping_address": {"country_code": "US"},
            "billing_address": {"country_code": "RU"},   # mismatch
        })

        # Heuristic should be ≥ 0.7 from the stacked rules
        assert result["heuristic_score"] >= 0.7
        # Combined = max(heuristic, shopify) = heuristic
        assert result["risk_score"] == result["heuristic_score"]
        assert result["risk_level"] == "high"

    def test_adapter_failure_does_not_break_screening(self):
        """If the adapter raises or returns failure, the engine
        must still produce a heuristic-only result rather than
        propagating the exception."""
        from engines.order_management.fraud_screener import screen_for_fraud

        class _Broken(BaseAdapter):
            name = "broken_risk"
            category = AdapterCategory.SHOPIFY_NATIVE
            capabilities = {Capability.SHOPIFY_ASSESS_RISK}
            def is_configured(self): return True
            def _execute(self, c, p):
                raise AdapterUnavailable(self.name, "down")
        get_registry().register(_Broken())

        result = screen_for_fraud({
            "id": "1",
            "total_price": 50,
            "customer": {"orders_count": 10},
        })
        assert result["status"] == "success"
        # No shopify_risk field — adapter failed silently
        assert "shopify_risk" not in result

    def test_shopify_investigate_flag(self):
        """A medium-severity Shopify recommendation gets a
        distinct flag so the operator can spot it in logs."""
        from engines.order_management.fraud_screener import screen_for_fraud
        get_registry().register(
            _FakeRiskAdapter(score=0.55, recommendation="investigate"),
        )
        result = screen_for_fraud({
            "id": "1",
            "total_price": 50,
            "customer": {"orders_count": 10},
        })
        assert "shopify_risk_investigate" in result["flags"]


# ── chat_ai.py ──────────────────────────────────────────────


class TestChatAIMigration:
    def test_no_adapter_returns_placeholder(self):
        """No LLM adapter wired → cleanup behaviour preserved."""
        from core.intelligence.chat_ai import ChatAI
        result = ChatAI().respond("where is my order?")
        assert result["status"] == "adapter_required"
        assert result["response"] == ""
        assert result["message"] == "where is my order?"

    def test_adapter_response_returned_as_text(self):
        """When an LLM adapter is configured, the engine
        returns the LLM's actual reply text."""
        from core.intelligence.chat_ai import ChatAI
        get_registry().register(
            _FakeChatAdapter(reply="Your order ships tomorrow."),
        )
        result = ChatAI().respond(
            "where is my order?",
            context={"order_id": "1234"},
        )
        assert result["status"] == "ok"
        assert result["response"] == "Your order ships tomorrow."
        assert result["adapter"] == "fake_chat"
        assert result["model"] == "fake-1.0"
        assert result["tokens_in"] == 10
        assert result["tokens_out"] == 5

    def test_context_included_in_prompt(self):
        """The merchant context dict must reach the LLM as
        part of the prompt so the response can be grounded."""
        from core.intelligence.chat_ai import ChatAI

        captured = {}

        class _Capture(BaseAdapter):
            name = "capture_chat"
            category = AdapterCategory.LLM
            capabilities = {Capability.CHAT_COMPLETE}
            priority = 100
            def is_configured(self): return True
            def _execute(self, c, p):
                captured.update(p)
                return AdapterResult.success(
                    adapter=self.name,
                    capability=c.value,
                    data={"text": "ok"},
                )

        get_registry().register(_Capture())
        ChatAI().respond(
            "tell me about my order",
            context={"order_id": "X9", "customer_name": "Alice"},
        )

        prompt = captured.get("prompt", "")
        assert "X9" in prompt
        assert "Alice" in prompt
        assert "tell me about my order" in prompt
        # System prompt threaded through
        assert "system" in captured
        assert "customer service" in captured["system"].lower()

    def test_empty_response_falls_back_to_placeholder(self):
        """If the LLM returns an empty string the engine still
        gives the caller a structured envelope they can detect."""
        from core.intelligence.chat_ai import ChatAI
        get_registry().register(_FakeChatAdapter(reply="   "))
        result = ChatAI().respond("hi")
        assert result["status"] == "adapter_required"

    def test_adapter_failure_falls_back_to_placeholder(self):
        """When the only configured adapter raises, the engine
        falls back to the placeholder envelope rather than
        propagating the error."""
        from core.intelligence.chat_ai import ChatAI

        class _Broken(BaseAdapter):
            name = "broken_chat"
            category = AdapterCategory.LLM
            capabilities = {Capability.CHAT_COMPLETE}
            def is_configured(self): return True
            def _execute(self, c, p):
                raise AdapterUnavailable(self.name, "down")
        get_registry().register(_Broken())

        result = ChatAI().respond("hello")
        assert result["status"] == "adapter_required"

    def test_response_strips_whitespace(self):
        from core.intelligence.chat_ai import ChatAI
        get_registry().register(
            _FakeChatAdapter(reply="  \n  Real reply.  \n  "),
        )
        result = ChatAI().respond("hi")
        assert result["status"] == "ok"
        assert result["response"] == "Real reply."

    def test_message_and_context_echoed(self):
        from core.intelligence.chat_ai import ChatAI
        get_registry().register(_FakeChatAdapter())
        result = ChatAI().respond(
            "test message",
            context={"key": "value"},
        )
        assert result["message"] == "test message"
        assert result["context"]["key"] == "value"

    def test_non_string_message_normalised(self):
        """The respond() method must accept non-string input
        gracefully — caller bugs shouldn't propagate."""
        from core.intelligence.chat_ai import ChatAI
        result = ChatAI().respond(None)  # type: ignore[arg-type]
        # Treated as empty string → placeholder
        assert result["status"] == "adapter_required"
        assert result["message"] == ""
