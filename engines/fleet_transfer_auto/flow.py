"""Fleet Transfer Auto Engine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import os
import time
from dataclasses import asdict
from typing import Any

from .applier import FleetTransferReport, apply_fleet_transfers

logger = logging.getLogger(__name__)


_ENV_GATE = "SHOPAI_FLEET_TRANSFER_AUTO"


def _env_enabled() -> bool:
    raw = os.environ.get(_ENV_GATE, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


class FleetTransferAutoEngine:
    ENGINE_NAME = "fleet_transfer_auto"

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
        # Triple gate: operator --yes flag + env gate.
        # confirmed=True only when BOTH are true; otherwise
        # treat as dry-run regardless of operator intent.
        confirmed = operator_yes and env_enabled

        try:
            min_positive = int(data.get("min_positive", 3))
        except (TypeError, ValueError):
            min_positive = 3
        try:
            max_per_pair = int(data.get("max_per_pair", 5))
        except (TypeError, ValueError):
            max_per_pair = 5
        try:
            top_k = int(data.get("top_k", 50))
        except (TypeError, ValueError):
            top_k = 50
        allow_cross_niche = bool(
            data.get("allow_cross_niche", False),
        )

        report = apply_fleet_transfers(
            confirmed=confirmed,
            min_positive=max(1, min_positive),
            max_per_pair=max(1, max_per_pair),
            allow_cross_niche=allow_cross_niche,
            top_k=max(1, top_k),
        )

        return self._success(
            {
                "operator_confirmed": operator_yes,
                "env_gate_set": env_enabled,
                "confirmed": confirmed,
                "min_positive": report.min_positive,
                "max_per_pair": report.max_per_pair,
                "allow_cross_niche": report.allow_cross_niche,
                "candidates_scanned": report.candidates_scanned,
                "enqueued_count": report.enqueued_count,
                "skip_count": report.skip_count,
                "skip_reasons": dict(report.skip_reasons),
                "applied": [
                    asdict(a) for a in report.applied
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
    report: FleetTransferReport,
    operator_yes: bool,
    env_enabled: bool,
) -> str:
    if report.candidates_scanned == 0:
        return (
            "No transfer candidates. Each source store needs "
            f">={report.min_positive} positive outcomes per "
            "(engine, action_type) for the scanner to lift it."
        )
    if not env_enabled:
        return (
            "Env gate OFF. Enable: export "
            f"{_ENV_GATE}=1 (and re-run with --yes)."
        )
    if not operator_yes:
        return (
            f"{report.candidates_scanned} candidate(s); dry-run. "
            "Add --yes to enqueue."
        )
    if report.enqueued_count == 0:
        return (
            f"Scanned {report.candidates_scanned} but enqueued "
            f"0 (all duplicates or pair-cap hit). Raise "
            "--max-per-pair to widen."
        )
    return (
        f"Enqueued {report.enqueued_count} transfer(s) as "
        "PENDING. Review: shopai approvals pending --sort priority"
    )
