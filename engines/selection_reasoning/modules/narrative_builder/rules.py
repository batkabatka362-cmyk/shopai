"""Narrative Builder — constraint rules for narrative quality.

Defines guardrails ensuring narratives are concise, data-driven,
and transparent about risk. Violating critical rules means the
narrative needs revision before being shown to the user.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Narrative rule definitions
# ---------------------------------------------------------------------------
NARRATIVE_RULES: dict[str, dict[str, Any]] = {
    "max_word_count": {
        "description": "Narrative must be under 500 words to stay readable",
        "threshold": 500,
        "severity": "critical",
        "action": "Trim narrative — remove redundant phrases and weak qualifiers",
    },
    "min_data_points": {
        "description": "Must include at least 3 supporting data points with numbers",
        "threshold": 3,
        "severity": "critical",
        "action": "Add more quantitative evidence — score, margin, demand numbers",
    },
    "must_mention_risk": {
        "description": "Narrative must explicitly mention risk level or risk factors",
        "severity": "critical",
        "action": "Add risk disclosure — hiding risks destroys trust",
    },
    "must_include_score": {
        "description": "Narrative must include the unified score",
        "severity": "warning",
        "action": "Include the product score to ground the recommendation",
    },
    "must_include_margin": {
        "description": "Narrative should include profit margin when available",
        "severity": "warning",
        "action": "Add margin data — it is the most important number for sellers",
    },
    "no_unsupported_superlatives": {
        "description": "Avoid 'best', 'perfect', 'guaranteed' without data backing",
        "severity": "warning",
        "action": "Replace superlatives with specific numbers",
    },
    "must_state_confidence": {
        "description": "Narrative must disclose the confidence level of the recommendation",
        "severity": "warning",
        "action": "Add confidence disclosure so the reader knows how reliable this is",
    },
    "conclusion_first": {
        "description": "Start with the conclusion (selection), then explain",
        "severity": "info",
        "action": "Restructure narrative to lead with the recommendation",
    },
}


def validate_narrative(
    narrative_text: str, data_points: dict[str, Any],
) -> dict[str, Any]:
    """Validate a narrative against all narrative rules.

    Args:
        narrative_text: The full assembled narrative string.
        data_points: The data points used in generation.

    Returns:
        Dict with valid flag, violations, warnings, and passed rules.
    """
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    passed: list[str] = []

    words = narrative_text.split()
    word_count = len(words)
    text_lower = narrative_text.lower()

    # --- Max word count ---
    rule = NARRATIVE_RULES["max_word_count"]
    if word_count > rule["threshold"]:
        violations.append({
            "rule": "max_word_count",
            "severity": rule["severity"],
            "detail": f"Narrative is {word_count} words (max {rule['threshold']})",
            "action": rule["action"],
        })
    else:
        passed.append("max_word_count")

    # --- Minimum data points ---
    rule = NARRATIVE_RULES["min_data_points"]
    numeric_mentions = _count_numeric_mentions(narrative_text)
    if numeric_mentions < rule["threshold"]:
        violations.append({
            "rule": "min_data_points",
            "severity": rule["severity"],
            "detail": f"Found {numeric_mentions} data points (min {rule['threshold']})",
            "action": rule["action"],
        })
    else:
        passed.append("min_data_points")

    # --- Must mention risk ---
    rule = NARRATIVE_RULES["must_mention_risk"]
    risk_keywords = ("risk", "downside", "threat", "vulnerability", "danger")
    mentions_risk = any(kw in text_lower for kw in risk_keywords)
    if not mentions_risk:
        violations.append({
            "rule": "must_mention_risk",
            "severity": rule["severity"],
            "detail": "Narrative does not mention risk",
            "action": rule["action"],
        })
    else:
        passed.append("must_mention_risk")

    # --- Must include score ---
    rule = NARRATIVE_RULES["must_include_score"]
    score = data_points.get("unified_score", 0)
    if str(int(score)) not in narrative_text and f"{score}" not in narrative_text:
        warnings.append({
            "rule": "must_include_score",
            "severity": rule["severity"],
            "action": rule["action"],
        })
    else:
        passed.append("must_include_score")

    # --- No unsupported superlatives ---
    rule = NARRATIVE_RULES["no_unsupported_superlatives"]
    bad_words = ("guaranteed", "perfect", "flawless", "risk-free", "can't fail")
    found_bad = [w for w in bad_words if w in text_lower]
    if found_bad:
        warnings.append({
            "rule": "no_unsupported_superlatives",
            "severity": rule["severity"],
            "detail": f"Found: {', '.join(found_bad)}",
            "action": rule["action"],
        })
    else:
        passed.append("no_unsupported_superlatives")

    # --- Must state confidence ---
    rule = NARRATIVE_RULES["must_state_confidence"]
    confidence_keywords = ("confidence", "confident", "certainty", "reliability")
    mentions_confidence = any(kw in text_lower for kw in confidence_keywords)
    if not mentions_confidence:
        warnings.append({
            "rule": "must_state_confidence",
            "severity": rule["severity"],
            "action": rule["action"],
        })
    else:
        passed.append("must_state_confidence")

    has_violations = len(violations) > 0

    return {
        "valid": not has_violations,
        "violations": violations,
        "warnings": warnings,
        "passed_rules": passed,
        "word_count": word_count,
        "data_points_found": numeric_mentions,
    }


def _count_numeric_mentions(text: str) -> int:
    """Count distinct numeric data points in the narrative."""
    import re
    # Match numbers like 72.3, 45%, $1500, 100
    matches = re.findall(r'\d+\.?\d*[%]?', text)
    return len(set(matches))
