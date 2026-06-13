"""Strategist Memory — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from . import store as store_mod

logger = logging.getLogger(__name__)


class StrategistMemoryEngine:
    ENGINE_NAME = "strategist_memory"

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

        action = str(data.get("action") or "recall").lower()

        if action == "record":
            return self._handle_record(data, start)
        if action == "stats":
            return self._handle_stats(data, start)
        if action == "recall":
            return self._handle_recall(data, start)
        if action == "summary":
            return self._handle_summary(data, start)
        if action == "update_outcome":
            return self._handle_update_outcome(data, start)
        return self._fail(
            f"unknown action {action!r}. Use record / "
            "recall / stats / summary / update_outcome.",
            time.monotonic() - start,
        )

    # ── Handlers ────────────────────────────────────────

    def _handle_record(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        try:
            priority = float(data.get("priority_score", 0.0))
        except (TypeError, ValueError):
            priority = 0.0
        wrote = store_mod.record(
            store_id=str(data.get("store_id") or ""),
            signal=str(data.get("signal") or ""),
            action=str(data.get("recommendation") or ""),
            drill_command=str(
                data.get("drill_command") or "",
            ),
            confidence=confidence,
            impact=str(data.get("impact") or "medium"),
            priority_score=priority,
            outcome=str(data.get("outcome") or "unknown"),
            notes=str(data.get("notes") or ""),
        )
        return self._success(
            {
                "action": "record",
                "wrote": wrote,
                "entry_count_after":
                    store_mod.entry_count(),
                "next_action": (
                    "Entry recorded."
                    if wrote
                    else "Not written (test env or invalid)."
                ),
            },
            start,
        )

    def _handle_stats(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        store_id = str(data.get("store_id") or "")
        signal = str(data.get("signal") or "")
        stats = store_mod.signal_stats(
            store_id=store_id, signal=signal,
        )
        return self._success(
            {
                "action": "stats",
                "store_id": store_id,
                "signal": signal,
                "stats": stats,
                "next_action": _stats_next_action(stats),
            },
            start,
        )

    def _handle_recall(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        store_id = str(data.get("store_id") or "")
        signal = str(data.get("signal") or "")
        try:
            k = int(data.get("k", 10))
        except (TypeError, ValueError):
            k = 10
        entries = store_mod.recall(
            store_id=store_id, signal=signal,
            k=max(1, k),
        )
        return self._success(
            {
                "action": "recall",
                "store_id": store_id,
                "signal": signal,
                "k": max(1, k),
                "entries": list(entries),
                "entry_count_total":
                    store_mod.entry_count(),
                "next_action": (
                    f"{len(entries)} entries returned."
                ),
            },
            start,
        )

    def _handle_summary(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        total = store_mod.entry_count()
        stores = store_mod.stores_with_entries()
        return self._success(
            {
                "action": "summary",
                "total_entries": total,
                "stores_with_entries": stores,
                "store_count": len(stores),
                "next_action": (
                    f"{total} entries across "
                    f"{len(stores)} store(s)."
                ),
            },
            start,
        )

    def _handle_update_outcome(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        try:
            idx = int(data.get("entry_index", -1))
        except (TypeError, ValueError):
            idx = -1
        outcome = str(data.get("outcome") or "")
        wrote = store_mod.update_outcome(
            entry_index=idx, outcome=outcome,
        )
        return self._success(
            {
                "action": "update_outcome",
                "wrote": wrote,
                "entry_index": idx,
                "outcome": outcome,
                "next_action": (
                    "Outcome updated."
                    if wrote
                    else (
                        "Update skipped (test-env or "
                        "invalid input)."
                    )
                ),
            },
            start,
        )

    # ── Internal ──────────────────────────────────────

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


def _stats_next_action(stats: dict[str, int]) -> str:
    total = stats.get("total", 0)
    if total == 0:
        return (
            "No matching entries. Memory accrues as cycles "
            "run + strategist records."
        )
    pos = stats.get("positive", 0)
    if pos == 0:
        return (
            f"{total} entries, none with confirmed positive "
            "outcome yet."
        )
    return (
        f"{pos}/{total} positive outcomes recorded. "
        "Future strategist runs can reason from this."
    )
