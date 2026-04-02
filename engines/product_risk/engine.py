"""Product Risk Engine — orchestrates all risk modules into a composite assessment.

Runs five risk modules: market_risk, supplier_risk, legal_risk, financial_risk,
seasonal_risk. Aggregates individual scores into a composite risk score.
"""
from __future__ import annotations
import time
from typing import Any
from .input.handler import validate_and_standardize
from .output.formatter import format_output
from .validation.validator import validate_result
from .modules.market_risk.code import assess_market_risk
from .modules.supplier_risk.code import assess_supplier_risk
from .modules.legal_risk.code import assess_legal_risk
from .modules.financial_risk.code import assess_financial_risk
from .modules.seasonal_risk.code import assess_seasonal_risk

MODULE_WEIGHTS = {"market_risk": 0.25, "supplier_risk": 0.20, "legal_risk": 0.15, "financial_risk": 0.25, "seasonal_risk": 0.15}
MODULE_RUNNERS = {"market_risk": assess_market_risk, "supplier_risk": assess_supplier_risk, "legal_risk": assess_legal_risk, "financial_risk": assess_financial_risk, "seasonal_risk": assess_seasonal_risk}


class ProductRiskEngine:
    """Comprehensive product risk assessment engine."""
    ENGINE_NAME = "product_risk"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Execute full risk assessment pipeline."""
        start = time.monotonic()
        processed = validate_and_standardize(input_payload)
        if processed["status"] == "fail":
            return processed
        data = processed["data"]
        contract_payload = {"status": "success", "data": data, "meta": {}, "error": None}

        # Run each risk module
        module_results: dict[str, Any] = {}
        for name, runner in MODULE_RUNNERS.items():
            try:
                module_results[name] = runner(contract_payload)
            except Exception as exc:
                module_results[name] = {"status": "error", "data": None, "meta": {"module": name}, "error": str(exc)}

        # Aggregate composite score
        composite = self._compute_composite_score(module_results)
        classification = self._classify_risk(composite)
        top_risks = self._identify_top_risks(module_results)

        elapsed = time.monotonic() - start
        output = format_output(self.ENGINE_NAME, module_results, composite, classification, top_risks, data, elapsed)
        v = validate_result(output)
        if not v["valid"]:
            return {"status": "fail", "data": None, "meta": {"engine": self.ENGINE_NAME, "confidence": 0, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": {"reason": v["reason"]}}
        return output

    def _compute_composite_score(self, results: dict[str, Any]) -> float:
        """Weighted average of individual module risk scores."""
        total_w, w_sum = 0.0, 0.0
        for name, weight in MODULE_WEIGHTS.items():
            r = results.get(name, {})
            if r.get("status") != "success":
                continue
            rd = r.get("data") or {}
            score = rd.get("composite_risk_score", rd.get("risk_score", 0.5))
            w_sum += score * weight
            total_w += weight
        return round(w_sum / total_w, 3) if total_w > 0 else 0.5

    @staticmethod
    def _classify_risk(score: float) -> str:
        if score < 0.20: return "low"
        if score < 0.40: return "moderate"
        if score < 0.60: return "elevated"
        if score < 0.80: return "high"
        return "critical"

    @staticmethod
    def _identify_top_risks(results: dict[str, Any], max_n: int = 5) -> list[dict[str, Any]]:
        """Extract highest-severity risks across all modules."""
        risks = []
        for name, r in results.items():
            if r.get("status") != "success":
                risks.append({"module": name, "risk": f"{name} failed", "severity": "unknown", "score": 0.5})
                continue
            rd = r.get("data") or {}
            risks.append({
                "module": name,
                "risk": rd.get("classification", name),
                "severity": rd.get("risk_level", "unknown"),
                "score": rd.get("composite_risk_score", rd.get("risk_score", 0.0)),
            })
        risks.sort(key=lambda x: x["score"], reverse=True)
        return risks[:max_n]
