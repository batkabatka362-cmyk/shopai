"""Domain knowledge for legal risk management in e-commerce.

Hard-won lessons about regulatory compliance, IP protection, and
liability management. Each insight includes context and actionable advice.
"""

from __future__ import annotations

from typing import Any

LEGAL_KNOWLEDGE: list[dict[str, Any]] = [
    {
        "id": "fda_supplement_timeline",
        "insight": "FDA compliance for supplements = $3K-10K and 3-6 months",
        "detail": (
            "Supplement compliance involves GMP-certified manufacturing, supplement "
            "facts panel creation, adverse event reporting setup, and structure/function "
            "claim review. The $3K minimum covers basic labeling review and testing. "
            "Full GMP audit of your manufacturer can push costs to $10K+. Do NOT skip "
            "this — FDA warning letters are public and will get your Amazon listing "
            "killed overnight."
        ),
        "applies_when": "category == supplements",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "patent_troll_threshold",
        "insight": "Patent trolls target sellers with >$50K/month revenue",
        "detail": (
            "Non-practicing entities (patent trolls) monitor Amazon best-seller "
            "lists and target sellers doing $50K+/month. They send demand letters "
            "for $10K-50K settlements on broad utility patents. Most are nuisance "
            "suits, but fighting them costs $50K-200K. Best defense: product "
            "liability insurance with IP rider, and keeping a low profile until "
            "you have legal reserves."
        ),
        "applies_when": "monthly_revenue > 50000",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "liability_insurance_value",
        "insight": "Product liability insurance = $500-2000/year (worth it)",
        "detail": (
            "A $1M general product liability policy costs $500-2000/year for most "
            "e-commerce products. One lawsuit without insurance can bankrupt a small "
            "business. Amazon requires it for pro sellers above $10K/month. Even if "
            "your product seems harmless, a customer tripping over your product's "
            "packaging can trigger a $50K claim. This is the cheapest peace of mind "
            "you will ever buy."
        ),
        "applies_when": "always",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "cpsc_children_mandatory",
        "insight": "CPSC testing is mandatory for ALL children's products — no exceptions",
        "detail": (
            "If your product is designed or intended primarily for children 12 and "
            "under, it MUST be tested by a CPSC-accepted lab. This includes lead "
            "content, phthalates, small parts, and flammability. A Children's Product "
            "Certificate (CPC) must accompany every shipment. Selling without one "
            "is a federal offense with fines up to $100K per violation. Amazon will "
            "request your CPC and test reports."
        ),
        "applies_when": "target_children == True",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "fcc_electronic_devices",
        "insight": "FCC certification required for any device that emits RF — including Bluetooth and WiFi",
        "detail": (
            "Any electronic device sold in the US that intentionally or unintentionally "
            "emits radio frequency energy needs FCC authorization. This includes "
            "Bluetooth speakers, WiFi devices, LED controllers, and even some USB "
            "chargers. Testing costs $2K-8K at an accredited lab. Importing without "
            "FCC ID risks customs seizure and $100K+ fines."
        ),
        "applies_when": "category == electronics",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "health_claims_ftc",
        "insight": "FTC has fined supplement sellers $5M+ for unsubstantiated health claims",
        "detail": (
            "The FTC requires 'competent and reliable scientific evidence' for any "
            "health claim. 'Cures cancer', 'treats diabetes', 'prevents COVID' will "
            "trigger immediate enforcement. Even softer claims like 'boosts immunity' "
            "are under scrutiny. Stick to structure/function claims: 'supports joint "
            "health' (with disclaimer). When in doubt, hire an FTC advertising attorney "
            "for a $500-1000 review of your claims."
        ),
        "applies_when": "makes_health_claims == True",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "trademark_before_brand",
        "insight": "Register your trademark BEFORE building your brand — $250-2000 saves $50K+ later",
        "detail": (
            "A USPTO trademark search costs $250-500. Registration costs $250-350 "
            "per class. Total investment: under $2000. If you build a brand, print "
            "packaging, launch ads, and THEN discover your name infringes an existing "
            "mark, rebranding costs $20K-50K+ including new packaging, listings, and "
            "lost brand equity. File your trademark application on day one."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
    {
        "id": "amazon_ip_complaints",
        "insight": "Three IP complaints on Amazon = permanent account suspension",
        "detail": (
            "Amazon's IP complaint system is heavily biased toward rights holders. "
            "Three valid IP complaints against your account triggers a review that "
            "often results in permanent suspension. Competitors weaponize this by "
            "filing bogus complaints. Protect yourself: register your brand on "
            "Amazon Brand Registry, file your own trademarks, and keep records of "
            "your design and sourcing process."
        ),
        "applies_when": "platform == amazon",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "country_of_origin_label",
        "insight": "Missing 'Made in X' labels = customs seizure — costs $0.02 per label to fix",
        "detail": (
            "US Customs requires country of origin marking on virtually all imported "
            "products. A missing label can result in shipment seizure, re-marking fees "
            "($2-5/unit at the port), and delays of 2-4 weeks. The fix costs $0.02 "
            "per label at the factory. Ensure your supplier includes proper country "
            "of origin marking on every unit and every retail package."
        ),
        "applies_when": "is_imported == True",
        "impact": "medium",
        "priority": 3,
    },
    {
        "id": "product_testing_records",
        "insight": "Keep product testing records for 5+ years — they are your legal shield",
        "detail": (
            "In a product liability lawsuit, your testing records are your primary "
            "defense. Courts look at whether you exercised 'reasonable care' in "
            "ensuring product safety. Third-party test reports, quality inspection "
            "records, and supplier certifications from an accredited lab can mean "
            "the difference between a dismissed case and a $500K judgment. Store "
            "them securely for at least 5 years after last sale."
        ),
        "applies_when": "always",
        "impact": "high",
        "priority": 2,
    },
]


def get_legal_insight(insight_id: str) -> dict[str, Any] | None:
    """Retrieve a specific legal knowledge entry by ID."""
    for entry in LEGAL_KNOWLEDGE:
        if entry["id"] == insight_id:
            return entry
    return None


def get_relevant_legal_insights(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Return legal insights relevant to a given product context.

    Args:
        context: dict with keys like category, monthly_revenue,
                 target_children, is_imported, makes_health_claims, platform.

    Returns:
        List of matching knowledge entries sorted by priority (1 = highest).
    """
    relevant: list[dict[str, Any]] = []

    category = context.get("category", "")
    monthly_revenue = context.get("monthly_revenue", 0)
    target_children = context.get("target_children", False)
    is_imported = context.get("is_imported", False)
    health_claims = context.get("makes_health_claims", False)
    platform = context.get("platform", "")

    for entry in LEGAL_KNOWLEDGE:
        condition = entry["applies_when"]
        match = False

        if condition == "always":
            match = True
        elif "category == supplements" in condition and category == "supplements":
            match = True
        elif "category == electronics" in condition and category == "electronics":
            match = True
        elif "monthly_revenue > 50000" in condition and monthly_revenue > 50000:
            match = True
        elif "target_children == True" in condition and target_children:
            match = True
        elif "makes_health_claims == True" in condition and health_claims:
            match = True
        elif "is_imported == True" in condition and is_imported:
            match = True
        elif "platform == amazon" in condition and "amazon" in platform:
            match = True

        if match:
            relevant.append(entry)

    relevant.sort(key=lambda x: x["priority"])
    return relevant
