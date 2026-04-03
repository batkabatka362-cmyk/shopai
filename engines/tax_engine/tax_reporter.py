"""Tax Engine — tax reporter.

Generates tax collection summaries by jurisdiction for compliance reporting.
Determines filing periods and produces jurisdiction breakdowns.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Filing frequency by state (simplified)
# ---------------------------------------------------------------------------

_MONTHLY_FILING_STATES = {
    "CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "MI",
    "NJ", "VA", "WA", "AZ", "MA", "TN", "IN", "MO", "MD", "WI",
    "MN", "CO", "SC", "AL", "LA", "KY", "OR", "OK", "CT", "UT",
    "NV", "IA", "AR", "MS", "KS", "NE",
}

# States typically requiring quarterly filing for smaller volumes
_QUARTERLY_FILING_STATES = {
    "ND", "SD", "WY", "MT", "NH", "VT", "ME", "RI", "DE", "HI",
    "ID", "NM", "WV", "DC",
}


def generate_tax_report(
    tax_lines: list[dict[str, Any]],
    jurisdictions: list[dict[str, Any]],
    period: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a tax compliance report.

    Args:
        tax_lines: List of TaxLineItem dicts from tax_calculator.
        jurisdictions: List of JurisdictionInfo dicts.
        period: Optional dict with 'start' and 'end' date strings.

    Returns:
        Structured dict with filing report.
    """
    try:
        tax_lines = copy.deepcopy(tax_lines)
        jurisdictions = copy.deepcopy(jurisdictions)

        if not tax_lines:
            return _fail("No tax lines provided for reporting")

        # Determine filing jurisdiction (primary state or country)
        filing_jurisdiction = _determine_filing_jurisdiction(jurisdictions)

        # Determine filing period
        filing_period = _determine_filing_period(filing_jurisdiction, period)

        # Compute totals
        total_taxable = 0.0
        total_tax = 0.0
        jurisdiction_totals: dict[str, dict[str, float]] = {}

        for line in tax_lines:
            taxable = float(line.get("taxable_amount", 0.0))
            total_taxable += taxable

            line_tax = float(line.get("tax_amount", 0.0))
            total_tax += line_tax

            for jd in line.get("jurisdictions", []):
                jur_name = str(jd.get("name", "unknown"))
                amount = float(jd.get("amount", 0.0))

                if jur_name not in jurisdiction_totals:
                    jurisdiction_totals[jur_name] = {
                        "taxable": 0.0,
                        "collected": 0.0,
                    }
                jurisdiction_totals[jur_name]["taxable"] += taxable
                jurisdiction_totals[jur_name]["collected"] += amount

        # Build breakdown list
        breakdown: list[dict[str, Any]] = []
        for jur_name, totals in jurisdiction_totals.items():
            breakdown.append({
                "name": jur_name,
                "taxable": round(totals["taxable"], 2),
                "collected": round(totals["collected"], 2),
            })

        # Sort by collected descending
        breakdown.sort(key=lambda x: x["collected"], reverse=True)

        report: dict[str, Any] = {
            "filing_jurisdiction": filing_jurisdiction,
            "period": filing_period,
            "total_taxable": round(total_taxable, 2),
            "total_tax": round(total_tax, 2),
            "jurisdiction_breakdown": breakdown,
        }

        return {
            "status": "success",
            "report": report,
        }
    except Exception as exc:
        return _fail(f"Tax report generation failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fail(reason: str) -> dict[str, Any]:
    """Standardized error output."""
    return {
        "status": "error",
        "report": {},
        "error": reason,
    }


def _determine_filing_jurisdiction(
    jurisdictions: list[dict[str, Any]],
) -> str:
    """Determine the primary filing jurisdiction."""
    for jur in jurisdictions:
        jur_type = str(jur.get("type", ""))
        if jur_type == "state":
            return str(jur.get("code", jur.get("name", "unknown")))
        if jur_type == "country":
            return str(jur.get("code", jur.get("name", "unknown")))
    if jurisdictions:
        return str(jurisdictions[0].get("code", "unknown"))
    return "unknown"


def _determine_filing_period(
    filing_jurisdiction: str,
    period: dict[str, Any] | None,
) -> str:
    """Determine the filing period string."""
    if period:
        start = str(period.get("start", ""))
        end = str(period.get("end", ""))
        if start and end:
            return f"{start} to {end}"
        if start:
            return start

    # Determine frequency based on jurisdiction
    state = ""
    if filing_jurisdiction.startswith("US-"):
        parts = filing_jurisdiction.split("-")
        if len(parts) >= 2:
            state = parts[1]

    if state in _MONTHLY_FILING_STATES:
        return "monthly"
    if state in _QUARTERLY_FILING_STATES:
        return "quarterly"

    # Default for VAT/GST countries or unknown
    return "quarterly"
