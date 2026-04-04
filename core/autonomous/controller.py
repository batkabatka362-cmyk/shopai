"""AutonomousController — the main brain loop for autonomous store operation.

Connects all components into a single self-improving cycle:
  Data → Analysis → Decision → Action → Outcome → Learn → repeat

Each cycle:
  1. Fetch fresh store data (DataProvider)
  2. Run relevant engines (analysis, pricing, inventory, etc.)
  3. Convert engine output to proposed actions (DecisionExecutor)
  4. Execute approved actions (ActionExecutor)
  5. Track outcomes (OutcomeTracker)
  6. Learn from outcomes (LearningPipeline)
  7. Adjust future decisions based on learning
"""
from __future__ import annotations

import time
import threading
from typing import Any

from utils.logger import get_logger

logger = get_logger("autonomous")


class AutonomousController:
    """Self-improving autonomous e-commerce controller."""

    def __init__(self, store_manager: Any = None, auto_approve: bool = False) -> None:
        self._store_manager = store_manager
        self._auto_approve = auto_approve
        self._running = False
        self._cycle_count = 0
        self._cycle_thread: threading.Thread | None = None
        self._cycle_interval = 600  # 10 minutes default
        self._cycle_history: list[dict[str, Any]] = []
        self._max_history = 100

        # Components (lazy init)
        self._data_provider = None
        self._action_executor = None
        self._decision_executor = None
        self._learning_pipeline = None
        self._performance_tracker = None

    def initialize(self, store_manager: Any = None) -> dict[str, Any]:
        """Initialize all components."""
        if store_manager:
            self._store_manager = store_manager

        if not self._store_manager:
            from data_pipeline.store.store_manager import StoreManager
            self._store_manager = StoreManager()

        from data_pipeline.store.data_provider import DataProvider
        from execution.action_executor import ActionExecutor, DecisionExecutor

        self._data_provider = DataProvider(self._store_manager)
        self._action_executor = ActionExecutor(self._store_manager)
        self._action_executor.set_auto_approve(self._auto_approve)
        self._decision_executor = DecisionExecutor(self._action_executor)

        self._learning_pipeline = LearningPipeline(self._store_manager)
        self._performance_tracker = PerformanceTracker(self._store_manager)

        # System layer integration
        try:
            from core.system.shared_memory import get_shared_memory
            from core.system.llm_adapter import get_llm
            from core.system.adaptive_skills import get_adaptive_skills
            self._memory = get_shared_memory()
            self._llm = get_llm()
            self._skills = get_adaptive_skills()
        except Exception:
            self._memory = None
            self._llm = None
            self._skills = None

        logger.info("AutonomousController initialized")
        return {"status": "initialized", "auto_approve": self._auto_approve}

    # ── Single Cycle ─────────────────────────────────────────

    def run_cycle(self, store_id: str = "") -> dict[str, Any]:
        """Run one full autonomous cycle."""
        sid = store_id or (self._store_manager.active_store_id if self._store_manager else "")
        if not sid:
            return {"status": "error", "error": "No store specified"}

        self._cycle_count += 1
        cycle_id = f"cycle_{self._cycle_count}_{int(time.time())}"
        start = time.monotonic()

        logger.info("Starting cycle %s for store %s", cycle_id, sid)

        cycle_result: dict[str, Any] = {
            "cycle_id": cycle_id,
            "store_id": sid,
            "cycle_number": self._cycle_count,
            "phases": {},
        }

        # Phase 1: DATA — Fetch current store state
        data = self._phase_data(sid)
        cycle_result["phases"]["data"] = {
            "products": len(data.get("products", [])),
            "orders": len(data.get("order_data", [])),
            "customers": len(data.get("customer_data", [])),
            "source": data.get("source", "unknown"),
        }

        # Populate shared memory
        if self._memory:
            self._memory.load_store_data(
                data.get("products", []),
                data.get("order_data", []),
                data.get("customer_data", []),
                sid,
            )

        # Get skill recommendations
        if self._skills:
            recommended = self._skills.recommend_skills({
                "products": data.get("products", []),
                "orders": data.get("order_data", []),
                "customers": data.get("customer_data", []),
            })
            cycle_result["phases"]["skills"] = {
                "recommended": len(recommended),
                "top": [r["name"] for r in recommended[:5]],
            }

        # Phase 1b: BRAIN THINK — autonomous reasoning
        try:
            from core.brain.decision_brain import DecisionBrain
            brain = DecisionBrain()
            thought = brain.think(data)
            cycle_result["phases"]["brain"] = {
                "health_score": thought.get("health_score", 0),
                "problems": len(thought.get("problems", [])),
                "opportunities": len(thought.get("opportunities", [])),
                "decisions": len(thought.get("decisions", [])),
                "top_action": thought["action_plan"][0]["action"] if thought.get("action_plan") else "none",
            }
            # Store brain decisions for phase 3
            cycle_result["_brain_decisions"] = thought.get("decisions", [])
        except Exception as exc:
            logger.debug("Brain think: %s", exc)
            thought = {}

        # Phase 2: ANALYZE — Run analysis engines
        analysis = self._phase_analyze(sid, data)
        total_insights = 0
        _insight_keys = (
            "recommendations", "winners", "ranked_products",
            "reorder_plan", "alerts", "segments",
            "reorder_recommendations", "opportunities",
        )
        for a in analysis.values():
            if isinstance(a, dict) and a.get("status") != "error":
                d = a.get("data")
                if isinstance(d, dict):
                    for key in _insight_keys:
                        val = d.get(key)
                        if isinstance(val, list):
                            total_insights += len(val)
                    if d.get("recommended_price"):
                        total_insights += 1
        cycle_result["phases"]["analysis"] = {
            "engines_run": len([a for a in analysis.values() if isinstance(a, dict) and a.get("status") != "error"]),
            "insights": total_insights,
        }

        # Phase 3: DECIDE — Convert brain decisions + analysis to actions
        brain_decisions = cycle_result.get("_brain_decisions", [])
        decisions = self._phase_decide(sid, analysis, brain_decisions)
        cycle_result["phases"]["decisions"] = {
            "proposed": len(decisions),
            "types": list(set(d.get("type", "") for d in decisions)),
        }

        # Phase 4: EXECUTE — Run approved actions
        executions = self._phase_execute()
        cycle_result["phases"]["execution"] = {
            "executed": len([e for e in executions if e.get("status") == "executed"]),
            "failed": len([e for e in executions if e.get("status") == "failed"]),
            "pending": len(self._action_executor.get_pending()) if self._action_executor else 0,
        }

        # Phase 5: LEARN — Track outcomes and update weights
        learning = self._phase_learn(sid, cycle_id, analysis, executions)
        cycle_result["phases"]["learning"] = learning

        # Phase 6: REPORT — Generate cycle summary
        elapsed = time.monotonic() - start
        cycle_result["duration_s"] = round(elapsed, 2)
        cycle_result["status"] = "complete"

        # Phase 6b: SELF-IMPROVE — review cycle and learn from mistakes
        try:
            from core.ai.self_improver import SelfImprover
            improver = SelfImprover()
            review = improver.review_cycle(cycle_result)
            cycle_result["phases"]["self_improvement"] = review
        except Exception as exc:
            logger.debug("Self-improvement review: %s", exc)

        # Track performance
        if self._performance_tracker:
            self._performance_tracker.record_cycle(cycle_result)

        # Save to history
        self._cycle_history.append(cycle_result)
        if len(self._cycle_history) > self._max_history:
            self._cycle_history = self._cycle_history[-self._max_history:]

        logger.info("Cycle %s complete in %.1fs: %d insights, %d actions",
                     cycle_id, elapsed,
                     cycle_result["phases"]["analysis"]["insights"],
                     cycle_result["phases"]["decisions"]["proposed"])

        return cycle_result

    # ── Phase Implementations ────────────────────────────────

    def _phase_data(self, store_id: str) -> dict[str, Any]:
        """Phase 1: Fetch current store data (sync first, then read from DB)."""
        if not self._data_provider or not self._store_manager:
            return {}

        # Sync from Shopify first if possible
        try:
            from data_pipeline.store.sync_service import SyncService
            sync = SyncService(self._store_manager)
            sync.sync_store(store_id)
        except Exception as exc:
            logger.debug("Pre-cycle sync: %s", exc)

        # Now read from DB (freshly synced)
        data: dict[str, Any] = {"store_id": store_id, "source": "database"}
        products = self._store_manager.get_products(store_id)
        orders = self._store_manager.get_orders(store_id)
        customers = self._store_manager.get_customers(store_id)

        data["products"] = products if products else self._data_provider._mock_products()
        data["order_data"] = orders if orders else self._data_provider._mock_orders()
        data["customer_data"] = customers if customers else self._data_provider._mock_customers()

        if not products and not orders and not customers:
            data["source"] = "mock"

        return data

    def _phase_analyze(self, store_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Phase 2: Run key analysis engines + AI reasoning."""
        from engines.registry import get_engine

        engines_to_run = [
            "pricing", "inventory", "product_ranking",
            "customer_segmentation", "product_research",
        ]
        results: dict[str, Any] = {}

        for engine_name in engines_to_run:
            try:
                engine = get_engine(engine_name)
                if not engine:
                    continue
                # Build engine-compatible input
                engine_data = self._build_engine_input(engine_name, data)
                result = engine.run(engine_data)
                results[engine_name] = result if isinstance(result, dict) else {"status": "error", "error": "engine returned non-dict"}
            except Exception as exc:
                logger.warning("Engine %s failed: %s", engine_name, exc)
                results[engine_name] = {"status": "error", "error": str(exc)}

        # AI-enhanced analysis layer
        try:
            from core.ai.reasoning import ai_reason
            ai_pricing = ai_reason("pricing_optimization", products=data.get("products", []))
            if ai_pricing.get("recommendations"):
                results["ai_pricing"] = {
                    "status": "success",
                    "data": ai_pricing,
                    "source": ai_pricing.get("source", "unknown"),
                }
            ai_inventory = ai_reason("inventory_management", products=data.get("products", []))
            if ai_inventory.get("recommendations"):
                results["ai_inventory"] = {
                    "status": "success",
                    "data": ai_inventory,
                    "source": ai_inventory.get("source", "unknown"),
                }
        except Exception as exc:
            logger.debug("AI reasoning layer: %s", exc)

        return results

    def _phase_decide(self, store_id: str, analysis: dict[str, Any],
                      brain_decisions: list[dict] | None = None) -> list[dict[str, Any]]:
        """Phase 3: Convert brain decisions + analysis to proposed actions."""
        if not self._action_executor:
            return []

        all_decisions: list[dict[str, Any]] = []

        # Brain decisions → actions
        for dec in (brain_decisions or []):
            action = self._action_executor.propose_action({
                "type": dec.get("type", "brain_recommendation"),
                "store_id": store_id,
                "engine": "brain",
                "confidence": dec.get("confidence", 0.7),
                "reason": dec.get("reason", ""),
                "params": {"priority": dec.get("priority", 4)},
            })
            all_decisions.append(action)

        # From engine results — convert to actions
        # Inventory alerts
        inv = analysis.get("inventory", {})
        if isinstance(inv, dict) and inv.get("status") != "error":
            inv_data = inv.get("data", {})
            if isinstance(inv_data, dict):
                for alert in inv_data.get("alerts", [])[:5]:
                    if isinstance(alert, dict) and alert.get("severity") in ("critical", "high"):
                        all_decisions.append(self._action_executor.propose_action({
                            "type": "inventory_alert",
                            "store_id": store_id,
                            "engine": "inventory",
                            "confidence": 0.85,
                            "reason": alert.get("message", str(alert)[:80]),
                            "params": alert,
                        }))

        # Pricing recommendation — only if it RAISES price or has competitor data
        pr = analysis.get("pricing", {})
        if isinstance(pr, dict) and pr.get("status") != "error":
            pr_data = pr.get("data", {})
            if isinstance(pr_data, dict) and pr_data.get("recommended_price"):
                rec_price = pr_data["recommended_price"]
                # Get current price from first product in data
                products = data.get("products", []) if hasattr(self, '_last_data') else []
                current_price = products[0].get("price", 0) if products else 0

                # Only propose if raising price or confidence is high
                if rec_price > current_price or pr_data.get("confidence", 0) > 0.7:
                    all_decisions.append(self._action_executor.propose_action({
                        "type": "pricing_recommendation",
                        "store_id": store_id,
                        "engine": "pricing",
                        "confidence": pr_data.get("confidence", 0.5),
                        "reason": pr_data.get("rationale", "")[:100],
                        "params": {
                            "recommended_price": rec_price,
                            "strategy": pr_data.get("strategy", ""),
                        },
                    }))

        # From AI reasoning recommendations
        for key in ("ai_pricing", "ai_inventory"):
            result = analysis.get(key, {})
            if not isinstance(result, dict) or result.get("status") == "error":
                continue
            data = result.get("data", {})
            for rec in data.get("recommendations", []):
                if not isinstance(rec, dict):
                    continue
                # Convert AI recommendation to action
                if rec.get("recommended_price") and rec.get("product_id"):
                    action = self._action_executor.propose_action({
                        "type": "update_price",
                        "store_id": store_id,
                        "engine": key,
                        "confidence": rec.get("confidence", 0.5),
                        "reason": rec.get("reason", "AI recommendation"),
                        "params": {
                            "product_id": rec.get("product_id", ""),
                            "variant_id": rec.get("variant_id", ""),
                            "price": rec["recommended_price"],
                        },
                    })
                    all_decisions.append(action)
                elif rec.get("action") == "urgent_restock" or rec.get("priority") == "critical":
                    action = self._action_executor.propose_action({
                        "type": "alert",
                        "store_id": store_id,
                        "engine": key,
                        "confidence": rec.get("confidence", 0.8),
                        "reason": rec.get("reason", "Urgent attention needed"),
                        "params": {"product": rec.get("product", ""), "action": rec.get("action", "")},
                    })
                    all_decisions.append(action)

        return all_decisions

    def _phase_execute(self) -> list[dict[str, Any]]:
        """Phase 4: Execute approved actions."""
        if not self._action_executor:
            return []

        if self._auto_approve:
            # In auto mode, actions were already executed when proposed
            return self._action_executor.get_action_log(limit=20)

        # In manual mode, only execute pre-approved actions
        return []

    def _phase_learn(self, store_id: str, cycle_id: str,
                     analysis: dict[str, Any], executions: list[dict[str, Any]]) -> dict[str, Any]:
        """Phase 5: Track outcomes and update learning weights."""
        if not self._learning_pipeline:
            return {"status": "skipped"}

        return self._learning_pipeline.process_cycle(
            store_id=store_id,
            cycle_id=cycle_id,
            analysis_results=analysis,
            execution_results=executions,
        )

    @staticmethod
    def _build_engine_input(engine_name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Build engine-compatible input from raw store data.

        Most engines expect: {status: "success", data: {product: {...}, ...}}
        Some (product_research) expect: {products: [...]}
        """
        products = data.get("products", [])
        orders = data.get("order_data", [])
        customers = data.get("customer_data", [])

        # Engines that take the flat format directly
        if engine_name in ("product_research",):
            return {"products": products}

        # Standard engine format: {status, data: {...}}
        product = {}
        for p in products:
            if p.get("cost", 0) > 0:
                product = p
                break
        if not product and products:
            product = products[0]

        # Customer segmentation needs customers at top level of data
        if engine_name == "customer_segmentation":
            return {
                "status": "success",
                "data": {"customer_data": customers, "customers": customers},
                "meta": {"engine": engine_name},
                "error": None,
            }

        # Map DB field names to engine field names
        if product:
            product = dict(product)
            product.setdefault("cogs", product.get("cost", 0))
            product.setdefault("shipping_cost", 0)
            product.setdefault("weight_kg", product.get("weight", 0))

        engine_data: dict[str, Any] = {
            "status": "success",
            "data": {
                "product": product,
                "products": products,
                "order_data": orders,
                "customer_data": customers,
                "inventory_data": [
                    {"product_id": p.get("id"), "name": p.get("name"),
                     "quantity": p.get("inventory_quantity", 0),
                     "price": p.get("price", 0), "cost": p.get("cost", 0)}
                    for p in products
                ],
            },
            "meta": {"engine": engine_name},
            "error": None,
        }
        return engine_data

    # ── Auto-Run ─────────────────────────────────────────────

    def start(self, interval_seconds: int = 600) -> dict[str, Any]:
        """Start autonomous operation."""
        if self._running:
            return {"status": "already_running"}

        self.initialize()
        self._cycle_interval = interval_seconds
        self._running = True
        self._cycle_thread = threading.Thread(
            target=self._auto_cycle_loop, daemon=True, name="shopai-autonomous"
        )
        self._cycle_thread.start()
        logger.info("Autonomous mode started (every %ds)", interval_seconds)
        return {"status": "started", "interval": interval_seconds}

    def stop(self) -> dict[str, Any]:
        """Stop autonomous operation."""
        self._running = False
        logger.info("Autonomous mode stopped after %d cycles", self._cycle_count)
        return {"status": "stopped", "cycles_completed": self._cycle_count}

    def _auto_cycle_loop(self) -> None:
        while self._running:
            try:
                stores = self._store_manager.list_stores() if self._store_manager else []
                for store in stores:
                    if not self._running:
                        break
                    self.run_cycle(store["store_id"])
            except Exception as exc:
                logger.error("Auto-cycle error: %s", exc)

            for _ in range(self._cycle_interval):
                if not self._running:
                    break
                time.sleep(1)

    # ── Status & History ─────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "cycles_completed": self._cycle_count,
            "auto_approve": self._auto_approve,
            "interval_s": self._cycle_interval,
            "pending_actions": len(self._action_executor.get_pending()) if self._action_executor else 0,
            "performance": self._performance_tracker.get_summary() if self._performance_tracker else {},
        }

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._cycle_history[-limit:]


class LearningPipeline:
    """Connects action outcomes to the learning system.

    After each cycle:
      1. Record what decisions were made
      2. Compare with previous outcomes
      3. Update Bayesian weights
      4. Store learning in episodic memory
    """

    def __init__(self, store_manager: Any = None) -> None:
        self._store_manager = store_manager
        self._outcome_tracker = None
        self._learning_engine = None

    def _init_components(self) -> None:
        if not self._outcome_tracker:
            try:
                from core.learning.outcome_tracker import OutcomeTracker
                self._outcome_tracker = OutcomeTracker()
            except Exception:
                pass
        if not self._learning_engine:
            try:
                from core.learning.learning_engine import LearningEngine
                self._learning_engine = LearningEngine()
            except Exception:
                pass

    def process_cycle(self, store_id: str, cycle_id: str,
                      analysis_results: dict[str, Any],
                      execution_results: list[dict[str, Any]]) -> dict[str, Any]:
        """Process a complete cycle through the learning pipeline."""
        self._init_components()

        learning_result: dict[str, Any] = {
            "decisions_recorded": 0,
            "outcomes_recorded": 0,
            "patterns_found": 0,
            "weight_updates": 0,
        }

        # Step 1: Record decisions from analysis
        for engine_name, result in analysis_results.items():
            if result.get("status") == "error":
                continue
            try:
                if self._outcome_tracker:
                    decision_id = f"{cycle_id}_{engine_name}"
                    self._outcome_tracker.record_decision(
                        decision_id, engine_name,
                        {"engine": engine_name, "result_summary": _summarize(result)},
                    )
                    learning_result["decisions_recorded"] += 1
            except Exception as exc:
                logger.debug("Decision recording failed: %s", exc)

        # Step 2: Record outcomes from executions
        for execution in execution_results:
            if not isinstance(execution, dict):
                continue
            try:
                if self._outcome_tracker and execution.get("engine"):
                    decision_id = f"{cycle_id}_{execution['engine']}"
                    self._outcome_tracker.record_outcome(
                        decision_id, execution["engine"],
                        {
                            "success": execution.get("status") == "executed",
                            "action_type": execution.get("type", ""),
                            "duration_s": execution.get("duration_s", 0),
                        },
                    )
                    learning_result["outcomes_recorded"] += 1
            except Exception as exc:
                logger.debug("Outcome recording failed: %s", exc)

        # Step 3: Extract patterns and update weights
        try:
            patterns = self._extract_patterns(analysis_results)
            learning_result["patterns_found"] = len(patterns)
            weight_updates = self._update_weights(patterns)
            learning_result["weight_updates"] = weight_updates
        except Exception as exc:
            logger.debug("Pattern extraction failed: %s", exc)

        # Step 4: Store in episodic memory
        try:
            self._store_episode(store_id, cycle_id, learning_result)
        except Exception:
            pass

        learning_result["status"] = "complete"
        return learning_result

    def _extract_patterns(self, analysis_results: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract actionable patterns from analysis results."""
        patterns = []

        for engine_name, result in analysis_results.items():
            if not isinstance(result, dict) or result.get("status") == "error":
                continue

            data = result.get("data", {})
            recommendations = data.get("recommendations", [])

            # Count recommendation types
            for rec in recommendations:
                if isinstance(rec, dict):
                    patterns.append({
                        "engine": engine_name,
                        "type": rec.get("type", rec.get("action", "general")),
                        "confidence": rec.get("confidence", 0),
                        "impact": rec.get("expected_impact", rec.get("impact", "unknown")),
                    })

        return patterns

    def _update_weights(self, patterns: list[dict[str, Any]]) -> int:
        """Update Bayesian learning weights based on patterns."""
        try:
            from core.intelligence.loop.stage_learn import _update_weight, LEARNABLE_FACTORS
        except ImportError:
            return 0

        updates = 0
        for pattern in patterns:
            confidence = pattern.get("confidence", 0)
            if confidence > 0.7:
                # High confidence → reinforce
                engine = pattern.get("engine", "")
                if "pricing" in engine or "price" in engine:
                    _update_weight("price", 1)
                    updates += 1
                elif "inventory" in engine or "demand" in engine:
                    _update_weight("demand", 1)
                    updates += 1
                elif "margin" in engine:
                    _update_weight("margin", 1)
                    updates += 1
                elif "competition" in engine or "competitor" in engine:
                    _update_weight("competition", 1)
                    updates += 1

        return updates

    def _store_episode(self, store_id: str, cycle_id: str, learning: dict[str, Any]) -> None:
        """Store learning episode in long-term memory."""
        try:
            from memory.long_term.persistent_store import PersistentStore
            store = PersistentStore()
            store.store(
                f"learning_{cycle_id}",
                learning,
                namespace="learning_history",
                metadata={"store_id": store_id, "cycle_id": cycle_id},
            )
        except Exception:
            pass

    def get_learning_summary(self) -> dict[str, Any]:
        """Get summary of what the system has learned."""
        self._init_components()
        result: dict[str, Any] = {"engines": {}}

        if self._learning_engine:
            try:
                system_analysis = self._learning_engine.analyze_system()
                result["system"] = system_analysis
            except Exception:
                pass

        # Get current weights
        try:
            from core.intelligence.loop.weight_manager import _learned_weights
            result["weights"] = dict(_learned_weights)
        except Exception:
            result["weights"] = {}

        return result


class PerformanceTracker:
    """Tracks autonomous controller performance over time."""

    def __init__(self, store_manager: Any = None) -> None:
        self._cycles: list[dict[str, Any]] = []
        self._store_manager = store_manager

    def record_cycle(self, cycle_result: dict[str, Any]) -> None:
        self._cycles.append({
            "cycle_id": cycle_result.get("cycle_id", ""),
            "store_id": cycle_result.get("store_id", ""),
            "duration_s": cycle_result.get("duration_s", 0),
            "insights": cycle_result.get("phases", {}).get("analysis", {}).get("insights", 0),
            "actions_proposed": cycle_result.get("phases", {}).get("decisions", {}).get("proposed", 0),
            "actions_executed": cycle_result.get("phases", {}).get("execution", {}).get("executed", 0),
            "learning": cycle_result.get("phases", {}).get("learning", {}),
            "timestamp": time.time(),
        })
        if len(self._cycles) > 500:
            self._cycles = self._cycles[-500:]

    def get_summary(self) -> dict[str, Any]:
        if not self._cycles:
            return {"total_cycles": 0}

        total = len(self._cycles)
        total_insights = sum(c.get("insights", 0) for c in self._cycles)
        total_actions = sum(c.get("actions_proposed", 0) for c in self._cycles)
        total_executed = sum(c.get("actions_executed", 0) for c in self._cycles)
        avg_duration = sum(c.get("duration_s", 0) for c in self._cycles) / total

        return {
            "total_cycles": total,
            "total_insights": total_insights,
            "total_actions_proposed": total_actions,
            "total_actions_executed": total_executed,
            "avg_cycle_duration_s": round(avg_duration, 2),
            "learning_updates": sum(
                c.get("learning", {}).get("weight_updates", 0) for c in self._cycles
            ),
        }

    def get_trend(self, last_n: int = 10) -> dict[str, Any]:
        """Get recent performance trend."""
        recent = self._cycles[-last_n:]
        if len(recent) < 2:
            return {"trend": "insufficient_data"}

        first_half = recent[:len(recent)//2]
        second_half = recent[len(recent)//2:]

        first_insights = sum(c.get("insights", 0) for c in first_half) / len(first_half)
        second_insights = sum(c.get("insights", 0) for c in second_half) / len(second_half)

        if second_insights > first_insights * 1.1:
            trend = "improving"
        elif second_insights < first_insights * 0.9:
            trend = "declining"
        else:
            trend = "stable"

        return {
            "trend": trend,
            "recent_avg_insights": round(second_insights, 1),
            "previous_avg_insights": round(first_insights, 1),
        }


def _summarize(result: dict[str, Any]) -> dict[str, Any]:
    """Create a compact summary of engine output for storage."""
    data = result.get("data", {})
    return {
        "status": result.get("status", "unknown"),
        "recommendations_count": len(data.get("recommendations", [])),
        "has_alerts": bool(data.get("alerts", [])),
    }
