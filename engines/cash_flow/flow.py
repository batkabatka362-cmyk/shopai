"""Cash Flow Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Validate → Memory Reader → Cash Position Tracker → Payment Term Manager →
  Runway Calculator → Forecast Generator → Alert Generator →
  Memory Writer → Output

Engine contract:
  Input:  {status, data: {current_balance, inflows, outflows, receivables, payables, monthly_fixed_costs, avg_monthly_revenue, period}, meta, error}
  Output: {status, data: {cash_position, payment_terms, runway, forecast, alerts}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .cash_position_tracker import track_cash_position
from .payment_term_manager import manage_payment_terms
from .runway_calculator import calculate_runway
from .forecast_generator import generate_forecast
from .alert_generator import generate_alerts
from .memory_reader import read_cash_history
from .memory_writer import write_cash_record


class CashFlowEngine:
    """Cash Flow Engine — orchestrator only, no logic."""

    ENGINE_NAME = "cash_flow"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full cash flow pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            CashFlowOutput dict.
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

        current_balance = float(data.get("current_balance", 0.0))
        inflows = data.get("inflows", [])
        outflows = data.get("outflows", [])
        receivables = data.get("receivables", [])
        payables = data.get("payables", [])
        monthly_fixed_costs = float(data.get("monthly_fixed_costs", 0.0))
        avg_monthly_revenue = float(data.get("avg_monthly_revenue", 0.0))
        period = data.get("period", {})

        if not isinstance(period, dict):
            period = {}

        # ---- Stage 1: Read past cash history (non-blocking) ----
        _past = read_cash_history(limit=5)

        # ---- Stage 2: Cash Position Tracker ----
        position_result = track_cash_position(
            current_balance=current_balance,
            inflows=inflows,
            outflows=outflows,
            period=period,
        )
        if position_result.get("status") == "error":
            return self._fail(
                f"Cash position tracking failed: {position_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 3: Payment Term Manager ----
        terms_result = manage_payment_terms(
            receivables=receivables,
            payables=payables,
        )
        if terms_result.get("status") == "error":
            return self._fail(
                f"Payment term management failed: {terms_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 4: Runway Calculator ----
        runway_result = calculate_runway(
            current_balance=current_balance,
            monthly_fixed_costs=monthly_fixed_costs,
            avg_monthly_revenue=avg_monthly_revenue,
        )
        if runway_result.get("status") == "error":
            return self._fail(
                f"Runway calculation failed: {runway_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 5: Forecast Generator ----
        forecast_result = generate_forecast(
            cash_position=position_result,
            inflows=inflows,
            outflows=outflows,
            receivables=receivables,
            payables=payables,
        )
        if forecast_result.get("status") == "error":
            return self._fail(
                f"Forecast generation failed: {forecast_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 6: Alert Generator ----
        alert_result = generate_alerts(
            runway=runway_result,
            cash_position=position_result,
            payment_terms=terms_result,
        )
        if alert_result.get("status") == "error":
            return self._fail(
                f"Alert generation failed: {alert_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        alerts = alert_result.get("alerts", [])

        # ---- Stage 7: Memory Writer (non-fatal) ----
        _write_result = write_cash_record(
            cash_position=position_result,
            payment_terms=terms_result,
            runway=runway_result,
            forecast=forecast_result,
            alerts=alerts,
        )

        # ---- Stage 8: Assemble output ----
        elapsed = time.monotonic() - start

        cash_position: dict[str, Any] = {
            "current_balance": position_result.get("current_balance", 0.0),
            "period_inflows": position_result.get("period_inflows", 0.0),
            "period_outflows": position_result.get("period_outflows", 0.0),
            "net_change": position_result.get("net_change", 0.0),
            "projected_end_balance": position_result.get("projected_end_balance", 0.0),
        }

        payment_terms: dict[str, Any] = {
            "total_receivables": terms_result.get("total_receivables", 0.0),
            "total_payables": terms_result.get("total_payables", 0.0),
            "net_receivables": terms_result.get("net_receivables", 0.0),
            "aging_receivables": terms_result.get("aging_receivables", {}),
            "aging_payables": terms_result.get("aging_payables", {}),
            "overdue_count": terms_result.get("overdue_count", 0),
        }

        runway: dict[str, Any] = {
            "monthly_burn_rate": runway_result.get("monthly_burn_rate", 0.0),
            "net_monthly_burn": runway_result.get("net_monthly_burn", 0.0),
            "months_of_runway": runway_result.get("months_of_runway", 0.0),
            "runway_risk": runway_result.get("runway_risk", "unknown"),
            "zero_cash_date": runway_result.get("zero_cash_date"),
        }

        forecast: dict[str, Any] = {
            "30_day": forecast_result.get("30_day", {}),
            "60_day": forecast_result.get("60_day", {}),
            "90_day": forecast_result.get("90_day", {}),
            "trend": forecast_result.get("trend", "unknown"),
        }

        return {
            "status": "success",
            "data": {
                "cash_position": cash_position,
                "payment_terms": payment_terms,
                "runway": runway,
                "forecast": forecast,
                "alerts": alerts,
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
