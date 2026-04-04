"""DecisionEngine — structured decision making with memory.

Every decision follows:
  1. Context build (current input + memory retrieval)
  2. Options generate (possible actions)
  3. Scoring (profit, risk, past performance)
  4. Selection (best option)

1 decision = 1 clear choice + reason + score.
NO random decisions. NO decisions without memory.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("brain.decision_engine")


class Decision:
    """A single structured decision."""

    def __init__(self, choice: str, reason: str, score: float,
                 category: str = "", options_considered: int = 0,
                 memory_used: bool = False, rules_applied: list | None = None) -> None:
        self.choice = choice
        self.reason = reason
        self.score = score  # 0-1 confidence
        self.category = category
        self.options_considered = options_considered
        self.memory_used = memory_used
        self.rules_applied = rules_applied or []
        self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "choice": self.choice, "reason": self.reason,
            "score": round(self.score, 3), "category": self.category,
            "options_considered": self.options_considered,
            "memory_used": self.memory_used,
            "rules_applied": self.rules_applied,
        }


class DecisionEngine:
    """Structured decision maker — always uses memory."""

    def __init__(self) -> None:
        self._memory = None
        self._decisions_made = 0

    def _get_memory(self):
        if not self._memory:
            from core.brain.memory import get_brain_memory
            self._memory = get_brain_memory()
        return self._memory

    # ── Main Decision Process ────────────────────────────────

    def decide(self, category: str, input_data: dict,
               options: list[dict] | None = None) -> Decision:
        """Make a structured decision.

        Args:
            category: Decision type (pricing, product, marketing, etc.)
            input_data: Current situation data
            options: Possible actions (auto-generated if not provided)

        Returns:
            Decision with choice, reason, score
        """
        start = time.monotonic()
        mem = self._get_memory()

        # Step 1: CONTEXT — retrieve relevant memories
        context = mem.retrieve_for_decision(category, input_data)

        # Step 2: OPTIONS — generate or use provided
        if not options:
            options = self._generate_options(category, input_data, context)

        if not options:
            return Decision("no_action", "No viable options found", 0.2, category)

        # Step 3: SCORE each option
        scored = self._score_options(options, context, input_data)

        # Step 4: SELECT best option
        best = max(scored, key=lambda x: x["final_score"])

        # Step 5: Build decision
        rules_applied = [r.get("rule", "")[:60] for r in context.get("rules", [])[:3]]
        decision = Decision(
            choice=best["action"],
            reason=best["reason"],
            score=best["final_score"],
            category=category,
            options_considered=len(options),
            memory_used=context["total_memories"] > 0,
            rules_applied=rules_applied,
        )

        # Step 6: Record in memory
        mem.record_decision(
            category=category,
            input_data=input_data,
            action=decision.choice,
            result={},  # Will be updated after execution
            score=decision.score * 5,  # Convert 0-1 → 1-5
            tags=[category, decision.choice],
        )

        self._decisions_made += 1
        elapsed = time.monotonic() - start
        logger.info("Decision [%s]: %s (score %.2f, %d options, %.3fs)",
                    category, decision.choice, decision.score, len(options), elapsed)

        return decision

    # ── Option Generation ────────────────────────────────────

    def _generate_options(self, category: str, data: dict,
                         context: dict) -> list[dict[str, Any]]:
        """Generate possible actions based on category and context."""
        options = []

        if category == "pricing":
            price = float(data.get("price", 0) or 0)
            cost = float(data.get("cost", 0) or 0)
            margin = (price - cost) / price if price > 0 and cost > 0 else 0

            options.append({
                "action": "keep_price",
                "reason": f"Current price ${price} with {margin:.0%} margin",
                "profit_score": margin,
                "risk_score": 0.1,
            })
            if margin > 0.5:
                lower = round(price * 0.9, 2)
                options.append({
                    "action": "lower_10pct",
                    "reason": f"Lower to ${lower} to increase volume",
                    "profit_score": (lower - cost) / lower if lower > cost else 0,
                    "risk_score": 0.4,
                    "new_price": lower,
                })
            if margin < 0.7:
                higher = round(price * 1.1, 2)
                options.append({
                    "action": "raise_10pct",
                    "reason": f"Raise to ${higher} to increase margin",
                    "profit_score": (higher - cost) / higher if higher > 0 else 0,
                    "risk_score": 0.3,
                    "new_price": higher,
                })

        elif category == "product":
            options.append({"action": "keep", "reason": "Keep current product lineup", "profit_score": 0.5, "risk_score": 0.1})
            options.append({"action": "add_similar", "reason": "Add complementary products", "profit_score": 0.6, "risk_score": 0.3})
            options.append({"action": "remove_underperformer", "reason": "Remove lowest performer", "profit_score": 0.4, "risk_score": 0.2})

        elif category == "marketing":
            options.append({"action": "email_campaign", "reason": "Email existing customers", "profit_score": 0.5, "risk_score": 0.2})
            options.append({"action": "social_media", "reason": "Post on social media", "profit_score": 0.4, "risk_score": 0.1})
            options.append({"action": "paid_ads", "reason": "Run paid advertisements", "profit_score": 0.7, "risk_score": 0.6})

        else:
            options.append({"action": "analyze", "reason": "Gather more data first", "profit_score": 0.3, "risk_score": 0.1})
            options.append({"action": "act", "reason": "Take immediate action", "profit_score": 0.5, "risk_score": 0.4})

        return options

    # ── Option Scoring ───────────────────────────────────────

    def _score_options(self, options: list[dict], context: dict,
                       input_data: dict) -> list[dict[str, Any]]:
        """Score each option using profit, risk, and past performance."""
        scored = []
        best_cases = context.get("best_cases", [])
        failures = context.get("failures", [])
        rules = context.get("rules", [])

        for opt in options:
            profit = float(opt.get("profit_score", 0.5))
            risk = float(opt.get("risk_score", 0.3))

            # Memory boost: if similar action was successful before
            memory_boost = 0
            for case in best_cases:
                if case.get("action") == opt.get("action"):
                    memory_boost += 0.1
                    break

            # Memory penalty: if similar action failed before
            memory_penalty = 0
            for case in failures:
                if case.get("action") == opt.get("action"):
                    memory_penalty += 0.15
                    break

            # Rule application
            rule_boost = 0
            for rule in rules:
                if rule.get("action") == "prefer" and opt.get("action") in rule.get("condition", ""):
                    rule_boost += rule.get("confidence", 0) * 0.1
                elif rule.get("action") == "avoid" and opt.get("action") in rule.get("condition", ""):
                    rule_boost -= rule.get("confidence", 0) * 0.1

            # Final score: profit - risk + memory + rules
            final = profit * 0.5 - risk * 0.3 + memory_boost - memory_penalty + rule_boost
            final = max(0, min(1, final))

            scored.append({
                **opt,
                "final_score": round(final, 3),
                "memory_boost": memory_boost,
                "memory_penalty": memory_penalty,
                "rule_boost": round(rule_boost, 3),
            })

        return scored

    # ── Update After Execution ───────────────────────────────

    def record_outcome(self, category: str, action: str, input_data: dict,
                       result: dict, score: float) -> None:
        """Record the real outcome of a decision for future learning."""
        mem = self._get_memory()
        mem.record_decision(
            category=category,
            input_data=input_data,
            action=action,
            result=result,
            score=score,
            tags=[category, action, "outcome"],
        )

    def get_stats(self) -> dict[str, Any]:
        mem = self._get_memory()
        return {
            "decisions_made": self._decisions_made,
            "memory": mem.get_stats(),
        }
