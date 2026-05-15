"""ShopifyAnalyticsAdapter — execute ShopifyQL queries.

ShopifyQL is Shopify's SQL-like DSL for the analytics API. It lets
engines ask questions like "what were daily sales last 30 days?" or
"which products had > $1000 revenue this week?" without scraping the
admin UI or hand-rolling REST aggregations.

Why ShopAI needs it:

  * **ROAS guardrails.** The pricing engine wants per-SKU revenue
    over rolling windows to decide who's still earning their slot
    and who should be paused.
  * **Winning-products engine.** Cross-checks ad-side velocity claims
    against actual checkout-side revenue before promoting a SKU.
  * **Analytics dashboards.** ShopAI surfaces trend lines without
    asking the merchant to install a separate reporting app.

Capability:

  * ``SHOPIFY_RUN_ANALYTICS_QUERY`` — execute one ShopifyQL string
    and get back a normalised list of row dicts keyed by column
    name. Engines write::

        adapter.execute(Capability.SHOPIFY_RUN_ANALYTICS_QUERY, {
            "query": '''
                FROM orders
                SHOW count(orders) AS orders, sum(total_price) AS revenue
                SINCE -7d
                GROUP BY date
                ORDER BY date ASC
            ''',
        })

    and get::

        result.data["rows"] == [
            {"date": "2026-04-19", "orders": 12, "revenue": 980.50},
            ...
        ]

Single-statement only — ShopifyQL doesn't support multi-statement
batching, so the adapter doesn't either. Engines that need several
metrics make several calls (each one is its own query budget anyway).

----

**Schema gating — important caveat.**

``Query.shopifyqlQuery`` is gated behind Shopify's "Level 2 access to
protected customer data" approval flow on top of the ``read_reports``
scope. For apps that haven't gone through the protected-customer-data
declaration the field is *hidden from the schema entirely*: a query
referencing it returns ``Field 'shopifyqlQuery' doesn't exist on type
'QueryRoot'`` even when the app's token has read_reports.

Caught live during smoke test against a dev store with a custom-
distribution app that has read_reports but no protected-data
declaration. The fix is paperwork, not code: the merchant goes
through the protected-data flow in the Partner Dashboard, then the
field re-appears.

The adapter's wire format follows the documented schema
(``tableData.rows`` + ``tableData.columns.{name, dataType,
displayName}`` + top-level ``parseErrors``). When the merchant
completes the gate, this adapter starts working without code changes.
"""
from __future__ import annotations

import json
from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


# Per the docs the response object exposes ``tableData`` and
# ``parseErrors`` directly — no union destructure required (the
# response was a union in earlier API versions but is flat now).
_RUN_QUERY_QUERY = """
query shopifyqlQuery($query: String!) {
  shopifyqlQuery(query: $query) {
    tableData {
      columns {
        name
        dataType
        displayName
      }
      rows
    }
    parseErrors {
      code
      message
    }
  }
}
""".strip()


class ShopifyAnalyticsAdapter(ShopifyBaseAdapter):
    name = "shopify_analytics"
    capabilities = {Capability.SHOPIFY_RUN_ANALYTICS_QUERY}
    # read_reports plus Level 2 protected-customer-data declaration
    # (see file docstring — schema-gated beyond OAuth).
    required_scopes = frozenset({"read_reports"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability != Capability.SHOPIFY_RUN_ANALYTICS_QUERY:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        query = params.get("query") or params.get("shopifyql")
        if not isinstance(query, str) or not query.strip():
            raise AdapterValidationError(
                "shopify_analytics",
                "'query' (a ShopifyQL string) is required",
            )

        data = self._gql(_RUN_QUERY_QUERY, {"query": query.strip()})
        envelope = data.get("shopifyqlQuery") or {}
        # Surface parse errors as adapter validation errors —
        # ShopifyQL syntax bugs are caller bugs, not vendor outages,
        # and the router shouldn't fall back on them.
        parse_errors = envelope.get("parseErrors") or []
        if isinstance(parse_errors, list) and parse_errors:
            messages = [
                f"{e.get('code', '')}: {e.get('message', '')}"
                for e in parse_errors if isinstance(e, dict)
            ]
            raise AdapterValidationError(
                "shopify_analytics",
                f"ShopifyQL parseErrors: {'; '.join(messages)[:300]}",
            )

        table_data = envelope.get("tableData") or {}
        columns_raw = table_data.get("columns") or []
        # Field is `rows` in the documented schema. Tolerate the
        # legacy `rowData` shape too (for older API versions still
        # exposing it) so the adapter doesn't break on schema flips.
        rows_raw = table_data.get("rows")
        if rows_raw is None:
            rows_raw = table_data.get("rowData") or []
        columns = self._normalise_columns(columns_raw)
        rows = self._rows_to_dicts(columns, rows_raw)

        return self._success(
            Capability.SHOPIFY_RUN_ANALYTICS_QUERY,
            data={
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _normalise_columns(raw: Any) -> list[dict[str, str]]:
        """Lift the GraphQL ``[ {name, dataType, displayName} ]`` array
        into the same shape but with snake_case keys so the engine
        consumers match the rest of ShopAI."""
        if not isinstance(raw, list):
            return []
        out: list[dict[str, str]] = []
        for c in raw:
            if not isinstance(c, dict):
                continue
            out.append({
                "name": c.get("name", "") or "",
                "data_type": c.get("dataType", "") or "",
                "display_name": c.get("displayName", "") or "",
            })
        return out

    @staticmethod
    def _rows_to_dicts(
        columns: list[dict[str, str]], rows_raw: Any,
    ) -> list[dict[str, Any]]:
        """Turn the parallel-arrays rowData shape into a list of
        dicts keyed by column name.

        Shopify returns ``rowData`` as ``[[col0, col1, ...], ...]``
        in the same order as ``columns``. Numeric columns come back
        as strings (Decimal); we coerce them to floats so engines
        can do arithmetic without re-casting.
        """
        if not isinstance(rows_raw, list):
            return []
        col_names = [c["name"] for c in columns]
        col_types = [c.get("data_type", "") for c in columns]
        out: list[dict[str, Any]] = []
        for row in rows_raw:
            if not isinstance(row, list):
                continue
            entry: dict[str, Any] = {}
            for i, value in enumerate(row):
                if i >= len(col_names):
                    break
                col_name = col_names[i]
                col_type = col_types[i].lower() if i < len(col_types) else ""
                entry[col_name] = _coerce_value(value, col_type)
            out.append(entry)
        return out


# Numeric ShopifyQL types whose string values we coerce to float so
# engines can do `revenue * 0.3` without re-casting.
_NUMERIC_TYPES = {
    "decimal", "currency", "money", "float", "double",
    "percent", "percentage",
}
_INT_TYPES = {"integer", "int", "long", "count"}


def _coerce_value(value: Any, col_type: str) -> Any:
    """Coerce ShopifyQL string-typed numerics to native Python types.

    Strings that *look* numeric but live in non-numeric columns are
    left as strings — caller might be doing exact-equality matching
    on an order id or SKU.
    """
    if value is None:
        return None
    if col_type in _NUMERIC_TYPES and isinstance(value, str):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if col_type in _INT_TYPES and isinstance(value, str):
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                # ShopifyQL sometimes returns count columns as
                # decimal-formatted strings ("12.0") even though the
                # column is logically an integer; tolerate that.
                return int(float(value))
            except (TypeError, ValueError):
                return value
    # JSON values come back as native dicts/lists already; pass
    # through. If a caller passed a complex value as JSON-string we
    # try to parse — engines that intentionally want the string can
    # opt out by using a non-json data_type.
    if col_type == "json" and isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return value
