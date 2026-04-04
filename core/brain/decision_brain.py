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
            price = float(p.get("price", 0) or 0)
            cost = float(p.get("cost", 0) or 0)
            if price > 0 and cost > 0:
                margins.append((price - cost) / price)
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
    """ShopAI's autonomous decision-making core."""

    def __init__(self) -> None:
        self._llm = None
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
        # Connect intelligent memory + decision engine + learning loop
        if not hasattr(self, "_brain_memory") or not self._brain_memory:
            try:
                from core.brain.memory import get_brain_memory
                from core.brain.decision_engine import DecisionEngine
                from core.brain.learning_loop import LearningLoop
                self._brain_memory = get_brain_memory()
                self._decision_engine = DecisionEngine()
                self._learning_loop = LearningLoop()
            except Exception:
                self._brain_memory = None
                self._decision_engine = None
                self._learning_loop = None

    # ── Main thinking process ────────────────────────────────

    def think(self, store_data: dict[str, Any]) -> dict[str, Any]:
        """Main thinking process — observe, understand, decide, plan.

        This is called each cycle. The brain:
          1. Observes current state
          2. Identifies problems and opportunities
          3. Considers past experience
          4. Decides what to focus on
          5. Creates a priority action plan
        """
        self._init_components()
        start = time.monotonic()

        state = StoreState(store_data)
        thought: dict[str, Any] = {
            "timestamp": time.time(),
            "state": state.summary(),
            "observations": [],
            "problems": [],
            "opportunities": [],
            "decisions": [],
            "action_plan": [],
        }

        # Step 0: INGEST — feed all data into intelligent memory
        if self._brain_memory:
            for p in state.products:
                self._brain_memory.ingest("product", p, source="cycle", store_id=store_data.get("store_id", ""))
            for o in state.orders:
                self._brain_memory.ingest("order", o, source="cycle")
            for c in state.customers:
                self._brain_memory.ingest("customer", c, source="cycle")

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
        decisions = self._decide(state, problems, opportunities, experience_advice)

        # Step 5a: Structured decisions via DecisionEngine
        if self._decision_engine:
            for p in state.products[:5]:  # Top 5 products
                structured = self._decision_engine.decide("pricing", p)
                if structured.choice != "no_action":
                    thought.setdefault("structured_decisions", []).append(structured.to_dict())

        # Step 5b: VALIDATE — remove bad decisions
        decisions = self._validate_decisions(decisions, state)
        thought["decisions"] = decisions

        # Step 6: PLAN — in what order?
        action_plan = self._create_action_plan(decisions)
        thought["action_plan"] = action_plan

        # Step 7: Think with LLM if available (deep reasoning)
        if self._llm and (problems or opportunities):
            ai_thought = self._deep_think(state, problems, opportunities)
            thought["ai_reasoning"] = ai_thought

        thought["duration_s"] = round(time.monotonic() - start, 3)
        thought["health_score"] = state.health_score

        # Store in memory
        if self._memory:
            self._memory.record_decision(f"brain_{int(time.time())}", thought)

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
            price = float(p.get("price", 0) or 0)
            cost = float(p.get("cost", 0) or 0)
            if price > 0 and cost > 0 and (price - cost) / price < 0.3:
                problems.append({
                    "type": "low_margin",
                    "severity": "medium",
                    "detail": f"{p.get('name', '?')[:30]} has {(price-cost)/price:.0%} margin (below 30%)",
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
            price = float(p.get("price", 0) or 0)
            cost = float(p.get("cost", 0) or 0)
            if price > 0 and cost > 0 and (price - cost) / price > 0.6:
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

    def _decide(self, state: StoreState, problems: list,
                opportunities: list, experience: dict) -> list[dict[str, Any]]:
        """Make decisions — what to do, in priority order."""
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
            })

        # Priority 3: Pursue high-impact opportunities
        for opp in opportunities:
            if opp.get("impact") == "high":
                decisions.append({
                    "priority": 3,
                    "type": opp["type"],
                    "reason": opp["detail"],
                    "confidence": 0.7,
                })

        # Priority 4: Medium improvements
        medium = [p for p in problems if p.get("severity") == "medium"]
        for p in medium[:3]:
            decisions.append({
                "priority": 4,
                "type": p["action"],
                "reason": p["detail"],
                "confidence": 0.6,
            })

        return sorted(decisions, key=lambda d: d["priority"])

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
        """Use LLM for deeper strategic reasoning."""
        if not self._llm:
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

        try:
            response = self._llm.ask("analyzer", prompt)
            if response.success:
                return {"available": True, "reasoning": response.parse_json(), "model": response.model}
        except Exception as exc:
            logger.debug("LLM deep think: %s", exc)

        return {"available": False}

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
