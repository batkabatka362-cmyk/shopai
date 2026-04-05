"""Strategy Expander — generates strategies for uncovered categories.

ADDITIVE ONLY — does not modify existing strategies.
Creates new strategies for categories that lack them.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("brain.strategy_expander")


class StrategyExpander:
    """Expands strategy coverage to uncovered categories."""

    def expand(self) -> dict[str, Any]:
        """Find categories without strategies and create them."""
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
        except Exception:
            return {"status": "unavailable"}

        stats = mi.get_stats()
        all_cats = set(stats.get("by_category", {}).keys())

        # Get categories that already have strategies
        strategies = mi.get_strategies()
        covered = set(s.get("category", "") for s in strategies)

        # Skip working/ephemeral categories
        skip = {"working", "experiment", "cycle"}
        uncovered = all_cats - covered - skip

        if not uncovered:
            return {"status": "all_covered", "categories": len(covered)}

        created = []
        for cat in uncovered:
            # Get rules for this category
            rules = mi.get_rules(cat)
            patterns = mi.get_patterns(cat)

            # Get category stats
            cat_memories = stats.get("by_category", {}).get(cat, 0)
            if cat_memories < 5:
                continue  # Not enough data

            # Build strategy from available rules + patterns
            strategy_actions = []
            if rules:
                for r in rules[:3]:
                    rc = r.get("content", {})
                    if isinstance(rc, dict):
                        strategy_actions.append(rc.get("rule", str(rc)[:60]))

            if not strategy_actions:
                # Generate generic strategy from patterns
                if patterns:
                    for p in patterns[:2]:
                        pc = p.get("content", {})
                        if isinstance(pc, dict):
                            strategy_actions.append(
                                "Pattern: {}".format(pc.get("observation", "")[:60]))

            if not strategy_actions:
                strategy_actions.append(
                    "Monitor {} performance and gather more data".format(cat))

            # Create strategy memory
            avg_score = 3.0
            if rules:
                avg_score = sum(r.get("score", 3.0) for r in rules) / len(rules)

            mi.create_strategy(
                category=cat,
                content={
                    "strategy": "Strategy for {}: {} action items".format(cat, len(strategy_actions)),
                    "rules": strategy_actions,
                    "rule_count": len(rules),
                    "pattern_count": len(patterns),
                    "auto_generated": True,
                },
                score=min(4.5, avg_score + 0.5),
                tags=[cat, "strategy", "auto_expanded"],
            )

            created.append({
                "category": cat,
                "actions": len(strategy_actions),
                "based_on_rules": len(rules),
                "based_on_patterns": len(patterns),
            })

            logger.info("Strategy expanded [%s]: %d actions from %d rules + %d patterns",
                        cat, len(strategy_actions), len(rules), len(patterns))

        return {
            "expanded": len(created),
            "categories_covered_before": len(covered),
            "categories_covered_after": len(covered) + len(created),
            "details": created,
        }


_instance: StrategyExpander | None = None

def get_strategy_expander() -> StrategyExpander:
    global _instance
    if _instance is None:
        _instance = StrategyExpander()
    return _instance
