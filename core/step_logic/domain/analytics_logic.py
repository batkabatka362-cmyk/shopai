"""AnalyticsLogic — deep logic for analytics/reporting engines."""
from __future__ import annotations
import math
from typing import Any


class AnalyticsLogic:
    ANALYTICS_ENGINES = {
        "analytics", "store_analytics", "product_analytics", "customer_analytics",
        "marketing_analytics", "cohort_analysis", "ltv_prediction", "cac_optimization",
        "margin_analysis", "revenue_forecasting", "kpi_tracking", "anomaly_detection",
        "predictive_analytics", "trend_detection", "trend_forecasting", "demand_forecasting",
        "benchmark_analysis", "financial_modeling", "roi_calculator", "break_even",
        "unit_economics", "ab_test_analysis", "conversion_tracking", "attribution",
    }

    def applies_to(self, engine_name: str) -> bool:
        return engine_name in self.ANALYTICS_ENGINES

    def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        # Find numeric data and compute analytics
        metrics = self._extract_metrics(data)
        if metrics:
            result["metrics_summary"] = self._summarize_metrics(metrics)
            result["trends"] = self._detect_trends(metrics)
            result["anomalies"] = self._detect_anomalies(metrics)
            result["score"] = min(10, 5 + len(metrics) * 0.5)
            result["decision"] = "approve"
            result["reason"] = f"Analyzed {len(metrics)} metrics"
        else:
            result["score"] = 3
            result["decision"] = "reject"
            result["reason"] = "Insufficient numeric data for analysis"
        return result

    def execute(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        metrics = self._extract_metrics(data)
        if metrics:
            result["kpi_dashboard"] = {name: {"value": vals[-1] if vals else 0, "trend": self._trend_direction(vals)} for name, vals in metrics.items()}
            result["recommendations"] = self._generate_recommendations(metrics)
            result["generated"] = True
        return result

    def _extract_metrics(self, data: dict) -> dict[str, list[float]]:
        metrics = {}
        for key, value in data.items():
            if key.startswith("_"): continue
            if isinstance(value, (int, float)):
                metrics[key] = [float(value)]
            elif isinstance(value, list):
                nums = [float(v) for v in value if isinstance(v, (int, float))]
                if nums: metrics[key] = nums
                # Extract from list of dicts
                if value and isinstance(value[0], dict):
                    for field in value[0]:
                        vals = [float(item[field]) for item in value if isinstance(item.get(field), (int, float))]
                        if vals: metrics[f"{key}.{field}"] = vals
        return metrics

    def _summarize_metrics(self, metrics: dict[str, list]) -> dict:
        summary = {}
        for name, values in metrics.items():
            if not values: continue
            summary[name] = {
                "current": round(values[-1], 2),
                "avg": round(sum(values)/len(values), 2),
                "min": round(min(values), 2),
                "max": round(max(values), 2),
                "count": len(values),
            }
        return summary

    def _detect_trends(self, metrics: dict[str, list]) -> list[dict]:
        trends = []
        for name, values in metrics.items():
            if len(values) >= 3:
                direction = self._trend_direction(values)
                if direction != "stable":
                    trends.append({"metric": name, "direction": direction, "data_points": len(values)})
        return trends

    def _detect_anomalies(self, metrics: dict[str, list]) -> list[dict]:
        anomalies = []
        for name, values in metrics.items():
            if len(values) >= 5:
                mean = sum(values) / len(values)
                std = (sum((v-mean)**2 for v in values)/len(values))**0.5
                if std > 0:
                    latest = values[-1]
                    z = abs(latest - mean) / std
                    if z > 2:
                        anomalies.append({"metric": name, "value": latest, "z_score": round(z, 2), "expected": round(mean, 2)})
        return anomalies

    @staticmethod
    def _trend_direction(values: list[float]) -> str:
        if len(values) < 2: return "stable"
        first_half = sum(values[:len(values)//2]) / max(len(values)//2, 1)
        second_half = sum(values[len(values)//2:]) / max(len(values) - len(values)//2, 1)
        if second_half > first_half * 1.05: return "up"
        if second_half < first_half * 0.95: return "down"
        return "stable"

    def _generate_recommendations(self, metrics: dict[str, list]) -> list[str]:
        recs = []
        for name, values in metrics.items():
            direction = self._trend_direction(values)
            if direction == "down" and any(k in name.lower() for k in ("revenue", "conversion", "rate", "score")):
                recs.append(f"{name} is declining — investigate and optimize")
            if direction == "up" and any(k in name.lower() for k in ("cost", "error", "churn", "bounce")):
                recs.append(f"{name} is increasing — take corrective action")
        return recs[:5] if recs else ["All metrics within normal range"]
