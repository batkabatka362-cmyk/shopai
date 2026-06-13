"""Capability Browser Engine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .searcher import (
    BrowseReport,
    goal_suggestions,
    search_capabilities,
)

logger = logging.getLogger(__name__)


class CapabilityBrowserEngine:
    ENGINE_NAME = "capability_browser"

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

        query = str(data.get("query") or "")
        kind_filter = str(data.get("kind") or "")
        tag_filter = str(data.get("tag") or "")
        try:
            top = int(data.get("top", 20))
        except (TypeError, ValueError):
            top = 20

        report = search_capabilities(
            query=query,
            kind_filter=kind_filter,
            tag_filter=tag_filter,
            top=max(0, top),
        )

        return self._success(
            {
                "query": report.query,
                "kind_filter": report.kind_filter,
                "tag_filter": report.tag_filter,
                "total_registry": report.total_registry,
                "hit_count": len(report.hits),
                "hits": [asdict(h) for h in report.hits],
                "goal_suggestions": goal_suggestions(),
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


def _next_action(report: BrowseReport) -> str:
    if report.total_registry == 0:
        return (
            "Registry not bootstrapped. Run: python -c "
            "'from core.capability_registry.bootstrap "
            "import ensure_registered; ensure_registered()'"
        )
    if not report.hits and report.query:
        return (
            f"No matches for query {report.query!r}. Try a "
            "broader phrase or run without --query."
        )
    if report.hits and report.query:
        top = report.hits[0]
        cli_hint = ""
        if top.cli_commands:
            cli_hint = (
                f" Run: shopai {top.cli_commands[0]}"
            )
        return (
            f"Top match: {top.name}.{cli_hint}"
        )
    return (
        f"{len(report.hits)} capabilities returned. "
        "Use --query to narrow."
    )
