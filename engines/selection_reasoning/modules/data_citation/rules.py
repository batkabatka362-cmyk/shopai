"""Data Citation — constraint rules for citation quality and completeness.

Ensures citations are sufficient in number, cover required data categories,
and include the critical engines (profitability, demand, risk). Violations
indicate the reasoning report lacks adequate supporting evidence.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Citation rule definitions
# ---------------------------------------------------------------------------
CITATION_RULES: dict[str, dict[str, Any]] = {
    "minimum_citations": {
        "description": "Must include at least 5 data citations to support the decision",
        "threshold": 5,
        "severity": "critical",
        "action": "Extract more data points from engine results — check for missing sources",
    },
    "must_include_profitability": {
        "description": "Must cite at least one profitability data point (margin, ROI, cost)",
        "severity": "critical",
        "action": "Add profitability citation — sellers need to know the numbers",
    },
    "must_include_demand": {
        "description": "Must cite at least one demand data point (score, volume)",
        "severity": "critical",
        "action": "Add demand citation — market pull is essential context",
    },
    "must_include_risk": {
        "description": "Must cite at least one risk data point (composite risk, risk level)",
        "severity": "critical",
        "action": "Add risk citation — transparency about downside is non-negotiable",
    },
    "citations_must_have_source": {
        "description": "Every citation must name its source engine",
        "severity": "warning",
        "action": "Add source attribution — data without source is opinion",
    },
    "no_duplicate_citations": {
        "description": "Do not cite the same data point twice",
        "severity": "info",
        "action": "Deduplicate citations to keep the report clean",
    },
    "max_citations": {
        "description": "Cap at 15 citations to avoid information overload",
        "threshold": 15,
        "severity": "info",
        "action": "Trim to the most impactful citations",
    },
}


def validate_citations(
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate a list of citations against all citation rules.

    Args:
        citations: List of citation dicts with category, source, data_point.

    Returns:
        Dict with valid flag, violations, warnings, and passed rules.
    """
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    passed: list[str] = []

    categories = {c.get("category") for c in citations}

    # --- Minimum citations ---
    rule = CITATION_RULES["minimum_citations"]
    if len(citations) < rule["threshold"]:
        violations.append({
            "rule": "minimum_citations",
            "severity": rule["severity"],
            "detail": f"Found {len(citations)} citations (min {rule['threshold']})",
            "action": rule["action"],
        })
    else:
        passed.append("minimum_citations")

    # --- Must include profitability ---
    rule = CITATION_RULES["must_include_profitability"]
    if "profitability" not in categories:
        violations.append({
            "rule": "must_include_profitability",
            "severity": rule["severity"],
            "action": rule["action"],
        })
    else:
        passed.append("must_include_profitability")

    # --- Must include demand ---
    rule = CITATION_RULES["must_include_demand"]
    if "demand" not in categories:
        violations.append({
            "rule": "must_include_demand",
            "severity": rule["severity"],
            "action": rule["action"],
        })
    else:
        passed.append("must_include_demand")

    # --- Must include risk ---
    rule = CITATION_RULES["must_include_risk"]
    if "risk" not in categories:
        violations.append({
            "rule": "must_include_risk",
            "severity": rule["severity"],
            "action": rule["action"],
        })
    else:
        passed.append("must_include_risk")

    # --- Citations must have source ---
    rule = CITATION_RULES["citations_must_have_source"]
    sourceless = [c for c in citations if not c.get("source")]
    if sourceless:
        warnings.append({
            "rule": "citations_must_have_source",
            "severity": rule["severity"],
            "detail": f"{len(sourceless)} citation(s) missing source",
            "action": rule["action"],
        })
    else:
        passed.append("citations_must_have_source")

    # --- No duplicate citations ---
    rule = CITATION_RULES["no_duplicate_citations"]
    data_points = [c.get("data_point", "") for c in citations]
    duplicates = len(data_points) - len(set(data_points))
    if duplicates > 0:
        warnings.append({
            "rule": "no_duplicate_citations",
            "severity": rule["severity"],
            "detail": f"{duplicates} duplicate citation(s) found",
            "action": rule["action"],
        })
    else:
        passed.append("no_duplicate_citations")

    # --- Max citations ---
    rule = CITATION_RULES["max_citations"]
    if len(citations) > rule["threshold"]:
        warnings.append({
            "rule": "max_citations",
            "severity": rule["severity"],
            "detail": f"Found {len(citations)} citations (max {rule['threshold']})",
            "action": rule["action"],
        })
    else:
        passed.append("max_citations")

    return {
        "valid": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "passed_rules": passed,
        "total_citations": len(citations),
        "categories_covered": sorted(categories),
    }
