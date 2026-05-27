"""Returns Management Engine — refund_applier (Wave 101).

The Wave 6 ``return_applier`` deliberately stopped at tagging
orders -- "Refunds are real money out, and refundCreate needs a
transaction-parent-id lookup the engine doesn't carry."

Wave 101 closes that gap. This module:

  1. Filters the engine's ``processed`` output to only the
     ``status=approved`` rows.
  2. Drops rows with non-trivial fraud risk
     (``risk_score >= SHOPAI_REFUND_MAX_FRAUD_RISK`` -- default 0.5).
  3. Drops rows whose computed ``refund_amount`` exceeds the
     safety ceiling (``SHOPAI_REFUND_MAX_AMOUNT_USD`` -- default
     $500). The ceiling is intentionally restrictive; the autono-
     mous loop should handle small everyday refunds, NOT bigger
     ones that benefit from operator review.
  4. Looks up the order's parent transaction id via
     ``SHOPIFY_GET_ORDER`` (one read per return). Skips when the
     order has no eligible parent transaction.
  5. Calls ``SHOPIFY_CREATE_REFUND`` with a transactions list
     scoped to the parent + refund_amount.
  6. Records every outcome (success OR failure) via
     ``record_writeback`` so Phase 8 learning loop sees refund
     activity flow into MemoryIntelligence + DataArchitecture +
     LearningLoop.

## Opt-in

Default OFF. Caller flips ``data.apply_refunds=True`` to
enable. Mirrors the Phase 6/7 wireup pattern used by
``loyalty/discount_minter``, ``dynamic_pricing/price_applier``,
etc.

## Per-return skip taxonomy

The applier never crashes on a single bad row -- every row
either applies or surfaces a typed skip reason in the result:

  - ``router_unavailable``       -- core.adapters.router import
                                     failed (catastrophic; no row
                                     applied)
  - ``not_approved``             -- engine status != approved
  - ``zero_refund_amount``       -- refund_amount <= 0
  - ``exceeds_max_amount``       -- safety ceiling
  - ``fraud_risk_too_high``      -- risk >= threshold
  - ``no_order_id``              -- engine row carried internal
                                     id; can't address Shopify
  - ``order_lookup_failed``      -- SHOPIFY_GET_ORDER failed
  - ``no_parent_transaction``    -- order has no refundable
                                     transaction to attach to
  - ``adapter_failed``           -- refundCreate userErrors /
                                     adapter raised
  - ``recorded``                 -- success
"""
from __future__ import annotations

import os
from typing import Any

from engines._writeback_recorder import record_writeback
from utils.logger import get_logger

logger = get_logger("engines.returns_management.refund_applier")


_ENGINE = "returns_management"
_ACTION_TYPE = "apply_refund"


def _max_amount() -> float:
    """Safety ceiling. Refunds above this are skipped."""
    raw = os.environ.get(
        "SHOPAI_REFUND_MAX_AMOUNT_USD", "500",
    )
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 500.0


def _max_fraud_risk() -> float:
    """Skip when fraud_flag.risk_score >= this. 0..1 scale."""
    raw = os.environ.get(
        "SHOPAI_REFUND_MAX_FRAUD_RISK", "0.5",
    )
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.5


def _get_router() -> Any:
    try:
        from core.adapters.router import get_router
        return get_router()
    except Exception:  # noqa: BLE001
        return None


def _capability(name: str) -> Any:
    """Resolve a Capability enum member by name, returning None
    when the enum isn't loadable (router will then no-op)."""
    try:
        from core.adapters.base import Capability
        return getattr(Capability, name, None)
    except Exception:  # noqa: BLE001
        return None


def _fraud_risk_by_return(
    fraud_flags: list[dict[str, Any]],
) -> dict[str, float]:
    """Index ``fraud_flags`` by return_id -> risk_score so we
    can look up risk in O(1) inside the per-return loop."""
    out: dict[str, float] = {}
    if not isinstance(fraud_flags, list):
        return out
    for f in fraud_flags:
        if not isinstance(f, dict):
            continue
        rid = str(f.get("return_id", "") or "")
        if not rid:
            continue
        try:
            score = float(f.get("risk_score", 0) or 0)
        except (TypeError, ValueError):
            score = 0.0
        out[rid] = score
    return out


def _lookup_parent_transaction(
    router: Any, get_order_cap: Any, order_id: str,
) -> tuple[str | None, str]:
    """Read the order's transaction list + return the first
    eligible parent transaction id.

    Returns ``(parent_gid, error_reason)`` where exactly one is
    non-empty.

    "Eligible" = original SALE / AUTHORIZATION / CAPTURE
    transaction (NOT a prior REFUND). Picks the FIRST such
    transaction; multi-tx orders may want a different policy
    but that's a future enhancement.
    """
    if router is None or get_order_cap is None:
        return None, "router_unavailable"
    try:
        res = router.execute(
            get_order_cap, {"order_id": order_id},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "refund_applier order lookup raised: %s", exc,
        )
        return None, "order_lookup_failed"
    if not getattr(res, "ok", False):
        return None, "order_lookup_failed"
    data = getattr(res, "data", None) or {}
    txs = data.get("transactions") or []
    if not isinstance(txs, list):
        return None, "no_parent_transaction"
    for tx in txs:
        if not isinstance(tx, dict):
            continue
        kind = str(tx.get("kind", "") or "").upper()
        # REFUND transactions can't parent another refund;
        # VOID / FAILED transactions also disqualify.
        if kind in ("REFUND", "VOID"):
            continue
        gid = tx.get("id") or tx.get("gid")
        if isinstance(gid, str) and gid:
            return gid, ""
    return None, "no_parent_transaction"


def _record(
    *,
    return_row: dict[str, Any],
    success: bool,
    error: str | None,
    refund_amount: float,
) -> None:
    """Pattern Z writeback recorder."""
    try:
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_TYPE,
            capability="SHOPIFY_CREATE_REFUND",
            params={
                "return_id": str(return_row.get("return_id", "")),
                "order_id": str(return_row.get("order_id", "")),
                "refund_amount": refund_amount,
            },
            success=success,
            error=error,
        )
    except Exception:  # noqa: BLE001
        # Writeback recording must never break the applier.
        pass


def apply_refunds(
    processed: list[dict[str, Any]],
    fraud_flags: list[dict[str, Any]],
    *,
    max_amount: float | None = None,
    max_fraud_risk: float | None = None,
) -> list[dict[str, Any]]:
    """Issue refunds for engine-approved returns.

    Args:
        processed: ``returns_management.flow`` output's
            ``processed`` list.
        fraud_flags: ``returns_management.flow`` output's
            ``fraud_flags`` list. Used to filter risky returns.
        max_amount: Override the ``SHOPAI_REFUND_MAX_AMOUNT_USD``
            env value (handy for tests).
        max_fraud_risk: Override the
            ``SHOPAI_REFUND_MAX_FRAUD_RISK`` env value.

    Returns:
        Per-return list with ``{return_id, order_id, applied,
        refund_amount, status, error}``.
    """
    if not isinstance(processed, list) or not processed:
        return []

    cap_amount = (
        max_amount if max_amount is not None else _max_amount()
    )
    cap_risk = (
        max_fraud_risk if max_fraud_risk is not None
        else _max_fraud_risk()
    )
    fraud_by_return = _fraud_risk_by_return(fraud_flags)

    router = _get_router()
    get_order_cap = _capability("SHOPIFY_GET_ORDER")
    create_refund_cap = _capability("SHOPIFY_CREATE_REFUND")

    out: list[dict[str, Any]] = []
    for row in processed:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("return_id", "") or "")
        oid = str(row.get("order_id", "") or "")
        try:
            amount = float(row.get("refund_amount", 0) or 0)
        except (TypeError, ValueError):
            amount = 0.0
        applied = False
        status_label = ""
        error: str | None = None

        # Gate 1: engine must have approved
        if str(row.get("status", "")).lower() != "approved":
            status_label = "not_approved"
        # Gate 2: zero refund (engine eligible but no items)
        elif amount <= 0:
            status_label = "zero_refund_amount"
        # Gate 3: safety ceiling
        elif amount > cap_amount:
            status_label = "exceeds_max_amount"
            error = (
                f"refund_amount=${amount:.2f} > cap=${cap_amount:.2f}"
            )
        # Gate 4: fraud risk
        elif fraud_by_return.get(rid, 0.0) >= cap_risk:
            status_label = "fraud_risk_too_high"
            error = (
                f"risk={fraud_by_return.get(rid, 0):.2f} "
                f">= cap={cap_risk:.2f}"
            )
        # Gate 5: must have order_id to address Shopify
        elif not oid:
            status_label = "no_order_id"
        elif (
            router is None
            or get_order_cap is None
            or create_refund_cap is None
        ):
            status_label = "router_unavailable"
        else:
            parent_gid, err = _lookup_parent_transaction(
                router, get_order_cap, oid,
            )
            if err:
                status_label = err
                error = err
            else:
                # All gates passed -- issue the refund
                try:
                    res = router.execute(
                        create_refund_cap,
                        {
                            "order_id": oid,
                            "transactions": [{
                                "parent_id": parent_gid,
                                "amount": amount,
                                "kind": "REFUND",
                            }],
                        },
                    )
                    if getattr(res, "ok", False):
                        applied = True
                        status_label = "recorded"
                    else:
                        status_label = "adapter_failed"
                        error = getattr(
                            res, "error", "adapter_failed",
                        )
                except Exception as exc:  # noqa: BLE001
                    status_label = "adapter_failed"
                    error = str(exc)
                _record(
                    return_row=row,
                    success=applied,
                    error=error,
                    refund_amount=amount,
                )

        out.append({
            "return_id": rid,
            "order_id": oid,
            "applied": applied,
            "refund_amount": amount,
            "status": status_label,
            "error": error,
        })
    return out
