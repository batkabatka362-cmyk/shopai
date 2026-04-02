"""A/B Testing -- winner selector.

Selects the winner based on three criteria:
  1. Statistical significance (p < 0.05)
  2. Practical significance (effect >= MDE)
  3. Sufficient sample size (actual >= required)

Produces a recommendation: "implement", "extend_test", or "stop_test".

Model note: Would use Qwen for structured decision output.
"""
from __future__ import annotations

from typing import Any


def select_winner(
    analysis: dict[str, Any],
    metrics: list[dict[str, Any]],
    mde: float,
    sample_size_per_variant: int,
    required_sample: int,
) -> dict[str, Any]:
    """Select the winning variant or declare no winner.

    Args:
        analysis: Statistical analysis result dict.
        metrics: Per-variant metric dicts.
        mde: Minimum detectable effect (absolute).
        sample_size_per_variant: Actual sample size per variant.
        required_sample: Required sample size per variant.

    Returns:
        Structured dict with winner decision.
    """
    try:
        if not analysis or not metrics:
            return {
                "status": "error",
                "winner": {},
                "error": "Missing analysis or metrics",
            }

        # ---- Check three criteria ----
        p_value = float(analysis.get("p_value", 1.0))
        effect_size = abs(float(analysis.get("effect_size", 0.0)))
        significant = bool(analysis.get("significant", False))

        statistically_significant = significant and p_value < 0.05
        practically_significant = effect_size >= mde
        sample_sufficient = sample_size_per_variant >= required_sample

        # ---- Identify control and treatment ----
        control = None
        treatment = None
        for m in metrics:
            if m.get("variant_name") == "control" or m.get("is_control"):
                control = m
            else:
                treatment = m

        if control is None or treatment is None:
            control = metrics[0]
            treatment = metrics[1] if len(metrics) > 1 else metrics[0]

        # ---- Decision logic ----
        if statistically_significant and practically_significant and sample_sufficient:
            # Clear winner -- determine which variant is better
            ctrl_rate = float(control.get("conversion_rate", 0.0))
            treat_rate = float(treatment.get("conversion_rate", 0.0))

            if treat_rate > ctrl_rate:
                winner_id = treatment.get("variant_id", "treatment")
                winner_name = treatment.get("variant_name", "treatment_a")
                reason = (
                    f"Treatment outperforms control: "
                    f"{treat_rate:.4f} vs {ctrl_rate:.4f} "
                    f"(p={p_value:.4f}, effect={effect_size:.4f})"
                )
            else:
                winner_id = control.get("variant_id", "control")
                winner_name = control.get("variant_name", "control")
                reason = (
                    f"Control outperforms treatment: "
                    f"{ctrl_rate:.4f} vs {treat_rate:.4f} "
                    f"(p={p_value:.4f}, effect={effect_size:.4f})"
                )

            recommendation = "implement"
            confidence = _compute_confidence(p_value, effect_size, mde, sample_sufficient)

        elif statistically_significant and not practically_significant:
            winner_id = "no_winner"
            winner_name = "no_winner"
            reason = (
                f"Statistically significant (p={p_value:.4f}) but effect "
                f"({effect_size:.4f}) below MDE ({mde:.4f})"
            )
            recommendation = "stop_test"
            confidence = 0.3

        elif not sample_sufficient:
            winner_id = "no_winner"
            winner_name = "no_winner"
            reason = (
                f"Insufficient sample: {sample_size_per_variant} of "
                f"{required_sample} required"
            )
            recommendation = "extend_test"
            confidence = 0.1

        else:
            winner_id = "no_winner"
            winner_name = "no_winner"
            reason = (
                f"Not statistically significant (p={p_value:.4f}). "
                f"Effect size: {effect_size:.4f}, MDE: {mde:.4f}"
            )
            recommendation = "extend_test"
            confidence = 0.2

        winner_result = {
            "winner": winner_id,
            "winner_name": winner_name,
            "reason": reason,
            "statistically_significant": statistically_significant,
            "practically_significant": practically_significant,
            "sample_sufficient": sample_sufficient,
            "recommendation": recommendation,
            "confidence": round(confidence, 4),
        }

        return {
            "status": "success",
            "winner": winner_result,
        }
    except Exception as exc:
        return {
            "status": "error",
            "winner": {},
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_confidence(
    p_value: float,
    effect_size: float,
    mde: float,
    sample_sufficient: bool,
) -> float:
    """Compute an overall confidence score (0.0 - 1.0).

    Combines statistical confidence (1 - p_value), practical significance
    ratio, and sample sufficiency into a single score.
    """
    # Statistical confidence component (weight: 0.50)
    stat_conf = max(0.0, min(1.0, 1.0 - p_value))

    # Practical significance component (weight: 0.30)
    if mde > 0:
        prac_conf = min(1.0, effect_size / mde)
    else:
        prac_conf = 0.0

    # Sample sufficiency component (weight: 0.20)
    sample_conf = 1.0 if sample_sufficient else 0.3

    confidence = 0.50 * stat_conf + 0.30 * prac_conf + 0.20 * sample_conf
    return max(0.0, min(1.0, confidence))
