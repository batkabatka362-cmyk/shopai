"""HelpdeskBaseAdapter -- shared HTTP base for
customer support / ticketing adapters (Gorgias, Tidio,
Zendesk, Intercom, Reamaze).

Concrete adapters override:
  - base_url
  - config_alias / config_alias_user (Basic auth uses
    both)
  - _auth_headers
  - _list_path / _parse_list_response
  - _get_path / _parse_get_response
  - _reply_path / _build_reply_payload
  - _update_tags_path / _build_update_tags_payload
  - _normalise_status (vendor status -> normalised)

Normalised shapes:

  Ticket (output):
    {
      "id":              "12345",
      "subject":         "Where is my order?",
      "status":          "open",  # open / pending /
                                  # resolved / closed
      "channel":         "email",
      "customer": {
        "email": "x@y.z",
        "name":  "Jane Doe",
      },
      "tags":            ["shopai-support-shipping"],
      "last_message_at": "2026-06-12T...",
      "messages":        [...],
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

logger = get_logger("adapters.helpdesk")


# Normalised ticket status (vendor-agnostic)
TICKET_OPEN = "open"
TICKET_PENDING = "pending"
TICKET_RESOLVED = "resolved"
TICKET_CLOSED = "closed"
TICKET_SPAM = "spam"


class HelpdeskBaseAdapter(BaseAdapter):
    """Abstract base for every helpdesk adapter."""

    category = AdapterCategory.HELPDESK
    capabilities = {
        Capability.HELPDESK_LIST_TICKETS,
        Capability.HELPDESK_GET_TICKET,
        Capability.HELPDESK_SEND_REPLY,
        Capability.HELPDESK_UPDATE_TICKET_TAGS,
        Capability.HELPDESK_CREATE_TICKET,
    }

    base_url: str = ""
    config_alias: str = ""
    timeout: float = 20.0
    cost_per_call: float = 0.0

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        if not self.base_url or not self.config_alias:
            return False
        return bool(
            _resolve_per_store(self.config_alias)
            or get_config().get(self.config_alias)
        )

    def _api_key(self) -> str:
        key = (
            _resolve_per_store(self.config_alias)
            or get_config().get(self.config_alias)
        )
        if not key:
            env = get_config().env_var_for(
                self.config_alias,
            )
            raise AdapterNotConfigured(
                self.name,
                f"missing API key (set ${env or self.config_alias})",
            )
        return key

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability == Capability.HELPDESK_LIST_TICKETS:
            return self._do_list(capability, params)
        if capability == Capability.HELPDESK_GET_TICKET:
            return self._do_get(capability, params)
        if capability == Capability.HELPDESK_SEND_REPLY:
            return self._do_reply(capability, params)
        if (
            capability
            == Capability.HELPDESK_UPDATE_TICKET_TAGS
        ):
            return self._do_update_tags(
                capability, params,
            )
        if capability == Capability.HELPDESK_CREATE_TICKET:
            return self._do_create_ticket(
                capability, params,
            )
        return AdapterResult.failure(
            self.name, capability.value,
            AdapterValidationError(
                self.name,
                f"unsupported capability {capability.value}",
            ),
        )

    # ── LIST ──────────────────────────────────────────────────

    def _do_list(
        self, capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        limit = int(params.get("limit") or 30)
        status_filter = (
            params.get("status") or ""
        ).strip()
        path = self._list_path(
            limit=limit, status_filter=status_filter,
        )
        result = self._get(capability, path)
        if not result.ok:
            return result
        data = self._parse_list_response(
            result.data or {},
        )
        return AdapterResult.success(
            self.name, capability.value,
            data=data, latency_ms=result.latency_ms,
            cost_usd=self.cost_per_call,
        )

    # ── GET ───────────────────────────────────────────────────

    def _do_get(
        self, capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        ticket_id = str(
            params.get("ticket_id") or "",
        ).strip()
        if not ticket_id:
            raise AdapterValidationError(
                self.name, "ticket_id required",
            )
        path = self._get_path(ticket_id=ticket_id)
        result = self._get(capability, path)
        if not result.ok:
            return result
        data = self._parse_get_response(
            result.data or {},
        )
        return AdapterResult.success(
            self.name, capability.value,
            data=data, latency_ms=result.latency_ms,
            cost_usd=self.cost_per_call,
        )

    # ── REPLY ─────────────────────────────────────────────────

    def _do_reply(
        self, capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        ticket_id = str(
            params.get("ticket_id") or "",
        ).strip()
        body = str(params.get("body") or "").strip()
        if not ticket_id:
            raise AdapterValidationError(
                self.name, "ticket_id required",
            )
        if not body:
            raise AdapterValidationError(
                self.name, "body required",
            )
        path = self._reply_path(ticket_id=ticket_id)
        payload = self._build_reply_payload(
            ticket_id=ticket_id,
            body=body,
            channel=params.get("channel", "email"),
            from_agent_id=params.get(
                "from_agent_id", "",
            ),
        )
        result = self._post(capability, path, payload)
        if not result.ok:
            return result
        return AdapterResult.success(
            self.name, capability.value,
            data={
                "reply_sent": True,
                "ticket_id": ticket_id,
            },
            latency_ms=result.latency_ms,
            cost_usd=self.cost_per_call,
        )

    # ── UPDATE TAGS ───────────────────────────────────────────

    def _do_update_tags(
        self, capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        ticket_id = str(
            params.get("ticket_id") or "",
        ).strip()
        tags = params.get("tags") or []
        if not ticket_id:
            raise AdapterValidationError(
                self.name, "ticket_id required",
            )
        if (
            not isinstance(tags, list)
            or not tags
        ):
            raise AdapterValidationError(
                self.name,
                "tags must be a non-empty list",
            )
        path = self._update_tags_path(
            ticket_id=ticket_id,
        )
        payload = self._build_update_tags_payload(
            ticket_id=ticket_id, tags=tags,
        )
        result = self._post(capability, path, payload)
        if not result.ok:
            return result
        return AdapterResult.success(
            self.name, capability.value,
            data={
                "tags_updated": True,
                "ticket_id": ticket_id,
                "tags": tags,
            },
            latency_ms=result.latency_ms,
            cost_usd=self.cost_per_call,
        )

    # ── CREATE TICKET ─────────────────────────────────────────

    def _do_create_ticket(
        self, capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        subject = str(
            params.get("subject") or "",
        ).strip()
        body = str(params.get("body") or "").strip()
        customer_email = str(
            params.get("customer_email") or "",
        ).strip()
        if not subject:
            raise AdapterValidationError(
                self.name, "subject required",
            )
        if not body:
            raise AdapterValidationError(
                self.name, "body required",
            )
        if not customer_email:
            raise AdapterValidationError(
                self.name, "customer_email required",
            )
        path = self._create_ticket_path()
        payload = self._build_create_ticket_payload(
            subject=subject,
            body=body,
            customer_email=customer_email,
            tags=params.get("tags", []),
        )
        result = self._post(capability, path, payload)
        if not result.ok:
            return result
        data = self._parse_create_ticket_response(
            result.data or {},
        )
        return AdapterResult.success(
            self.name, capability.value,
            data=data, latency_ms=result.latency_ms,
            cost_usd=self.cost_per_call,
        )

    # ── Vendor-specific hooks ─────────────────────────────────

    def _list_path(
        self, *, limit: int, status_filter: str,
    ) -> str:
        raise NotImplementedError

    def _parse_list_response(
        self, raw: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _get_path(self, *, ticket_id: str) -> str:
        raise NotImplementedError

    def _parse_get_response(
        self, raw: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _reply_path(self, *, ticket_id: str) -> str:
        raise NotImplementedError

    def _build_reply_payload(
        self, **kwargs: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _update_tags_path(
        self, *, ticket_id: str,
    ) -> str:
        raise NotImplementedError

    def _build_update_tags_payload(
        self, **kwargs: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _create_ticket_path(self) -> str:
        raise NotImplementedError

    def _build_create_ticket_payload(
        self, **kwargs: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _parse_create_ticket_response(
        self, raw: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    # ── HTTP plumbing ─────────────────────────────────────────

    def _get(
        self, capability: Capability, path: str,
    ) -> AdapterResult:
        import time
        start = time.monotonic()
        url = self.base_url.rstrip("/") + path
        try:
            resp = _requests.get(
                url, headers=self._auth_headers(),
                timeout=self.timeout,
            )
        except _requests.exceptions.Timeout as exc:
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterTimeout(self.name, str(exc)),
            )
        except _requests.exceptions.RequestException as exc:
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterUnavailable(self.name, str(exc)),
            )
        elapsed = (time.monotonic() - start) * 1000
        return self._normalise_http_response(
            capability, resp, elapsed,
        )

    def _post(
        self, capability: Capability,
        path: str, payload: dict[str, Any],
    ) -> AdapterResult:
        import time
        start = time.monotonic()
        url = self.base_url.rstrip("/") + path
        try:
            resp = _requests.post(
                url, headers=self._auth_headers(),
                json=payload, timeout=self.timeout,
            )
        except _requests.exceptions.Timeout as exc:
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterTimeout(self.name, str(exc)),
            )
        except _requests.exceptions.RequestException as exc:
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterUnavailable(self.name, str(exc)),
            )
        elapsed = (time.monotonic() - start) * 1000
        return self._normalise_http_response(
            capability, resp, elapsed,
        )

    def _normalise_http_response(
        self, capability: Capability,
        resp: Any, latency_ms: float,
    ) -> AdapterResult:
        status = resp.status_code
        body_text = resp.text or ""
        if status in (401, 403):
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterAuthError(
                    self.name, body_text[:240],
                ),
                latency_ms=round(latency_ms, 2),
            )
        if status == 429:
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterRateLimited(
                    self.name, body_text[:240],
                ),
                latency_ms=round(latency_ms, 2),
            )
        if status >= 500:
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterUnavailable(
                    self.name, body_text[:240],
                ),
                latency_ms=round(latency_ms, 2),
            )
        if status >= 400:
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterError(
                    self.name, body_text[:240],
                ),
                latency_ms=round(latency_ms, 2),
            )
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            data = {"raw": body_text}
        return AdapterResult.success(
            self.name, capability.value,
            data=data, latency_ms=round(latency_ms, 2),
        )
