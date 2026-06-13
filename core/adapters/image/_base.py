"""ImageBaseAdapter — shared HTTP base for image generators.

Concrete adapters (DALL-E 3 today; Stable Diffusion, Replicate,
Pollinations, Hugging Face later) inherit this class and override
only the vendor-specific bits:

  * ``base_url``                   — vendor API root
  * ``config_alias``               — ``ENV_ALIASES`` key for the
                                     API credential
  * ``_generate_url``              — the POST endpoint that
                                     creates an image
  * ``_auth_headers``              — vendor-specific auth header
  * ``_build_generate_payload``    — normalised params → vendor
                                     body
  * ``_parse_generate_response``   — vendor response → normalised
                                     result dict

The base handles:

  * Capability dispatch for ``Capability.GENERATE_IMAGE``
  * Required-field validation (``prompt``; optional ``size`` /
    ``quality`` / ``n``)
  * HTTP POST execution with typed error mapping
  * AdapterResult assembly (cost per image is multiplied by
    ``n`` so the router's budget optimiser sees the true spend)

Normalised request shape (vendor-agnostic):

    {
        "prompt":   "A watercolour hero banner of ...",   # required
        "size":     "1024x1024",                           # optional
        "quality":  "standard",                            # optional
        "n":        1,                                      # optional
        "style":    "vivid",                                # optional
        "response_format": "url",                           # optional
    }

Normalised response shape:

    {
        "images": [
            {
                "url":            "https://...",
                "revised_prompt": "Vendor-rewritten prompt",
                "b64_json":       "",          # populated when
                                               # response_format=b64
            },
            ...
        ],
        "count":  1,
        "model":  "dall-e-3",
    }

Scope note: this Wave 1 surface covers *generation* only.
Image editing, variations, masks, and upscaling are out of scope
for the first image adapter and belong in a later wave.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from ..base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
)
from .._per_store_credentials import (
    resolve_per_store as _resolve_per_store,
)
from ..config import get_config
from ..errors import (
    AdapterAuthError,
    AdapterError,
    AdapterNotConfigured,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
)

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

logger = get_logger("adapters.image")


_DEFAULT_TIMEOUT = 60.0  # image gen is slow; generous by design


class ImageBaseAdapter(BaseAdapter):
    """Abstract base for every image-generation adapter.

    Concrete adapters MUST set:

      * ``name``         — registry key (e.g. ``"dalle3"``)
      * ``base_url``     — vendor API root
      * ``config_alias`` — env alias for the API key

    They MAY override:

      * ``priority``      — router preference (0-100)
      * ``cost_per_call`` — average $/image (DALL-E 3 standard is
                            $0.04 at 1024x1024; HD is $0.08)
      * ``timeout``       — per-request timeout in seconds
      * ``model_default`` — default vendor model name
    """

    category = AdapterCategory.IMAGE_GEN
    capabilities = {Capability.GENERATE_IMAGE}

    base_url: str = ""
    config_alias: str = ""
    timeout: float = _DEFAULT_TIMEOUT
    model_default: str = ""

    cost_per_call: float = 0.0
    priority: int = 50

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        if not self.base_url or not self.config_alias:
            return False
        return bool((_resolve_per_store(self.config_alias) or get_config().get(self.config_alias)))

    def _api_key(self) -> str:
        key = (_resolve_per_store(self.config_alias) or get_config().get(self.config_alias))
        if not key:
            env = get_config().env_var_for(self.config_alias)
            raise AdapterNotConfigured(
                self.name,
                f"missing API key (set ${env or self.config_alias})",
            )
        return key

    # ── Cost estimation ────────────────────────────────────────

    def estimate_cost(
        self, capability: Capability, params: dict[str, Any],
    ) -> float:
        """Cost scales with ``n`` images. Subclasses that charge
        per-pixel or per-quality tier override this."""
        try:
            n = int(params.get("n", 1) or 1)
        except (TypeError, ValueError):
            n = 1
        return float(self.cost_per_call) * max(n, 1)

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability != Capability.GENERATE_IMAGE:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        self._validate_generate(params)
        url = self._generate_url()
        body = self._build_generate_payload(params)
        raw = self._http_post(url, body, headers=self._auth_headers())
        normalised = self._parse_generate_response(raw, params)

        n_images = max(len(normalised.get("images") or []), 1)
        cost = float(self.cost_per_call) * n_images

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data=normalised,
            cost_usd=cost,
            model=str(normalised.get("model", "") or self.model_default),
            raw=raw,
        )

    # ── Validation ─────────────────────────────────────────────

    def _validate_generate(self, params: dict[str, Any]) -> None:
        prompt = params.get("prompt")
        if not prompt or not isinstance(prompt, str):
            raise AdapterValidationError(
                self.name,
                "'prompt' is required for image generation",
            )
        if len(prompt) > 4_000:
            raise AdapterValidationError(
                self.name,
                f"'prompt' too long ({len(prompt)} chars; max 4000)",
            )
        n = params.get("n")
        if n is not None:
            try:
                n_int = int(n)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name, f"'n' must be an integer (got {n!r})",
                ) from exc
            if n_int < 1 or n_int > 10:
                raise AdapterValidationError(
                    self.name,
                    f"'n' must be between 1 and 10 (got {n_int})",
                )

    # ── Vendor-specific hooks (override in subclasses) ────────

    def _generate_url(self) -> str:
        raise NotImplementedError(
            f"{type(self).__name__}._generate_url must be implemented",
        )

    def _auth_headers(self) -> dict[str, str]:
        """Default: Bearer token. Override when the vendor uses
        a different scheme."""
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _build_generate_payload(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{type(self).__name__}._build_generate_payload must be implemented",
        )

    def _parse_generate_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{type(self).__name__}._parse_generate_response must be implemented",
        )

    # ── HTTP ───────────────────────────────────────────────────

    def _http_post(
        self,
        url: str,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> Any:
        """W962-65: delegates to shared core.adapters._http_retry
        which implements 3x retry on 429/5xx/transient transport
        errors with exponential backoff + Retry-After honoring."""
        from core.adapters._http_retry import http_retry
        return http_retry(
            lambda: _requests.post(
                url, json=body, headers=headers,
                timeout=self.timeout,
            ),
            adapter_name=self.name,
            timeout=self.timeout,
        )
