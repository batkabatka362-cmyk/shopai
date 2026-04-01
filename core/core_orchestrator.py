"""CoreOrchestrator — the central brain that coordinates ALL intelligence modules.

Unlike MainOrchestrator (which routes tasks to engines), CoreOrchestrator
connects the ~17 real intelligence modules into one coordinated decision cycle:

    Fetch Data → Financial Analysis → Campaign Analysis → Intelligence Loop
    → Strategy Optimization → Event Processing → Health Report

Each cycle produces a unified result with insights from all subsystems.
Outcomes feed back into learning, closing the loop.
"""
from __future__ import annotations

import os
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("core_orchestrator")


class CoreOrchestrator:
    """Coordinates all intelligence modules into one unified decision cycle.

    Usage:
        orchestrator = CoreOrchestrator()
        result = orchestrator.run_cycle(goal="maximize_profit")
    """

    def __init__(self) -> None:
        self._modules: dict[str, Any] = {}
        self._cycle_count = 0
        self._history: list[dict[str, Any]] = []
        self._initialized = False
        self._init_modules()

    def _init_modules(self) -> None:
        """Initialize all intelligence modules. Each is optional — failure doesn't block others."""
        module_specs = {
            "shopify_bridge": ("core.bridge.shopify_bridge", "ShopifyBridge", {
                "shop_url": os.getenv("SHOPAI_SHOPIFY_URL", ""),
                "api_key": os.getenv("SHOPAI_SHOPIFY_KEY", ""),
            }),
            "intelligence_loop": ("core.intelligence_loop", "IntelligenceLoop", {}),
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
        }

        for name, (module_path, class_name, kwargs) in module_specs.items():
            try:
                import importlib
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                self._modules[name] = cls(**kwargs)
                logger.info("Module loaded: %s", name)
            except Exception as exc:
                logger.warning("Module %s failed to load: %s", name, exc)

        self._initialized = True
        logger.info(
            "CoreOrchestrator initialized: %d/%d modules loaded",
            len(self._modules), len(module_specs),
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

        # ── Phase 5: INTELLIGENCE LOOP (core decision-making) ──
        # Enrich data with insights from phases 2-4
        enriched_data = self._enrich_data(data, financial, campaigns, competitive)
        intel = self._phase_intelligence(enriched_data, goal)
        results["phases"]["intelligence"] = intel

        # ── Phase 6: STRATEGY OPTIMIZATION ──
        strategy = self._phase_strategy(intel, goal)
        results["phases"]["strategy"] = strategy

        # ── Phase 7: EVENT PROCESSING ──
        events = self._phase_events(results)
        results["phases"]["events"] = events

        # ── Phase 8: HEALTH REPORT ──
        health = self._phase_health()
        results["phases"]["health"] = health

        # ── Record KPIs ──
        self._record_kpis(cycle_id, intel, goal)

        # ── Compute summary ──
        elapsed = time.monotonic() - start
        results["elapsed_seconds"] = round(elapsed, 3)
        results["summary"] = self._compute_summary(results)

        self._history.append({
            "cycle_id": cycle_id,
            "goal": goal,
            "summary": results["summary"],
            "elapsed": results["elapsed_seconds"],
            "timestamp": results["timestamp"],
        })

        logger.info(
            "Cycle %s completed in %.2fs — decision: %s, confidence: %s",
            cycle_id, elapsed,
            results["summary"].get("decision", "none"),
            results["summary"].get("confidence", "unknown"),
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
                    reactor.fire("revenue.drop", {
                        "product": alert.get("product", "unknown"),
                        "margin": alert.get("margin", 0),
                        "alert": "critical_margin",
                    })
                    events_fired.append(f"revenue.drop:{alert.get('product', '?')}")

            # Check competitive alerts
            competitive = cycle_results.get("phases", {}).get("competitive", {})
            for alert in competitive.get("alerts", []):
                reactor.fire("product.price_change", {
                    "source": "competitor",
                    "alert": alert,
                })
                events_fired.append("product.price_change:competitor")

            # Check campaign underperformance
            campaigns = cycle_results.get("phases", {}).get("campaigns", {})
            optimization = campaigns.get("optimization", {})
            for action in optimization.get("actions", []):
                if action.get("action") == "pause":
                    reactor.fire("campaign.underperform", {
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
        }

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent cycle history."""
        return self._history[-limit:]
