"""Warmup Plan Engine — Pattern Q envelope.

Wraps the schedule module in the canonical
{status, data, meta, error} shape. Actions:

  full    -- complete 30-day plan
  day     -- single day drill (data.day = 1..30)
  phases  -- 4-phase summary
"""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .schedule import generate_plan, get_day, phase_summary

logger = logging.getLogger(__name__)


class WarmupPlanEngine:
    ENGINE_NAME = "warmup_plan"

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

        action = (data.get("action") or "full").lower()
        niche = data.get("niche")

        if action == "full":
            plan = generate_plan(niche=niche)
            return self._success(
                {
                    "action": "full",
                    "niche": (niche or "general").lower(),
                    "phase_summary": phase_summary(),
                    "days": [asdict(d) for d in plan],
                    "day_count": len(plan),
                    "next_action": _full_next_action(plan),
                },
                start,
            )

        if action == "day":
            try:
                day = int(data.get("day", 1))
            except (TypeError, ValueError):
                return self._fail(
                    "data.day must be an integer 1..30",
                    time.monotonic() - start,
                )
            wd = get_day(day, niche=niche)
            if wd is None:
                return self._fail(
                    f"day must be 1..30 (got {day})",
                    time.monotonic() - start,
                )
            return self._success(
                {
                    "action": "day",
                    "niche": (niche or "general").lower(),
                    "day": asdict(wd),
                    "next_action": _day_next_action(wd),
                },
                start,
            )

        if action == "phases":
            return self._success(
                {
                    "action": "phases",
                    "phase_summary": phase_summary(),
                    "next_action": (
                        "Run a single day: shopai warmup-plan "
                        "--day 1"
                    ),
                },
                start,
            )

        return self._fail(
            f"unknown action '{action}'. Use full / day / "
            "phases.",
            time.monotonic() - start,
        )

    # ── Internal ──────────────────────────────────────────

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


def _full_next_action(plan) -> str:
    return (
        f"30-day plan ready ({len(plan)} days). "
        "Run day 1: shopai warmup-plan --day 1"
    )


def _day_next_action(day) -> str:
    next_day = day.day + 1 if day.day < 30 else None
    if next_day:
        return (
            f"Run day {next_day}: shopai warmup-plan "
            f"--day {next_day}"
        )
    return (
        "Plan complete. Schedule recurring cycle: "
        "shopai cycle schedule"
    )
