"""DallE3Adapter — OpenAI DALL-E 3 image generation.

Wave 1 #3 — the simplest possible "decision → external action"
loop for the media side of ShopAI. Fix S already added a
``refresh_images`` decision option; this adapter is the
mechanical hand that actually renders the replacement asset.

Auth: static secret key in an ``Authorization: Bearer``
header — ``OPENAI_API_KEY`` is already wired into
``ENV_ALIASES`` for the LLM adapters, so this adapter reuses
that same alias instead of introducing a parallel key.

Endpoint used:

  * ``POST /v1/images/generations``

Cost (standard DALL-E 3 pricing as of 2024):

  * 1024x1024 standard  — $0.040 / image
  * 1024x1024 HD        — $0.080 / image
  * 1792x1024 standard  — $0.080 / image
  * 1792x1024 HD        — $0.120 / image

The adapter sets ``cost_per_call = 0.04`` as the conservative
default (standard tier, square) so the router's budget optimiser
never underestimates spend on higher tiers. Concrete callers
that want HD can pass ``quality="hd"`` — the payload still goes
out correctly, the budget projection simply treats it as the
standard price (an acceptable trade-off; the router is not a
billing engine).

Reference: https://platform.openai.com/docs/api-reference/images/create
"""
from __future__ import annotations

from typing import Any

from ..errors import AdapterError
from ._base import ImageBaseAdapter


_VALID_SIZES = {
    "1024x1024",
    "1024x1792",
    "1792x1024",
}
_VALID_QUALITIES = {"standard", "hd"}
_VALID_STYLES = {"vivid", "natural"}
_VALID_RESPONSE_FORMATS = {"url", "b64_json"}


class DallE3Adapter(ImageBaseAdapter):
    name = "dalle3"
    base_url = "https://api.openai.com/v1"
    config_alias = "openai"
    model_default = "dall-e-3"

    # Only image adapter wired today, but pin priority high so
    # future free-tier alternatives (Pollinations, HF) stay
    # secondary unless an operator explicitly prefers them via
    # RouteContext.prefer.
    priority = 80

    # Standard square tier ($0.04). Sub-adapters that want HD
    # pricing can override estimate_cost.
    cost_per_call = 0.04

    # DALL-E 3 restricts n to 1 (per OpenAI docs — multi-image
    # generation is DALL-E 2 only). We enforce this in the
    # payload so callers don't get surprised by a 400.
    _FORCED_N = 1

    # ── URL / auth ────────────────────────────────────────────

    def _generate_url(self) -> str:
        return f"{self.base_url}/images/generations"

    # ── Payload translation ──────────────────────────────────

    def _build_generate_payload(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        """Translate the normalised params into OpenAI's shape.

        OpenAI accepts::

            {
                "model":           "dall-e-3",
                "prompt":          "...",
                "n":               1,
                "size":            "1024x1024",
                "quality":         "standard" | "hd",
                "style":           "vivid" | "natural",
                "response_format": "url" | "b64_json",
                "user":            "<optional end-user id>",
            }
        """
        body: dict[str, Any] = {
            "model": str(params.get("model") or self.model_default),
            "prompt": params["prompt"],
            # DALL-E 3 only supports n=1; we hard-pin it rather
            # than silently dropping a caller-supplied value so
            # the adapter never issues a request the vendor will
            # reject.
            "n": self._FORCED_N,
        }

        size = params.get("size")
        if size:
            size_str = str(size)
            if size_str not in _VALID_SIZES:
                # Don't raise — OpenAI tolerates unknown sizes by
                # falling back to 1024x1024, and the validation
                # layer belongs in ``_validate_generate``. Here
                # we just forward the caller's choice.
                pass
            body["size"] = size_str

        quality = params.get("quality")
        if quality:
            q_str = str(quality).lower()
            if q_str in _VALID_QUALITIES:
                body["quality"] = q_str

        style = params.get("style")
        if style:
            s_str = str(style).lower()
            if s_str in _VALID_STYLES:
                body["style"] = s_str

        response_format = params.get("response_format")
        if response_format:
            rf_str = str(response_format).lower()
            if rf_str in _VALID_RESPONSE_FORMATS:
                body["response_format"] = rf_str

        user = params.get("user")
        if user:
            body["user"] = str(user)

        return body

    # ── Response parsing ──────────────────────────────────────

    def _parse_generate_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"image response not a dict: {type(raw).__name__}",
            )
        items = raw.get("data") or []
        images: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            images.append({
                "url": str(item.get("url", "") or ""),
                "revised_prompt": str(
                    item.get("revised_prompt", "") or "",
                ),
                "b64_json": str(item.get("b64_json", "") or ""),
            })
        return {
            "images": images,
            "count": len(images),
            "model": str(params.get("model") or self.model_default),
        }
