from __future__ import annotations

import pathlib
from typing import Any

import yaml

from utils.helpers import generate_id
from utils.logger import get_logger
from core.state.state_manager import StateManager
from core.context.context_manager import ContextManager
from core.memory.memory_manager import MemoryManager
from core.memory.memory_router import MemoryRouter
from core.memory.memory_sync import MemorySync
from .task_router import TaskRouter
from .execution_router import ExecutionRouter
from .decision_router import DecisionRouter
from .fallback_router import FallbackRouter

logger = get_logger("orchestrator.main")

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / "config"


class MainOrchestrator:
    """Central orchestrator that coordinates all core subsystems.

    Lifecycle:
        1. initialize() — loads config, boots subsystems
        2. submit_task() — accepts tasks and routes them through the pipeline
        3. shutdown() — tears down gracefully
    """

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._state = StateManager()
        self._context = ContextManager()
        self._memory = MemoryManager()
        self._memory_router = MemoryRouter(self._memory)
        self._memory_sync = MemorySync(self._memory)
        self._task_router = TaskRouter()
        self._execution_router = ExecutionRouter()
        self._decision_router = DecisionRouter()
        self._fallback_router = FallbackRouter()
        self._running = False

    def initialize(self, config_override: dict[str, Any] | None = None) -> None:
        self._config = self._load_configs()
        if config_override:
            self._config.update(config_override)

        system_cfg = self._config.get("system", {})
        self._state.initialize(system_cfg)

        orchestrator_cfg = self._config.get("orchestrator", {})
        max_depth = orchestrator_cfg.get("max_fallback_depth", 3)
        self._fallback_router = FallbackRouter(max_depth=max_depth)

        engine_cfg = self._config.get("engines", {})
        self._task_router = TaskRouter(engine_config=engine_cfg)

        self._running = True
        self._state.global_state.system_status = "running"
        logger.info("MainOrchestrator initialized (env=%s)", system_cfg.get("environment", "unknown"))

    def submit_task(
        self,
        task_type: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if not self._running:
            return {"status": "error", "error": "Orchestrator not running"}

        task_id = generate_id("task")

        # Register in runtime state
        self._state.runtime.register_task(task_id, task_type)

        # Build context
        session = self._state.get_session(session_id) if session_id else None
        session_data = session.snapshot() if session else None
        context = self._context.create_context(task_type, params, session_data)

        # Decision routing — check if rules override the default route
        decision_action = self._decision_router.evaluate(context)

        # Task routing — resolve engine
        engine = decision_action or self._task_router.resolve(task_type)
        if engine is None:
            self._state.runtime.update_task(task_id, "failed", error="No engine found")
            return {"task_id": task_id, "status": "failed", "error": f"No engine for task_type={task_type}"}

        # Execute (with fallback support)
        result = self._execute_with_fallback(engine, task_id, params)

        # Store result in memory
        self._memory_router.route_store(f"result:{task_id}", result, data_type="task_result")

        # Update runtime state
        self._state.runtime.update_task(task_id, result["status"], result=result.get("result"), error=result.get("error"))

        return result

    def create_session(self, session_id: str | None = None) -> str:
        session = self._state.create_session(session_id)
        return session.session_id

    def shutdown(self) -> None:
        self._running = False
        self._state.global_state.system_status = "stopped"
        self._memory.clear_short_term()
        logger.info("MainOrchestrator shut down")

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "state": self._state.snapshot(),
            "memory": self._memory.get_stats(),
            "routes": self._task_router.list_routes(),
            "handlers": self._execution_router.list_handlers(),
        }

    # -- component accessors --

    @property
    def state(self) -> StateManager:
        return self._state

    @property
    def context(self) -> ContextManager:
        return self._context

    @property
    def memory(self) -> MemoryManager:
        return self._memory

    @property
    def task_router(self) -> TaskRouter:
        return self._task_router

    @property
    def execution_router(self) -> ExecutionRouter:
        return self._execution_router

    @property
    def decision_router(self) -> DecisionRouter:
        return self._decision_router

    @property
    def fallback_router(self) -> FallbackRouter:
        return self._fallback_router

    # -- internal helpers --

    def _execute_with_fallback(self, engine: str, task_id: str, params: dict[str, Any] | None) -> dict[str, Any]:
        max_attempts = self._config.get("orchestrator", {}).get("retry_max_attempts", 3)
        result = self._execution_router.execute(engine, task_id, params)
        if result["status"] == "completed":
            return result

        for attempt in range(max_attempts):
            fallback_engine = self._fallback_router.get_fallback(engine, attempt)
            if fallback_engine is None:
                break
            logger.info("Attempting fallback %s for task %s (attempt %d)", fallback_engine, task_id, attempt)
            result = self._execution_router.execute(fallback_engine, task_id, params)
            if result["status"] == "completed":
                return result

        return result

    @staticmethod
    def _load_configs() -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for name in ("system_config", "engine_config", "model_config"):
            path = CONFIG_DIR / f"{name}.yaml"
            if path.exists():
                with open(path) as f:
                    data = yaml.safe_load(f) or {}
                    merged.update(data)
        return merged
