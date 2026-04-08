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

# Upper bound on the post-weight final score. The scoring
# math clamps the base to [0.05, 1.0] and then multiplies by
# a learned weight in [0.1, 2.0], so in the extreme a strong
# option with a fully-learned 2.0 weight lands at 2.0. We
# keep the cap at 2.0 so downstream consumers can tell that
# the score is a "learned-boosted" value without the old
# 0..1 ceiling silently truncating learning.
_MAX_FINAL_SCORE = 2.0


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
    """Structured decision maker — always uses memory.

    Since the Fix C learning-loop closure, the engine also
    consults an ``ActionWeightStore`` when ranking options.
    Every ``record_outcome`` call updates the store with an
    exponential moving average of the outcome score, and every
    subsequent ``decide`` multiplies each option's final score
    by the learned weight for its ``(category, action)`` pair.
    Over time consistently successful actions rise in the
    ranking and consistently failing ones sink — the brain
    actually learns from its history instead of recording
    outcomes into a black hole.
    """

    def __init__(self) -> None:
        self._memory = None
        self._memory_intel = None
        self._data_arch = None
        self._decisions_made = 0
        self._weights = None  # lazy-loaded ActionWeightStore

    def _get_memory(self):
        """Lazily fetch the 6-layer ``IntelligentMemory``
        backend via the ``UnifiedMemory`` entry point.

        Pre-fix this imported ``core.brain.memory.get_brain_memory``
        directly, bypassing ``UnifiedMemory``. The audit
        flagged that as the #2 CRITICAL weakness: two
        parallel SQLite DBs with no single owner. Fix D
        routes through ``UnifiedMemory.get_brain_memory()``
        so all brain code shares one entry point.

        Raises ``RuntimeError`` if the unified memory backend
        cannot provide a brain memory instance — the
        DecisionEngine REQUIRES memory to function, same
        semantics as the pre-fix direct import which would
        raise ImportError.
        """
        if self._memory:
            return self._memory
        try:
            from core.memory.unified_memory import get_unified_memory
            self._memory = get_unified_memory().get_brain_memory()
        except Exception as exc:  # noqa: BLE001
            logger.warning("brain memory load failed: %s", exc)
            self._memory = None
        if self._memory is None:
            raise RuntimeError(
                "DecisionEngine requires IntelligentMemory — "
                "UnifiedMemory.get_brain_memory() returned None",
            )
        return self._memory

    def _get_intelligence(self):
        """Lazily fetch the 4-level ``MemoryIntelligence``
        backend via ``UnifiedMemory``. Same rationale as
        ``_get_memory``."""
        if not self._memory_intel:
            try:
                from core.memory.unified_memory import get_unified_memory
                self._memory_intel = get_unified_memory().get_memory_intelligence()
            except Exception as exc:  # noqa: BLE001
                logger.debug("memory intelligence load failed: %s", exc)
        if not self._data_arch:
            try:
                from core.data.architecture import get_data_architecture
                self._data_arch = get_data_architecture()
            except Exception:
                pass
        return self._memory_intel

    def _get_weights(self):
        """Lazy-load the process-wide ``ActionWeightStore``.

        Fix C: closes the learning loop. Every ``decide`` call
        consults the store to boost / suppress options based
        on past outcomes, and every ``record_outcome`` call
        updates the store with an EMA of the outcome score.
        Import is deferred so a broken ``core.learning``
        package can't take down decision making.
        """
        if not self._weights:
            try:
                from core.learning.action_weights import get_action_weight_store
                self._weights = get_action_weight_store()
            except Exception as exc:  # noqa: BLE001
                logger.debug("weights store init failed: %s", exc)
                self._weights = None
        return self._weights

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
        mi = self._get_intelligence()

        # Step 1: CONTEXT — retrieve from both memory systems
        context = mem.retrieve_for_decision(category, input_data)

        # Enhance with 4-level intelligence (patterns, rules, strategies)
        if mi:
            intel = mi.retrieve_for_decision(category)
            context["intel_rules"] = intel.get("rules", [])
            context["intel_strategies"] = intel.get("strategies", [])
            context["intel_patterns"] = intel.get("patterns", [])
            context["total_memories"] = max(
                context.get("total_memories", 0), intel.get("total_memories", 0),
            )

        # Step 2: OPTIONS — generate or use provided
        if not options:
            options = self._generate_options(category, input_data, context)

        if not options:
            return Decision("no_action", "No viable options found", 0.2, category)

        # Step 3: SCORE each option (goal-aware + weight-aware)
        scored = self._score_options(
            options, context, input_data, category=category,
        )

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

        # Step 6: Record in memory (both systems)
        # Memory score = data quality, NOT decision confidence
        mem_score = 3.0  # Base: valid decision
        if decision.memory_used:
            mem_score += 0.5  # Memory-informed = better quality
        if decision.options_considered >= 3:
            mem_score += 0.3  # More options considered
        if decision.rules_applied:
            mem_score += 0.2  # Rules applied
        mem_score = min(5.0, mem_score)

        mem.record_decision(
            category=category,
            input_data=input_data,
            action=decision.choice,
            result={},  # Will be updated after execution
            score=mem_score,
            tags=[category, decision.choice],
        )

        # Record in MemoryIntelligence (4-level, with promotion checks)
        if mi:
            mi.create_from_decision(
                category=category,
                input_data=input_data,
                action=decision.choice,
                result={},
                score=mem_score,
                tags=[category, decision.choice],
            )

        # Capture in DataArchitecture (12-domain)
        if self._data_arch:
            self._data_arch.capture(
                domain="decision",
                data={
                    "choice": decision.choice,
                    "category": category,
                    "confidence": decision.score,
                    "options_considered": decision.options_considered,
                    "memory_used": decision.memory_used,
                    "rules_applied": len(decision.rules_applied),
                },
                source="decision_engine",
                score=mem_score,
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
            from utils.finance import margin as _margin
            margin = _margin(price, cost)

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

    def _score_options(
        self,
        options: list[dict],
        context: dict,
        input_data: dict,
        *,
        category: str = "",
    ) -> list[dict[str, Any]]:
        """Score each option using profit, risk, past
        performance, and the learned action-weight store.

        The final score is:

            base = 0.3 + profit*0.4 - risk*0.2
                   + memory_boost - memory_penalty + rule_boost
            clamped to [0.05, 1.0]
            final = clamped * learned_weight

        Where ``learned_weight`` comes from ``ActionWeightStore``
        and starts at the neutral 1.0 for unknown
        ``(category, action)`` pairs. As outcomes accumulate
        the weight drifts toward the EMA of the observed
        scores, boosting consistently successful actions and
        suppressing consistently failing ones.
        """
        scored = []
        best_cases = context.get("best_cases", [])
        failures = context.get("failures", [])
        rules = context.get("rules", [])
        weight_store = self._get_weights()

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

            # Rule application (from IntelligentMemory L5)
            rule_boost = 0
            for rule in rules:
                if rule.get("action") == "prefer" and opt.get("action") in rule.get("condition", ""):
                    rule_boost += rule.get("confidence", 0) * 0.1
                elif rule.get("action") == "avoid" and opt.get("action") in rule.get("condition", ""):
                    rule_boost -= rule.get("confidence", 0) * 0.1

            # Intelligence rules (from MemoryIntelligence L2)
            for irule in context.get("intel_rules", []):
                rc = irule.get("content", {})
                if not isinstance(rc, dict):
                    continue
                recommended = rc.get("recommended_action", irule.get("action", ""))
                if recommended == "prefer":
                    rule_boost += irule.get("confidence", 0.5) * 0.15
                elif recommended == "avoid":
                    rule_boost -= irule.get("confidence", 0.5) * 0.15

            # Final score: base 0.3 + profit-weighted + risk penalty + memory + rules
            base_score = 0.3 + profit * 0.4 - risk * 0.2 + memory_boost - memory_penalty + rule_boost
            base_score = max(0.05, min(1.0, base_score))

            # Fix C: apply learned weight from outcome history.
            # Unknown pairs get 1.0 (neutral). Consistently
            # good outcomes drift the weight toward 2.0;
            # consistent failures toward 0.0.
            learned_weight = 1.0
            if weight_store is not None:
                try:
                    learned_weight = float(
                        weight_store.get(category, str(opt.get("action", ""))),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("weight lookup failed: %s", exc)
                    learned_weight = 1.0

            final = base_score * learned_weight
            # Upper bound stays at the old 1.0 cap for
            # downstream consumers that expect a 0..1 score.
            # We deliberately let the weight lift a strong
            # option above the old cap to signal "this is
            # outperforming"; lower bound stays at 0.05 so
            # nothing silently becomes exactly 0.
            final = max(0.05, min(_MAX_FINAL_SCORE, final))

            scored.append({
                **opt,
                "final_score": round(final, 3),
                "base_score": round(base_score, 3),
                "learned_weight": round(learned_weight, 4),
                "memory_boost": memory_boost,
                "memory_penalty": memory_penalty,
                "rule_boost": round(rule_boost, 3),
            })

        return scored

    # ── Update After Execution ───────────────────────────────

    def record_outcome(self, category: str, action: str, input_data: dict,
                       result: dict, score: float) -> None:
        """Record the real outcome of a decision for future learning.

        Fix C: every outcome now also updates the
        ``ActionWeightStore`` EMA so the next ``decide`` call
        in the same category will consult the learned weight
        when scoring options. This closes the decision →
        action → outcome → memory → next decision loop that
        was broken pre-fix (weights were counted but never
        written anywhere queries could reach).
        """
        # Close the learning loop: update the weight store
        # BEFORE writing memory, so even if memory write
        # fails the weight update survives.
        weight_store = self._get_weights()
        if weight_store is not None and category and action:
            try:
                weight_store.record(category, action, score)
            except Exception as exc:  # noqa: BLE001
                logger.debug("weight store record failed: %s", exc)

        mem = self._get_memory()
        mem.record_decision(
            category=category,
            input_data=input_data,
            action=action,
            result=result,
            score=score,
            tags=[category, action, "outcome"],
        )

        # Record in MemoryIntelligence with full result
        mi = self._get_intelligence()
        if mi:
            mi.create_from_decision(
                category=category,
                input_data=input_data,
                action=action,
                result=result,
                score=score,
                tags=[category, action, "outcome"],
            )
            # Failures are gold
            if score <= 2.0:
                root_cause = result.get("error", result.get("reason", ""))
                mi.record_failure(
                    category=category,
                    failure_data={"action": action, "input": input_data, "result": result},
                    root_cause=str(root_cause)[:100] if root_cause else "low_score_outcome",
                    severity="critical" if score <= 1.5 else "medium",
                )

        # Track action→result in DataArchitecture
        if self._data_arch:
            action_id = f"de_{category}_{int(time.time())}"
            self._data_arch.record_action(action_id, action, input_data)
            self._data_arch.attach_result(action_id, result, score=score)

    def get_stats(self) -> dict[str, Any]:
        mem = self._get_memory()
        return {
            "decisions_made": self._decisions_made,
            "memory": mem.get_stats(),
        }
