"""Supplier scorer domain knowledge — expert heuristics for supplier evaluation.

What experienced sourcing professionals know:
  - "Always order samples before committing to bulk — no exceptions"
  - "The cheapest quote is rarely the best deal; hidden costs destroy margins"
  - "A supplier who communicates poorly before the sale will be worse after"
  - "Trade Assurance is non-negotiable for first orders from new suppliers"
"""
from __future__ import annotations

from typing import Any


NEGOTIATION_TIPS: list[str] = [
    "Never accept the first quoted price — suppliers expect 15-30% negotiation room",
    "Ask for pricing at 3 quantity tiers (sample, small batch, bulk) to understand their cost curve",
    "Request an itemized cost breakdown: materials, labor, packaging, shipping — this reveals padding",
    "Mention competing quotes to create price pressure, but never fabricate — suppliers talk to each other",
    "Negotiate payment terms before price — 30/70 split (30% deposit, 70% before shipping) is standard",
    "Offer a long-term volume commitment in exchange for lower unit prices — suppliers value predictability",
    "Ask about off-season discounts — manufacturing capacity is cheaper during slow periods",
    "Request free samples for the first order; pay shipping. Paid samples signal you are serious.",
    "Do not negotiate via email alone — a video call builds rapport and speeds up the process",
    "If a supplier will not negotiate at all, they are either at true cost or not interested — move on",
    "Always get agreements in writing via the platform — verbal promises have no enforcement",
    "Bundle packaging customization into the unit price rather than paying separately",
]

SAMPLE_ORDERING_PROCESS: list[dict[str, str]] = [
    {"step": "1", "action": "Request 2-3 samples from your top supplier candidates",
     "detail": "Order from multiple suppliers to compare quality side-by-side"},
    {"step": "2", "action": "Specify exact requirements in writing",
     "detail": "Include material, color, dimensions, weight, packaging — leave nothing to assumption"},
    {"step": "3", "action": "Pay for samples and shipping via platform",
     "detail": "Expect $30-150 per sample depending on product. This investment prevents costly bulk mistakes."},
    {"step": "4", "action": "Inspect samples thoroughly on arrival",
     "detail": "Check against your spec sheet. Photograph defects. Test functionality and durability."},
    {"step": "5", "action": "Send feedback and request revision if needed",
     "detail": "A good supplier will iterate. If they resist changes, they will not meet bulk quality either."},
    {"step": "6", "action": "Order a small test batch (10-50 units) before full MOQ",
     "detail": "Validates consistency. One good sample does not guarantee 500 good units."},
]

QUALITY_INSPECTION_CHECKLIST: list[dict[str, Any]] = [
    {"item": "Material quality", "check": "Matches spec sheet and sample",
     "red_flag": "Thinner, lighter, or different texture than sample"},
    {"item": "Dimensions and weight", "check": "Within 2% tolerance of specifications",
     "red_flag": "Significant deviation indicates different materials or molds"},
    {"item": "Color consistency", "check": "Uniform across all units in batch",
     "red_flag": "Color variance between units suggests poor quality control"},
    {"item": "Packaging integrity", "check": "No damage, correct labeling, barcodes scan",
     "red_flag": "Crushed boxes or missing labels mean careless handling"},
    {"item": "Functionality test", "check": "Product works as intended across 10% sample",
     "red_flag": "Any failure in random sample suggests batch-wide issues"},
    {"item": "Defect rate", "check": "Less than 2% AQL (Acceptable Quality Level)",
     "red_flag": "Above 5% defect rate means reject the entire shipment"},
    {"item": "Safety compliance", "check": "CE/FCC/FDA marks where required",
     "red_flag": "Missing compliance marks can result in customs seizure"},
    {"item": "Smell and finish", "check": "No chemical odor, smooth edges, no sharp burrs",
     "red_flag": "Strong chemical smell indicates unsafe materials or poor finishing"},
]

COMMON_SCAMS: list[dict[str, Any]] = [
    {"scam": "Bait and switch", "how_it_works": "Send a great sample, ship inferior bulk product",
     "prevention": "Hire a third-party inspector (SGS, Bureau Veritas) for pre-shipment inspection"},
    {"scam": "Ghost supplier", "how_it_works": "Take deposit payment then disappear completely",
     "prevention": "Only pay through Trade Assurance or verified escrow. Never wire transfer directly."},
    {"scam": "Trading company posing as factory",
     "how_it_works": "Middleman marks up 20-40% while claiming to be the manufacturer",
     "prevention": "Request factory audit certificate. Ask for live video tour of production floor."},
    {"scam": "Fake certifications", "how_it_works": "Forge CE/ISO/FDA documents to win the order",
     "prevention": "Verify certificate numbers directly with the issuing body"},
    {"scam": "Quantity shortfall", "how_it_works": "Ship 450 units when you ordered 500, hoping you will not count",
     "prevention": "Require packing list with unit count. Weigh the shipment against expected weight."},
    {"scam": "IP theft", "how_it_works": "Copy your custom design and sell to your competitors",
     "prevention": "File design patents before sharing. Use NNN agreements (Non-use, Non-disclosure, Non-circumvention)."},
]

COMMUNICATION_TEMPLATES: dict[str, str] = {
    "initial_inquiry": (
        "Hello, I am sourcing [PRODUCT] for my e-commerce business. I need [QUANTITY] units "
        "with [SPECIFICATIONS]. Could you provide: 1) Unit price at 100/500/1000 qty, "
        "2) MOQ and lead time, 3) Sample availability and cost, 4) Payment terms? "
        "I am looking for a long-term supplier relationship."
    ),
    "sample_request": (
        "Thank you for the quote. I would like to order [N] samples to evaluate quality. "
        "Please confirm: 1) Sample cost, 2) Shipping method and cost to [COUNTRY], "
        "3) Production time for samples, 4) Can the sample match these exact specs: [SPECS]?"
    ),
    "negotiation": (
        "I appreciate the pricing. I have received competitive quotes from other suppliers "
        "in the range of [RANGE]. For an initial order of [QTY] with potential to scale to "
        "[LARGER_QTY] monthly, could you improve on the unit price? I am also open to "
        "discussing payment terms."
    ),
    "quality_issue": (
        "I received the shipment and found the following quality issues: [ISSUES]. "
        "This does not match the approved sample. Please advise on: 1) Root cause, "
        "2) Replacement or refund options, 3) Corrective action for future orders. "
        "I have attached photos for reference."
    ),
}


def get_negotiation_tips() -> list[str]:
    """Return expert negotiation tips for supplier dealings."""
    return NEGOTIATION_TIPS


def get_sample_process() -> list[dict[str, str]]:
    """Return the step-by-step sample ordering process."""
    return SAMPLE_ORDERING_PROCESS


def get_inspection_checklist() -> list[dict[str, Any]]:
    """Return quality inspection checklist for incoming shipments."""
    return QUALITY_INSPECTION_CHECKLIST


def get_scam_guide() -> list[dict[str, Any]]:
    """Return common supplier scams and prevention strategies."""
    return COMMON_SCAMS


def get_communication_template(template_key: str) -> str:
    """Return a communication template by key."""
    return COMMUNICATION_TEMPLATES.get(template_key, "Template not found — draft a custom message.")
