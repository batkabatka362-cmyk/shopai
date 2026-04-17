"""MetabaseAdapter — Metabase BI / dashboarding query access.

Metabase is an open-source BI tool used by tens of thousands of
companies for dashboards, ad-hoc SQL, and scheduled reports.
Unlike PostHog and Mixpanel (event-capture analytics), Metabase
is READ-ONLY from the brain's perspective — it's where the
warehouse lives, not where events land.

This adapter surfaces Metabase under the ANALYTICS_QUERY
capability only. ``ANALYTICS_TRACK_EVENT`` and
``ANALYTICS_IDENTIFY`` make no sense for Metabase (it doesn't
capture; it queries) and raise ``AdapterValidationError`` so
the router never mis-routes an ingest call into a BI tool.

Two query modes:

  * **Card mode** — ``params = {"card_id": 42, ...}`` runs a
    saved question and returns its rows. This is the mode
    dashboards use and the primary interface for governed data.

  * **Dataset mode** — ``params = {"database_id": 1,
    "sql": "SELECT ..."}`` runs ad-hoc SQL against a connected
    database. Useful for the brain to ask questions that no
    one has saved as a card yet, gated by Metabase's own SQL
    permissions.

Configuration::

    METABASE_URL=https://metabase.example.com      # required
    METABASE_API_KEY=mb_...                        # Metabase 0.49+

Auth: ``X-API-KEY`` header. Session-based auth (POST /api/session
with username+password) is deliberately NOT supported — session
tokens expire after 14 days and require a refresh loop that
doesn't belong in a thin adapter. Operators on Metabase < 0.49
should upgrade or front Metabase with a proxy that issues a
static token.

Reference: https://www.metabase.com/docs/latest/api-documentation
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
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
from ._base import AnalyticsBaseAdapter

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False


# Endpoints that return text/csv rather than application/json.
# The base's `_http_post` would blow up calling `.json()` on CSV,
# so the Metabase adapter overrides `_http_post` to branch on the
# URL suffix and return raw text for these paths.
_CSV_URL_SUFFIX = "/query/csv"


class MetabaseAdapter(AnalyticsBaseAdapter):
    """Metabase BI query adapter (read-only)."""

    name = "metabase"
    # Metabase only surfaces ANALYTICS_QUERY — narrowing the
    # capabilities set prevents the router from routing
    # track/identify calls here just because another analytics
    # adapter (PostHog, Mixpanel) is unavailable.
    capabilities = {Capability.ANALYTICS_QUERY}

    config_alias = "metabase_api_key"

    # Default priority is below PostHog (85) so track-event
    # calls never wander over — belt-and-braces beside the
    # narrowed capability set.
    priority = 70
    cost_per_call = 0.0
    timeout: float = 30.0  # BI queries can be slow.

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        """True when METABASE_URL + METABASE_API_KEY are both set.

        The base's is_configured requires base_url AND config_alias
        AND an api key; since base_url is dynamic (per operator)
        rather than a class constant, we reimplement the check.
        """
        if not _REQUESTS_AVAILABLE:
            return False
        if not get_config().get("metabase_url"):
            return False
        if not get_config().get(self.config_alias):
            return False
        return True

    def _get_base_url(self) -> str:
        url = get_config().get("metabase_url")
        if not url:
            raise AdapterNotConfigured(
                self.name, "METABASE_URL not set",
            )
        return str(url).rstrip("/")

    # ── Auth ───────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        """Metabase 0.49+ uses ``X-API-KEY`` for programmatic
        access — that's the only scheme this adapter supports.
        Session auth (POST /api/session) expires after 14 days
        and needs a refresh loop; staying out of scope keeps
        the adapter thin."""
        return {
            "X-API-KEY": self._api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Unsupported capabilities ──────────────────────────────

    def _do_track(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise AdapterValidationError(
            self.name,
            "Metabase is read-only; ANALYTICS_TRACK_EVENT is not supported. "
            "Use PostHog or Mixpanel for event ingest.",
        )

    def _do_identify(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise AdapterValidationError(
            self.name,
            "Metabase has no user-identify concept; "
            "ANALYTICS_IDENTIFY is not supported.",
        )

    # ── Query (card or ad-hoc SQL) ────────────────────────────

    def _do_query(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        """Run a Metabase card or ad-hoc SQL.

        Params (exactly one mode):

          Card mode:
            * ``card_id``    (int)  — required
            * ``parameters`` (list) — optional parameterized values
            * ``format``     (str)  — "json" (default) or "csv"

          Dataset mode:
            * ``database_id`` (int) — required
            * ``sql``         (str) — required
            * ``parameters``  (list, optional)
            * ``template_tags`` (dict, optional)
        """
        card_id = params.get("card_id")
        sql = params.get("sql") or params.get("query")
        database_id = params.get("database_id")

        # Exactly one mode must be chosen. Mixing them (e.g.
        # card_id + sql) is almost always a caller bug — refuse
        # rather than silently picking a winner.
        if card_id is not None and sql:
            raise AdapterValidationError(
                self.name,
                "pass either 'card_id' OR 'sql'+'database_id', not both",
            )
        if card_id is None and not sql:
            raise AdapterValidationError(
                self.name,
                "one of 'card_id' or 'sql'+'database_id' is required",
            )

        if card_id is not None:
            return self._query_card(capability, params, card_id)
        return self._query_dataset(capability, params, sql, database_id)

    def _query_card(
        self,
        capability: Capability,
        params: dict[str, Any],
        card_id: Any,
    ) -> AdapterResult:
        """POST /api/card/:id/query — runs the card's definition
        server-side with the caller's parameters.

        The ``format`` param lets the caller ask for JSON (default,
        structured) or CSV (cheap for large result sets — the
        brain's summariser can stream it). Format defaults to
        JSON because downstream consumers expect structured rows.
        """
        try:
            card_id_int = int(card_id)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name, f"'card_id' must be int, got {card_id!r}",
            ) from exc

        fmt = str(params.get("format") or "json").lower()
        if fmt not in ("json", "csv"):
            raise AdapterValidationError(
                self.name, "'format' must be 'json' or 'csv'",
            )

        url = (
            f"{self._get_base_url()}/api/card/{card_id_int}/query/{fmt}"
        )
        body: dict[str, Any] = {}
        if params.get("parameters"):
            body["parameters"] = params["parameters"]

        raw = self._http_post(url, body, headers=self._auth_headers())
        rows, columns = self._extract_rows_columns(raw, fmt)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "rows": rows,
                "columns": columns,
                "count": len(rows),
                "card_id": card_id_int,
                "format": fmt,
            },
            raw=raw,
        )

    def _query_dataset(
        self,
        capability: Capability,
        params: dict[str, Any],
        sql: str,
        database_id: Any,
    ) -> AdapterResult:
        """POST /api/dataset — runs ad-hoc SQL against a
        database the caller names by ID. Metabase's own
        permissions model gates which SQL the API-key principal
        can run, so this adapter doesn't do SQL sanitisation —
        Metabase is the authoritative policy point.
        """
        if database_id is None:
            raise AdapterValidationError(
                self.name,
                "'database_id' is required when using 'sql' mode",
            )
        try:
            db_id_int = int(database_id)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name,
                f"'database_id' must be int, got {database_id!r}",
            ) from exc

        url = f"{self._get_base_url()}/api/dataset"
        body: dict[str, Any] = {
            "type": "native",
            "database": db_id_int,
            "native": {"query": str(sql)},
        }
        if params.get("template_tags"):
            body["native"]["template-tags"] = params["template_tags"]
        if params.get("parameters"):
            body["parameters"] = params["parameters"]

        raw = self._http_post(url, body, headers=self._auth_headers())
        rows, columns = self._extract_rows_columns(raw, "json")

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "rows": rows,
                "columns": columns,
                "count": len(rows),
                "database_id": db_id_int,
            },
            raw=raw,
        )

    # ── HTTP override (CSV support) ───────────────────────────

    def _http_post(
        self,
        url: str,
        body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Metabase's ``/api/card/:id/query/csv`` endpoint returns
        ``text/csv``, not JSON. The base adapter's ``_http_post``
        unconditionally calls ``response.json()``, which would
        ``ValueError`` on CSV and surface as a confusing
        ``invalid JSON`` error. We override here to hand back raw
        text when the path ends in ``/query/csv``; every other
        endpoint still flows through the normal JSON parser."""
        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        if not url.endswith(_CSV_URL_SUFFIX):
            return super()._http_post(url, body, headers=headers)

        hdrs = headers or self._auth_headers()
        # CSV endpoint returns text — advertise that in Accept so
        # Metabase doesn't try to content-negotiate JSON.
        hdrs = {**hdrs, "Accept": "text/csv"}

        try:
            response = _requests.post(
                url, json=body, headers=hdrs, timeout=self.timeout,
            )
        except _requests.Timeout as exc:  # type: ignore[union-attr]
            raise AdapterTimeout(
                self.name, f"timeout after {self.timeout}s",
            ) from exc
        except _requests.ConnectionError as exc:  # type: ignore[union-attr]
            raise AdapterUnavailable(
                self.name, f"connection error: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name, f"HTTP POST failed: {exc}",
            ) from exc

        if response.status_code >= 400:
            snippet = (getattr(response, "text", "") or "")[:200]
            if response.status_code in (401, 403):
                raise AdapterAuthError(self.name, snippet)
            if response.status_code == 429:
                raise AdapterRateLimited(self.name, snippet)
            raise AdapterError(
                self.name,
                f"Metabase returned {response.status_code}: {snippet}",
            )

        return response.text or ""

    # ── Response normalisation ────────────────────────────────

    @staticmethod
    def _extract_rows_columns(
        raw: Any, fmt: str,
    ) -> tuple[list[Any], list[str]]:
        """Metabase's /api/dataset and /api/card/:id/query/json
        responses wrap rows in ``{"data": {"rows": [...], "cols":
        [{"name": ...}, ...]}}``. /api/card/:id/query/csv returns
        raw CSV text; we hand it back as a single 'rows' string
        so the caller can stream-parse without this adapter
        inventing a CSV dialect.
        """
        if fmt == "csv":
            # CSV endpoints return a text body; _http_post
            # already parsed JSON. If the caller asked for CSV
            # and got a dict, respect that and fall through
            # to JSON extraction so we never silently drop rows.
            if isinstance(raw, str):
                return ([raw], ["csv"])

        if not isinstance(raw, dict):
            return ([], [])

        data = raw.get("data")
        if not isinstance(data, dict):
            return ([], [])

        rows = data.get("rows")
        if not isinstance(rows, list):
            rows = []

        cols_raw = data.get("cols") or []
        columns: list[str] = []
        for c in cols_raw:
            if isinstance(c, dict):
                name = c.get("name") or c.get("display_name") or ""
                columns.append(str(name))
            else:
                columns.append(str(c))

        return (rows, columns)
