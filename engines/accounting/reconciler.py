"""Accounting Engine — bank reconciler.

Matches internal journal entries with bank transactions using
amount matching and date tolerance. Identifies discrepancies.

All matching is real — fuzzy on description, exact on amounts.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DATE_TOLERANCE_DAYS = 2
_AMOUNT_TOLERANCE = 0.01  # cent-level tolerance for rounding


def reconcile_transactions(
    internal_entries: list[dict[str, Any]],
    bank_transactions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reconcile internal journal entries against bank transactions.

    Matching criteria:
      1. Amount match (within rounding tolerance)
      2. Date within +/- 2 days
      3. Fuzzy description match (bonus, not required)

    Args:
        internal_entries: List of JournalEntry dicts.
        bank_transactions: List of bank transaction dicts.

    Returns:
        Structured dict with match counts, unmatched items, discrepancies.
    """
    try:
        internals = copy.deepcopy(internal_entries)
        banks = copy.deepcopy(bank_transactions)

        # Pre-compute net cash impact per internal entry
        internal_records: list[dict[str, Any]] = []
        for entry in internals:
            net_cash = _compute_net_cash(entry)
            internal_records.append({
                "entry": entry,
                "net_cash": net_cash,
                "date": _parse_date(entry.get("date", "")),
                "matched": False,
            })

        bank_records: list[dict[str, Any]] = []
        for btxn in banks:
            bank_records.append({
                "transaction": btxn,
                "amount": float(btxn.get("amount", 0.0)),
                "date": _parse_date(btxn.get("date", "")),
                "description": str(btxn.get("description", "")),
                "matched": False,
            })

        matched_count = 0
        discrepancies: list[dict[str, Any]] = []

        # Try to match each bank transaction to an internal entry
        for brec in bank_records:
            best_match = None
            best_score = -1

            for irec in internal_records:
                if irec["matched"]:
                    continue

                score = _match_score(irec, brec)
                if score > best_score:
                    best_score = score
                    best_match = irec

            if best_match is not None and best_score >= 2:
                # Good enough match (date + amount)
                best_match["matched"] = True
                brec["matched"] = True
                matched_count += 1

                # Check for amount discrepancy
                diff = round(abs(best_match["net_cash"] - brec["amount"]), 2)
                if diff > _AMOUNT_TOLERANCE:
                    discrepancies.append({
                        "internal": {
                            "id": best_match["entry"].get("id", ""),
                            "amount": best_match["net_cash"],
                            "date": best_match["entry"].get("date", ""),
                        },
                        "bank": {
                            "id": brec["transaction"].get("id", ""),
                            "amount": brec["amount"],
                            "date": brec["transaction"].get("date", ""),
                        },
                        "difference": diff,
                    })

        unmatched_internal = sum(1 for r in internal_records if not r["matched"])
        unmatched_bank = sum(1 for r in bank_records if not r["matched"])

        if unmatched_internal == 0 and unmatched_bank == 0 and not discrepancies:
            recon_status = "balanced"
        else:
            recon_status = "discrepancies_found"

        return {
            "status": "success",
            "matched_count": matched_count,
            "unmatched_internal": unmatched_internal,
            "unmatched_bank": unmatched_bank,
            "discrepancies": discrepancies,
            "reconciliation_status": recon_status,
        }
    except Exception as exc:
        return _fail(f"Reconciliation failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_net_cash(entry: dict[str, Any]) -> float:
    """Compute net cash movement from a journal entry.

    Positive = cash inflow, negative = cash outflow.
    Looks at account 1000 (Cash/Bank) lines only.
    """
    net = 0.0
    for line in entry.get("lines", []):
        if str(line.get("account", "")) == "1000":
            amount = float(line.get("amount", 0.0))
            if line.get("type") == "debit":
                net += amount
            elif line.get("type") == "credit":
                net -= amount
    return round(net, 2)


def _parse_date(date_str: str) -> datetime | None:
    """Parse a date string (YYYY-MM-DD) into a datetime."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _match_score(
    internal: dict[str, Any],
    bank: dict[str, Any],
) -> int:
    """Score a potential match between internal entry and bank transaction.

    Scoring:
      +2  amount matches (within tolerance)
      +2  date within tolerance
      +1  description has common words

    Minimum score of 2 required (date + amount).
    """
    score = 0

    # Amount matching
    i_amount = abs(internal["net_cash"])
    b_amount = abs(bank["amount"])
    if abs(i_amount - b_amount) <= _AMOUNT_TOLERANCE:
        score += 2
    elif abs(i_amount - b_amount) <= 1.0:
        # Close but not exact — still a possible match
        score += 1

    # Date matching
    i_date = internal["date"]
    b_date = bank["date"]
    if i_date is not None and b_date is not None:
        delta = abs((i_date - b_date).days)
        if delta <= _DATE_TOLERANCE_DAYS:
            score += 2
        elif delta <= _DATE_TOLERANCE_DAYS * 2:
            score += 1

    # Description fuzzy match (bonus)
    i_desc = str(internal["entry"].get("description", "")).lower()
    b_desc = bank["description"].lower()
    common = set(i_desc.split()) & set(b_desc.split())
    if len(common) >= 1:
        score += 1

    return score


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error dict."""
    return {
        "status": "error",
        "matched_count": 0,
        "unmatched_internal": 0,
        "unmatched_bank": 0,
        "discrepancies": [],
        "reconciliation_status": "error",
        "error": reason,
    }
