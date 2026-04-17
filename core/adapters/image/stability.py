"""StabilityAdapter — Stability AI image generation & editing.

Stability AI powers Stable Diffusion — the leading open-source
image model. The REST API adds capabilities DALL-E doesn't have:

  * **Image generation** — text-to-image via SDXL / SD3
  * **Upscale**          — 4x resolution enhancement
  * **Background removal** — clean product photography

This adapter exposes both GENERATE_IMAGE and OPTIMIZE_IMAGE
capabilities so the router can dispatch image editing tasks here.

Auth: Bearer token.
Pricing: credit-based (~$0.01-0.07/image depending on model).

Reference: https://platform.stability.ai/docs/api-reference
"""
from __future__ import annotations

import base64
from typing import Any

from ..base import AdapterResult, Capability
from ..errors import AdapterError, AdapterValidationError
from ._base import ImageBaseAdapter


class StabilityAdapter(ImageBaseAdapter):
    name = "stability_ai"
    base_url = "https://api.stability.ai/v2beta"
    config_alias = "stability_ai"
    model_default = "sd3-large"

    capabilities = {Capability.GENERATE_IMAGE, Capability.OPTIMIZE_IMAGE}

    priority = 70  # Below DALL-E 3 (80)
    cost_per_call = 0.03  # ~3 credits per generation

    # ── URL / auth ────────────────────────────────────────────

    def _generate_url(self) -> str:
        return f"{self.base_url}/stable-image/generate/sd3"

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Accept": "application/json",
        }

    # ── Capability dispatch (override for dual caps) ──────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability == Capability.OPTIMIZE_IMAGE:
            return self._do_optimize(capability, params)
        return super()._execute(capability, params)

    # ── Generate payload ──────────────────────────────────────

    def _build_generate_payload(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "prompt": params["prompt"],
            "model": str(params.get("model") or self.model_default),
            "output_format": params.get("output_format", "png"),
        }

        if params.get("negative_prompt"):
            body["negative_prompt"] = params["negative_prompt"]
        if params.get("aspect_ratio"):
            body["aspect_ratio"] = params["aspect_ratio"]
        if params.get("seed") is not None:
            body["seed"] = int(params["seed"])

        return body

    def _parse_generate_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"image response not a dict: {type(raw).__name__}",
            )

        image_b64 = raw.get("image", "")
        images = []
        if image_b64:
            images.append({
                "url": "",
                "revised_prompt": "",
                "b64_json": image_b64,
            })

        return {
            "images": images,
            "count": len(images),
            "model": str(params.get("model") or self.model_default),
            "seed": raw.get("seed", 0),
        }

    # ── Optimize (upscale / background removal) ───────────────

    def _do_optimize(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        action = params.get("action", "upscale")

        if action == "remove_background":
            return self._do_remove_background(capability, params)
        elif action == "upscale":
            return self._do_upscale(capability, params)
        else:
            raise AdapterValidationError(
                self.name,
                f"unsupported optimize action: {action!r} "
                f"(use 'upscale' or 'remove_background')",
            )

    def _do_upscale(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        image_b64 = params.get("image_base64") or params.get("image")
        if not image_b64:
            raise AdapterValidationError(
                self.name, "'image_base64' is required for upscale",
            )

        url = f"{self.base_url}/stable-image/upscale/fast"
        body = {"image": image_b64, "output_format": "png"}
        raw = self._http_post(url, body, headers=self._auth_headers())

        result_b64 = raw.get("image", "") if isinstance(raw, dict) else ""

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "action": "upscale",
                "image_base64": result_b64,
                "has_result": bool(result_b64),
            },
            raw=raw,
        )

    def _do_remove_background(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        image_b64 = params.get("image_base64") or params.get("image")
        if not image_b64:
            raise AdapterValidationError(
                self.name,
                "'image_base64' is required for background removal",
            )

        url = f"{self.base_url}/stable-image/edit/remove-background"
        body = {"image": image_b64, "output_format": "png"}
        raw = self._http_post(url, body, headers=self._auth_headers())

        result_b64 = raw.get("image", "") if isinstance(raw, dict) else ""

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "action": "remove_background",
                "image_base64": result_b64,
                "has_result": bool(result_b64),
            },
            raw=raw,
        )
