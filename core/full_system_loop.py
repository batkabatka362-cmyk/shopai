"""FullSystemLoop — connects ALL modules into one intelligent flow.

The COMPLETE chain:
  Raw Data → Pipeline (clean/normalize/validate/features)
  → IntelligenceLoop (analyze/decide/plan/execute/track/learn)
  → Agents (coordinate multi-agent tasks)
  → Execution (dispatch to Shopify/email/ads)
  → Memory (store results for future decisions)
  → Knowledge (update rules from outcomes)

This is the MASTER loop — everything flows through here.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("full_system_loop")


class FullSystemLoop:
    """Master loop connecting data pipeline → intelligence → agents → execution → memory → learning."""

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = []
        self._cycle_count = 0

    def run(self, raw_data: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the FULL system loop.

        Phases:
          1. DATA    — Pipeline: clean, normalize, validate, extract features
          2. INTEL   — IntelligenceLoop: analyze, decide, plan
          3. AGENTS  — Coordinate: route tasks to specialized agents
          4. EXECUTE — Dispatch: send actions to real systems
          5. MEMORY  — Store: save results for future retrieval
          6. LEARN   — Update: feed outcomes back to improve decisions
        """
        cycle_id = generate_id("full")
        start = time.monotonic()
        cfg = config or {}
        phases = {}

        # ── Phase 1: DATA PIPELINE ──
        pipeline_result = self._phase_data(raw_data, cfg)
        phases["data"] = pipeline_result

        # Use pipeline-cleaned data for intelligence
        clean_data = pipeline_result.get("clean_data", raw_data)

        # ── Phase 2: INTELLIGENCE LOOP ──
        intel_result = self._phase_intelligence(clean_data, cfg.get("goal", "maximize_profit"))
        phases["intelligence"] = intel_result

        # ── Phase 3: AGENT COORDINATION ──
        agent_result = self._phase_agents(intel_result, cfg)
        phases["agents"] = agent_result

        # ── Phase 4: EXECUTION DISPATCH ──
        exec_result = self._phase_execute(intel_result, agent_result)
        phases["execution"] = exec_result

        # ── Phase 5: MEMORY STORAGE ──
        memory_result = self._phase_memory(cycle_id, phases)
        phases["memory"] = memory_result

        # ── Phase 6: LEARNING UPDATE ──
        learn_result = self._phase_learn(cycle_id, phases)
        phases["learning"] = learn_result

        elapsed = time.monotonic() - start
        self._cycle_count += 1

        result = {
            "cycle_id": cycle_id,
            "cycle_number": self._cycle_count,
            "elapsed_seconds": round(elapsed, 3),
            "status": "completed",
            "phases": {
                "data": {
                    "products_processed": pipeline_result.get("products_processed", 0),
                    "features_extracted": pipeline_result.get("features_extracted", 0),
                    "quality": pipeline_result.get("quality", "unknown"),
                },
                "intelligence": {
                    "data_quality": intel_result.get("data_quality", 0),
                    "decision": intel_result.get("decision", {}),
                    "actions_planned": intel_result.get("plan", {}).get("actions", 0),
                },
                "agents": {
                    "tasks_routed": agent_result.get("tasks_routed", 0),
                    "agents_used": agent_result.get("agents_used", []),
                },
                "execution": {
                    "actions_dispatched": exec_result.get("dispatched", 0),
                    "actions_queued": exec_result.get("queued", 0),
                },
                "memory": {
                    "vectors_stored": memory_result.get("stored", 0),
                },
                "learning": {
                    "rules_updated": learn_result.get("rules_updated", 0),
                    "patterns_found": learn_result.get("patterns_found", 0),
                },
            },
            "summary": self._build_summary(phases, elapsed),
        }

        self._history.append(result)
        if len(self._history) > 100:
            self._history = self._history[-100:]

        return result

    # ── Phase Implementations ──

    def _phase_data(self, raw_data: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
        """Phase 1: Run data through appropriate pipeline."""
        result = {"clean_data": raw_data, "products_processed": 0, "features_extracted": 0, "quality": "raw"}

        products = raw_data.get("products", raw_data.get("product_data", []))
        if isinstance(products, list) and products:
            try:
                from data_pipeline.pipelines.product_pipeline import ProductPipeline
                pp = ProductPipeline()
                pipeline_out = pp.run(products)
                result["clean_data"] = dict(raw_data)
                result["clean_data"]["products"] = pipeline_out.get("products", products)
                result["products_processed"] = pipeline_out.get("stats", {}).get("input_count", len(products))
                result["features_extracted"] = len(pipeline_out.get("features", []))
                result["quality"] = "pipeline_processed"
                result["pipeline_stats"] = pipeline_out.get("stats", {})
            except Exception as exc:
                logger.warning("Product pipeline error: %s", exc)
                result["quality"] = "raw_fallback"

        customers = raw_data.get("customers", raw_data.get("customer_data", []))
        if isinstance(customers, list) and customers:
            try:
                from data_pipeline.processing.cleaner import DataCleaner
                from data_pipeline.processing.normalizer import DataNormalizer
                cleaner = DataCleaner()
                normalizer = DataNormalizer()
                cleaned = cleaner.clean(customers)
                normalized = normalizer.normalize(cleaned)
                result["clean_data"]["customers"] = normalized
                result["customers_processed"] = len(normalized)
            except Exception:
                pass

        return result

    def _phase_intelligence(self, data: dict[str, Any], goal: str) -> dict[str, Any]:
        """Phase 2: Run IntelligenceLoop on cleaned data."""
        try:
            from core.intelligence_loop import IntelligenceLoop
            il = IntelligenceLoop()
            return il.run(data, goal=goal)
        except Exception as exc:
            logger.error("Intelligence loop error: %s", exc)
            return {"data_quality": 0, "decision": {"action": "error", "confidence": "none"}, "plan": {"actions": 0}}

    def _phase_agents(self, intel_result: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
        """Phase 3: Route tasks to specialized agents."""
        result = {"tasks_routed": 0, "agents_used": [], "agent_results": []}

        try:
            from agents.manager.agent_manager import AgentManager
            from agents.communication.message_bus import MessageBus
            am = AgentManager()
            mb = MessageBus()

            # Register agents for this cycle
            for agent_type in ("product", "marketing", "customer", "analytics"):
                am.register_agent(agent_type, agent_type, {})

            # Route intelligence actions to appropriate agents
            plan = intel_result.get("plan", {})
            p1_actions = plan.get("priority_1", [])
            if isinstance(p1_actions, list):
                for action in p1_actions:
                    if not isinstance(action, dict):
                        continue
                    target = action.get("target", "")
                    agent_type = self._target_to_agent(target)

                    # Publish task to message bus
                    mb.publish(f"task.{agent_type}", {
                        "action": action,
                        "intel": {
                            "decision": intel_result.get("decision", {}),
                            "data_quality": intel_result.get("data_quality", 0),
                        },
                    }, sender="full_system_loop")

                    result["tasks_routed"] += 1
                    if agent_type not in result["agents_used"]:
                        result["agents_used"].append(agent_type)

            # Also route all ready execution targets
            execution = intel_result.get("execution", {})
            ready = execution.get("ready", [])
            if isinstance(ready, list):
                for item in ready:
                    if not isinstance(item, dict):
                        continue
                    target = item.get("target", "")
                    agent_type = self._target_to_agent(target)
                    mb.publish(f"execute.{agent_type}", item, sender="full_system_loop")
                    result["tasks_routed"] += 1
                    if agent_type not in result["agents_used"]:
                        result["agents_used"].append(agent_type)

        except Exception as exc:
            logger.warning("Agent coordination error: %s", exc)

        return result

    def _phase_execute(self, intel_result: dict[str, Any], agent_result: dict[str, Any]) -> dict[str, Any]:
        """Phase 4: Dispatch actions to real execution modules."""
        result = {"dispatched": 0, "queued": 0, "results": []}

        try:
            from core.bridge.execution_bridge import ExecutionBridge
            eb = ExecutionBridge()

            # Wire executors
            try:
                from execution.shopify.product_creator import ProductCreator
                from execution.shopify.product_updater import ProductUpdater
                eb.register_executor("shopify", "product.create_listing", ProductCreator())
                eb.register_executor("shopify", "pricing.update", ProductUpdater())
            except Exception:
                pass

            # Plan actions from intelligence result
            execution = intel_result.get("execution", {})
            ready = execution.get("ready", [])
            if isinstance(ready, list):
                for action_data in ready:
                    if not isinstance(action_data, dict):
                        continue
                    # Create action plans from intelligence output
                    actions = eb.plan_actions(
                        action_data.get("target", "unknown"),
                        action_data.get("payload", action_data),
                    )
                    result["queued"] += len(actions)

            # Auto-approve low-risk actions
            for action in eb.get_queue():
                if action.get("priority") in ("low", "medium"):
                    eb.approve_action(action["action_id"])

            # Execute approved actions
            executed = eb.execute_approved()
            result["dispatched"] = len(executed)
            result["results"] = executed

        except Exception as exc:
            logger.warning("Execution dispatch error: %s", exc)

        return result

    def _phase_memory(self, cycle_id: str, phases: dict[str, Any]) -> dict[str, Any]:
        """Phase 5: Store important results in vector memory."""
        stored = 0

        try:
            from memory.vector_store.vector_db import VectorDB
            from memory.short_term.cache import ShortTermCache
            vdb = VectorDB()
            cache = ShortTermCache()

            # Store decision in short-term cache
            intel = phases.get("intelligence", {})
            decision = intel.get("decision", {})
            if decision:
                cache.set(f"decision:{cycle_id}", decision, ttl=3600)
                stored += 1

            # Store a simple embedding of the cycle result for similarity search
            embedding = self._simple_embedding(phases)
            vdb.add("cycles", cycle_id, embedding, {
                "type": "cycle_result",
                "decision": str(decision.get("action", ""))[:100],
                "quality": intel.get("data_quality", 0),
            })
            stored += 1

        except Exception as exc:
            logger.warning("Memory storage error: %s", exc)

        return {"stored": stored}

    def _phase_learn(self, cycle_id: str, phases: dict[str, Any]) -> dict[str, Any]:
        """Phase 6: Feed outcomes back to knowledge system."""
        rules_updated = 0
        patterns_found = 0

        try:
            from knowledge.rules.rule_engine import RuleEngine
            re = RuleEngine()

            # Check if intelligence found patterns that should become rules
            intel = phases.get("intelligence", {})
            learning = intel.get("learning", {})
            patterns = learning.get("patterns", [])
            patterns_found = len(patterns)

            # Auto-generate rules from strong patterns
            for pattern in patterns:
                if not isinstance(pattern, dict):
                    continue
                if pattern.get("pattern") == "score_range":
                    min_score = pattern.get("min", 0)
                    if min_score > 0:
                        re.add_rule(
                            f"auto_min_score_{min_score}",
                            condition={"total_score": {"lt": min_score}},
                            action={"type": "notify", "message": f"Score below learned minimum {min_score}"},
                            priority=5,
                        )
                        rules_updated += 1

            # Record this cycle's outcome for the learning engine
            from core.learning.outcome_tracker import OutcomeTracker
            ot = OutcomeTracker()
            decision = intel.get("decision", {})
            exec_phase = phases.get("execution", {})
            ot.record_decision(cycle_id, "full_system_loop", {
                "action": decision.get("action", ""),
                "confidence": decision.get("confidence", ""),
                "data_quality": intel.get("data_quality", 0),
                "actions_dispatched": exec_phase.get("dispatched", 0),
            })

        except Exception as exc:
            logger.warning("Learning update error: %s", exc)

        return {"rules_updated": rules_updated, "patterns_found": patterns_found}

    # ── Helpers ──

    @staticmethod
    def _target_to_agent(target: str) -> str:
        """Map execution targets to agent types."""
        mapping = {
            "pricing_engine": "product",
            "seo_engine": "marketing",
            "content_engine": "content",
            "email_engine": "marketing",
            "customer_engine": "customer",
            "workflow_engine": "operations",
            "data_engine": "analytics",
        }
        return mapping.get(target, "product")

    @staticmethod
    def _simple_embedding(phases: dict[str, Any]) -> list[float]:
        """Create a simple numerical embedding from cycle data for vector search."""
        intel = phases.get("intelligence", {})
        exec_p = phases.get("execution", {})
        data_p = phases.get("data", {})

        # 8-dimension embedding capturing key metrics
        return [
            float(intel.get("data_quality", 0)) / 100.0,
            1.0 if intel.get("decision", {}).get("confidence") == "high" else 0.5 if intel.get("decision", {}).get("confidence") == "medium" else 0.2,
            float(intel.get("plan", {}).get("actions", 0)) / 10.0,
            float(exec_p.get("dispatched", 0)) / 10.0,
            float(data_p.get("products_processed", 0)) / 100.0,
            float(data_p.get("features_extracted", 0)) / 50.0,
            float(intel.get("learning", {}).get("past_outcomes", 0)) / 20.0,
            float(phases.get("agents", {}).get("tasks_routed", 0)) / 10.0,
        ]

    @staticmethod
    def _build_summary(phases: dict[str, Any], elapsed: float) -> str:
        """Human-readable summary of the full system cycle."""
        data = phases.get("data", {})
        intel = phases.get("intelligence", {})
        agents = phases.get("agents", {})
        exec_p = phases.get("execution", {})

        decision = intel.get("decision", {})
        lines = [
            f"Pipeline: {data.get('products_processed', 0)} products → {data.get('features_extracted', 0)} features",
            f"Decision: {decision.get('action', 'N/A')[:60]}",
            f"Confidence: {decision.get('confidence', 'N/A')}",
            f"Agents: {len(agents.get('agents_used', []))} active, {agents.get('tasks_routed', 0)} tasks routed",
            f"Execution: {exec_p.get('dispatched', 0)} dispatched, {exec_p.get('queued', 0)} queued",
            f"Time: {elapsed:.3f}s",
        ]
        return "\n".join(lines)

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(self._history[-limit:])
