"""
rules.py — Shipping constraint definitions and validation functions.

Encodes hard limits that carriers enforce and regulatory requirements
that override business preferences.
"""

from .data import CARRIER_LIMITS, DEFAULT_MAX_WEIGHT_KG, HAZMAT_CATEGORIES, SURCHARGES

# ── Threshold constants ─────────────────────────────────────────────────

MAX_SHIPPING_COST_PCT = 15.0       # above this = infeasible
MARGINAL_SHIPPING_COST_PCT = 10.0  # above this = marginal
OVERSIZED_DIMENSION_CM = 120       # single side triggers surcharge
MAX_COMBINED_CM = 330              # L + 2*(W+H) for most carriers
FRAGILE_EXTRA_PADDING_CM = 5       # added per side for fragile items


def check_weight_limit(weight_kg, carrier="usps"):
    """Return (passes, message) for carrier weight check."""
    limit = CARRIER_LIMITS.get(carrier, {}).get("max_weight_kg", DEFAULT_MAX_WEIGHT_KG)
    if weight_kg > limit:
        return False, f"Weight {weight_kg}kg exceeds {carrier} limit of {limit}kg"
    return True, None


def check_size_constraints(dimensions_cm):
    """Validate package dimensions against carrier limits.

    Returns (passes, issues, surcharge_keys)
    """
    l, w, h = dimensions_cm.get("length", 0), dimensions_cm.get("width", 0), dimensions_cm.get("height", 0)
    issues, surcharge_keys = [], []

    if max(l, w, h) > OVERSIZED_DIMENSION_CM:
        surcharge_keys.append("oversized")
        issues.append(f"Longest side {max(l, w, h)}cm > {OVERSIZED_DIMENSION_CM}cm")

    combined = l + 2 * (w + h)
    if combined > MAX_COMBINED_CM:
        surcharge_keys.append("additional_handling")
        issues.append(f"Combined L+2(W+H) = {combined}cm > {MAX_COMBINED_CM}cm")

    return len(issues) == 0, issues, surcharge_keys


def check_hazmat_restrictions(hazmat_class, ship_method="ground"):
    """Return (allowed, message) for a hazmat class and shipping method."""
    info = HAZMAT_CATEGORIES.get(hazmat_class, HAZMAT_CATEGORIES["none"])
    is_air = ship_method in ("express", "overnight", "air")
    if is_air and not info["air_allowed"]:
        return False, f"{info['label']} cannot ship via air ({ship_method}). Ground only. UN {info['un_number']}."
    if not info["ground_allowed"]:
        return False, f"{info['label']} cannot ship via any method."
    return True, None


def check_battery_rules(product):
    """Specific check for lithium battery shipping rules."""
    hazmat = product.get("hazmat_class", "none")
    if hazmat not in ("lithium_ion", "lithium_metal"):
        return {"allowed": True, "restriction": None, "documentation": []}

    info = HAZMAT_CATEGORIES[hazmat]
    docs = [f"UN number: {info['un_number']}", "Shipper declaration for dangerous goods required",
            "Outer package must display Class 9 lithium battery mark"]
    if hazmat == "lithium_metal":
        docs.append("Standalone lithium-metal cells banned from air cargo")
    return {"allowed": info["ground_allowed"],
            "restriction": "Ground shipping only — air freight prohibited", "documentation": docs}


def check_liquid_restrictions(product):
    """Validate liquid shipping requirements."""
    if not product.get("is_liquid"):
        return {"allowed": True, "requirements": []}
    reqs = ["Inner container must be leak-proof",
            "Absorbent material required between inner and outer packaging",
            "Outer packaging must pass ISTA 3A drop test",
            "'This Side Up' orientation arrows required"]
    volume_ml = product.get("volume_ml", 0)
    if volume_ml > 1000:
        reqs.append(f"Volume {volume_ml}ml exceeds 1L — may require freight class upgrade")
    return {"allowed": True, "requirements": reqs}


def check_fragile_requirements(product):
    """Return packaging requirements for fragile items."""
    if not product.get("is_fragile"):
        return {"is_fragile": False, "requirements": [], "extra_cost": 0.0}
    return {
        "is_fragile": True,
        "requirements": ["Double-wall corrugated outer box",
                         f"Minimum {FRAGILE_EXTRA_PADDING_CM}cm cushioning on all sides",
                         "Inner product wrap (bubble or foam)",
                         "'FRAGILE — HANDLE WITH CARE' labels on all sides"],
        "extra_cost": SURCHARGES["fragile_packaging"],
    }


def compute_surcharges(product, dimensions_cm):
    """Sum all applicable surcharges. Returns (total, breakdown)."""
    total, breakdown = 0.0, {}

    _, _, size_keys = check_size_constraints(dimensions_cm)
    for key in size_keys:
        cost = SURCHARGES.get(key, 0)
        breakdown[key] = cost
        total += cost

    if product.get("is_fragile"):
        breakdown["fragile_packaging"] = SURCHARGES["fragile_packaging"]
        total += SURCHARGES["fragile_packaging"]

    if product.get("hazmat_class", "none") != "none":
        breakdown["hazmat"] = SURCHARGES["hazmat_ground"]
        total += SURCHARGES["hazmat_ground"]

    if product.get("temperature_sensitive"):
        cold = SURCHARGES["cold_chain_per_kg"] * product.get("weight_kg", 1)
        breakdown["cold_chain"] = round(cold, 2)
        total += cold

    return round(total, 2), breakdown
