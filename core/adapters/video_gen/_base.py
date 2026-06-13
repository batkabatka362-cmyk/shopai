"""VideoGenBaseAdapter — shared base for video generation / stock sources.

ShopAI's "hybrid video creative" strategy combines three distinct
kinds of video source:

  1. **Stock video libraries** (Pexels, Pixabay) — free-to-use
     clips indexed by keyword. Cheapest path; perfect for
     stock-footage + voiceover ads where the product is shown
     generically (e.g. a kitchen gadget in any kitchen).

  2. **AI text→video generators** (Higgsfield, Runway, Replicate,
     Sora, Veo) — paid APIs that synthesise a video from a prompt.
     Expensive ($0.20-$1.00/sec) but produce product-in-scene
     shots that stock libraries cannot match.

  3. **Slideshow composer** (engine-level, no API) — the
     ``engines.ad_creative_generator`` engine stitches product
     images + voiceover into an MP4 when no clip source is
     available. Handled downstream; this adapter layer does not
     cover it.

Every adapter returns the same normalised clip record so the
creative-generation engine can compose videos from any mix of
vendors without vendor-specific code.

Capabilities:

  * :attr:`Capability.VIDEO_STOCK_SEARCH`  — keyword → clips
    (stock libraries only)
  * :attr:`Capability.VIDEO_GENERATE`      — prompt → video job
    (AI providers only; async on most APIs)
  * :attr:`Capability.VIDEO_GET_STATUS`    — poll async job
    (AI providers only)

Normalised clip record::

    {
        "clip_id":       "<vendor id>",
        "source":        "pexels | higgsfield | runway | ...",
        "kind":          "stock" | "ai" | "slideshow",
        "status":        "ready" | "processing" | "failed",
        "video_url":     "https://cdn.vendor.com/clip.mp4",
        "preview_url":   "https://cdn.vendor.com/preview.gif",
        "thumbnail_url": "https://cdn.vendor.com/thumb.jpg",
        "duration_seconds": 12,
        "width":         1920,
        "height":        1080,
        "format":        "mp4",
        "license":       "pexels" | "royalty_free" | "proprietary",
        "cost_usd":      0.00,             # per-clip incremental
        "prompt":        "<for AI clips; empty for stock>",
        "raw_url":       "https://vendor.com/clip/123",
    }

Missing fields MUST default to sensible empties (``""``, ``0``,
``0.0``) so downstream consumers never have to null-guard.
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

logger = get_logger("adapters.video_gen")


# AI video generation is inherently slow (renders take 30s-5min).
# Stock searches are fast. Each adapter tunes this.
_DEFAULT_TIMEOUT = 60.0


class VideoGenBaseAdapter(BaseAdapter):
    """Abstract base for every video generation / stock adapter.

    Concrete adapters MUST set:

      * ``name``         — registry key (e.g. ``"pexels"``)
      * ``base_url``     — vendor API root
      * ``config_alias`` — env alias for the credential (or ``""``
                           for fully-public endpoints)
      * ``capabilities`` — the subset of video capabilities this
                           adapter actually implements

    They MAY override:

      * ``priority``       — router preference (0-100)
      * ``cost_per_call``  — average $/query (stock is ~0;
                             AI gen is $0.20-$1.00)
      * ``timeout``        — per-request timeout
      * ``requires_key``   — ``False`` for public endpoints
      * ``kind``           — default record ``kind`` (``"stock"``
                             for stock libs, ``"ai"`` for gen)
    """

    category = AdapterCategory.VIDEO_GEN
    # Default capability set is empty — concrete adapters declare
    # exactly what they support. This means the router will never
    # dispatch a request to an adapter that can't fulfil it.
    capabilities: set[Capability] = set()

    base_url: str = ""
    config_alias: str = ""
    timeout: float = _DEFAULT_TIMEOUT

    cost_per_call: float = 0.0
    priority: int = 50

    requires_key: bool = True

    # Default record ``kind``; overridden by AI generators to
    # ``"ai"`` so downstream consumers can distinguish stock from
    # AI without string-matching the source name.
    kind: str = "stock"

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        if not self.base_url:
            return False
        if not self.requires_key:
            return True
        if not self.config_alias:
            return False
        return bool((_resolve_per_store(self.config_alias) or get_config().get(self.config_alias)))

    def _api_key(self) -> str:
        if not self.requires_key:
            return ""
        key = (_resolve_per_store(self.config_alias) or get_config().get(self.config_alias))
        if not key:
            env = get_config().env_var_for(self.config_alias)
            raise AdapterNotConfigured(
                self.name,
                f"missing API key (set ${env or self.config_alias})",
            )
        return key

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability not in self.capabilities:
            raise AdapterValidationError(
                self.name,
                f"{self.name} does not implement {capability.value}",
            )
        dispatch = {
            Capability.VIDEO_STOCK_SEARCH: self._do_stock_search,
            Capability.VIDEO_GENERATE: self._do_generate,
            Capability.VIDEO_GET_STATUS: self._do_get_status,
        }
        handler = dispatch.get(capability)
        if handler is None:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )
        return handler(capability, params)

    # ── Vendor hooks (override in subclass) ────────────────────

    def _do_stock_search(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{type(self).__name__}._do_stock_search must be implemented",
        )

    def _do_generate(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{type(self).__name__}._do_generate must be implemented",
        )

    def _do_get_status(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{type(self).__name__}._do_get_status must be implemented",
        )

    # ── Validation helpers ─────────────────────────────────────

    def _validate_stock_search(self, params: dict[str, Any]) -> None:
        query = params.get("query")
        if not query or not isinstance(query, str):
            raise AdapterValidationError(
                self.name, "'query' is required for video_stock_search",
            )
        limit = params.get("limit", 10)
        try:
            lim = int(limit)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name, f"'limit' must be int (got {limit!r})",
            ) from exc
        if lim < 1 or lim > 100:
            raise AdapterValidationError(
                self.name, f"'limit' must be 1-100 (got {lim})",
            )

    def _validate_generate(self, params: dict[str, Any]) -> None:
        prompt = params.get("prompt")
        if not prompt or not isinstance(prompt, str):
            raise AdapterValidationError(
                self.name, "'prompt' is required for video_generate",
            )
        # Reasonable prompt length guardrail — most vendors cap
        # at 1000-2000 chars; we enforce 2000 to stay universal.
        if len(prompt) > 2000:
            raise AdapterValidationError(
                self.name,
                f"'prompt' too long ({len(prompt)} chars, max 2000)",
            )
        duration = params.get("duration_seconds", 0)
        if duration:
            try:
                d = int(duration)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"'duration_seconds' must be int (got {duration!r})",
                ) from exc
            # Generous ceiling — most vendors cap at 10-15s; some
            # at 60s. Per-vendor adapters refine with vendor-
            # specific limits if they differ.
            if d < 1 or d > 120:
                raise AdapterValidationError(
                    self.name,
                    f"'duration_seconds' must be 1-120 (got {d})",
                )

    def _validate_get_status(self, params: dict[str, Any]) -> None:
        job_id = params.get("job_id")
        if not job_id or not isinstance(job_id, str):
            raise AdapterValidationError(
                self.name, "'job_id' is required for video_get_status",
            )

    # ── Record normalisation ───────────────────────────────────

    def _normalise_clip(
        self,
        record: dict[str, Any],
        *,
        default_source: str = "",
        default_kind: str = "",
    ) -> dict[str, Any]:
        """Fill every required field with a safe default.

        Vendors only return what they know — this helper guarantees
        the downstream shape so engines never have to ``.get()``
        with a fallback.
        """
        source = str(record.get("source") or default_source or self.name)
        kind = str(record.get("kind") or default_kind or self.kind or "stock")
        status = str(record.get("status") or "ready")

        # Duration is often returned as float (seconds) or as an
        # ISO-8601 duration; normalise to int seconds, tolerating
        # either. On failure, fall back to 0 — downstream engines
        # can still use the clip, just without trimming/fading
        # based on duration.
        duration_raw = record.get("duration_seconds", 0)
        try:
            duration_seconds = int(float(duration_raw or 0))
        except (TypeError, ValueError):
            duration_seconds = 0

        try:
            width = int(record.get("width", 0) or 0)
        except (TypeError, ValueError):
            width = 0
        try:
            height = int(record.get("height", 0) or 0)
        except (TypeError, ValueError):
            height = 0
        try:
            cost_usd = float(record.get("cost_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            cost_usd = 0.0

        return {
            "clip_id":       str(record.get("clip_id", "") or ""),
            "source":        source,
            "kind":          kind,
            "status":        status,
            "video_url":     str(record.get("video_url", "") or ""),
            "preview_url":   str(record.get("preview_url", "") or ""),
            "thumbnail_url": str(record.get("thumbnail_url", "") or ""),
            "duration_seconds": duration_seconds,
            "width":         width,
            "height":        height,
            "format":        str(record.get("format", "") or ""),
            "license":       str(record.get("license", "") or ""),
            "cost_usd":      cost_usd,
            "prompt":        str(record.get("prompt", "") or ""),
            "raw_url":       str(record.get("raw_url", "") or ""),
        }

    def _build_clips_response(
        self,
        capability: Capability,
        records: list[dict[str, Any]],
        *,
        query: str = "",
        raw: Any = None,
    ) -> AdapterResult:
        normalised = [
            self._normalise_clip(r, default_source=self.name)
            for r in records
            if isinstance(r, dict)
        ]
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "source": self.name,
                "query":  query,
                "clips":  normalised,
                "total":  len(normalised),
            },
            cost_usd=float(self.cost_per_call),
            raw=raw,
        )

    def _build_job_response(
        self,
        capability: Capability,
        record: dict[str, Any],
        *,
        prompt: str = "",
        raw: Any = None,
    ) -> AdapterResult:
        """Envelope for VIDEO_GENERATE / VIDEO_GET_STATUS (single clip)."""
        normalised = self._normalise_clip(
            record, default_source=self.name, default_kind="ai",
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "source": self.name,
                "prompt": prompt,
                "clip":   normalised,
            },
            cost_usd=float(self.cost_per_call),
            raw=raw,
        )

    # ── HTTP ───────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        """Default: Bearer token when a key exists. Override for
        vendor-specific schemes (Pexels uses the key in
        ``Authorization`` without ``Bearer`` prefix; Higgsfield
        uses ``X-API-Key``, etc.)."""
        if not self.requires_key:
            return {
                "Accept": "application/json",
                "User-Agent": "ShopAI-VideoGen/1.0",
            }
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Accept": "application/json",
            "User-Agent": "ShopAI-VideoGen/1.0",
        }

    def _http_request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """W962-65: shared retry helper."""
        from core.adapters._http_retry import http_retry
        hdrs = headers or self._auth_headers()

        def _do_call():
            if method.upper() == "GET":
                return _requests.get(
                    url, headers=hdrs, params=params,
                    timeout=self.timeout,
                )
            return _requests.post(
                url, json=body, headers=hdrs, params=params,
                timeout=self.timeout,
            )

        return http_retry(
            _do_call,
            adapter_name=self.name,
            timeout=self.timeout,
        )
