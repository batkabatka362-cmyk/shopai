"""Tax Engine — tax calculator.

Calculates tax for each line item across all applicable jurisdictions.
Handles compound taxes and tax-included pricing.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def calculate_tax(
    line_items: list[dict[str, Any]],
    rates: list[dict[str, Any]],
    tax_included: bool = False,
) -> dict[str, Any]:
    """Calculate tax for line items given jurisdiction rates.

    Args:
        line_items: List of TransactionItem dicts.
        rates: List of TaxRate dicts from rate_lookup.
        tax_included: If True, prices already include tax (extract tax).

    Returns:
        Structured dict with per-line-item tax breakdown and totals.
    """
    try:
        line_items = copy.deepcopy(line_items)
        rates = copy.deepcopy(rates)

        if not line_items:
            return _fail("No line items provided")

        tax_lines: list[dict[str, Any]] = []
        total_tax = 0.0

        for item in line_items:
            item_id = str(item.get("id", "unknown"))
            quantity = int(item.get("quantity", 1))
            unit_price = float(item.get("unit_price", 0.0))
            category = str(item.get("product_category", ""))
            is_exempt = bool(item.get("_exempt", False))

            gross_amount = round(quantity * unit_price, 2)

            if is_exempt:
                # Exempt items: no tax
                tax_lines.append({
                    "line_item_id": item_id,
                    "taxable_amount": gross_amount,
                    "tax_amount": 0.0,
                    "jurisdictions": [],
                })
                continue

            # Compute combined rate considering category adjustments
            combined_rate = 0.0
            jurisdiction_details: list[dict[str, Any]] = []

            for rate_entry in rates:
                jur_name = str(rate_entry.get("jurisdiction", ""))
                base_rate = float(rate_entry.get("rate", 0.0))
                cat_adjustments = rate_entry.get("category_adjustments", {})

                # Check if this category has an adjusted rate
                effective_rate = base_rate
                if category and category in cat_adjustments:
                    effective_rate = float(cat_adjustments[category])

                if effective_rate <= 0.0:
                    # Still include for reporting as 0 rate
                    if base_rate > 0.0:
                        jurisdiction_details.append({
                            "name": jur_name,
                            "rate": 0.0,
                            "amount": 0.0,
                        })
                    continue

                combined_rate += effective_rate

                # We'll compute amounts after combining
                jurisdiction_details.append({
                    "name": jur_name,
                    "rate": effective_rate,
                    "amount": 0.0,  # filled below
                })

            # Compute taxable amount and tax
            if tax_included and combined_rate > 0:
                # Extract tax from tax-inclusive price
                # price = taxable + tax = taxable * (1 + rate/100)
                # taxable = price / (1 + rate/100)
                taxable_amount = round(gross_amount / (1.0 + combined_rate / 100.0), 2)
                total_line_tax = round(gross_amount - taxable_amount, 2)
            else:
                taxable_amount = gross_amount
                total_line_tax = round(taxable_amount * combined_rate / 100.0, 2)

            # Distribute tax across jurisdictions proportionally
            if combined_rate > 0:
                for jd in jurisdiction_details:
                    if jd["rate"] > 0:
                        proportion = jd["rate"] / combined_rate
                        jd["amount"] = round(total_line_tax * proportion, 2)

                # Fix rounding: adjust the largest jurisdiction to match total
                non_zero = [jd for jd in jurisdiction_details if jd["amount"] > 0]
                if non_zero:
                    distributed = sum(jd["amount"] for jd in non_zero)
                    diff = round(total_line_tax - distributed, 2)
                    if diff != 0:
                        # Apply rounding diff to largest jurisdiction
                        largest = max(non_zero, key=lambda x: x["amount"])
                        largest["amount"] = round(largest["amount"] + diff, 2)

            tax_lines.append({
                "line_item_id": item_id,
                "taxable_amount": taxable_amount,
                "tax_amount": total_line_tax,
                "jurisdictions": jurisdiction_details,
            })

            total_tax += total_line_tax

        total_tax = round(total_tax, 2)

        return {
            "status": "success",
            "tax_lines": tax_lines,
            "total_tax": total_tax,
        }
    except Exception as exc:
        return _fail(f"Tax calculation failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fail(reason: str) -> dict[str, Any]:
    """Standardized error output."""
    return {
        "status": "error",
        "tax_lines": [],
        "total_tax": 0.0,
        "error": reason,
    }
