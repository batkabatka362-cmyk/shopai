"""Multi-Store Intelligence — share learning across stores.

When one store learns something, all stores benefit.
Cross-store pattern detection, rule sharing, strategy transfer.
"""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("brain.multi_store")


class MultiStoreIntelligence:
    """Cross-store learning and knowledge sharing."""

    def __init__(self) -> None:
        self._store_knowledge: dict[str, dict] = {}

    def register_store(self, store_id: str, metadata: dict | None = None) -> None:
        """Register a store for cross-store intelligence."""
        self._store_knowledge[store_id] = {
            "registered_at": time.time(),
            "metadata": metadata or {},
            "rules_shared": 0,
            "rules_received": 0,
        }

    def share_learning(self, from_store: str) -> dict[str, Any]:
        """Extract shareable learnings from a store."""
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
        except Exception:
            return {"status": "unavailable"}

        # Get high-confidence rules
        rules = mi.get_rules()
        shareable = []
        for r in rules:
            if r.get("confidence", 0) > 0.6 and r.get("success_count", 0) > 0:
                shareable.append({
                    "category": r.get("category", ""),
                    "content": r.get("content", {}),
                    "confidence": r.get("confidence", 0),
                    "success_rate": r.get("success_count", 0) / max(r.get("use_count", 1), 1),
                    "source_store": from_store,
                })

        # Get strategies
        strategies = mi.get_strategies()
        shareable_strats = []
        for s in strategies:
            shareable_strats.append({
                "category": s.get("category", ""),
                "content": s.get("content", {}),
                "source_store": from_store,
            })

        if from_store in self._store_knowledge:
            self._store_knowledge[from_store]["rules_shared"] = len(shareable)

        return {
            "store": from_store,
            "shareable_rules": len(shareable),
            "shareable_strategies": len(shareable_strats),
            "rules": shareable,
            "strategies": shareable_strats,
        }

    def apply_learning(self, to_store: str, shared: dict) -> dict[str, Any]:
        """Apply shared learning to a target store."""
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
        except Exception:
            return {"status": "unavailable"}

        applied_rules = 0
        for rule in shared.get("rules", []):
            # Create as semantic knowledge (not forced rule)
            mi.create(
                category=rule.get("category", "shared"),
                content={"shared_rule": rule.get("content", {}),
                         "source": rule.get("source_store", ""),
                         "original_confidence": rule.get("confidence", 0)},
                score=3.0,  # Start neutral, let it prove itself
                memory_type="semantic",
                tags=["shared", "cross_store", rule.get("category", "")],
            )
            applied_rules += 1

        if to_store in self._store_knowledge:
            self._store_knowledge[to_store]["rules_received"] = applied_rules

        return {"applied_rules": applied_rules, "target_store": to_store}

    def get_network_stats(self) -> dict[str, Any]:
        return {
            "stores": len(self._store_knowledge),
            "total_shared": sum(s.get("rules_shared", 0) for s in self._store_knowledge.values()),
            "total_received": sum(s.get("rules_received", 0) for s in self._store_knowledge.values()),
        }


_instance = None
def get_multi_store():
    global _instance
    if _instance is None:
        _instance = MultiStoreIntelligence()
    return _instance
