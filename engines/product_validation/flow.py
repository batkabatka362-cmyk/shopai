"""Product Validation Engine — flow orchestrator.

Pipeline:
  Products -> Compliance Checker -> Sourcing Validator -> Quality Assessor ->
  Risk Flagger -> Memory Writer -> Output

Engine contract:
  Input:  {status, data: {products, compliance_standards}, meta, error}
  Output: {status, data: {validated_products, compliance_issues, quality_summary, risk_flags}, meta, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .compliance_checker import check_compliance
from .sourcing_validator import validate_sourcing
from .quality_assessor import assess_quality
from .risk_flagger import flag_risks
from .memory_reader import read_past_validations
from .memory_writer import write_validation_result
from engines._shopify_hydrator import hydrate


class ProductValidationEngine:
    """Product Validation Engine — orchestrator only, no logic."""

    ENGINE_NAME = "product_validation"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()

        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(payload.get("error", "Upstream failure"), 0.0)

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        products = data.get("products", [])
        standards = data.get("compliance_standards", [])

        # Auto-hydrate products from Shopify when caller left the
        # list empty. Pre-existing failure semantics preserved:
        # empty supplied AND empty hydrated → standard error.
        products = hydrate(
            supplied=products if isinstance(products, list) else [],
            capability_name="SHOPIFY_LIST_PRODUCTS",
            list_field="products",
            limit=data.get("hydrate_limit"),
            query=data.get("hydrate_query"),
        )

        if not products:
            return self._fail("Product list is required", 0.0)

        _past = read_past_validations(limit=5)

        # Stage 1: Compliance Checker
        compliance_result = check_compliance(products=products, standards=standards)
        if compliance_result.get("status") == "error":
            return self._fail(f"Compliance check failed: {compliance_result.get('error', 'unknown')}", time.monotonic() - start)
        compliance_issues = compliance_result.get("issues", [])

        # Stage 2: Sourcing Validator
        sourcing_result = validate_sourcing(products=products)
        if sourcing_result.get("status") == "error":
            return self._fail(f"Sourcing validation failed: {sourcing_result.get('error', 'unknown')}", time.monotonic() - start)
        sourcing_results = sourcing_result.get("results", [])

        # Stage 3: Quality Assessor
        quality_result = assess_quality(products=products)
        if quality_result.get("status") == "error":
            return self._fail(f"Quality assessment failed: {quality_result.get('error', 'unknown')}", time.monotonic() - start)
        quality_assessments = quality_result.get("assessments", [])
        quality_summary = quality_result.get("summary", {})

        # Stage 4: Risk Flagger
        risk_result = flag_risks(
            products=products,
            compliance_issues=compliance_issues,
            sourcing_results=sourcing_results,
            quality_assessments=quality_assessments,
        )
        if risk_result.get("status") == "error":
            return self._fail(f"Risk flagging failed: {risk_result.get('error', 'unknown')}", time.monotonic() - start)
        risk_flags = risk_result.get("flags", [])

        # Build validated product list
        risk_map = {str(f.get("id", "")): f for f in risk_flags}
        validated: list[dict[str, Any]] = []
        for p in products:
            pid = str(p.get("id", ""))
            rf = risk_map.get(pid, {})
            validated.append({
                "id": pid,
                "title": str(p.get("title", "")),
                "risk_level": rf.get("risk_level", "unknown"),
                "recommendation": rf.get("recommendation", "review"),
                "passed": rf.get("risk_level", "high") not in ("high", "critical"),
            })

        _write = write_validation_result(
            validated_products=validated,
            compliance_issues=compliance_issues,
            quality_summary=quality_summary,
            risk_flags=risk_flags,
        )

        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "validated_products": validated,
                "compliance_issues": compliance_issues,
                "quality_summary": quality_summary,
                "risk_flags": risk_flags,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
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
