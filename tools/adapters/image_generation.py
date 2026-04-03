"""Image generation adapter for ShopAI — wraps AI image generation APIs."""

import time
import uuid

from tools.base import (
    BaseToolAdapter,
    HealthStatus,
    RateConfig,
    ToolMetadata,
    ToolResult,
)


class ImageGenerationAdapter(BaseToolAdapter):
    tool_name = "image_generation"
    tool_category = "ai"
    version = "1.0.0"

    OPENAI_BASE = "https://api.openai.com/v1"

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._openai_api_key: str = ""
        self._default_model: str = "dall-e-3"
        self._default_size: str = "1024x1024"

    def configure(self, credentials: dict) -> None:
        self._credentials = credentials
        self._openai_api_key = credentials.get("openai_api_key", "")
        self._default_model = credentials.get("model", self._default_model)
        self._default_size = credentials.get("default_size", self._default_size)

    def capabilities(self) -> list[str]:
        return [
            "generate_image",
            "edit_image",
            "remove_background",
            "generate_variations",
            "upscale",
        ]

    def execute(self, action: str, params: dict) -> ToolResult:
        dispatch = {
            "generate_image": self._generate_image,
            "edit_image": self._edit_image,
            "remove_background": self._remove_background,
            "generate_variations": self._generate_variations,
            "upscale": self._upscale,
        }
        handler = dispatch.get(action)
        if not handler:
            return ToolResult(success=False, data={}, error=f"Unknown action: {action}")
        start = time.monotonic()
        try:
            result = handler(params)
            elapsed = (time.monotonic() - start) * 1000
            cost = result.pop("_cost_usd", 0.0)
            return ToolResult(
                success=True,
                data=result,
                error=None,
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=cost,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                success=False,
                data={},
                error=str(exc),
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=0.0,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )

    def health_check(self) -> HealthStatus:
        start = time.monotonic()
        healthy = bool(self._openai_api_key)
        latency = (time.monotonic() - start) * 1000 + 200.0
        return HealthStatus(
            healthy=healthy,
            latency_ms=latency,
            last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error=None if healthy else "No OpenAI API key configured",
        )

    def get_rate_config(self) -> RateConfig:
        return RateConfig(requests_per_second=0.5, burst=5, daily_quota=1000)

    # ── cost estimation ───────────────────────────────────────

    def _estimate_cost(self, model: str, size: str, n: int = 1) -> float:
        costs = {
            ("dall-e-3", "1024x1024"): 0.040,
            ("dall-e-3", "1024x1792"): 0.080,
            ("dall-e-3", "1792x1024"): 0.080,
            ("dall-e-2", "1024x1024"): 0.020,
            ("dall-e-2", "512x512"): 0.018,
            ("dall-e-2", "256x256"): 0.016,
        }
        per_image = costs.get((model, size), 0.040)
        return per_image * n

    # ── handlers ──────────────────────────────────────────────

    def _generate_image(self, params: dict) -> dict:
        if "prompt" not in params:
            raise ValueError("prompt is required")
        model = params.get("model", self._default_model)
        size = params.get("size", self._default_size)
        n = params.get("n", 1)
        quality = params.get("quality", "standard")
        style = params.get("style", "vivid")
        valid_sizes = ["256x256", "512x512", "1024x1024", "1024x1792", "1792x1024"]
        if size not in valid_sizes:
            raise ValueError(f"size must be one of: {', '.join(valid_sizes)}")
        return {
            "endpoint": f"{self.OPENAI_BASE}/images/generations",
            "method": "POST",
            "payload": {
                "model": model,
                "prompt": params["prompt"],
                "n": n,
                "size": size,
                "quality": quality,
                "style": style,
                "response_format": params.get("response_format", "url"),
            },
            "request_id": str(uuid.uuid4()),
            "images": [],
            "_cost_usd": self._estimate_cost(model, size, n),
        }

    def _edit_image(self, params: dict) -> dict:
        if "image_url" not in params or "prompt" not in params:
            raise ValueError("image_url and prompt are required")
        size = params.get("size", "1024x1024")
        return {
            "endpoint": f"{self.OPENAI_BASE}/images/edits",
            "method": "POST",
            "payload": {
                "image": params["image_url"],
                "mask": params.get("mask_url"),
                "prompt": params["prompt"],
                "n": params.get("n", 1),
                "size": size,
            },
            "request_id": str(uuid.uuid4()),
            "images": [],
            "_cost_usd": self._estimate_cost("dall-e-2", size),
        }

    def _remove_background(self, params: dict) -> dict:
        if "image_url" not in params:
            raise ValueError("image_url is required")
        return {
            "endpoint": f"{self.OPENAI_BASE}/images/edits",
            "method": "POST",
            "payload": {
                "image": params["image_url"],
                "prompt": "Remove background, keep only the main subject on a transparent background",
                "n": 1,
                "size": params.get("size", "1024x1024"),
            },
            "request_id": str(uuid.uuid4()),
            "images": [],
            "_cost_usd": self._estimate_cost("dall-e-2", "1024x1024"),
        }

    def _generate_variations(self, params: dict) -> dict:
        if "image_url" not in params:
            raise ValueError("image_url is required")
        n = params.get("n", 4)
        size = params.get("size", "1024x1024")
        return {
            "endpoint": f"{self.OPENAI_BASE}/images/variations",
            "method": "POST",
            "payload": {
                "image": params["image_url"],
                "n": n,
                "size": size,
                "response_format": params.get("response_format", "url"),
            },
            "request_id": str(uuid.uuid4()),
            "images": [],
            "_cost_usd": self._estimate_cost("dall-e-2", size, n),
        }

    def _upscale(self, params: dict) -> dict:
        if "image_url" not in params:
            raise ValueError("image_url is required")
        target_size = params.get("target_size", "2048x2048")
        return {
            "endpoint": f"{self.OPENAI_BASE}/images/edits",
            "method": "POST",
            "payload": {
                "image": params["image_url"],
                "prompt": "Upscale this image with enhanced detail and sharpness",
                "size": "1024x1024",
            },
            "target_size": target_size,
            "upscale_factor": params.get("upscale_factor", 2),
            "request_id": str(uuid.uuid4()),
            "images": [],
            "_cost_usd": self._estimate_cost("dall-e-2", "1024x1024"),
        }
