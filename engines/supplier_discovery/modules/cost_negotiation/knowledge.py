"""Negotiation knowledge base — tactics, strategies, and heuristics.

Sourced from experienced sourcing agents, trade consultants, and
e-commerce operators. These are practical guidelines, not rules.
"""
from __future__ import annotations

from typing import Any


def get_negotiation_tactics() -> list[dict[str, str]]:
    """Core negotiation tactics for supplier price discussions."""
    return [
        {
            "tactic": "anchor_low",
            "description": (
                "Open with a price 20-30% below your actual target. Suppliers expect "
                "negotiation and pad their initial quote by 15-40%. Your anchor sets "
                "the midpoint where you will likely settle."
            ),
            "when_to_use": "First price counter-offer in any negotiation",
        },
        {
            "tactic": "bundle_orders",
            "description": (
                "Combine multiple SKUs or product lines into a single order. Suppliers "
                "give better pricing when total order value is higher, even if per-SKU "
                "quantity is modest. A $10k order across 5 SKUs beats 5 separate $2k orders."
            ),
            "when_to_use": "When ordering multiple products from the same supplier",
        },
        {
            "tactic": "time_for_slow_season",
            "description": (
                "Place orders during the supplier's slow season (typically Nov-Feb for "
                "Chinese manufacturers, after CNY). Factories are hungry for orders and "
                "will offer 5-15% better pricing to keep production lines running."
            ),
            "when_to_use": "When order timing is flexible",
        },
        {
            "tactic": "mention_competition",
            "description": (
                "Let the supplier know you are evaluating 3-5 other suppliers. Share "
                "competing quotes if you have them (redact names). This creates urgency "
                "and signals you have alternatives."
            ),
            "when_to_use": "When you have genuine competing quotes",
        },
        {
            "tactic": "ask_for_value_adds",
            "description": (
                "When the supplier cannot move on price, ask for value-adds: free "
                "samples, custom packaging, extended payment terms, free shipping on "
                "samples, or a percentage of defective-unit replacement at no cost. "
                "These cost the supplier less than a price cut but save you money."
            ),
            "when_to_use": "When price negotiation has stalled near your target",
        },
        {
            "tactic": "commit_to_forecast",
            "description": (
                "Share a 6-12 month purchase forecast showing growing volume. Suppliers "
                "will discount current pricing to lock in a long-term customer. Be "
                "honest — overcommitting destroys trust for future orders."
            ),
            "when_to_use": "When you genuinely plan repeat orders",
        },
        {
            "tactic": "request_cost_breakdown",
            "description": (
                "Ask the supplier for a detailed cost breakdown: material, labor, "
                "tooling, packaging, margin. This shifts the conversation from "
                "'what is the price' to 'where can we reduce cost together.'"
            ),
            "when_to_use": "When the supplier's quote seems inflated or opaque",
        },
    ]


def get_payment_term_strategies() -> list[dict[str, str]]:
    """Payment term strategies ranked by buyer favorability."""
    return [
        {
            "term": "net_30_after_delivery",
            "favorability": "excellent",
            "description": (
                "Pay 30 days after goods are delivered and inspected. Best cash flow "
                "position — you can start selling before paying. Typically only "
                "available after 3+ successful orders with a supplier."
            ),
        },
        {
            "term": "trade_assurance_milestone",
            "favorability": "good",
            "description": (
                "30% deposit via Trade Assurance, balance released after inspection "
                "and shipment. Alibaba holds the funds in escrow — if the supplier "
                "fails to deliver, you get a refund."
            ),
        },
        {
            "term": "letter_of_credit",
            "favorability": "good",
            "description": (
                "Bank-backed guarantee. Supplier gets paid only when shipping documents "
                "prove the goods were sent. Costs 1-3% of order value but excellent "
                "protection for orders over $20k."
            ),
        },
        {
            "term": "tt_split_payment",
            "favorability": "moderate",
            "description": (
                "30% T/T deposit, 70% T/T before shipment. Standard but less protection "
                "than escrow. Only use with verified suppliers after sample approval."
            ),
        },
        {
            "term": "full_tt_upfront",
            "favorability": "avoid",
            "description": (
                "100% wire transfer before production. Maximum risk with zero recourse. "
                "Never do this regardless of how trustworthy the supplier appears."
            ),
        },
    ]


def get_walk_away_signals() -> list[dict[str, str]]:
    """Red flags that indicate you should walk away from a supplier deal."""
    return [
        {"signal": "Demands 100% payment upfront with no escrow or protection"},
        {"signal": "Refuses to send samples or charges excessive sample fees"},
        {"signal": "Cannot provide references from other international buyers"},
        {"signal": "Price is more than 40% below market average — likely bait-and-switch"},
        {"signal": "Pressures you to decide immediately or claims a 'special price' expiring today"},
        {"signal": "Will not agree to third-party quality inspection before shipment"},
        {"signal": "Changes price or terms after you have committed to the order"},
        {"signal": "Cannot produce certifications required for your market (CE, FDA, UL, etc.)"},
    ]


def get_seasonal_timing_advice() -> dict[str, Any]:
    """Best and worst times to negotiate with Chinese manufacturers."""
    return {
        "best_months": {
            "months": ["March", "April", "November"],
            "reason": (
                "Post-CNY (March-April) factories reopen and need orders. November "
                "is after the peak production season ends."
            ),
        },
        "worst_months": {
            "months": ["September", "October", "January"],
            "reason": (
                "Sep-Oct is peak production for holiday inventory. January is "
                "pre-CNY wind-down — factories are finishing orders, not taking new ones."
            ),
        },
        "cny_blackout": {
            "period": "2 weeks around Chinese New Year (late Jan / early Feb)",
            "impact": "Factories fully closed. Plan orders to arrive before or well after.",
        },
    }


def get_value_add_requests() -> list[str]:
    """Free value-adds to request when price negotiation stalls."""
    return [
        "Free custom packaging or branded inserts",
        "Extended defect replacement warranty (180 days instead of 90)",
        "Free shipping on first sample order",
        "Reduced MOQ for first order to test the market",
        "Free product photography or lifestyle images",
        "Priority production slot for reorders",
        "Free minor product customization (color, logo placement)",
        "Absorb cost of third-party inspection",
        "Include spare parts or accessories at no extra charge",
        "30-day payment extension on balance (Net 30 instead of before-shipment)",
    ]
