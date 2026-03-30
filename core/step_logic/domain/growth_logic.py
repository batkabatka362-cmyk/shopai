"""GrowthLogic — deep logic for growth/experiment/activation engines."""
from __future__ import annotations
import math
from typing import Any


class GrowthLogic:
    GROWTH_ENGINES = {
        "growth", "growth_loop", "growth_hacking", "growth_experiment",
        "north_star_metric", "activation_funnel", "aha_moment_detector",
        "onboarding_optimizer", "feature_adoption_tracker", "viral_coefficient",
        "network_effect", "flywheel", "product_market_fit", "mvp_builder",
        "experimentation", "ab_testing",
    }

    def applies_to(self, engine_name: str) -> bool:
        return engine_name in self.GROWTH_ENGINES

    def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        metrics = self._extract_metrics(data)

        if metrics:
            result["growth_metrics"] = self._compute_growth(metrics)
            result["experiment_candidates"] = self._suggest_experiments(metrics)

        # Always analyze funnel if data present
        funnel = self._analyze_funnel(data)
        if funnel.get("stages"):
            result["funnel_analysis"] = funnel

        result["score"] = 7.0
        result["decision"] = "approve"
        result["reason"] = "Growth analysis complete"
        return result

    def execute(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        result["growth_playbook"] = self._generate_playbook(data)
        result["experiment_queue"] = self._build_experiment_queue(data)
        result["north_star"] = self._define_north_star(data)
        result["generated"] = True
        return result

    def _compute_growth(self, metrics: dict) -> dict:
        growth = {}
        for name, values in metrics.items():
            if len(values) >= 2:
                current = values[-1]
                previous = values[-2]
                pct = ((current - previous) / previous * 100) if previous != 0 else 0
                growth[name] = {"current": current, "previous": previous, "growth_pct": round(pct, 1),
                                "direction": "up" if pct > 0 else "down" if pct < 0 else "flat"}
        return growth

    def _analyze_funnel(self, data: dict) -> dict:
        funnel = data.get("funnel_data", [])
        if isinstance(funnel, list) and funnel:
            stages = []
            for i, stage in enumerate(funnel):
                if isinstance(stage, dict):
                    count = int(stage.get("count", stage.get("users", 0)))
                    stages.append({"stage": stage.get("step", stage.get("name", f"step_{i}")), "count": count})

            if len(stages) >= 2:
                for i in range(1, len(stages)):
                    prev = stages[i-1]["count"]
                    curr = stages[i]["count"]
                    stages[i]["conversion_rate"] = round(curr / prev * 100, 1) if prev > 0 else 0
                    stages[i]["drop_off"] = prev - curr

                worst_idx = min(range(1, len(stages)), key=lambda i: stages[i].get("conversion_rate", 100))
                return {"stages": stages, "worst_step": stages[worst_idx]["stage"],
                        "overall_conversion": round(stages[-1]["count"] / stages[0]["count"] * 100, 2) if stages[0]["count"] > 0 else 0}

        return {"stages": [], "note": "No funnel data provided"}

    def _suggest_experiments(self, metrics: dict) -> list[dict]:
        experiments = []
        for name, values in metrics.items():
            if len(values) >= 2 and values[-1] < values[-2]:
                experiments.append({
                    "metric": name,
                    "hypothesis": f"Improve {name} by optimizing the user experience",
                    "priority": "high" if abs(values[-1] - values[-2]) / max(abs(values[-2]), 1) > 0.1 else "medium",
                })
        if not experiments:
            experiments.append({"metric": "conversion", "hypothesis": "Test new CTA copy to improve conversion", "priority": "medium"})
        return experiments[:5]

    def _generate_playbook(self, data: dict) -> list[dict]:
        return [
            {"phase": "acquisition", "tactics": ["SEO optimization", "Content marketing", "Paid ads"], "timeline": "Week 1-4"},
            {"phase": "activation", "tactics": ["Onboarding optimization", "First-purchase incentive", "Welcome email series"], "timeline": "Week 2-6"},
            {"phase": "retention", "tactics": ["Loyalty program", "Personalized recommendations", "Re-engagement emails"], "timeline": "Week 4-12"},
            {"phase": "referral", "tactics": ["Referral program", "Social sharing incentives", "UGC campaigns"], "timeline": "Week 6-16"},
            {"phase": "revenue", "tactics": ["Upsell/cross-sell", "Pricing optimization", "Bundle offers"], "timeline": "Ongoing"},
        ]

    def _build_experiment_queue(self, data: dict) -> list[dict]:
        return [
            {"experiment": "Homepage hero CTA test", "type": "ab_test", "metric": "conversion_rate", "duration_days": 14},
            {"experiment": "Free shipping threshold", "type": "ab_test", "metric": "aov", "duration_days": 7},
            {"experiment": "Product page layout", "type": "multivariate", "metric": "add_to_cart_rate", "duration_days": 21},
        ]

    def _define_north_star(self, data: dict) -> dict:
        return {
            "metric": "weekly_active_buyers",
            "definition": "Unique customers who make a purchase in a 7-day window",
            "target_growth": "10% month-over-month",
            "input_metrics": ["traffic", "conversion_rate", "repeat_purchase_rate"],
        }

    def _extract_metrics(self, data: dict) -> dict[str, list[float]]:
        metrics = {}
        for key, value in data.items():
            if key.startswith("_"): continue
            if isinstance(value, list) and value and isinstance(value[0], (int, float)):
                metrics[key] = [float(v) for v in value]
            elif isinstance(value, (int, float)):
                metrics[key] = [float(value)]
        return metrics
