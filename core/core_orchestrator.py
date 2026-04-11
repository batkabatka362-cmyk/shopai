"""CoreOrchestrator — the central brain that coordinates ALL intelligence modules.

Unlike MainOrchestrator (which routes tasks to engines), CoreOrchestrator
connects the ~17 real intelligence modules into one coordinated decision cycle:

    Fetch Data → Snapshot → Prioritize → Financial Analysis → Campaign Analysis
    → Intelligence Loop → Strategy Optimization → Event Processing → Health Report
    → Journal

Each cycle produces a unified result with insights from all subsystems.
Outcomes feed back into learning, closing the loop.

New in v2: StoreSnapshot, PriorityEngine, ActionCoordinator, CycleJournal
"""
from __future__ import annotations

import os
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id
from core.orchestrator.store_snapshot import StoreSnapshot
from core.orchestrator.priority_engine import PriorityEngine
from core.orchestrator.action_coordinator import ActionCoordinator
from core.orchestrator.cycle_journal import CycleJournal

logger = get_logger("core_orchestrator")


class CoreOrchestrator:
    """Coordinates all intelligence modules into one unified decision cycle.

    Usage:
        orchestrator = CoreOrchestrator()
        result = orchestrator.run_cycle(goal="maximize_profit")
        situation = orchestrator.get_situation()
    """

    def __init__(self) -> None:
        self._modules: dict[str, Any] = {}
        self._cycle_count = 0
        self._history: list[dict[str, Any]] = []
        self._initialized = False
        # Per-module init failure messages. Mirrors the
        # LayerDispatcher / AgentDispatcher / UnifiedMemory
        # observability hooks so dashboards and tests can see
        # exactly which of the ~35 intelligence modules failed
        # to load. Empty dict means everything came up clean.
        self._init_errors: dict[str, str] = {}
        # New coordination components
        self.snapshot = StoreSnapshot.load()
        self.priority_engine = PriorityEngine()
        self.action_coordinator = ActionCoordinator()
        self.journal = CycleJournal()
        self._init_modules()

    def get_init_errors(self) -> dict[str, str]:
        """Return per-module initialization error messages.

        Empty dict means every module loaded successfully. Each
        entry is ``"TypeName: message"`` — symmetric with the
        LayerDispatcher / AgentDispatcher / UnifiedMemory init-
        error APIs added in earlier passes.
        """
        return dict(self._init_errors)

    def _init_modules(self) -> None:
        """Initialize all intelligence modules. Each is optional — failure doesn't block others."""
        module_specs = {
            "shopify_bridge": ("core.bridge.shopify_bridge", "ShopifyBridge", {
                "shop_url": os.getenv("SHOPAI_SHOPIFY_URL", ""),
                "api_key": os.getenv("SHOPAI_SHOPIFY_KEY", ""),
            }),
            "intelligence_loop": ("core.intelligence.loop", "IntelligenceLoop", {}),
            "financial_brain": ("core.intelligence.financial_brain", "FinancialBrain", {}),
            "campaign_optimizer": ("core.intelligence.campaign_optimizer", "CampaignOptimizer", {}),
            "ads_intelligence": ("core.intelligence.ads_intelligence", "AdsIntelligence", {}),
            "strategy_optimizer": ("core.intelligence.strategy_optimizer", "StrategyOptimizer", {}),
            "competitive_loop": ("core.intelligence.competitive_loop", "CompetitiveLoop", {}),
            "kpi_tracker": ("core.intelligence.kpi_tracker", "KPITracker", {}),
            "revenue_tracker": ("core.intelligence.revenue_tracker", "RevenueTracker", {}),
            "system_health": ("core.intelligence.system_health", "SystemHealthReport", {}),
            "event_reactor": ("core.reactor", "EventReactor", {}),
            "scheduler": ("core.scheduling", "SmartScheduler", {}),
            # New intelligence modules from research
            "financial_depth": ("core.intelligence.financial", "FinancialDepth", {}),
            "marketing_tactics": ("core.intelligence.marketing", "MarketingTactics", {}),
            "customer_journey": ("core.intelligence.customer", "CustomerJourney", {}),
            "supply_chain": ("core.intelligence.supply", "SupplyChainIntelligence", {}),
            # Thinking layers
            "goal_manager": ("core.goals.goal_manager", "GoalManager", {}),
            "episodic_memory": ("core.memory.episodic_memory", "EpisodicMemory", {}),
            "decision_narrator": ("core.intelligence.decision_narrator", "DecisionNarrator", {}),
            "legal_compliance": ("core.intelligence.compliance", "LegalCompliance", {}),
            # Feedback loop closers
            "causal_graph": ("core.causal.causal_graph", "CausalGraph", {}),
            "root_cause_analyzer": ("core.learning.root_cause_analyzer", "RootCauseAnalyzer", {}),
            "capability_assessor": ("core.self_monitor.capability_assessor", "CapabilityAssessor", {}),
            # Proactive + strategy
            "proactive_preparation": ("core.intelligence.proactive_preparation", "ProactivePreparation", {}),
            "self_diagnostics": ("core.self_monitor.self_diagnostics", "SelfDiagnostics", {}),
            "strategy_planner": ("core.strategy.strategy_planner", "StrategyPlanner", {}),
            # Expert layers
            "offer_architect": ("core.intelligence.offer_architect", "OfferArchitect", {}),
            "compounding_optimizer": ("core.intelligence.compounding_optimizer", "CompoundingOptimizer", {}),
            "growth_intelligence": ("core.intelligence.growth_intelligence", "GrowthIntelligence", {}),
            "human_communicator": ("core.intelligence.human_communicator", "HumanCommunicator", {}),
            "growth_planner": ("core.strategy.growth_planner", "GrowthPlanner", {}),
            # Final layers — completing 27-layer plan
            "reasoning_forum": ("core.intelligence.reasoning_forum", "ReasoningForum", {}),
            "compute_superior": ("core.intelligence.compute_superior", "ComputeSuperior", {}),
            "operational_mastery": ("core.intelligence.operational_mastery", "OperationalMastery", {}),
            "multi_store": ("core.multi_store.store_manager", "MultiStoreManager", {}),
        }

        import importlib
        for name, (module_path, class_name, kwargs) in module_specs.items():
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                self._modules[name] = cls(**kwargs)
                logger.info("Module loaded: %s", name)
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                self._init_errors[name] = err
                logger.warning("Module %s failed to load: %s", name, err)

        # Initialize thinking layers that need cross-references
        try:
            from core.judgment.failure_prevention import FailureContextPrevention
            from core.judgment.judgment_advisor import JudgmentAdvisor
            self._modules["failure_prevention"] = FailureContextPrevention(
                episodic_memory=self._modules.get("episodic_memory"),
            )
            self._modules["judgment_advisor"] = JudgmentAdvisor(
                episodic_memory=self._modules.get("episodic_memory"),
                failure_prevention=self._modules.get("failure_prevention"),
                action_coordinator=self.action_coordinator,
            )
            # Wire cross-references for modules that need episodic memory
            rca = self._modules.get("root_cause_analyzer")
            if rca:
                rca._memory = self._modules.get("episodic_memory")
            cap = self._modules.get("capability_assessor")
            if cap:
                cap._memory = self._modules.get("episodic_memory")
            logger.info("Thinking layers initialized (judgment, failure_prevention, root_cause, capability)")
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            self._init_errors["thinking_layers"] = err
            logger.warning("Thinking layers failed: %s", err)

        self._initialized = True
        if self._init_errors:
            logger.warning(
                "CoreOrchestrator initialized: %d/%d modules loaded (%d failed: %s)",
                len(self._modules), len(module_specs) + 2,
                len(self._init_errors),
                ", ".join(sorted(self._init_errors.keys())),
            )
        else:
            logger.info(
                "CoreOrchestrator initialized: %d/%d modules loaded",
                len(self._modules), len(module_specs) + 2,
            )

    def get_module(self, name: str) -> Any | None:
        """Get a loaded module by name."""
        return self._modules.get(name)

    def run_cycle(
        self,
        goal: str = "maximize_profit",
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one full intelligence cycle coordinating all modules.

        Flow:
            1. Fetch data from Shopify
            2. Financial analysis (P&L, cash flow, margins)
            3. Campaign analysis (ad performance, optimization)
            4. Competitive analysis (market monitoring)
            5. Intelligence loop (7-stage: clean→analyze→decide→plan→execute→track→learn)
            6. Strategy optimization (auto-pilot, weight adjustment)
            7. Event processing (react to alerts)
            8. Health report (system-wide grade)

        Returns unified result with all subsystem outputs.
        """
        cycle_id = generate_id("cycle")
        self._cycle_count += 1
        start = time.monotonic()
        cfg = config or {}

        # ── Phase 0: GOAL SELECTION ──
        # Callers can pass goal="" or goal=None to request automatic
        # goal selection from the GoalManager; otherwise the provided
        # goal wins. The previous code had two mutually-exclusive
        # `goal is None` branches that were both unreachable because
        # the signature defaults `goal: str = "maximize_profit"` —
        # collapsing to a single clear condition here.
        goal_mgr = self._modules.get("goal_manager")
        if not goal:
            if goal_mgr:
                try:
                    goal_result = goal_mgr.select_goal(
                        self.snapshot.get_situation(),
                        cycle_number=self._cycle_count,
                    )
                    goal = (goal_result or {}).get("goal") or "maximize_profit"
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "CoreOrchestrator: goal_manager.select_goal failed (%s); "
                        "falling back to maximize_profit", exc,
                    )
                    goal = "maximize_profit"
            else:
                goal = "maximize_profit"

        results: dict[str, Any] = {
            "cycle_id": cycle_id,
            "cycle_number": self._cycle_count,
            "goal": goal,
            "timestamp": time.time(),
            "phases": {},
        }

        # ── Phase 1: FETCH DATA ──
        data = self._phase_fetch_data(cfg)
        results["phases"]["data"] = {
            "products": len(data.get("products", [])),
            "orders": len(data.get("orders", [])),
            "customers": len(data.get("customers", [])),
            "source": data.get("_source", "unknown"),
        }

        # ── Phase 2: FINANCIAL ANALYSIS ──
        financial = self._phase_financial(data)
        results["phases"]["financial"] = financial

        # ── Phase 3: CAMPAIGN ANALYSIS ──
        campaigns = self._phase_campaigns(data, cfg)
        results["phases"]["campaigns"] = campaigns

        # ── Phase 4: COMPETITIVE ANALYSIS ──
        competitive = self._phase_competitive(data)
        results["phases"]["competitive"] = competitive

        # ── Phase 5: HEALTH REPORT ──
        health = self._phase_health()
        results["phases"]["health"] = health

        # ── Phase 6: EXPERT ANALYSIS (runs BEFORE intelligence to feed context) ──
        fin_depth = self._phase_financial_depth(data, cfg)
        results["phases"]["financial_depth"] = fin_depth

        mkt_tactics = self._phase_marketing_tactics(data, cfg)
        results["phases"]["marketing_tactics"] = mkt_tactics

        journey = self._phase_customer_journey(data)
        results["phases"]["customer_journey"] = journey

        supply = self._phase_supply_chain(data)
        results["phases"]["supply_chain"] = supply

        compliance = self._phase_compliance(data)
        results["phases"]["compliance"] = compliance

        # ── Phase 7: EPISODIC MEMORY RECALL ──
        past_episodes = self._recall_episodes()

        # ── Phase 8: INTELLIGENCE LOOP (core decision-making) ──
        # Enrich data with ALL insights from phases 2-7
        enriched_data = self._enrich_data(data, financial, campaigns, competitive)
        enriched_data["_expert"] = self._build_expert_context(
            fin_depth, mkt_tactics, journey, supply, compliance,
        )
        enriched_data["_episodes"] = past_episodes
        intel = self._phase_intelligence(enriched_data, goal)
        results["phases"]["intelligence"] = intel

        # ── Phase 9: STRATEGY OPTIMIZATION ──
        strategy = self._phase_strategy(intel, goal)
        results["phases"]["strategy"] = strategy

        # ── Phase 10: EVENT PROCESSING ──
        events = self._phase_events(results)
        results["phases"]["events"] = events

        # ── Phase 11: CAUSAL ANALYSIS ──
        causal = self._phase_causal(events)
        results["phases"]["causal"] = causal

        # ── Phase 12: JUDGMENT ──
        judgment = self._phase_judgment(intel, data)
        results["phases"]["judgment"] = judgment

        # ── ENFORCE JUDGMENT VERDICT ──
        verdict = judgment.get("verdict", "proceed")
        if verdict == "escalate_to_human":
            results["blocked"] = True
            results["block_reason"] = judgment.get("reason", "Risk too high")
            logger.warning("Cycle %s BLOCKED by judgment: %s", cycle_id, judgment.get("reason"))
        elif verdict == "delay":
            results["delayed"] = True
            results["delay_reason"] = judgment.get("reason", "Conditions not optimal")
            logger.info("Cycle %s DELAYED by judgment: %s", cycle_id, judgment.get("reason"))

        # ── Phase 15: EXECUTION (only if not blocked/delayed) ──
        if not results.get("blocked") and not results.get("delayed"):
            execution = self._phase_execution(intel, data)
            results["phases"]["execution"] = execution
        else:
            results["phases"]["execution"] = {
                "status": "skipped",
                "reason": results.get("block_reason") or results.get("delay_reason", "judgment blocked"),
            }

        # ── Update StoreSnapshot ──
        self.snapshot.update_financial(financial)
        self.snapshot.update_products(intel)
        self.snapshot.update_inventory(data.get("products", []))
        self.snapshot.update_customers(data.get("customers", []), data.get("orders", []))
        self.snapshot.update_marketing(campaigns)
        self.snapshot.update_health(health)
        self.snapshot.update_events(events)

        # ── Compute Priorities ──
        strategy_weights = None
        opt = self._modules.get("strategy_optimizer")
        if opt:
            try:
                strategy_weights = opt.get_adjusted_weights(goal)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "CoreOrchestrator: strategy_optimizer.get_adjusted_weights "
                    "failed (%s); using unweighted priorities", exc,
                )
        priorities = self.priority_engine.compute(
            self.snapshot.get_situation(), goal=goal, strategy_weights=strategy_weights,
        )
        self.snapshot.set_priorities(priorities)
        self.snapshot.finalize(cycle_id)
        self.snapshot.persist()
        results["priorities"] = priorities

        # ── Record KPIs ──
        self._record_kpis(cycle_id, intel, goal)

        # ── Compute summary ──
        elapsed = time.monotonic() - start
        results["elapsed_seconds"] = round(elapsed, 3)
        results["summary"] = self._compute_summary(results)

        # ── Narrative ──
        narrator = self._modules.get("decision_narrator")
        if narrator:
            try:
                results["narrative"] = narrator.narrate(results)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "CoreOrchestrator: decision_narrator.narrate failed (%s)",
                    exc,
                )
                results["narrative"] = ""

        # ── Record Episode ──
        self._record_episode(results)

        # ── Journal ──
        self.journal.record_cycle(results)

        self._history.append({
            "cycle_id": cycle_id,
            "goal": goal,
            "summary": results["summary"],
            "elapsed": results["elapsed_seconds"],
            "timestamp": results["timestamp"],
        })

        logger.info(
            "Cycle %s completed in %.2fs — decision: %s, confidence: %s, top_priority: %s",
            cycle_id, elapsed,
            results["summary"].get("decision", "none"),
            results["summary"].get("confidence", "unknown"),
            priorities[0]["domain"] if priorities else "none",
        )

        return results

    # ── Phase implementations ──

    def _phase_fetch_data(self, cfg: dict[str, Any]) -> dict[str, Any]:
        """Fetch products, orders, customers from Shopify."""
        bridge = self._modules.get("shopify_bridge")
        if bridge is None:
            return {"products": [], "orders": [], "customers": [], "_source": "no_bridge"}

        try:
            products = bridge.fetch_products(limit=cfg.get("product_limit", 50))
            orders = bridge.fetch_orders(days_back=cfg.get("days_back", 30))
            customers = bridge.fetch_customers(limit=cfg.get("customer_limit", 100))
            return {
                "products": products if isinstance(products, list) else products.get("products", []),
                "orders": orders if isinstance(orders, list) else orders.get("orders", []),
                "customers": customers if isinstance(customers, list) else customers.get("customers", []),
                "_source": "shopify",
            }
        except Exception as exc:
            logger.warning("Data fetch failed: %s", exc)
            return {"products": [], "orders": [], "customers": [], "_source": "error"}

    def _phase_financial(self, data: dict[str, Any]) -> dict[str, Any]:
        """Run financial analysis: P&L, cash flow, margins."""
        brain = self._modules.get("financial_brain")
        if brain is None:
            return {"status": "unavailable"}

        try:
            products = data.get("products", [])
            orders = data.get("orders", [])
            result = brain.full_analysis(products=products, orders=orders)
            return result
        except Exception as exc:
            logger.warning("Financial analysis failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _phase_campaigns(self, data: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
        """Analyze ad campaigns and generate optimization recommendations."""
        optimizer = self._modules.get("campaign_optimizer")
        ads = self._modules.get("ads_intelligence")
        if optimizer is None and ads is None:
            return {"status": "unavailable"}

        result: dict[str, Any] = {}

        # Campaign optimization (ROAS-based rules)
        if optimizer is not None:
            try:
                campaigns = cfg.get("campaigns", [])
                if campaigns:
                    result["optimization"] = optimizer.optimize(campaigns)
                    result["health"] = optimizer.get_campaign_health(campaigns)
                else:
                    result["optimization"] = {"actions": [], "note": "no_campaigns_provided"}
            except Exception as exc:
                result["optimization"] = {"status": "error", "error": str(exc)}

        # Ads intelligence (creative scoring, targeting)
        if ads is not None:
            try:
                products = data.get("products", [])
                customers = data.get("customers", [])
                if products:
                    result["targeting"] = ads.recommend_targeting(products, customers)
                if cfg.get("ad_creatives"):
                    result["creative_scores"] = [
                        ads.score_ad_creative(c) for c in cfg["ad_creatives"]
                    ]
            except Exception as exc:
                result["ads_intel"] = {"status": "error", "error": str(exc)}

        return result if result else {"status": "no_data"}

    def _phase_competitive(self, data: dict[str, Any]) -> dict[str, Any]:
        """Monitor competitors and generate alerts."""
        comp = self._modules.get("competitive_loop")
        if comp is None:
            return {"status": "unavailable"}

        try:
            products = data.get("products", [])
            competitors = data.get("competitors", [])
            if not products:
                return {"status": "no_products"}
            monitoring = comp.monitor(products, competitors)
            alerts = comp.get_alerts()
            return {"monitoring": monitoring, "alerts": alerts}
        except Exception as exc:
            logger.warning("Competitive analysis failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _phase_intelligence(self, data: dict[str, Any], goal: str) -> dict[str, Any]:
        """Run the 7-stage IntelligenceLoop with enriched data."""
        loop = self._modules.get("intelligence_loop")
        if loop is None:
            return {"status": "unavailable"}

        try:
            result = loop.run(data, goal=goal)
            return result
        except Exception as exc:
            logger.warning("Intelligence loop failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _phase_strategy(self, intel_result: dict[str, Any], goal: str) -> dict[str, Any]:
        """Optimize strategy based on intelligence results."""
        optimizer = self._modules.get("strategy_optimizer")
        if optimizer is None:
            return {"status": "unavailable"}

        try:
            # Update from latest outcomes
            optimizer.update_from_outcomes()

            # Get auto-pilot recommendation
            revenue_data = intel_result.get("stages", {}).get("analyze", {}).get("revenue", {})
            revenue_trend = "stable"
            total_revenue = 0
            if isinstance(revenue_data, dict):
                total_revenue = revenue_data.get("total", 0)
                revenue_trend = revenue_data.get("trend", "stable")

            autopilot = optimizer.auto_pilot(
                current_goal=goal,
                performance_data={
                    "revenue": total_revenue,
                    "revenue_trend": revenue_trend,
                },
            )

            report = optimizer.get_strategy_report()
            return {
                "autopilot": autopilot,
                "report": report,
                "current_goal": goal,
            }
        except Exception as exc:
            logger.warning("Strategy optimization failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _phase_events(self, cycle_results: dict[str, Any]) -> dict[str, Any]:
        """Process events generated during this cycle."""
        reactor = self._modules.get("event_reactor")
        if reactor is None:
            return {"status": "unavailable"}

        events_fired = []
        try:
            # Check financial alerts → fire events
            financial = cycle_results.get("phases", {}).get("financial", {})
            margin_alerts = financial.get("margin_alerts", [])
            for alert in margin_alerts:
                if alert.get("severity") == "critical":
                    reactor.react("revenue.drop", {
                        "product": alert.get("product", "unknown"),
                        "margin": alert.get("margin", 0),
                        "alert": "critical_margin",
                    })
                    events_fired.append(f"revenue.drop:{alert.get('product', '?')}")

            # Check competitive alerts
            competitive = cycle_results.get("phases", {}).get("competitive", {})
            for alert in competitive.get("alerts", []):
                reactor.react("product.price_change", {
                    "source": "competitor",
                    "alert": alert,
                })
                events_fired.append("product.price_change:competitor")

            # Check campaign underperformance
            campaigns = cycle_results.get("phases", {}).get("campaigns", {})
            optimization = campaigns.get("optimization", {})
            for action in optimization.get("actions", []):
                if action.get("action") == "pause":
                    reactor.react("campaign.underperform", {
                        "campaign": action.get("campaign_id", "unknown"),
                        "reason": action.get("reason", "low_roas"),
                    })
                    events_fired.append(f"campaign.underperform:{action.get('campaign_id', '?')}")

            return {
                "events_fired": len(events_fired),
                "details": events_fired,
                "reactor_stats": {"pending": reactor._queue.qsize()} if hasattr(reactor, "_queue") else {},
            }
        except Exception as exc:
            logger.warning("Event processing failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _phase_health(self) -> dict[str, Any]:
        """Generate system-wide health report."""
        health = self._modules.get("system_health")
        if health is None:
            return {"status": "unavailable"}

        try:
            return health.generate()
        except Exception as exc:
            logger.warning("Health report failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _phase_financial_depth(self, data: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
        """Run expert-level financial analysis: tax nexus, BNPL, dim shipping, working capital."""
        depth = self._modules.get("financial_depth")
        if depth is None:
            return {"status": "unavailable"}
        try:
            return depth.full_analysis(
                products=data.get("products", []),
                orders=data.get("orders", []),
                revenue_by_state=cfg.get("revenue_by_state"),
                current_processor=cfg.get("payment_processor", "shopify_payments"),
            )
        except Exception as exc:
            logger.warning("Financial depth failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _phase_marketing_tactics(self, data: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
        """Run marketing tactics analysis: creative fatigue, retargeting, influencer strategy."""
        tactics = self._modules.get("marketing_tactics")
        if tactics is None:
            return {"status": "unavailable"}
        try:
            return tactics.full_analysis(
                campaigns=cfg.get("campaigns"),
                products=data.get("products", []),
                customers=data.get("customers", []),
            )
        except Exception as exc:
            logger.warning("Marketing tactics failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _phase_customer_journey(self, data: dict[str, Any]) -> dict[str, Any]:
        """Run customer journey analysis: lifecycle segmentation, winback, surprise & delight."""
        journey = self._modules.get("customer_journey")
        if journey is None:
            return {"status": "unavailable"}
        try:
            return journey.full_analysis(
                customers=data.get("customers", []),
                orders=data.get("orders", []),
            )
        except Exception as exc:
            logger.warning("Customer journey failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _phase_supply_chain(self, data: dict[str, Any]) -> dict[str, Any]:
        """Run supply chain analysis: reorder points, dead stock, shipping, returns."""
        supply = self._modules.get("supply_chain")
        if supply is None:
            return {"status": "unavailable"}
        try:
            return supply.full_analysis(
                products=data.get("products", []),
                orders=data.get("orders", []),
            )
        except Exception as exc:
            logger.warning("Supply chain failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _phase_causal(self, events: dict[str, Any]) -> dict[str, Any]:
        """Run causal analysis on events to detect cause-effect chains."""
        cg = self._modules.get("causal_graph")
        if cg is None:
            return {"status": "unavailable"}
        try:
            event_list = []
            for detail in events.get("details", []):
                if isinstance(detail, str) and ":" in detail:
                    event_type = detail.split(":")[0]
                    event_list.append({"type": event_type, "days_ago": 0})

            # Also check snapshot for metrics
            metrics = {
                "revenue_change": self.snapshot.financial.get("net_profit", 0),
                "health_grade": self.snapshot.financial.get("health_grade", "?"),
            }
            return cg.analyze(event_list, metrics)
        except Exception as exc:
            logger.warning("Causal analysis failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _phase_execution(self, intel: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        """Execute approved actions via ExecutionBridge.

        Converts IntelligenceLoop output into ExecutionBridge format,
        registers executors, auto-approves low/medium risk, executes.
        """
        try:
            from core.bridge.execution_bridge import ExecutionBridge

            eb = ExecutionBridge()

            # Register available executors. Previously a bare
            # `except Exception: pass` silently swallowed any import
            # or registration failure, so later Shopify executions
            # would return "no executor found" with no hint that
            # registration had failed at startup.
            try:
                from execution.shopify.product_creator import ProductCreator
                from execution.shopify.product_updater import ProductUpdater
                eb.register_executor("shopify", "product.create_listing", ProductCreator())
                eb.register_executor("shopify", "pricing.update", ProductUpdater())
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "CoreOrchestrator: Shopify executor registration failed (%s)",
                    exc,
                )

            # Convert IntelligenceLoop output to ExecutionBridge format
            decision = intel.get("decision", {})
            execution = intel.get("execution", {})
            products = data.get("products", [])

            # Build execution-ready payload
            bridge_input: dict[str, Any] = {}

            # Map scored products as selected products
            analysis = intel.get("analysis", {})
            if isinstance(analysis, dict):
                scored = analysis.get("products", {}).get("scored", [])
                viable = [p for p in scored if isinstance(p, dict) and p.get("viable")]
                if viable:
                    bridge_input["selected_products"] = viable[:5]

            # Map pricing decisions
            action_str = decision.get("action", "")
            if "pric" in action_str.lower():
                recs = []
                for p in products[:5]:
                    if isinstance(p, dict):
                        recs.append({
                            "product_id": p.get("id"),
                            "action": "increase_price" if "increase" in action_str.lower() or "optim" in action_str.lower() else "can_discount",
                            "current_price": p.get("price"),
                        })
                if recs:
                    bridge_input["pricing_recommendations"] = recs

            # Map customer churn risks
            customers = data.get("customers", [])
            churn_risks = [
                {"customer_id": c.get("id"), "risk_level": "high"}
                for c in customers
                if isinstance(c, dict) and c.get("orders_count", 0) == 0
            ]
            if churn_risks:
                bridge_input["churn_risks"] = churn_risks

            # Plan actions
            planned = eb.plan_actions("core_orchestrator", bridge_input)

            # Auto-approve low/medium priority actions
            for action in eb.get_queue():
                if action.get("priority") in ("low", "medium"):
                    eb.approve_action(action["action_id"])

            # Execute approved actions
            executed = eb.execute_approved()

            # Record outcomes
            success_count = sum(1 for e in executed if e.get("status") == "executed")
            fail_count = sum(1 for e in executed if e.get("status") == "failed")

            return {
                "status": "executed",
                "planned": len(planned),
                "executed": len(executed),
                "success_count": success_count,
                "fail_count": fail_count,
                "details": executed[:10],
            }
        except Exception as exc:
            logger.warning("Execution phase failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _phase_compliance(self, data: dict[str, Any]) -> dict[str, Any]:
        """Run legal compliance checks on products."""
        compliance = self._modules.get("legal_compliance")
        if compliance is None:
            return {"status": "unavailable"}
        try:
            products = data.get("products", [])
            return compliance.full_audit(products=products if products else None)
        except Exception as exc:
            logger.warning("Compliance check failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _phase_judgment(self, intel: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        """Run JudgmentAdvisor — check if decision should proceed."""
        advisor = self._modules.get("judgment_advisor")
        if advisor is None:
            return {"verdict": "proceed", "reason": "No judgment advisor"}
        try:
            decision = intel.get("decision", {})
            situation = self.snapshot.get_situation()
            return advisor.evaluate(decision, situation)
        except Exception as exc:
            logger.warning("Judgment failed: %s", exc)
            return {"verdict": "proceed", "reason": f"Judgment error: {exc}"}

    def _recall_episodes(self) -> list[dict[str, Any]]:
        """Recall similar past episodes BEFORE making decisions."""
        memory = self._modules.get("episodic_memory")
        if memory is None:
            return []
        try:
            context = {
                "health_grade": self.snapshot.financial.get("health_grade", "?"),
                "churn_pct": self.snapshot.customers.get("churn_risk_pct", 0),
                "stockout_risk": self.snapshot.inventory.get("stockout_risk", False),
                "confidence_score": 50,
                "net_margin": self.snapshot.financial.get("net_margin", 0),
            }
            return memory.recall_similar(context, limit=3)
        except Exception:
            return []

    def _build_expert_context(
        self,
        fin_depth: dict[str, Any],
        mkt_tactics: dict[str, Any],
        journey: dict[str, Any],
        supply: dict[str, Any],
        compliance: dict[str, Any],
    ) -> dict[str, Any]:
        """Build expert context dict for IntelligenceLoop enrichment."""
        return {
            "bnpl_recommendation": fin_depth.get("bnpl_opportunity", {}).get("recommendation"),
            "chargeback_risk": fin_depth.get("chargeback_risk", {}).get("risk_level"),
            "working_capital_days": fin_depth.get("working_capital", {}).get("cash_conversion_cycle_days"),
            "creative_fatigue_count": mkt_tactics.get("creative_fatigue", {}).get("fatigued_campaigns", 0),
            "weak_social_proof": mkt_tactics.get("social_proof_audit", {}).get("weak_social_proof", 0),
            "influencer_tier": mkt_tactics.get("influencer_strategy", {}).get("recommended_tier"),
            "lifecycle_action": journey.get("lifecycle_segments", {}).get("top_action"),
            "biggest_dropoff": journey.get("journey_map", {}).get("biggest_dropoff"),
            "reorder_urgent": supply.get("reorder_analysis", {}).get("urgent_reorders", 0),
            "dead_stock_value": supply.get("dead_stock", {}).get("total_capital_tied_up", 0),
            "free_shipping_threshold": supply.get("shipping_optimization", {}).get("recommended_threshold"),
            "compliance_violations": compliance.get("violation_count", 0),
        }

    def _record_episode(self, results: dict[str, Any]) -> None:
        """Record this cycle as an episode in episodic memory."""
        memory = self._modules.get("episodic_memory")
        if memory is None:
            return
        try:
            summary = results.get("summary", {})
            financial = results.get("phases", {}).get("financial", {})
            intel = results.get("phases", {}).get("intelligence", {})
            decision = intel.get("decision", {})

            context = {
                "health_grade": summary.get("health_grade", "?"),
                "churn_pct": self.snapshot.customers.get("churn_risk_pct", 0),
                "stockout_risk": self.snapshot.inventory.get("stockout_risk", False),
                "confidence_score": summary.get("confidence_score", 0),
                "net_margin": financial.get("pnl", {}).get("net_margin_pct", 0),
                "critical_alerts": self.snapshot.financial.get("critical_alerts", 0),
            }

            success = intel.get("stages_completed", 0) == 7 and not results.get("blocked", False)
            dt = decision.get("action", "cycle").split()[0].lower() if decision.get("action") else "cycle"

            episode_id = memory.record_episode(
                decision_type=dt,
                action=summary.get("decision", "none"),
                context=context,
                outcome={
                    "success": success,
                    "confidence": summary.get("confidence_score", 0),
                    "data_quality": summary.get("data_quality", 0),
                    "blocked": results.get("blocked", False),
                },
                goal=results.get("goal", ""),
                confidence_score=summary.get("confidence_score", 0),
            )

            # Run RootCauseAnalyzer on failures
            if not success:
                rca = self._modules.get("root_cause_analyzer")
                if rca:
                    try:
                        episode = {
                            "episode_id": episode_id,
                            "decision_type": dt,
                            "action": summary.get("decision", "none"),
                            "context": context,
                        }
                        rca_result = rca.analyze_failure(episode)
                        logger.info("Root cause analysis: %s", rca_result.get("lesson", "")[:100])
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug("Episode recording failed: %s", exc)

    # ── Helper methods ──

    def _enrich_data(
        self,
        data: dict[str, Any],
        financial: dict[str, Any],
        campaigns: dict[str, Any],
        competitive: dict[str, Any],
    ) -> dict[str, Any]:
        """Enrich raw data with insights from financial/campaign/competitive analysis."""
        enriched = dict(data)

        # Add financial context for IntelligenceLoop
        if financial.get("status") != "error" and financial.get("status") != "unavailable":
            enriched["_financial"] = {
                "net_margin": financial.get("pnl", {}).get("net_margin", 0),
                "net_profit": financial.get("pnl", {}).get("net_profit", 0),
                "cash_flow": financial.get("cash_flow", {}),
                "margin_alerts_count": len(financial.get("margin_alerts", [])),
                "health_grade": financial.get("health", {}).get("grade", "?"),
            }

        # Add campaign context
        if campaigns.get("status") != "unavailable":
            enriched["_campaigns"] = campaigns

        # Add competitive context
        if competitive.get("status") != "unavailable":
            enriched["_competitive"] = competitive

        return enriched

    def _record_kpis(self, cycle_id: str, intel: dict[str, Any], goal: str) -> None:
        """Record KPIs from this cycle."""
        kpi = self._modules.get("kpi_tracker")
        if kpi is None:
            return

        try:
            decision = intel.get("decision", {})
            kpi.record_decision_outcome(
                decision_id=cycle_id,
                decision_type=f"cycle_{goal}",
                confidence=decision.get("confidence", "unknown"),
                confidence_score=decision.get("confidence_score", 50),
                success=intel.get("stages_completed", 0) == 7,
                data_quality=intel.get("data_quality", 50),
                execution_results=intel.get("execution", {}),
            )
        except Exception as exc:
            logger.debug("KPI recording failed: %s", exc)

    def _compute_summary(self, results: dict[str, Any]) -> dict[str, Any]:
        """Compute a human-readable summary of the cycle."""
        phases = results.get("phases", {})

        # Extract key metrics from IntelligenceLoop output
        intel = phases.get("intelligence", {})
        decision = intel.get("decision", {})
        financial = phases.get("financial", {})
        strategy = phases.get("strategy", {})
        health = phases.get("health", {})
        events = phases.get("events", {})

        return {
            "decision": decision.get("action", "none"),
            "decision_reason": decision.get("reason", ""),
            "confidence": decision.get("confidence", "unknown"),
            "confidence_score": decision.get("confidence_score", 0),
            "data_quality": intel.get("data_quality", 0),
            "options_evaluated": decision.get("options_evaluated", 0),
            "net_profit": financial.get("pnl", {}).get("net_profit", "?"),
            "net_margin": financial.get("pnl", {}).get("net_margin", "?"),
            "health_grade": health.get("overall_grade", financial.get("health", {}).get("grade", "?")),
            "strategy_goal": strategy.get("current_goal", results.get("goal")),
            "strategy_switch": strategy.get("autopilot", {}).get("should_switch", False),
            "events_fired": events.get("events_fired", 0),
            "modules_active": len(self._modules),
            "intel_summary": intel.get("summary", ""),
        }

    # ── Public API ──

    def status(self) -> dict[str, Any]:
        """Get current orchestrator status."""
        return {
            "initialized": self._initialized,
            "modules_loaded": list(self._modules.keys()),
            "modules_count": len(self._modules),
            "cycles_completed": self._cycle_count,
            "last_cycle": self._history[-1] if self._history else None,
            "snapshot_age": round(time.time() - self.snapshot.last_updated, 1) if self.snapshot.last_updated else None,
            "journal_entries": self.journal.get_stats().get("total_entries", 0),
            "actions_in_flight": len(self.action_coordinator.get_in_flight()),
        }

    def get_situation(self) -> dict[str, Any]:
        """Get current store situation without running a cycle."""
        situation = self.snapshot.get_situation()
        situation["alerts"] = self.snapshot.get_alerts()
        situation["patterns"] = self.journal.detect_patterns()
        return situation

    def check_action(self, action_type: str, target_id: str = "") -> dict[str, Any]:
        """Check if an action is allowed (no conflicts, no cooldowns)."""
        return self.action_coordinator.check(action_type, target_id)

    def execute_action(self, action_type: str, target_id: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute an action with coordination (conflict check + record)."""
        verdict = self.action_coordinator.check(action_type, target_id)
        if not verdict["allowed"]:
            return {"status": "blocked", **verdict}

        action_id = self.action_coordinator.start_action(action_type, target_id)
        # Actual execution would go here via ExecutionBridge
        self.action_coordinator.finish_action(action_type, target_id, "success", metadata)
        return {"status": "executed", "action_id": action_id, "action_type": action_type}

    def react(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Handle a real-time event. Critical events trigger immediate mini-cycle."""
        reactor = self._modules.get("event_reactor")
        if reactor:
            try:
                reactor.fire(event_type, data)
            except Exception as exc:
                logger.warning("Event reactor failed: %s", exc)

        self.journal.record_event(event_type, data)

        # Critical events trigger immediate cycle
        critical_events = {"revenue.drop", "product.out_of_stock", "order.cancelled"}
        if event_type in critical_events:
            logger.info("Critical event %s — triggering immediate cycle", event_type)
            return self.run_cycle()

        return {"status": "processed", "event_type": event_type}

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent cycle history."""
        return self._history[-limit:]

    def get_journal_stats(self) -> dict[str, Any]:
        """Get journal statistics and patterns."""
        return {
            "stats": self.journal.get_stats(),
            "patterns": self.journal.detect_patterns(),
            "recent_decisions": self.journal.get_decisions(limit=5),
        }

    # ------------------------------------------------------------------
    # Layer + Agent integration
    # ------------------------------------------------------------------

    def run_layer(self, layer_name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Run a named layer from the layer system.

        Layers group engines into domain pipelines (data, analysis, product, etc.).
        Each layer has a flow.py that orchestrates its engines.

        Args:
            layer_name: One of the 12 layer names (e.g. "data_layer", "pricing_layer")
            data: Input data for the layer

        Returns:
            Layer output dict with accumulated engine results.
        """
        try:
            import importlib
            mod = importlib.import_module(f"layers.{layer_name}")
            # Find the flow class (ends with 'LayerFlow')
            flow_cls = None
            for attr_name in dir(mod):
                if attr_name.endswith("LayerFlow"):
                    flow_cls = getattr(mod, attr_name)
                    break
            if flow_cls is None:
                return {"status": "error", "error": f"No LayerFlow class in {layer_name}"}

            flow = flow_cls()
            payload = {"status": "success", "data": data, "meta": {}, "error": None}
            result = flow.run(payload)
            if hasattr(self.journal, "record_decision"):
                self.journal.record_decision(f"layer:{layer_name}", result.get("meta", {}))
            return result
        except Exception as exc:
            logger.error("Layer %s failed: %s", layer_name, exc)
            return {"status": "error", "error": str(exc)}

    def run_agent(self, agent_name: str, goal: str, context: dict[str, Any],
                  constraints: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a named agent with plan→execute→evaluate→recommend cycle.

        Args:
            agent_name: One of 7 agents (research, product, marketing, finance, operations, customer, content)
            goal: What the agent should accomplish
            context: Domain-specific context data
            constraints: Optional constraints

        Returns:
            Agent output with plan, results, evaluation, recommendation.
        """
        try:
            import importlib
            mod = importlib.import_module(f"agents.{agent_name}")
            # Find the agent class (ends with 'Agent')
            agent_cls = None
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type) and attr_name.endswith("Agent") and attr_name != "BaseAgent":
                    agent_cls = attr
                    break
            if agent_cls is None:
                return {"status": "error", "error": f"No Agent class in {agent_name}"}

            agent = agent_cls()
            result = agent.run(goal=goal, context=context, constraints=constraints or {})
            if hasattr(self.journal, "record_decision"):
                self.journal.record_decision(f"agent:{agent_name}", {
                    "goal": goal, "status": result.get("status", "unknown"),
                })
            return result
        except Exception as exc:
            logger.error("Agent %s failed: %s", agent_name, exc)
            return {"status": "error", "error": str(exc)}

    def list_layers(self) -> list[str]:
        """List all available layers."""
        return [
            "data_layer", "analysis_layer", "product_layer", "pricing_layer",
            "customer_layer", "marketing_layer", "sales_layer", "operations_layer",
            "financial_layer", "intelligence_layer", "execution_layer", "scaling_layer",
        ]

    def list_available_agents(self) -> list[str]:
        """List all available agents."""
        return ["research", "product", "marketing", "finance", "operations", "customer", "content"]
