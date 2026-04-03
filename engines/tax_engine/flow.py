"""Tax Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Validate → Memory Reader → Jurisdiction Resolver → Rate Lookup →
  Exemption Checker → Tax Calculator → Tax Reporter → Memory Writer → Output

Engine contract:
  Input:  {status, data: {transaction, origin_address, destination_address, customer, tax_type}, meta, error}
  Output: {status, data: {transaction_id, currency, tax_type, tax_lines, total_tax, total_taxable, exemptions, report}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .memory_reader import read_tax_cache
from .jurisdiction_resolver import resolve_jurisdiction
from .rate_lookup import lookup_rates
from .exemption_checker import check_exemptions
from .tax_calculator import calculate_tax
from .tax_reporter import generate_tax_report
from .memory_writer import write_tax_record


class TaxEngine:
    """Tax Engine — orchestrator only, no logic."""

    ENGINE_NAME = "tax_engine"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full tax pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            TaxOutput dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation (no mutation) ----
        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        transaction = data.get("transaction", {})
        if not isinstance(transaction, dict):
            return self._fail("Transaction data is required", 0.0)

        line_items = transaction.get("line_items", [])
        if not line_items:
            return self._fail("Transaction must have line items", 0.0)

        origin_address = data.get("origin_address", {})
        destination_address = data.get("destination_address", {})
        customer = data.get("customer", {})
        tax_type = str(data.get("tax_type", "auto"))
        tax_included = bool(data.get("tax_included", False))
        transaction_id = str(transaction.get("id", ""))
        currency = str(transaction.get("currency", "USD"))

        if not destination_address:
            return self._fail("Destination address is required", 0.0)

        # ---- Stage 1: Read tax cache (non-blocking) ----
        _cache = read_tax_cache(limit=10)

        # ---- Stage 2: Jurisdiction Resolver ----
        jurisdiction_result = resolve_jurisdiction(
            origin=origin_address,
            destination=destination_address,
            tax_type=tax_type,
        )
        if jurisdiction_result.get("status") == "error":
            return self._fail(
                f"Jurisdiction resolution failed: {jurisdiction_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        jurisdictions = jurisdiction_result.get("jurisdictions", [])
        resolved_tax_type = str(jurisdiction_result.get("tax_type", tax_type))

        # ---- Stage 3: Rate Lookup ----
        product_categories = list({
            str(item.get("product_category", ""))
            for item in line_items
            if item.get("product_category")
        })

        rate_result = lookup_rates(
            jurisdictions=jurisdictions,
            product_categories=product_categories,
        )
        if rate_result.get("status") == "error":
            return self._fail(
                f"Rate lookup failed: {rate_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        rates = rate_result.get("rates", [])

        # ---- Stage 4: Exemption Checker ----
        exemption_result = check_exemptions(
            customer=customer,
            line_items=line_items,
            jurisdictions=jurisdictions,
        )
        if exemption_result.get("status") == "error":
            return self._fail(
                f"Exemption check failed: {exemption_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        exemptions = exemption_result.get("exemptions", [])
        fully_exempt = exemption_result.get("fully_exempt", False)

        # ---- Stage 5: Tax Calculator ----
        # Apply exemptions to line items before calculation
        calc_items = copy.deepcopy(line_items)
        exemption_map = {
            str(e.get("line_item_id", "")): e
            for e in exemptions
        }
        for item in calc_items:
            item_id = str(item.get("id", ""))
            ex = exemption_map.get(item_id, {})
            if ex.get("exempt", False):
                item["_exempt"] = True

        tax_result = calculate_tax(
            line_items=calc_items,
            rates=rates,
            tax_included=tax_included,
        )
        if tax_result.get("status") == "error":
            return self._fail(
                f"Tax calculation failed: {tax_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        tax_lines = tax_result.get("tax_lines", [])
        total_tax = float(tax_result.get("total_tax", 0.0))

        # ---- Stage 6: Tax Reporter ----
        report_result = generate_tax_report(
            tax_lines=tax_lines,
            jurisdictions=jurisdictions,
        )
        if report_result.get("status") == "error":
            return self._fail(
                f"Tax report generation failed: {report_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        report = report_result.get("report", {})

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_tax_record(
            transaction_id=transaction_id,
            tax_lines=tax_lines,
            total_tax=total_tax,
            jurisdictions=jurisdictions,
            report=report,
            exemptions=exemptions,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        total_taxable = round(
            sum(float(tl.get("taxable_amount", 0.0)) for tl in tax_lines), 2,
        )

        return {
            "status": "success",
            "data": {
                "transaction_id": transaction_id,
                "currency": currency,
                "tax_type": resolved_tax_type,
                "tax_included": tax_included,
                "tax_lines": tax_lines,
                "total_tax": total_tax,
                "total_taxable": total_taxable,
                "exemptions": exemptions,
                "report": report,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Error output
    # -------------------------------------------------------------------

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
