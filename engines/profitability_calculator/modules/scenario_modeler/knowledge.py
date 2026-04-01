"""
Scenario Modeler — Domain knowledge and planning principles.

Encodes expert heuristics for scenario-based decision making,
risk management, and sensitivity analysis. Each principle includes
rationale, application guidance, and severity/priority metadata.
"""

SCENARIO_PLANNING_PRINCIPLES = [
    {
        "id": "plan_for_pessimistic",
        "title": "Always plan for the pessimistic scenario",
        "description": (
            "Build your operating plan assuming the pessimistic case will happen. "
            "If you can survive the worst case, you can thrive in the expected case. "
            "Optimism bias is the number one killer of new ventures."
        ),
        "application": (
            "Set cash reserves to cover pessimistic scenario for at least 6 months. "
            "Size your team and fixed costs so they are sustainable even at 50% volume."
        ),
        "severity": "critical",
        "category": "risk_management",
        "priority": 1,
    },
    {
        "id": "bankruptcy_check",
        "title": "If pessimistic equals bankruptcy, don't do it",
        "description": (
            "No opportunity is worth risking the entire business. If the downside "
            "scenario leads to insolvency or unrecoverable debt, the risk-reward "
            "ratio is fundamentally broken regardless of the upside."
        ),
        "application": (
            "Before any major investment, calculate the pessimistic scenario. If the "
            "resulting loss exceeds your total available reserves plus credit lines, "
            "the venture is a no-go. Restructure the deal to cap downside first."
        ),
        "severity": "critical",
        "category": "risk_management",
        "priority": 2,
    },
    {
        "id": "key_driver_analysis",
        "title": "Change one variable at a time to find what matters most",
        "description": (
            "Key driver analysis isolates the impact of each variable on profitability. "
            "Hold all other inputs constant and vary one by its expected range. The "
            "variable that produces the largest profit swing is your key driver."
        ),
        "application": (
            "Run sensitivity analysis on price, volume, COGS, ad spend, and conversion "
            "rate independently. Rank by absolute profit impact. Focus management "
            "attention and resources on controlling the top 2-3 drivers."
        ),
        "severity": "high",
        "category": "analysis",
        "priority": 3,
    },
    {
        "id": "monte_carlo_thinking",
        "title": "Monte Carlo thinking: run 100 scenarios, not just 3",
        "description": (
            "Three scenarios (pessimistic/expected/optimistic) are a useful mental "
            "model but oversimplify reality. True outcomes follow probability "
            "distributions. Running many randomized scenarios reveals the shape "
            "of the outcome distribution and tail risks."
        ),
        "application": (
            "For high-stakes decisions, generate 100+ scenarios with randomized "
            "inputs drawn from historical variance ranges. Plot the distribution "
            "of outcomes to understand probability of profit vs loss and the "
            "expected value with confidence intervals."
        ),
        "severity": "high",
        "category": "analysis",
        "priority": 4,
    },
    {
        "id": "correlation_awareness",
        "title": "Variables are correlated, not independent",
        "description": (
            "In a downturn, volume drops AND prices fall AND costs may rise. "
            "Scenarios that only adjust one variable understate real risk. "
            "Correlated moves amplify both gains and losses."
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
            "the expected return exceeds your hurdle rate by at least 20% to "
            "account for unknowns and model imprecision."
        ),
        "application": (
            "If your required return is 15%, only proceed if the expected scenario "
            "shows at least 18% return. This buffer absorbs forecast errors without "
            "pushing the project into loss territory."
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
            "pilot vs full launch. Irreversible bets require much higher "
            "confidence in the expected scenario."
        ),
        "application": (
            "Calculate the scenario spread (optimistic profit minus pessimistic). "
            "If the spread exceeds 3x the expected profit, structure the decision "
            "as a staged commitment with exit points between stages."
        ),
        "severity": "medium",
        "category": "decision_making",
        "priority": 7,
    },
    {
        "id": "time_horizon_matters",
        "title": "Short-term pessimism, long-term expected value",
        "description": (
            "Plan cash flow and operations for the pessimistic case in the first "
            "6-12 months. Over longer horizons, outcomes tend to regress toward "
            "the expected value as variance averages out."
        ),
        "application": (
            "Use pessimistic projections for months 1-6 and expected projections "
            "for months 7-24. This protects near-term survival while allowing "
            "realistic long-term planning."
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
    """
    Return principles relevant to a given context string.

    Matches context keywords against principle categories and IDs.
    Useful for surfacing the right guidance at decision time.

    Parameters:
        context: one of 'risk_management', 'analysis', 'decision_making',
                 'planning', or a principle ID.

    Returns list of matching principles sorted by priority.
    """
    matches = []
    context_lower = context.lower()
    for p in SCENARIO_PLANNING_PRINCIPLES:
        if (
            p["category"] == context_lower
            or context_lower in p["id"]
            or context_lower in p["title"].lower()
            or context_lower in p["description"].lower()
        ):
            matches.append(p)
    return sorted(matches, key=lambda p: p["priority"])


def get_critical_principles():
    """Return only principles with 'critical' severity."""
    return [p for p in SCENARIO_PLANNING_PRINCIPLES if p["severity"] == "critical"]


def format_principle_summary(principle):
    """Format a principle as a concise one-line summary for logs or UI."""
    return f"[{principle['severity'].upper()}] {principle['title']} (priority {principle['priority']})"
