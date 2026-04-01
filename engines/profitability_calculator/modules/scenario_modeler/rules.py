"""
Scenario Modeler — Validation rules.

Enforces guardrails on scenario results: survivability in pessimistic
case, expected profitability, and risk tolerance boundaries.
"""


def validate_scenario_survivability(scenarios, budget):
    """
    Rule: pessimistic scenario loss must be less than 50% of total budget.
    A loss exceeding half the budget threatens business survival.

    Returns validation result with pass/fail, details, and threshold.
    """
    pessimistic = next((s for s in scenarios if s["label"] == "pessimistic"), None)
    if not pessimistic:
        return {
            "rule": "survivability",
            "passed": False,
            "reason": "No pessimistic scenario found",
            "details": {},
        }

    max_tolerable_loss = budget * 0.50
    actual_loss = abs(pessimistic["profit"]) if pessimistic["profit"] < 0 else 0
    passed = actual_loss <= max_tolerable_loss

    headroom = max_tolerable_loss - actual_loss
    headroom_pct = (headroom / max_tolerable_loss * 100) if max_tolerable_loss > 0 else 0

    severity = "safe"
    if not passed:
        overshoot_pct = (actual_loss - max_tolerable_loss) / max_tolerable_loss * 100
        if overshoot_pct > 100:
            severity = "critical"
        elif overshoot_pct > 50:
            severity = "severe"
        else:
            severity = "warning"

    return {
        "rule": "survivability",
        "passed": passed,
        "reason": (
            f"Pessimistic loss ${actual_loss:,.2f} is within budget threshold ${max_tolerable_loss:,.2f}"
            if passed
            else f"Pessimistic loss ${actual_loss:,.2f} exceeds 50% of budget ${max_tolerable_loss:,.2f}"
        ),
        "details": {
            "pessimistic_profit": pessimistic["profit"],
            "actual_loss": actual_loss,
            "max_tolerable_loss": max_tolerable_loss,
            "budget": budget,
            "headroom": round(headroom, 2),
            "headroom_pct": round(headroom_pct, 2),
            "severity": severity,
        },
    }


def validate_expected_profitability(scenarios):
    """
    Rule: the expected (base) scenario must show positive profit.
    If the most likely outcome is unprofitable, the venture is not viable.

    Returns validation result with margin and cash flow details.
    """
    expected = next((s for s in scenarios if s["label"] == "expected"), None)
    if not expected:
        return {
            "rule": "expected_profitability",
            "passed": False,
            "reason": "No expected scenario found",
            "details": {},
        }

    passed = expected["profit"] > 0
    margin_healthy = expected["margin"] > 10

    if passed and margin_healthy:
        grade = "strong"
    elif passed:
        grade = "marginal"
    else:
        grade = "unprofitable"

    return {
        "rule": "expected_profitability",
        "passed": passed,
        "reason": (
            f"Expected profit ${expected['profit']:,.2f} with {expected['margin']:.1f}% margin"
            if passed
            else f"Expected scenario shows loss of ${abs(expected['profit']):,.2f}"
        ),
        "details": {
            "profit": expected["profit"],
            "margin": expected["margin"],
            "revenue": expected["revenue"],
            "total_costs": expected["total_costs"],
            "cash_flow": expected["cash_flow"],
            "grade": grade,
            "margin_healthy": margin_healthy,
        },
    }


def validate_risk_tolerance(scenarios, risk_tolerance):
    """
    Rule: maximum downside across ALL scenarios must be within the
    stated risk tolerance. Includes custom scenarios if present.

    Returns validation with per-scenario risk breakdown.
    """
    if not scenarios:
        return {
            "rule": "risk_tolerance",
            "passed": False,
            "reason": "No scenarios to evaluate",
            "details": {},
        }

    worst = min(scenarios, key=lambda s: s["profit"])
    max_downside = abs(worst["profit"]) if worst["profit"] < 0 else 0
    passed = max_downside <= risk_tolerance

    breaches = []
    for s in scenarios:
        loss = abs(s["profit"]) if s["profit"] < 0 else 0
        if loss > risk_tolerance:
            breaches.append({
                "scenario": s["label"],
                "loss": loss,
                "overshoot": round(loss - risk_tolerance, 2),
            })

    utilization = (max_downside / risk_tolerance * 100) if risk_tolerance > 0 else 0

    return {
        "rule": "risk_tolerance",
        "passed": passed,
        "reason": (
            f"Max downside ${max_downside:,.2f} within tolerance ${risk_tolerance:,.2f}"
            if passed
            else f"Max downside ${max_downside:,.2f} exceeds tolerance ${risk_tolerance:,.2f}"
        ),
        "details": {
            "worst_scenario": worst["label"],
            "max_downside": max_downside,
            "risk_tolerance": risk_tolerance,
            "utilization_pct": round(utilization, 2),
            "breaching_scenarios": breaches,
            "scenarios_evaluated": len(scenarios),
        },
    }


def run_all_validations(scenarios, budget=None, risk_tolerance=None):
    """
    Run all validation rules and return an aggregate pass/fail with details.

    Parameters:
        scenarios: list of scenario dicts from model_scenarios()
        budget: total available budget for survivability check
        risk_tolerance: maximum acceptable loss for risk check

    Returns aggregate result with individual rule outcomes.
    """
    results = []
    all_passed = True

    if budget is not None:
        surv = validate_scenario_survivability(scenarios, budget)
        results.append(surv)
        if not surv["passed"]:
            all_passed = False

    prof = validate_expected_profitability(scenarios)
    results.append(prof)
    if not prof["passed"]:
        all_passed = False

    if risk_tolerance is not None:
        risk = validate_risk_tolerance(scenarios, risk_tolerance)
        results.append(risk)
        if not risk["passed"]:
            all_passed = False

    failed = [r for r in results if not r["passed"]]
    return {
        "all_passed": all_passed,
        "rules_checked": len(results),
        "rules_failed": len(failed),
        "results": results,
        "summary": (
            "All scenario rules passed"
            if all_passed
            else f"{len(failed)} rule(s) failed: {', '.join(r['rule'] for r in failed)}"
        ),
    }
