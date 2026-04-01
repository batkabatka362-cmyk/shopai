"""ROI projection domain knowledge — expert heuristics for investment decisions.

Hard-won wisdom from e-commerce operators about what ROI projections miss,
how reality diverges from spreadsheets, and the mental models that separate
profitable stores from money pits.
"""
from __future__ import annotations

from typing import Any


# Core ROI wisdom — lessons from real e-commerce P&Ls
ROI_KNOWLEDGE = [
    {
        "id": "month_1_always_negative",
        "title": "Month 1 is always negative (launch costs)",
        "insight": (
            "Every product launch loses money in month 1. You've paid for inventory, "
            "photography, ads at inefficient CPCs, and your store has zero reviews. "
            "This is normal and expected. If your projections show month-1 profit, "
            "they're wrong — you forgot something."
        ),
        "category": "expectations",
        "severity": "critical",
    },
    {
        "id": "velocity_compounds",
        "title": "ROI compounds: month 3 = 2x month 1 velocity typically",
        "insight": (
            "New store sales follow an S-curve, not a straight line. Month 1 is "
            "painful (0.4x expected), month 2 improves (0.65x), month 3 hits near-"
            "target (0.85x). By month 6 you're above baseline. This is because: "
            "reviews accumulate, SEO indexing matures, ad pixel learns your buyers, "
            "and repeat customers appear."
        ),
        "category": "growth",
        "severity": "critical",
    },
    {
        "id": "opportunity_cost",
        "title": "Compare to opportunity cost — your time has value",
        "insight": (
            "A product returning 30% ROI sounds good until you realize you spent "
            "15 hours/month managing it. At $30/hour implicit wage, that's $5,400/year "
            "in time cost. If your investment is $3,000 and you made $900 profit, you "
            "effectively earned $-4,500 when accounting for time. Always compare: "
            "'Would I be better off putting this money in an index fund and spending "
            "those 15 hours freelancing?'"
        ),
        "category": "decision_making",
        "severity": "critical",
    },
    {
        "id": "roi_not_linear",
        "title": "ROI is not linear — it follows an S-curve",
        "insight": (
            "Don't project month-1 results forward. Months 1-2 are the 'trough of "
            "sorrow' — low sales, high costs, zero organic traffic. Months 3-6 are "
            "the ramp. Months 6-12 are the plateau (unless you actively expand). "
            "Linear projections either overestimate (using month 6 data) or "
            "underestimate (using month 1 data)."
        ),
        "category": "growth",
        "severity": "important",
    },
    {
        "id": "seasonality_matters",
        "title": "Q4 is not normal — don't use it as your baseline",
        "insight": (
            "November-December sales are 30-40% above average. If you launch in Q4 "
            "and use those numbers for projections, January will feel like a crisis. "
            "Conversely, if you launch in January (worst month, -20%), your year-end "
            "will be better than projected. Always seasonality-adjust."
        ),
        "category": "timing",
        "severity": "important",
    },
    {
        "id": "reinvestment_trap",
        "title": "Paper profit is not real profit until cash is in your account",
        "insight": (
            "Many sellers show $5,000/month 'profit' but have $0 in the bank because "
            "they keep reinvesting in inventory. This is fine if intentional (growth "
            "phase) but dangerous if you're mistaking inventory-on-hand for profit. "
            "Track cash extracted from the business, not just spreadsheet margins."
        ),
        "category": "finance",
        "severity": "important",
    },
    {
        "id": "multiple_products_diversify",
        "title": "One product is a gamble, three products is a business",
        "insight": (
            "Single-product stores have binary outcomes: the product either works or "
            "it doesn't. Three products with 50% individual success rates give you "
            "an 87.5% chance of at least one winner. Winners subsidize losers, and "
            "you learn what works. Aim for 3-5 products by month 6."
        ),
        "category": "strategy",
        "severity": "important",
    },
    {
        "id": "ad_efficiency_improves",
        "title": "Ads get cheaper over time (if you optimize)",
        "insight": (
            "Month-1 Facebook/Google ROAS is typically 1.5x (barely break even). "
            "By month 3-4, a well-managed account reaches 2.5-3.5x ROAS as the "
            "pixel learns and you kill underperforming ads. This means your ad "
            "contribution to ROI improves each month. But only if you actively "
            "manage — set-and-forget ads degrade over time."
        ),
        "category": "advertising",
        "severity": "important",
    },
    {
        "id": "ltv_unlocks_roi",
        "title": "Repeat customers are where real ROI lives",
        "insight": (
            "First-purchase ROI is often negative after acquisition costs. Profit "
            "comes from repeat purchases where you pay zero acquisition cost. "
            "Products with high repeat rates (consumables, pet food, supplements) "
            "have dramatically better 12-month ROI than one-time purchases. "
            "A customer who buys 4x/year at $50 is worth 4x their first order."
        ),
        "category": "growth",
        "severity": "important",
    },
    {
        "id": "exit_criteria",
        "title": "Set kill criteria BEFORE you launch — remove emotion",
        "insight": (
            "Before spending a dollar, write down: 'I will stop if X happens by month Y.' "
            "Example: 'If monthly profit is negative at month 3, I liquidate.' "
            "Without pre-set criteria, sunk cost fallacy will keep you investing in "
            "a loser. The hardest but most valuable skill in e-commerce is knowing "
            "when to cut losses."
        ),
        "category": "decision_making",
        "severity": "critical",
    },
]


# Organized by category for quick lookup
_INSIGHTS_BY_CATEGORY: dict[str, list[dict[str, Any]]] = {}
for _item in ROI_KNOWLEDGE:
    _cat = _item["category"]
    if _cat not in _INSIGHTS_BY_CATEGORY:
        _INSIGHTS_BY_CATEGORY[_cat] = []
    _INSIGHTS_BY_CATEGORY[_cat].append(_item)


def get_roi_insight(topic: str | None = None) -> list[dict[str, Any]]:
    """Get ROI insights, optionally filtered by topic.

    Args:
        topic: Filter by category (expectations, growth, decision_making,
               timing, finance, strategy, advertising). None returns all.
    """
    if topic is None:
        return ROI_KNOWLEDGE
    return _INSIGHTS_BY_CATEGORY.get(topic, [])


def get_critical_insights() -> list[dict[str, Any]]:
    """Get only the critical-severity insights — must-reads before investing."""
    return [k for k in ROI_KNOWLEDGE if k["severity"] == "critical"]


def get_insight_summary() -> str:
    """One-paragraph summary of ROI projection wisdom."""
    return (
        "Month 1 is always negative — don't panic. Sales follow an S-curve, reaching "
        "expected velocity around month 3-4. Always compare ROI against opportunity cost "
        "(your time + index fund returns). Set exit criteria before launching: if monthly "
        "profit is negative at month 3 or cumulative ROI is negative at month 6, stop. "
        "Q4 numbers are inflated — don't use them as baseline. Real profit comes from "
        "repeat customers, not first purchases. Paper profit is not cash — track what you "
        "actually extract from the business."
    )
