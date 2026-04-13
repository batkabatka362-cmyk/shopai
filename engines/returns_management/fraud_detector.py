"""Returns Management Engine — fraud detector.

Detects return fraud patterns by analyzing return frequency,
value anomalies, and customer behavior signals.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Fraud thresholds
# ---------------------------------------------------------------------------

_HIGH_FREQUENCY_THRESHOLD = 3      # Returns per customer in batch
_HIGH_VALUE_THRESHOLD = 500.0      # Single return value
_SERIAL_RETURNER_THRESHOLD = 5     # Total returns flagged


def detect_fraud(
    returns: list[dict[str, Any]],
    processed: list[dict[str, Any]],
) -> dict[str, Any]:
    """Detect fraud patterns in return requests.

    Args:
        returns: List of original ReturnRequest dicts.
        processed: List of ProcessedReturn dicts from return_processor.

    Returns:
        Structured dict with fraud flags.
    """
    try:
        returns = copy.deepcopy(returns)
        processed = copy.deepcopy(processed)

        # Build customer return counts and values
        customer_returns: dict[str, list[dict[str, Any]]] = {}
        for idx, ret in enumerate(returns):
            cid = str(ret.get("customer_id", f"anon_{idx}"))
            proc = processed[idx] if idx < len(processed) else {}
            customer_returns.setdefault(cid, []).append({
                "return": ret,
                "processed": proc,
            })

        fraud_flags: list[dict[str, Any]] = []

        for cid, cust_rets in customer_returns.items():
            indicators: list[str] = []
            risk_score = 0.0

            # High frequency check
            if len(cust_rets) >= _HIGH_FREQUENCY_THRESHOLD:
                indicators.append(f"high_frequency ({len(cust_rets)} returns)")
                risk_score += 0.3

            # High value check
            for cr in cust_rets:
                refund = float(cr["processed"].get("refund_amount", 0.0))
                if refund >= _HIGH_VALUE_THRESHOLD:
                    indicators.append(f"high_value_return (${refund:.2f})")
                    risk_score += 0.2
                    break

            # All-items-returned pattern
            all_eligible = all(
                cr["processed"].get("eligible", False) for cr in cust_rets
            )
            if len(cust_rets) >= 2 and all_eligible:
                indicators.append("all_returns_eligible")
                risk_score += 0.15

            # Vague reason pattern
            vague_reasons = sum(
                1 for cr in cust_rets
                if len(str(cr["return"].get("reason", ""))) < 10
            )
            if vague_reasons > len(cust_rets) * 0.5:
                indicators.append("vague_reasons")
                risk_score += 0.1

            risk_score = round(min(risk_score, 1.0), 2)

            if indicators:
                # Determine recommended action
                if risk_score >= 0.6:
                    action = "block_future_returns"
                elif risk_score >= 0.3:
                    action = "manual_review"
                else:
                    action = "monitor"

                for cr in cust_rets:
                    ret_id = str(cr["processed"].get("return_id", ""))
                    fraud_flags.append({
                        "return_id": ret_id,
                        "customer_id": cid,
                        "risk_score": risk_score,
                        "fraud_indicators": indicators,
                        "recommended_action": action,
                    })

        return {
            "status": "success",
            "fraud_flags": fraud_flags,
        }
    except Exception as exc:
        return {
            "status": "error",
            "fraud_flags": [],
            "error": f"Fraud detection failed: {exc}",
        }
