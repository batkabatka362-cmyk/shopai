"""
logic.py — Compliance cost assessment, path recommendations, and timeline estimation.

Higher-order functions that use rules and data to compute actionable
compliance plans for products that need certification.
"""

from .data import CERTIFICATION_COSTS, PROCESSING_TIMES
from .rules import REGULATORY_REQUIREMENTS, CERTIFICATION_REQUIREMENTS


def assess_compliance_cost(product):
    """Estimate total compliance cost for a product.

    Parameters
    ----------
    product : dict
        Must include 'category'.  May include 'certifications_held' (list).

    Returns
    -------
    dict  With keys: total_low, total_typical, total_high, line_items.
    """
    category = (product.get("category") or "general").lower()
    held = set(product.get("certifications_held") or [])
    reqs = REGULATORY_REQUIREMENTS.get(category, REGULATORY_REQUIREMENTS["general"])

    line_items = []
    total_low = 0
    total_typical = 0
    total_high = 0

    for cert in reqs["mandatory"]:
        if cert in held:
            continue
        costs = CERTIFICATION_COSTS.get(cert)
        if costs:
            line_items.append({
                "certification": cert,
                "cost_low": costs["low"],
                "cost_typical": costs["typical"],
                "cost_high": costs["high"],
                "required": True,
            })
            total_low += costs["low"]
            total_typical += costs["typical"]
            total_high += costs["high"]

    for cert in reqs.get("recommended", []):
        if cert in held:
            continue
        costs = CERTIFICATION_COSTS.get(cert)
        if costs:
            line_items.append({
                "certification": cert,
                "cost_low": costs["low"],
                "cost_typical": costs["typical"],
                "cost_high": costs["high"],
                "required": False,
            })

    return {
        "total_low": total_low,
        "total_typical": total_typical,
        "total_high": total_high,
        "line_items": line_items,
        "category": category,
    }


def recommend_compliance_path(violations):
    """Given a list of violations, recommend the cheapest path to compliance.

    Parameters
    ----------
    violations : list[dict]
        Each dict has 'certification' and 'severity' keys.

    Returns
    -------
    dict  With keys: steps (ordered list), estimated_cost, estimated_days.
    """
    steps = []
    total_cost = 0
    total_days = 0

    severity_order = {"critical": 0, "major": 1, "minor": 2}
    sorted_violations = sorted(
        violations,
        key=lambda v: severity_order.get(v.get("severity", "minor"), 2),
    )

    for violation in sorted_violations:
        cert = violation.get("certification", "unknown")
        costs = CERTIFICATION_COSTS.get(cert, {"low": 0, "typical": 0, "high": 0})
        times = PROCESSING_TIMES.get(cert, {"fast": 7, "typical": 14, "slow": 30})

        step = {
            "certification": cert,
            "severity": violation.get("severity", "minor"),
            "description": violation.get("description", f"Obtain {cert}"),
            "estimated_cost": costs["typical"],
            "estimated_days": times["typical"],
            "can_run_parallel": violation.get("severity") != "critical",
        }
        steps.append(step)
        total_cost += costs["typical"]

    # Critical steps are sequential; non-critical can overlap
    critical_days = sum(s["estimated_days"] for s in steps if not s["can_run_parallel"])
    parallel_days = max(
        (s["estimated_days"] for s in steps if s["can_run_parallel"]),
        default=0,
    )
    total_days = critical_days + parallel_days

    return {
        "steps": steps,
        "estimated_cost": total_cost,
        "estimated_days": total_days,
        "step_count": len(steps),
    }


def estimate_certification_timeline(category):
    """Estimate the total certification timeline for a product category.

    Returns the best-case, typical, and worst-case days assuming all
    mandatory certifications run in parallel where possible.

    Parameters
    ----------
    category : str

    Returns
    -------
    dict  With keys: fast_days, typical_days, slow_days, certifications.
    """
    cat = (category or "general").lower()
    reqs = REGULATORY_REQUIREMENTS.get(cat, REGULATORY_REQUIREMENTS["general"])
    certs = reqs.get("mandatory", [])

    fast_max = 0
    typical_max = 0
    slow_max = 0
    cert_details = []

    for cert in certs:
        times = PROCESSING_TIMES.get(cert, {"fast": 7, "typical": 14, "slow": 30})
        cert_details.append({"certification": cert, **times})
        fast_max = max(fast_max, times["fast"])
        typical_max = max(typical_max, times["typical"])
        slow_max = max(slow_max, times["slow"])

    return {
        "fast_days": fast_max,
        "typical_days": typical_max,
        "slow_days": slow_max,
        "certifications": cert_details,
        "category": cat,
        "note": "Assumes mandatory certifications run in parallel.",
    }
