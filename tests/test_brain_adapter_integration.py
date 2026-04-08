"""Integration tests for the Phase 1 brain ↔ adapter wiring.

Verifies that ``DecisionBrain``, ``AgentDispatcher``, and
``AutonomousController.initialize`` correctly wire the
``SmartRouter`` from ``core.adapters`` into the cycle path so
new code can route LLM calls (and later API calls) through the
multi-vendor adapter ecosystem instead of hard-coding
``self._llm.ask(...)``.

Coverage:

  * Brain auto-attaches the router on first ``_init_components``
  * ``smart_complete`` returns ``AdapterResult`` (success when
    the router has a configured adapter, failure with typed
    error when not)
  * ``smart_complete`` is no-op-safe when the router is missing
  * ``_deep_think`` prefers router output and falls back to
    legacy LLM when the router fails
  * ``_deep_think`` parses Markdown-fenced JSON
  * ``AgentDispatcher`` injects ``_router`` and ``_capabilities``
    into the agent context
  * ``AgentDispatcher.dispatch_single`` enriches context too
  * ``_build_agent_context`` does NOT mutate the caller's dict
  * Caller-supplied ``_router`` overrides the dispatcher's
    default
  * ``AutonomousController.initialize`` exposes
    ``_adapter_router`` + ``_adapter_status`` after a successful
    init
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.adapters import (
    AdapterResult,
    AdapterUnavailable,
    Capability,
    NoAdapterAvailable,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean_singletons(monkeypatch):
    """Drop API key env vars and reset every adapter singleton
    so tests don't see leakage from earlier files."""
    for var in (
        "GROQ_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY",
        "MISTRAL_API_KEY", "OPENROUTER_API_KEY", "HUGGINGFACE_API_KEY",
        "OLLAMA_BASE_URL",
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


# ── DecisionBrain ────────────────────────────────────────────


class TestDecisionBrainRouter:
    def test_init_attaches_smart_router(self):
        """``_init_components`` must populate ``_llm_router``
        with the singleton ``SmartRouter`` lazily."""
        from core.brain.decision_brain import DecisionBrain
        b = DecisionBrain()
        assert b._llm_router is None  # not yet
        b._init_components()
        assert b._llm_router is not None
        assert b.has_smart_router() is True

    def test_smart_complete_returns_none_when_router_missing(self):
        """If the router never initialised, ``smart_complete``
        returns ``None`` instead of raising — legacy callers can
        detect this and fall back to ``self._llm``."""
        from core.brain.decision_brain import DecisionBrain
        b = DecisionBrain()
        # Skip _init_components → router stays None
        assert b.smart_complete("hello") is None

    def test_smart_complete_returns_adapter_result(self, monkeypatch):
        """When the router has a configured adapter, the brain
        gets back a real ``AdapterResult``."""
        from core.brain.decision_brain import DecisionBrain
        from core.adapters import get_registry

        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        reset_config()

        b = DecisionBrain()
        b._init_components()  # registers all adapters

        # Patch the Groq instance the brain's router will actually
        # use. We must do this AFTER ``_init_components`` because
        # the bootstrap call there constructs fresh adapter
        # instances and registers them with replace=True.
        groq = get_registry().get("groq")
        with patch.object(
            groq, "_post_json",
            return_value={
                "choices": [{
                    "message": {"role": "assistant", "content": "stub reply"},
                }],
                "model": "llama-3.3-70b",
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            },
        ):
            result = b.smart_complete("hello world")

        assert result is not None
        assert isinstance(result, AdapterResult)
        assert result.ok
        assert result.adapter == "groq"
        assert result.data["text"] == "stub reply"
        assert result.tokens_in == 5

    def test_smart_complete_accepts_string_capability(self, monkeypatch):
        from core.brain.decision_brain import DecisionBrain
        from core.adapters import get_registry

        monkeypatch.setenv("GROQ_API_KEY", "k")
        reset_config()

        b = DecisionBrain()
        b._init_components()

        groq = get_registry().get("groq")
        with patch.object(groq, "_post_json", return_value={
            "choices": [{"message": {"content": "ok"}}],
            "model": "llama",
            "usage": {},
        }):
            result = b.smart_complete(
                "hi",
                capability="reason_fast",  # string instead of enum
            )
        assert result is not None and result.ok

    def test_smart_complete_unknown_capability_returns_none(self):
        from core.brain.decision_brain import DecisionBrain
        b = DecisionBrain()
        b._init_components()
        result = b.smart_complete("hi", capability="not_a_real_capability")
        assert result is None

    def test_smart_complete_with_system_prompt(self, monkeypatch):
        from core.brain.decision_brain import DecisionBrain
        from core.adapters import get_registry

        monkeypatch.setenv("GROQ_API_KEY", "k")
        reset_config()

        b = DecisionBrain()
        b._init_components()

        captured_payload: dict = {}
        def fake_post(url, payload, **kw):
            captured_payload.update(payload)
            return {
                "choices": [{"message": {"content": "ok"}}],
                "model": "x", "usage": {},
            }

        groq = get_registry().get("groq")
        with patch.object(groq, "_post_json", side_effect=fake_post):
            b.smart_complete("hi", system="Be terse")

        # System prompt prepended as the first message
        assert captured_payload["messages"][0]["role"] == "system"
        assert captured_payload["messages"][0]["content"] == "Be terse"


class TestDeepThinkRouterPath:
    def _make_state(self):
        from core.brain.decision_brain import StoreState
        return StoreState({
            "products": [
                {"id": "p1", "name": "Widget", "price": 49.99,
                 "cost": 15, "inventory_quantity": 10},
                {"id": "p2", "name": "Gadget", "price": 29.99,
                 "cost": 8, "inventory_quantity": 5},
            ],
            "orders": [{"id": "o1", "total": 49.99}],
            "customers": [],
        })

    def test_deep_think_uses_router_when_available(self, monkeypatch):
        """Phase 1 path: ``_deep_think`` should call the router
        with REASON_DEEP and return ``via = "smart_router"`` when
        the router succeeds."""
        from core.brain.decision_brain import DecisionBrain
        from core.adapters import get_registry

        monkeypatch.setenv("DEEPSEEK_API_KEY", "ds_test")
        reset_config()

        b = DecisionBrain()
        b._init_components()

        # Stop the router from falling through to ollama_local —
        # patch ollama's HTTP layer to fail too
        ollama = get_registry().get("ollama_local")
        # Force ollama out of the candidate set by making it
        # un-configured for this test
        ollama._configured_override = False  # marker for test isolation

        # DeepSeek is the configured cloud adapter; patch its
        # HTTP layer to return a fake JSON response.
        deepseek = get_registry().get("deepseek")
        json_payload = (
            '{"top_actions": ['
            '{"action": "raise_price", "reason": "low margin", "expected_impact": "high"}'
            ']}'
        )
        with patch.object(deepseek, "_post_json", return_value={
            "choices": [{"message": {"content": json_payload}}],
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }):
            # Also stop ollama from making real connection
            with patch.object(
                ollama, "_post_json",
                side_effect=AdapterUnavailable("ollama_local", "test stub"),
            ):
                result = b._deep_think(
                    self._make_state(), problems=[], opportunities=[],
                )

        assert result["available"] is True
        assert result["via"] == "smart_router"
        # DeepSeek wins because it's higher priority than ollama
        # (80 vs 60). The router actually picks DeepSeek first so
        # the call goes there, not to ollama.
        assert result["adapter"] == "deepseek"
        assert "top_actions" in result["reasoning"]
        assert result["tokens_in"] == 100

    def test_deep_think_parses_markdown_fenced_json(self, monkeypatch):
        """Gemini and DeepSeek wrap JSON in ```json...``` fences.
        ``_try_parse_json`` must strip them before json.loads."""
        from core.brain.decision_brain import DecisionBrain

        text = '```json\n{"top_actions": [{"action": "x"}]}\n```'
        parsed = DecisionBrain._try_parse_json(text)
        assert parsed == {"top_actions": [{"action": "x"}]}

    def test_deep_think_parses_plain_json(self):
        from core.brain.decision_brain import DecisionBrain
        parsed = DecisionBrain._try_parse_json('{"a": 1}')
        assert parsed == {"a": 1}

    def test_deep_think_returns_none_for_garbage(self):
        from core.brain.decision_brain import DecisionBrain
        assert DecisionBrain._try_parse_json("not json at all") is None
        assert DecisionBrain._try_parse_json("") is None

    def test_deep_think_falls_back_to_legacy_llm(self, monkeypatch):
        """When the router has no configured adapter for
        REASON_DEEP, ``_deep_think`` falls back to the legacy
        ``self._llm.ask()`` path."""
        from core.brain.decision_brain import DecisionBrain
        from core.adapters.llm.bootstrap import register_all

        # No env vars → no cloud adapter is configured. Ollama
        # IS configured (default URL) but the call will fail
        # because no Ollama server is running. The brain should
        # try the router, see the failure, and fall back to
        # the legacy LLM.
        register_all()

        b = DecisionBrain()
        b._init_components()

        # Stub the legacy LLM
        legacy_response = MagicMock(
            success=True,
            model="legacy_test",
            parse_json=lambda: {"top_actions": [{"action": "legacy"}]},
        )
        b._llm = MagicMock()
        b._llm.ask = MagicMock(return_value=legacy_response)

        # Force the router path to fail by patching execute
        # to return a non-ok result
        from core.adapters.errors import AdapterUnavailable as _Unavailable
        b._llm_router = MagicMock()
        b._llm_router.execute = MagicMock(return_value=AdapterResult.failure(
            adapter="ollama_local",
            capability="reason_deep",
            error=_Unavailable("ollama_local", "down"),
        ))

        result = b._deep_think(
            self._make_state(), problems=[], opportunities=[],
        )

        assert result["available"] is True
        assert result["via"] == "legacy_llm"
        assert result["model"] == "legacy_test"
        b._llm.ask.assert_called_once()

    def test_deep_think_returns_unavailable_when_both_fail(self):
        """If both the router and the legacy LLM are missing,
        ``_deep_think`` reports unavailable."""
        from core.brain.decision_brain import DecisionBrain
        b = DecisionBrain()
        # Don't init — both _llm and _llm_router stay None
        result = b._deep_think(
            self._make_state(), problems=[], opportunities=[],
        )
        assert result == {"available": False}

    def test_deep_think_router_wins_over_legacy(self, monkeypatch):
        """When BOTH paths are available and BOTH would succeed,
        the router path must win — that's the whole point of
        the migration."""
        from core.brain.decision_brain import DecisionBrain

        b = DecisionBrain()

        # Both paths configured
        b._llm = MagicMock()
        b._llm.ask = MagicMock(return_value=MagicMock(
            success=True, model="legacy",
            parse_json=lambda: {"from": "legacy"},
        ))

        b._llm_router = MagicMock()
        b._llm_router.execute = MagicMock(return_value=AdapterResult.success(
            adapter="groq",
            capability="reason_deep",
            data={"text": '{"from": "router"}'},
            model="llama-3.3-70b",
            tokens_in=10,
            tokens_out=5,
        ))

        result = b._deep_think(
            self._make_state(), problems=[], opportunities=[],
        )

        assert result["via"] == "smart_router"
        assert result["reasoning"] == {"from": "router"}
        # Legacy should NOT have been called
        b._llm.ask.assert_not_called()


# ── AgentDispatcher ──────────────────────────────────────────


class TestAgentDispatcherRouter:
    def test_initialize_attaches_router(self):
        from core.autonomous.agent_dispatcher import AgentDispatcher
        d = AgentDispatcher()
        d.initialize()
        assert d._router is not None
        assert d.get_stats()["router_attached"] is True

    def test_dispatch_injects_router_into_context(self):
        from core.autonomous.agent_dispatcher import AgentDispatcher
        d = AgentDispatcher()
        d.initialize()

        # Replace one agent with a spy that records what context
        # it received
        spy = MagicMock()
        spy.run = MagicMock(return_value={"status": "ok"})
        d._agents["product"] = spy

        d.dispatch(
            brain_decisions=[{"type": "add_products", "reason": "low count"}],
            context={"store_id": "s1"},
        )

        spy.run.assert_called_once()
        kwargs = spy.run.call_args.kwargs
        assert "context" in kwargs
        assert "_router" in kwargs["context"]
        assert kwargs["context"]["_router"] is not None
        assert "_capabilities" in kwargs["context"]
        assert isinstance(kwargs["context"]["_capabilities"], list)
        # Original key still present
        assert kwargs["context"]["store_id"] == "s1"

    def test_dispatch_does_not_mutate_caller_context(self):
        """``_build_agent_context`` must not mutate the dict the
        caller passed in."""
        from core.autonomous.agent_dispatcher import AgentDispatcher
        d = AgentDispatcher()
        d.initialize()

        original_ctx = {"store_id": "s1"}
        d.dispatch(
            brain_decisions=[],
            context=original_ctx,
        )
        # Caller's dict still has just one key
        assert "_router" not in original_ctx
        assert "_capabilities" not in original_ctx

    def test_dispatch_single_enriches_context(self):
        from core.autonomous.agent_dispatcher import AgentDispatcher
        d = AgentDispatcher()
        d.initialize()

        spy = MagicMock()
        spy.run = MagicMock(return_value={"status": "ok"})
        d._agents["finance"] = spy

        d.dispatch_single(
            "finance",
            goal={"objective": "lower_price"},
            context={"product_id": "p1"},
        )

        kwargs = spy.run.call_args.kwargs
        assert kwargs["context"]["_router"] is not None
        assert kwargs["context"]["product_id"] == "p1"

    def test_dispatch_result_includes_router_attached_flag(self):
        from core.autonomous.agent_dispatcher import AgentDispatcher
        d = AgentDispatcher()
        d.initialize()
        result = d.dispatch(brain_decisions=[], context={})
        assert "router_attached" in result
        assert result["router_attached"] is True

    def test_explicit_router_in_context_wins(self):
        """If the caller passes ``_router`` in context, the
        dispatcher must NOT overwrite it. Useful for tests +
        per-call adapter override."""
        from core.autonomous.agent_dispatcher import AgentDispatcher
        d = AgentDispatcher()
        d.initialize()

        custom_router = MagicMock(name="custom_router")
        spy = MagicMock()
        spy.run = MagicMock(return_value={"status": "ok"})
        d._agents["product"] = spy

        d.dispatch(
            brain_decisions=[{"type": "add_products"}],
            context={"_router": custom_router},
        )

        kwargs = spy.run.call_args.kwargs
        assert kwargs["context"]["_router"] is custom_router

    def test_capabilities_list_reflects_configured_adapters(self, monkeypatch):
        """``_capabilities`` should only contain capabilities
        that at least one CONFIGURED adapter implements. Without
        any cloud API key, only Ollama is configured, so we
        expect chat-style capabilities and nothing else."""
        from core.autonomous.agent_dispatcher import AgentDispatcher
        d = AgentDispatcher()
        d.initialize()
        ctx = d._build_agent_context({})
        caps = ctx["_capabilities"]
        # Ollama supports CHAT_COMPLETE + REASON_FAST + REASON_DEEP + CODE_GENERATE
        assert "chat_complete" in caps
        assert "code_generate" in caps
        # No vision adapter is configured
        assert "image_analyze" not in caps


# ── AutonomousController ─────────────────────────────────────


class TestAutonomousControllerAdapter:
    def test_initialize_exposes_adapter_router(self):
        """``AutonomousController.initialize`` must populate
        ``self._adapter_router`` and ``self._adapter_status``
        when the adapter layer loads cleanly. Phase 1 LLM,
        Phase 2 Shopify native, and Phase 3 search adapters
        must all be registered in one go."""
        import tempfile
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        from core.autonomous.controller import AutonomousController

        db = ShopAIDatabase(tempfile.mktemp(suffix=".db"))
        sm = StoreManager(db)
        sm.add_store("test", "test.myshopify.com", "shpat_test")

        ac = AutonomousController(sm, auto_approve=False)
        ac.initialize()

        assert hasattr(ac, "_adapter_router")
        assert ac._adapter_router is not None
        assert hasattr(ac, "_adapter_status")

        # 7 LLM + 4 Shopify native + 3 search = 14 adapters total
        assert len(ac._adapter_status) == 14
        names = set(ac._adapter_status.keys())
        # Phase 1 LLM adapters
        assert {
            "groq", "gemini", "deepseek", "mistral",
            "ollama_local", "openrouter", "huggingface",
        } <= names
        # Phase 2 Shopify native adapters
        assert {
            "shopify_risk", "shopify_inventory",
            "shopify_fulfillment", "shopify_metafield",
        } <= names
        # Phase 3 search adapters
        assert {"brave_search", "serper", "ddgs"} <= names
        # DDGS is the only one configured by default (no API key)
        assert ac._adapter_status["ddgs"] is True

    def test_initialize_degraded_mode_still_safe(self, monkeypatch):
        """If the adapter bootstrap blows up entirely, the
        controller must still finish initialising and the
        adapter fields must be safely set to None / empty."""
        import tempfile
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        from core.autonomous.controller import AutonomousController

        db = ShopAIDatabase(tempfile.mktemp(suffix=".db"))
        sm = StoreManager(db)
        sm.add_store("t", "t.myshopify.com", "shpat_t")

        # Force the bootstrap call to raise
        import core.adapters.llm.bootstrap as bootstrap_mod
        original = bootstrap_mod.register_all
        def boom(*a, **k):
            raise RuntimeError("boom")
        monkeypatch.setattr(bootstrap_mod, "register_all", boom)

        try:
            ac = AutonomousController(sm, auto_approve=False)
            ac.initialize()
        finally:
            monkeypatch.setattr(bootstrap_mod, "register_all", original)

        # Adapter router should be None but the controller still
        # finished initialising
        assert ac._adapter_router is None
        assert ac._adapter_status == {}
        # The non-adapter subsystems should still be present
        assert ac._unified_memory is not None
