"""Narrative constraint rules for quality and completeness.

These rules enforce that generated narratives are informative,
honest, and backed by data. Violations are flagged but do not
block output — they indicate quality degradation.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Narrative rule definitions
# ---------------------------------------------------------------------------
NARRATIVE_RULES: dict[str, dict[str, Any]] = {
    "max_word_count": {
        "description": "Narrative must be under 500 words to remain digestible",
        "threshold": 500,
        "severity": "warning",
        "action": "Trim verbose sections; prioritize data over filler",
    },
    "min_data_points": {
        "description": "Must include at least 3 supporting data points for credibility",
        "threshold": 3,
        "severity": "critical",
        "action": "Add more engine results as supporting evidence",
    },
    "must_mention_risk": {
        "description": "Every narrative must mention risk — hiding it destroys trust",
        "severity": "critical",
        "action": "Include risk level and at least one specific risk factor",
    },
    "must_start_with_conclusion": {
        "description": "Lead with the decision, then explain — do not bury the lede",
        "severity": "warning",
        "action": "Ensure summary appears before explanation paragraphs",
    },
    "no_unsubstantiated_claims": {
        "description": "Every claim must be backed by a data point or engine result",
        "severity": "warning",
        "action": "Replace vague adjectives with specific numbers",
    },
    "must_include_confidence_level": {
        "description": "Always state how confident we are in this recommendation",
        "severity": "warning",
        "action": "Include confidence level and data coverage percentage",
    },
    "balanced_tone": {
        "description": "Tone must be balanced — not overly optimistic or pessimistic",
        "severity": "info",
        "action": "Present both strengths and weaknesses of the selection",
    },
    "actionable_language": {
        "description": "Use language that guides the reader toward next steps",
        "severity": "info",
        "action": "End with a forward-looking statement or call to action",
    },
}


def validate_narrative(
    narrative: str,
    key_points: list[dict[str, str]],
) -> dict[str, Any]:
    """Validate a generated narrative against quality rules.

    Args:
        narrative: The full narrative text.
        key_points: List of key factor dicts with 'label' and 'value'.

    Returns:
        Dict with violations, warnings, passed rules, and overall valid flag.
    """
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    passed: list[str] = []

    words = narrative.split()
    word_count = len(words)
    narrative_lower = narrative.lower()

    # --- Max word count ---
    rule = NARRATIVE_RULES["max_word_count"]
    if word_count > rule["threshold"]:
        warnings.append({
            "rule": "max_word_count",
            "severity": rule["severity"],
            "word_count": word_count,
            "threshold": rule["threshold"],
            "action": rule["action"],
        })
    else:
        passed.append("max_word_count")

    # --- Min data points ---
    rule = NARRATIVE_RULES["min_data_points"]
    data_point_count = len(key_points)
    if data_point_count < rule["threshold"]:
        violations.append({
            "rule": "min_data_points",
            "severity": rule["severity"],
            "data_points": data_point_count,
            "threshold": rule["threshold"],
            "action": rule["action"],
        })
    else:
        passed.append("min_data_points")

    # --- Must mention risk ---
    rule = NARRATIVE_RULES["must_mention_risk"]
    risk_mentioned = "risk" in narrative_lower
    if not risk_mentioned:
        violations.append({
            "rule": "must_mention_risk",
            "severity": rule["severity"],
            "action": rule["action"],
        })
    else:
        passed.append("must_mention_risk")

    # --- Must include confidence ---
    rule = NARRATIVE_RULES["must_include_confidence_level"]
    confidence_mentioned = "confidence" in narrative_lower or "confident" in narrative_lower
    if not confidence_mentioned:
        warnings.append({
            "rule": "must_include_confidence_level",
            "severity": rule["severity"],
            "action": rule["action"],
        })
    else:
        passed.append("must_include_confidence_level")

    # --- Must start with conclusion ---
    rule = NARRATIVE_RULES["must_start_with_conclusion"]
    first_line = narrative.split("\n")[0] if narrative else ""
    starts_with_selection = (
        "selected" in first_line.lower()
        or "recommend" in first_line.lower()
        or "pick" in first_line.lower()
    )
    if not starts_with_selection:
        warnings.append({
            "rule": "must_start_with_conclusion",
            "severity": rule["severity"],
            "action": rule["action"],
        })
    else:
        passed.append("must_start_with_conclusion")

    return {
        "valid": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "passed_rules": passed,
        "word_count": word_count,
        "data_points": data_point_count,
        "risk_mentioned": risk_mentioned,
    }
