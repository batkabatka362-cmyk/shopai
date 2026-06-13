"""Confidence Calibrator — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .calibrator import (
    CalibrationReport,
    band_thresholds,
    calibrate,
)

logger = logging.getLogger(__name__)


class ConfidenceCalibratorEngine:
    ENGINE_NAME = "confidence_calibrator"

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

        store_id = data.get("store_id") or None
        try:
            min_sample = int(data.get("min_sample", 5))
        except (TypeError, ValueError):
            min_sample = 5

        engines_arg = data.get("engines")
        if not isinstance(engines_arg, list):
            engines_arg = None

        report = calibrate(
            store_id=store_id,
            min_sample=max(1, min_sample),
            engines=engines_arg,
        )

        return self._success(
            {
                "store_id": report.store_id,
                "min_sample": report.min_sample,
                "total_engines": report.total_engines,
                "band_counts": dict(report.band_counts),
                "calibrations": [
                    asdict(c) for c in report.calibrations
                ],
                "band_thresholds": band_thresholds(),
                "next_action": _next_action(report),
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


def _next_action(report: CalibrationReport) -> str:
    if report.total_engines == 0:
        return (
            "No engines with executed history in queue. "
            "Fire a cycle first: shopai cycle run --yes"
        )
    blocked = report.band_counts.get("blocked", 0)
    relaxed = report.band_counts.get("relaxed", 0)
    if blocked > 0:
        return (
            f"{blocked} engine(s) BLOCKED -- positive ratio "
            "below 60%. Investigate: "
            "shopai engine alerts"
        )
    if relaxed > 0:
        return (
            f"{relaxed} engine(s) earned RELAXED trust "
            "(>=95%). Lower auto-approve threshold for those."
        )
    return (
        f"{report.total_engines} engine(s) calibrated. "
        "Use thresholds in shopai auto-approve."
    )
