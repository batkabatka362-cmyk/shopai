"""Product Filter Engine — filters products through 5 validation gates.

Flow: input → criteria → blacklist → shipping → legal → brand_fit → output

Products must pass ALL gates to be "accepted".
Each gate can: accept / reject (with reason) / flag (needs review).
"""
from __future__ import annotations

import time
from typing import Any

from .input.handler import validate_and_standardize
from .output.formatter import format_output
from .validation.validator import validate_result
from .modules.criteria_matcher.code import filter_by_criteria
from .modules.blacklist_checker.code import check_blacklist
from .modules.shipping_feasibility.code import check_shipping_feasibility
from .modules.legal_checker.code import check_legal_compliance
from .modules.brand_fit.code import check_brand_fit


class ProductFilterEngine:
    """Product Filter Engine — orchestrator only."""

    ENGINE_NAME = "product_filter"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()

        processed = validate_and_standardize(input_payload)
        if processed["status"] == "fail":
            return processed

        data = processed["data"]
        products = data.get("products", [])
        criteria = data.get("criteria", {})
        brand_profile = data.get("brand_profile", {})

        results: dict[str, Any] = {}
        current_products = list(products)

        # Gate 1: Criteria filter (margin, price, weight, rating)
        criteria_result = filter_by_criteria({
            "status": "success",
            "data": {"products": current_products, "criteria": criteria},
            "meta": {}, "error": None,
        })
        results["criteria"] = criteria_result
        if criteria_result.get("status") == "success":
            current_products = criteria_result.get("data", {}).get("accepted", current_products)

        # Gate 2: Blacklist check
        blacklist_results = []
        passed_blacklist = []
        for product in current_products:
            bl = check_blacklist({"status": "success", "data": {"product": product}, "meta": {}, "error": None})
            blacklist_results.append(bl)
            if bl.get("status") == "success" and bl.get("data", {}).get("verdict") != "blocked":
                passed_blacklist.append(product)
        results["blacklist"] = {"checked": len(current_products), "passed": len(passed_blacklist)}
        current_products = passed_blacklist

        # Gate 3: Shipping feasibility
        shipping_results = []
        passed_shipping = []
        for product in current_products:
            sh = check_shipping_feasibility({"status": "success", "data": {"product": product}, "meta": {}, "error": None})
            shipping_results.append(sh)
            verdict = sh.get("data", {}).get("verdict", "feasible") if sh.get("status") == "success" else "unknown"
            if verdict != "infeasible":
                passed_shipping.append(product)
        results["shipping"] = {"checked": len(current_products), "passed": len(passed_shipping)}
        current_products = passed_shipping

        # Gate 4: Legal compliance
        legal_results = []
        passed_legal = []
        for product in current_products:
            lc = check_legal_compliance({"status": "success", "data": {"product": product}, "meta": {}, "error": None})
            legal_results.append(lc)
            status = lc.get("data", {}).get("status", "compliant") if lc.get("status") == "success" else "unknown"
            if status != "non_compliant":
                passed_legal.append(product)
        results["legal"] = {"checked": len(current_products), "passed": len(passed_legal)}
        current_products = passed_legal

        # Gate 5: Brand fit
        brand_results = []
        passed_brand = []
        for product in current_products:
            bf = check_brand_fit({"status": "success", "data": {"product": product, "brand_profile": brand_profile}, "meta": {}, "error": None})
            brand_results.append(bf)
            score = bf.get("data", {}).get("fit_score", 50) if bf.get("status") == "success" else 50
            if score >= 40:
                passed_brand.append(product)
        results["brand_fit"] = {"checked": len(current_products), "passed": len(passed_brand)}

        final_products = passed_brand
        elapsed = time.monotonic() - start

        output = format_output(
            engine_name=self.ENGINE_NAME,
            results=results,
            input_count=len(products),
            final_products=final_products,
            elapsed=elapsed,
        )

        validation = validate_result(output)
        if not validation["valid"]:
            return {"status": "fail", "data": None, "meta": {"engine": self.ENGINE_NAME, "confidence": 0, "timestamp": _now()}, "error": {"reason": validation["reason"]}}

        return output


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
