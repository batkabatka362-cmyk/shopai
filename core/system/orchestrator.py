"""SystemOrchestrator — centralized control layer for ShopAI.

This is the BRAIN. It:
  - Controls all task execution flow
  - Routes tasks to correct engines
  - Manages system state
  - Uses SharedMemory for context
  - Uses TaskQueue for dependency-aware execution
  - Uses LLMAdapter for AI reasoning

Orchestrator = control layer. Engines = workers. They don't control.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("system.orchestrator")


class SystemOrchestrator:
    """Central control layer — manages all ShopAI operations."""

    def __init__(self) -> None:
        self._initialized = False
        self._memory = None
        self._llm = None
        self._task_queue = None
        self._store_manager = None
        self._cycle_count = 0

    def initialize(self, store_manager: Any = None) -> dict[str, Any]:
        """Initialize all system components."""
        from core.system.shared_memory import get_shared_memory
        from core.system.llm_adapter import get_llm
        from core.system.task_queue import TaskQueue

        self._memory = get_shared_memory()
        self._llm = get_llm()
        self._task_queue = TaskQueue()
        self._store_manager = store_manager

        # Auto-configure LLM
        llm_status = self._llm.auto_configure()

        self._initialized = True
        logger.info("SystemOrchestrator initialized")

        return {
            "status": "initialized",
            "llm": llm_status,
            "memory": self._memory.get_stats(),
        }

    # ── Task Execution ───────────────────────────────────────

    def run_task(self, task_type: str, data: dict | None = None,
                 store_id: str = "") -> dict[str, Any]:
        """Run a single task through the system."""
        self._ensure_init()
        start = time.monotonic()

        # Load context from shared memory and merge with caller data.
        # Caller-provided `data` MUST win over cached context — it's
        # the freshest, most-specific signal. Previously the order was
        # `{**(data or {}), **context}` which let cached products /
        # orders / decisions silently overwrite whatever the caller
        # had explicitly passed in, producing stale task inputs.
        context = self._memory.get_context_for_task(task_type)
        task_data = {**context, **(data or {})}

        # Execute
        from engines.registry import get_engine
        engine = get_engine(task_type)
        if not engine:
            return {"status": "error", "error": f"Engine not found: {task_type}"}

        try:
            result = engine.run(task_data)
            # Store result in shared memory
            self._memory.put("cache", f"result_{task_type}", result, ttl_seconds=300)
            return result if isinstance(result, dict) else {"output": result}
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SystemOrchestrator: engine %r raised: %s", task_type, exc,
            )
            return {"status": "error", "error": str(exc)}

    def run_flow(self, flow_name: str, store_id: str = "") -> dict[str, Any]:
        """Run a predefined flow (chain of tasks with dependencies)."""
        self._ensure_init()

        flows = {
            "full_analysis": [
                {"id": "sync", "engine": "sync", "action": "sync_store"},
                {"id": "product_analysis", "engine": "product_research", "depends_on": ["sync"]},
                {"id": "pricing_analysis", "engine": "pricing", "depends_on": ["sync"]},
                {"id": "inventory_check", "engine": "inventory", "depends_on": ["sync"]},
                {"id": "customer_analysis", "engine": "customer_segmentation", "depends_on": ["sync"]},
            ],
            "pricing_optimization": [
                {"id": "analyze", "engine": "pricing"},
                {"id": "competitor_check", "engine": "competitor_monitor", "depends_on": ["analyze"]},
                {"id": "apply_prices", "engine": "pricing", "action": "apply", "depends_on": ["competitor_check"]},
            ],
            "new_product": [
                {"id": "research", "engine": "product_research"},
                {"id": "validate", "engine": "product_validation", "depends_on": ["research"]},
                {"id": "optimize", "engine": "product_optimization", "depends_on": ["validate"]},
                {"id": "create", "engine": "product_description", "depends_on": ["optimize"]},
            ],
            "daily_operations": [
                {"id": "sync", "engine": "sync"},
                {"id": "analytics", "engine": "analytics", "depends_on": ["sync"]},
                {"id": "pricing", "engine": "pricing", "depends_on": ["analytics"]},
                {"id": "inventory", "engine": "inventory", "depends_on": ["analytics"]},
                {"id": "marketing", "engine": "email_marketing", "depends_on": ["analytics"]},
            ],
        }

        flow = flows.get(flow_name)
        if not flow:
            return {"status": "error", "error": f"Unknown flow: {flow_name}",
                    "available": list(flows.keys())}

        # Load store data into memory
        if store_id and self._store_manager:
            self._load_store_data(store_id)

        # Build task queue
        self._task_queue.clear()
        for task_def in flow:
            data = self._memory.get_context_for_task(task_def.get("engine", ""))
            self._task_queue.add(
                task_def["id"], engine=task_def.get("engine", ""),
                action=task_def.get("action", ""),
                data=data, depends_on=task_def.get("depends_on", []),
            )

        # Execute
        return self._task_queue.execute_all()

    # ── AI-Powered Decision ──────────────────────────────────

    def ask_ai(self, question: str, role: str = "analyzer",
               context: dict | None = None) -> dict[str, Any]:
        """Ask the AI a question with system context."""
        self._ensure_init()

        # Enrich context with shared memory
        full_context = context or {}
        full_context["system_state"] = self._memory.get_all("state")
        full_context["recent_decisions"] = self._memory.get_all("decisions")

        response = self._llm.ask(role, question, full_context)
        return response.to_dict()

    def ai_decide(self, task: str, options: list[dict] | None = None,
                  context: dict | None = None) -> dict[str, Any]:
        """Ask AI to make a decision."""
        self._ensure_init()

        prompt = f"Task: {task}\n"
        if options:
            prompt += "Options:\n"
            for i, opt in enumerate(options, 1):
                prompt += f"  {i}. {opt.get('name', opt)}: {opt.get('description', '')}\n"
        prompt += "\nChoose the best option and explain why. Respond in JSON: {\"choice\": N, \"reason\": \"...\"}"

        response = self._llm.ask_json("analyzer", prompt, context)

        # Record decision
        self._memory.record_decision(f"dec_{int(time.time())}", {
            "task": task, "options": options, "decision": response,
        })

        return response

    # ── State Management ─────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        """Get current system state."""
        return {
            "initialized": self._initialized,
            "cycle_count": self._cycle_count,
            "memory": self._memory.get_stats() if self._memory else {},
            "llm": self._llm.get_stats() if self._llm else {},
            "task_queue": self._task_queue.get_status() if self._task_queue else {},
        }

    def _load_store_data(self, store_id: str) -> None:
        """Load store data into shared memory."""
        if not self._store_manager:
            return
        products = self._store_manager.get_products(store_id)
        orders = self._store_manager.get_orders(store_id)
        customers = self._store_manager.get_customers(store_id)
        self._memory.load_store_data(products, orders, customers, store_id)

    def _ensure_init(self) -> None:
        if not self._initialized:
            self.initialize()


# Singleton
_orchestrator: SystemOrchestrator | None = None


def get_orchestrator() -> SystemOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = SystemOrchestrator()
    return _orchestrator
