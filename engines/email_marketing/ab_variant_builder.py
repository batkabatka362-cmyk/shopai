"""Email Marketing Engine — A/B variant builder.

Builds A/B test variants for subject lines, content blocks, and CTAs.
Assigns split ratios and determines the primary test metric.

Model note: no model usage — deterministic variant construction.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Default split strategies
# ---------------------------------------------------------------------------

_SPLIT_STRATEGIES: dict[int, list[float]] = {
    2: [0.50, 0.50],
    3: [0.34, 0.33, 0.33],
    4: [0.25, 0.25, 0.25, 0.25],
}

# Minimum sample per variant for statistical significance
_MIN_SAMPLE_MAP: dict[str, int] = {
    "open_rate": 1000,
    "click_rate": 2500,
    "conversion_rate": 5000,
}

# Test metric per campaign goal
_TEST_METRICS: dict[str, str] = {
    "promotional": "click_rate",
    "nurture": "open_rate",
    "win-back": "open_rate",
    "announcement": "click_rate",
}

# CTA alternatives per goal
_CTA_VARIANTS: dict[str, list[str]] = {
    "promotional": ["Shop Now & Save", "Grab the Deal", "See the Sale"],
    "nurture": ["Explore More", "Read On", "Discover"],
    "win-back": ["Claim Your Offer", "Come Back & Save", "Redeem Now"],
    "announcement": ["Learn More", "See What's New", "Get Started"],
}


def build_ab_variants(
    goal: str,
    subject_lines: list[dict[str, Any]],
    body: dict[str, Any],
    audience_size: int,
) -> dict[str, Any]:
    """Build A/B test variants for the campaign.

    Args:
        goal: Campaign goal / type.
        subject_lines: SubjectLineSet subject_lines list.
        body: EmailBody result from body_composer.
        audience_size: Total reachable audience.

    Returns:
        Structured dict with ABVariantSet data.
    """
    try:
        goal_key = str(goal).lower().strip()
        subj_lines = copy.deepcopy(subject_lines)
        body_data = copy.deepcopy(body)

        test_metric = _TEST_METRICS.get(goal_key, "open_rate")
        min_sample = _MIN_SAMPLE_MAP.get(test_metric, 1000)

        # Decide how many variants we can support
        max_variants = min(len(subj_lines), 4)
        if audience_size > 0:
            # Need at least min_sample per variant
            affordable = max(audience_size // min_sample, 1)
            max_variants = min(max_variants, affordable)
        max_variants = max(max_variants, 2)  # always at least 2

        # Build variants
        variants: list[dict[str, Any]] = []
        cta_options = _CTA_VARIANTS.get(goal_key, _CTA_VARIANTS["promotional"])
        original_cta = body_data.get("cta_text", cta_options[0])

        for idx in range(max_variants):
            subj = subj_lines[idx] if idx < len(subj_lines) else subj_lines[-1]

            # Alternate CTA for even-indexed variants beyond the first
            cta = original_cta
            if idx > 0 and idx < len(cta_options):
                cta = cta_options[idx]

            variant_label = chr(65 + idx)  # A, B, C, D

            variants.append({
                "variant_id": f"variant_{variant_label}",
                "label": f"Variant {variant_label}",
                "subject_line": subj.get("text", ""),
                "subject_style": subj.get("style", ""),
                "cta_text": cta,
                "is_control": idx == 0,
            })

        # Assign split ratios
        split_ratios = _SPLIT_STRATEGIES.get(
            len(variants),
            [round(1.0 / len(variants), 2)] * len(variants),
        )

        # Adjust minimum sample size for actual audience
        effective_min_sample = min(min_sample, audience_size) if audience_size > 0 else min_sample

        return {
            "status": "success",
            "ab_variants": {
                "variants": variants,
                "split_ratios": split_ratios,
                "test_metric": test_metric,
                "minimum_sample_size": effective_min_sample,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "ab_variants": {},
            "error": f"A/B variant building failed: {exc}",
        }
