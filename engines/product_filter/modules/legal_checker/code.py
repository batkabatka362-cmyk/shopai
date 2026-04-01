"""
code.py — Main legal compliance checking entry point.

Accepts an input payload containing products, evaluates each against
FDA, CPSC, FCC, CPSIA, labeling, and import rules, and returns an
engine-contract response with per-product compliance verdicts.
"""

from .rules import REGULATORY_REQUIREMENTS, LABELING_RULES, get_rules_for_category
from .data import CERTIFICATION_COSTS, PROCESSING_TIMES
from .logic import assess_compliance_cost, estimate_certification_timeline
from .knowledge import diagnose_compliance_issues


def _check_single_product(product):
    """Evaluate one product's legal compliance.

    Returns a dict with status, violations, cost_estimate, and timeline.
    """
    category = (product.get("category") or "general").lower()
    rules = get_rules_for_category(category)
    reqs = rules["regulatory"]
    required_labels = rules["labeling"]

    violations = []
    held_certs = set(product.get("certifications_held") or [])
    product_labels = set(product.get("labels") or [])

    # --- Check mandatory certifications ---
    for cert in reqs.get("mandatory", []):
        if cert not in held_certs:
            violations.append({
                "certification": cert,
                "severity": "critical",
                "description": f"Missing mandatory certification: {cert}",
                "agency": reqs["agencies"][0] if reqs["agencies"] else "unknown",
            })

    # --- Check labeling requirements ---
    missing_labels = [lbl for lbl in required_labels if lbl not in product_labels]
    for lbl in missing_labels:
        violations.append({
            "certification": lbl,
            "severity": "major",
            "description": f"Missing required label element: {lbl}",
            "agency": reqs["agencies"][0] if reqs["agencies"] else "unknown",
        })

    # --- Check import restrictions ---
    if reqs.get("import_restricted") and product.get("is_imported", False):
        has_import_docs = product.get("has_import_documentation", False)
        if not has_import_docs:
            violations.append({
                "certification": "import_documentation",
                "severity": "critical",
                "description": f"Imported {category} product lacks required import documentation",
                "agency": "CBP",
            })

    # --- Check banned ingredients ---
    if reqs.get("banned_ingredients_list"):
        flagged = product.get("flagged_ingredients") or []
        for ingredient in flagged:
            violations.append({
                "certification": "ingredient_review",
                "severity": "critical",
                "description": f"Potentially banned/restricted ingredient: {ingredient}",
                "agency": reqs["agencies"][0] if reqs["agencies"] else "FDA",
            })

    # --- Check children's product age-specific rules (CPSIA) ---
    target_age = product.get("target_age_max")
    if target_age is not None and target_age <= 12:
        if "cpsia_testing" not in held_certs:
            already_flagged = any(v["certification"] == "cpsia_testing" for v in violations)
            if not already_flagged:
                violations.append({
                    "certification": "cpsia_testing",
                    "severity": "critical",
                    "description": "Product targets children under 12; CPSIA lead/phthalate testing required",
                    "agency": "CPSC",
                })

    # --- Determine overall status ---
    critical_count = sum(1 for v in violations if v["severity"] == "critical")
    major_count = sum(1 for v in violations if v["severity"] == "major")

    if critical_count > 0:
        status = "non_compliant"
    elif major_count > 0:
        status = "needs_certification"
    else:
        status = "compliant"

    # --- Cost and timeline ---
    cost_estimate = assess_compliance_cost(product)
    timeline = estimate_certification_timeline(category)

    return {
        "product": product,
        "status": status,
        "violations": violations,
        "violation_count": len(violations),
        "critical_count": critical_count,
        "cost_estimate": cost_estimate,
        "timeline": timeline,
        "category": category,
    }


def check_legal_compliance(input_payload):
    """Check products for legal/regulatory compliance.

    Parameters
    ----------
    input_payload : dict
        - products : list[dict]  — required, each with at least 'category'
        - strict   : bool        — if True, treat 'needs_certification' as non-compliant

    Returns
    -------
    dict  Engine contract: {status, data, meta, error}
    """
    try:
        products = input_payload.get("products")
        if not products or not isinstance(products, list):
            return {
                "status": "error",
                "data": None,
                "meta": {},
                "error": "input_payload.products must be a non-empty list",
            }

        strict = input_payload.get("strict", False)
        results = []
        compliant = []
        needs_cert = []
        non_compliant = []

        for product in products:
            result = _check_single_product(product)
            results.append(result)

            if result["status"] == "compliant":
                compliant.append(result)
            elif result["status"] == "needs_certification":
                if strict:
                    non_compliant.append(result)
                else:
                    needs_cert.append(result)
            else:
                non_compliant.append(result)

        total = len(products)
        diagnostics = diagnose_compliance_issues(results)

        total_cost_low = sum(r["cost_estimate"]["total_low"] for r in results)
        total_cost_typical = sum(r["cost_estimate"]["total_typical"] for r in results)

        return {
            "status": "success",
            "data": {
                "compliant": compliant,
                "needs_certification": needs_cert,
                "non_compliant": non_compliant,
            },
            "meta": {
                "total_input": total,
                "compliant_count": len(compliant),
                "needs_certification_count": len(needs_cert),
                "non_compliant_count": len(non_compliant),
                "compliance_rate": round(len(compliant) / total, 4) if total else 0.0,
                "estimated_total_cost_low": total_cost_low,
                "estimated_total_cost_typical": total_cost_typical,
                "diagnostics": diagnostics,
            },
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "error",
            "data": None,
            "meta": {},
            "error": str(exc),
        }
