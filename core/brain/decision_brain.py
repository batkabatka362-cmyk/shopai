"""DecisionBrain — ShopAI's autonomous thinking and decision-making core.

This is NOT a tool. This is the AI's MIND.

It observes the store, understands the situation, thinks about what to do,
considers past experience, weighs options, and makes decisions.

Like a human store owner who:
  - Wakes up and checks the store
  - Sees what happened overnight
  - Thinks about what's working and what's not
  - Decides what to focus on today
  - Takes action on the most important things
  - Reviews results and adjusts

The brain has:
  - Worldview: core beliefs about e-commerce
  - Situation awareness: understands current state
  - Memory: remembers past decisions and outcomes
  - Reasoning: thinks through options using LLM
  - Priorities: knows what matters most right now
  - Action bias: prefers doing over analyzing
"""
from __future__ import annotations

import time
from typing import Any

from utils.finance import margin as _margin
from utils.helpers import safe_float
from utils.logger import get_logger

logger = get_logger("brain.decision")


# ── Core beliefs (the AI's worldview) ────────────────────────

WORLDVIEW = {
    "profit_first": "Revenue means nothing without profit. Always track margins.",
    "customer_lifetime": "A repeat customer is 5x more valuable than a new one.",
    "speed_wins": "Fast decisions with 70% confidence beat perfect decisions that come too late.",
    "test_everything": "Never assume. Test prices, products, ads. Let data decide.",
    "cut_losers_fast": "Products not selling after 2 weeks should be removed or repriced.",
    "double_down_winners": "When something works, do MORE of it immediately.",
    "cash_flow_is_king": "Don't tie up money in slow inventory. Keep cash moving.",
    "simplicity_scales": "Simple systems that work beat complex systems that don't.",
    "learn_from_every_order": "Every sale teaches something. Every non-sale teaches more.",
    "competition_awareness": "Always know what competitors charge. Don't compete on price alone.",
}


# ── Goal-aware action weights ────────────────────────────────
#
# The ``GoalManager`` tells the brain what the store's strategic
# goal is right now. The brain uses this table to boost or
# suppress specific action types during decision ranking —
# e.g. in ``survive_crisis`` mode we boost ``lower_price`` and
# ``clear_inventory`` while suppressing ``add_products``
# (expansion during a crisis is almost always wrong).
#
# Each weight is a multiplier applied to the decision's raw
# score (priority-derived). Values > 1 boost, values < 1
# suppress. The default weight is 1.0 (unchanged). Action types
# not listed use the default.
#
# The table is intentionally small and explicit — machine-
# learned rankers have no place at the core decision layer
# because we need the behaviour to be auditable. The brain's
# learning loop operates a layer above this (weight updates
# flow from outcome tracker into a separate fast-lookup table
# that Fix C will introduce).

_GOAL_ACTION_WEIGHTS: dict[str, dict[str, float]] = {
    "survive_crisis": {
        # When cash is tight, lower prices + clear slow stock +
        # collect cash. Never expand.
        "lower_price":         1.5,
        "clear_inventory":     1.5,
        "clearance_sale":      1.5,
        "restock":             0.3,   # don't tie up cash
        "add_products":        0.1,   # absolutely not
        "raise_price":         0.4,   # risky when demand is soft
        "marketing_push":      1.2,   # traffic is cheap survival
        "email_campaign":      1.3,
    },
    "grow_customers": {
        # Churn is the threat. Retention wins, acquisition
        # follows. Price moves are secondary.
        "win_back_campaign":   1.6,
        "vip_program":         1.5,
        "loyalty_program":     1.5,
        "email_campaign":      1.4,
        "customer_segment":    1.3,
        "marketing_push":      1.3,
        "raise_price":         0.5,   # don't alienate at-risk customers
    },
    "capture_opportunity": {
        # Short window. Expand the catalog and push hard. Margin
        # can be recovered later.
        "add_products":        1.6,
        "add_similar":         1.5,
        "trending_product_hunt": 1.5,
        "marketing_push":      1.5,
        "social_media":        1.4,
        "paid_ads":            1.4,
        "raise_price":         1.1,   # capture is OK if demand is clearly there
    },
    "increase_aov": {
        # Customer base is stable. Push dollars-per-order.
        "promote_high_margin": 1.5,
        "cross_sell":          1.5,
        "upsell":              1.5,
        "create_bundles":      1.4,
        "add_premium":         1.4,
        "raise_price":         1.2,
        "marketing_push":      0.8,   # traffic is not the bottleneck
    },
    "maximize_profit": {
        # Default mode. No modulation — rank purely by severity.
    },
}


class StoreState:
    """Current understanding of the store's situation."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.products = data.get("products", [])
        self.orders = data.get("orders", data.get("order_data", []))
        self.customers = data.get("customers", data.get("customer_data", []))
        self.store_id = data.get("store_id", "")
        self.timestamp = time.time()

    @property
    def product_count(self) -> int:
        return len(self.products)

    @property
    def order_count(self) -> int:
        return len(self.orders)

    @property
    def total_revenue(self) -> float:
        return sum(float(o.get("total", 0) or 0) for o in self.orders)

    @property
    def avg_margin(self) -> float:
        margins = []
        for p in self.products:
            m = _margin(p.get("price", 0), p.get("cost", 0), default=-1.0)
            if m >= 0:
                margins.append(m)
        return sum(margins) / len(margins) if margins else 0

    @property
    def out_of_stock(self) -> list[dict]:
        return [p for p in self.products if int(p.get("inventory_quantity", 0) or 0) == 0]

    @property
    def low_stock(self) -> list[dict]:
        return [p for p in self.products if 0 < int(p.get("inventory_quantity", 0) or 0) < 10]

    @property
    def health_score(self) -> int:
        """0-100 store health score."""
        score = 50  # Base
        if self.product_count >= 10:
            score += 10
        elif self.product_count < 5:
            score -= 10
        if self.order_count > 0:
            score += 15
        if self.avg_margin > 0.5:
            score += 10
        elif self.avg_margin < 0.3:
            score -= 10
        if not self.out_of_stock:
            score += 5
        else:
            score -= len(self.out_of_stock) * 5
        if len(self.customers) > 10:
            score += 10
        return max(0, min(100, score))

    def summary(self) -> dict[str, Any]:
        return {
            "products": self.product_count,
            "orders": self.order_count,
            "customers": len(self.customers),
            "revenue": round(self.total_revenue, 2),
            "avg_margin": round(self.avg_margin, 3),
            "out_of_stock": len(self.out_of_stock),
            "low_stock": len(self.low_stock),
            "health_score": self.health_score,
        }


class DecisionBrain:
    """ShopAI's autonomous decision-making core.

    Holds two LLM execution paths:

      * ``self._llm`` (legacy) — ``core.system.llm_adapter`` from
        the original ShopAI build. Kept intact for backwards
        compatibility with the cycle code that already calls
        ``self._llm.ask(...)``.
      * ``self._llm_router`` (Phase 1 adapter layer) — the
        ``SmartRouter`` from ``core.adapters``. Picks the best
        registered LLM adapter (Groq → Gemini → DeepSeek →
        Mistral → Ollama → OpenRouter → HuggingFace) for each
        capability, falls back through the chain on failure,
        records metrics for every call.

    The ``smart_complete()`` helper is the recommended path for
    new code; ``_deep_think()`` now tries it first and only
    falls back to the legacy LLM if the router cannot serve the
    request. Old call sites that still use ``self._llm.ask(...)``
    keep working without modification.
    """

    def __init__(self) -> None:
        self._llm = None
        self._llm_router = None  # Phase 1 adapter SmartRouter
        self._experience = None
        self._skills = None
        self._memory = None
        self._decision_history: list[dict[str, Any]] = []

    def _init_components(self) -> None:
        if not self._llm:
            try:
                from core.system.llm_adapter import get_llm
                self._llm = get_llm()
            except Exception:
                pass

        # ── Adapter layer SmartRouter ──
        # Lazily attach the singleton SmartRouter so brain calls
        # can route through every adapter ecosystem:
        #
        #   * Phase 1 LLM adapters (Groq / Gemini / DeepSeek /
        #     Mistral / Ollama / OpenRouter / HuggingFace)
        #   * Phase 2 Shopify native adapters (risk / inventory /
        #     fulfillment / metafield)
        #   * Phase 3 Search adapters (Brave / Serper / DDGS)
        #   * Phase 4 Shipping adapters (EasyPost / Shippo)
        #   * Phase 5 Email adapters (Brevo / Resend)
        #
        # All bootstrap calls are idempotent (uses replace=True
        # internally) so calling them from both controller and
        # brain is safe — second call is a no-op against an
        # already-populated registry. Failure here is non-fatal:
        # the legacy ``self._llm`` path keeps working.
        if not self._llm_router:
            try:
                from core.adapters import get_router
                from core.adapters.llm.bootstrap import register_all as register_llms
                from core.adapters.shopify.bootstrap import register_all as register_shopify
                from core.adapters.search.bootstrap import register_all as register_search
                from core.adapters.shipping.bootstrap import register_all as register_shipping
                from core.adapters.email.bootstrap import register_all as register_email
                register_llms()
                register_shopify()
                register_search()
                register_shipping()
                register_email()
                self._llm_router = get_router()
            except Exception as exc:  # noqa: BLE001
                logger.debug("smart router init failed: %s", exc)
                self._llm_router = None

        if not self._experience:
            try:
                from core.ai.experience import get_experience
                self._experience = get_experience()
            except Exception:
                pass
        if not self._skills:
            try:
                from core.system.adaptive_skills import get_adaptive_skills
                self._skills = get_adaptive_skills()
            except Exception:
                pass
        if not self._memory:
            try:
                from core.system.shared_memory import get_shared_memory
                self._memory = get_shared_memory()
            except Exception:
                pass
        # Connect brain memory + intelligence memory via the
        # UnifiedMemory entry point (Fix D). Pre-fix this code
        # imported ``core.brain.memory.get_brain_memory`` and
        # ``core.memory.intelligence.get_memory_intelligence``
        # directly, bypassing ``UnifiedMemory`` entirely. That
        # left two parallel SQLite DBs with no single owner
        # and made any future observability / backend swap a
        # grep-the-codebase exercise. Now both backends come
        # from ``UnifiedMemory.get_brain_memory()`` and
        # ``UnifiedMemory.get_memory_intelligence()`` so
        # callers don't have to know the underlying module
        # layout.
        if not hasattr(self, "_brain_memory") or not self._brain_memory:
            try:
                from core.memory.unified_memory import get_unified_memory
                from core.brain.decision_engine import DecisionEngine
                from core.brain.learning_loop import LearningLoop
                _unified = get_unified_memory()
                self._brain_memory = _unified.get_brain_memory()
                self._decision_engine = DecisionEngine()
                self._learning_loop = LearningLoop()
            except Exception:
                self._brain_memory = None
                self._decision_engine = None
                self._learning_loop = None
        # Connect MemoryIntelligence (4-level) + DataArchitecture
        if not hasattr(self, "_memory_intel") or not self._memory_intel:
            try:
                from core.memory.unified_memory import get_unified_memory
                from core.data.architecture import get_data_architecture
                _unified = get_unified_memory()
                self._memory_intel = _unified.get_memory_intelligence()
                self._data_arch = get_data_architecture()
            except Exception:
                self._memory_intel = None
                self._data_arch = None

    # ── Adapter-layer convenience helpers ────────────────────

    def smart_complete(
        self,
        prompt: str,
        *,
        capability: Any = None,
        system: str | None = None,
        context: Any = None,
        **params: Any,
    ) -> Any:
        """Route a prompt through the Phase 1 LLM adapter layer.

        Returns:
            ``AdapterResult`` on success/failure (caller checks
            ``result.ok``), or ``None`` when the adapter layer is
            not initialised at all (legacy callers can detect
            this and fall back to ``self._llm``).

        Args:
            prompt:     User prompt text. Required.
            capability: Optional ``Capability`` enum (or string).
                        Defaults to ``CHAT_COMPLETE``. Use
                        ``REASON_DEEP`` for strategic reasoning,
                        ``CODE_GENERATE`` for Shopify Functions
                        Rust generation, ``LONG_CONTEXT`` when
                        the prompt exceeds 100K tokens, etc.
            system:     Optional system prompt prepended to the
                        message list.
            context:    Optional ``RouteContext`` carrying budget /
                        region / PII routing hints. Pass an
                        instance from ``core.adapters`` directly,
                        or omit for default routing.
            **params:   Forwarded to the adapter (model,
                        max_tokens, temperature, ...).

        Why this exists:
            New brain code should call this instead of touching
            ``self._llm.ask(...)`` so the multi-vendor router
            (with fallback chains, metrics, free-tier quota
            tracking, PII safety) is used end-to-end. The legacy
            ``self._llm`` is kept around so existing call sites
            don't break in this commit, but new features must
            use ``smart_complete``.
        """
        if not self._llm_router:
            return None

        try:
            from core.adapters import Capability, RouteContext
        except Exception as exc:  # noqa: BLE001
            logger.debug("adapter import failed: %s", exc)
            return None

        # Default to plain chat completion. Accept either an enum
        # or a string capability so callers don't have to import
        # the enum.
        cap: Any = capability or Capability.CHAT_COMPLETE
        if isinstance(cap, str):
            try:
                cap = Capability(cap)
            except ValueError:
                logger.warning("smart_complete: unknown capability %r", cap)
                return None

        ctx = context or RouteContext()

        call_params: dict[str, Any] = {"prompt": prompt}
        if system:
            call_params["system"] = system
        call_params.update(params)

        try:
            return self._llm_router.execute(cap, call_params, ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("smart_complete: router raised %s", exc)
            return None

    def has_smart_router(self) -> bool:
        """Return True iff the brain has a usable adapter
        SmartRouter wired up. Useful for tests + observability."""
        return self._llm_router is not None

    # ── Main thinking process ────────────────────────────────

    def think(
        self,
        store_data: dict[str, Any],
        goal: str | None = None,
    ) -> dict[str, Any]:
        """Main thinking process — observe, understand, decide, plan.

        This is called each cycle. The brain:
          1. Observes current state
          2. Identifies problems and opportunities
          3. Considers past experience
          4. Decides what to focus on (GOAL-AWARE)
          5. Creates a priority action plan

        Args:
            store_data: Per-cycle store snapshot (products,
                orders, customers, ...) the brain will reason
                about.
            goal: Optional strategic goal selected by
                ``GoalManager`` — one of ``"survive_crisis"``,
                ``"grow_customers"``, ``"capture_opportunity"``,
                ``"increase_aov"``, ``"maximize_profit"``. When
                provided the brain re-ranks decisions using the
                goal weights defined in ``_GOAL_ACTION_WEIGHTS``
                so pricing / product / marketing actions reflect
                the current business priority instead of being
                evaluated in isolation. Pre-fix the brain took
                NO goal parameter and the GoalManager's output
                was dead code within the autonomous cycle.
                Defaults to ``None`` (ranks by severity alone)
                for backwards compatibility.
        """
        self._init_components()
        start = time.monotonic()

        state = StoreState(store_data)
        # Normalise the goal — strip whitespace and reject
        # unknown values so downstream scoring can trust the
        # key. Unknown goals fall back to the weight-free path.
        normalised_goal = (
            goal.strip().lower() if isinstance(goal, str) and goal.strip() else None
        )
        if normalised_goal is not None and normalised_goal not in _GOAL_ACTION_WEIGHTS:
            logger.debug(
                "think: unknown goal %r, falling back to severity-only ranking",
                goal,
            )
            normalised_goal = None

        thought: dict[str, Any] = {
            "timestamp": time.time(),
            "state": state.summary(),
            "goal": normalised_goal or "",
            "observations": [],
            "problems": [],
            "opportunities": [],
            "decisions": [],
            "action_plan": [],
        }

        # Step 0: INGEST — feed data into memory (skip if recently ingested)
        sid = store_data.get("store_id", "")
        _ingest_key = f"_ingested_{sid}_{len(state.products)}"
        if not hasattr(self, "_last_ingest") or self._last_ingest != _ingest_key:
            self._last_ingest = _ingest_key
            if self._brain_memory:
                for p in state.products:
                    self._brain_memory.ingest("product", p, source="cycle", store_id=sid)
                for o in state.orders:
                    self._brain_memory.ingest("order", o, source="cycle")
                for c in state.customers:
                    self._brain_memory.ingest("customer", c, source="cycle")
            if hasattr(self, "_data_arch") and self._data_arch:
                for p in state.products:
                    self._data_arch.capture("product", p, source="brain_cycle", store_id=sid)

        # Step 1: OBSERVE — what's happening?
        observations = self._observe(state)
        thought["observations"] = observations

        # Step 2: DIAGNOSE — what problems exist?
        problems = self._diagnose(state, observations)
        thought["problems"] = problems

        # Step 3: FIND OPPORTUNITIES
        opportunities = self._find_opportunities(state)
        thought["opportunities"] = opportunities

        # Step 4: CONSULT EXPERIENCE — what worked before?
        experience_advice = self._consult_experience(state, problems, opportunities)
        thought["experience"] = experience_advice

        # Step 5: DECIDE — what to do? (uses DecisionEngine + memory)
        decisions = self._decide(
            state, problems, opportunities, experience_advice,
            goal=normalised_goal,
        )

        # Step 5a: Structured decisions via DecisionEngine (top 2 for speed)
        if self._decision_engine:
            for p in state.products[:2]:
                structured = self._decision_engine.decide("pricing", p)
                if structured.choice != "no_action":
                    thought.setdefault("structured_decisions", []).append(structured.to_dict())

        # Fix G note (core audit #5): pre-fix Step 5c here
        # instantiated a ``ModelCoordinator`` fresh every cycle
        # and called ``pricing_decision(top_product)``, which
        # fired a legacy LLM (``core.system.llm_adapter``)
        # request and dropped the JSON response onto
        # ``thought["model_coordinator"]``. That key was never
        # read anywhere in the codebase — grep(thought
        # \\[.model_coordinator.\\]) returned exactly ONE hit,
        # the write site itself.
        #
        # The pricing decision already goes through
        # ``DecisionEngine.decide("pricing", p)`` above, which
        # is deterministic, memory-informed, rule-aware, and
        # now learning-aware (Fix C). The ModelCoordinator
        # call was:
        #
        #   * wasteful — burned a ~1-5s LLM request per cycle
        #     with no downstream consumer
        #   * non-deterministic — two cycles on the same data
        #     could produce different recommendations
        #   * competing — produced a pricing opinion that did
        #     not reconcile with the DecisionEngine output
        #   * legacy — bypassed the Phase 1 adapter
        #     ``SmartRouter`` entirely
        #
        # Removed. ``ModelCoordinator`` the class itself is
        # still used by ``tests/test_multi_model.py`` for
        # testing multi-role LLM orchestration, so the file
        # stays. New brain code that wants LLM input should
        # use ``self.smart_complete(...)`` which routes
        # through the adapter SmartRouter.

        # Step 5b: VALIDATE — remove bad decisions
        decisions = self._validate_decisions(decisions, state)
        thought["decisions"] = decisions

        # Step 6: PLAN — in what order?
        action_plan = self._create_action_plan(decisions)
        thought["action_plan"] = action_plan

        # Step 7: Think with LLM if available (deep reasoning).
        #
        # Pre-fix this gate was ``if self._llm and ...`` which made
        # the adapter SmartRouter path in ``_deep_think`` completely
        # unreachable — the router-only case (legacy llm absent,
        # adapters configured) was impossible to hit. Smoke run on
        # the ``test`` store confirmed ``ai_reasoning`` was never
        # populated even with a live router. Accept EITHER the
        # legacy ``self._llm`` OR the adapter router; the inner
        # method already handles both paths with fallback.
        if (self._llm or self._llm_router) and (problems or opportunities):
            ai_thought = self._deep_think(state, problems, opportunities)
            thought["ai_reasoning"] = ai_thought

        thought["duration_s"] = round(time.monotonic() - start, 3)
        thought["health_score"] = state.health_score

        # Store in memory
        if self._memory:
            self._memory.record_decision(f"brain_{int(time.time())}", thought)

        # Store in MemoryIntelligence (4-level hierarchy)
        if hasattr(self, "_memory_intel") and self._memory_intel:
            self._memory_intel.create(
                category="brain_thought",
                content={"problems": len(problems), "opportunities": len(opportunities),
                         "decisions": len(decisions), "health_score": state.health_score},
                action=action_plan[0]["action"] if action_plan else "none",
                result={"action_plan_size": len(action_plan)},
                score=min(5.0, state.health_score / 20.0),  # health 0-100 → score 0-5
                memory_type="episodic",
                tags=["brain_cycle", f"health:{state.health_score}"],
            )

        self._decision_history.append(thought)
        if len(self._decision_history) > 50:
            self._decision_history = self._decision_history[-50:]

        return thought

    # ── Step 1: Observe ──────────────────────────────────────

    def _observe(self, state: StoreState) -> list[dict[str, Any]]:
        """What's happening in the store right now?"""
        obs = []

        obs.append({
            "type": "store_size",
            "detail": f"{state.product_count} products, {state.order_count} orders, {len(state.customers)} customers",
            "severity": "critical" if state.product_count < 5 else "info",
        })

        if state.avg_margin > 0:
            obs.append({
                "type": "margin",
                "detail": f"Average margin: {state.avg_margin:.0%}",
                "severity": "good" if state.avg_margin > 0.5 else "warning" if state.avg_margin > 0.3 else "critical",
            })

        if state.out_of_stock:
            names = [p.get("name", "?")[:30] for p in state.out_of_stock]
            obs.append({
                "type": "stockout",
                "detail": f"{len(state.out_of_stock)} products out of stock: {', '.join(names)}",
                "severity": "critical",
            })

        if state.low_stock:
            obs.append({
                "type": "low_stock",
                "detail": f"{len(state.low_stock)} products running low on stock",
                "severity": "warning",
            })

        if state.order_count == 0:
            obs.append({
                "type": "no_sales",
                "detail": "No orders yet — store needs traffic and marketing",
                "severity": "critical",
            })

        return obs

    # ── Step 2: Diagnose Problems ────────────────────────────

    def _diagnose(self, state: StoreState, observations: list) -> list[dict[str, Any]]:
        """What problems need fixing?"""
        problems = []

        # Critical: too few products
        if state.product_count < 10:
            problems.append({
                "type": "insufficient_products",
                "severity": "high",
                "detail": f"Only {state.product_count} products. Need 10+ for a credible store.",
                "action": "add_products",
                "impact": "high",
            })

        # Critical: no sales
        if state.order_count == 0:
            problems.append({
                "type": "no_revenue",
                "severity": "critical",
                "detail": "Zero orders. Need marketing, traffic, or better products.",
                "action": "marketing_push",
                "impact": "critical",
            })

        # Missing product data
        no_cost = [p for p in state.products if float(p.get("cost", 0) or 0) == 0]
        if no_cost:
            problems.append({
                "type": "missing_costs",
                "severity": "medium",
                "detail": f"{len(no_cost)} products have no cost data — can't optimize pricing",
                "action": "update_costs",
                "impact": "medium",
            })

        no_images = [p for p in state.products if not p.get("image_url")]
        if no_images:
            problems.append({
                "type": "missing_images",
                "severity": "high",
                "detail": f"{len(no_images)} products have no images — hurts conversion",
                "action": "add_images",
                "impact": "high",
            })

        # Low margins
        for p in state.products:
            m = _margin(p.get("price", 0), p.get("cost", 0), default=-1.0)
            if 0 <= m < 0.3:
                problems.append({
                    "type": "low_margin",
                    "severity": "medium",
                    "detail": f"{p.get('name', '?')[:30]} has {m:.0%} margin (below 30%)",
                    "action": "raise_price",
                    "product": p.get("name", ""),
                    "impact": "medium",
                })

        return problems

    # ── Step 3: Find Opportunities ───────────────────────────

    def _find_opportunities(self, state: StoreState) -> list[dict[str, Any]]:
        """What opportunities exist?"""
        opportunities = []

        # High margin products to promote
        stars = []
        for p in state.products:
            if _margin(p.get("price", 0), p.get("cost", 0)) > 0.6:
                stars.append(p)

        if stars:
            names = [p.get("name", "?")[:25] for p in stars[:3]]
            opportunities.append({
                "type": "promote_high_margin",
                "detail": f"{len(stars)} products with 60%+ margin — promote aggressively",
                "products": names,
                "impact": "high",
            })

        # Bundle opportunity
        if state.product_count >= 3:
            opportunities.append({
                "type": "create_bundles",
                "detail": "Create product bundles to increase average order value",
                "impact": "medium",
            })

        # Cross-sell
        categories = set(p.get("category", "") for p in state.products if p.get("category"))
        if len(categories) > 1:
            opportunities.append({
                "type": "cross_sell",
                "detail": f"Products span {len(categories)} categories — cross-sell potential",
                "impact": "medium",
            })

        # Upsell
        prices = sorted([float(p.get("price", 0) or 0) for p in state.products if float(p.get("price", 0) or 0) > 0])
        if prices and prices[-1] < 50:
            opportunities.append({
                "type": "add_premium",
                "detail": f"Highest price is ${prices[-1]:.2f}. Add premium products ($50+) for higher AOV.",
                "impact": "medium",
            })

        return opportunities

    # ── Step 4: Consult Experience ───────────────────────────

    def _consult_experience(self, state: StoreState, problems: list,
                           opportunities: list) -> dict[str, Any]:
        """What does past experience tell us?"""
        advice: dict[str, Any] = {"past_decisions": 0, "relevant_strategies": []}

        if self._experience:
            summary = self._experience.get_knowledge_summary()
            advice["past_decisions"] = summary.get("decisions_recorded", 0)
            advice["success_rate"] = summary.get("overall_success_rate", 0)

            # Get relevant strategies
            for problem in problems:
                action = problem.get("action", "")
                strategies = self._experience.get_best_strategies(action, limit=2)
                for s in strategies:
                    advice["relevant_strategies"].append({
                        "for": action,
                        "strategy": s.get("strategy", "")[:100],
                        "effectiveness": s.get("effectiveness", 0),
                    })

            # Get mistakes to avoid
            mistakes = self._experience.get_mistakes(limit=5)
            advice["avoid"] = [m["description"][:80] for m in mistakes[:3]]

        if self._skills:
            # Get best skills for current situation
            context = {
                "need_new_products": state.product_count < 10,
                "have_products": state.product_count > 0,
                "slow_sales": state.order_count < 5,
                "have_customers": len(state.customers) > 0,
            }
            top_skills = []
            for cat in ["pricing", "product", "marketing"]:
                best = self._skills.get_best_skills(cat, context, limit=1)
                if best:
                    top_skills.append({"skill": best[0].name, "score": best[0].score})
            advice["recommended_skills"] = top_skills

        return advice

    # ── Step 5: Decide ───────────────────────────────────────

    def _decide(
        self,
        state: StoreState,
        problems: list,
        opportunities: list,
        experience: dict,
        *,
        goal: str | None = None,
    ) -> list[dict[str, Any]]:
        """Make decisions — what to do, in priority order.

        When ``goal`` is supplied (and known to
        ``_GOAL_ACTION_WEIGHTS``), each candidate's score is
        multiplied by the goal-specific weight so the final
        ranking reflects the store's current strategic goal.
        Unknown / missing goals fall back to the severity-only
        ranking that existed before Fix A.
        """
        decisions = []

        # Priority 1: Fix critical problems
        critical = [p for p in problems if p.get("severity") == "critical"]
        for p in critical:
            decisions.append({
                "priority": 1,
                "type": p["action"],
                "reason": p["detail"],
                "confidence": 0.9,
                "worldview": self._relevant_belief(p["action"]),
                "_priority_source": "critical_problem",
            })

        # Priority 2: Fix high severity problems
        high = [p for p in problems if p.get("severity") == "high"]
        for p in high:
            decisions.append({
                "priority": 2,
                "type": p["action"],
                "reason": p["detail"],
                "confidence": 0.8,
                "worldview": self._relevant_belief(p["action"]),
                "_priority_source": "high_severity_problem",
            })

        # Priority 3: Pursue high-impact opportunities
        for opp in opportunities:
            if opp.get("impact") == "high":
                decisions.append({
                    "priority": 3,
                    "type": opp["type"],
                    "reason": opp["detail"],
                    "confidence": 0.7,
                    "_priority_source": "high_impact_opportunity",
                })

        # Priority 4: Medium improvements
        medium = [p for p in problems if p.get("severity") == "medium"]
        for p in medium[:3]:
            decisions.append({
                "priority": 4,
                "type": p["action"],
                "reason": p["detail"],
                "confidence": 0.6,
                "_priority_source": "medium_improvement",
            })

        # Lower priority number → higher base score, then
        # modulated by the active goal's per-action weight.
        weight_table = _GOAL_ACTION_WEIGHTS.get(goal or "", {}) if goal else {}

        _priority_descriptions = {
            "critical_problem": "critical-severity problem requires immediate action (priority 1)",
            "high_severity_problem": "high-severity problem (priority 2)",
            "high_impact_opportunity": "high-impact opportunity (priority 3)",
            "medium_improvement": "medium-severity improvement (priority 4)",
        }

        exp = experience if isinstance(experience, dict) else {}
        relevant_strategies = exp.get("relevant_strategies", [])
        avoid_list = exp.get("avoid", [])

        # Index strategies by action for O(1) per-decision lookup
        strategy_by_action: dict[str, list[float]] = {}
        for s in relevant_strategies:
            if not isinstance(s, dict):
                continue
            action = str(s.get("for", ""))
            if not action:
                continue
            strategy_by_action.setdefault(action, []).append(
                safe_float(s.get("effectiveness")),
            )

        def _attribute(
            trail: list[dict[str, Any]],
            *,
            source: str,
            rule_id: str,
            description: str,
            impact: float,
        ) -> None:
            trail.append({
                "source": source,
                "rule_id": rule_id,
                "description": description,
                "impact": round(impact, 3),
            })

        for d in decisions:
            base_score = 5.0 - float(d.get("priority", 5))  # 4.0..1.0
            weight = float(weight_table.get(d.get("type", ""), 1.0))
            action_type = str(d.get("type", ""))

            # Experience multiplier: avg strategy effectiveness in
            # [0,1] maps to [0.6, 1.4] so bad strategies dampen.
            experience_mult = 1.0
            effectiveness_values = strategy_by_action.get(action_type, [])
            if effectiveness_values:
                avg_eff = sum(effectiveness_values) / len(effectiveness_values)
                experience_mult = 0.6 + 0.8 * max(0.0, min(1.0, avg_eff))

            # Any "avoid" entry mentioning the action → 0.8x dampener.
            mistake_hits = [
                m for m in avoid_list
                if isinstance(m, str) and action_type and action_type in m
            ]
            mistake_mult = 0.8 if mistake_hits else 1.0

            d["score"] = round(
                base_score * weight * experience_mult * mistake_mult, 3,
            )
            d["goal_weight"] = weight
            d["experience_mult"] = round(experience_mult, 3)
            if goal:
                d["goal"] = goal

            attribution: list[dict[str, Any]] = []

            priority_source = d.pop("_priority_source", "")
            if priority_source:
                _attribute(
                    attribution,
                    source="priority_rule",
                    rule_id=f"priority:{priority_source}",
                    description=_priority_descriptions.get(
                        priority_source, priority_source,
                    ),
                    impact=base_score,
                )

            if goal and abs(weight - 1.0) > 1e-9:
                direction = "boosts" if weight > 1.0 else "suppresses"
                _attribute(
                    attribution,
                    source="goal_weight",
                    rule_id=f"goal:{goal}:{action_type}",
                    description=(
                        f"goal '{goal}' {direction} {action_type} "
                        f"by {weight:.2f}x"
                    ),
                    impact=base_score * (weight - 1.0),
                )

            if effectiveness_values and abs(experience_mult - 1.0) > 1e-9:
                avg_eff = sum(effectiveness_values) / len(effectiveness_values)
                direction = "boosts" if experience_mult > 1.0 else "dampens"
                n = len(effectiveness_values)
                noun = "strategy" if n == 1 else "strategies"
                _attribute(
                    attribution,
                    source="experience_strategy",
                    rule_id=f"experience:{action_type}",
                    description=(
                        f"past experience {direction} {action_type} "
                        f"(avg effectiveness {avg_eff:.2f} from {n} {noun})"
                    ),
                    impact=base_score * weight * (experience_mult - 1.0),
                )

            if mistake_hits:
                _attribute(
                    attribution,
                    source="experience_mistake",
                    rule_id=f"mistake:{action_type}",
                    description=(
                        f"past mistake involving {action_type}: "
                        f"{mistake_hits[0][:80]}"
                    ),
                    impact=base_score * weight * experience_mult * (mistake_mult - 1.0),
                )

            d["attribution"] = attribution

        # Sort by score DESC (tiebreak by original priority
        # ascending for deterministic order when goals don't
        # distinguish two decisions).
        return sorted(
            decisions,
            key=lambda d: (-d["score"], d["priority"]),
        )

    # ── Step 5b: Validate Decisions ─────────────────────────

    def _validate_decisions(self, decisions: list, state: StoreState) -> list[dict[str, Any]]:
        """Brain reviews its own decisions before acting. Removes bad ideas."""
        validated = []
        for dec in decisions:
            action = dec.get("type", "")

            # DON'T lower prices when there are zero orders
            # Lowering prices without data = losing margin for nothing
            if action == "lower_price" and state.order_count == 0:
                logger.info("Brain rejected: lower_price with 0 orders (no data to justify)")
                continue

            # DON'T make pricing changes without competitor data
            if action in ("raise_price", "lower_price") and not dec.get("has_competitor_data"):
                dec["confidence"] = min(dec.get("confidence", 0.5), 0.4)
                dec["reason"] = dec.get("reason", "") + " [low confidence: no competitor data]"

            # DON'T add more products if current ones have no images
            if action == "add_products" and state.product_count >= 10:
                # Check if existing products are well-set-up first
                no_images = sum(1 for p in state.products if not p.get("image_url"))
                if no_images > state.product_count * 0.5:
                    dec["reason"] = f"Add products BUT fix images first ({no_images}/{state.product_count} have no images)"

            validated.append(dec)
        return validated

    # ── Step 6: Action Plan ──────────────────────────────────

    def _create_action_plan(self, decisions: list) -> list[dict[str, Any]]:
        """Convert decisions into ordered action plan."""
        plan = []
        for i, dec in enumerate(decisions[:10]):
            plan.append({
                "step": i + 1,
                "action": dec["type"],
                "reason": dec["reason"][:100],
                "priority": dec["priority"],
                "confidence": dec.get("confidence", 0.5),
            })
        return plan

    # ── Step 7: Deep Think (LLM) ─────────────────────────────

    def _deep_think(self, state: StoreState, problems: list,
                    opportunities: list) -> dict[str, Any]:
        """Use an LLM for deeper strategic reasoning.

        Two execution paths in priority order:

        1. **Adapter SmartRouter** (preferred). Routes the prompt
           through the Phase 1 LLM adapter ecosystem with
           ``Capability.REASON_DEEP`` so the router picks the
           best reasoning model among Groq / DeepSeek / Gemini /
           Mistral / Ollama / OpenRouter / HuggingFace, with
           automatic fallback on failure.

        2. **Legacy ``self._llm.ask()``** (fallback). Used when
           the adapter layer is not initialised, when the router
           returns ``NoAdapterAvailable`` (no configured adapter
           supports REASON_DEEP), or when the router run fails
           outright. Keeping the legacy path means this method
           still works in environments where adapters are not
           wired up yet.

        Returns ``{"available": False}`` only if BOTH paths fail.
        """
        # If neither path is available, bail early.
        if not self._llm and not self._llm_router:
            return {"available": False}

        summary = state.summary()
        prob_text = "\n".join(f"- [{p['severity']}] {p['detail']}" for p in problems[:5])
        opp_text = "\n".join(f"- {o['detail']}" for o in opportunities[:5])

        prompt = f"""You are an expert e-commerce strategist managing a dropshipping store.

STORE STATE:
- {summary['products']} products, {summary['orders']} orders, {summary['customers']} customers
- Average margin: {summary['avg_margin']:.0%}, Revenue: ${summary['revenue']}
- Health score: {summary['health_score']}/100

PROBLEMS:
{prob_text or 'None critical'}

OPPORTUNITIES:
{opp_text or 'None identified'}

What are the TOP 3 things this store should do RIGHT NOW? Be specific and actionable.
Respond in JSON: {{"top_actions": [{{"action": "...", "reason": "...", "expected_impact": "..."}}]}}"""

        # ── Path 1: Adapter SmartRouter ──
        if self._llm_router:
            try:
                from core.adapters import Capability
                result = self.smart_complete(
                    prompt,
                    capability=Capability.REASON_DEEP,
                    system="You are a strategic e-commerce reasoning engine. Reply ONLY with the requested JSON.",
                )
                if result is not None and result.ok:
                    text = result.data.get("text", "")
                    parsed = self._try_parse_json(text)
                    return {
                        "available": True,
                        "reasoning": parsed if parsed is not None else {"raw": text},
                        "model": result.model or result.adapter,
                        "adapter": result.adapter,
                        "tokens_in": result.tokens_in,
                        "tokens_out": result.tokens_out,
                        "via": "smart_router",
                    }
                if result is not None and not result.ok and result.error is not None:
                    logger.debug(
                        "smart router deep_think failed (%s), falling back to legacy LLM",
                        type(result.error).__name__,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug("smart router deep_think raised: %s", exc)

        # ── Path 2: Legacy LLM ──
        if self._llm:
            try:
                response = self._llm.ask("analyzer", prompt)
                if response.success:
                    return {
                        "available": True,
                        "reasoning": response.parse_json(),
                        "model": response.model,
                        "via": "legacy_llm",
                    }
            except Exception as exc:
                logger.debug("LLM deep think: %s", exc)

        return {"available": False}

    @staticmethod
    def _try_parse_json(text: str) -> Any:
        """Best-effort JSON parser used by ``_deep_think`` to
        normalise the router's text response into the same
        structure the legacy ``response.parse_json()`` would
        produce. Returns ``None`` on failure so the caller can
        fall back to the raw text payload."""
        if not text:
            return None
        import json as _json

        # Strip Markdown code fences if the model wrapped the
        # JSON in ```json ... ``` (Gemini and DeepSeek both do
        # this when the system prompt asks for JSON).
        stripped = text.strip()
        if stripped.startswith("```"):
            # Drop the first fence line and the trailing fence
            lines = stripped.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()

        try:
            return _json.loads(stripped)
        except (ValueError, TypeError):
            return None

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _relevant_belief(action: str) -> str:
        """Get the most relevant worldview belief for an action."""
        mapping = {
            "add_products": WORLDVIEW["simplicity_scales"],
            "marketing_push": WORLDVIEW["speed_wins"],
            "raise_price": WORLDVIEW["profit_first"],
            "update_costs": WORLDVIEW["profit_first"],
            "add_images": WORLDVIEW["test_everything"],
            "promote_high_margin": WORLDVIEW["double_down_winners"],
            "restock": WORLDVIEW["cash_flow_is_king"],
        }
        return mapping.get(action, WORLDVIEW["speed_wins"])

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._decision_history[-limit:]
