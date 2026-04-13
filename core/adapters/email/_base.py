"""EmailBaseAdapter — shared HTTP base for email adapters.

Concrete adapters (Brevo, Resend, …) inherit this class and
override only the vendor-specific bits:

  * ``base_url``       — vendor API root
  * ``config_alias``   — ``ENV_ALIASES`` key for the API key
  * ``_send_url``      — the POST endpoint (defaults to
                          ``{base_url}/send``)
  * ``_auth_headers``  — vendor-specific auth header
  * ``_build_payload`` — Message → vendor body
  * ``_parse_response``— vendor response → normalised result

The base handles:

  * Required-field validation (``to``, ``from_email``,
    ``subject``, and at least one of ``html`` or ``text``)
  * HTTP POST execution with typed error mapping
  * AdapterResult assembly with latency + message id

Normalised ``EmailMessage`` shape:

    {
        "to":         "user@example.com",          # required (string)
        "to_name":    "Customer Name",              # optional
        "from_email": "shop@example.com",           # required
        "from_name":  "Acme Store",                 # optional
        "subject":    "Your order has shipped",     # required
        "html":       "<html>...</html>",           # html OR text required
        "text":       "Plain fallback",             # (both recommended)
        "reply_to":   "support@example.com",        # optional
        "tags":       ["shipment_notification"],    # optional
    }

Scope note: the base deliberately models ONE recipient and ONE
sender. Batching, list management, template management,
unsubscribe handling, and bounce webhooks are out of scope for
this phase. The brain's marketing / customer agents will
compose one Message per recipient and dispatch through the
router.
"""
from __future__ import annotations

from typing import Any, TypedDict

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

logger = get_logger("adapters.email")


class EmailMessage(TypedDict, total=False):
    """Normalised email shape accepted by every email adapter."""

    to: str
    to_name: str
    from_email: str
    from_name: str
    subject: str
    html: str
    text: str
    reply_to: str
    tags: list[str]


_REQUIRED_FIELDS = ("to", "from_email", "subject")
_DEFAULT_TIMEOUT = 15.0


class EmailBaseAdapter(BaseAdapter):
    """Abstract base for every email adapter.

    Concrete adapters MUST set:

      * ``name``         — registry key
      * ``base_url``     — vendor API root
      * ``config_alias`` — env alias for the API key

    They MAY set:

      * ``priority``                — router preference (0-100)
      * ``cost_per_call``           — $/call (0 on free tiers)
      * ``free_tier_daily_limit``   — quota hint for metrics
      * ``free_tier_monthly_limit``
    """

    category = AdapterCategory.EMAIL
    capabilities = {
        Capability.SEND_EMAIL_TRANSACTIONAL,
        Capability.SEND_EMAIL_CAMPAIGN,
    }

    base_url: str = ""
    config_alias: str = ""
    timeout: float = _DEFAULT_TIMEOUT

    cost_per_call: float = 0.0
    free_tier_daily_limit: int = 0
    free_tier_monthly_limit: int = 0

    # ── Configuration ──────────────────────────────────────────

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
                f"missing API key (set ${env or self.config_alias})",
            )
        return key

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        # Both transactional and campaign capabilities funnel
        # through the same POST today — vendors do not
        # distinguish in their send endpoint. Campaign vs
        # transactional is a billing/list concern handled at a
        # higher layer.
        if capability not in (
            Capability.SEND_EMAIL_TRANSACTIONAL,
            Capability.SEND_EMAIL_CAMPAIGN,
        ):
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        self._validate_message(params)
        payload = self._build_payload(params)
        raw = self._http_post(
            self._send_url(),
            payload,
            headers=self._auth_headers(),
        )
        message_id = self._parse_response(raw)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "message_id": message_id,
                "to": params["to"],
                "subject": params["subject"],
            },
            raw=raw,
        )

    # ── Validation ─────────────────────────────────────────────

    def _validate_message(self, params: dict[str, Any]) -> None:
        missing = [f for f in _REQUIRED_FIELDS if not params.get(f)]
        if missing:
            raise AdapterValidationError(
                self.name,
                f"missing required fields: {', '.join(missing)}",
            )

        if not params.get("html") and not params.get("text"):
            raise AdapterValidationError(
                self.name,
                "at least one of 'html' or 'text' is required",
            )

        to = params["to"]
        if not isinstance(to, str) or "@" not in to:
            raise AdapterValidationError(
                self.name, f"'to' must be a valid email, got {to!r}",
            )

        from_email = params["from_email"]
        if not isinstance(from_email, str) or "@" not in from_email:
            raise AdapterValidationError(
                self.name,
                f"'from_email' must be a valid email, got {from_email!r}",
            )

    # ── Vendor-specific hooks ──────────────────────────────────

    def _send_url(self) -> str:
        """Default send endpoint — ``{base_url}/send``. Override
        when the vendor uses a different path."""
        return f"{self.base_url.rstrip('/')}/send"

    def _auth_headers(self) -> dict[str, str]:
        """Default: Bearer token. Override when the vendor uses
        a different scheme (Brevo uses ``api-key`` header)."""
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _build_payload(self, message: dict[str, Any]) -> dict[str, Any]:
        """Translate the ``EmailMessage`` into the vendor's body.
        MUST be overridden — every vendor has a different schema."""
        raise NotImplementedError(
            f"{type(self).__name__}._build_payload must be implemented",
        )

    def _parse_response(self, raw: Any) -> str:
        """Return the message id the vendor assigned, or an
        empty string if the vendor doesn't echo one. MUST be
        overridden."""
        raise NotImplementedError(
            f"{type(self).__name__}._parse_response must be implemented",
        )

    # ── HTTP ───────────────────────────────────────────────────

    def _http_post(
        self,
        url: str,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> Any:
        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        try:
            response = _requests.post(
                url, json=body, headers=headers, timeout=self.timeout,
            )
        except _requests.Timeout as exc:  # type: ignore[union-attr]
            raise AdapterTimeout(
                self.name, f"timeout after {self.timeout}s: {exc}",
            ) from exc
        except _requests.ConnectionError as exc:  # type: ignore[union-attr]
            raise AdapterUnavailable(
                self.name, f"connection error: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"http post failed: {type(exc).__name__}: {exc}",
            ) from exc

        if response.status_code >= 400:
            snippet = (getattr(response, "text", "") or "")[:200]
            if response.status_code in (401, 403):
                raise AdapterAuthError(
                    self.name,
                    f"vendor rejected credentials "
                    f"({response.status_code}): {snippet}",
                )
            if response.status_code == 429:
                raise AdapterRateLimited(
                    self.name, f"rate limit (429): {snippet}",
                )
            if 500 <= response.status_code < 600:
                raise AdapterUnavailable(
                    self.name,
                    f"vendor 5xx ({response.status_code}): {snippet}",
                )
            raise AdapterError(
                self.name,
                f"vendor returned {response.status_code}: {snippet}",
            )

        try:
            return response.json() if response.text else {}
        except ValueError as exc:
            raise AdapterError(
                self.name, f"invalid JSON response: {exc}",
            ) from exc
