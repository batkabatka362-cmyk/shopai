"""Wholesale B2B Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.

Pipeline:
  Input → Tier Builder → Account Manager → Volume Calculator →
  Order Processor → Memory Writer → Output

Engine contract:
  Input:  {status, data: {products, accounts, pricing_config, order}, meta, error}
  Output: {status, data: {tiers, account_status, volume_discounts, processed_orders, credit_terms}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .tier_builder import build_tiers
from .account_manager import manage_accounts
from .volume_calculator import calculate_volume_discounts
from .order_processor import process_orders
from .memory_reader import read_past_wholesale
from .memory_writer import write_wholesale_result


class WholesaleB2bEngine:
    """Wholesale B2B Engine — orchestrator only, no logic."""

    ENGINE_NAME = "wholesale_b2b"

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
        accounts = data.get("accounts", [])
        pricing_config = data.get("pricing_config", {})
        order = data.get("order", {})

        if not products:
            return self._fail("Product list is required", 0.0)

        _past = read_past_wholesale(limit=5)

        # Stage 1: Tier Builder
        tier_result = build_tiers(products=products, pricing_config=pricing_config)
        if tier_result.get("status") == "error":
            return self._fail(f"Tier building failed: {tier_result.get('error', 'unknown')}", time.monotonic() - start)
        tiers = tier_result.get("tiers", [])

        # Stage 2: Account Manager
        acct_result = manage_accounts(accounts=accounts)
        if acct_result.get("status") == "error":
            return self._fail(f"Account management failed: {acct_result.get('error', 'unknown')}", time.monotonic() - start)
        account_status = acct_result.get("account_statuses", [])

        # Stage 3: Volume Calculator
        vol_result = calculate_volume_discounts(products=products, tiers=tiers, order=order)
        if vol_result.get("status") == "error":
            return self._fail(f"Volume calculation failed: {vol_result.get('error', 'unknown')}", time.monotonic() - start)
        volume_discounts = vol_result.get("volume_discounts", [])

        # Stage 4: Order Processor
        order_result = process_orders(order=order, volume_discounts=volume_discounts, account_statuses=account_status)
        if order_result.get("status") == "error":
            return self._fail(f"Order processing failed: {order_result.get('error', 'unknown')}", time.monotonic() - start)
        processed_orders = order_result.get("processed_orders", [])
        credit_terms = order_result.get("credit_terms", [])

        # Stage 5: Memory Writer (non-fatal)
        _write_result = write_wholesale_result(
            tiers=tiers, account_status=account_status,
            volume_discounts=volume_discounts, processed_orders=processed_orders,
            credit_terms=credit_terms,
        )

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "tiers": tiers,
                "account_status": account_status,
                "volume_discounts": volume_discounts,
                "processed_orders": processed_orders,
                "credit_terms": credit_terms,
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
            "status": "error", "data": None,
            "meta": {"engine": self.ENGINE_NAME, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
            "error": reason,
        }
