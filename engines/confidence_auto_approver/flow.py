"""Confidence Auto-Approver Engine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import os
import time
from dataclasses import asdict
from typing import Any

from .approver import (
    AutoApproveReport,
    auto_approve_pending,
)

logger = logging.getLogger(__name__)


_ENV_GATE = "SHOPAI_CONFIDENCE_AUTO_APPROVE"


def _env_enabled() -> bool:
    raw = os.environ.get(_ENV_GATE, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


class ConfidenceAutoApproverEngine:
    ENGINE_NAME = "confidence_auto_approver"

    def run(
        self, input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        start = time.monotonic()
        payload = self._safe_copy(input_payload)
        if payload is None:
            return self._fail("Input copy failed", 0.0)
        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)
        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        operator_yes = bool(data.get("confirmed", False))
        env_enabled = _env_enabled()
        # Triple-gate (same pattern as fleet_transfer_auto):
        # confirmed=True only when BOTH operator yes AND env
        # gate are set.
        confirmed = operator_yes and env_enabled

        try:
            min_sample = int(data.get("min_sample", 5))
        except (TypeError, ValueError):
            min_sample = 5
        try:
            min_positive_ratio = float(
                data.get("min_positive_ratio", 0.8),
            )
        except (TypeError, ValueError):
            min_positive_ratio = 0.8
        try:
            max_approvals = int(data.get("max_approvals", 50))
        except (TypeError, ValueError):
            max_approvals = 50

        store_id = data.get("store_id") or None

        report = auto_approve_pending(
            confirmed=confirmed,
            min_sample=max(1, min_sample),
            min_positive_ratio=max(
                0.0, min(1.0, min_positive_ratio),
            ),
            store_id=store_id,
            max_approvals=max(1, max_approvals),
        )

        return self._success(
            {
                "operator_confirmed": operator_yes,
                "env_gate_set": env_enabled,
                "confirmed": confirmed,
                "min_sample": report.min_sample,
                "min_positive_ratio": report.min_positive_ratio,
                "store_id": report.store_id,
                "pending_scanned": report.pending_scanned,
                "approved_count": report.approved_count,
                "skipped_count": report.skipped_count,
                "skip_reasons": dict(report.skip_reasons),
                "decisions": [
                    asdict(d) for d in report.decisions
                ],
                "next_action": _next_action(
                    report, operator_yes, env_enabled,
                ),
            },
            start,
        )

    @staticmethod
    def _safe_copy(payload: Any) -> Any:
        if payload is None:
            return {}
        try:
            return copy.deepcopy(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("input copy raised: %s", exc)
            return None

    def _success(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        return {
            "status": "success",
            "data": data,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "elapsed_seconds": round(
                    time.monotonic() - start, 3,
                ),
            },
            "error": None,
        }

    def _fail(
        self, reason: str, elapsed: float,
    ) -> dict[str, Any]:
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }


def _next_action(
    report: AutoApproveReport,
    operator_yes: bool,
    env_enabled: bool,
) -> str:
    if report.pending_scanned == 0:
        return (
            "No PENDING actions in queue. "
            "shopai approvals pending"
        )
    if not env_enabled:
        return (
            f"Env gate OFF. Enable: export "
            f"{_ENV_GATE}=1 (and re-run with --yes)."
        )
    if not operator_yes:
        ready = sum(
            1 for d in report.decisions if d.threshold_met
        )
        if ready == 0:
            return (
                f"{report.pending_scanned} pending; "
                "no engines have earned trust yet. Operator "
                "review still required."
            )
        return (
            f"{ready} action(s) would auto-approve. "
            "Add --yes to commit."
        )
    if report.approved_count == 0:
        return (
            f"Scanned {report.pending_scanned} but approved "
            "0. Engines haven't earned trust (raise --yes "
            "log: shopai approvals velocity)."
        )
    return (
        f"Auto-approved {report.approved_count} action(s). "
        "shopai cycle run --yes to execute."
    )
