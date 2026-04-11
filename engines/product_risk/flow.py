"""Product Risk Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Input → Market Risk Scorer → Supply Risk Scorer → Legal Risk Scorer →
  Financial Risk Scorer → Aggregate → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, market_data, suppliers}, meta, error}
  Output: {status, data: {risks: [{product_id, market_risk, supply_risk, legal_risk, financial_risk, overall}]}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .market_risk_scorer import score_market_risk
from .supply_risk_scorer import score_supply_risk
from .legal_risk_scorer import score_legal_risk
from .financial_risk_scorer import score_financial_risk
from .memory_reader import read_past_risks
from .memory_writer import write_risk_result


class ProductRiskEngine:
    """Product Risk Engine — orchestrator only, no logic."""

    ENGINE_NAME = "product_risk"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full risk assessment pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            ProductRiskOutput dict.
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

        products = data.get("products", [])
        market_data = data.get("market_data", [])
        suppliers = data.get("suppliers", [])

        if not products:
            return self._fail("Product list is required", 0.0)

        # ---- Stage 1: Read past risks (non-blocking) ----
        _past = read_past_risks(limit=5)

        # ---- Stage 2: Market Risk Scorer ----
        market_result = score_market_risk(
            products=products,
            market_data=market_data,
        )
        if market_result.get("status") == "error":
            return self._fail(
                f"Market risk scoring failed: {market_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        market_scores = market_result.get("scores", [])

        # ---- Stage 3: Supply Risk Scorer ----
        supply_result = score_supply_risk(
            products=products,
            suppliers=suppliers,
        )
        if supply_result.get("status") == "error":
            return self._fail(
                f"Supply risk scoring failed: {supply_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        supply_scores = supply_result.get("scores", [])

        # ---- Stage 4: Legal Risk Scorer ----
        legal_result = score_legal_risk(
            products=products,
        )
        if legal_result.get("status") == "error":
            return self._fail(
                f"Legal risk scoring failed: {legal_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        legal_scores = legal_result.get("scores", [])

        # ---- Stage 5: Financial Risk Scorer ----
        financial_result = score_financial_risk(
            products=products,
        )
        if financial_result.get("status") == "error":
            return self._fail(
                f"Financial risk scoring failed: {financial_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        financial_scores = financial_result.get("scores", [])

        # ---- Stage 6: Aggregate risks per product ----
        mkt_map = {s["product_id"]: s for s in market_scores}
        sup_map = {s["product_id"]: s for s in supply_scores}
        leg_map = {s["product_id"]: s for s in legal_scores}
        fin_map = {s["product_id"]: s for s in financial_scores}

        risks: list[dict[str, Any]] = []
        for product in products:
            pid = str(product.get("id", "unknown"))
            m = mkt_map.get(pid, {}).get("market_risk_score", 0.0)
            s = sup_map.get(pid, {}).get("supply_risk_score", 0.0)
            l = leg_map.get(pid, {}).get("legal_risk_score", 0.0)
            f = fin_map.get(pid, {}).get("financial_risk_score", 0.0)

            overall = round(m * 0.25 + s * 0.25 + l * 0.20 + f * 0.30, 3)

            if overall < 0.25:
                risk_level = "low"
            elif overall < 0.50:
                risk_level = "moderate"
            elif overall < 0.75:
                risk_level = "high"
            else:
                risk_level = "critical"

            risks.append({
                "product_id": pid,
                "market_risk": m,
                "supply_risk": s,
                "legal_risk": l,
                "financial_risk": f,
                "overall": overall,
                "risk_level": risk_level,
            })

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_risk_result(risks=risks)

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "risks": risks,
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
