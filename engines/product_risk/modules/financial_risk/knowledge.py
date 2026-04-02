"""Domain knowledge for financial risk management in e-commerce.

Hard-won lessons about capital management, cash flow, and financial
planning for product-based businesses. Each insight includes context
on when it matters most and what to do about it.
"""

from __future__ import annotations

from typing import Any

FINANCIAL_KNOWLEDGE: list[dict[str, Any]] = [
    {
        "id": "never_bet_the_farm",
        "insight": "Never invest more than you can afford to lose on one product",
        "detail": (
            "The #1 reason e-commerce businesses fail is over-concentration. "
            "A seller puts $30K into one product, it flops, and the business "
            "is done. Cap any single product at 30-40% of available capital. "
            "If you have $20K, your first order should be $5K-8K maximum. "
            "Test small, validate demand, THEN scale. The product that 'can't "
            "fail' is the one that bankrupts you."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "cash_flow_kills",
        "insight": "Cash flow kills more businesses than profitability",
        "detail": (
            "A product can be profitable on paper but kill your business if "
            "cash flow timing is wrong. You pay your supplier $10K on day 1. "
            "Inventory arrives day 30. First sale day 35. Amazon pays you day "
            "49. You are cash-negative for 49 days minimum. If your next order "
            "is due before Amazon pays, you need working capital. Most sellers "
            "underestimate this gap by 2-3x."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "budget_worst_case",
        "insight": "Budget for the worst case, hope for the best",
        "detail": (
            "Your financial plan should survive your worst realistic scenario: "
            "50% of projected sales, 2x expected ad costs, 15% return rate, "
            "and a 30-day shipping delay. If the business still has 3 months "
            "of runway under those conditions, you have a viable plan. If not, "
            "reduce your initial order or increase your reserves."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "moq_trap",
        "insight": "High MOQs are a trap — negotiate or walk away",
        "detail": (
            "Suppliers often quote MOQs of 1000-5000 units to maximize their "
            "production efficiency. For a new product, ordering 1000 units at "
            "$5 = $5000 in unvalidated inventory. Counter with 200-500 units "
            "at a 10-15% price premium. The extra $0.50-1.00/unit is cheap "
            "insurance against a $5K loss. Any supplier who refuses to do a "
            "trial order is not a partner — they are a liability."
        ),
        "applies_when": "initial_order == True",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "margin_erosion_reality",
        "insight": "Plan for 10-20% margin erosion in year one from competition",
        "detail": (
            "Your launch margin of 40% will not last. Competitors will enter, "
            "prices will drop, ad costs will rise. Plan for 30% margin by month "
            "6 and 25% by month 12. If your business model does not work at 25% "
            "margin, it does not work — you are just on borrowed time. Build "
            "defensibility through branding, patents, or customer relationships."
        ),
        "applies_when": "competition_level == high",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "three_month_reserve",
        "insight": "Always maintain 3 months of operating costs in reserve",
        "detail": (
            "Three months of fixed costs (software, storage, insurance, minimum "
            "ad spend) should sit untouched in your account. This is not investment "
            "capital — it is survival capital. A supplier delay, a listing "
            "suspension, or a seasonal slump will happen. When it does, your "
            "reserve is the difference between a temporary setback and closing "
            "the business."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "ad_spend_sunk_cost",
        "insight": "Ad spend is a sunk cost — cut losses at $500 with no sales",
        "detail": (
            "If you have spent $500 on ads with zero or near-zero conversions, "
            "the product or listing has a fundamental problem. More ad spend "
            "will not fix it. Stop, diagnose (price? images? reviews? demand?), "
            "fix the root cause, then resume. The average seller wastes $1000-2000 "
            "trying to 'make ads work' before accepting the product needs changes."
        ),
        "applies_when": "ad_spend > 500 and conversions < 5",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "currency_hedging",
        "insight": "CNY appreciation of 5% wipes out a 35% margin product's profit",
        "detail": (
            "If COGS is 35% of revenue and you import in CNY, a 5% CNY "
            "appreciation increases your COGS by 5% of 35% = 1.75% of revenue. "
            "On thin margins, that is half your profit. For orders over $10K, "
            "lock exchange rates with forward contracts or maintain a USD "
            "reserve account with your supplier. Pay in USD when possible — "
            "the 1-2% spread is worth the stability."
        ),
        "applies_when": "is_imported and cogs_percent > 0.30",
        "impact": "medium",
        "priority": 3,
    },
    {
        "id": "refund_cash_flow_lag",
        "insight": "Refunds hit cash flow 30-60 days after the sale — budget for the lag",
        "detail": (
            "You collect revenue on day 1, spend it on inventory on day 15, "
            "then process a refund on day 45. That refund comes out of your "
            "current balance, not from some imaginary returns reserve. At a 10% "
            "return rate, this means 10% of last month's revenue disappears from "
            "this month's cash. Budget for it or watch your account balance "
            "mysteriously shrink every month."
        ),
        "applies_when": "refund_rate > 0.05",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "scaling_capital_math",
        "insight": "Scaling from $5K to $20K/month revenue requires $15K-25K additional capital",
        "detail": (
            "Scaling is not free. Doubling sales means doubling inventory, "
            "doubling ad spend, and increasing working capital. A product doing "
            "$5K/month that wants to hit $20K/month needs: larger inventory order "
            "($8K-12K), increased ad budget ($2K-4K/month), and buffer for slower "
            "inventory turns at higher volume ($3K-5K). Sellers who try to scale "
            "on revenue alone run out of cash at the worst possible time."
        ),
        "applies_when": "scaling == True",
        "impact": "high",
        "priority": 2,
    },
]


def get_financial_insight(insight_id: str) -> dict[str, Any] | None:
    """Retrieve a specific financial knowledge entry by ID."""
    for entry in FINANCIAL_KNOWLEDGE:
        if entry["id"] == insight_id:
            return entry
    return None


def get_relevant_financial_insights(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Return financial insights relevant to a given product context.

    Args:
        context: dict with keys like competition_level, is_imported,
                 cogs_percent, refund_rate, ad_spend, scaling, etc.

    Returns:
        List of matching knowledge entries sorted by priority (1 = highest).
    """
    relevant: list[dict[str, Any]] = []

    competition = context.get("competition_level", "")
    is_imported = context.get("is_imported", False)
    cogs_pct = context.get("cogs_percent", 0)
    refund_rate = context.get("refund_rate", 0)
    ad_spend = context.get("ad_spend", 0)
    conversions = context.get("conversions", 999)
    scaling = context.get("scaling", False)
    initial_order = context.get("initial_order", False)

    for entry in FINANCIAL_KNOWLEDGE:
        condition = entry["applies_when"]
        match = False

        if condition == "always":
            match = True
        elif "competition_level == high" in condition and competition == "high":
            match = True
        elif "is_imported" in condition and is_imported and cogs_pct > 0.30:
            match = True
        elif "refund_rate > 0.05" in condition and refund_rate > 0.05:
            match = True
        elif "ad_spend > 500" in condition and ad_spend > 500 and conversions < 5:
            match = True
        elif "scaling == True" in condition and scaling:
            match = True
        elif "initial_order == True" in condition and initial_order:
            match = True

        if match:
            relevant.append(entry)

    relevant.sort(key=lambda x: x["priority"])
    return relevant
