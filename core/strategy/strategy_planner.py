"""StrategyPlanner — 30-day strategic plans with milestones.

System cycle бүрт шийдвэр гаргадаг, гэхдээ олон cycle-г хамарсан стратеги
төлөвлөж чадахгүй байсан. StrategyPlanner 30 хоногийн milestone-тай план бичнэ.

Plan types:
  - product_launch: research → price → content → marketing → optimize → scale
  - growth_sprint: baseline → experiment → double_down → expand → consolidate
  - recovery: diagnose → stabilize → rebuild → grow → sustain
  - seasonal_prep: plan → inventory → content → marketing → execute → review
"""
from __future__ import annotations

import threading
import time
from typing import Any

from utils.helpers import generate_id, safe_float, safe_int
from utils.logger import get_logger

logger = get_logger("strategy.planner")

# Plan templates with phases and milestones
PLAN_TEMPLATES = {
    "product_launch": {
        "description": "Launch a new product or product line",
        "duration_days": 30,
        "phases": [
            {"name": "research", "days": (1, 3), "goal": "Validate market demand and competition",
             "tasks": ["competitor_analysis", "demand_validation", "pricing_research"],
             "milestone": "Market validation complete — go/no-go decision"},
            {"name": "prepare", "days": (4, 7), "goal": "Set pricing, create content, prepare listing",
             "tasks": ["set_pricing", "product_photography", "write_descriptions", "seo_optimization"],
             "milestone": "Listing ready — all content created"},
            {"name": "soft_launch", "days": (8, 14), "goal": "Launch to small audience, gather feedback",
             "tasks": ["create_listing", "email_to_vip", "small_ad_test", "collect_reviews"],
             "milestone": "10+ orders, 3+ reviews collected"},
            {"name": "optimize", "days": (15, 21), "goal": "Optimize based on initial data",
             "tasks": ["analyze_conversion", "adjust_pricing", "optimize_ads", "improve_content"],
             "milestone": "Conversion rate > 2%, ROAS > 2x"},
            {"name": "scale", "days": (22, 30), "goal": "Scale winning channels",
             "tasks": ["increase_ad_budget", "expand_audiences", "cross_sell_setup", "inventory_reorder"],
             "milestone": "Profitable at scale — positive ROI confirmed"},
        ],
    },
    "growth_sprint": {
        "description": "Rapid growth push — increase revenue 20%+ in 30 days",
        "duration_days": 30,
        "phases": [
            {"name": "baseline", "days": (1, 3), "goal": "Measure current metrics as baseline",
             "tasks": ["record_baseline_revenue", "record_baseline_aov", "record_baseline_conversion", "identify_bottleneck"],
             "milestone": "Baseline recorded, #1 bottleneck identified"},
            {"name": "experiment", "days": (4, 14), "goal": "Run 3-5 experiments simultaneously",
             "tasks": ["test_new_pricing", "test_new_creative", "test_new_audience", "test_upsell", "test_email_sequence"],
             "milestone": "At least 2 experiments showing positive signal"},
            {"name": "double_down", "days": (15, 21), "goal": "Scale winning experiments, kill losers",
             "tasks": ["increase_budget_winners", "pause_losers", "optimize_landing_pages", "expand_email_segments"],
             "milestone": "Revenue up 10%+ from baseline"},
            {"name": "expand", "days": (22, 27), "goal": "Expand to new channels or audiences",
             "tasks": ["new_channel_test", "referral_program_launch", "influencer_outreach", "content_marketing"],
             "milestone": "New channel contributing 5%+ of revenue"},
            {"name": "consolidate", "days": (28, 30), "goal": "Document wins, set up for next sprint",
             "tasks": ["document_learnings", "update_playbook", "set_next_targets", "automate_winners"],
             "milestone": "20%+ revenue growth confirmed, playbook updated"},
        ],
    },
    "recovery": {
        "description": "Recover from revenue decline or crisis",
        "duration_days": 30,
        "phases": [
            {"name": "diagnose", "days": (1, 3), "goal": "Find root cause of decline",
             "tasks": ["analyze_traffic_sources", "check_conversion_funnel", "review_competitor_changes", "audit_customer_feedback"],
             "milestone": "Root cause identified with evidence"},
            {"name": "stabilize", "days": (4, 10), "goal": "Stop the bleeding",
             "tasks": ["fix_critical_issues", "pause_underperforming_spend", "resolve_customer_complaints", "ensure_inventory"],
             "milestone": "Revenue decline stopped or slowed"},
            {"name": "rebuild", "days": (11, 20), "goal": "Rebuild momentum",
             "tasks": ["relaunch_campaigns", "fresh_creative", "customer_winback", "improve_product_pages"],
             "milestone": "Revenue back to 80% of pre-decline level"},
            {"name": "grow", "days": (21, 27), "goal": "Push past previous levels",
             "tasks": ["expand_what_works", "test_new_offers", "loyalty_program", "referral_incentives"],
             "milestone": "Revenue exceeds pre-decline baseline"},
            {"name": "sustain", "days": (28, 30), "goal": "Prevent recurrence",
             "tasks": ["set_monitoring_alerts", "document_root_cause", "create_prevention_rules", "update_strategy"],
             "milestone": "Monitoring in place, prevention rules active"},
        ],
    },
    "seasonal_prep": {
        "description": "Prepare for seasonal sales event",
        "duration_days": 30,
        "phases": [
            {"name": "plan", "days": (1, 5), "goal": "Set targets and strategy",
             "tasks": ["set_revenue_target", "plan_promotions", "budget_allocation", "timeline_creation"],
             "milestone": "Full plan documented with targets"},
            {"name": "inventory", "days": (6, 12), "goal": "Ensure adequate stock",
             "tasks": ["forecast_demand", "place_orders", "arrange_backup_suppliers", "prep_packaging"],
             "milestone": "All inventory ordered, delivery confirmed"},
            {"name": "content", "days": (13, 18), "goal": "Create all marketing assets",
             "tasks": ["design_banners", "write_emails", "create_ads", "prep_landing_pages"],
             "milestone": "All creative assets ready"},
            {"name": "marketing", "days": (19, 24), "goal": "Build anticipation",
             "tasks": ["teaser_emails", "social_media_countdown", "influencer_activation", "ad_warmup"],
             "milestone": "Email list warmed up, ads running"},
            {"name": "execute", "days": (25, 28), "goal": "Execute the event",
             "tasks": ["launch_promotions", "monitor_inventory", "customer_support_ready", "real_time_optimization"],
             "milestone": "Revenue target hit or exceeded"},
            {"name": "review", "days": (29, 30), "goal": "Post-mortem and learnings",
             "tasks": ["calculate_roi", "document_learnings", "customer_followup", "plan_next_event"],
             "milestone": "Full retrospective documented"},
        ],
    },
}


class StrategyPlanner:
    """Creates and manages 30-day strategic plans.

    Usage:
        planner = StrategyPlanner()
        plan = planner.create_plan("product_launch", context={...})
        progress = planner.check_progress(plan_id)
    """

    def __init__(self) -> None:
        self._plans: dict[str, dict[str, Any]] = {}
        # Protect ``_plans`` from concurrent create/update.
        # Audit pass 51.
        self._lock = threading.RLock()

    def create_plan(
        self,
        plan_type: str,
        context: dict[str, Any] | None = None,
        custom_targets: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new strategic plan from a template."""
        # Defensive coercion. Audit pass 51.
        if not isinstance(plan_type, str) or plan_type not in PLAN_TEMPLATES:
            return {
                "status": "error",
                "error": f"Unknown plan type: {plan_type}",
                "available_types": list(PLAN_TEMPLATES.keys()),
            }

        template = PLAN_TEMPLATES[plan_type]
        plan_id = generate_id("plan")
        now = time.time()

        plan = {
            "plan_id": plan_id,
            "type": plan_type,
            "description": template["description"],
            "created_at": now,
            "duration_days": template["duration_days"],
            "status": "active",
            "current_day": 1,
            "current_phase": template["phases"][0]["name"],
            "context": context if isinstance(context, dict) else {},
            "custom_targets": custom_targets if isinstance(custom_targets, dict) else {},
            "phases": [],
        }

        for phase in template["phases"]:
            plan["phases"].append({
                "name": phase["name"],
                "days": phase["days"],
                "goal": phase["goal"],
                "tasks": [{"task": t, "status": "pending"} for t in phase["tasks"]],
                "milestone": phase["milestone"],
                "milestone_met": False,
                "status": "pending",
            })

        # Mark first phase as active
        plan["phases"][0]["status"] = "active"

        with self._lock:
            self._plans[plan_id] = plan
        logger.info("Plan created: %s (%s) — %d phases", plan_id, plan_type, len(plan["phases"]))

        return plan

    def check_progress(self, plan_id: str, current_day: int | None = None) -> dict[str, Any]:
        """Check progress of a plan and advance phases if needed."""
        with self._lock:
            plan = self._plans.get(plan_id) if isinstance(plan_id, str) else None
        if not plan:
            return {"status": "not_found", "plan_id": plan_id}

        if current_day is not None:
            plan["current_day"] = safe_int(current_day, default=plan.get("current_day", 1))

        day = safe_int(plan.get("current_day"), default=1)
        behind = False
        ahead = False

        for phase in plan["phases"]:
            start_day, end_day = phase["days"]
            if day >= start_day and day <= end_day:
                phase["status"] = "active"
                plan["current_phase"] = phase["name"]
            elif day > end_day:
                if not phase["milestone_met"]:
                    phase["status"] = "overdue"
                    behind = True
                else:
                    phase["status"] = "completed"
            else:
                if phase["milestone_met"]:
                    phase["status"] = "completed_early"
                    ahead = True

        # Calculate overall progress
        completed_phases = sum(1 for p in plan["phases"] if p["status"] in ("completed", "completed_early"))
        total_phases = len(plan["phases"])
        progress_pct = round(completed_phases / total_phases * 100)

        completed_tasks = sum(
            1 for p in plan["phases"] for t in p["tasks"] if t["status"] == "completed"
        )
        total_tasks = sum(len(p["tasks"]) for p in plan["phases"])

        return {
            "plan_id": plan_id,
            "type": plan["type"],
            "day": day,
            "current_phase": plan["current_phase"],
            "progress_pct": progress_pct,
            "phases_completed": completed_phases,
            "total_phases": total_phases,
            "tasks_completed": completed_tasks,
            "total_tasks": total_tasks,
            "behind_schedule": behind,
            "ahead_of_schedule": ahead,
            "status": "behind" if behind else "ahead" if ahead else "on_track",
            "phases": plan["phases"],
        }

    def complete_task(self, plan_id: str, phase_name: str, task_name: str) -> bool:
        """Mark a task as completed."""
        with self._lock:
            plan = self._plans.get(plan_id) if isinstance(plan_id, str) else None
            if not plan:
                return False

            for phase in plan["phases"]:
                if phase["name"] == phase_name:
                    for task in phase["tasks"]:
                        if task["task"] == task_name:
                            task["status"] = "completed"
                            # Check if all tasks in phase are done
                            if all(t["status"] == "completed" for t in phase["tasks"]):
                                phase["milestone_met"] = True
                                phase["status"] = "completed"
                            return True
        return False

    def recommend_plan_type(self, situation: dict[str, Any]) -> dict[str, Any]:
        """Recommend the best plan type based on current store situation."""
        # Defensive: None situation / non-dict situation crashed
        # the first ``.get()`` call. Audit pass 51.
        situation = situation if isinstance(situation, dict) else {}
        financial = situation.get("financial") or {}
        if not isinstance(financial, dict):
            financial = {}
        health_grade = financial.get("health_grade", "B")
        inventory = situation.get("inventory") or {}
        if not isinstance(inventory, dict):
            inventory = {}
        customers = situation.get("customers") or {}
        if not isinstance(customers, dict):
            customers = {}

        if health_grade in ("D", "F"):
            return {"plan_type": "recovery", "reason": f"Financial health {health_grade} — recovery needed"}

        if inventory.get("stockout_risk"):
            return {"plan_type": "seasonal_prep", "reason": "Inventory at risk — prepare and stabilize"}

        # ``churn_risk_pct`` can arrive as None or a string ("30%").
        # Pre-audit ``None > 30`` crashed. safe_float handles
        # both. Audit pass 51.
        churn_pct = safe_float(customers.get("churn_risk_pct"))
        if churn_pct > 30:
            return {"plan_type": "recovery", "reason": f"High churn ({churn_pct}%) — need retention focus"}

        return {"plan_type": "growth_sprint", "reason": "Store healthy — push for growth"}

    def get_active_plans(self) -> list[dict[str, Any]]:
        """Get all active plans."""
        with self._lock:
            return [
                {"plan_id": pid, "type": p["type"], "day": p["current_day"], "phase": p["current_phase"]}
                for pid, p in self._plans.items()
                if p["status"] == "active"
            ]

    def get_today_tasks(self, plan_id: str) -> list[dict[str, Any]]:
        """Get tasks for today's phase."""
        with self._lock:
            plan = self._plans.get(plan_id) if isinstance(plan_id, str) else None
        if not plan:
            return []

        day = safe_int(plan.get("current_day"), default=1)
        for phase in plan["phases"]:
            start, end = phase["days"]
            if start <= day <= end:
                return [
                    {"task": t["task"], "status": t["status"], "phase": phase["name"]}
                    for t in phase["tasks"]
                ]
        return []
