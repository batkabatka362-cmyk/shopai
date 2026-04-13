"""RemoveBgAdapter — Remove.bg background removal API.

Remove.bg is the industry standard for automated background
removal. One API call produces a clean product image with
transparent background — essential for e-commerce listings.

This adapter implements OPTIMIZE_IMAGE only (no generation).

Auth: ``X-Api-Key`` header.
Free tier: 1 free preview/month, 50 free API calls on signup.
Pricing: from $0.20/image (standard quality).

Reference: https://www.remove.bg/api
"""
from __future__ import annotations

import base64
from typing import Any

from ..base import AdapterCategory, AdapterResult, Capability
from ..config import get_config
from ..errors import (
    AdapterError,
    AdapterNotConfigured,
    AdapterValidationError,
)
from ._base import ImageBaseAdapter

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False


class RemoveBgAdapter(ImageBaseAdapter):
    name = "removebg"
    base_url = "https://api.remove.bg/v1.0"
    config_alias = "removebg"
    model_default = "removebg"

    capabilities = {Capability.OPTIMIZE_IMAGE}

    priority = 85  # Best-in-class for background removal
    cost_per_call = 0.20

    # ── Override _execute for OPTIMIZE_IMAGE only ─────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability != Capability.OPTIMIZE_IMAGE:
            raise AdapterValidationError(
                self.name,
                f"unsupported capability: {capability.value} "
                f"(only OPTIMIZE_IMAGE is supported)",
            )

        image_b64 = params.get("image_base64") or params.get("image")
        image_url = params.get("image_url") or params.get("url")

        if not image_b64 and not image_url:
            raise AdapterValidationError(
                self.name,
                "'image_base64' or 'image_url' is required",
            )

        url = f"{self.base_url}/removebg"
        body: dict[str, Any] = {
            "size": params.get("size", "auto"),
            "type": params.get("type", "auto"),
            "format": params.get("format", "png"),
        }
        if image_b64:
            body["image_file_b64"] = image_b64
        elif image_url:
            body["image_url"] = image_url

        if params.get("bg_color"):
            body["bg_color"] = params["bg_color"]

        headers = {
            "X-Api-Key": self._api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        raw = self._http_post(url, body, headers=headers)

        result_b64 = ""
        if isinstance(raw, dict):
            data = raw.get("data", {})
            result_b64 = data.get("result_b64", "") if isinstance(data, dict) else ""

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "action": "remove_background",
                "image_base64": result_b64,
                "has_result": bool(result_b64),
                "format": params.get("format", "png"),
            },
            raw=raw,
        )

    # ── Not used (OPTIMIZE_IMAGE only, no generation) ─────────

    def _generate_url(self) -> str:
        return ""

    def _build_generate_payload(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        return {}

    def _parse_generate_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        return {}
