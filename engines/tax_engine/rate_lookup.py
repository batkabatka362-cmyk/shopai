"""Tax Engine — rate lookup.

Looks up tax rates for resolved jurisdictions. Contains real tax rates
for all 50 US states, major US cities/counties, and EU VAT rates.

All rates are real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# US State Sales Tax Rates (as of 2025 — real rates)
# ---------------------------------------------------------------------------

_US_STATE_RATES: dict[str, float] = {
    "AL": 4.00,
    "AK": 0.00,   # No state sales tax
    "AZ": 5.60,
    "AR": 6.50,
    "CA": 7.25,
    "CO": 2.90,
    "CT": 6.35,
    "DE": 0.00,   # No state sales tax
    "FL": 6.00,
    "GA": 4.00,
    "HI": 4.00,
    "ID": 6.00,
    "IL": 6.25,
    "IN": 7.00,
    "IA": 6.00,
    "KS": 6.50,
    "KY": 6.00,
    "LA": 4.45,
    "ME": 5.50,
    "MD": 6.00,
    "MA": 6.25,
    "MI": 6.00,
    "MN": 6.875,
    "MS": 7.00,
    "MO": 4.225,
    "MT": 0.00,   # No state sales tax
    "NE": 5.50,
    "NV": 6.85,
    "NH": 0.00,   # No state sales tax
    "NJ": 6.625,
    "NM": 5.125,
    "NY": 4.00,
    "NC": 4.75,
    "ND": 5.00,
    "OH": 5.75,
    "OK": 4.50,
    "OR": 0.00,   # No state sales tax
    "PA": 6.00,
    "RI": 7.00,
    "SC": 6.00,
    "SD": 4.20,
    "TN": 7.00,
    "TX": 6.25,
    "UT": 6.10,
    "VT": 6.00,
    "VA": 5.30,
    "WA": 6.50,
    "WV": 6.00,
    "WI": 5.00,
    "WY": 4.00,
    "DC": 6.00,
    "PR": 10.50,
}

# States with NO sales tax
_NO_TAX_STATES = {"AK", "DE", "MT", "NH", "OR"}


# ---------------------------------------------------------------------------
# US County/City tax rates for major jurisdictions
# ---------------------------------------------------------------------------

_US_LOCAL_RATES: dict[str, dict[str, float]] = {
    # Texas cities
    "US-TX-DALLAS": 2.00,            # Dallas: 2.00% local
    "US-TX-DALLAS_COUNTY": 0.00,     # no county rate (absorbed in city)
    "US-TX-TRAVIS_COUNTY": 0.00,
    "US-TX-AUSTIN": 2.00,            # Austin: 2.00% local
    "US-TX-HOUSTON": 2.00,
    "US-TX-HARRIS_COUNTY": 0.00,
    "US-TX-SAN_ANTONIO": 2.00,
    "US-TX-BEXAR_COUNTY": 0.00,
    "US-TX-FORT_WORTH": 2.00,
    "US-TX-TARRANT_COUNTY": 0.00,
    # California cities
    "US-CA-LOS_ANGELES": 2.25,       # LA district taxes
    "US-CA-LOS_ANGELES_COUNTY": 0.25,
    "US-CA-SAN_FRANCISCO": 1.25,
    "US-CA-SAN_FRANCISCO_COUNTY": 0.00,
    "US-CA-SAN_JOSE": 1.25,
    "US-CA-SANTA_CLARA_COUNTY": 0.00,
    "US-CA-SAN_DIEGO": 0.50,
    "US-CA-SAN_DIEGO_COUNTY": 0.50,
    # New York
    "US-NY-NEW_YORK_CITY": 4.50,     # NYC local
    "US-NY-NEW_YORK_COUNTY": 0.00,
    "US-NY-KINGS_COUNTY": 0.00,
    "US-NY-QUEENS_COUNTY": 0.00,
    "US-NY-BRONX_COUNTY": 0.00,
    "US-NY-RICHMOND_COUNTY": 0.00,
    "US-NY-BROOKLYN": 4.50,
    "US-NY-QUEENS": 4.50,
    "US-NY-BRONX": 4.50,
    "US-NY-STATEN_ISLAND": 4.50,
    "US-NY-JAMAICA": 4.50,
    "US-NY-BUFFALO": 4.00,
    "US-NY-ERIE_COUNTY": 0.00,
    "US-NY-ROCHESTER": 4.00,
    "US-NY-MONROE_COUNTY": 0.00,
    "US-NY-NIAGARA_FALLS": 4.00,
    "US-NY-NIAGARA_COUNTY": 0.00,
    # Illinois / Chicago
    "US-IL-CHICAGO": 1.25,
    "US-IL-COOK_COUNTY": 1.75,       # Cook County rate
    "US-IL-CHICAGO_SUBURBS": 1.25,
    # Florida
    "US-FL-MIAMI": 1.00,
    "US-FL-MIAMI-DADE_COUNTY": 0.00,
    "US-FL-ORLANDO": 0.50,
    "US-FL-ORANGE_COUNTY": 0.00,
    "US-FL-TAMPA": 1.50,
    "US-FL-HILLSBOROUGH_COUNTY": 0.00,
    # Pennsylvania
    "US-PA-PHILADELPHIA": 2.00,       # Philly extra
    "US-PA-PHILADELPHIA_COUNTY": 0.00,
    "US-PA-PITTSBURGH": 1.00,
    "US-PA-ALLEGHENY_COUNTY": 1.00,   # Allegheny County
    # Washington
    "US-WA-SEATTLE": 3.60,
    "US-WA-KING_COUNTY": 0.00,
    # Georgia
    "US-GA-ATLANTA": 1.50,
    "US-GA-FULTON_COUNTY": 0.00,
    # Michigan
    "US-MI-DETROIT": 0.00,
    "US-MI-WAYNE_COUNTY": 0.00,
    # Ohio
    "US-OH-COLUMBUS": 0.00,
    "US-OH-FRANKLIN_COUNTY": 1.75,
    "US-OH-CLEVELAND": 0.00,
    "US-OH-CUYAHOGA_COUNTY": 2.25,
    "US-OH-CINCINNATI": 0.00,
    "US-OH-HAMILTON_COUNTY": 1.50,
    # Massachusetts
    "US-MA-BOSTON": 0.00,
    "US-MA-SUFFOLK_COUNTY": 0.00,
    # Colorado
    "US-CO-DENVER": 4.81,            # Denver is notably high local
    "US-CO-DENVER_COUNTY": 0.00,
    # Arizona
    "US-AZ-PHOENIX": 2.30,
    "US-AZ-MARICOPA_COUNTY": 0.70,
    # Minnesota
    "US-MN-MINNEAPOLIS": 0.50,
    "US-MN-HENNEPIN_COUNTY": 0.15,
    "US-MN-ST._PAUL": 0.50,
    "US-MN-RAMSEY_COUNTY": 0.15,
    # Oregon — no state tax but cities have some taxes
    "US-OR-PORTLAND": 0.00,
    "US-OR-MULTNOMAH_COUNTY": 0.00,
    # Nevada
    "US-NV-LAS_VEGAS": 1.38,
    "US-NV-CLARK_COUNTY": 0.00,
    # Missouri
    "US-MO-ST._LOUIS": 4.454,
    "US-MO-ST._LOUIS_COUNTY": 0.00,
    "US-MO-KANSAS_CITY": 3.25,
    "US-MO-JACKSON_COUNTY": 0.00,
    # Tennessee
    "US-TN-NASHVILLE": 2.25,
    "US-TN-DAVIDSON_COUNTY": 0.00,
    "US-TN-MEMPHIS": 2.25,
    "US-TN-SHELBY_COUNTY": 0.00,
    # Louisiana
    "US-LA-NEW_ORLEANS": 5.00,
    "US-LA-ORLEANS_PARISH": 0.00,
    # Indiana
    "US-IN-INDIANAPOLIS": 0.00,
    "US-IN-MARION_COUNTY": 0.00,
}


# ---------------------------------------------------------------------------
# EU VAT standard rates
# ---------------------------------------------------------------------------

_EU_VAT_RATES: dict[str, float] = {
    "AT": 20.00,   # Austria
    "BE": 21.00,   # Belgium
    "BG": 20.00,   # Bulgaria
    "HR": 25.00,   # Croatia
    "CY": 19.00,   # Cyprus
    "CZ": 21.00,   # Czech Republic
    "DK": 25.00,   # Denmark
    "EE": 22.00,   # Estonia
    "FI": 25.50,   # Finland
    "FR": 20.00,   # France
    "DE": 19.00,   # Germany
    "GR": 24.00,   # Greece
    "HU": 27.00,   # Hungary
    "IE": 23.00,   # Ireland
    "IT": 22.00,   # Italy
    "LV": 21.00,   # Latvia
    "LT": 21.00,   # Lithuania
    "LU": 17.00,   # Luxembourg
    "MT": 18.00,   # Malta
    "NL": 21.00,   # Netherlands
    "PL": 23.00,   # Poland
    "PT": 23.00,   # Portugal
    "RO": 19.00,   # Romania
    "SK": 20.00,   # Slovakia
    "SI": 22.00,   # Slovenia
    "ES": 21.00,   # Spain
    "SE": 25.00,   # Sweden
    "GB": 20.00,   # United Kingdom
}

# EU VAT reduced rates (food, books, medicine, etc.)
_EU_VAT_REDUCED: dict[str, dict[str, float]] = {
    "DE": {"food": 7.0, "books": 7.0, "medicine": 19.0},
    "FR": {"food": 5.5, "books": 5.5, "medicine": 2.1},
    "GB": {"food": 0.0, "books": 0.0, "medicine": 0.0, "children_clothing": 0.0},
    "IT": {"food": 4.0, "books": 4.0, "medicine": 10.0},
    "ES": {"food": 4.0, "books": 4.0, "medicine": 4.0},
    "NL": {"food": 9.0, "books": 9.0, "medicine": 9.0},
    "BE": {"food": 6.0, "books": 6.0, "medicine": 6.0},
    "AT": {"food": 10.0, "books": 10.0, "medicine": 10.0},
    "SE": {"food": 12.0, "books": 6.0, "medicine": 0.0},
    "DK": {"food": 25.0, "books": 25.0, "medicine": 25.0},  # DK has no reduced rate
    "IE": {"food": 0.0, "books": 9.0, "medicine": 0.0},
    "PT": {"food": 6.0, "books": 6.0, "medicine": 6.0},
    "PL": {"food": 5.0, "books": 5.0, "medicine": 8.0},
    "HU": {"food": 18.0, "books": 5.0, "medicine": 5.0},
}


# ---------------------------------------------------------------------------
# GST rates by country
# ---------------------------------------------------------------------------

_GST_RATES: dict[str, float] = {
    "AU": 10.00,
    "NZ": 15.00,
    "CA": 5.00,    # Federal GST only (provincial on top)
    "SG": 9.00,
    "IN": 18.00,   # Standard GST
    "MY": 8.00,
}

# Canadian provincial sales tax (PST/HST additions beyond 5% GST)
_CA_PROVINCIAL_TAX: dict[str, float] = {
    "AB": 0.00,    # Alberta — GST only
    "BC": 7.00,    # British Columbia PST
    "MB": 7.00,    # Manitoba RST
    "NB": 10.00,   # New Brunswick — HST portion above GST
    "NL": 10.00,   # Newfoundland — HST portion above GST
    "NS": 10.00,   # Nova Scotia — HST portion above GST
    "NT": 0.00,    # Northwest Territories
    "NU": 0.00,    # Nunavut
    "ON": 8.00,    # Ontario — HST portion above GST
    "PE": 10.00,   # Prince Edward Island — HST portion above GST
    "QC": 9.975,   # Quebec QST
    "SK": 6.00,    # Saskatchewan PST
    "YT": 0.00,    # Yukon
}


# ---------------------------------------------------------------------------
# US product category exemptions / reduced rates by state
# ---------------------------------------------------------------------------

_US_CATEGORY_ADJUSTMENTS: dict[str, dict[str, float]] = {
    # States that exempt groceries (food for home consumption)
    "AZ": {"food": 0.0},
    "CA": {"food": 0.0},
    "CT": {"food": 0.0},
    "FL": {"food": 0.0},
    "GA": {"food": 0.0},
    "IA": {"food": 0.0},
    "ID": {"food": 0.0},
    "IL": {"food": 1.0},       # IL: reduced rate for food
    "IN": {"food": 0.0},
    "KY": {"food": 0.0},
    "LA": {"food": 0.0},
    "MA": {"food": 0.0},
    "MD": {"food": 0.0},
    "ME": {"food": 0.0},
    "MI": {"food": 0.0},
    "MN": {"food": 0.0, "clothing": 0.0},
    "MO": {"food": 1.225},     # MO: reduced rate for food
    "NE": {"food": 0.0},
    "NJ": {"food": 0.0, "clothing": 0.0},
    "NM": {"food": 0.0},
    "NY": {"food": 0.0, "clothing": 0.0},  # NY: clothing under $110 exempt
    "NC": {"food": 2.0},       # NC: reduced rate for food
    "ND": {"food": 0.0},
    "OH": {"food": 0.0},
    "OK": {"food": 4.5},       # OK: full state rate on food
    "OR": {},                   # No sales tax
    "PA": {"food": 0.0, "clothing": 0.0, "medicine": 0.0},
    "RI": {"food": 0.0, "clothing": 0.0},
    "SC": {"food": 0.0},
    "TX": {"food": 0.0},
    "UT": {"food": 3.0},       # UT: reduced rate for food
    "VA": {"food": 1.0},       # VA: reduced rate for food
    "VT": {"food": 0.0, "clothing": 0.0},
    "WA": {"food": 0.0},
    "WI": {"food": 0.0},
    "WV": {"food": 0.0},
    "WY": {"food": 0.0},
    # States that exempt medicine/prescription drugs
    "AL": {"medicine": 0.0},
    "CO": {"food": 0.0, "medicine": 0.0},
    "HI": {"medicine": 0.0},
    "KS": {"food": 2.0},       # KS: reduced rate for food (as of 2025)
    "MS": {"medicine": 0.0},
    "SD": {"medicine": 0.0},
    "TN": {"food": 4.0},       # TN: reduced rate for food
}


def lookup_rates(
    jurisdictions: list[dict[str, Any]],
    product_categories: list[str] | None = None,
) -> dict[str, Any]:
    """Look up tax rates for a list of jurisdictions.

    Args:
        jurisdictions: List of JurisdictionInfo dicts from jurisdiction_resolver.
        product_categories: Optional list of product categories for adjusted rates.

    Returns:
        Structured dict with rate details per jurisdiction.
    """
    try:
        jurisdictions = copy.deepcopy(jurisdictions)
        categories = list(product_categories) if product_categories else []

        if not jurisdictions:
            return _fail("No jurisdictions provided")

        rates: list[dict[str, Any]] = []

        for jur in jurisdictions:
            name = str(jur.get("name", ""))
            jur_type = str(jur.get("type", ""))
            code = str(jur.get("code", ""))

            rate_entry = _resolve_rate(name, jur_type, code, categories)
            if rate_entry is not None:
                rates.append(rate_entry)

        return {
            "status": "success",
            "rates": rates,
        }
    except Exception as exc:
        return _fail(f"Rate lookup failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fail(reason: str) -> dict[str, Any]:
    """Standardized error output."""
    return {
        "status": "error",
        "rates": [],
        "error": reason,
    }


def _resolve_rate(
    name: str,
    jur_type: str,
    code: str,
    categories: list[str],
) -> dict[str, Any] | None:
    """Resolve a single rate for one jurisdiction."""

    # --- US state ---
    if jur_type == "state" and code.startswith("US-"):
        state = code.split("-")[1] if "-" in code else name
        base_rate = _US_STATE_RATES.get(state, 0.0)
        adjustments = _build_category_adjustments(
            _US_CATEGORY_ADJUSTMENTS.get(state, {}), categories,
        )
        return {
            "jurisdiction": name,
            "type": "state",
            "rate": base_rate,
            "category_adjustments": adjustments,
        }

    # --- US county / city ---
    if jur_type in ("county", "city") and code.startswith("US-"):
        local_rate = _US_LOCAL_RATES.get(code, 0.0)
        return {
            "jurisdiction": name,
            "type": jur_type,
            "rate": local_rate,
            "category_adjustments": {},
        }

    # --- EU VAT (country level) ---
    if jur_type == "country" and name in _EU_VAT_RATES:
        base_rate = _EU_VAT_RATES[name]
        adjustments = _build_category_adjustments(
            _EU_VAT_REDUCED.get(name, {}), categories,
        )
        return {
            "jurisdiction": name,
            "type": "vat",
            "rate": base_rate,
            "category_adjustments": adjustments,
        }

    # --- GST (country level) ---
    if jur_type == "country" and name in _GST_RATES:
        base_rate = _GST_RATES[name]
        return {
            "jurisdiction": name,
            "type": "gst",
            "rate": base_rate,
            "category_adjustments": {},
        }

    # --- Canadian province ---
    if jur_type == "province" and code.startswith("CA-"):
        province = code.split("-")[1] if "-" in code else name
        prov_rate = _CA_PROVINCIAL_TAX.get(province, 0.0)
        return {
            "jurisdiction": name,
            "type": "provincial",
            "rate": prov_rate,
            "category_adjustments": {},
        }

    # Jurisdiction not found in rate tables — return zero rate
    return {
        "jurisdiction": name,
        "type": jur_type,
        "rate": 0.0,
        "category_adjustments": {},
    }


def _build_category_adjustments(
    state_adjustments: dict[str, float],
    categories: list[str],
) -> dict[str, float]:
    """Build category adjustment map for the given categories.

    Returns a dict mapping category -> adjusted rate.
    Only includes categories that have a special rate.
    """
    if not state_adjustments or not categories:
        return {}

    adjustments: dict[str, float] = {}
    for cat in categories:
        cat_lower = cat.lower().replace(" ", "_")
        if cat_lower in state_adjustments:
            adjustments[cat] = state_adjustments[cat_lower]
    return adjustments
