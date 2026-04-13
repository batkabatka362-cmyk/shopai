"""A/B Testing — sample size calculator.

Calculates minimum sample size using power analysis.
Pure Python math — no scipy dependency.

Uses the standard formula for two-proportion z-test:
  n = ((z_alpha * sqrt(2*p_bar*q_bar) + z_beta * sqrt(p1*q1 + p2*q2)) / (p2 - p1))^2

For continuous metrics (t-test):
  n = ((z_alpha + z_beta)^2 * 2 * sigma^2) / delta^2
"""
from __future__ import annotations

import math
from typing import Any


def calculate_sample_size(
    primary_metric: str,
    current_rate: float,
    mde: float,
    alpha: float = 0.05,
    power: float = 0.80,
    daily_traffic: int = 1000,
    num_variants: int = 2,
) -> dict[str, Any]:
    """Calculate minimum sample size per variant using power analysis.

    Args:
        primary_metric: The metric being tested.
        current_rate: Baseline rate for the primary metric.
        mde: Minimum detectable effect (absolute change).
        alpha: Significance level (default 0.05).
        power: Statistical power (default 0.80).
        daily_traffic: Total daily visitors available.
        num_variants: Number of variants including control.

    Returns:
        Structured dict with sample size calculation results.
    """
    try:
        if mde <= 0:
            return {
                "status": "error",
                "result": {},
                "error": "MDE must be positive",
            }
        if current_rate <= 0:
            return {
                "status": "error",
                "result": {},
                "error": "Current rate must be positive",
            }
        if daily_traffic <= 0:
            return {
                "status": "error",
                "result": {},
                "error": "Daily traffic must be positive",
            }

        # Get critical values from z-scores
        z_alpha = _z_score(1 - alpha / 2)  # two-tailed
        z_beta = _z_score(power)

        proportion_metrics = {
            "conversion_rate", "click_through_rate", "bounce_rate",
            "signup_rate", "purchase_rate", "retention_rate",
            "churn_rate", "cart_abandonment",
        }

        if primary_metric in proportion_metrics:
            n_per_variant = _sample_size_proportions(
                p1=current_rate,
                p2=current_rate + mde,
                z_alpha=z_alpha,
                z_beta=z_beta,
            )
        else:
            # For continuous metrics, estimate variance from rate
            # Assume coefficient of variation ~ 1.0 for revenue-like metrics
            sigma = current_rate * 1.0
            n_per_variant = _sample_size_means(
                delta=mde,
                sigma=sigma,
                z_alpha=z_alpha,
                z_beta=z_beta,
            )

        total_sample = n_per_variant * num_variants
        daily_per_variant = max(1, daily_traffic // num_variants)
        estimated_days = math.ceil(n_per_variant / daily_per_variant) if daily_per_variant > 0 else 0

        # Enforce minimum test duration of 7 days (full week cycle)
        estimated_days = max(estimated_days, 7)

        result = {
            "sample_size_per_variant": n_per_variant,
            "total_sample_size": total_sample,
            "baseline_rate": round(current_rate, 6),
            "mde": round(mde, 6),
            "alpha": alpha,
            "power": power,
            "estimated_days": estimated_days,
            "daily_traffic_per_variant": daily_per_variant,
        }

        return {
            "status": "success",
            "result": result,
        }
    except Exception as exc:
        return {
            "status": "error",
            "result": {},
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Core formulas (pure Python, no scipy)
# ---------------------------------------------------------------------------

def _sample_size_proportions(
    p1: float,
    p2: float,
    z_alpha: float,
    z_beta: float,
) -> int:
    """Sample size for two-proportion z-test.

    Formula:
        n = ((z_a * sqrt(2*p_bar*q_bar) + z_b * sqrt(p1*q1 + p2*q2)) / (p2 - p1))^2

    Where p_bar = (p1 + p2) / 2, q = 1 - p.
    """
    p_bar = (p1 + p2) / 2.0
    q_bar = 1.0 - p_bar
    q1 = 1.0 - p1
    q2 = 1.0 - p2

    numerator = (
        z_alpha * math.sqrt(2.0 * p_bar * q_bar)
        + z_beta * math.sqrt(p1 * q1 + p2 * q2)
    )
    denominator = abs(p2 - p1)

    if denominator == 0:
        return 0

    n = (numerator / denominator) ** 2
    return math.ceil(n)


def _sample_size_means(
    delta: float,
    sigma: float,
    z_alpha: float,
    z_beta: float,
) -> int:
    """Sample size for two-sample t-test (approximated with z).

    Formula:
        n = ((z_alpha + z_beta)^2 * 2 * sigma^2) / delta^2
    """
    if delta == 0:
        return 0

    n = ((z_alpha + z_beta) ** 2 * 2.0 * sigma ** 2) / (delta ** 2)
    return math.ceil(n)


# ---------------------------------------------------------------------------
# z-score lookup (inverse normal CDF approximation)
# ---------------------------------------------------------------------------

def _z_score(p: float) -> float:
    """Approximate inverse of the standard normal CDF.

    Uses the rational approximation by Abramowitz and Stegun (formula 26.2.23)
    with refinement. Accurate to ~4.5e-4.

    Args:
        p: Probability (0 < p < 1).

    Returns:
        z such that P(Z <= z) = p for standard normal Z.
    """
    if p <= 0.0 or p >= 1.0:
        raise ValueError(f"p must be in (0, 1), got {p}")

    if p < 0.5:
        return -_z_score(1.0 - p)

    # Rational approximation for 0.5 <= p < 1.0
    t = math.sqrt(-2.0 * math.log(1.0 - p))

    # Coefficients (Abramowitz & Stegun)
    c0 = 2.515517
    c1 = 0.802853
    c2 = 0.010328
    d1 = 1.432788
    d2 = 0.189269
    d3 = 0.001308

    z = t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)
    return z
