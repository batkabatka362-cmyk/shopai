"""PinterestAdapter — Pinterest API v5 (W963-10).

Pinterest is one of the highest-ROI organic-traffic platforms
for visual e-commerce verticals: pins surface in search for
months to years, have direct shopping intent, and the platform
has comparatively lower content velocity than Instagram or
TikTok. This adapter wraps Pinterest API v5 for:

  * **Authentication probe** — verify the OAuth token works
    (SOCIAL_VERIFY_AUTH).
  * **Board management** — list + create boards
    (SOCIAL_LIST_BOARDS / SOCIAL_CREATE_BOARD).
  * **Pin creation** — publish pins from public image URLs
    with title + description + product link
    (SOCIAL_CREATE_PIN).

Authentication: OAuth 2.0 bearer token. Operators generate the
token via the Pinterest Developer dashboard:
  https://developers.pinterest.com/apps

Required scopes for ShopAI's use case:
  - user_accounts:read   (verify auth)
  - boards:read          (list boards)
  - boards:write         (create boards)
  - pins:write           (create pins)

Pinterest API rate limits:
  - 1000 requests / hour per app per access token
  - Pin creation: ~10 / minute soft limit (use spacing)

The adapter doesn't enforce client-side spacing — callers
publishing in bulk should add delays. ShopAI's autonomous loop
publishes one pin per cycle which is well within limits.
"""
from __future__ import annotations

import json
from typing import Any

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
    AdapterRateLimited,
    AdapterValidationError,
)

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False


_PINTEREST_BASE = "https://api.pinterest.com/v5"
_DEFAULT_TIMEOUT = 30.0


class PinterestAdapter(BaseAdapter):
    """Pinterest API v5 adapter."""

    name = "pinterest"
    base_url = _PINTEREST_BASE
    config_alias = "pinterest"
    category = AdapterCategory.SOCIAL

    priority = 90
    cost_per_call = 0.0

    required_scopes: tuple[str, ...] = ()

    capabilities = frozenset({
        Capability.SOCIAL_VERIFY_AUTH,
        Capability.SOCIAL_LIST_BOARDS,
        Capability.SOCIAL_CREATE_BOARD,
        Capability.SOCIAL_CREATE_PIN,
    })

    # ── Configuration ─────────────────────────────────────────

    def is_configured(self) -> bool:
        return bool(get_config().get(self.config_alias))

    def _api_key(self) -> str:
        key = get_config().get(self.config_alias)
        if not key:
            raise AdapterAuthError(
                self.name, "PINTEREST_ACCESS_TOKEN not set",
            )
        return str(key)

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Dispatch ──────────────────────────────────────────────

    def _execute(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        if not _REQUESTS_AVAILABLE:
            raise AdapterError(
                self.name,
                "requests library not available",
            )

        if capability == Capability.SOCIAL_VERIFY_AUTH:
            return self._verify_auth(capability)
        if capability == Capability.SOCIAL_LIST_BOARDS:
            return self._list_boards(capability, params)
        if capability == Capability.SOCIAL_CREATE_BOARD:
            return self._create_board(capability, params)
        if capability == Capability.SOCIAL_CREATE_PIN:
            return self._create_pin(capability, params)
        raise AdapterValidationError(
            self.name,
            f"unsupported capability: {capability.value}",
        )

    # ── Verify auth ───────────────────────────────────────────

    def _verify_auth(
        self, capability: Capability,
    ) -> AdapterResult:
        raw = self._http_get("/user_account")
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "username": raw.get("username", ""),
                "account_type": raw.get("account_type", ""),
                "profile_image": raw.get("profile_image", ""),
            },
            raw=raw,
        )

    # ── Boards ────────────────────────────────────────────────

    def _list_boards(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        page_size = int(params.get("limit", 25))
        page_size = max(1, min(page_size, 100))
        raw = self._http_get(
            "/boards", query={"page_size": page_size},
        )
        items = raw.get("items", []) or []
        boards = []
        for b in items:
            if not isinstance(b, dict):
                continue
            boards.append({
                "id": b.get("id", ""),
                "name": b.get("name", ""),
                "description": b.get("description", ""),
                "privacy": b.get("privacy", ""),
                "pin_count": b.get("pin_count", 0),
                "follower_count": b.get("follower_count", 0),
            })
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "boards": boards,
                "count": len(boards),
            },
            raw=raw,
        )

    def _create_board(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        name = str(params.get("name") or "").strip()
        if not name:
            raise AdapterValidationError(
                self.name, "'name' is required",
            )
        body: dict[str, Any] = {"name": name}
        if params.get("description"):
            body["description"] = str(params["description"])
        privacy = str(params.get("privacy") or "PUBLIC").upper()
        if privacy not in ("PUBLIC", "PROTECTED", "SECRET"):
            privacy = "PUBLIC"
        body["privacy"] = privacy

        raw = self._http_post("/boards", body=body)
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "board_id": raw.get("id", ""),
                "name": raw.get("name", name),
                "privacy": raw.get("privacy", privacy),
            },
            raw=raw,
        )

    # ── Pins ──────────────────────────────────────────────────

    def _create_pin(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        # Required: board_id + image source + title.
        board_id = str(params.get("board_id") or "").strip()
        if not board_id:
            raise AdapterValidationError(
                self.name, "'board_id' is required",
            )
        title = str(params.get("title") or "").strip()
        if not title:
            raise AdapterValidationError(
                self.name, "'title' is required (max 100 chars)",
            )
        if len(title) > 100:
            title = title[:100]

        image_url = str(params.get("image_url") or "").strip()
        if not image_url:
            raise AdapterValidationError(
                self.name,
                "'image_url' is required "
                "(public HTTPS image URL)",
            )

        # Optional fields.
        description = str(
            params.get("description") or "",
        )[:800]  # Pinterest limit
        link = str(params.get("link") or "").strip()

        body: dict[str, Any] = {
            "board_id": board_id,
            "title": title,
            "media_source": {
                "source_type": "image_url",
                "url": image_url,
            },
        }
        if description:
            body["description"] = description
        if link:
            body["link"] = link

        raw = self._http_post("/pins", body=body)
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "pin_id": raw.get("id", ""),
                "board_id": board_id,
                "title": title,
                "link": link,
                "url": raw.get("link", link),
            },
            raw=raw,
        )

    # ── HTTP plumbing ─────────────────────────────────────────

    def _http_get(
        self, path: str, *, query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._http_request("GET", path, query=query)

    def _http_post(
        self, path: str, *, body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._http_request("POST", path, body=body)

    def _http_request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            resp = _requests.request(
                method,
                url,
                headers=self._auth_headers(),
                data=json.dumps(body) if body else None,
                params=query,
                timeout=_DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"network error: {type(exc).__name__}",
            ) from exc

        if resp.status_code == 401 or resp.status_code == 403:
            raise AdapterAuthError(
                self.name,
                f"auth failed (HTTP {resp.status_code}): "
                f"{resp.text[:200]}",
            )
        if resp.status_code == 429:
            raise AdapterRateLimited(
                self.name,
                "Pinterest rate limit hit (HTTP 429)",
            )
        if resp.status_code >= 400:
            raise AdapterError(
                self.name,
                f"HTTP {resp.status_code}: {resp.text[:200]}",
            )
        try:
            return resp.json()
        except json.JSONDecodeError:
            return {}
