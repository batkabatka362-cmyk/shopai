"""Anomaly Auto-Quarantine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import os
import time
from dataclasses import asdict
from typing import Any

from .quarantiner import (
    AnomalyQuarantineReport,
    default_pause_engines,
    run_quarantine,
)

logger = logging.getLogger(__name__)


_ENV_GATE = "SHOPAI_ANOMALY_AUTO_QUARANTINE"


def _env_enabled() -> bool:
    raw = os.environ.get(_ENV_GATE, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


class AnomalyAutoQuarantineEngine:
    ENGINE_NAME = "anomaly_auto_quarantine"

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
            min_deviation = float(
                data.get("min_deviation", 4.0),
            )
        except (TypeError, ValueError):
            min_deviation = 4.0

        pause_engines = data.get("pause_engines")
        if not isinstance(pause_engines, list):
            pause_engines = None

        report = run_quarantine(
            confirmed=confirmed,
            min_deviation=min_deviation,
            pause_engines=pause_engines,
            alerts=data.get("alerts"),
        )

        return self._success(
            {
                "operator_confirmed": operator_yes,
                "env_gate_set": env_enabled,
                "confirmed": confirmed,
                "min_deviation": report.min_deviation,
                "pause_engines": list(report.pause_engines),
                "alerts_scanned": report.alerts_scanned,
                "eligible_alerts": report.eligible_alerts,
                "total_pauses_added":
                    report.total_pauses_added,
                "skip_count": report.skip_count,
                "skip_reasons": dict(report.skip_reasons),
                "decisions": [
                    asdict(d) for d in report.decisions
                ],
                "default_pause_engines": list(
                    default_pause_engines(),
                ),
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
    report: AnomalyQuarantineReport,
    operator_yes: bool,
    env_enabled: bool,
) -> str:
    if report.alerts_scanned == 0:
        return (
            "No anomaly alerts above threshold "
            f"{report.min_deviation:.1f} MAD. Try lower "
            "via --min-deviation 3.0."
        )
    if not env_enabled:
        return (
            f"Env gate OFF. Enable: export "
            f"{_ENV_GATE}=1 (and re-run with --yes)."
        )
    if not operator_yes:
        return (
            f"{report.eligible_alerts} outlier(s) would be "
            "quarantined. Add --yes to commit."
        )
    if report.total_pauses_added == 0:
        return (
            "0 pauses applied. Either already paused or "
            "substrate failed. Check shopai approvals "
            "quarantine."
        )
    return (
        f"Auto-quarantined: {report.total_pauses_added} "
        "(engine, store) pause(s) added. Release: "
        "shopai approvals quarantine --release-alert ENGINE "
        "--release-alert-store STORE"
    )
