"""Affiliate Links Engine — Pattern Q wrapper.

Single 'generate' action — given a partner identity + shop URL,
return a stable ref code + the trackable URL.
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from .code_generator import build_link, generate_code

logger = logging.getLogger(__name__)


class AffiliateLinksEngine:
    ENGINE_NAME = "affiliate_links"

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

        # Identity resolution: prefer email, fall back to name.
        partner_email = (
            data.get("partner_email") or ""
        ).strip()
        partner_name = (data.get("partner_name") or "").strip()
        identity = partner_email or partner_name

        if not identity:
            return self._fail(
                "partner_email or partner_name is required",
                time.monotonic() - start,
            )

        shop_url = (data.get("shop_url") or "").strip()
        if not shop_url:
            return self._fail(
                "shop_url is required (e.g. "
                "store.myshopify.com)",
                time.monotonic() - start,
            )

        code = generate_code(identity)
        link = build_link(shop_url, code)

        return self._success(
            {
                "partner_email": partner_email,
                "partner_name": partner_name,
                "shop_url": shop_url,
                "code": code,
                "link": link,
                "next_action": (
                    "Share the link with the partner. Track "
                    "via order.note_attributes when ?ref= "
                    "cookie persists to checkout. Commissions "
                    "settle via shopai engine run affiliate."
                ),
            },
            start,
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
