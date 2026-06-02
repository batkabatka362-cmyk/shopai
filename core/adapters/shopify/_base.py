"""ShopifyBaseAdapter — shared GraphQL base for every Shopify
native adapter.

Lifts auth, GraphQL execution, error mapping, and result
assembly into a single class so concrete adapters
(``risk``, ``inventory``, ``fulfillment``, ``metafield``, ...)
become 50-100 lines of capability declaration + GraphQL
template + response parsing.

Two construction modes:

  * **Direct** — pass ``shop_url`` + ``access_token`` to the
    constructor. Used at startup when credentials are read from
    env vars or a secrets file. Thread-safe — the underlying
    ``ShopifyGraphQL`` client holds no mutable per-call state
    beyond a cost counter.

  * **Lazy from env** — construct with no arguments and the
    base reads ``SHOPAI_SHOPIFY_URL`` + ``SHOPAI_SHOPIFY_KEY``
    from ``AdapterConfig`` on first use. ``is_configured()``
    returns False until both are set, so the smart router
    silently skips unconfigured adapters instead of raising.

The base never imports the legacy ``ShopifyGraphQL`` at module
level — that import only happens inside ``_make_client()``,
which is gated by ``is_configured()``. This keeps test
collection fast and lets the rest of the adapter ecosystem
import the Shopify package even when ``data_pipeline`` is not
on the path.
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
    AdapterUnavailable,
    AdapterValidationError,
)

logger = get_logger("adapters.shopify")


class ShopifyBaseAdapter(BaseAdapter):
    """Shared GraphQL base for every Shopify native adapter.

    Concrete subclasses MUST set:

      * ``name``         — registry key (e.g. ``"shopify_risk"``)
      * ``capabilities`` — set of ``Capability`` enums

    They override ``_execute()`` to dispatch the capability to a
    private handler. The private handlers call ``self._gql(...)``
    to talk to Shopify and let the base handle the auth/error
    plumbing.

    Construction:

        # explicit
        adapter = ShopifyRiskAdapter(
            shop_url="store.myshopify.com",
            access_token="shpat_xxx",
        )

        # lazy from AdapterConfig env vars
        adapter = ShopifyRiskAdapter()
    """

    category = AdapterCategory.SHOPIFY_NATIVE
    cost_per_call = 0.0  # Free — included in Shopify plan
    priority = 100        # Native APIs always preferred over apps

    # OAuth scope manifest. Each concrete adapter declares the
    # Shopify access scopes (https://shopify.dev/docs/api/usage/
    # access-scopes) it needs for its GraphQL calls. Aggregated
    # via ``core.adapters.shopify.scope_registry`` so operators
    # see exactly which scopes the app install needs without
    # reading every adapter docstring.
    #
    # Empty default — adapters that haven't been wired into the
    # registry yet won't surface scopes, but won't break either.
    # The registry treats an unwired adapter as "scopes unknown"
    # and flags it so operators can request a wireup.
    required_scopes: frozenset[str] = frozenset()

    # Sentinel for adapters that legitimately need NO extra OAuth
    # scope — either because they're app-level features available
    # to any installed app (e.g. app billing, app subscriptions,
    # mobile platform app, shop info) or because the scope depends
    # on the caller's payload at runtime (bulk operations,
    # generic tags). Set this to ``True`` AND leave
    # ``required_scopes`` as the empty default; the registry will
    # treat the adapter as "declared, no scopes needed" rather
    # than surfacing it in the rollout-gap list.
    scope_independent: bool = False

    def __init__(
        self,
        shop_url: str | None = None,
        access_token: str | None = None,
    ) -> None:
        super().__init__()
        self._shop_url_override = shop_url
        self._token_override = access_token
        self._client: Any = None  # ShopifyGraphQL, lazy

    # ── Configuration ──────────────────────────────────────────

    def _resolve_credentials(self) -> tuple[str, str]:
        """Return ``(shop_url, access_token)`` from override fields
        first, falling back to ``AdapterConfig`` env vars.

        Empty strings indicate "missing" — caller should treat
        the adapter as not configured.
        """
        if self._shop_url_override and self._token_override:
            return self._shop_url_override, self._token_override
        cfg = get_config()
        return (
            self._shop_url_override or cfg.get("shopify_url"),
            self._token_override or cfg.get("shopify_key"),
        )

    def is_configured(self) -> bool:
        shop, token = self._resolve_credentials()
        return bool(shop and token)

    # ── GraphQL client ─────────────────────────────────────────

    def _make_client(self) -> Any:
        """Lazily build the underlying ``ShopifyGraphQL`` client.

        Imported inside the method (not at module top) so the
        adapter package can be imported in environments where
        ``data_pipeline`` is missing — useful for unit tests
        that mock ``_gql`` directly without touching the real
        HTTP layer.
        """
        if self._client is not None:
            return self._client

        shop, token = self._resolve_credentials()
        if not shop or not token:
            raise AdapterNotConfigured(
                self.name,
                "missing SHOPAI_SHOPIFY_URL / SHOPAI_SHOPIFY_KEY",
            )

        try:
            from data_pipeline.ingestion.api.shopify_graphql import ShopifyGraphQL
        except Exception as exc:  # noqa: BLE001
            raise AdapterUnavailable(
                self.name, f"shopify_graphql import failed: {exc}",
            ) from exc

        self._client = ShopifyGraphQL(shop, token)
        return self._client

    def _gql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query / mutation against Shopify and
        translate every error into an ``AdapterError`` subclass.

        Returns the ``data`` portion of the response. The
        envelope's ``errors`` array (if present) is logged at
        WARNING level and raised as ``AdapterError`` so callers
        never have to inspect the envelope themselves.
        """
        client = self._make_client()

        try:
            response = client.query(query, variables or {})
        except Exception as exc:  # noqa: BLE001
            # ShopifyGraphQLError carries HTTP status info in its
            # message; classify by string match. The 401 case
            # is rare in practice (token would be rejected at
            # OAuth time) but we still distinguish it.
            msg = str(exc)
            if "401" in msg or "403" in msg:
                raise AdapterAuthError(self.name, msg) from exc
            if "429" in msg:
                raise AdapterRateLimited(self.name, msg) from exc
            # W962-37 bugfix: the original check was
            #   any(s in msg for s in ("5", "Network", ...))
            # The bare "5" substring matched ANY error message
            # containing the digit 5 (e.g. "order 5 not found"
            # -> Unavailable). The intent was 5xx HTTP codes,
            # so match those concretely via a regex for a
            # 5xx triple at a word boundary.
            import re as _re
            msg_lower = msg.lower()
            is_5xx = bool(
                _re.search(r"\b5\d{2}\b", msg)
                or "5xx" in msg_lower
            )
            if (
                is_5xx
                or "network" in msg_lower
                or "timeout" in msg_lower
            ):
                raise AdapterUnavailable(self.name, msg) from exc
            raise AdapterError(self.name, msg) from exc

        if not isinstance(response, dict):
            raise AdapterError(
                self.name,
                f"unexpected GraphQL response type: {type(response).__name__}",
            )

        # GraphQL "soft" errors live inside the envelope under
        # ``errors`` even when HTTP returned 200. The Shopify
        # client logs them at WARNING; we promote them to
        # AdapterError so the router can fall back / retry.
        errors = response.get("errors")
        if errors:
            messages = []
            for e in errors:
                if isinstance(e, dict):
                    messages.append(str(e.get("message", e)))
                else:
                    messages.append(str(e))
            raise AdapterError(
                self.name,
                f"GraphQL errors: {'; '.join(messages)[:300]}",
            )

        data = response.get("data")
        if not isinstance(data, dict):
            raise AdapterError(
                self.name,
                f"GraphQL response missing 'data' field",
            )
        return data

    # ── User errors helper ─────────────────────────────────────

    def _check_user_errors(
        self,
        result: dict[str, Any],
        mutation_name: str,
    ) -> list[dict[str, Any]]:
        """Shopify mutations return a ``userErrors`` list inside
        the mutation payload (e.g. ``fulfillmentCreate.userErrors``)
        for business-rule failures (invalid arguments, missing
        required fields, …). They are NOT GraphQL errors and
        live next to the success payload, so the caller has to
        check them explicitly.

        Returns the list. Raises ``AdapterValidationError`` if
        non-empty so the router does NOT fall back — these are
        caller bugs, not vendor outages.
        """
        payload = result.get(mutation_name)
        if not isinstance(payload, dict):
            return []
        user_errors = payload.get("userErrors") or []
        if not isinstance(user_errors, list):
            return []
        if user_errors:
            messages = []
            for e in user_errors:
                if isinstance(e, dict):
                    field = ".".join(e.get("field", []) or [])
                    msg = e.get("message", "")
                    messages.append(f"{field}: {msg}" if field else msg)
            raise AdapterValidationError(
                self.name,
                f"{mutation_name} userErrors: {'; '.join(messages)[:300]}",
            )
        return user_errors

    # ── Convenience for ``_execute`` overrides ────────────────

    def _success(
        self,
        capability: Capability,
        data: dict[str, Any],
        **extra: Any,
    ) -> AdapterResult:
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data=data,
            **extra,
        )
