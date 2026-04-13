"""A/B Testing -- statistical analyzer.

Performs statistical analysis on A/B test results:
  - Z-test for proportions (conversion rate, click-through rate, etc.)
  - T-test for means (revenue per visitor, time on page, etc.)
  - P-value calculation using normal CDF approximation
  - Confidence intervals
  - Effect size (absolute and relative)
  - Achieved power

Pure Python math -- no scipy dependency.

Model note: Would use Mistral for interpreting results and generating
            human-readable statistical summaries.
"""
from __future__ import annotations

import math
from typing import Any


def analyze_statistics(
    metrics: list[dict[str, Any]],
    primary_metric: str,
    alpha: float = 0.05,
    methodology: str = "two-sample z-test",
) -> dict[str, Any]:
    """Run the appropriate statistical test on variant metrics.

    Args:
        metrics: Per-variant metric dicts (must have at least 2).
        primary_metric: The metric being compared.
        alpha: Significance level.
        methodology: "two-sample z-test" or "two-sample t-test".

    Returns:
        Structured dict with full statistical results.
    """
    try:
        if len(metrics) < 2:
            return {
                "status": "error",
                "analysis": {},
                "error": "Need at least 2 variants for comparison",
            }

        # Identify control and treatment
        control = None
        treatment = None
        for m in metrics:
            if m.get("variant_name") == "control" or m.get("is_control"):
                control = m
            else:
                treatment = m

        if control is None or treatment is None:
            # Fallback: first is control, second is treatment
            control = metrics[0]
            treatment = metrics[1]

        if methodology == "two-sample z-test":
            analysis = _z_test_proportions(control, treatment, primary_metric, alpha)
        else:
            analysis = _t_test_means(control, treatment, primary_metric, alpha)

        return {
            "status": "success",
            "analysis": analysis,
        }
    except Exception as exc:
        return {
            "status": "error",
            "analysis": {},
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Z-test for proportions
# ---------------------------------------------------------------------------

def _z_test_proportions(
    control: dict[str, Any],
    treatment: dict[str, Any],
    primary_metric: str,
    alpha: float,
) -> dict[str, Any]:
    """Two-sample z-test for proportions.

    H0: p_treatment = p_control
    H1: p_treatment != p_control  (two-tailed)

    Z = (p2 - p1) / sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))
    """
    n1 = int(control.get("visitors", 0))
    n2 = int(treatment.get("visitors", 0))

    if n1 == 0 or n2 == 0:
        return _empty_analysis("Insufficient visitors", "z-test")

    x1 = int(control.get("conversions", 0))
    x2 = int(treatment.get("conversions", 0))

    p1 = x1 / n1
    p2 = x2 / n2

    # Pooled proportion under H0
    p_pool = (x1 + x2) / (n1 + n2)
    q_pool = 1.0 - p_pool

    if p_pool <= 0.0 or p_pool >= 1.0:
        return _empty_analysis("Pooled proportion at boundary", "z-test")

    se = math.sqrt(p_pool * q_pool * (1.0 / n1 + 1.0 / n2))

    if se == 0.0:
        return _empty_analysis("Standard error is zero", "z-test")

    z = (p2 - p1) / se

    # Two-tailed p-value
    p_value = 2.0 * (1.0 - _normal_cdf(abs(z)))
    p_value = max(0.0, min(1.0, p_value))

    # Confidence interval for the difference (p2 - p1)
    se_diff = math.sqrt(p1 * (1.0 - p1) / n1 + p2 * (1.0 - p2) / n2)
    z_crit = _z_score(1.0 - alpha / 2.0)
    diff = p2 - p1
    ci_lower = round(diff - z_crit * se_diff, 6)
    ci_upper = round(diff + z_crit * se_diff, 6)

    # Effect size (absolute and relative)
    effect_size = round(diff, 6)
    relative_effect = round((diff / p1) * 100.0, 2) if p1 > 0 else 0.0

    # Achieved power
    power_achieved = _compute_power(diff, se, alpha)

    significant = p_value < alpha

    return {
        "test_statistic": round(z, 4),
        "p_value": round(p_value, 6),
        "confidence_interval": (ci_lower, ci_upper),
        "effect_size": effect_size,
        "relative_effect": relative_effect,
        "power_achieved": round(power_achieved, 4),
        "significant": significant,
        "method": "z-test",
        "model_note": (
            "Mistral would provide human-readable interpretation of these "
            "results and flag potential confounds"
        ),
    }


# ---------------------------------------------------------------------------
# T-test for means
# ---------------------------------------------------------------------------

def _t_test_means(
    control: dict[str, Any],
    treatment: dict[str, Any],
    primary_metric: str,
    alpha: float,
) -> dict[str, Any]:
    """Two-sample t-test for means (Welch's approximation).

    Uses z-distribution approximation for large samples.

    t = (mean2 - mean1) / sqrt(s1^2/n1 + s2^2/n2)
    """
    n1 = int(control.get("visitors", 0))
    n2 = int(treatment.get("visitors", 0))

    if n1 == 0 or n2 == 0:
        return _empty_analysis("Insufficient visitors", "t-test")

    # Extract metric values
    mean1 = float(control.get(primary_metric, control.get("revenue_per_visitor", 0.0)))
    mean2 = float(treatment.get(primary_metric, treatment.get("revenue_per_visitor", 0.0)))

    # Estimate standard deviation as coefficient of variation * mean
    # CV ~ 1.0 is typical for revenue metrics
    cv = 1.0
    s1 = abs(mean1) * cv if mean1 != 0 else 1.0
    s2 = abs(mean2) * cv if mean2 != 0 else 1.0

    se = math.sqrt(s1 ** 2 / n1 + s2 ** 2 / n2)

    if se == 0.0:
        return _empty_analysis("Standard error is zero", "t-test")

    t_stat = (mean2 - mean1) / se

    # For large n, t-distribution ~ normal
    p_value = 2.0 * (1.0 - _normal_cdf(abs(t_stat)))
    p_value = max(0.0, min(1.0, p_value))

    # Confidence interval
    z_crit = _z_score(1.0 - alpha / 2.0)
    diff = mean2 - mean1
    ci_lower = round(diff - z_crit * se, 6)
    ci_upper = round(diff + z_crit * se, 6)

    effect_size = round(diff, 6)
    relative_effect = round((diff / mean1) * 100.0, 2) if mean1 != 0 else 0.0

    power_achieved = _compute_power(diff, se, alpha)

    significant = p_value < alpha

    return {
        "test_statistic": round(t_stat, 4),
        "p_value": round(p_value, 6),
        "confidence_interval": (ci_lower, ci_upper),
        "effect_size": effect_size,
        "relative_effect": relative_effect,
        "power_achieved": round(power_achieved, 4),
        "significant": significant,
        "method": "t-test",
        "model_note": (
            "Mistral would provide human-readable interpretation of these "
            "results and flag potential confounds"
        ),
    }


# ---------------------------------------------------------------------------
# Normal CDF approximation (pure Python, no scipy)
# ---------------------------------------------------------------------------

def _normal_cdf(x: float) -> float:
    """Approximate the standard normal cumulative distribution function.

    Uses the Abramowitz and Stegun approximation (formula 7.1.26)
    with the error function.  Accurate to ~1.5e-7.

    P(Z <= x) = 0.5 * (1 + erf(x / sqrt(2)))
    """
    return 0.5 * (1.0 + _erf(x / math.sqrt(2.0)))


def _erf(x: float) -> float:
    """Approximate the error function using Horner form.

    Abramowitz and Stegun, formula 7.1.26.
    Maximum error: 1.5e-7.
    """
    sign = 1.0
    if x < 0:
        sign = -1.0
        x = -x

    # Constants
    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911

    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)

    return sign * y


# ---------------------------------------------------------------------------
# Inverse normal CDF (z-score lookup)
# ---------------------------------------------------------------------------

def _z_score(p: float) -> float:
    """Approximate inverse of the standard normal CDF.

    Rational approximation by Abramowitz and Stegun (formula 26.2.23).
    Accurate to ~4.5e-4.
    """
    if p <= 0.0 or p >= 1.0:
        raise ValueError(f"p must be in (0, 1), got {p}")

    if p < 0.5:
        return -_z_score(1.0 - p)

    t = math.sqrt(-2.0 * math.log(1.0 - p))

    c0 = 2.515517
    c1 = 0.802853
    c2 = 0.010328
    d1 = 1.432788
    d2 = 0.189269
    d3 = 0.001308

    z = t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)
    return z


# ---------------------------------------------------------------------------
# Power computation
# ---------------------------------------------------------------------------

def _compute_power(effect: float, se: float, alpha: float) -> float:
    """Compute achieved statistical power.

    Power = P(reject H0 | H1 true)
          = 1 - beta
          = P(|Z| > z_crit | true effect)
    """
    if se <= 0.0:
        return 0.0

    z_crit = _z_score(1.0 - alpha / 2.0)
    noncentrality = abs(effect) / se

    # Power for two-tailed test
    power = (
        1.0
        - _normal_cdf(z_crit - noncentrality)
        + _normal_cdf(-z_crit - noncentrality)
    )
    return max(0.0, min(1.0, power))


# ---------------------------------------------------------------------------
# Empty / fallback result
# ---------------------------------------------------------------------------

def _empty_analysis(reason: str, method: str) -> dict[str, Any]:
    """Return a neutral analysis when computation is not possible."""
    return {
        "test_statistic": 0.0,
        "p_value": 1.0,
        "confidence_interval": (0.0, 0.0),
        "effect_size": 0.0,
        "relative_effect": 0.0,
        "power_achieved": 0.0,
        "significant": False,
        "method": method,
        "model_note": f"Analysis unavailable: {reason}",
    }
