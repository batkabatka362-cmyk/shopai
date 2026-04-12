"""A/B Test Framework — auto-test prices, content, targeting and pick winners.

Creates experiments, splits traffic, tracks results, declares winners
with statistical significance.
"""
from __future__ import annotations

import hashlib
import math
import threading
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("intelligence.ab")

# ── Named constants ──────────────────────────────────────────
Z_SCORE_95_CONFIDENCE = 1.96           # two-tailed 95% significance
MIN_SAMPLES_PER_VARIANT = 10           # minimum impressions before test
MIN_LIFT_DENOMINATOR = 0.001           # floor to avoid division by zero


class ABFramework:
    """Production A/B testing framework."""

    def __init__(self) -> None:
        self._experiments: dict[str, dict[str, Any]] = {}
        self._results: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def create_experiment(self, name: str, test_type: str, variants: list[dict[str, Any]],
                           traffic_pct: float = 100, min_samples: int = 100) -> dict[str, Any]:
        """Create a new A/B experiment."""
        exp_id = generate_id("exp")
        experiment = {
            "id": exp_id, "name": name, "type": test_type,
            "variants": variants, "traffic_pct": traffic_pct,
            "min_samples": min_samples, "status": "running",
            "created_at": time.time(), "winner": None,
        }
        with self._lock:
            self._experiments[exp_id] = experiment
            self._results[exp_id] = []
        return experiment

    def assign_variant(self, exp_id: str, user_id: str) -> dict[str, Any]:
        """Deterministically assign a user to a variant."""
        with self._lock:
            exp = self._experiments.get(exp_id)
        if not exp or exp["status"] != "running":
            return {"variant": "control", "assigned": False}

        # Deterministic hash
        h = int(hashlib.md5(f"{exp_id}:{user_id}".encode()).hexdigest()[:8], 16)
        idx = h % len(exp["variants"])
        return {"variant_index": idx, "variant": exp["variants"][idx], "assigned": True}

    def record_conversion(self, exp_id: str, variant_index: int, revenue: float = 0) -> None:
        """Record a conversion for a variant."""
        with self._lock:
            if exp_id in self._results:
                self._results[exp_id].append({
                    "variant_index": variant_index, "converted": True,
                    "revenue": revenue, "timestamp": time.time(),
                })

    def record_impression(self, exp_id: str, variant_index: int) -> None:
        """Record an impression (view) for a variant."""
        with self._lock:
            if exp_id in self._results:
                self._results[exp_id].append({
                    "variant_index": variant_index, "converted": False,
                    "revenue": 0, "timestamp": time.time(),
                })

    def get_results(self, exp_id: str) -> dict[str, Any]:
        """Get experiment results with statistical analysis."""
        with self._lock:
            exp = self._experiments.get(exp_id)
            results = list(self._results.get(exp_id, []))
        if not exp:
            return {"error": "Experiment not found"}

        variant_stats = {}
        for i, variant in enumerate(exp["variants"]):
            records = [r for r in results if r["variant_index"] == i]
            impressions = len(records)
            conversions = sum(1 for r in records if r["converted"])
            revenue = sum(r.get("revenue", 0) for r in records if r["converted"])
            rate = conversions / max(impressions, 1) * 100

            variant_stats[i] = {
                "variant": variant, "impressions": impressions,
                "conversions": conversions, "conversion_rate": round(rate, 2),
                "revenue": round(revenue, 2),
                "revenue_per_impression": round(revenue / max(impressions, 1), 4),
            }

        # Statistical significance (z-test between first two variants)
        significance = self._test_significance(variant_stats)

        # Auto-declare winner
        winner = None
        total_samples = sum(v["impressions"] for v in variant_stats.values())
        if total_samples >= exp["min_samples"] and significance.get("significant"):
            winner_idx = significance.get("winner_index", 0)
            winner = {"variant_index": winner_idx, "variant": exp["variants"][winner_idx],
                       "lift_pct": significance.get("lift_pct", 0)}

        return {
            "experiment": exp["name"], "type": exp["type"],
            "status": "winner_found" if winner else exp["status"],
            "total_samples": total_samples,
            "variants": variant_stats,
            "significance": significance,
            "winner": winner,
            "ready_to_call": total_samples >= exp["min_samples"],
        }

    def auto_winner(self, exp_id: str) -> dict[str, Any]:
        """Check if we can declare a winner and stop the test."""
        results = self.get_results(exp_id)
        if results.get("winner"):
            with self._lock:
                if exp_id in self._experiments:
                    self._experiments[exp_id]["status"] = "completed"
                    self._experiments[exp_id]["winner"] = results["winner"]
            return {"action": "implement_winner", **results["winner"]}
        if results.get("ready_to_call"):
            return {"action": "no_significant_difference", "recommendation": "Extend test or try different variants"}
        return {"action": "keep_running", "samples_needed": max(0, 100 - results.get("total_samples", 0))}

    def list_experiments(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{"id": e["id"], "name": e["name"], "type": e["type"], "status": e["status"]}
                    for e in self._experiments.values()]

    def _test_significance(self, stats: dict) -> dict[str, Any]:
        if len(stats) < 2:
            return {"significant": False, "reason": "need_2_variants"}

        a = stats[0]
        b = stats[1]
        n_a, c_a = a["impressions"], a["conversions"]
        n_b, c_b = b["impressions"], b["conversions"]

        if n_a < MIN_SAMPLES_PER_VARIANT or n_b < MIN_SAMPLES_PER_VARIANT:
            return {"significant": False, "reason": "insufficient_samples"}

        rate_a = c_a / max(n_a, 1)
        rate_b = c_b / max(n_b, 1)
        pooled = (c_a + c_b) / max(n_a + n_b, 1)
        se = math.sqrt(pooled * (1 - pooled) * (1/max(n_a, 1) + 1/max(n_b, 1))) if pooled > 0 else 0
        z = (rate_b - rate_a) / se if se > 0 else 0
        significant = abs(z) > Z_SCORE_95_CONFIDENCE
        lift = ((rate_b - rate_a) / max(rate_a, MIN_LIFT_DENOMINATOR)) * 100

        winner_idx = 1 if rate_b > rate_a else 0

        return {
            "significant": significant,
            "z_score": round(z, 3),
            "confidence": f"{min(99.9, (1 - 2 * (1 - self._norm_cdf(abs(z)))) * 100):.1f}%" if se > 0 else "0%",
            "lift_pct": round(lift, 2),
            "winner_index": winner_idx if significant else None,
        }

    @staticmethod
    def _norm_cdf(x: float) -> float:
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))
