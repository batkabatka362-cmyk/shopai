"""A/B Testing — experiment designer.

Designs the experiment: defines hypothesis, control/treatment, primary
metric, guardrail metrics, and test methodology.

Model note: Would use Mistral for hypothesis refinement and methodology selection.
"""
from __future__ import annotations

import uuid
from typing import Any


def design_experiment(
    test_type: str,
    hypothesis: str,
    control: dict[str, Any],
    treatment: dict[str, Any],
    primary_metric: str,
    guardrail_metrics: list[str],
    current_rate: float,
    mde: float,
) -> dict[str, Any]:
    """Design an A/B test experiment with full specification.

    Args:
        test_type: Category of test (pricing, content, ads, ux).
        hypothesis: Human-readable hypothesis statement.
        control: Control variant parameters.
        treatment: Treatment variant parameters.
        primary_metric: The main metric to evaluate.
        guardrail_metrics: Metrics that must not degrade.
        current_rate: Baseline rate for the primary metric.
        mde: Minimum detectable effect (absolute).

    Returns:
        Structured dict with experiment design.
    """
    try:
        test_id = f"ab_{uuid.uuid4().hex[:10]}"

        # Determine expected direction from hypothesis
        direction = _infer_direction(hypothesis, primary_metric)

        # Build null hypothesis
        null_hypothesis = _build_null_hypothesis(primary_metric, direction)

        # Select test methodology based on metric type
        methodology = _select_methodology(primary_metric)

        # Generate descriptions for control and treatment
        control_desc = _describe_variant(control, test_type, "control")
        treatment_desc = _describe_variant(treatment, test_type, "treatment")

        # Validate guardrail metrics
        validated_guardrails = _validate_guardrails(
            guardrail_metrics, primary_metric,
        )

        experiment = {
            "test_id": test_id,
            "test_type": test_type,
            "hypothesis": hypothesis,
            "null_hypothesis": null_hypothesis,
            "primary_metric": primary_metric,
            "guardrail_metrics": validated_guardrails,
            "control_description": control_desc,
            "treatment_description": treatment_desc,
            "test_methodology": methodology,
            "expected_direction": direction,
            "model_note": (
                "Mistral would refine hypothesis wording, validate metric "
                "selection, and suggest additional guardrail metrics"
            ),
        }

        return {
            "status": "success",
            "experiment": experiment,
        }
    except Exception as exc:
        return {
            "status": "error",
            "experiment": {},
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _infer_direction(hypothesis: str, primary_metric: str) -> str:
    """Infer expected direction of change from hypothesis text."""
    h_lower = hypothesis.lower()

    increase_signals = [
        "increase", "improve", "boost", "raise", "higher",
        "more", "grow", "uplift", "enhance", "better",
    ]
    decrease_signals = [
        "decrease", "reduce", "lower", "drop", "less",
        "fewer", "minimize", "shrink", "cut",
    ]

    # Metrics where decrease is good
    inverse_metrics = {"bounce_rate", "cart_abandonment", "churn_rate", "cost"}

    inc_count = sum(1 for w in increase_signals if w in h_lower)
    dec_count = sum(1 for w in decrease_signals if w in h_lower)

    if primary_metric in inverse_metrics:
        # For inverse metrics, flip the interpretation
        if dec_count > inc_count:
            return "decrease"
        return "increase" if inc_count > dec_count else "decrease"

    if inc_count > dec_count:
        return "increase"
    if dec_count > inc_count:
        return "decrease"
    return "increase"  # default assumption


def _build_null_hypothesis(primary_metric: str, direction: str) -> str:
    """Build a formal null hypothesis statement."""
    metric_label = primary_metric.replace("_", " ")
    return (
        f"There is no statistically significant difference in "
        f"{metric_label} between the control and treatment groups."
    )


def _select_methodology(primary_metric: str) -> str:
    """Select the appropriate statistical test methodology."""
    proportion_metrics = {
        "conversion_rate", "click_through_rate", "bounce_rate",
        "signup_rate", "purchase_rate", "retention_rate",
        "churn_rate", "cart_abandonment",
    }
    if primary_metric in proportion_metrics:
        return "two-sample z-test"
    return "two-sample t-test"


def _describe_variant(
    params: dict[str, Any],
    test_type: str,
    role: str,
) -> str:
    """Generate a human-readable description of a variant."""
    if not params:
        return f"{role.capitalize()} variant with default parameters"

    parts = [f"{role.capitalize()} variant for {test_type} test:"]
    for key, value in params.items():
        label = key.replace("_", " ").title()
        parts.append(f"  {label}: {value}")

    return " | ".join(parts)


def _validate_guardrails(
    guardrail_metrics: list[str],
    primary_metric: str,
) -> list[str]:
    """Validate and deduplicate guardrail metrics."""
    default_guardrails = ["revenue_per_visitor", "bounce_rate"]

    validated = list(guardrail_metrics) if guardrail_metrics else []

    # Add defaults if not already present
    for metric in default_guardrails:
        if metric not in validated and metric != primary_metric:
            validated.append(metric)

    # Remove primary metric from guardrails (it is the primary)
    validated = [m for m in validated if m != primary_metric]

    return validated
