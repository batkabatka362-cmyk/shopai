"""Tests for Phase 6 agent → adapter migration.

Pre-migration the agent dispatcher injected ``context["_router"]``
but individual agents never consulted it — the smoke run
confirmed ``router_attached: true`` with zero downstream adapter
usage. This phase makes three agents (Operations, Research,
Marketing) actually call the router via their ``execute()``
method, surfacing the adapter result under
``results.adapter_augmentations.<capability>``.

The migration is deliberately additive: when ``_router`` is
absent (or the capability has no configured adapter), the
existing engine-based output is returned unchanged. Backward
compat is pinned end-to-end.

Coverage per agent:

  * No ``_router`` in context → augmentation absent
  * Router present + adapter succeeds → augmentation present
  * Router present + adapter fails → augmentation absent,
    agent still returns success
  * Agent-specific context requirements (from_address +
    parcel for ops, query for research, product for marketing)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterResult,
    AdapterUnavailable,
    BaseAdapter,
    Capability,
    get_registry,
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "GROQ_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY",
        "BRAVE_SEARCH_API_KEY", "SERPER_API_KEY",
        "EASYPOST_API_KEY", "SHIPPO_API_KEY",
        "BREVO_API_KEY", "RESEND_API_KEY",
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


# ── In-process fake adapters ─────────────────────────────────


class _FakeShippingAdapter(BaseAdapter):
    name = "fake_ship"
    category = AdapterCategory.LOGISTICS
    capabilities = {Capability.SHIPPING_RATE_QUOTE}
    priority = 200

    def is_configured(self):
        return True

    def _execute(self, capability, params):
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "rates": [],
                "count": 2,
                "cheapest": {
                    "carrier": "USPS", "service": "Priority",
                    "rate": 8.95, "delivery_days": 3,
                },
                "fastest": {
                    "carrier": "UPS", "service": "2-Day",
                    "rate": 15.00, "delivery_days": 2,
                },
                "shipment_id": "shp_1",
            },
        )


class _FakeSearchAdapter(BaseAdapter):
    name = "fake_web_search"
    category = AdapterCategory.SEARCH
    capabilities = {Capability.WEB_SEARCH}
    priority = 200

    def is_configured(self):
        return True

    def _execute(self, capability, params):
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "query": params.get("query", ""),
                "count": 3,
                "hits": [
                    {"title": "Hit 1", "url": "https://a.example.com",
                     "snippet": "x", "source": "a", "retrieved_at": ""},
                    {"title": "Hit 2", "url": "https://b.example.com",
                     "snippet": "y", "source": "b", "retrieved_at": ""},
                    {"title": "Hit 3", "url": "https://c.example.com",
                     "snippet": "z", "source": "c", "retrieved_at": ""},
                ],
            },
        )


class _FakeLLMAdapter(BaseAdapter):
    name = "fake_llm_agent"
    category = AdapterCategory.LLM
    capabilities = {Capability.CHAT_COMPLETE}
    priority = 200

    def is_configured(self):
        return True

    def _execute(self, capability, params):
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "text": "Subject: Big Launch\nBody: Real copy here.",
            },
            model="fake-model-v1",
            tokens_in=50,
            tokens_out=20,
        )


class _BrokenAdapter(BaseAdapter):
    name = "broken"
    category = AdapterCategory.OTHER
    capabilities = {
        Capability.SHIPPING_RATE_QUOTE,
        Capability.WEB_SEARCH,
        Capability.CHAT_COMPLETE,
    }
    priority = 300

    def is_configured(self):
        return True

    def _execute(self, capability, params):
        raise AdapterUnavailable(self.name, "simulated outage")


# ── OperationsAgent ──────────────────────────────────────────


class TestOperationsAgentAdapterAugmentation:
    def _make_context(self, **extra):
        ctx = {
            "products": [{"id": "p1", "name": "Widget", "inventory_quantity": 5}],
            "orders": [{
                "id": "o1",
                "shipping_address": {
                    "address1": "123 Main", "city": "Seattle",
                    "zip": "98101", "country_code": "US",
                },
            }],
            "from_address": {
                "street1": "456 Warehouse", "city": "Portland",
                "zip": "97205", "country": "US",
            },
            "default_parcel": {
                "length": 10, "width": 8, "height": 4, "weight": 16,
            },
        }
        ctx.update(extra)
        return ctx

    def test_no_router_no_augmentation(self):
        """Without ``_router`` in context, the agent returns the
        existing engine-based results unchanged (cleanup
        invariant)."""
        from agents.operations.agent import OperationsAgent
        op = OperationsAgent()
        result = op.run(
            goal="Check inventory",
            context=self._make_context(),  # no _router
            constraints={},
        )
        assert result["status"] == "success"
        aug = result.get("data", {}).get("results", {}).get(
            "adapter_augmentations", {},
        )
        assert "shipping_rate_quote" not in aug

    def test_router_with_fake_shipping_adds_augmentation(self):
        """Router + fake shipping adapter → shipping_rate_quote
        appears in adapter_augmentations."""
        from agents.operations.agent import OperationsAgent
        get_registry().register(_FakeShippingAdapter())
        router = get_router()

        op = OperationsAgent()
        ctx = self._make_context(_router=router)
        result = op.run(goal="Check inventory", context=ctx, constraints={})

        assert result["status"] == "success"
        aug = result["data"]["results"]["adapter_augmentations"]
        assert "shipping_rate_quote" in aug
        quote = aug["shipping_rate_quote"]
        assert quote["adapter"] == "fake_ship"
        assert quote["rate_count"] == 2
        assert quote["cheapest"]["carrier"] == "USPS"

    def test_missing_from_address_skips_augmentation(self):
        """Without a ``from_address`` the agent can't run a
        rate quote — skip silently, return the engine output
        unchanged."""
        from agents.operations.agent import OperationsAgent
        get_registry().register(_FakeShippingAdapter())
        router = get_router()

        op = OperationsAgent()
        ctx = self._make_context(_router=router)
        del ctx["from_address"]
        result = op.run(goal="Check inventory", context=ctx, constraints={})
        aug = result.get("data", {}).get("results", {}).get(
            "adapter_augmentations", {},
        )
        assert "shipping_rate_quote" not in aug

    def test_order_without_shipping_address_skips(self):
        from agents.operations.agent import OperationsAgent
        get_registry().register(_FakeShippingAdapter())
        router = get_router()

        op = OperationsAgent()
        ctx = self._make_context(_router=router)
        ctx["orders"] = [{"id": "o1"}]  # no shipping_address
        result = op.run(goal="Check inventory", context=ctx, constraints={})
        aug = result.get("data", {}).get("results", {}).get(
            "adapter_augmentations", {},
        )
        assert "shipping_rate_quote" not in aug

    def test_adapter_failure_is_silent(self):
        """Broken adapter raises → agent still returns success,
        augmentation is absent."""
        from agents.operations.agent import OperationsAgent
        get_registry().register(_BrokenAdapter())
        router = get_router()

        op = OperationsAgent()
        ctx = self._make_context(_router=router)
        result = op.run(goal="Check inventory", context=ctx, constraints={})
        # The broken adapter fails (AdapterUnavailable) → result.ok is
        # False → augmentation absent. Agent still succeeds.
        assert result["status"] == "success"
        aug = result.get("data", {}).get("results", {}).get(
            "adapter_augmentations", {},
        )
        assert "shipping_rate_quote" not in aug


# ── ResearchAgent ────────────────────────────────────────────


class TestResearchAgentAdapterAugmentation:
    def _make_context(self, **extra):
        ctx = {
            "category": "electronics",
            "query": "wireless earbuds 2026",
        }
        ctx.update(extra)
        return ctx

    def test_no_router_no_augmentation(self):
        from agents.research.agent import ResearchAgent
        ra = ResearchAgent()
        result = ra.run(
            goal="Research earbuds market",
            context=self._make_context(),
            constraints={},
        )
        aug = result.get("data", {}).get("results", {}).get(
            "adapter_augmentations", {},
        )
        assert "web_search" not in aug

    def test_router_with_fake_search(self):
        from agents.research.agent import ResearchAgent
        get_registry().register(_FakeSearchAdapter())
        router = get_router()

        ra = ResearchAgent()
        result = ra.run(
            goal="Research earbuds market",
            context=self._make_context(_router=router),
            constraints={},
        )
        aug = result["data"]["results"]["adapter_augmentations"]
        assert "web_search" in aug
        ws = aug["web_search"]
        assert ws["adapter"] == "fake_web_search"
        assert ws["query"] == "wireless earbuds 2026"
        assert ws["hit_count"] == 3
        assert len(ws["top_hits"]) == 3
        assert ws["top_hits"][0]["title"] == "Hit 1"

    def test_falls_back_to_category_when_no_query(self):
        """No ``query`` in context but ``category`` is present
        → agent uses the category as the search query."""
        from agents.research.agent import ResearchAgent
        get_registry().register(_FakeSearchAdapter())
        router = get_router()

        ra = ResearchAgent()
        ctx = {"category": "fitness", "_router": router}
        result = ra.run(goal="Scout niche", context=ctx, constraints={})
        aug = result["data"]["results"]["adapter_augmentations"]["web_search"]
        assert aug["query"] == "fitness"

    def test_no_topic_skips_augmentation(self):
        """No category, query, or topic → nothing to search,
        augmentation absent."""
        from agents.research.agent import ResearchAgent
        get_registry().register(_FakeSearchAdapter())
        router = get_router()

        ra = ResearchAgent()
        result = ra.run(
            goal="broad scan",
            context={"_router": router},  # no topic fields
            constraints={},
        )
        aug = result.get("data", {}).get("results", {}).get(
            "adapter_augmentations", {},
        )
        assert "web_search" not in aug

    def test_adapter_failure_is_silent(self):
        from agents.research.agent import ResearchAgent
        get_registry().register(_BrokenAdapter())
        router = get_router()

        ra = ResearchAgent()
        result = ra.run(
            goal="Research",
            context=self._make_context(_router=router),
            constraints={},
        )
        assert result["status"] == "success"
        aug = result.get("data", {}).get("results", {}).get(
            "adapter_augmentations", {},
        )
        assert "web_search" not in aug


# ── MarketingAgent ───────────────────────────────────────────


class TestMarketingAgentAdapterAugmentation:
    def _make_context(self, **extra):
        ctx = {
            "products": [{"id": "p1", "name": "Premium Widget", "price": 49.99}],
            "campaign_goal": "Drive pre-orders for new line",
        }
        ctx.update(extra)
        return ctx

    def test_no_router_no_augmentation(self):
        from agents.marketing.agent import MarketingAgent
        mk = MarketingAgent()
        result = mk.run(
            goal="Launch campaign",
            context=self._make_context(),
            constraints={},
        )
        aug = result.get("data", {}).get("results", {}).get(
            "adapter_augmentations", {},
        )
        assert "copy_generation" not in aug

    def test_router_with_fake_llm(self):
        from agents.marketing.agent import MarketingAgent
        get_registry().register(_FakeLLMAdapter())
        router = get_router()

        mk = MarketingAgent()
        result = mk.run(
            goal="Launch campaign",
            context=self._make_context(_router=router),
            constraints={},
        )
        aug = result["data"]["results"]["adapter_augmentations"]
        assert "copy_generation" in aug
        cg = aug["copy_generation"]
        assert cg["adapter"] == "fake_llm_agent"
        assert cg["model"] == "fake-model-v1"
        assert "Subject:" in cg["copy"]
        assert cg["tokens_in"] == 50

    def test_copy_generation_includes_product_name_in_prompt(self):
        """Verify the prompt builder actually threads the
        product name into what gets sent to the LLM."""
        from agents.marketing.agent import MarketingAgent

        captured = {}

        class _CaptureLLM(BaseAdapter):
            name = "capture_llm"
            category = AdapterCategory.LLM
            capabilities = {Capability.CHAT_COMPLETE}
            priority = 250
            def is_configured(self): return True
            def _execute(self, c, p):
                captured["prompt"] = p.get("prompt", "")
                captured["system"] = p.get("system", "")
                return AdapterResult.success(
                    adapter=self.name, capability=c.value,
                    data={"text": "generated"}, model="x",
                )
        get_registry().register(_CaptureLLM())
        router = get_router()

        mk = MarketingAgent()
        mk.run(
            goal="Launch",
            context=self._make_context(_router=router),
            constraints={},
        )
        assert "Premium Widget" in captured["prompt"]
        assert "49.99" in captured["prompt"]
        # Campaign goal should also reach the prompt
        assert "pre-orders" in captured["prompt"]
        # System prompt is the safety-guard copywriter prompt
        assert "copywriter" in captured["system"].lower()

    def test_no_product_or_goal_skips_augmentation(self):
        from agents.marketing.agent import MarketingAgent
        get_registry().register(_FakeLLMAdapter())
        router = get_router()

        mk = MarketingAgent()
        result = mk.run(
            goal="Campaign",
            context={"_router": router},  # no product, no campaign_goal
            constraints={},
        )
        aug = result.get("data", {}).get("results", {}).get(
            "adapter_augmentations", {},
        )
        assert "copy_generation" not in aug

    def test_empty_llm_reply_skips_augmentation(self):
        """Defensive: LLM returns empty text → augmentation is
        absent rather than polluting the output with an empty
        copy string."""
        from agents.marketing.agent import MarketingAgent

        class _EmptyLLM(BaseAdapter):
            name = "empty_llm"
            category = AdapterCategory.LLM
            capabilities = {Capability.CHAT_COMPLETE}
            priority = 250
            def is_configured(self): return True
            def _execute(self, c, p):
                return AdapterResult.success(
                    adapter=self.name, capability=c.value,
                    data={"text": "   "}, model="x",
                )
        get_registry().register(_EmptyLLM())
        router = get_router()

        mk = MarketingAgent()
        result = mk.run(
            goal="Campaign",
            context=self._make_context(_router=router),
            constraints={},
        )
        aug = result.get("data", {}).get("results", {}).get(
            "adapter_augmentations", {},
        )
        assert "copy_generation" not in aug

    def test_adapter_failure_is_silent(self):
        from agents.marketing.agent import MarketingAgent
        get_registry().register(_BrokenAdapter())
        router = get_router()

        mk = MarketingAgent()
        result = mk.run(
            goal="Campaign",
            context=self._make_context(_router=router),
            constraints={},
        )
        assert result["status"] == "success"
        aug = result.get("data", {}).get("results", {}).get(
            "adapter_augmentations", {},
        )
        assert "copy_generation" not in aug

    def _attach_capture(self):
        """Attach a list-backed handler to the marketing logger.
        ``utils.logger.get_logger`` sets ``propagate=False`` which
        blocks pytest's caplog, so we hook the logger directly."""
        import logging

        records: list[logging.LogRecord] = []
        mlog = logging.getLogger("shopai.agent.marketing")

        class _CaptureHandler(logging.Handler):
            def emit(self, record):
                records.append(record)

        h = _CaptureHandler(level=logging.WARNING)
        mlog.addHandler(h)
        return mlog, h, records

    def test_adapter_failure_logs_warning(self):
        """§4d audit fix: silent None is invisible degradation.
        Warning log gives the owner a real signal when the LLM
        copy augmentation silently declines."""
        import logging

        from agents.marketing.agent import MarketingAgent
        get_registry().register(_BrokenAdapter())
        router = get_router()

        mlog, handler, records = self._attach_capture()
        try:
            mk = MarketingAgent()
            mk.run(
                goal="Campaign",
                context=self._make_context(_router=router),
                constraints={},
            )
        finally:
            mlog.removeHandler(handler)
        warns = [
            r for r in records
            if r.levelno == logging.WARNING
        ]
        assert warns, (
            "marketing copy failure must emit a warning"
        )

    def test_empty_llm_reply_logs_warning(self):
        """Empty text from the LLM is degradation, not success
        — log it at warning level so the owner can see adapter
        drift in production."""
        import logging

        from agents.marketing.agent import MarketingAgent

        class _EmptyLLM(BaseAdapter):
            name = "empty_llm_for_warn"
            category = AdapterCategory.LLM
            capabilities = {Capability.CHAT_COMPLETE}
            priority = 260
            def is_configured(self): return True
            def _execute(self, c, p):
                return AdapterResult.success(
                    adapter=self.name, capability=c.value,
                    data={"text": ""}, model="x",
                )
        get_registry().register(_EmptyLLM())
        router = get_router()

        mlog, handler, records = self._attach_capture()
        try:
            mk = MarketingAgent()
            mk.run(
                goal="Campaign",
                context=self._make_context(_router=router),
                constraints={},
            )
        finally:
            mlog.removeHandler(handler)
        warns = [
            r for r in records
            if r.levelno == logging.WARNING
            and "empty text" in r.getMessage()
        ]
        assert warns, (
            "empty-text adapter must emit an empty-text warning"
        )


# ── Backward compatibility sanity ────────────────────────────


class TestAgentBackwardCompat:
    """Verify each agent still produces the original output
    shape (plan / results / evaluation / recommendation) even
    when the adapter augmentation fires."""

    def test_operations_output_shape_unchanged(self):
        from agents.operations.agent import OperationsAgent
        get_registry().register(_FakeShippingAdapter())
        router = get_router()

        op = OperationsAgent()
        result = op.run(
            goal="Check inventory",
            context={
                "_router": router,
                "products": [{"id": "p1", "name": "W", "inventory_quantity": 5}],
                "orders": [{
                    "id": "o1",
                    "shipping_address": {
                        "address1": "x", "city": "y", "zip": "1", "country": "US",
                    },
                }],
                "from_address": {
                    "street1": "a", "city": "b", "zip": "1", "country": "US",
                },
                "default_parcel": {"length": 1, "width": 1, "height": 1, "weight": 1},
            },
            constraints={},
        )
        data = result.get("data", {})
        # Classic fields must still be present
        for field in ("plan", "results", "evaluation", "recommendation"):
            assert field in data, f"{field} missing from operations output"

    def test_research_output_shape_unchanged(self):
        from agents.research.agent import ResearchAgent
        get_registry().register(_FakeSearchAdapter())
        router = get_router()

        ra = ResearchAgent()
        result = ra.run(
            goal="Research",
            context={"_router": router, "category": "fitness"},
            constraints={},
        )
        data = result.get("data", {})
        for field in ("plan", "results", "evaluation", "recommendation"):
            assert field in data, f"{field} missing from research output"

    def test_marketing_output_shape_unchanged(self):
        from agents.marketing.agent import MarketingAgent
        get_registry().register(_FakeLLMAdapter())
        router = get_router()

        mk = MarketingAgent()
        result = mk.run(
            goal="Campaign",
            context={
                "_router": router,
                "products": [{"name": "X", "price": 1.0}],
                "campaign_goal": "launch",
            },
            constraints={},
        )
        data = result.get("data", {})
        for field in ("plan", "results", "evaluation", "recommendation"):
            assert field in data, f"{field} missing from marketing output"
