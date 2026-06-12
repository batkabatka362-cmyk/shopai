"""BrandIdentityComposerEngine -- Pattern Q envelope.

On submit_to_queue=True enqueues a single 'apply_brand_
identity' approval action carrying the brief + chosen
candidates. Dispatcher (W963-149 family) iterates the
approved payload + pushes:
  - palette + typography -> Shopify theme settings
  - first logo concept -> Files upload + assign as
    shop logo
  - hero candidates -> Files upload
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from .composer import (
    BrandBrief,
    build_brief,
    brief_to_markdown,
)

logger = logging.getLogger(__name__)


class BrandIdentityComposerEngine:
    ENGINE_NAME = "brand_identity_composer"

    def run(
        self,
        input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        start = time.monotonic()
        payload = self._safe_copy(input_payload)
        if payload is None:
            return self._fail(
                "Input copy failed", 0.0,
            )
        if not isinstance(payload, dict):
            return self._fail(
                "Input must be a dict", 0.0,
            )
        if payload.get("status") == "fail":
            return self._fail(
                payload.get(
                    "error", "Upstream failure",
                ), 0.0,
            )
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        store_id = str(data.get("store_id") or "")
        if not store_id:
            return self._fail(
                "store_id required (per-store "
                "brand composition)", 0.0,
            )
        niche = str(data.get("niche") or "")
        target_market = str(
            data.get("target_market") or "",
        )
        logo_count = int(
            data.get("logo_concept_count", 2) or 2,
        )
        hero_count = int(
            data.get("hero_count", 3) or 3,
        )
        submit = bool(
            data.get("submit_to_queue", False),
        )

        try:
            brief = build_brief(
                store_id,
                niche=niche,
                target_market=target_market,
                logo_concept_count=logo_count,
                hero_count=hero_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "build_brief raised: %s", exc,
            )
            return self._fail(
                f"build_brief raised: {exc}", 0.0,
            )

        md = brief_to_markdown(brief)
        action_id = ""
        if submit and brief.is_complete:
            try:
                action_id = self._submit_to_queue(
                    brief=brief, md=md,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "queue submit raised: %s", exc,
                )

        out = {
            "store_id": store_id,
            "niche": brief.niche,
            "is_complete": brief.is_complete,
            "brand_name_suggestions": (
                brief.brand_name_suggestions
            ),
            "tagline": brief.tagline,
            "voice": brief.voice,
            "palette": (
                {
                    "primary": brief.palette.primary,
                    "secondary": (
                        brief.palette.secondary
                    ),
                    "accent": brief.palette.accent,
                    "text": brief.palette.text,
                    "background": (
                        brief.palette.background
                    ),
                }
                if brief.palette else None
            ),
            "typography": (
                {
                    "heading": brief.typography.heading,
                    "body": brief.typography.body,
                }
                if brief.typography else None
            ),
            "logo_concepts": brief.logo_concepts,
            "hero_candidates": brief.hero_candidates,
            "notes": brief.notes,
            "report_markdown": md,
            "approval_action_id": action_id,
        }
        return self._success(out, start)

    @staticmethod
    def _submit_to_queue(
        *, brief: BrandBrief, md: str,
    ) -> str:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
        action = queue.enqueue(
            engine="brand_identity_composer",
            action_type="apply_brand_identity",
            capability="SHOPIFY_UPDATE_ONLINE_STORE",
            params={
                "niche": brief.niche,
                "palette": (
                    {
                        "primary": (
                            brief.palette.primary
                        ),
                        "secondary": (
                            brief.palette.secondary
                        ),
                        "accent": brief.palette.accent,
                        "text": brief.palette.text,
                        "background": (
                            brief.palette.background
                        ),
                    }
                    if brief.palette else {}
                ),
                "typography": (
                    {
                        "heading": (
                            brief.typography.heading
                        ),
                        "body": (
                            brief.typography.body
                        ),
                    }
                    if brief.typography else {}
                ),
                "logo_concept": (
                    brief.logo_concepts[0]
                    if brief.logo_concepts else {}
                ),
                "hero_candidates": (
                    brief.hero_candidates
                ),
                "tagline": brief.tagline,
                "voice": brief.voice,
                "brand_names": (
                    brief.brand_name_suggestions
                ),
            },
            narrative=md,
            confidence=0.8,
            store_id=brief.store_id,
        )
        return getattr(action, "id", "") or ""

    @staticmethod
    def _safe_copy(payload: Any) -> Any:
        if payload is None:
            return {}
        try:
            return copy.deepcopy(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "input copy raised: %s", exc,
            )
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
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(),
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
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(),
                ),
                "elapsed_seconds": round(
                    elapsed, 3,
                ),
            },
            "error": reason,
        }
