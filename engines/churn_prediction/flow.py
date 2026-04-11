"""Churn Prediction Engine — orchestrates the full churn prediction pipeline.

This is the FLOW file.  It ONLY orchestrates — no business logic here.
Every step delegates to a dedicated module; this file wires them together.

Pipeline:
  Customer Data -> Feature Extractor -> Engagement Scorer ->
  Recency Analyzer -> Purchase Pattern Detector ->
  Churn Probability Calculator -> Risk Classifier ->
  Retention Recommender -> Output

Engine contract:
  Input:  {status, data: {customers: [...]}, meta, error}
  Output: {status, data: {predictions, summary, confidence}, meta, error}

Model usage summary:
  - Engagement Scorer:          Mistral (engagement pattern analysis)
  - Purchase Pattern Detector:  Mistral (pattern trend analysis)
  - Retention Recommender:      LLaMA   (retention strategy reasoning)
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .feature_extractor import extract_features
from .engagement_scorer import score_engagement
from .recency_analyzer import analyze_recency
from .purchase_pattern_detector import detect_purchase_patterns
from .churn_probability_calculator import calculate_churn_probability
from .risk_classifier import classify_risk
from .retention_recommender import recommend_retention
from .memory_writer import write_to_memory
from .memory_reader import find_past_predictions


class ChurnPredictionEngine:
    """Churn Prediction Engine — orchestrator only, no logic."""

    ENGINE_NAME = "churn_prediction"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full churn prediction pipeline.

        Accepts a raw dict (will be validated and deep-copied).
        Returns a ChurnPredictionOutput-shaped dict — always structured,
        never raises.
        """
        start = time.monotonic()

        try:
            return self._execute_pipeline(input_payload, start)
        except Exception as exc:
            return self._error_output(
                reason=f"Unexpected pipeline error: {exc}",
                elapsed=time.monotonic() - start,
            )

    # ------------------------------------------------------------------
    # Private pipeline
    # ------------------------------------------------------------------

    def _execute_pipeline(
        self,
        input_payload: dict[str, Any],
        start: float,
    ) -> dict[str, Any]:
        """Run each pipeline stage in sequence, short-circuiting on failure."""

        # Stage 0: Input validation and deep copy
        customers = self._validate_input(input_payload)
        if customers is None:
            return self._error_output(
                reason=(
                    "Invalid input: requires 'data.customers' as a non-empty "
                    "list of customer records, each with at least an 'id'."
                ),
                elapsed=time.monotonic() - start,
            )

        predictions: list[dict[str, Any]] = []
        total_probability = 0.0
        high_risk_count = 0

        for customer in customers:
            result = self._process_single_customer(customer)
            if result is None:
                continue

            predictions.append(result)
            total_probability += result["churn_probability"]
            if result["risk_level"] in ("critical", "high"):
                high_risk_count += 1

        total_analyzed = len(predictions)

        if total_analyzed == 0:
            return self._error_output(
                reason="No customers could be analyzed — all records failed processing.",
                elapsed=time.monotonic() - start,
            )

        avg_churn_probability = round(total_probability / total_analyzed, 4)

        # Confidence: based on data completeness across customers
        confidence = self._calculate_confidence(customers, total_analyzed)

        elapsed = time.monotonic() - start

        output: dict[str, Any] = {
            "status": "success",
            "data": {
                "predictions": predictions,
                "summary": {
                    "total_analyzed": total_analyzed,
                    "high_risk_count": high_risk_count,
                    "avg_churn_probability": avg_churn_probability,
                },
                "confidence": confidence,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": _now(),
                "elapsed_seconds": round(elapsed, 3),
                "models": {
                    "engagement_scorer": "mistral",
                    "purchase_pattern_detector": "mistral",
                    "retention_recommender": "llama",
                },
            },
            "error": None,
        }

        # Persist to memory for accuracy tracking
        write_to_memory(output)

        return output

    # ------------------------------------------------------------------
    # Single customer processing
    # ------------------------------------------------------------------

    def _process_single_customer(
        self,
        customer: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Run the full per-customer pipeline.  Returns None on failure."""

        # Stage 1: Feature Extractor (no model — deterministic)
        feature_result = extract_features(customer)
        if feature_result.get("status") != "success":
            return None
        features = feature_result["features"]

        # Stage 0.5: Check memory for past predictions
        customer_id = features.get("customer_id", "unknown")
        _prior = find_past_predictions(customer_id, min_confidence=0.1, max_results=3)

        # Stage 2: Engagement Scorer (model: Mistral)
        engagement_result = score_engagement(features, customer)
        if engagement_result.get("status") != "success":
            return None
        engagement = engagement_result["engagement"]

        # Stage 3: Recency Analyzer (no model — exponential decay)
        recency_result = analyze_recency(features, customer)
        if recency_result.get("status") != "success":
            return None
        recency = recency_result["recency"]

        # Stage 4: Purchase Pattern Detector (model: Mistral)
        pattern_result = detect_purchase_patterns(features, engagement, customer)
        if pattern_result.get("status") != "success":
            return None
        pattern = pattern_result["pattern"]

        # Stage 5: Churn Probability Calculator (no model — weighted)
        churn_result = calculate_churn_probability(
            features, recency, engagement, pattern,
        )
        if churn_result.get("status") != "success":
            return None
        churn = churn_result["churn"]

        probability = churn["probability"]
        contributions = churn["factor_contributions"]

        # Stage 6: Risk Classifier (no model — deterministic thresholds)
        risk_result = classify_risk(probability)
        if risk_result.get("status") != "success":
            return None
        classification = risk_result["classification"]
        risk_level = classification["level"]

        # Stage 7: Retention Recommender (model: LLaMA)
        retention_result = recommend_retention(risk_level, features)
        if retention_result.get("status") != "success":
            return None
        retention = retention_result["retention"]

        # Build key factors: top contributors sorted by weight
        key_factors = self._extract_key_factors(contributions, pattern, recency)

        return {
            "customer_id": customer_id,
            "churn_probability": probability,
            "risk_level": risk_level,
            "key_factors": key_factors,
            "retention_action": retention["action"],
        }

    # ------------------------------------------------------------------
    # Key factor extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_key_factors(
        contributions: dict[str, float],
        pattern: dict[str, Any],
        recency: dict[str, Any],
    ) -> list[str]:
        """Extract human-readable key factors from churn contributions.

        Returns the top contributing factors sorted by contribution weight,
        enriched with context from pattern and recency analysis.
        """
        factor_labels: dict[str, str] = {
            "recency": "purchase_recency_gap",
            "frequency_change": "declining_order_frequency",
            "engagement_drop": "low_engagement_score",
            "aov_decline": "declining_average_order_value",
            "support_issues": "elevated_support_tickets",
        }

        # Sort contributions by value descending, take top 3
        sorted_factors = sorted(
            contributions.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        key_factors: list[str] = []
        for factor_key, value in sorted_factors:
            if value > 0.001 and len(key_factors) < 3:
                label = factor_labels.get(factor_key, factor_key)
                key_factors.append(label)

        # Add contextual signals if they are active
        if pattern.get("category_shift") and len(key_factors) < 4:
            key_factors.append("category_browsing_shift")
        if pattern.get("declining_engagement") and len(key_factors) < 4:
            key_factors.append("declining_engagement_signals")

        return key_factors if key_factors else ["no_significant_risk_factors"]

    # ------------------------------------------------------------------
    # Confidence calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_confidence(
        customers: list[dict[str, Any]],
        total_analyzed: int,
    ) -> float:
        """Calculate overall confidence based on data completeness.

        Checks how many of the expected input fields are present and non-zero
        across all successfully analyzed customers.
        """
        expected_fields = [
            "days_since_last_purchase",
            "total_orders",
            "total_spent",
            "avg_order_value",
            "email_open_rate",
            "site_visits_30d",
            "support_tickets_90d",
            "account_age_days",
        ]

        if total_analyzed == 0:
            return 0.0

        total_present = 0
        total_possible = total_analyzed * len(expected_fields)

        for customer in customers:
            for field in expected_fields:
                value = customer.get(field)
                if value is not None and value != 0 and value != "":
                    total_present += 1

        if total_possible == 0:
            return 0.0

        # Base confidence from data completeness (0.0 – 1.0)
        completeness = total_present / total_possible

        # Scale: minimum 0.3 if we got any results, max 0.95
        confidence = 0.3 + completeness * 0.65
        return round(min(0.95, confidence), 4)

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def _validate_input(
        self,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]] | None:
        """Validate and normalise the input into a usable customer list.

        Returns ``None`` if the input is unusable.
        Never mutates *payload*.
        """
        if not isinstance(payload, dict):
            return None

        safe = copy.deepcopy(payload)

        # Engine contract: payload is {status, data, meta, error}
        data = safe.get("data", safe)  # fallback to raw dict
        if not isinstance(data, dict):
            return None

        customers = data.get("customers", [])
        if not isinstance(customers, list) or not customers:
            return None

        # Validate each customer has at least an id
        valid_customers: list[dict[str, Any]] = []
        for customer in customers:
            if not isinstance(customer, dict):
                continue
            if not customer.get("id"):
                continue
            valid_customers.append(customer)

        return valid_customers if valid_customers else None

    # ------------------------------------------------------------------
    # Error output helper
    # ------------------------------------------------------------------

    def _error_output(self, *, reason: str, elapsed: float) -> dict[str, Any]:
        """Build a well-formed error response."""
        return {
            "status": "fail",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": _now(),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
