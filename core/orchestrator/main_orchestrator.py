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
from core.data_context import DataEnricher
from core.step_logic import PreProcessor, PostProcessor
from core.step_logic.response_enricher import ResponseEnricher
from core.events import EventBus, EventType, EventHandler
from core.telemetry import Tracer, MetricsCollector
from core.performance import ExecutionCache
from core.error_intelligence import ErrorClassifier, FixSuggester, ErrorPatternDetector
from core.self_monitor import SystemMonitor
from core.shared_memory import CrossEngineCache, SessionContext
from core.chaining import ChainRegistry
from core.bridge import AgentEngineBridge
from core.bridge.pipeline_bridge import PipelineBridge
from core.bridge.execution_bridge import ExecutionBridge
from core.bridge.workflow_bridge import WorkflowBridge

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
        # System modules
        self._event_bus = EventBus()
        self._tracer = Tracer()
        self._metrics = MetricsCollector()
        self._exec_cache = ExecutionCache()
        self._error_classifier = ErrorClassifier()
        self._fix_suggester = FixSuggester()
        self._error_patterns = ErrorPatternDetector()
        self._system_monitor = SystemMonitor()
        self._cross_cache = CrossEngineCache()
        self._chain_registry = ChainRegistry()
        # Bridges
        self._agent_bridge = AgentEngineBridge()
        self._pipeline_bridge = PipelineBridge()
        self._execution_bridge = ExecutionBridge()
        self._workflow_bridge = WorkflowBridge()
        # New module integrations
        self._agent_manager = None
        self._message_bus = None
        self._vector_db = None
        self._rule_engine = None
        self._prompt_manager = None
        self._product_pipeline = None
        self._marketing_pipeline = None
        self._analytics_pipeline = None
        self._kpi_tracker = None
        self._system_health = None
        self._engine_memories: dict[str, Any] = {}
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

        # Wire data processing layers into all engines
        from engines.base.base_engine import set_feedback_store, set_data_layers
        set_feedback_store(self._feedback_store)
        set_data_layers(
            enricher=DataEnricher(),
            pre_processor=PreProcessor(),
            post_processor=PostProcessor(),
            response_enricher=ResponseEnricher(),
        )

        # Wire events system
        EventHandler().register_defaults()
        self._event_bus.emit(EventType.SYSTEM_HEALTH_CHECK, "orchestrator", {"phase": "startup"})

        # Initialize new modules
        self._init_modules()

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

        # Start trace
        trace_span = self._tracer.start_trace(f"task:{task_type}", {"task_id": task_id})
        self._metrics.increment("task.submitted")
        self._event_bus.emit(EventType.ENGINE_START, task_type, {"task_id": task_id})

        # Check execution cache
        cached = self._exec_cache.get(task_type, params or {})
        if cached is not None:
            self._metrics.increment("task.cache_hit")
            self._tracer.finish_span(trace_span, "cache_hit")
            elapsed = time.monotonic() - start_time
            cached["_cached"] = True
            cached["elapsed_seconds"] = round(elapsed, 3)
            return cached

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
                self._tracer.finish_span(trace_span, "no_engine")
                return {"task_id": task_id, "engine": task_type, "status": "failed", "result": None, "error": f"No engine for task_type={task_type}", "timestamp": time.time()}

            # Engine memory: check for duplicate inputs
            engine_mem = self._engine_memories.get(task_type)
            if engine_mem and params:
                try:
                    dedup = engine_mem.remember_input(params)
                    if dedup.get("is_duplicate"):
                        self._metrics.increment("task.duplicate_input")
                except Exception:
                    pass

            # Execute (with fallback support)
            exec_span = self._tracer.start_span(trace_span.trace_id, f"execute:{engine}", trace_span.span_id)
            result = self._execute_with_fallback(engine, task_id, params or {})
            self._tracer.finish_span(exec_span, result.get("status", "unknown"))

            # Engine memory: record successful patterns
            if engine_mem and result.get("status") == "completed":
                try:
                    engine_mem.remember_success(params or {}, result.get("result", {}))
                except Exception:
                    pass

            # Store result in memory
            self._memory_router.route_store(f"result:{task_id}", result, data_type="task_result")

            # Update runtime state
            self._state.runtime.update_task(task_id, result["status"], result=result.get("result"), error=result.get("error"))

            elapsed = time.monotonic() - start_time
            result["elapsed_seconds"] = round(elapsed, 3)

            # Post-execution: cache, events, metrics, cross-engine cache
            status = result.get("status", "unknown")
            self._metrics.increment(f"task.{status}")
            self._metrics.histogram("task.duration_ms", elapsed * 1000)
            self._tracer.finish_span(trace_span, status)

            if status == "completed":
                self._exec_cache.store(task_type, params or {}, result)
                self._cross_cache.store(task_type, "latest_result", result.get("result", {}))
                self._event_bus.emit(EventType.ENGINE_COMPLETE, task_type, {"task_id": task_id, "elapsed": elapsed})
            else:
                error_msg = result.get("error", "unknown")
                self._event_bus.emit(EventType.ENGINE_FAILED, task_type, {"task_id": task_id, "error": error_msg})
                self._error_patterns.record(task_type, str(error_msg), severity="high")

            # Record KPI for decision quality tracking
            if self._kpi_tracker is not None:
                try:
                    self._kpi_tracker.record_decision_outcome(
                        decision_id=task_id,
                        decision_type=task_type,
                        confidence=result.get("confidence", "unknown"),
                        confidence_score=result.get("confidence_score", 50),
                        success=status == "completed",
                        data_quality=result.get("data_quality", 50),
                        execution_results={"dispatched": 1, "success_count": 1 if status == "completed" else 0,
                                           "fail_count": 0 if status == "completed" else 1},
                    )
                except Exception:
                    pass

            return result

        except Exception as exc:
            elapsed = time.monotonic() - start_time
            logger.error("Task %s crashed: %s", task_id, exc)
            self._tracer.finish_span(trace_span, "crash")
            self._metrics.increment("task.crash")
            self._error_patterns.record(task_type, str(exc), severity="critical")
            self._event_bus.emit(EventType.ENGINE_FAILED, task_type, {"task_id": task_id, "error": str(exc)})
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
            "metrics": self._metrics.snapshot(),
            "cache_stats": self._exec_cache.get_stats(),
            "event_stats": self._event_bus.get_stats(),
            "error_patterns": self._error_patterns.detect_patterns(),
            "chains": self._chain_registry.list_chains(),
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

    @property
    def events(self) -> EventBus:
        return self._event_bus

    @property
    def tracer(self) -> Tracer:
        return self._tracer

    @property
    def metrics(self) -> MetricsCollector:
        return self._metrics

    @property
    def cache(self) -> ExecutionCache:
        return self._exec_cache

    @property
    def monitor(self) -> SystemMonitor:
        return self._system_monitor

    @property
    def chains(self) -> ChainRegistry:
        return self._chain_registry

    @property
    def errors(self) -> ErrorPatternDetector:
        return self._error_patterns

    def diagnose_error(self, error: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Diagnose an error with classification, root cause, and fix suggestions."""
        return self._fix_suggester.suggest(error, context)

    def health_check(self) -> dict[str, Any]:
        """Run full system health check."""
        return self._system_monitor.full_check()

    def run_chain(self, chain_name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Run a named engine chain."""
        return self._chain_registry.run(chain_name, data)

    def run_full_loop(self, data: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the FULL system loop: Pipeline → Intelligence → Agents → Execution → Memory → Learning."""
        from core.full_system_loop import FullSystemLoop
        return FullSystemLoop().run(data, config)

    # -- bridges --

    def agent_run(self, agent_name: str, task: str, data: dict[str, Any]) -> dict[str, Any]:
        """Run a task through an agent (agent decides which engine)."""
        return self._agent_bridge.agent_run(agent_name, task, data)

    def run_workflow(self, workflow_name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Run a named business workflow (multi-agent, multi-engine)."""
        return self._workflow_bridge.run_workflow(workflow_name, data)

    def plan_actions(self, engine_name: str, result: dict[str, Any]) -> list[dict[str, Any]]:
        """Plan executable actions from engine output."""
        return self._execution_bridge.plan_actions(engine_name, result)

    def list_agents(self) -> list[dict[str, Any]]:
        return self._agent_bridge.list_agents()

    def list_workflows(self) -> list[dict[str, Any]]:
        return self._workflow_bridge.list_workflows()

    @property
    def agents(self) -> AgentEngineBridge:
        return self._agent_bridge

    @property
    def workflows(self) -> WorkflowBridge:
        return self._workflow_bridge

    @property
    def execution(self) -> ExecutionBridge:
        return self._execution_bridge

    @property
    def pipeline(self) -> PipelineBridge:
        return self._pipeline_bridge

    # -- new module accessors --

    @property
    def agent_manager(self):
        return self._agent_manager

    @property
    def message_bus(self):
        return self._message_bus

    @property
    def vector_db(self):
        return self._vector_db

    @property
    def rule_engine(self):
        return self._rule_engine

    @property
    def prompt_manager(self):
        return self._prompt_manager

    def run_pipeline(self, pipeline_type: str, data: Any) -> dict[str, Any]:
        """Run data through a specific pipeline before engine processing."""
        pipelines = {
            "product": self._product_pipeline,
            "marketing": self._marketing_pipeline,
            "analytics": self._analytics_pipeline,
        }
        pipeline = pipelines.get(pipeline_type)
        if pipeline is None:
            return {"status": "error", "error": f"Unknown pipeline: {pipeline_type}"}
        try:
            return pipeline.run(data)
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def store_knowledge(self, collection: str, key: str, embedding: list[float], metadata: dict[str, Any] | None = None) -> bool:
        """Store a vector embedding in the knowledge base."""
        if self._vector_db is None:
            return False
        self._vector_db.add(collection, key, embedding, metadata or {})
        return True

    def search_knowledge(self, collection: str, query_embedding: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        """Search knowledge base by vector similarity."""
        if self._vector_db is None:
            return []
        return self._vector_db.search(collection, query_embedding, top_k=top_k)

    def evaluate_rules(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Evaluate business rules against data."""
        if self._rule_engine is None:
            return []
        return self._rule_engine.evaluate(data)

    def publish_message(self, topic: str, payload: dict[str, Any], sender: str = "orchestrator") -> bool:
        """Publish a message to the agent message bus."""
        if self._message_bus is None:
            return False
        self._message_bus.publish(topic, payload, sender)
        return True

    @property
    def kpi_tracker(self):
        return self._kpi_tracker

    def get_engine_memory(self, engine_type: str) -> dict[str, Any]:
        """Get learned patterns for an engine type."""
        mem = self._engine_memories.get(engine_type)
        if mem is None:
            return {"status": "not_available"}
        return {
            "engine": engine_type,
            "success_patterns": mem.get_success_patterns(),
            "baselines": mem.get_baselines() if hasattr(mem, "get_baselines") else {},
        }

    def get_system_health(self) -> dict[str, Any]:
        """Generate comprehensive system health report."""
        if self._system_health is None:
            return {"status": "unavailable"}
        return self._system_health.generate()

    def get_kpi_summary(self) -> dict[str, Any]:
        """Get decision quality and revenue KPIs."""
        if self._kpi_tracker is None:
            return {"status": "unavailable"}
        return {
            "decisions": self._kpi_tracker.get_decision_kpis(),
            "revenue": self._kpi_tracker.get_revenue_kpis(),
        }

    # -- internal helpers --

    def _init_modules(self) -> None:
        """Initialize all external modules — agents, pipelines, memory, knowledge."""
        try:
            from agents.manager.agent_manager import AgentManager
            from agents.communication.message_bus import MessageBus
            self._agent_manager = AgentManager()
            self._message_bus = MessageBus()
            # Register default agents
            for agent_type in ("product", "marketing", "customer", "operations", "analytics", "content"):
                self._agent_manager.register_agent(agent_type, agent_type, {"auto_created": True})
            logger.info("Agents module initialized (%d agents)", len(self._agent_manager.list_agents()))
        except Exception as exc:
            logger.warning("Agents module not available: %s", exc)

        try:
            from memory.vector_store.vector_db import VectorDB
            self._vector_db = VectorDB()
            logger.info("VectorDB initialized")
        except Exception as exc:
            logger.warning("VectorDB not available: %s", exc)

        try:
            from knowledge.rules.rule_engine import RuleEngine
            from knowledge.prompts.prompt_manager import PromptManager
            self._rule_engine = RuleEngine()
            self._prompt_manager = PromptManager()
            # Load default business rules
            self._rule_engine.add_rule(
                "low_stock_alert",
                condition={"inventory_quantity": {"lt": 5}},
                action={"type": "notify", "message": "Low stock alert"},
                priority=10,
            )
            self._rule_engine.add_rule(
                "high_value_order",
                condition={"total": {"gt": 200}},
                action={"type": "notify", "message": "High value order"},
                priority=8,
            )
            logger.info("Knowledge module initialized (%d rules)", len(self._rule_engine.list_rules()))
        except Exception as exc:
            logger.warning("Knowledge module not available: %s", exc)

        try:
            from data_pipeline.pipelines.product_pipeline import ProductPipeline
            from data_pipeline.pipelines.marketing_pipeline import MarketingPipeline
            from data_pipeline.pipelines.analytics_pipeline import AnalyticsPipeline
            self._product_pipeline = ProductPipeline()
            self._marketing_pipeline = MarketingPipeline()
            self._analytics_pipeline = AnalyticsPipeline()
            logger.info("Data pipelines initialized (product, marketing, analytics)")
        except Exception as exc:
            logger.warning("Data pipelines not available: %s", exc)

        # Initialize KPI + health monitoring
        try:
            from core.intelligence.kpi_tracker import KPITracker
            from core.intelligence.system_health import SystemHealthReport
            self._kpi_tracker = KPITracker()
            self._system_health = SystemHealthReport()
            logger.info("KPI tracker and system health monitor initialized")
        except Exception as exc:
            logger.warning("KPI/Health not available: %s", exc)

        # Initialize engine memory for pattern learning
        try:
            from core.shared_memory import EngineMemory
            for engine_type in ("pricing", "marketing", "customer", "seo", "content", "inventory"):
                self._engine_memories[engine_type] = EngineMemory(engine_type)
            logger.info("Engine memory initialized for %d engine types", len(self._engine_memories))
        except Exception as exc:
            logger.warning("Engine memory not available: %s", exc)

        # Wire execution bridge to real executors
        self._wire_executors()

    def _wire_executors(self) -> None:
        """Connect ExecutionBridge to real execution modules."""
        try:
            from execution.shopify.product_creator import ProductCreator
            from execution.shopify.product_updater import ProductUpdater
            from execution.marketing.ad_launcher import AdLauncher
            from execution.marketing.campaign_manager import CampaignManager
            from execution.content.publisher import ContentPublisher

            self._execution_bridge.register_executor("shopify", "product.create_listing", ProductCreator())
            self._execution_bridge.register_executor("shopify", "pricing.update", ProductUpdater())
            self._execution_bridge.register_executor("multi_channel", "marketing.launch_campaign", AdLauncher())
            self._execution_bridge.register_executor("multi_channel", "marketing.manage_campaign", CampaignManager())
            self._execution_bridge.register_executor("cms", "content.publish", ContentPublisher())
            logger.info("Execution bridge wired to real executors")
        except Exception as exc:
            logger.warning("Executor wiring partial: %s", exc)

    def _register_engines(self) -> None:
        """Auto-register all engines from the registry as execution handlers."""
        from engines.base import EngineInput
        from engines.base.engine_types import normalize_engine_output

        for engine_name in list_engines():
            def _make_handler(name: str):
                def handler(task_id: str, params: dict[str, Any]) -> Any:
                    engine = get_engine(name)
                    engine_input = EngineInput(
                        task_id=task_id,
                        engine_name=name,
                        data=params,
                    )
                    raw_output = engine.run(engine_input)
                    output = normalize_engine_output(raw_output, engine_input)
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
