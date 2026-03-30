"""AbConfig — A/B testing for engine configurations.

Run two config variants side by side, measure which performs better.
Never modifies engine code — only changes runtime config.
"""
from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("config.ab")


class AbConfig:
    """A/B test engine configurations."""

    def __init__(self) -> None:
        self._experiments: dict[str, dict[str, Any]] = {}
        self._results: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def create_experiment(
        self,
        experiment_id: str,
        engine_name: str,
        variant_a: dict[str, Any],
        variant_b: dict[str, Any],
        traffic_split: float = 0.5,
    ) -> dict[str, Any]:
        """Create an A/B config experiment."""
        experiment = {
            "id": experiment_id,
            "engine": engine_name,
            "variant_a": variant_a,
            "variant_b": variant_b,
            "traffic_split": traffic_split,
            "created_at": time.time(),
            "status": "running",
        }
        with self._lock:
            self._experiments[experiment_id] = experiment
            self._results[experiment_id] = []
        logger.info("A/B experiment '%s' created for engine '%s'", experiment_id, engine_name)
        return experiment

    def get_variant(self, experiment_id: str, request_id: str = "") -> dict[str, Any]:
        """Get which variant to use for a request. Deterministic by request_id."""
        with self._lock:
            exp = self._experiments.get(experiment_id)
            if exp is None or exp["status"] != "running":
                return {"variant": "control", "config": {}}

        # Deterministic split based on request hash
        hash_val = int(hashlib.md5(request_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        if hash_val < exp["traffic_split"]:
            return {"variant": "A", "config": exp["variant_a"]}
        else:
            return {"variant": "B", "config": exp["variant_b"]}

    def record_result(self, experiment_id: str, variant: str, metrics: dict[str, float]) -> None:
        """Record result for a variant."""
        with self._lock:
            if experiment_id not in self._results:
                self._results[experiment_id] = []
            self._results[experiment_id].append({
                "variant": variant,
                "metrics": metrics,
                "timestamp": time.time(),
            })

    def get_results(self, experiment_id: str) -> dict[str, Any]:
        """Get experiment results with statistical comparison."""
        with self._lock:
            results = list(self._results.get(experiment_id, []))
            exp = self._experiments.get(experiment_id, {})

        a_metrics = [r["metrics"] for r in results if r["variant"] == "A"]
        b_metrics = [r["metrics"] for r in results if r["variant"] == "B"]

        return {
            "experiment_id": experiment_id,
            "engine": exp.get("engine", "unknown"),
            "total_samples": len(results),
            "variant_a": self._summarize_metrics(a_metrics, "A"),
            "variant_b": self._summarize_metrics(b_metrics, "B"),
            "winner": self._determine_winner(a_metrics, b_metrics),
            "confidence": self._calc_confidence(len(a_metrics), len(b_metrics)),
        }

    def stop_experiment(self, experiment_id: str) -> None:
        with self._lock:
            if experiment_id in self._experiments:
                self._experiments[experiment_id]["status"] = "stopped"

    def list_experiments(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{"id": e["id"], "engine": e["engine"], "status": e["status"]} for e in self._experiments.values()]

    @staticmethod
    def _summarize_metrics(metrics: list[dict], variant: str) -> dict[str, Any]:
        if not metrics:
            return {"variant": variant, "samples": 0}
        all_keys = set()
        for m in metrics:
            all_keys.update(m.keys())
        summary = {"variant": variant, "samples": len(metrics)}
        for key in all_keys:
            values = [m[key] for m in metrics if key in m and isinstance(m[key], (int, float))]
            if values:
                summary[f"{key}_avg"] = round(sum(values) / len(values), 4)
        return summary

    @staticmethod
    def _determine_winner(a_metrics: list, b_metrics: list) -> str:
        if not a_metrics or not b_metrics:
            return "insufficient_data"
        a_scores = [m.get("score", m.get("quality", 0)) for m in a_metrics if isinstance(m.get("score", m.get("quality")), (int, float))]
        b_scores = [m.get("score", m.get("quality", 0)) for m in b_metrics if isinstance(m.get("score", m.get("quality")), (int, float))]
        if not a_scores or not b_scores:
            return "no_score_data"
        a_avg = sum(a_scores) / len(a_scores)
        b_avg = sum(b_scores) / len(b_scores)
        if abs(a_avg - b_avg) < 0.5:
            return "no_significant_difference"
        return "A" if a_avg > b_avg else "B"

    @staticmethod
    def _calc_confidence(n_a: int, n_b: int) -> str:
        total = n_a + n_b
        if total < 30: return "low"
        if total < 100: return "medium"
        return "high"
