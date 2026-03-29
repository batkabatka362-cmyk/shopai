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
from engines.registry import get_engine, list_engines
from core.learning import FeedbackStore, LearningEngine, ImprovementTracker

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
        self._feedback_store = FeedbackStore()
        self._learning_engine = LearningEngine(self._feedback_store)
        self._improvement_tracker = ImprovementTracker()
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

        # Wire learning feedback into all engines (read-only — never modifies code)
        from engines.base.base_engine import set_feedback_store
        set_feedback_store(self._feedback_store)

        # Auto-register engine handlers from registry
        self._register_engines()

        self._running = True
        self._state.global_state.system_status = "running"
        logger.info(
            "MainOrchestrator initialized (env=%s, engines=%d)",
            system_cfg.get("environment", "unknown"),
            len(self._execution_router.list_handlers()),
        )

    def submit_task(
        self,
        task_type: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        import time

        if not self._running:
            return {"task_id": "", "engine": "", "status": "error", "result": None, "error": "Orchestrator not running", "timestamp": ""}

        task_id = generate_id("task")
        start_time = time.monotonic()

        # Register in runtime state
        self._state.runtime.register_task(task_id, task_type)

        try:
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
                return {"task_id": task_id, "engine": task_type, "status": "failed", "result": None, "error": f"No engine for task_type={task_type}", "timestamp": time.time()}

            # Execute (with fallback support)
            result = self._execute_with_fallback(engine, task_id, params or {})

            # Store result in memory
            self._memory_router.route_store(f"result:{task_id}", result, data_type="task_result")

            # Update runtime state
            self._state.runtime.update_task(task_id, result["status"], result=result.get("result"), error=result.get("error"))

            elapsed = time.monotonic() - start_time
            result["elapsed_seconds"] = round(elapsed, 3)
            return result

        except Exception as exc:
            elapsed = time.monotonic() - start_time
            logger.error("Task %s crashed: %s", task_id, exc)
            error_result = {
                "task_id": task_id,
                "engine": task_type,
                "status": "error",
                "result": None,
                "error": str(exc),
                "elapsed_seconds": round(elapsed, 3),
                "timestamp": time.time(),
            }
            self._state.runtime.update_task(task_id, "failed", error=str(exc))
            return error_result

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

    @property
    def learning(self) -> LearningEngine:
        return self._learning_engine

    @property
    def feedback(self) -> FeedbackStore:
        return self._feedback_store

    def analyze_engine(self, engine_name: str) -> dict[str, Any]:
        """Analyze engine performance using learning data (read-only)."""
        return self._learning_engine.analyze(engine_name)

    def analyze_system(self) -> dict[str, Any]:
        """Analyze entire system learning state (read-only)."""
        return self._learning_engine.analyze_system()

    # -- internal helpers --

    def _register_engines(self) -> None:
        """Auto-register all engines from the registry as execution handlers."""
        from engines.base import EngineInput

        for engine_name in list_engines():
            def _make_handler(name: str):
                def handler(task_id: str, params: dict[str, Any]) -> Any:
                    engine = get_engine(name)
                    engine_input = EngineInput(
                        task_id=task_id,
                        engine_name=name,
                        data=params,
                    )
                    output = engine.run(engine_input)
                    return output.to_dict()
                return handler

            self._execution_router.register_handler(engine_name, _make_handler(engine_name))

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
