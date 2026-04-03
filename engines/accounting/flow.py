"""Accounting Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Validate → Memory Reader → Transaction Categorizer → Ledger Writer →
  Balance Calculator → Reconciler (if bank data) → Report Generator →
  Memory Writer → Output

Engine contract:
  Input:  {status, data: {transactions, report_type, period, bank_transactions?}, meta, error}
  Output: {status, data: {journal_entries, balances, reconciliation, report}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .transaction_categorizer import categorize_transaction
from .ledger_writer import write_journal_entries
from .balance_calculator import calculate_balances
from .reconciler import reconcile_transactions
from .report_generator import generate_report
from .memory_reader import read_ledger_state
from .memory_writer import write_accounting_record


class AccountingEngine:
    """Accounting Engine — orchestrator only, no logic."""

    ENGINE_NAME = "accounting"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full accounting pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            AccountingOutput dict.
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

        transactions = data.get("transactions", [])
        report_type = str(data.get("report_type", "profit_and_loss"))
        period = data.get("period", {})
        bank_transactions = data.get("bank_transactions", [])

        if not transactions:
            return self._fail("Transaction list is required", 0.0)

        if not period:
            return self._fail("Period is required", 0.0)

        # ---- Stage 1: Read past ledger state (non-blocking) ----
        past_state = read_ledger_state(period=period)
        existing_balances = past_state.get("balances", {}) or None

        # ---- Stage 2: Categorize & journalize each transaction ----
        all_entries: list[dict[str, Any]] = []

        for txn in transactions:
            # Stage 2a: Categorize
            cat_result = categorize_transaction(transaction=txn)
            if cat_result.get("status") == "error":
                return self._fail(
                    f"Categorization failed for {txn.get('id', '?')}: "
                    f"{cat_result.get('error', 'unknown')}",
                    time.monotonic() - start,
                )

            # Stage 2b: Write journal entries
            je_result = write_journal_entries(
                transaction=txn,
                category=cat_result,
            )
            if je_result.get("status") == "error":
                return self._fail(
                    f"Journal entry failed for {txn.get('id', '?')}: "
                    f"{je_result.get('error', 'unknown')}",
                    time.monotonic() - start,
                )

            if not je_result.get("balanced", False):
                return self._fail(
                    f"Unbalanced journal entry for {txn.get('id', '?')}: "
                    f"debits != credits",
                    time.monotonic() - start,
                )

            all_entries.extend(je_result.get("entries", []))

        # ---- Stage 3: Calculate balances ----
        balance_result = calculate_balances(
            journal_entries=all_entries,
            existing_balances=existing_balances,
        )
        if balance_result.get("status") == "error":
            return self._fail(
                f"Balance calculation failed: {balance_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )

        # ---- Stage 4: Reconcile with bank (if bank data provided) ----
        recon_result = None
        if bank_transactions:
            recon_result = reconcile_transactions(
                internal_entries=all_entries,
                bank_transactions=bank_transactions,
            )
            if recon_result.get("status") == "error":
                return self._fail(
                    f"Reconciliation failed: {recon_result.get('error', 'unknown')}",
                    time.monotonic() - start,
                )

        # ---- Stage 5: Generate report ----
        report_result = generate_report(
            balances=balance_result,
            transactions=transactions,
            report_type=report_type,
            period=period,
        )
        if report_result.get("status") == "error":
            return self._fail(
                f"Report generation failed: {report_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        report_data = report_result.get("report", {})

        # ---- Stage 6: Memory writer (non-fatal) ----
        _write_result = write_accounting_record(
            journal_entries=all_entries,
            balances=balance_result,
            report=report_data,
            reconciliation=recon_result,
        )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "journal_entries": all_entries,
                "balances": {
                    "balances": balance_result.get("balances", {}),
                    "total_debits": balance_result.get("total_debits", 0.0),
                    "total_credits": balance_result.get("total_credits", 0.0),
                    "is_balanced": balance_result.get("is_balanced", False),
                },
                "reconciliation": recon_result,
                "report": report_data,
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
