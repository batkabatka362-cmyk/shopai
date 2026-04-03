"""Tax Engine — jurisdiction resolver.

Determines the applicable tax jurisdiction(s) based on origin and
destination addresses, and resolves the tax type (sales_tax, vat, gst).

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Country → tax type mapping
# ---------------------------------------------------------------------------

_EU_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE",
}

_GST_COUNTRIES = {"AU", "NZ", "SG", "IN", "MY"}

# Canada uses GST federally (some provinces add PST or use HST)
_CANADA_CODE = "CA"

# UK left EU but still uses VAT
_VAT_COUNTRIES = _EU_COUNTRIES | {"GB", "NO", "CH", "IS"}

# US states with NO sales tax
_US_NO_TAX_STATES = {"MT", "OR", "NH", "DE", "AK"}

# ---------------------------------------------------------------------------
# US ZIP → city/county lookup (major metro areas)
# ---------------------------------------------------------------------------

_US_ZIP_LOOKUP: dict[str, dict[str, Any]] = {
    "100": {"city": "New York", "county": "New York County", "state": "NY"},
    "101": {"city": "New York", "county": "New York County", "state": "NY"},
    "102": {"city": "New York", "county": "New York County", "state": "NY"},
    "103": {"city": "Staten Island", "county": "Richmond County", "state": "NY"},
    "112": {"city": "Brooklyn", "county": "Kings County", "state": "NY"},
    "113": {"city": "Flushing", "county": "Queens County", "state": "NY"},
    "606": {"city": "Chicago", "county": "Cook County", "state": "IL"},
    "607": {"city": "Chicago", "county": "Cook County", "state": "IL"},
    "900": {"city": "Los Angeles", "county": "Los Angeles County", "state": "CA"},
    "901": {"city": "Los Angeles", "county": "Los Angeles County", "state": "CA"},
    "902": {"city": "Inglewood", "county": "Los Angeles County", "state": "CA"},
    "941": {"city": "San Francisco", "county": "San Francisco County", "state": "CA"},
    "946": {"city": "Oakland", "county": "Alameda County", "state": "CA"},
    "770": {"city": "Houston", "county": "Harris County", "state": "TX"},
    "752": {"city": "Dallas", "county": "Dallas County", "state": "TX"},
    "787": {"city": "Austin", "county": "Travis County", "state": "TX"},
    "331": {"city": "Miami", "county": "Miami-Dade County", "state": "FL"},
    "330": {"city": "Fort Lauderdale", "county": "Broward County", "state": "FL"},
    "303": {"city": "Atlanta", "county": "Fulton County", "state": "GA"},
    "981": {"city": "Seattle", "county": "King County", "state": "WA"},
    "021": {"city": "Boston", "county": "Suffolk County", "state": "MA"},
    "191": {"city": "Philadelphia", "county": "Philadelphia County", "state": "PA"},
    "852": {"city": "Phoenix", "county": "Maricopa County", "state": "AZ"},
    "891": {"city": "Las Vegas", "county": "Clark County", "state": "NV"},
    "802": {"city": "Denver", "county": "Denver County", "state": "CO"},
    "481": {"city": "Detroit", "county": "Wayne County", "state": "MI"},
    "551": {"city": "Minneapolis", "county": "Hennepin County", "state": "MN"},
    "631": {"city": "St. Louis", "county": "St. Louis County", "state": "MO"},
    "432": {"city": "Columbus", "county": "Franklin County", "state": "OH"},
    "462": {"city": "Indianapolis", "county": "Marion County", "state": "IN"},
    "372": {"city": "Nashville", "county": "Davidson County", "state": "TN"},
    "282": {"city": "Charlotte", "county": "Mecklenburg County", "state": "NC"},
    "532": {"city": "Milwaukee", "county": "Milwaukee County", "state": "WI"},
    "701": {"city": "New Orleans", "county": "Orleans Parish", "state": "LA"},
    "402": {"city": "Louisville", "county": "Jefferson County", "state": "KY"},
    "292": {"city": "Columbia", "county": "Richland County", "state": "SC"},
    "212": {"city": "Baltimore", "county": "Baltimore City", "state": "MD"},
    "232": {"city": "Richmond", "county": "City of Richmond", "state": "VA"},
    "200": {"city": "Washington", "county": "District of Columbia", "state": "DC"},
    "503": {"city": "Des Moines", "county": "Polk County", "state": "IA"},
    "681": {"city": "Omaha", "county": "Douglas County", "state": "NE"},
    "731": {"city": "Oklahoma City", "county": "Oklahoma County", "state": "OK"},
    "672": {"city": "Wichita", "county": "Sedgwick County", "state": "KS"},
    "501": {"city": "Albuquerque", "county": "Bernalillo County", "state": "NM"},
    "962": {"city": "Honolulu", "county": "Honolulu County", "state": "HI"},
    "835": {"city": "Boise", "county": "Ada County", "state": "ID"},
    "841": {"city": "Salt Lake City", "county": "Salt Lake County", "state": "UT"},
    "053": {"city": "Burlington", "county": "Chittenden County", "state": "VT"},
    "040": {"city": "Portland", "county": "Cumberland County", "state": "ME"},
    "572": {"city": "Sioux Falls", "county": "Minnehaha County", "state": "SD"},
    "581": {"city": "Fargo", "county": "Cass County", "state": "ND"},
    "820": {"city": "Cheyenne", "county": "Laramie County", "state": "WY"},
    "596": {"city": "Helena", "county": "Lewis and Clark County", "state": "MT"},
    "995": {"city": "Anchorage", "county": "Anchorage Borough", "state": "AK"},
    "716": {"city": "Little Rock", "county": "Pulaski County", "state": "AR"},
    "392": {"city": "Jackson", "county": "Hinds County", "state": "MS"},
    "350": {"city": "Birmingham", "county": "Jefferson County", "state": "AL"},
    "257": {"city": "Charleston", "county": "Kanawha County", "state": "WV"},
    "198": {"city": "Wilmington", "county": "New Castle County", "state": "DE"},
    "030": {"city": "Manchester", "county": "Hillsborough County", "state": "NH"},
    "029": {"city": "Providence", "county": "Providence County", "state": "RI"},
    "061": {"city": "Hartford", "county": "Hartford County", "state": "CT"},
    "086": {"city": "Trenton", "county": "Mercer County", "state": "NJ"},
    "973": {"city": "Portland", "county": "Multnomah County", "state": "OR"},
}


def resolve_jurisdiction(
    origin: dict[str, Any],
    destination: dict[str, Any],
    tax_type: str = "auto",
) -> dict[str, Any]:
    """Resolve tax jurisdiction(s) from origin/destination addresses.

    Args:
        origin: Origin address dict.
        destination: Destination address dict.
        tax_type: "auto", "sales_tax", "vat", or "gst".

    Returns:
        Structured dict with jurisdiction info.
    """
    try:
        origin = copy.deepcopy(origin)
        destination = copy.deepcopy(destination)

        dest_country = str(destination.get("country_code", "")).upper()
        origin_country = str(origin.get("country_code", "")).upper()

        if not dest_country:
            return _fail("Destination country_code is required")

        # ---- Determine tax type ----
        resolved_type = tax_type
        if resolved_type == "auto":
            resolved_type = _detect_tax_type(dest_country)

        # ---- Resolve jurisdictions ----
        if resolved_type == "sales_tax":
            return _resolve_us_sales_tax(origin, destination, dest_country)
        elif resolved_type == "vat":
            return _resolve_vat(destination, dest_country)
        elif resolved_type == "gst":
            return _resolve_gst(destination, dest_country)
        else:
            return _fail(f"Unknown tax type: {resolved_type}")

    except Exception as exc:
        return _fail(f"Jurisdiction resolution failed: {exc}")


# ---------------------------------------------------------------------------
# Tax type detection
# ---------------------------------------------------------------------------

def _detect_tax_type(country_code: str) -> str:
    """Detect tax type from country code."""
    if country_code == "US":
        return "sales_tax"
    if country_code in _VAT_COUNTRIES:
        return "vat"
    if country_code in _GST_COUNTRIES or country_code == _CANADA_CODE:
        return "gst"
    # Default to VAT for unknown countries
    return "vat"


# ---------------------------------------------------------------------------
# US sales tax resolution
# ---------------------------------------------------------------------------

def _resolve_us_sales_tax(
    origin: dict[str, Any],
    destination: dict[str, Any],
    country_code: str,
) -> dict[str, Any]:
    """Resolve US state/county/city jurisdictions."""
    state = str(destination.get("province", "")).upper()
    zip_code = str(destination.get("zip", ""))
    city = str(destination.get("city", ""))

    if not state:
        return _fail("US destination requires 'province' (state code)")

    # No sales tax states
    if state in _US_NO_TAX_STATES:
        return {
            "status": "success",
            "country": country_code,
            "tax_type": "sales_tax",
            "jurisdictions": [],
            "is_nexus": True,
            "note": f"{state} has no state sales tax",
        }

    jurisdictions: list[dict[str, Any]] = []

    # State-level jurisdiction
    jurisdictions.append({
        "name": state,
        "type": "state",
        "code": f"US-{state}",
    })

    # County/city from ZIP lookup
    zip_prefix = zip_code[:3] if len(zip_code) >= 3 else ""
    local = _US_ZIP_LOOKUP.get(zip_prefix, {})

    county = local.get("county", "")
    local_city = local.get("city", city)

    if county:
        jurisdictions.append({
            "name": county,
            "type": "county",
            "code": f"US-{state}-COUNTY",
        })

    if local_city:
        jurisdictions.append({
            "name": local_city,
            "type": "city",
            "code": f"US-{state}-CITY",
        })

    # Nexus: same-state origin/destination = nexus
    origin_state = str(origin.get("province", "")).upper()
    is_nexus = origin_state == state

    return {
        "status": "success",
        "country": country_code,
        "tax_type": "sales_tax",
        "jurisdictions": jurisdictions,
        "is_nexus": is_nexus,
    }


# ---------------------------------------------------------------------------
# VAT resolution
# ---------------------------------------------------------------------------

def _resolve_vat(
    destination: dict[str, Any],
    country_code: str,
) -> dict[str, Any]:
    """Resolve VAT jurisdiction for EU/UK countries."""
    return {
        "status": "success",
        "country": country_code,
        "tax_type": "vat",
        "jurisdictions": [
            {
                "name": country_code,
                "type": "country",
                "code": country_code,
            },
        ],
        "is_nexus": True,
    }


# ---------------------------------------------------------------------------
# GST resolution
# ---------------------------------------------------------------------------

def _resolve_gst(
    destination: dict[str, Any],
    country_code: str,
) -> dict[str, Any]:
    """Resolve GST jurisdiction."""
    jurisdictions: list[dict[str, Any]] = [
        {
            "name": country_code,
            "type": "country",
            "code": country_code,
        },
    ]

    # Canada: also add province for PST/HST
    if country_code == "CA":
        province = str(destination.get("province", "")).upper()
        if province:
            jurisdictions.append({
                "name": province,
                "type": "province",
                "code": f"CA-{province}",
            })

    return {
        "status": "success",
        "country": country_code,
        "tax_type": "gst",
        "jurisdictions": jurisdictions,
        "is_nexus": True,
    }


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------

def _fail(reason: str) -> dict[str, Any]:
    """Return standardized error output."""
    return {
        "status": "error",
        "country": None,
        "tax_type": None,
        "jurisdictions": [],
        "is_nexus": False,
        "error": reason,
    }
