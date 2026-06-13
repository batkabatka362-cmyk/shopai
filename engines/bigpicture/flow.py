"""Bigpicture Engine — Pattern Q envelope.

Composes today + earnings-by-engine + warmup-plan into a
single multi-section envelope. Each section is wrapped in
try/except so a missing substrate degrades to "skipped"
rather than crashing the whole view.

The "overall_verdict" mirrors today_brief's bands
(critical > warn > ok > skipped), with an upgrade:
earning_count >= 1 promotes a warn back to ok because the
operator is making money even if some signals are loud.
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def _today_section(day, niche, store_id) -> dict[str, Any]:
    try:
        from engines.today_brief import TodayBriefEngine
        result = TodayBriefEngine().run({
            "data": {
                "day": day, "niche": niche,
                "store_id": store_id,
            },
        })
        return {
            "ok": result.get("status") == "success",
            "data": result.get("data") or {},
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("today_brief section raised: %s", exc)
        return {"ok": False, "data": {}, "error": str(exc)}


def _earnings_section(store_id) -> dict[str, Any]:
    try:
        from engines.earnings_by_engine import (
            EarningsByEngineEngine,
        )
        result = EarningsByEngineEngine().run({
            "data": {
                "window_hours": 168.0,
                "store_id": store_id,
            },
        })
        return {
            "ok": result.get("status") == "success",
            "data": result.get("data") or {},
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("earnings section raised: %s", exc)
        return {"ok": False, "data": {}, "error": str(exc)}


def _warmup_section(day, niche) -> dict[str, Any]:
    try:
        from engines.warmup_plan.schedule import get_day
        wd = get_day(day, niche=niche)
        if wd is None:
            return {"ok": False, "data": {}}
        from dataclasses import asdict
        return {"ok": True, "data": asdict(wd)}
    except Exception as exc:  # noqa: BLE001
        logger.debug("warmup section raised: %s", exc)
        return {"ok": False, "data": {}, "error": str(exc)}


def _compute_overall_verdict(
    sections: dict[str, dict[str, Any]],
) -> str:
    """Pick the worst signal, then upgrade if any engine is
    earning."""
    today = (sections.get("today") or {}).get("data") or {}
    today_verdict = today.get("verdict") or "skipped"

    earnings = (
        sections.get("earnings") or {}
    ).get("data") or {}
    earning_count = int(earnings.get("earning_count", 0))

    # Earning trumps warn (but not critical).
    if today_verdict == "warn" and earning_count >= 1:
        return "ok"
    return today_verdict


def _compute_top_action(
    sections: dict[str, dict[str, Any]],
) -> str:
    """Return the most useful drill hint."""
    today = (sections.get("today") or {}).get("data") or {}
    nxt = today.get("next_action") or ""
    if nxt:
        return nxt
    earnings = (
        sections.get("earnings") or {}
    ).get("data") or {}
    nxt = earnings.get("next_action") or ""
    if nxt:
        return nxt
    warmup = (sections.get("warmup") or {}).get("data") or {}
    if warmup:
        return (
            f"Day {warmup.get('day')}: "
            f"{warmup.get('intent', '')}"
        )
    return ""


class BigpictureEngine:
    ENGINE_NAME = "bigpicture"

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

        try:
            day = int(data.get("day", 1))
        except (TypeError, ValueError):
            day = 1
        day = max(1, min(day, 30))

        niche = data.get("niche")
        store_id = data.get("store_id")

        sections = {
            "today": _today_section(day, niche, store_id),
            "earnings": _earnings_section(store_id),
            "warmup": _warmup_section(day, niche),
        }
        verdict = _compute_overall_verdict(sections)
        top_action = _compute_top_action(sections)

        return self._success(
            {
                "day": day,
                "niche": (niche or "general").lower(),
                "store_id": store_id,
                "verdict": verdict,
                "sections": sections,
                "next_action": top_action,
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
