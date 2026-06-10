"""ImageCdnBaseAdapter — shared HTTP base for image CDN / optimiser
services.

Concrete adapters (ImageKit today; Cloudinary, imgix, Bunny
Optimizer later) inherit this class and override only the
vendor-specific bits:

  * ``base_url``                   — vendor API root
  * ``config_alias``               — ``ENV_ALIASES`` key for the
                                     API credential (private key
                                     for vendors that split
                                     pub/priv, like ImageKit)
  * ``_optimize_url``              — endpoint that uploads/
                                     optimises and returns a
                                     CDN-hosted URL
  * ``_auth_headers``              — vendor-specific auth header
  * ``_build_optimize_payload``    — normalised params → vendor
                                     body (dict or list-of-tuples
                                     for form-encoded vendors)
  * ``_parse_optimize_response``   — vendor response → normalised
                                     result dict

The base handles:

  * Capability dispatch for ``Capability.OPTIMIZE_IMAGE``
  * Required-field validation (``source_url`` + ``file_name``;
    ``source_url`` must be http(s)://)
  * HTTP POST execution with typed error mapping
  * AdapterResult assembly with optional size-based cost
    scaling so the budget advisor can attribute CDN spend to
    the right adapter

Normalised request shape (vendor-agnostic):

    {
        "source_url":  "https://cdn.shop.com/img/p1.jpg",   # required
        "file_name":   "p1.jpg",                             # required
        "folder":      "/products",                          # optional
        "tags":        ["product", "wave1"],                 # optional
        "transformation_pre": "w-1600,q-80,f-auto",          # optional
        "use_unique_filename": True,                         # optional
        "overwrite":   False,                                # optional
    }

Normalised response shape:

    {
        "url":           "https://ik.imagekit.io/.../p1.jpg",
        "file_id":       "abc123",
        "name":          "p1.jpg",
        "size":          48234,
        "width":         1600,
        "height":        900,
        "file_type":     "image",
        "thumbnail_url": "https://.../p1_thumb.jpg",
    }

Scope note: Wave 1 covers *upload + transformation* only.
Listing files, folders, signed URLs, purging the CDN, and
webhook management are out of scope.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

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

logger = get_logger("adapters.image_cdn")


_DEFAULT_TIMEOUT = 60.0  # upload + remote fetch can be slow
_MAX_FILE_NAME_LEN = 1024


class ImageCdnBaseAdapter(BaseAdapter):
    """Abstract base for every image-CDN adapter.

    Concrete adapters MUST set:

      * ``name``         — registry key (e.g. ``"imagekit"``)
      * ``base_url``     — vendor API root (may be dynamic —
                           override as a ``@property``)
      * ``config_alias`` — env alias for the private API key

    They MAY override:

      * ``priority``      — router preference (0-100)
      * ``cost_per_call`` — flat $/optimisation (most CDN free
                            tiers are $0 until a quota trips)
      * ``timeout``       — per-request timeout in seconds
    """

    category = AdapterCategory.IMAGE_CDN
    capabilities = {Capability.OPTIMIZE_IMAGE}

    base_url: str = ""
    config_alias: str = ""
    timeout: float = _DEFAULT_TIMEOUT

    cost_per_call: float = 0.0
    priority: int = 50

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        if not self.config_alias:
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
        """Flat cost per optimisation. Subclasses with per-MB or
        per-transformation pricing override this."""
        return float(self.cost_per_call)

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability != Capability.OPTIMIZE_IMAGE:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        self._validate_optimize(params)
        url = self._optimize_url()
        body = self._build_optimize_payload(params)
        raw = self._http_post(url, body, headers=self._auth_headers())
        normalised = self._parse_optimize_response(raw, params)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data=normalised,
            cost_usd=float(self.cost_per_call),
            raw=raw,
        )

    # ── Validation ─────────────────────────────────────────────

    def _validate_optimize(self, params: dict[str, Any]) -> None:
        source_url = params.get("source_url")
        if not source_url or not isinstance(source_url, str):
            raise AdapterValidationError(
                self.name,
                "'source_url' is required for optimize_image",
            )
        try:
            parsed = urlparse(source_url)
        except Exception as exc:  # noqa: BLE001
            raise AdapterValidationError(
                self.name, f"invalid 'source_url': {exc}",
            ) from exc
        if parsed.scheme not in ("http", "https"):
            raise AdapterValidationError(
                self.name,
                f"'source_url' must use http(s):// scheme "
                f"(got {parsed.scheme!r})",
            )
        if not parsed.netloc:
            raise AdapterValidationError(
                self.name, "'source_url' must include a host",
            )

        file_name = params.get("file_name")
        if not file_name or not isinstance(file_name, str):
            raise AdapterValidationError(
                self.name,
                "'file_name' is required for optimize_image",
            )
        if len(file_name) > _MAX_FILE_NAME_LEN:
            raise AdapterValidationError(
                self.name,
                f"'file_name' too long ({len(file_name)} chars; "
                f"max {_MAX_FILE_NAME_LEN})",
            )

        tags = params.get("tags")
        if tags is not None and not isinstance(tags, (list, tuple)):
            raise AdapterValidationError(
                self.name,
                f"'tags' must be a list, got {type(tags).__name__}",
            )

    # ── Vendor-specific hooks (override in subclasses) ────────

    def _optimize_url(self) -> str:
        raise NotImplementedError(
            f"{type(self).__name__}._optimize_url must be implemented",
        )

    def _auth_headers(self) -> dict[str, str]:
        """Default: Bearer token. Override when the vendor uses
        a different scheme (ImageKit uses HTTP Basic with the
        private key as username and an empty password)."""
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _build_optimize_payload(
        self, params: dict[str, Any],
    ) -> Any:
        raise NotImplementedError(
            f"{type(self).__name__}._build_optimize_payload must be implemented",
        )

    def _parse_optimize_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{type(self).__name__}._parse_optimize_response must be implemented",
        )

    # ── HTTP ───────────────────────────────────────────────────

    def _http_post(
        self,
        url: str,
        body: Any,
        headers: dict[str, str],
    ) -> Any:
        """W962-65: shared retry helper."""
        from core.adapters._http_retry import http_retry
        form_encoded = (
            headers.get("Content-Type")
            == "application/x-www-form-urlencoded"
        )

        def _do_call():
            if form_encoded:
                return _requests.post(
                    url, data=body, headers=headers,
                    timeout=self.timeout,
                )
            return _requests.post(
                url, json=body, headers=headers,
                timeout=self.timeout,
            )

        return http_retry(
            _do_call,
            adapter_name=self.name,
            timeout=self.timeout,
        )
