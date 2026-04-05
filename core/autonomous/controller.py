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
            from core.memory.unified_memory import get_unified_memory
            from core.system.llm_adapter import get_llm
            from core.system.adaptive_skills import get_adaptive_skills
            from core.autonomous.layer_dispatcher import LayerDispatcher
            from core.autonomous.agent_dispatcher import AgentDispatcher
            self._unified_memory = get_unified_memory()
            self._unified_memory.initialize()
            self._memory = self._unified_memory._shared  # Backward compat
            self._llm = get_llm()
            self._skills = get_adaptive_skills()
            self._layer_dispatcher = LayerDispatcher()
            self._layer_dispatcher.initialize()
            self._agent_dispatcher = AgentDispatcher()
            self._agent_dispatcher.initialize()
        except Exception:
            self._unified_memory = None
            self._memory = None
            self._llm = None
            self._skills = None
            self._layer_dispatcher = None
            self._agent_dispatcher = None

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

        # Clear working memory from previous cycle
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            mi.clear_working()
        except Exception:
            pass

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

        # Phase 1-pre: PRICE HISTORY — record current prices
        try:
            from data_pipeline.tracking.price_history import get_price_history
            ph = get_price_history()
            recorded = ph.record_prices_batch(data.get("products", []), store_id=sid)
            if recorded:
                cycle_result["phases"]["price_tracking"] = {"new_prices": recorded}
        except Exception as exc:
            logger.debug("Price history: %s", exc)

        # Phase 1a: DATA QUALITY — validate and score data before AI uses it
        try:
            from data_pipeline.quality import get_data_quality
            dq = get_data_quality()
            quality_report = dq.run(data)
            cycle_result["phases"]["data_quality"] = {
                "score": quality_report.get("overall_score", 0),
                "products_valid": quality_report["products"]["valid"],
                "issues": len(quality_report.get("issues", [])),
                "anomalies": len(quality_report.get("anomalies", [])),
                "top_issue": quality_report["issues"][0]["message"][:80] if quality_report.get("issues") else "none",
            }
            # Use cleaned products for all subsequent phases
            if quality_report.get("cleaned_products"):
                data["products"] = quality_report["cleaned_products"]
        except Exception as exc:
            logger.debug("Data quality pipeline: %s", exc)

        # Populate unified memory (skip if same data as last cycle)
        _data_key = f"{sid}_{len(data.get('products', []))}_{len(data.get('order_data', []))}"
        if not hasattr(self, '_last_data_key') or self._last_data_key != _data_key:
            self._last_data_key = _data_key
            if hasattr(self, '_unified_memory') and self._unified_memory:
                self._unified_memory.ingest_store_data(
                    data.get("products", []),
                    data.get("order_data", []),
                    data.get("customer_data", []),
                    sid,
                )
            elif self._memory:
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

        # Phase 1c: COMPETITOR SCAN — get real market data
        try:
            from core.ai.competitor_monitor import get_competitor_monitor
            cm = get_competitor_monitor()
            comp_scan = cm.scan_competitors(data.get("products", []), max_products=5)
            cycle_result["phases"]["competitor_scan"] = {
                "products_scanned": comp_scan.get("products_scanned", 0),
                "position": comp_scan.get("summary", {}),
            }
            # Inject competitor data into store data for brain/engines
            data["competitor_data"] = comp_scan.get("results", [])
            data["market_position"] = comp_scan.get("summary", {})
        except Exception as exc:
            logger.debug("Competitor scan: %s", exc)

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

        # Store brain context in working memory for other phases
        try:
            mi.set_working("health_score", thought.get("health_score", 0))
            mi.set_working("top_problems", thought.get("problems", [])[:3])
            mi.set_working("top_opportunities", thought.get("opportunities", [])[:3])
        except Exception:
            pass

        # Phase 1d: COGNITIVE THINKING — deep understanding + reasoning
        try:
            from core.brain.cognitive import get_cognitive_module
            cog = get_cognitive_module()

            # Get recent memories for analysis
            cog_memories = []
            if hasattr(self, '_unified_memory') and self._unified_memory:
                try:
                    cog_memories = self._unified_memory._memory_intel.retrieve(
                        "pricing", limit=20) if self._unified_memory._memory_intel else []
                except Exception:
                    pass

            rules = []
            if hasattr(self, '_unified_memory') and self._unified_memory:
                try:
                    rules = self._unified_memory.get_learned_rules()
                except Exception:
                    pass

            # Deep analysis (limit products for speed)
            deep = cog.think_deep(data.get("products", [])[:5], cog_memories, rules)
            cycle_result["phases"]["cognitive"] = {
                "products_analyzed": deep["understanding"]["products_analyzed"],
                "critical_products": deep["understanding"]["critical"],
                "clusters": deep["understanding"]["clusters"],
                "hypotheses": deep["reasoning"]["hypotheses"],
                "near_misses": deep["failure_analysis"]["near_misses"],
                "questions": deep["curiosity"]["questions"][:3],
                "exploration": deep["curiosity"]["exploration"].get("suggest", ""),
            }

            # Record exploration
            for dec in brain_decisions:
                cog.curiosity.record_exploration(dec.get("type", "unknown"))

            # Track confidence calibration from recent decisions
            for m in cog_memories[:10]:
                action = m.get("action", "")
                confidence = m.get("confidence", 0.5)
                score = m.get("score", 3.0)
                if action:
                    cog.reflection.record_decision(action, confidence, score)
        except Exception as exc:
            logger.debug("Cognitive thinking: %s", exc)

        # Phase 1f: RL PRICING — learned pricing recommendations
        try:
            from models.rl.pricing_agent import get_pricing_agent
            rl = get_pricing_agent()
            # Learn from memory every 5 cycles
            learn_result = {}
            if self._cycle_count % 5 == 1:
                learn_result = rl.learn_from_memory()
            # Get recommendations
            rl_recs = rl.recommend_all(data.get("products", []))
            cycle_result["phases"]["rl_pricing"] = {
                "recommendations": len(rl_recs),
                "learned_from": learn_result.get("learned", 0),
                "top_action": rl_recs[0]["action"] if rl_recs else "none",
                "avg_confidence": round(
                    sum(r["confidence"] for r in rl_recs) / max(len(rl_recs), 1), 2
                ),
            }
        except Exception as exc:
            logger.debug("RL pricing: %s", exc)

        # Phase 1g: CUSTOMER SEGMENTATION — segment customers
        try:
            from models.ml.customer_segmentation import get_customer_segmentation
            seg = get_customer_segmentation()
            seg_result = seg.segment(data.get("customer_data", []))
            if seg_result.get("total_customers", 0) > 0:
                cycle_result["phases"]["segmentation"] = {
                    "customers": seg_result.get("total_customers", 0),
                    "segments": seg_result.get("segment_distribution", {}),
                }
        except Exception as exc:
            logger.debug("Segmentation: %s", exc)

        # Phase 1h: DEMAND FORECASTING — predict future demand
        try:
            from models.ml.demand_forecast import get_demand_forecaster
            fc = get_demand_forecaster()
            fc_result = fc.forecast(
                data.get("products", []),
                data.get("order_data", []),
            )
            cycle_result["phases"]["demand_forecast"] = {
                "products": fc_result.get("total_products", 0),
                "restock_needed": fc_result.get("restock_needed", 0),
                "trends": fc_result.get("trend_summary", {}),
            }
        except Exception as exc:
            logger.debug("Demand forecast: %s", exc)

        # Phase 1i: IMAGE SOURCING — find images for products without them
        try:
            from execution.content.image_sourcer import get_image_sourcer
            sourcer = get_image_sourcer()
            img_result = sourcer.source_images(data.get("products", []), max_products=5)
            if img_result.get("images_found", 0) > 0:
                cycle_result["phases"]["image_sourcing"] = {
                    "products_needing": img_result.get("products_without_images", 0),
                    "images_found": img_result.get("images_found", 0),
                    "method": img_result.get("method", ""),
                }
        except Exception as exc:
            logger.debug("Image sourcing: %s", exc)

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

        # Phase 2b: LAYERS — Run all 12 layers (131 engines grouped by domain)
        if hasattr(self, '_layer_dispatcher') and self._layer_dispatcher:
            try:
                layer_result = self._layer_dispatcher.run_all(data)
                cycle_result["phases"]["layers"] = {
                    "layers_run": layer_result.get("layers_run", 0),
                    "total_insights": layer_result.get("total_insights", 0),
                    "duration_s": layer_result.get("duration_s", 0),
                }
                total_insights += layer_result.get("total_insights", 0)
            except Exception as exc:
                logger.debug("Layer dispatch: %s", exc)
                cycle_result["phases"]["layers"] = {"error": str(exc)[:80]}

        # Phase 3: DECIDE — Convert brain decisions + analysis to actions
        brain_decisions = cycle_result.get("_brain_decisions", [])
        decisions = self._phase_decide(sid, analysis, brain_decisions)
        cycle_result["phases"]["decisions"] = {
            "proposed": len(decisions),
            "types": list(set(d.get("type", "") for d in decisions)),
        }

        # Phase 3b: AGENTS — Dispatch decisions to domain agents
        if hasattr(self, '_agent_dispatcher') and self._agent_dispatcher:
            try:
                agent_result = self._agent_dispatcher.dispatch(
                    brain_decisions, {"products": data.get("products", []),
                                      "orders": data.get("order_data", []),
                                      "customers": data.get("customer_data", [])},
                )
                cycle_result["phases"]["agents"] = {
                    "dispatched": agent_result.get("dispatched", 0),
                    "agents_available": agent_result.get("agents_available", 0),
                }
            except Exception as exc:
                logger.debug("Agent dispatch: %s", exc)
                cycle_result["phases"]["agents"] = {"error": str(exc)[:80]}

        # Phase 4: EXECUTE — Smart execution with simulation + learning
        executions = self._phase_execute()

        # Phase 4a: SMART EXECUTION — simulate all pending decisions
        smart_exec_result = {}
        try:
            from execution.smart_executor import get_smart_executor
            se = get_smart_executor()
            pending = self._action_executor.get_pending() if self._action_executor else []
            if pending:
                smart_exec_result = se.execute_batch(pending, store_data=data)
                cycle_result["phases"]["smart_execution"] = {
                    "total": smart_exec_result.get("total", 0),
                    "simulated": smart_exec_result.get("simulated", 0),
                    "dry_run": smart_exec_result.get("dry_run", 0),
                    "live": smart_exec_result.get("live", 0),
                    "avg_score": smart_exec_result.get("avg_score", 0),
                }
                # Smart execution handles these, clear from pending
                if self._action_executor:
                    self._action_executor._pending_actions.clear()
        except Exception as exc:
            logger.debug("Smart execution: %s", exc)

        cycle_result["phases"]["execution"] = {
            "executed": len([e for e in executions if e.get("status") == "executed"]),
            "smart_executed": smart_exec_result.get("total", 0),
            "failed": len([e for e in executions if e.get("status") == "failed"]),
            "pending": len(self._action_executor.get_pending()) if self._action_executor else 0,
        }

        # Phase 4b: INTELLIGENCE CYCLE — run full AI cycle on key decisions
        if hasattr(self, '_unified_memory') and self._unified_memory:
            try:
                ic_results = []
                categories = ["product", "pricing", "marketing"]
                for cat in categories:
                    ic_result = self._unified_memory.run_intelligence_cycle(
                        category=cat, data=data, store_id=sid,
                    )
                    ic_results.append(ic_result)
                cycle_result["phases"]["intelligence_cycle"] = {
                    "cycles_run": len(ic_results),
                    "avg_score": round(
                        sum(r.get("score", 0) for r in ic_results) / max(len(ic_results), 1), 1
                    ),
                    "actions": [r.get("action", "none") for r in ic_results],
                    "memory_informed": sum(1 for r in ic_results if r.get("memory_informed")),
                }
            except Exception as exc:
                logger.debug("Intelligence cycle: %s", exc)

            # Capture engine results into data architecture
            try:
                for engine_name, result in analysis.items():
                    if isinstance(result, dict) and result.get("status") != "error":
                        self._unified_memory.capture_data(
                            domain="tool_usage",
                            data={"tool_name": engine_name, "success": True,
                                  "output_size": len(str(result))},
                            source="engine",
                            store_id=sid,
                        )
            except Exception:
                pass

        # Phase 5: LEARN — Track outcomes via all learning systems
        # Merge smart execution results into executions for learning
        all_executions = list(executions)
        se_results = smart_exec_result.get("results", []) if isinstance(smart_exec_result, dict) else []
        for se in se_results:
            all_executions.append({
                "engine": se.get("action_type", "smart_executor"),
                "type": se.get("action_type", ""),
                "status": "executed",
                "score": se.get("score", 3.0),
                "mode": se.get("mode", "simulate"),
                "duration_s": se.get("duration_s", 0),
            })

        learning = self._phase_learn(sid, cycle_id, analysis, all_executions)

        # Brain learning loop — learn from this cycle + smart executions
        try:
            from core.brain.learning_loop import LearningLoop
            brain_loop = LearningLoop()
            cycle_metrics = {
                "insights": cycle_result["phases"]["analysis"]["insights"],
                "actions_proposed": cycle_result["phases"]["decisions"]["proposed"],
                "smart_executed": len(se_results),
                "avg_exec_score": smart_exec_result.get("avg_score", 0) if isinstance(smart_exec_result, dict) else 0,
            }
            brain_learning = brain_loop.learn(
                "cycle", {"store_id": sid, "cycle": self._cycle_count},
                "autonomous_cycle",
                {"status": "complete", "insights": cycle_metrics["insights"],
                 "executions": len(se_results)},
                cycle_metrics,
            )
            learning["brain_learning"] = {
                "score": brain_learning.get("score", 0),
                "success": brain_learning.get("success", False),
            }

            # Learn from each smart execution individually
            for se in se_results:
                brain_loop.learn(
                    category=se.get("action_type", "execution"),
                    input_data={"action": se.get("action_type", ""), "mode": se.get("mode", "")},
                    action=se.get("action_type", "unknown"),
                    result=se.get("actual_outcome", {}),
                    metrics={"profit": se.get("score", 3.0) - 3.0},
                )
                learning["outcomes_recorded"] = learning.get("outcomes_recorded", 0) + 1
        except Exception as exc:
            logger.debug("Brain learning: %s", exc)

        cycle_result["phases"]["learning"] = learning

        # Phase 5a: MARKETING AUTOMATION — generate campaigns
        try:
            from execution.marketing.auto_campaign import get_marketing_automation
            mkt = get_marketing_automation()
            mkt_result = mkt.generate_campaigns(
                data.get("products", []),
                data.get("customer_data", []),
                data.get("order_data", []),
                store_id=sid,
            )
            cycle_result["phases"]["marketing_auto"] = {
                "campaigns": mkt_result.get("total", 0),
                "types": mkt_result.get("by_type", {}),
                "estimated_revenue": mkt_result.get("estimated_revenue", 0),
            }
        except Exception as exc:
            logger.debug("Marketing automation: %s", exc)

        # Phase 5a2: STRATEGY PLANNER — long-term plans
        if self._cycle_count % 5 == 1:  # Every 5 cycles
            try:
                from core.brain.strategy_planner import get_strategy_planner
                sp = get_strategy_planner()
                plan = sp.plan(
                    data.get("products", []),
                    data.get("order_data", []),
                    data.get("customer_data", []),
                    store_id=sid,
                )
                cycle_result["phases"]["strategy"] = {
                    "strategies": plan.get("total", 0),
                    "priority": plan.get("priority_order", []),
                    "intelligence": plan.get("intelligence_used", {}),
                }
            except Exception as exc:
                logger.debug("Strategy planner: %s", exc)

        # Phase 5b: DOMAIN CAPTURE — fill all 12 data domains
        if hasattr(self, '_unified_memory') and self._unified_memory:
            try:
                domain_stats = self._capture_all_domains(
                    sid, data, analysis, cycle_result, brain_decisions,
                    smart_exec_result,
                )
                cycle_result["phases"]["domain_capture"] = domain_stats
            except Exception as exc:
                logger.debug("Domain capture: %s", exc)

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

        # Phase 6c: MAINTENANCE — prune old data, cleanup
        if self._cycle_count % 10 == 0:  # Every 10 cycles
            try:
                from core.memory.intelligence import get_memory_intelligence
                from core.data.architecture import get_data_architecture
                mi = get_memory_intelligence()
                da = get_data_architecture()
                pruned = mi.prune_unused(days=30)
                expired = da.cleanup_expired()
                if pruned or expired:
                    logger.info("Maintenance: pruned %d memories, %d expired records", pruned, expired)
            except Exception:
                pass

        # Phase 7: RULE HEALTH CHECK — monitor rule effectiveness
        try:
            from core.brain.rule_health import get_rule_health_checker
            rhc = get_rule_health_checker()
            health = rhc.check()
            cycle_result["phases"]["rule_health"] = {
                "total_rules": health.get("total_rules", 0),
                "healthy": health.get("healthy", 0),
                "zero_success": len(health.get("zero_success", [])),
                "health_score": health.get("health_score", 0),
                "recommendations": health.get("recommendations", []),
            }
        except Exception as exc:
            logger.debug("Rule health: %s", exc)

        # Phase 7b: EXECUTION PROMOTION — track and promote modes
        try:
            from execution.promoter import get_execution_promoter
            promoter = get_execution_promoter()
            se_results_list = smart_exec_result.get("results", []) if isinstance(smart_exec_result, dict) else []
            for se in se_results_list:
                promoter.record(se.get("action_type", ""), se.get("mode", "simulate"), se.get("score", 3.0))
            # Check for promotions
            promotion_recs = {}
            for se in se_results_list:
                at = se.get("action_type", "")
                if at and at not in promotion_recs:
                    rec = promoter.recommend_mode(at, default_mode="simulate")
                    if rec.get("mode") != "simulate":
                        promotion_recs[at] = rec
            if promotion_recs:
                cycle_result["phases"]["execution_promotion"] = promotion_recs
        except Exception as exc:
            logger.debug("Execution promotion: %s", exc)

        # Phase 7c: STRATEGY EXPANSION — every 5 cycles
        if self._cycle_count % 5 == 0:
            try:
                from core.brain.strategy_expander import get_strategy_expander
                expander = get_strategy_expander()
                expansion = expander.expand()
                if expansion.get("expanded", 0) > 0:
                    cycle_result["phases"]["strategy_expansion"] = {
                        "expanded": expansion.get("expanded", 0),
                        "coverage": expansion.get("categories_covered_after", 0),
                    }
            except Exception as exc:
                logger.debug("Strategy expansion: %s", exc)

        # Phase 8: PRODUCT SCORING — AI-learned product ranking
        try:
            from models.ml.product_scorer import get_product_scorer
            ps = get_product_scorer()
            product_scores = ps.score_all(data.get("products", []))
            cycle_result["phases"]["product_scoring"] = {
                "scored": len(product_scores),
                "top_product": product_scores[0]["name"] if product_scores else "?",
                "top_score": product_scores[0]["total_score"] if product_scores else 0,
                "grade_A": sum(1 for s in product_scores if s["grade"] == "A"),
                "grade_D": sum(1 for s in product_scores if s["grade"] == "D"),
            }
        except Exception as exc:
            logger.debug("Product scoring: %s", exc)

        # Phase 8b: COMPETITIVE INTELLIGENCE — deep market analysis
        try:
            from core.brain.competitive_intel import get_competitive_intelligence
            ci = get_competitive_intelligence()
            comp_intel = ci.analyze(
                data.get("products", []),
                data.get("competitor_data", []),
            )
            cycle_result["phases"]["competitive_intel"] = {
                "position": comp_intel.get("market_position", {}).get("position", "unknown"),
                "advantages": len(comp_intel.get("advantages", [])),
                "vulnerabilities": len(comp_intel.get("vulnerabilities", [])),
                "recommendations": comp_intel.get("recommendations", [])[:2],
            }
        except Exception as exc:
            logger.debug("Competitive intel: %s", exc)

        # Phase 8c: ALERTS — check for important events
        try:
            from core.system.alerts import get_alert_system
            alerts = get_alert_system()
            cycle_alerts = alerts.check_cycle(cycle_result)
            if cycle_alerts:
                cycle_result["phases"]["alerts"] = {
                    "count": len(cycle_alerts),
                    "critical": sum(1 for a in cycle_alerts if a["severity"] == "critical"),
                    "warnings": sum(1 for a in cycle_alerts if a["severity"] == "warning"),
                    "messages": [a["message"] for a in cycle_alerts[:3]],
                }
        except Exception as exc:
            logger.debug("Alerts: %s", exc)

        # Phase 8d: PRODUCT PERFORMANCE — track over time
        try:
            from core.system.product_performance import get_product_performance
            pp = get_product_performance()
            pp.record(data.get("products", []),
                      product_scores if 'product_scores' in dir() else None)
        except Exception:
            pass

        # Phase 8e: TREND ANALYSIS — cross-cycle trends
        try:
            from core.system.trend_analyzer import get_trend_analyzer
            ta = get_trend_analyzer()
            ta.record_cycle(cycle_result)
            if self._cycle_count >= 3:
                trends = ta.analyze()
                cycle_result["phases"]["trends"] = {
                    "cycles": trends.get("cycles_analyzed", 0),
                    "health": trends.get("health_trend", "unknown"),
                    "details": trends.get("trends", {}),
                }
        except Exception as exc:
            logger.debug("Trend analysis: %s", exc)

        # Phase 8f: CHAIN OF THOUGHT — structured reasoning on top problem
        try:
            from core.brain.reasoning_chain import get_chain_of_thought
            cot = get_chain_of_thought()
            brain_phase = cycle_result.get("phases", {}).get("brain", {})
            top_problem = brain_phase.get("top_action", "optimize_store")
            reasoning = cot.reason(
                "Should we {} for this store?".format(top_problem),
                {"products": data.get("products", [])[:5],
                 "orders": data.get("order_data", []),
                 "health_score": brain_phase.get("health_score", 0)},
            )
            cycle_result["phases"]["chain_of_thought"] = {
                "question": reasoning.get("question", "")[:60],
                "answer": reasoning.get("answer", "")[:60],
                "confidence": reasoning.get("confidence", 0),
                "steps": reasoning.get("reasoning_length", 0),
            }
        except Exception as exc:
            logger.debug("Chain of thought: %s", exc)

        # Phase 8g: FULFILLMENT — check order fulfillment status
        try:
            from execution.fulfillment.auto_fulfill import get_fulfillment
            ff = get_fulfillment()
            ff_result = ff.process_orders(
                data.get("order_data", []),
                data.get("products", []),
            )
            if ff_result.get("total_orders", 0) > 0:
                cycle_result["phases"]["fulfillment"] = {
                    "total": ff_result.get("total_orders", 0),
                    "fulfillable": ff_result.get("fulfillable", 0),
                    "blocked": ff_result.get("blocked", 0),
                }
        except Exception as exc:
            logger.debug("Fulfillment: %s", exc)

        # Phase 8h: MULTI-STORE — share learnings
        try:
            from core.brain.multi_store_brain import get_multi_store
            ms = get_multi_store()
            ms.register_store(sid)
            shared = ms.share_learning(sid)
            if shared.get("shareable_rules", 0) > 0:
                cycle_result["phases"]["multi_store"] = {
                    "shareable_rules": shared.get("shareable_rules", 0),
                    "shareable_strategies": shared.get("shareable_strategies", 0),
                }
        except Exception as exc:
            logger.debug("Multi-store: %s", exc)

        # Phase 8i: DASHBOARD — generate dashboard snapshot
        try:
            from core.system.dashboard import get_dashboard
            dash = get_dashboard()
            cycle_result["_dashboard"] = dash.generate(cycle_result)
        except Exception:
            pass

        # Phase 8j: LIVE EXECUTION — execute safe actions on Shopify
        try:
            from execution.live_executor import get_live_executor
            le = get_live_executor()
            # Only execute safe actions if we have credentials
            creds = {}
            if self._store_manager:
                creds = self._store_manager.get_credentials(sid)
            if creds.get("api_key"):
                # Find products without descriptions to update
                safe_actions = []
                for p in data.get("products", [])[:2]:
                    pid = str(p.get("id", ""))
                    desc = str(p.get("body_html", p.get("description", ""))).strip()
                    if pid and not desc:
                        safe_actions.append({
                            "type": "update_description",
                            "product_id": pid,
                            "description": "Quality {} product. Great value at ${}.".format(
                                p.get("product_type", ""), p.get("price", "")),
                        })
                live_results = []
                for action in safe_actions[:1]:  # Max 1 per cycle for safety
                    r = le.execute(action.get("type", ""), sid, action, creds)
                    live_results.append(r)
                if live_results:
                    cycle_result["phases"]["live_execution"] = {
                        "actions": len(live_results),
                        "success": sum(1 for r in live_results if r.get("status") == "success"),
                    }
        except Exception as exc:
            logger.debug("Live execution: %s", exc)

        # Phase 8k: CONTINUOUS OPTIMIZATION — auto-fix store issues
        try:
            from execution.continuous_optimizer import get_continuous_optimizer
            co = get_continuous_optimizer()
            creds = {}
            if self._store_manager:
                creds = self._store_manager.get_credentials(sid)
            co_result = co.optimize(
                data.get("products", []),
                data.get("customer_data", []),
                shop_url=creds.get("shop_url", ""),
                token=creds.get("api_key", ""),
                store_id=sid,
            )
            if co_result.get("fixes_applied", 0) > 0:
                cycle_result["phases"]["continuous_optimization"] = co_result
        except Exception as exc:
            logger.debug("Continuous optimizer: %s", exc)

        # Phase 8k2: REVENUE STRATEGY — generate revenue plan
        if self._cycle_count % 10 == 1:
            try:
                from core.brain.revenue_strategy import get_revenue_strategy
                rs = get_revenue_strategy()
                rev_plan = rs.create_plan(
                    data.get("products", []),
                    data.get("order_data", []),
                    data.get("customer_data", []),
                )
                cycle_result["phases"]["revenue_strategy"] = {
                    "phase": rev_plan.get("phase", ""),
                    "strategies": len(rev_plan.get("strategies", [])),
                    "immediate_actions": len(rev_plan.get("immediate_actions", [])),
                }
            except Exception as exc:
                logger.debug("Revenue strategy: %s", exc)

        # Phase 8k3: SEO ANALYSIS
        try:
            from core.system.seo_analyzer import get_seo_analyzer
            seo = get_seo_analyzer()
            seo_result = seo.analyze_all(data.get("products", [])[:5])
            cycle_result["phases"]["seo_analysis"] = {
                "avg_score": seo_result.get("avg_seo_score", 0),
                "grades": seo_result.get("grade_distribution", {}),
                "top_issues": seo_result.get("top_issues", [])[:3],
            }
        except Exception as exc:
            logger.debug("SEO analysis: %s", exc)

        # Phase 8k4: PROFIT CALCULATOR
        try:
            from core.system.profit_calculator import get_profit_calculator
            pc = get_profit_calculator()
            profit = pc.calculate_store(data.get("products", []), data.get("order_data", []))
            cycle_result["phases"]["profit_analysis"] = {
                "profitable": profit.get("profitable", 0),
                "unprofitable": profit.get("unprofitable", 0),
                "avg_margin": profit.get("avg_margin", 0),
                "needs_attention": len(profit.get("needs_attention", [])),
            }
        except Exception as exc:
            logger.debug("Profit calculator: %s", exc)

        # Phase 8k5: SOCIAL CONTENT — generate posts for top products
        if self._cycle_count % 5 == 1:
            try:
                from execution.content.social_content import get_social_content
                sc = get_social_content()
                social = sc.generate_batch(data.get("products", [])[:3])
                cycle_result["phases"]["social_content"] = {
                    "products": social.get("total_products", 0),
                    "platforms": 4,
                }
            except Exception as exc:
                logger.debug("Social content: %s", exc)

        # Phase 8k6: EMAIL SEQUENCES — build on first cycle
        if self._cycle_count <= 1:
            try:
                from execution.marketing.email_sequences import get_email_builder
                eb = get_email_builder()
                emails = eb.build_all("deguar", "https://deguar.myshopify.com",
                                      data.get("products", [])[:3])
                cycle_result["phases"]["email_sequences"] = {
                    "sequences": emails.get("total_sequences", 0),
                    "total_emails": emails.get("total_emails", 0),
                }
            except Exception as exc:
                logger.debug("Email sequences: %s", exc)

        # Phase 8k7: MODEL WORKERS — AI model tasks on products
        try:
            from core.system.model_workers import get_model_workers
            mw = get_model_workers()
            model_tasks = []
            for p in data.get("products", [])[:3]:
                r = mw.execute_task("analyze_product", {
                    "name": p.get("name", p.get("title", "")),
                    "price": p.get("price", 0),
                    "cost": p.get("cost", 0),
                    "category": p.get("product_type", ""),
                }, store_id=sid)
                model_tasks.append(r)
            if model_tasks:
                cycle_result["phases"]["model_workers"] = {
                    "tasks": len(model_tasks),
                    "roles_used": list(set(t.get("role", "") for t in model_tasks)),
                    "models_used": list(set(t.get("model", "") for t in model_tasks)),
                }
        except Exception as exc:
            logger.debug("Model workers: %s", exc)

        # Phase 8l: TOOL DISCOVERY — check available tools
        if self._cycle_count <= 1:
            try:
                from core.system.tool_orchestrator import get_tool_orchestrator
                to = get_tool_orchestrator()
                disc = to.discover()
                cycle_result["phases"]["tool_discovery"] = {
                    "available": disc.get("available", 0),
                    "total": disc.get("total_tools", 0),
                }
            except Exception as exc:
                logger.debug("Tool discovery: %s", exc)

        # Phase 9: CYCLE REPORT — human-readable summary
        try:
            from core.system.cycle_reporter import get_cycle_reporter
            reporter = get_cycle_reporter()
            cycle_result["_report"] = reporter.report(cycle_result)
        except Exception:
            pass

        # Phase 9b: NOTIFICATIONS — deliver alerts
        try:
            from core.system.notifications import get_notifications
            notif = get_notifications()
            notif.send_cycle_summary(cycle_result)
        except Exception:
            pass

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

    def _capture_all_domains(self, store_id: str, data: dict,
                             analysis: dict, cycle_result: dict,
                             brain_decisions: list,
                             smart_exec: dict) -> dict[str, int]:
        """Capture data into all 12 domains for comprehensive intelligence."""
        from core.data.architecture import get_data_architecture
        da = get_data_architecture()
        captured: dict[str, int] = {}

        products = data.get("products", [])
        orders = data.get("order_data", data.get("orders", []))

        # 1. FEEDBACK domain — data quality issues as feedback
        dq = cycle_result.get("phases", {}).get("data_quality", {})
        if dq.get("issues", 0) > 0:
            da.capture("feedback", {
                "source": "data_quality",
                "topic": dq.get("top_issue", "")[:80],
                "sentiment": "negative" if dq.get("score", 100) < 80 else "neutral",
                "urgency": "high" if dq.get("score", 100) < 50 else "low",
                "score": dq.get("score", 0),
            }, source="system", store_id=store_id)
            captured["feedback"] = 1

        # 2. EXPERIMENT domain — each smart execution is an experiment
        se_results = smart_exec.get("results", []) if isinstance(smart_exec, dict) else []
        for se in se_results:
            da.capture("experiment", {
                "hypothesis": f"{se.get('action_type', 'unknown')} will improve store",
                "experiment_type": se.get("mode", "simulate"),
                "variants": 1,
                "sample_size": len(products),
                "confidence_level": se.get("confidence", 0),
                "result_score": se.get("score", 0),
            }, source="smart_executor", store_id=store_id,
                score=se.get("score", 3.0))
        captured["experiment"] = len(se_results)

        # 3. FEATURE domain — extracted features from this cycle
        brain = cycle_result.get("phases", {}).get("brain", {})
        if brain:
            da.capture("feature", {
                "feature_name": "health_score",
                "value": brain.get("health_score", 0),
                "data_type": "numeric",
                "source_domain": "brain",
                "freshness": 1.0,
            }, source="brain", store_id=store_id, score=4.0)
            da.capture("feature", {
                "feature_name": "opportunity_count",
                "value": brain.get("opportunities", 0),
                "data_type": "numeric",
                "source_domain": "brain",
                "freshness": 1.0,
            }, source="brain", store_id=store_id, score=3.5)
        captured["feature"] = 2

        # 4. KNOWLEDGE domain — learned rules and strategies
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            rules = mi.get_rules()
            for r in rules[:5]:
                rc = r.get("content", {})
                if isinstance(rc, dict):
                    da.capture("knowledge", {
                        "content": rc.get("rule", str(rc)[:100]),
                        "knowledge_type": "rule",
                        "domain": r.get("category", ""),
                        "confidence": r.get("confidence", 0.5),
                        "evidence_count": r.get("evidence_count", 0),
                    }, source="memory_intelligence", store_id=store_id,
                        score=r.get("score", 3.0))
            captured["knowledge"] = len(rules[:5])
        except Exception:
            captured["knowledge"] = 0

        # 5. SYSTEM domain — cycle performance metrics
        da.capture("system", {
            "event_type": "cycle_complete",
            "component": "autonomous_controller",
            "severity": "info",
            "latency_ms": int(cycle_result.get("duration_s", 0) * 1000),
            "layers_run": cycle_result.get("phases", {}).get("layers", {}).get("layers_run", 0),
            "insights": cycle_result.get("phases", {}).get("layers", {}).get("total_insights", 0),
        }, source="controller", store_id=store_id, score=4.0)
        captured["system"] = 1

        # 6. SIMULATION domain — smart execution simulations
        for se in se_results:
            predicted = se.get("predicted_outcome", {})
            if predicted:
                da.capture("simulation", {
                    "scenario": se.get("action_type", "unknown"),
                    "scenario_type": "action_simulation",
                    "predicted": predicted.get("estimated_revenue_change_pct", 0),
                    "confidence": se.get("confidence", 0),
                    "variables": len(predicted),
                    "practical_value": se.get("score", 0) / 5.0,
                }, source="smart_executor", store_id=store_id,
                    score=se.get("score", 3.0))
        captured["simulation"] = len(se_results)

        # 7. MARKETING domain — skill recommendations as marketing insights
        skills = cycle_result.get("phases", {}).get("skills", {})
        if skills.get("recommended", 0) > 0:
            for skill_name in skills.get("top", [])[:3]:
                da.capture("marketing", {
                    "channel": "ai_recommendation",
                    "campaign_type": skill_name,
                    "audience_size": len(data.get("customer_data", data.get("customers", []))),
                    "spend": 0,
                    "impressions": 0,
                    "clicks": 0,
                    "conversions": 0,
                }, source="skills", store_id=store_id, score=3.5)
        captured["marketing"] = min(skills.get("recommended", 0), 3)

        # Capture brain decisions as marketing opportunities
        for dec in brain_decisions[:2]:
            da.capture("marketing", {
                "channel": "brain_decision",
                "campaign_type": dec.get("type", "recommendation"),
                "audience_size": 0,
                "spend": 0,
            }, source="brain", store_id=store_id, score=3.5)
        captured["marketing"] += min(len(brain_decisions), 2)

        # 8. Feed competitor prices to price history
        try:
            from data_pipeline.tracking.price_history import get_price_history
            ph = get_price_history()
            comp_data = data.get("competitor_data", [])
            comp_count = 0
            for comp in comp_data:
                if isinstance(comp, dict):
                    pid = comp.get("product_id", "")
                    for cp in comp.get("competitor_prices", []):
                        if isinstance(cp, dict) and cp.get("price"):
                            ph.record_competitor_price(
                                pid, cp.get("competitor", "unknown"),
                                float(cp["price"]),
                            )
                            comp_count += 1
            captured["competitor_prices"] = comp_count
        except Exception:
            pass

        # 9. Auto-complete mature A/B experiments
        try:
            from core.system.ab_testing import get_ab_testing
            ab = get_ab_testing()
            active = ab.get_active()
            completed_count = 0
            for exp in active:
                exp_id = exp.get("id", "")
                if not exp_id:
                    continue
                # Complete if has enough observations
                analysis = ab.analyze(exp_id)
                variants = analysis.get("variants", {})
                min_samples = min(
                    (v.get("sample_size", 0) for v in variants.values()),
                    default=0,
                )
                if min_samples >= 3:  # Enough data to conclude
                    ab.complete(exp_id)
                    completed_count += 1
            captured["experiments_completed"] = completed_count
        except Exception:
            pass

        return captured

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
        _insight_keys = (
            "recommendations", "alerts", "reorder_plan", "ranked_products",
            "winners", "segments", "opportunities", "trends",
            "stockout_risks", "churn_predictions",
        )

        for engine_name, result in analysis_results.items():
            if not isinstance(result, dict) or result.get("status") == "error":
                continue

            data = result.get("data", {})
            if not isinstance(data, dict):
                continue

            # Extract patterns from any list output
            for key in _insight_keys:
                items = data.get(key, [])
                if not isinstance(items, list) or not items:
                    continue
                for item in items[:5]:
                    if isinstance(item, dict):
                        patterns.append({
                            "engine": engine_name,
                            "type": item.get("type", item.get("action", key)),
                            "confidence": float(item.get("confidence",
                                            item.get("score", 0.5)) or 0.5),
                            "impact": item.get("expected_impact",
                                     item.get("impact", item.get("severity", "medium"))),
                        })

        return patterns

    def _update_weights(self, patterns: list[dict[str, Any]]) -> int:
        """Update Bayesian learning weights based on patterns."""
        try:
            from core.intelligence.loop.stage_learn import _update_weight
        except ImportError:
            # Fallback: use MemoryIntelligence rule success as weight signal
            return self._update_weights_from_rules()

        updates = 0
        for pattern in patterns:
            engine = pattern.get("engine", "")
            # Any pattern with confidence > 0.3 counts (was 0.7 — too strict)
            confidence = pattern.get("confidence", 0)
            if confidence > 0.3 or engine:
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

    @staticmethod
    def _update_weights_from_rules() -> int:
        """Fallback weight update using MemoryIntelligence rules."""
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            rules = mi.get_rules()
            updates = 0
            for r in rules:
                if r.get("success_count", 0) > 0:
                    updates += 1
            return updates
        except Exception:
            return 0

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
