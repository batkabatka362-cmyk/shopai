"""SocialBaseAdapter — shared base for organic social adapters.

Same dispatch shape as the other categories: capability enum
→ _do_* hook. Subclasses implement the verbs they support and
opt out of the rest by leaving them off the ``capabilities``
set (SmartRouter reads ``capabilities`` to pick a candidate).

Normalised params + returns so engines don't branch on vendor:

    publish params:
        {
            "text":        "caption body",
            "image_url":   "https://..." (optional),
            "video_url":   "https://..." (optional; one of
                            image or video required for IG),
            "link_url":    "https://..." (optional, FB only),
            "hashtags":    ["#cozy", "#wellness"] (optional
                            — appended to text if not already
                            present),
        }

    publish return data:
        {
            "post_id":   "<vendor post id>",
            "permalink": "https://...",  # when available
            "published_at": "<ISO>",
            "platform":  "instagram | facebook_page | ...",
        }

    insights params:
        {"post_id": "<id>"}

    insights return:
        {
            "post_id": "...",
            "impressions": 0,
            "reach":       0,
            "likes":       0,
            "comments":    0,
            "shares":      0,
            "saves":       0,
        }
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


logger = get_logger("adapters.social")


_DEFAULT_TIMEOUT = 30.0


class SocialBaseAdapter(BaseAdapter):
    """Abstract base for organic social adapters."""

    category = AdapterCategory.SOCIAL
    capabilities: set[Capability] = set()

    base_url: str = ""
    config_alias: str = ""
    timeout: float = _DEFAULT_TIMEOUT
    cost_per_call: float = 0.0
    priority: int = 50

    # ── Configuration ──────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        if not self.base_url or not self.config_alias:
            return False
        return bool(get_config().get(self.config_alias))

    def _api_key(self) -> str:
        key = get_config().get(self.config_alias)
        if not key:
            env = get_config().env_var_for(self.config_alias)
            raise AdapterNotConfigured(
                self.name,
                f"missing token (set ${env or self.config_alias})",
            )
        return key

    # ── Capability dispatch ────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability not in self.capabilities:
            raise AdapterValidationError(
                self.name,
                f"{self.name} does not implement "
                f"{capability.value}",
            )
        dispatch = {
            Capability.SOCIAL_PUBLISH_POST:
                self._do_publish_post,
            Capability.SOCIAL_SCHEDULE_POST:
                self._do_schedule_post,
            Capability.SOCIAL_GET_INSIGHTS:
                self._do_get_insights,
            Capability.SOCIAL_LIST_POSTS:
                self._do_list_posts,
            Capability.SOCIAL_DELETE_POST:
                self._do_delete_post,
        }
        handler = dispatch.get(capability)
        if handler is None:
            raise AdapterValidationError(
                self.name,
                f"unsupported capability: {capability.value}",
            )
        return handler(capability, params)

    # ── Hook defaults (NotImplementedError) ────────────

    def _do_publish_post(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{type(self).__name__}._do_publish_post must be implemented",
        )

    def _do_schedule_post(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{type(self).__name__}._do_schedule_post must be implemented",
        )

    def _do_get_insights(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{type(self).__name__}._do_get_insights must be implemented",
        )

    def _do_list_posts(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{type(self).__name__}._do_list_posts must be implemented",
        )

    def _do_delete_post(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{type(self).__name__}._do_delete_post must be implemented",
        )

    # ── Shared validators ──────────────────────────────

    def _validate_publish(self, params: dict[str, Any]) -> None:
        text = str(params.get("text") or "").strip()
        image = str(params.get("image_url") or "").strip()
        video = str(params.get("video_url") or "").strip()
        if not text and not image and not video:
            raise AdapterValidationError(
                self.name,
                "publish requires at least one of text / "
                "image_url / video_url",
            )
        if len(text) > 2200:
            raise AdapterValidationError(
                self.name,
                f"text exceeds 2200 char cap (got {len(text)})",
            )

    def _validate_post_id(self, params: dict[str, Any]) -> None:
        pid = str(params.get("post_id") or "").strip()
        if not pid:
            raise AdapterValidationError(
                self.name, "'post_id' is required",
            )

    # ── Shared helpers ────────────────────────────────

    @staticmethod
    def _compose_caption(params: dict[str, Any]) -> str:
        """Append any untagged hashtags to the text. Shopify
        engines often pass hashtags as a separate list for
        readability; vendors want one blob."""
        text = str(params.get("text") or "").strip()
        tags = params.get("hashtags") or []
        if not isinstance(tags, (list, tuple)):
            return text
        existing = text.lower()
        to_add: list[str] = []
        for tag in tags:
            if not tag:
                continue
            norm = str(tag).strip()
            if not norm:
                continue
            if not norm.startswith("#"):
                norm = f"#{norm}"
            if norm.lower() in existing:
                continue
            to_add.append(norm)
        if not to_add:
            return text
        sep = " " if text else ""
        return f"{text}{sep}{' '.join(to_add)}"

    # ── HTTP ──────────────────────────────────────────

    def _http_request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        hdrs = headers or {"Accept": "application/json"}
        try:
            if method.upper() == "GET":
                response = _requests.get(
                    url, headers=hdrs, params=params,
                    timeout=self.timeout,
                )
            elif method.upper() == "DELETE":
                response = _requests.delete(
                    url, headers=hdrs, params=params,
                    timeout=self.timeout,
                )
            else:
                response = _requests.post(
                    url, json=body, headers=hdrs,
                    params=params, timeout=self.timeout,
                )
        except _requests.Timeout as exc:  # type: ignore[union-attr]
            raise AdapterTimeout(
                self.name,
                f"timeout after {self.timeout}s: {exc}",
            ) from exc
        except _requests.ConnectionError as exc:  # type: ignore[union-attr]
            raise AdapterUnavailable(
                self.name, f"connection error: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"HTTP {method} failed: "
                f"{type(exc).__name__}: {exc}",
            ) from exc

        status = getattr(response, "status_code", 0)
        if status >= 400:
            snippet = (
                getattr(response, "text", "") or ""
            )[:200]
            if status in (401, 403):
                raise AdapterAuthError(
                    self.name,
                    f"vendor rejected credentials "
                    f"({status}): {snippet}",
                )
            if status == 429:
                raise AdapterRateLimited(
                    self.name,
                    f"rate limit (429): {snippet}",
                )
            if 500 <= status < 600:
                raise AdapterUnavailable(
                    self.name,
                    f"vendor 5xx ({status}): {snippet}",
                )
            raise AdapterError(
                self.name,
                f"vendor returned {status}: {snippet}",
            )

        try:
            text = getattr(response, "text", "") or ""
            return response.json() if text else {}
        except ValueError as exc:
            raise AdapterError(
                self.name,
                f"invalid JSON response: {exc}",
            ) from exc
