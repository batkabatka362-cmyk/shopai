"""AgentDispatcher — connects all 7 agents to the autonomous cycle.

Brain makes decisions → AgentDispatcher maps decisions to agents:
  add_products    → ProductAgent
  marketing_push  → MarketingAgent
  add_images      → ContentAgent
  pricing         → FinanceAgent
  restock         → OperationsAgent
  customer work   → CustomerAgent
  research        → ResearchAgent

Each agent: plan → execute → evaluate → return results.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("agent_dispatcher")

# Decision type → agent name mapping
DECISION_AGENT_MAP: dict[str, str] = {
    "add_products": "product",
    "add_similar": "product",
    "remove_underperformer": "product",
    "marketing_push": "marketing",
    "email_campaign": "marketing",
    "social_media": "marketing",
    "paid_ads": "marketing",
    "promote_high_margin": "marketing",
    "add_images": "content",
    "seo_title_optimization": "content",
    "ai_product_description": "content",
    "pricing_recommendation": "finance",
    "raise_price": "finance",
    "lower_price": "finance",
    "keep_price": "finance",
    "restock": "operations",
    "inventory_alert": "operations",
    "shipping_optimization": "operations",
    "customer_segment": "customer",
    "vip_program": "customer",
    "win_back_campaign": "customer",
    "research": "research",
    "trending_product_hunt": "research",
    "competitor_spy": "research",
    "niche_deep_dive": "research",
}


class AgentDispatcher:
    """Maps brain decisions to agents and dispatches them.

    Holds an optional reference to the Phase 1 ``SmartRouter``
    so dispatched agents can call external adapters (LLMs, APIs,
    apps, tools) without importing global singletons themselves.
    The router is wired in during ``initialize()`` and exposed
    to agents through the ``_router`` key on the per-call
    context dict that ``dispatch()`` builds.
    """

    def __init__(self) -> None:
        self._agents: dict[str, Any] = {}
        self._initialized = False
        self._dispatch_log: list[dict] = []
        # Per-agent init failure messages — symmetric with
        # LayerDispatcher / UnifiedMemory observability hooks.
        self._init_errors: dict[str, str] = {}
        # Phase 1 adapter SmartRouter — populated by initialize().
        # Agents read this from their per-call context (key
        # ``_router``) so they don't depend on global imports.
        self._router: Any = None

    def initialize(self) -> int:
        """Load all available agents. Returns count loaded.

        Each agent is imported individually; failures are captured
        per-agent in ``self._init_errors`` and logged at WARNING
        level. Previously failures were logged at DEBUG and were
        invisible at the default INFO level — operators saw
        ``"AgentDispatcher: 0 agents loaded"`` with no clue why.

        After loading agents, the dispatcher attaches the
        process-wide adapter ``SmartRouter`` so every dispatched
        agent receives it via ``context["_router"]``. The
        bootstrap call is idempotent (uses ``replace=True``)
        so calling it twice from controller + dispatcher is
        safe. Failure to wire the router is non-fatal — agents
        will simply see ``context["_router"] = None`` and fall
        back to whatever execution path they had before.
        """
        self._init_errors.clear()
        agent_modules = [
            ("product", "agents.product.agent", "ProductAgent"),
            ("marketing", "agents.marketing.agent", "MarketingAgent"),
            ("content", "agents.content.agent", "ContentAgent"),
            ("finance", "agents.finance.agent", "FinanceAgent"),
            ("operations", "agents.operations.agent", "OperationsAgent"),
            ("customer", "agents.customer.agent", "CustomerAgent"),
            ("research", "agents.research.agent", "ResearchAgent"),
        ]

        import importlib
        for name, module_path, class_name in agent_modules:
            try:
                mod = importlib.import_module(module_path)
                agent_cls = getattr(mod, class_name)
                self._agents[name] = agent_cls()
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                self._init_errors[name] = err
                logger.warning(
                    "AgentDispatcher: agent %r failed to load (%s)",
                    name, err,
                )

        # Adapter SmartRouter — wire once per dispatcher init
        # so every dispatched agent gets the full adapter
        # ecosystem (LLM + Shopify native + search + shipping)
        # via context.
        try:
            from core.adapters import get_router
            from core.adapters.llm.bootstrap import register_all as register_llms
            from core.adapters.shopify.bootstrap import register_all as register_shopify
            from core.adapters.search.bootstrap import register_all as register_search
            from core.adapters.shipping.bootstrap import register_all as register_shipping
            register_llms()
            register_shopify()
            register_search()
            register_shipping()
            self._router = get_router()
            logger.info("AgentDispatcher: SmartRouter attached")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "AgentDispatcher: SmartRouter init failed (%s) — "
                "agents will run without adapter routing", exc,
            )
            self._router = None

        self._initialized = True
        if self._init_errors:
            logger.warning(
                "AgentDispatcher: %d/%d agents loaded (%d failed: %s)",
                len(self._agents), len(agent_modules),
                len(self._init_errors), ", ".join(self._init_errors.keys()),
            )
        else:
            logger.info(
                "AgentDispatcher: %d agents loaded", len(self._agents),
            )
        return len(self._agents)

    def get_init_errors(self) -> dict[str, str]:
        """Return per-agent initialization error messages.

        Empty dict means every agent loaded successfully. Mirrors
        ``LayerDispatcher.get_init_errors()`` for symmetry.
        """
        return dict(self._init_errors)

    def dispatch(self, brain_decisions: list[dict[str, Any]],
                 context: dict[str, Any]) -> dict[str, Any]:
        """Dispatch brain decisions to appropriate agents.

        Args:
            brain_decisions: List of decisions from DecisionBrain
            context: Store data and memory context. The dispatcher
                ENRICHES this dict with ``_router`` (the
                ``SmartRouter`` instance) so dispatched agents can
                call adapters via capability instead of importing
                the registry themselves. The original ``context``
                object is NOT mutated — a shallow copy is built
                per dispatch.

        Returns:
            Dispatch results: agents called, results per agent
        """
        if not self._initialized:
            self.initialize()

        start = time.monotonic()
        results: dict[str, Any] = {}
        dispatched = 0

        # Build the per-call context once (shallow copy to avoid
        # mutating the caller's dict). Inject the router so agents
        # can reach the adapter ecosystem without importing
        # globals. ``_router`` may be None when adapter init
        # failed; agents must check before using.
        enriched_context = self._build_agent_context(context)

        for decision in brain_decisions:
            decision_type = decision.get("type", "")
            agent_name = DECISION_AGENT_MAP.get(decision_type)

            if not agent_name:
                continue

            agent = self._agents.get(agent_name)
            if not agent:
                results[decision_type] = {"status": "no_agent", "agent": agent_name}
                continue

            # Build goal for agent
            goal = {
                "objective": decision_type,
                "reason": decision.get("reason", ""),
                "priority": decision.get("priority", 4),
                "confidence": decision.get("confidence", 0.5),
            }

            try:
                agent_result = agent.run(
                    goal=goal,
                    context=enriched_context,
                    constraints={"max_actions": 5, "require_approval": True},
                )
                results[decision_type] = {
                    "status": "dispatched",
                    "agent": agent_name,
                    "result_status": agent_result.get("status", "unknown") if isinstance(agent_result, dict) else "ok",
                }
                dispatched += 1
            except Exception as exc:
                results[decision_type] = {
                    "status": "error",
                    "agent": agent_name,
                    "error": str(exc)[:100],
                }

            self._dispatch_log.append({
                "decision": decision_type, "agent": agent_name,
                "status": results[decision_type]["status"],
                "timestamp": time.time(),
            })

        elapsed = time.monotonic() - start
        return {
            "dispatched": dispatched,
            "total_decisions": len(brain_decisions),
            "agents_available": len(self._agents),
            "router_attached": self._router is not None,
            "duration_s": round(elapsed, 3),
            "results": results,
        }

    def dispatch_single(self, agent_name: str, goal: dict[str, Any],
                        context: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a single agent directly.

        ``context`` is enriched with the ``_router`` key
        (matching ``dispatch()``) so the agent gets the same
        access to the adapter ecosystem as it would in a normal
        cycle dispatch.
        """
        if not self._initialized:
            self.initialize()

        agent = self._agents.get(agent_name)
        if not agent:
            return {"status": "error", "error": f"Agent not found: {agent_name}"}

        enriched_context = self._build_agent_context(context)
        try:
            return agent.run(goal=goal, context=enriched_context, constraints={})
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _build_agent_context(self, context: dict[str, Any] | None) -> dict[str, Any]:
        """Return a shallow copy of *context* with adapter-layer
        keys injected.

        Keys added:

          * ``_router`` — the ``SmartRouter`` instance (or None
            if adapter init failed)
          * ``_capabilities`` — sorted list of capability strings
            currently servable by at least one configured
            adapter. Agents can use this to short-circuit a
            dispatch ("don't ask the router for ``send_email``
            if no email adapter is wired").

        The original ``context`` is NEVER mutated. Existing keys
        in ``context`` win over the injected ones — callers can
        override ``_router`` for tests by passing it directly.
        """
        enriched: dict[str, Any] = dict(context or {})

        if "_router" not in enriched:
            enriched["_router"] = self._router

        if "_capabilities" not in enriched and self._router is not None:
            try:
                from core.adapters import Capability, get_registry
                reg = get_registry()
                available = set()
                for adapter in reg:
                    if adapter.is_configured():
                        for cap in adapter.capabilities:
                            if isinstance(cap, Capability):
                                available.add(cap.value)
                enriched["_capabilities"] = sorted(available)
            except Exception:  # noqa: BLE001
                enriched["_capabilities"] = []

        return enriched

    def get_stats(self) -> dict[str, Any]:
        return {
            "agents_loaded": len(self._agents),
            "agents": list(self._agents.keys()),
            "dispatches": len(self._dispatch_log),
            "router_attached": self._router is not None,
        }
