"""Outcome Backfill — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import os
import time
from dataclasses import asdict
from typing import Any

from .backfiller import BackfillReport, run_backfill

logger = logging.getLogger(__name__)


_ENV_GATE = "SHOPAI_OUTCOME_BACKFILL_ENABLED"


def _env_enabled() -> bool:
    raw = os.environ.get(_ENV_GATE, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


class OutcomeBackfillEngine:
    ENGINE_NAME = "outcome_backfill"

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
        confirmed = operator_yes and env_enabled

        try:
            min_age = float(data.get("min_age_hours", 24.0))
        except (TypeError, ValueError):
            min_age = 24.0
        try:
            grace = float(data.get("grace_hours", 168.0))
        except (TypeError, ValueError):
            grace = 168.0
        store_filter = str(data.get("store_id") or "")

        report = run_backfill(
            confirmed=confirmed,
            min_age_hours=min_age,
            grace_hours=grace,
            store_filter=store_filter,
            orders_override=data.get("orders"),
            executed_override=data.get("executed"),
        )

        return self._success(
            {
                "operator_confirmed": operator_yes,
                "env_gate_set": env_enabled,
                "confirmed": confirmed,
                "min_age_hours": report.min_age_hours,
                "grace_hours": report.grace_hours,
                "store_filter": store_filter,
                "total_executed_scanned":
                    report.total_executed_scanned,
                "already_recorded": report.already_recorded,
                "too_recent": report.too_recent,
                "positive_count": report.positive_count,
                "negative_count": report.negative_count,
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
    report: BackfillReport,
    operator_yes: bool,
    env_enabled: bool,
) -> str:
    if report.total_executed_scanned == 0:
        return (
            "No EXECUTED actions in queue. Fire a cycle "
            "first: shopai cycle run --yes"
        )
    if not env_enabled:
        return (
            f"Env gate OFF. Enable: export "
            f"{_ENV_GATE}=1 (and re-run with --yes)."
        )
    if not operator_yes:
        eligible = (
            report.positive_count + report.negative_count
        )
        return (
            f"{eligible} outcome(s) would be recorded "
            "(dry-run). Add --yes to commit."
        )
    recorded = sum(
        1 for d in report.decisions if d.recorded
    )
    return (
        f"Recorded {recorded} outcome(s) "
        f"(positive={report.positive_count}, "
        f"negative={report.negative_count}). "
        "Calibrator + auto-approver will pick up next cycle."
    )
