"""
Scenario Modeler — Domain knowledge and planning principles.
Expert heuristics for scenario-based decision making and risk management.
"""

SCENARIO_PLANNING_PRINCIPLES = [
    {
        "id": "plan_for_pessimistic",
        "title": "Always plan for the pessimistic scenario",
        "description": (
            "Build your plan assuming the pessimistic case. If you survive the "
            "worst case, you thrive in expected. Optimism bias kills ventures."
        ),
        "application": "Set cash reserves for 6 months at pessimistic. Size fixed costs for 50% volume.",
        "severity": "critical",
        "category": "risk_management",
        "priority": 1,
    },
    {
        "id": "bankruptcy_check",
        "title": "If pessimistic equals bankruptcy, don't do it",
        "description": (
            "No opportunity is worth risking the entire business. If downside "
            "leads to insolvency, the risk-reward ratio is fundamentally broken."
        ),
        "application": "If pessimistic loss exceeds reserves plus credit, it's a no-go. Cap downside first.",
        "severity": "critical",
        "category": "risk_management",
        "priority": 2,
    },
    {
        "id": "key_driver_analysis",
        "title": "Change one variable at a time to find what matters most",
        "description": (
            "Isolate each variable's impact on profit. Hold others constant, vary "
            "one by its range. The largest profit swing reveals your key driver."
        ),
        "application": "Run sensitivity on price, volume, COGS, ad spend independently. Control top 2-3.",
        "severity": "high",
        "category": "analysis",
        "priority": 3,
    },
    {
        "id": "monte_carlo_thinking",
        "title": "Monte Carlo thinking: run 100 scenarios, not just 3",
        "description": (
            "Three scenarios oversimplify reality. Outcomes follow distributions. "
            "Many randomized scenarios reveal the true shape and tail risks."
        ),
        "application": "Generate 100+ scenarios with randomized inputs. Plot distribution for confidence intervals.",
        "severity": "high",
        "category": "analysis",
        "priority": 4,
    },
    {
        "id": "correlation_awareness",
        "title": "Variables are correlated, not independent",
        "description": (
            "In a downturn, volume drops AND prices fall AND costs may rise. "
            "Single-variable scenarios understate real risk. Correlated moves "
            "amplify both gains and losses."
        ),
        "application": (
            "When building pessimistic scenarios, apply correlation factors: if "
            "volume drops 30%, also model a 10-15% price decrease and potential "
            "cost increases from lost economies of scale."
        ),
        "severity": "high",
        "category": "risk_management",
        "priority": 5,
    },
    {
        "id": "margin_of_safety",
        "title": "Require a margin of safety on expected returns",
        "description": (
            "Even the expected scenario contains estimation error. Require that "
            "expected return exceeds your hurdle rate by at least 20% to account "
            "for unknowns and model imprecision."
        ),
        "application": (
            "If your required return is 15%, only proceed if expected scenario "
            "shows at least 18%. This buffer absorbs forecast errors."
        ),
        "severity": "medium",
        "category": "decision_making",
        "priority": 6,
    },
    {
        "id": "reversibility_preference",
        "title": "Prefer reversible decisions when scenarios are uncertain",
        "description": (
            "When the spread between pessimistic and optimistic is wide, favor "
            "decisions that can be unwound. Lease vs buy, contract vs hire, "
            "pilot vs full launch."
        ),
        "application": (
            "If scenario spread exceeds 3x expected profit, structure as a "
            "staged commitment with exit points between stages."
        ),
        "severity": "medium",
        "category": "decision_making",
        "priority": 7,
    },
    {
        "id": "time_horizon_matters",
        "title": "Short-term pessimism, long-term expected value",
        "description": (
            "Plan cash flow for the pessimistic case in months 1-12. Over longer "
            "horizons, outcomes regress toward expected value as variance averages out."
        ),
        "application": (
            "Use pessimistic projections for months 1-6 and expected projections "
            "for months 7-24. Protects survival while allowing realistic planning."
        ),
        "severity": "medium",
        "category": "planning",
        "priority": 8,
    },
]


def get_principle(principle_id):
    """Look up a single principle by its ID. Returns None if not found."""
    for p in SCENARIO_PLANNING_PRINCIPLES:
        if p["id"] == principle_id:
            return p
    return None


def get_all_principles():
    """Return all principles sorted by priority (most important first)."""
    return sorted(SCENARIO_PLANNING_PRINCIPLES, key=lambda p: p["priority"])


def get_principles_for_context(context):
    """Return principles matching a context keyword (category, ID, or text search)."""
    context_lower = context.lower()
    matches = [
        p for p in SCENARIO_PLANNING_PRINCIPLES
        if (p["category"] == context_lower
            or context_lower in p["id"]
            or context_lower in p["title"].lower()
            or context_lower in p["description"].lower())
    ]
    return sorted(matches, key=lambda p: p["priority"])


def get_critical_principles():
    """Return only principles with 'critical' severity."""
    return [p for p in SCENARIO_PLANNING_PRINCIPLES if p["severity"] == "critical"]


def format_principle_summary(principle):
    """Format a principle as a concise one-line summary."""
    return f"[{principle['severity'].upper()}] {principle['title']} (priority {principle['priority']})"
