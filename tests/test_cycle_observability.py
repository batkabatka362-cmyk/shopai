"""Regression tests for the end-to-end smoke run gap fixes.

The first smoke run against a real autonomous cycle
(``python cli.py auto --store test``) showed that the
adapter layer bootstrapped cleanly (18 adapters registered,
router attached) but the cycle's phase summaries hid every
adapter-layer signal. These tests pin the fixes so the
observability gaps don't regress.

Gaps closed:

  1. ``DecisionBrain.think`` only called ``_deep_think`` when
     ``self._llm`` was truthy, making the adapter SmartRouter
     path unreachable (router-only setups could never trigger
     LLM reasoning). Fixed by widening the gate to
     ``self._llm or self._llm_router``.

  2. ``controller.run_cycle`` brain phase summary dropped the
     ``ai_reasoning`` dict that ``_deep_think`` populates,
     hiding ``via`` / ``adapter`` / ``model`` / ``tokens``
     from operators. Fixed by surfacing the relevant fields
     on ``phases.brain`` when the adapter answered.

  3. ``controller.run_cycle`` fulfillment phase summary only
     exposed ``total`` / ``fulfillable`` / ``blocked`` and
     dropped the per-order ``shipping_rate_source`` field
     that the migrated ``auto_fulfill`` adds. Fixed by
     aggregating the sources into a count map on
     ``phases.fulfillment.shipping_rate_sources``.

  4. ``controller.run_cycle`` agents phase summary dropped
     the ``router_attached`` flag that ``AgentDispatcher``
     emits, so operators couldn't tell whether agents
     actually had the SmartRouter during dispatch. Fixed by
     surfacing ``router_attached`` on ``phases.agents``.
"""
from __future__ import annotations

import tempfile

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


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "GROQ_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY",
        "MISTRAL_API_KEY", "OLLAMA_BASE_URL",
        "SHOPAI_SHOPIFY_URL", "SHOPAI_SHOPIFY_KEY",
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


# ── Gap 1: _deep_think router-only path ─────────────────────


class _FakeLLMAdapter(BaseAdapter):
    """In-process LLM that returns a fixed JSON payload."""

    name = "fake_smoke_llm"
    category = AdapterCategory.LLM
    capabilities = {
        Capability.CHAT_COMPLETE,
        Capability.REASON_FAST,
        Capability.REASON_DEEP,
    }
    priority = 200  # higher than any real adapter

    def is_configured(self) -> bool:
        return True

    def _execute(self, capability, params):
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "text": (
                    '{"top_actions": [{"action": "raise_price",'
                    ' "reason": "margin too thin",'
                    ' "expected_impact": "high"}]}'
                ),
            },
            model="fake-gpt-4",
            tokens_in=150,
            tokens_out=80,
        )


class TestDeepThinkRouterOnlyPath:
    """Gap 1: the brain must reach ``_deep_think`` when only
    the adapter router is configured (no legacy self._llm).
    Pre-fix it required ``self._llm`` to be truthy as well,
    making the router-only case impossible."""

    def _make_brain(self):
        from core.brain.decision_brain import DecisionBrain
        b = DecisionBrain()
        b._init_components()
        # Explicitly drop the legacy LLM so the only path into
        # ``_deep_think`` is via the adapter router.
        b._llm = None
        return b

    def _make_state_with_problems(self):
        from core.brain.decision_brain import StoreState
        return StoreState({
            "products": [
                {"id": "p1", "name": "Widget", "price": 29.99,
                 "cost": 20, "inventory_quantity": 5},
            ],
            "orders": [],
            "customers": [],
        })

    def test_think_calls_deep_think_with_router_only(self):
        """No legacy LLM + configured router → ``_deep_think``
        must still fire and ``ai_reasoning`` must land on the
        thought dict."""
        get_registry().register(_FakeLLMAdapter())

        b = self._make_brain()
        store_data = {
            "products": [
                {"id": "p1", "name": "Widget", "price": 29.99,
                 "cost": 20, "inventory_quantity": 5},
            ],
            "orders": [],
            "customers": [],
        }
        thought = b.think(store_data)

        assert "ai_reasoning" in thought
        ai = thought["ai_reasoning"]
        assert ai["available"] is True
        assert ai["via"] == "smart_router"
        assert ai["adapter"] == "fake_smoke_llm"
        assert ai["model"] == "fake-gpt-4"

    def test_think_deep_think_skipped_when_neither_path_available(self):
        """Defensive: when ``self._llm`` AND ``self._llm_router``
        are both ``None``, ``_deep_think`` is not invoked (or
        returns ``available=False`` without crashing)."""
        from core.brain.decision_brain import DecisionBrain
        b = DecisionBrain()
        b._init_components()
        b._llm = None
        b._llm_router = None

        store_data = {
            "products": [{"id": "p1", "name": "Widget", "price": 10,
                          "cost": 8, "inventory_quantity": 1}],
            "orders": [], "customers": [],
        }
        thought = b.think(store_data)

        # No ai_reasoning field because the gate skipped deep think
        assert thought.get("ai_reasoning") is None or \
               thought.get("ai_reasoning") == {"available": False} or \
               thought["ai_reasoning"].get("available") is False


# ── Gap 2: Brain phase summary surfaces ai_reasoning ────────


class TestBrainPhaseSurfacesAdapter:
    """Gap 2: the controller's ``phases.brain`` summary must
    include the adapter-layer fields (``ai_available``, ``ai_via``,
    ``ai_adapter``, ``ai_model``, ``ai_tokens_in/out``) when
    ``_deep_think`` succeeds via the router."""

    def _make_controller_with_data(self):
        import tempfile
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        from core.autonomous.controller import AutonomousController

        db_path = tempfile.mktemp(suffix=".db")
        db = ShopAIDatabase(db_path)
        sm = StoreManager(db)
        sm.add_store("test", "test.myshopify.com", "shpat_test")
        db.upsert_products("test", [
            {"id": "p1", "title": "Widget", "price": 29.99,
             "cost": 20, "inventory_quantity": 5, "status": "active"},
            {"id": "p2", "title": "Gadget", "price": 49.99,
             "cost": 30, "inventory_quantity": 20, "status": "active"},
        ])
        db.upsert_orders("test", [
            {"id": "o1", "total": 29.99, "financial_status": "paid"},
        ])
        db.upsert_customers("test", [
            {"id": "c1", "name": "Test", "email": "t@t.com"},
        ])
        db.log_sync("test", "products", "success", 2, 0.1)
        db.log_sync("test", "orders", "success", 1, 0.1)
        db.log_sync("test", "customers", "success", 1, 0.1)

        controller = AutonomousController(sm, auto_approve=False)
        controller.initialize()
        return controller

    def test_brain_phase_ai_fields_present_with_router_success(self):
        """When the fake LLM answers, the summary carries the
        full set of adapter-layer diagnostics."""
        get_registry().register(_FakeLLMAdapter())
        reset_router()   # pick up the new registration

        controller = self._make_controller_with_data()
        result = controller.run_cycle("test")
        brain = result["phases"]["brain"]

        assert brain["ai_available"] is True
        assert brain["ai_via"] == "smart_router"
        assert brain["ai_adapter"] == "fake_smoke_llm"
        assert brain["ai_model"] == "fake-gpt-4"
        assert brain["ai_tokens_in"] == 150
        assert brain["ai_tokens_out"] == 80

    def test_brain_phase_ai_available_false_when_no_llm(self):
        """Pin the honest fallback: when no LLM can answer the
        summary must carry ``ai_available: false`` explicitly
        rather than silently omitting the field."""
        controller = self._make_controller_with_data()
        result = controller.run_cycle("test")
        brain = result["phases"]["brain"]
        # No ai_via / ai_adapter fields because the router had
        # nothing to route to — we just get the boolean.
        assert brain["ai_available"] is False


# ── Gap 3: Fulfillment phase surfaces shipping_rate_sources ──


class TestFulfillmentPhaseSurfacesShippingSources:
    """Gap 3: ``phases.fulfillment`` must aggregate the
    ``shipping_rate_source`` counts from the migrated
    ``auto_fulfill`` output instead of dropping them."""

    def _make_controller_with_orders(self):
        import tempfile
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        from core.autonomous.controller import AutonomousController

        db = ShopAIDatabase(tempfile.mktemp(suffix=".db"))
        sm = StoreManager(db)
        sm.add_store("test", "test.myshopify.com", "shpat_test")
        db.upsert_products("test", [
            {"id": "p1", "title": "Widget", "price": 29.99,
             "cost": 10, "inventory_quantity": 50, "status": "active"},
        ])
        db.upsert_orders("test", [
            {"id": "o1", "total": 29.99, "financial_status": "paid"},
            {"id": "o2", "total": 29.99, "financial_status": "paid"},
        ])
        db.upsert_customers("test", [
            {"id": "c1", "name": "T", "email": "t@t.com"},
        ])
        db.log_sync("test", "products", "success", 1, 0.1)
        db.log_sync("test", "orders", "success", 2, 0.1)
        db.log_sync("test", "customers", "success", 1, 0.1)

        controller = AutonomousController(sm, auto_approve=False)
        controller.initialize()
        return controller

    def test_fulfillment_phase_has_rate_sources(self):
        controller = self._make_controller_with_orders()
        result = controller.run_cycle("test")

        fulfillment = result["phases"].get("fulfillment")
        assert fulfillment is not None
        assert "shipping_rate_sources" in fulfillment
        sources = fulfillment["shipping_rate_sources"]
        assert isinstance(sources, dict)
        # Without a configured shipping adapter every order
        # carries ``shipping_rate_source = "adapter_required"``,
        # so the aggregate must show it.
        assert sources.get("adapter_required", 0) >= 1


# ── Gap 4: Agents phase surfaces router_attached ─────────────


class TestAgentsPhaseSurfacesRouter:
    """Gap 4: ``phases.agents`` must carry the
    ``router_attached`` flag so operators can tell whether
    agents actually had the SmartRouter during dispatch."""

    def _make_controller(self):
        import tempfile
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        from core.autonomous.controller import AutonomousController

        db = ShopAIDatabase(tempfile.mktemp(suffix=".db"))
        sm = StoreManager(db)
        sm.add_store("test", "test.myshopify.com", "shpat_test")
        db.upsert_products("test", [
            {"id": "p1", "title": "Widget", "price": 29.99,
             "cost": 10, "status": "active", "inventory_quantity": 10},
        ])
        db.upsert_orders("test", [
            {"id": "o1", "total": 29.99, "financial_status": "paid"},
        ])
        db.upsert_customers("test", [
            {"id": "c1", "name": "T", "email": "t@t.com"},
        ])
        db.log_sync("test", "products", "success", 1, 0.1)
        db.log_sync("test", "orders", "success", 1, 0.1)
        db.log_sync("test", "customers", "success", 1, 0.1)

        controller = AutonomousController(sm, auto_approve=False)
        controller.initialize()
        return controller

    def test_agents_phase_exposes_router_attached(self):
        controller = self._make_controller()
        result = controller.run_cycle("test")

        agents = result["phases"].get("agents")
        assert agents is not None
        # Controller initialised the adapter layer so the
        # dispatcher MUST have the router attached.
        assert agents.get("router_attached") is True
