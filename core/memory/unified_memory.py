"""UnifiedMemory — single entry point for ALL memory in ShopAI.

5 memory backend-ийг нэг interface-ээр удирдана:
  1. SharedMemory (system/shared_memory.py) — live namespace store, TTL
  2. IntelligentMemory (brain/memory.py) — 6-layer, patterns, rules
  3. Experience (ai/experience.py) — permanent knowledge DB
  4. CrossEngineCache (shared_memory/) — engine-to-engine state
  5. PersistentStore (memory/long_term/) — long-term key-value

Data flow:
  ingest() → SharedMemory + IntelligentMemory L0
  retrieve() → IntelligentMemory (best/fail/rules)
  record_decision() → IntelligentMemory L3 + Experience DB
  get_context() → SharedMemory namespace query
  get_rules() → IntelligentMemory L5
  persist() → PersistentStore (long-term)
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("unified_memory")


class UnifiedMemory:
    """Single entry point for ALL memory in ShopAI."""

    def __init__(self) -> None:
        self._shared = None
        self._brain = None
        self._experience = None
        self._cross_cache = None
        self._persistent = None
        self._data_arch = None        # 12-domain data architecture
        self._memory_intel = None     # 4-level memory intelligence
        self._intel_cycle = None      # 10-stage intelligence cycle
        self._initialized = False
        # Per-backend init failure messages, keyed by backend name.
        # Empty dict means everything loaded clean. Operators can
        # introspect this to see which subsystems are missing instead
        # of trying to read between the lines of the status dict.
        self._init_errors: dict[str, str] = {}

    def _try_init(
        self, name: str, loader,
    ) -> bool:
        """Run a backend loader and capture any failure with a real
        traceback log. Returns True iff the loader succeeded.

        Replaces the previous bare ``except Exception: pass`` blocks,
        which silently set every backend to None and left the
        operator with no signal that anything had broken.
        """
        try:
            loader()
            return True
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            self._init_errors[name] = err
            logger.warning(
                "UnifiedMemory: backend %r failed to initialize (%s)",
                name, err,
            )
            return False

    def initialize(self) -> dict[str, bool]:
        """Initialize all memory backends. Lazy — only loads what's available.

        Each backend loader runs inside ``_try_init`` so a single
        broken backend never silently disables observability for the
        rest. Failure messages are captured on ``self._init_errors``
        and logged at WARNING level with full type+message.
        """
        self._init_errors.clear()
        status: dict[str, bool] = {}

        def _load_shared():
            from core.system.shared_memory import get_shared_memory
            self._shared = get_shared_memory()
        status["shared_memory"] = self._try_init("shared_memory", _load_shared)

        def _load_brain():
            from core.brain.memory import get_brain_memory
            self._brain = get_brain_memory()
        status["brain_memory"] = self._try_init("brain_memory", _load_brain)

        def _load_experience():
            from core.ai.experience import get_experience
            self._experience = get_experience()
        status["experience"] = self._try_init("experience", _load_experience)

        def _load_cross_cache():
            from core.shared_memory import CrossEngineCache
            self._cross_cache = CrossEngineCache()
        status["cross_cache"] = self._try_init("cross_cache", _load_cross_cache)

        def _load_persistent():
            from memory.long_term.persistent_store import PersistentStore
            self._persistent = PersistentStore()
        status["persistent"] = self._try_init("persistent", _load_persistent)

        def _load_data_arch():
            from core.data.architecture import get_data_architecture
            self._data_arch = get_data_architecture()
        status["data_architecture"] = self._try_init(
            "data_architecture", _load_data_arch,
        )

        def _load_memory_intel():
            from core.memory.intelligence import get_memory_intelligence
            self._memory_intel = get_memory_intelligence()
        status["memory_intelligence"] = self._try_init(
            "memory_intelligence", _load_memory_intel,
        )

        def _load_intel_cycle():
            from core.intelligence_cycle import get_intelligence_cycle
            self._intel_cycle = get_intelligence_cycle()
        status["intelligence_cycle"] = self._try_init(
            "intelligence_cycle", _load_intel_cycle,
        )

        self._initialized = True
        if self._init_errors:
            logger.warning(
                "UnifiedMemory initialized with %d failed backends: %s",
                len(self._init_errors),
                ", ".join(self._init_errors.keys()),
            )
        else:
            logger.info("UnifiedMemory initialized: all %d backends ok", len(status))
        return status

    def get_init_errors(self) -> dict[str, str]:
        """Return per-backend initialization error messages.

        Empty dict means every backend loaded successfully. Useful
        for status dashboards and tests that want to assert clean
        startup."""
        return dict(self._init_errors)

    def _ensure_init(self) -> None:
        if not self._initialized:
            self.initialize()

    # ── INGEST — data enters the system ──────────────────────

    def ingest(self, category: str, data: Any, source: str = "",
               store_id: str = "", ttl: int = 600) -> None:
        """Data enters system → SharedMemory (live) + BrainMemory L0-L2."""
        self._ensure_init()

        # SharedMemory — live access, TTL-based
        if self._shared:
            key = f"{source}_{int(time.time())}" if source else str(int(time.time()))
            self._shared.put(category, key, data, ttl_seconds=ttl)

        # BrainMemory — features, scoring, pattern detection
        if self._brain:
            self._brain.ingest(category, data if isinstance(data, dict) else {"value": data},
                              source=source, store_id=store_id)

    def ingest_store_data(self, products: list, orders: list, customers: list,
                          store_id: str = "") -> None:
        """Bulk ingest store data into all memory layers."""
        self._ensure_init()

        # SharedMemory — live data access
        if self._shared:
            self._shared.load_store_data(products, orders, customers, store_id)

        # BrainMemory — feature extraction + scoring for each item
        if self._brain:
            for p in products:
                self._brain.ingest("product", p, source="sync", store_id=store_id)
            for o in orders:
                self._brain.ingest("order", o, source="sync", store_id=store_id)
            for c in customers:
                self._brain.ingest("customer", c, source="sync", store_id=store_id)

    # ── RETRIEVE — get data for decisions ────────────────────

    def retrieve(self, category: str, context: dict | None = None) -> dict[str, Any]:
        """Retrieve relevant memories for making a decision.

        Returns: best_cases, failures, rules, patterns, total_memories
        """
        self._ensure_init()
        if self._brain:
            return self._brain.retrieve_for_decision(category, context or {})
        return {"best_cases": [], "failures": [], "rules": [], "patterns": [], "total_memories": 0}

    def get_context(self, task_type: str) -> dict[str, Any]:
        """Build context for a task from SharedMemory."""
        self._ensure_init()
        if self._shared:
            return self._shared.get_context_for_task(task_type)
        return {}

    def get_rules(self, category: str = "") -> list[dict[str, Any]]:
        """Get learned rules from BrainMemory L5."""
        self._ensure_init()
        if self._brain:
            return self._brain.get_rules(category)
        return []

    # ── RECORD — store decisions and outcomes ────────────────

    def record_decision(self, category: str, input_data: dict, action: str,
                        result: dict, score: float, tags: list[str] | None = None,
                        store_id: str = "") -> None:
        """Record a decision + outcome across every available backend.

        Each backend write is isolated in its own try/except so a
        single broken backend never silently skips the others.
        Previously a failure in `brain.record_decision` would
        short-circuit the whole call, leaving Experience and
        SharedMemory missing the same decision and producing a
        divergent record across the memory backends.
        """
        self._ensure_init()

        # BrainMemory — scored, tagged, pattern detection triggers
        if self._brain:
            try:
                self._brain.record_decision(category, input_data, action, result,
                                           score, tags, store_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "UnifiedMemory: brain.record_decision failed: %s", exc,
                )

        # Experience DB — permanent decision outcome storage
        if self._experience:
            try:
                success = score >= 3.0
                impact = score / 5.0
                self._experience.record_decision_outcome(
                    category, input_data, result, success, impact, store_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "UnifiedMemory: experience.record_decision_outcome failed: %s",
                    exc,
                )

        # SharedMemory — recent decisions for quick access
        if self._shared:
            try:
                self._shared.record_decision(f"{category}_{int(time.time())}", {
                    "category": category, "action": action,
                    "score": score, "timestamp": time.time(),
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "UnifiedMemory: shared.record_decision failed: %s", exc,
                )

    def record_mistake(self, mistake_type: str, description: str,
                       cause: str = "", prevention: str = "",
                       store_id: str = "") -> None:
        """Record a mistake → Experience DB + BrainMemory bad_data."""
        self._ensure_init()
        if self._experience:
            self._experience.record_mistake(mistake_type, description, cause, prevention,
                                           store_id=store_id)
        if self._brain:
            self._brain._store_bad_data(mistake_type, {
                "description": description, "cause": cause,
            }, f"mistake: {mistake_type}")

    # ── LEARN — store learned knowledge ──────────────────────

    def learn_product(self, product_id: str, knowledge_type: str, insight: str,
                      confidence: float = 0.5, store_id: str = "") -> None:
        """Store product-specific knowledge."""
        self._ensure_init()
        if self._experience:
            self._experience.learn_product(product_id, knowledge_type, insight,
                                          confidence, store_id=store_id)

    def learn_strategy(self, strategy: str, category: str,
                       effectiveness: float, notes: str = "") -> None:
        """Store strategy knowledge."""
        self._ensure_init()
        if self._experience:
            self._experience.learn_strategy(strategy, category, effectiveness, notes=notes)

    # ── PERSIST — long-term storage ──────────────────────────

    def persist(self, key: str, value: Any, namespace: str = "general",
                metadata: dict | None = None) -> None:
        """Store in long-term persistent memory (survives restarts)."""
        self._ensure_init()
        if self._persistent:
            self._persistent.store(key, value, namespace=namespace, metadata=metadata)

    def recall(self, key: str, namespace: str = "general") -> Any:
        """Recall from long-term persistent memory."""
        self._ensure_init()
        if self._persistent:
            return self._persistent.retrieve(key, namespace=namespace)
        return None

    # ── CROSS-ENGINE — share data between engines ────────────

    def engine_put(self, engine_name: str, key: str, value: Any) -> None:
        """Store data for cross-engine sharing."""
        self._ensure_init()
        if self._cross_cache:
            self._cross_cache.put(engine_name, key, value)
        elif self._shared:
            self._shared.put("cache", f"{engine_name}_{key}", value, ttl_seconds=300)

    def engine_get(self, engine_name: str, key: str) -> Any:
        """Get data shared by another engine."""
        self._ensure_init()
        if self._cross_cache:
            return self._cross_cache.get(engine_name, key)
        elif self._shared:
            return self._shared.get("cache", f"{engine_name}_{key}")
        return None

    # ── INTELLIGENCE CYCLE — run full AI decision cycle ─────

    def run_intelligence_cycle(self, category: str, data: dict,
                               action_fn=None, store_id: str = "") -> dict[str, Any]:
        """Run the 10-stage intelligence cycle.

        Data → Filter → Feature → Memory → Decision → Execution
        → Result → Evaluation → Learning → Memory Update
        """
        self._ensure_init()
        if self._intel_cycle:
            return self._intel_cycle.run(category, data, action_fn, store_id)
        return {"status": "intelligence_cycle_not_available"}

    # ── DATA ARCHITECTURE — structured domain data ───────────

    def capture_data(self, domain: str, data: dict, source: str = "",
                     store_id: str = "", score: float = 0.0) -> int:
        """Capture data into the 12-domain architecture."""
        self._ensure_init()
        if self._data_arch:
            return self._data_arch.capture(domain, data, source=source,
                                           store_id=store_id, score=score)
        return 0

    def query_data(self, domain: str, min_score: float = 0.0,
                   tags: list | None = None, limit: int = 50) -> list[dict]:
        """Query data from a domain."""
        self._ensure_init()
        if self._data_arch:
            return self._data_arch.query(domain, min_score=min_score,
                                         tags=tags, limit=limit)
        return []

    def get_data_context(self, domain: str) -> dict[str, Any]:
        """Get full context from data architecture for decisions."""
        self._ensure_init()
        if self._data_arch:
            return self._data_arch.get_context_for_decision(domain)
        return {}

    # ── MEMORY INTELLIGENCE — 4-level hierarchy ──────────────

    def create_memory(self, category: str, content: dict, action: str = "",
                      result: dict | None = None, score: float = 3.0,
                      memory_type: str = "episodic",
                      tags: list[str] | None = None) -> int:
        """Create a memory in the 4-level hierarchy."""
        self._ensure_init()
        if self._memory_intel:
            return self._memory_intel.create(category, content, action=action,
                                             result=result, score=score,
                                             memory_type=memory_type, tags=tags)
        return 0

    def retrieve_intelligence(self, category: str) -> dict[str, Any]:
        """Retrieve full intelligence context (events, patterns, rules, strategies)."""
        self._ensure_init()
        if self._memory_intel:
            return self._memory_intel.retrieve_for_decision(category)
        return {"best_events": [], "patterns": [], "rules": [],
                "strategies": [], "failures": [], "total_memories": 0}

    def get_learned_rules(self, category: str = "") -> list[dict]:
        """Get rules learned through pattern promotion."""
        self._ensure_init()
        if self._memory_intel:
            return self._memory_intel.get_rules(category)
        return []

    def get_strategies(self, category: str = "") -> list[dict]:
        """Get strategies built from rules."""
        self._ensure_init()
        if self._memory_intel:
            return self._memory_intel.get_strategies(category)
        return []

    def record_failure(self, category: str, failure_data: dict,
                       root_cause: str = "", severity: str = "medium") -> int:
        """Record a failure for learning. Failures are gold."""
        self._ensure_init()
        if self._memory_intel:
            return self._memory_intel.record_failure(category, failure_data,
                                                     root_cause, severity)
        return 0

    # ── STATS ────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get stats from all memory backends."""
        self._ensure_init()
        stats: dict[str, Any] = {}

        if self._shared:
            stats["shared_memory"] = self._shared.get_stats()
        if self._brain:
            stats["brain_memory"] = self._brain.get_stats()
        if self._experience:
            stats["experience"] = self._experience.get_knowledge_summary()
        if self._data_arch:
            stats["data_architecture"] = self._data_arch.get_stats()
        if self._memory_intel:
            stats["memory_intelligence"] = self._memory_intel.get_stats()
        if self._intel_cycle:
            stats["intelligence_cycle"] = self._intel_cycle.get_stats()

        total = 0
        for v in stats.values():
            if isinstance(v, dict):
                total += v.get("total_memories", v.get("total_entries",
                         v.get("decisions_recorded", 0)))
        stats["total_across_all"] = total

        return stats


# Singleton
_unified: UnifiedMemory | None = None


def get_unified_memory() -> UnifiedMemory:
    global _unified
    if _unified is None:
        _unified = UnifiedMemory()
    return _unified
