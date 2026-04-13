"""
knowledge.py — Compliance heuristics, expert tips, and diagnostic helpers.

Encodes practitioner knowledge about regulatory compliance so the engine
can give actionable guidance beyond raw pass/fail verdicts.
"""

# ---------------------------------------------------------------------------
# Practitioner heuristics
# ---------------------------------------------------------------------------
COMPLIANCE_HEURISTICS = [
    {
        "id": "supplements_cost",
        "category": "supplements",
        "insight": "Supplements need $3K-10K for third-party testing before you can legally sell.",
        "action": "Budget at least $5K and 3 months lead time for a new supplement SKU.",
    },
    {
        "id": "children_cpc",
        "category": "children_products",
        "insight": "Children's products need a CPC (Children's Product Certificate) — no exceptions.",
        "action": "Use a CPSC-accepted lab for CPSIA testing; CPC is free once tests pass.",
    },
    {
        "id": "electronics_fcc",
        "category": "electronics",
        "insight": "Electronics need FCC testing costing $5K-15K and 4-12 weeks.",
        "action": "Request FCC grant from your manufacturer; importing without it is illegal.",
    },
    {
        "id": "cosmetics_mocra",
        "category": "cosmetics",
        "insight": "Since MoCRA (2023), cosmetics facilities must register with the FDA annually.",
        "action": "Verify your supplier's MoCRA registration before placing orders.",
    },
    {
        "id": "food_import",
        "category": "food",
        "insight": "Imported food requires a FSVP (Foreign Supplier Verification Program) plan.",
        "action": "Hire a FSVP agent if importing; fines start at $10K per violation.",
    },
    {
        "id": "lead_phthalate_shortcut",
        "category": "children_products",
        "insight": "Untreated wood and uncoated steel are exempt from lead surface-coating tests.",
        "action": "Use material exemptions to reduce testing costs by $500-1500.",
    },
    {
        "id": "fcc_sdoc",
        "category": "electronics",
        "insight": "Unintentional radiators (cables, monitors) can use SDoC instead of full FCC ID.",
        "action": "SDoC costs ~$3K vs $10K+ for full certification. Check if your product qualifies.",
    },
    {
        "id": "label_first",
        "category": "general",
        "insight": "80% of FDA warning letters are for labeling violations, not product defects.",
        "action": "Get your label reviewed by a regulatory consultant before manufacturing.",
    },
    {
        "id": "batch_testing",
        "category": "supplements",
        "insight": "Batch testing multiple SKUs from the same ingredient base saves 30-50% on lab fees.",
        "action": "Group product launches by ingredient overlap to reduce testing costs.",
    },
    {
        "id": "import_bond",
        "category": "general",
        "insight": "Customs can seize non-compliant products at the border with no refund.",
        "action": "Always have compliance documentation ready before importing goods.",
    },
]


def diagnose_compliance_issues(results):
    """Analyze compliance check results and return actionable diagnostics.

    Parameters
    ----------
    results : list[dict]
        Each dict has 'status', 'violations', and 'category'.

    Returns
    -------
    list[str]  Human-readable diagnostic messages.
    """
    diagnostics = []
    non_compliant_count = sum(1 for r in results if r.get("status") == "non_compliant")
    needs_cert_count = sum(1 for r in results if r.get("status") == "needs_certification")
    total = len(results)

    if total == 0:
        return ["No products to diagnose."]

    non_compliant_rate = non_compliant_count / total
    if non_compliant_rate > 0.5:
        diagnostics.append(
            f"Over half ({non_compliant_count}/{total}) of products are non-compliant. "
            "Consider switching to lower-regulation categories."
        )

    if needs_cert_count > 5:
        diagnostics.append(
            f"{needs_cert_count} products need certification. "
            "Batch similar products to reduce per-unit certification cost."
        )

    categories_flagged = set(r.get("category") for r in results if r.get("status") != "compliant")
    for cat in categories_flagged:
        tips = [h for h in COMPLIANCE_HEURISTICS if h["category"] == cat]
        for tip in tips:
            diagnostics.append(f"[{cat}] {tip['insight']}")

    if not diagnostics:
        diagnostics.append("All products appear compliant. Proceed to listing.")

    return diagnostics


def get_compliance_tips(category):
    """Return all heuristic tips relevant to a product category.

    Also includes 'general' tips that apply to every category.
    """
    cat = category.lower() if category else "general"
    tips = [
        h for h in COMPLIANCE_HEURISTICS
        if h["category"] == cat or h["category"] == "general"
    ]
    return tips
