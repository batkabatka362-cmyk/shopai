"""PexelsPhotosAdapter — free stock photo search (W963-169).

Pexels (https://pexels.com/api/) serves royalty-free stock photos
via a keyword search endpoint. This adapter wraps the photos API
(distinct from the videos API the existing PexelsAdapter in
``core/adapters/video_gen/pexels.py`` covers).

The product_sourcer engine generates beauty / fashion / home
product proposals with semantic queries; the create_draft_product
dispatcher uses this adapter to find a hero image per proposal
automatically. Before this, every autonomously-created product
landed on Shopify with no image -- a near-zero conversion gate
even when status=ACTIVE + price>0 + inventoryPolicy=CONTINUE.

Authentication: same ``PEXELS_API_KEY`` env as the video adapter.
The key value goes in the ``Authorization`` header (NO Bearer
prefix). Free tier: 200 requests/hour, 20000/month.

Endpoint:

  * ``GET /v1/search?query=...&per_page=N&orientation=landscape``

Reference: https://www.pexels.com/api/documentation/#photos
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

logger = get_logger("adapters.image.pexels_photos")


_DEFAULT_TIMEOUT = 15.0


class PexelsPhotosAdapter(BaseAdapter):
    """Stock photo search via Pexels Photos API."""

    name = "pexels_photos"
    category = AdapterCategory.IMAGE_GEN
    base_url = "https://api.pexels.com/v1"
    config_alias = "pexels"
    capabilities = {Capability.IMAGE_STOCK_SEARCH}
    required_scopes = frozenset()

    # Higher priority than AI image gen because it's free.
    priority = 90
    cost_per_call = 0.0
    timeout: float = _DEFAULT_TIMEOUT

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        return bool(
            _resolve_per_store(self.config_alias)
            or get_config().get(self.config_alias),
        )

    def _api_key(self) -> str:
        key = (
            _resolve_per_store(self.config_alias)
            or get_config().get(self.config_alias)
        )
        if not key:
            env = get_config().env_var_for(self.config_alias)
            raise AdapterNotConfigured(
                self.name,
                f"missing Pexels key (set ${env or 'PEXELS_API_KEY'})",
            )
        return key

    def _auth_headers(self) -> dict[str, str]:
        # Pexels accepts the raw key value (no Bearer prefix)
        return {
            "Authorization": self._api_key(),
            "Accept": "application/json",
            "User-Agent": "ShopAI-Image/1.0",
        }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability != Capability.IMAGE_STOCK_SEARCH:
            raise AdapterValidationError(
                self.name,
                f"unsupported capability: {capability.value}",
            )
        self._validate_search(params)
        query = str(params["query"]).strip()
        try:
            limit = int(params.get("limit", 10))
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(limit, 80))
        orientation = str(
            params.get("orientation", "") or "",
        )
        size = str(params.get("size", "") or "")

        url = f"{self.base_url}/search"
        query_params: dict[str, Any] = {
            "query": query,
            "per_page": limit,
        }
        if orientation in (
            "landscape", "portrait", "square",
        ):
            query_params["orientation"] = orientation
        if size in ("small", "medium", "large"):
            query_params["size"] = size

        raw = self._http_get(url, params=query_params)
        photos = _extract_pexels_photos(raw)
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "query": query,
                "photo_count": len(photos),
                "photos": photos,
            },
            cost_usd=self.cost_per_call,
            raw=raw,
        )

    def _validate_search(self, params: dict[str, Any]) -> None:
        q = params.get("query")
        if not isinstance(q, str) or not q.strip():
            raise AdapterValidationError(
                self.name,
                "'query' is required (non-empty string)",
            )

    def _http_get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """W962-65: delegates to shared core.adapters._http_retry."""
        from core.adapters._http_retry import http_retry
        return http_retry(
            lambda: _requests.get(
                url,
                headers=self._auth_headers(),
                params=params,
                timeout=self.timeout,
            ),
            adapter_name=self.name,
            timeout=self.timeout,
        )


def _extract_pexels_photos(raw: Any) -> list[dict[str, Any]]:
    """Map Pexels response -> normalised photo records.

    Pexels returns photos in ``photos[]`` with each entry carrying
    a ``src`` dict of size variants. We surface the URL set so
    callers can pick the best size for their use case (Shopify
    has a 25MP ceiling -- use ``src.large2x`` which is capped at
    ~2MP; ``src.original`` can be 30-60MP and gets rejected).
    """
    if not isinstance(raw, dict):
        return []
    photos = raw.get("photos") or []
    out: list[dict[str, Any]] = []
    for p in photos:
        if not isinstance(p, dict):
            continue
        src = p.get("src") or {}
        if not isinstance(src, dict):
            src = {}
        out.append({
            "photo_id": str(p.get("id", "")),
            "source": "pexels",
            "alt": p.get("alt", "") or "",
            "photographer": p.get("photographer", "") or "",
            # Direct CDN URLs. ``large2x`` is the sweet spot for
            # Shopify (~2MP), ``original`` can be too large.
            "url_original": src.get("original", "") or "",
            "url_large2x": src.get("large2x", "") or "",
            "url_large": src.get("large", "") or "",
            "url_medium": src.get("medium", "") or "",
            "url_small": src.get("small", "") or "",
            "url_tiny": src.get("tiny", "") or "",
            "width": int(p.get("width", 0) or 0),
            "height": int(p.get("height", 0) or 0),
            "avg_color": p.get("avg_color", "") or "",
            "page_url": p.get("url", "") or "",
        })
    return out
