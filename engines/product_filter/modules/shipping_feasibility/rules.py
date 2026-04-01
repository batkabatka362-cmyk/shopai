"""
rules.py — Shipping constraint definitions and validation functions.

Encodes hard limits that carriers enforce and regulatory requirements
that override business preferences.
"""

from .data import (
    CARRIER_LIMITS,
    DEFAULT_MAX_WEIGHT_KG,
    HAZMAT_CATEGORIES,
    SURCHARGES,
)


# ── Threshold constants ─────────────────────────────────────────────────

MAX_SHIPPING_COST_PCT = 15.0       # above this = infeasible
MARGINAL_SHIPPING_COST_PCT = 10.0  # above this = marginal
OVERSIZED_DIMENSION_CM = 120       # single side triggers surcharge
MAX_COMBINED_CM = 330              # L + 2*(W+H) for most carriers
FRAGILE_EXTRA_PADDING_CM = 5       # added per side for fragile items


# ── Validation helpers ──────────────────────────────────────────────────

def check_weight_limit(weight_kg, carrier="usps"):
    """Return (passes, message) for carrier weight check."""
    limit = CARRIER_LIMITS.get(carrier, {}).get(
        "max_weight_kg", DEFAULT_MAX_WEIGHT_KG
    )
    if weight_kg > limit:
        return False, f"Weight {weight_kg}kg exceeds {carrier} limit of {limit}kg"
    return True, None


def check_size_constraints(dimensions_cm):
    """Validate package dimensions against carrier limits.

    Parameters
    ----------
    dimensions_cm : dict  {length, width, height}

    Returns
    -------
    tuple  (passes: bool, issues: list[str], surcharges: list[str])
    """
    length = dimensions_cm.get("length", 0)
    width = dimensions_cm.get("width", 0)
    height = dimensions_cm.get("height", 0)
    issues = []
    surcharge_keys = []

    if max(length, width, height) > OVERSIZED_DIMENSION_CM:
        surcharge_keys.append("oversized")
        issues.append(
            f"Longest side {max(length, width, height)}cm > {OVERSIZED_DIMENSION_CM}cm"
        )

    combined = length + 2 * (width + height)
    if combined > MAX_COMBINED_CM:
        surcharge_keys.append("additional_handling")
        issues.append(f"Combined L+2(W+H) = {combined}cm > {MAX_COMBINED_CM}cm")

    passes = len(issues) == 0
    return passes, issues, surcharge_keys


def check_hazmat_restrictions(hazmat_class, ship_method="ground"):
    """Return (allowed, message) for a hazmat class and shipping method."""
    info = HAZMAT_CATEGORIES.get(hazmat_class, HAZMAT_CATEGORIES["none"])
    is_air = ship_method in ("express", "overnight", "air")

    if is_air and not info["air_allowed"]:
        return False, (
            f"{info['label']} cannot ship via air ({ship_method}). "
            f"Ground only.  UN {info['un_number']}."
        )
    if not info["ground_allowed"]:
        return False, f"{info['label']} cannot ship via any method."
    return True, None


def check_battery_rules(product):
    """Specific check for lithium battery shipping rules.

    Returns
    -------
    dict  {allowed: bool, restriction: str|None, documentation: list[str]}
    """
    hazmat = product.get("hazmat_class", "none")
    if hazmat not in ("lithium_ion", "lithium_metal"):
        return {"allowed": True, "restriction": None, "documentation": []}

    info = HAZMAT_CATEGORIES[hazmat]
    docs = [
        f"UN number: {info['un_number']}",
        "Shipper declaration for dangerous goods required",
        "Outer package must display Class 9 lithium battery mark",
    ]
    if hazmat == "lithium_metal":
        docs.append("Standalone lithium-metal cells banned from air cargo")

    return {
        "allowed": info["ground_allowed"],
        "restriction": "Ground shipping only — air freight prohibited",
        "documentation": docs,
    }


def check_liquid_restrictions(product):
    """Validate liquid shipping requirements.

    Returns
    -------
    dict  {allowed: bool, requirements: list[str]}
    """
    if not product.get("is_liquid"):
        return {"allowed": True, "requirements": []}

    requirements = [
        "Inner container must be leak-proof",
        "Absorbent material required between inner and outer packaging",
        "Outer packaging must pass ISTA 3A drop test",
        "'This Side Up' orientation arrows required",
    ]
    volume_ml = product.get("volume_ml", 0)
    if volume_ml > 1000:
        requirements.append(
            f"Volume {volume_ml}ml exceeds 1L — may require freight class upgrade"
        )

    return {"allowed": True, "requirements": requirements}


def check_fragile_requirements(product):
    """Return packaging requirements for fragile items.

    Returns
    -------
    dict  {is_fragile: bool, requirements: list[str], extra_cost: float}
    """
    if not product.get("is_fragile"):
        return {"is_fragile": False, "requirements": [], "extra_cost": 0.0}

    return {
        "is_fragile": True,
        "requirements": [
            "Double-wall corrugated outer box",
            f"Minimum {FRAGILE_EXTRA_PADDING_CM}cm cushioning on all sides",
            "Inner product wrap (bubble or foam)",
            "'FRAGILE — HANDLE WITH CARE' labels on all sides",
        ],
        "extra_cost": SURCHARGES["fragile_packaging"],
    }


def compute_surcharges(product, dimensions_cm):
    """Sum all applicable surcharges for a product.

    Returns
    -------
    tuple  (total_surcharge: float, breakdown: dict[str, float])
    """
    total = 0.0
    breakdown = {}

    _, _, size_surcharges = check_size_constraints(dimensions_cm)
    for key in size_surcharges:
        cost = SURCHARGES.get(key, 0)
        breakdown[key] = cost
        total += cost

    if product.get("is_fragile"):
        breakdown["fragile_packaging"] = SURCHARGES["fragile_packaging"]
        total += SURCHARGES["fragile_packaging"]

    hazmat = product.get("hazmat_class", "none")
    if hazmat != "none":
        haz_cost = SURCHARGES["hazmat_ground"]
        breakdown["hazmat"] = haz_cost
        total += haz_cost

    if product.get("temperature_sensitive"):
        weight = product.get("weight_kg", 1)
        cold_cost = SURCHARGES["cold_chain_per_kg"] * weight
        breakdown["cold_chain"] = round(cold_cost, 2)
        total += cold_cost

    return round(total, 2), breakdown
