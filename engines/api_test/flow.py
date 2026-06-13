"""ApiTestEngine -- Pattern Q envelope around run_api_test."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .health_check import run_api_test

logger = logging.getLogger(__name__)


class ApiTestEngine:
    ENGINE_NAME = "api_test"

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
        only = str(data.get("only_alias") or "").strip()

        try:
            report = run_api_test(only_alias=only)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "api_test: run raised: %s", exc,
            )
            return self._fail(f"run raised: {exc}", 0.0)

        # asdict() omits @property fields so we splice
        # `cls` (ok / fail / skipped) into each result dict
        # manually -- the renderer + JSON consumers both
        # depend on it.
        results_out = []
        for r in report.results:
            d = asdict(r)
            d["cls"] = r.cls
            results_out.append(d)
        out = {
            "headline": report.headline,
            "next_action": report.next_action,
            "ok_count": report.ok_count,
            "fail_count": report.fail_count,
            "skipped_count": report.skipped_count,
            "configured_count": report.configured_count,
            "all_configured_ok": report.all_configured_ok,
            "results": results_out,
        }
        return self._success(out, start)

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
