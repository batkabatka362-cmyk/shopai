"""ShopifyMarketCRUDAdapter — markets write side.

Companion to ``markets.py`` (read-only LIST/GET/locales). The
read adapter deliberately deferred mutations on the grounds that
markets are "merchant-configured one-time setup". This adapter
ships the write side because a class of operator-facing
ShopAI flows actually need it:

  * **International expansion launches.** Operator approves a
    new-country test ("turn on Mexico for 30 days") — the
    expansion engine creates the market, attaches the country,
    sets up currency, then disables it 30 days later if the
    cohort metrics miss target.
  * **Market region rotation.** Pricing engine groups countries
    into one market for a campaign, then splits them back out.
    Add/remove-region calls support that.
  * **Sunset cleanup.** When a multi-country market is replaced
    by per-country markets the old one needs deletion — leaving
    it lingering causes mis-routing.

Capabilities:

  * ``SHOPIFY_CREATE_MARKET``         — marketCreate, friendly shape.
  * ``SHOPIFY_UPDATE_MARKET``         — marketUpdate. Pattern A: id at
    field level, NOT inside the input dict.
  * ``SHOPIFY_DELETE_MARKET``         — marketDelete. Pattern A.
  * ``SHOPIFY_ADD_MARKET_REGIONS``    — friendly wrapper around
    marketUpdate's ``conditionsToAdd.regionsCondition``.
  * ``SHOPIFY_DELETE_MARKET_REGION``  — friendly wrapper around
    marketUpdate's ``conditionsToDelete.regionsCondition`` (takes
    region IDs to remove from the market).

2026 schema notes (Pattern D — major rework):

  * ``MarketCreateInput.enabled``    →  removed; replaced with
    ``status: MarketStatus`` (``DRAFT``/``ACTIVE``).
  * ``MarketCreateInput.regions``    →  removed; replaced with
    ``conditions: MarketConditionsInput`` containing
    ``regionsCondition.regions[].countryCode``.
  * ``Market.enabled``/``primary``   →  removed; ``status`` and
    ``type: MarketType`` carry that information now.
  * ``Market.regions``               →  removed; replaced with
    ``Market.conditions.regionsCondition.regions``.
  * ``marketRegionsCreate``          →  removed; use
    ``marketUpdate(input: { conditions: { conditionsToAdd: {...}}})``.
  * ``marketRegionDelete``           →  removed; use
    ``marketUpdate(input: { conditions: { conditionsToDelete:
    {regionsCondition: {regionIds: [...]}}}})``.

Pattern E: ``marketCreate``/``marketUpdate``/``marketDelete``
require the ``write_markets`` access scope on top of
``read_markets``. Custom-app tokens that only requested
``read_markets`` get ``ACCESS_DENIED`` even when the wire format
is provably correct via introspection.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_MARKET_RESPONSE_FIELDS = """
id
name
handle
status
type
conditions {
  regionsCondition {
    applicationLevel
    regions(first: 50) {
      edges {
        node {
          id
          name
          ... on MarketRegionCountry {
            code
          }
        }
      }
    }
  }
}
""".strip()


_CREATE_MARKET_MUTATION = f"""
mutation marketCreate($input: MarketCreateInput!) {{
  marketCreate(input: $input) {{
    market {{
      {_MARKET_RESPONSE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_UPDATE_MARKET_MUTATION = f"""
mutation marketUpdate($id: ID!, $input: MarketUpdateInput!) {{
  marketUpdate(id: $id, input: $input) {{
    market {{
      {_MARKET_RESPONSE_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_DELETE_MARKET_MUTATION = """
mutation marketDelete($id: ID!) {
  marketDelete(id: $id) {
    deletedId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_VALID_COUNTRY_CODE_LEN = 2
_VALID_STATUSES = {"DRAFT", "ACTIVE"}


class ShopifyMarketCRUDAdapter(ShopifyBaseAdapter):
    name = "shopify_market_crud"
    capabilities = {
        Capability.SHOPIFY_CREATE_MARKET,
        Capability.SHOPIFY_UPDATE_MARKET,
        Capability.SHOPIFY_DELETE_MARKET,
        Capability.SHOPIFY_ADD_MARKET_REGIONS,
        Capability.SHOPIFY_DELETE_MARKET_REGION,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_MARKET:
            return self._create(params)
        if capability == Capability.SHOPIFY_UPDATE_MARKET:
            return self._update(params)
        if capability == Capability.SHOPIFY_DELETE_MARKET:
            return self._delete(params)
        if capability == Capability.SHOPIFY_ADD_MARKET_REGIONS:
            return self._add_regions(params)
        if capability == Capability.SHOPIFY_DELETE_MARKET_REGION:
            return self._remove_regions(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        market_input = self._build_create_input(params)
        data = self._gql(_CREATE_MARKET_MUTATION, {"input": market_input})
        self._check_user_errors(data, "marketCreate")
        payload = data.get("marketCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_MARKET,
            data={
                "market": self._normalise_market(
                    payload.get("market") or {}
                ),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        market_id = params.get("id") or params.get("market_id")
        if not isinstance(market_id, str) or not market_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the market) is required — Pattern "
                "A: id at field level, NOT inside input",
            )
        market_input = self._build_update_input(params)
        if not market_input:
            raise AdapterValidationError(
                self.name,
                "no patchable fields supplied — pass at least one of "
                "name/handle/status/conditions",
            )
        data = self._gql(_UPDATE_MARKET_MUTATION, {
            "id": market_id.strip(),
            "input": market_input,
        })
        self._check_user_errors(data, "marketUpdate")
        payload = data.get("marketUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_MARKET,
            data={
                "market": self._normalise_market(
                    payload.get("market") or {}
                ),
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        market_id = params.get("id") or params.get("market_id")
        if not isinstance(market_id, str) or not market_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the market) is required",
            )
        data = self._gql(_DELETE_MARKET_MUTATION, {"id": market_id.strip()})
        self._check_user_errors(data, "marketDelete")
        payload = data.get("marketDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_MARKET,
            data={
                "deleted_id": payload.get("deletedId", "") or "",
            },
        )

    # ── Add regions (friendly wrapper around marketUpdate) ────────

    def _add_regions(self, params: dict[str, Any]) -> Any:
        market_id = params.get("market_id") or params.get("marketId")
        if not isinstance(market_id, str) or not market_id.strip():
            raise AdapterValidationError(
                self.name,
                "'market_id' (Shopify GID) is required — Pattern A: "
                "marketId at field level",
            )
        regions = self._build_country_regions(params.get("regions"))
        # Pattern: MarketConditionsRegionsInput is a oneOf union —
        # exactly ONE of {regionIds, regions, applicationLevel}.
        # Sending regions + applicationLevel together fails with
        # "requires exactly one argument, but 2 were provided".
        market_input = {
            "conditions": {
                "conditionsToAdd": {
                    "regionsCondition": {"regions": regions},
                },
            },
        }
        data = self._gql(_UPDATE_MARKET_MUTATION, {
            "id": market_id.strip(),
            "input": market_input,
        })
        self._check_user_errors(data, "marketUpdate")
        payload = data.get("marketUpdate") or {}
        market = payload.get("market") or {}
        regions_out = self._extract_regions(market)
        return self._success(
            Capability.SHOPIFY_ADD_MARKET_REGIONS,
            data={
                "market_id": market.get("id", "") or "",
                "regions": regions_out,
                "count": len(regions_out),
            },
        )

    # ── Remove regions (friendly wrapper around marketUpdate) ─────

    def _remove_regions(self, params: dict[str, Any]) -> Any:
        market_id = params.get("market_id") or params.get("marketId")
        if not isinstance(market_id, str) or not market_id.strip():
            raise AdapterValidationError(
                self.name,
                "'market_id' (Shopify GID) is required",
            )
        region_ids_raw = (
            params.get("region_ids")
            or params.get("regionIds")
            or params.get("id")
        )
        if isinstance(region_ids_raw, str):
            region_ids_raw = [region_ids_raw]
        if not isinstance(region_ids_raw, list) or not region_ids_raw:
            raise AdapterValidationError(
                self.name,
                "'region_ids' must be a non-empty list of region GIDs "
                "(or a single GID via 'id')",
            )
        if not all(isinstance(r, str) for r in region_ids_raw):
            raise AdapterValidationError(
                self.name, "'region_ids' must contain only GID strings",
            )
        ids = [r.strip() for r in region_ids_raw if r.strip()]
        if not ids:
            raise AdapterValidationError(
                self.name, "'region_ids' contained only blanks",
            )
        market_input = {
            "conditions": {
                "conditionsToDelete": {
                    "regionsCondition": {
                        "regionIds": ids,
                    },
                },
            },
        }
        data = self._gql(_UPDATE_MARKET_MUTATION, {
            "id": market_id.strip(),
            "input": market_input,
        })
        self._check_user_errors(data, "marketUpdate")
        payload = data.get("marketUpdate") or {}
        market = payload.get("market") or {}
        regions_remaining = self._extract_regions(market)
        return self._success(
            Capability.SHOPIFY_DELETE_MARKET_REGION,
            data={
                "market_id": market.get("id", "") or "",
                "removed_ids": ids,
                "regions_remaining": regions_remaining,
            },
        )

    # ── Input builders ─────────────────────────────────────────────

    def _build_create_input(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise AdapterValidationError(
                self.name, "'name' is required (non-empty string)",
            )
        out: dict[str, Any] = {"name": name.strip()}

        handle = params.get("handle")
        if handle is not None:
            if not isinstance(handle, str) or not handle.strip():
                raise AdapterValidationError(
                    self.name, "'handle' must be a non-empty string",
                )
            out["handle"] = handle.strip()

        status = self._coerce_status(params)
        if status is not None:
            out["status"] = status

        # Friendly: callers can pass a flat regions list; we wrap it
        # as conditions.regionsCondition under the hood.
        # Pattern: regionsCondition is a oneOf — only the regions key
        # may be present (no applicationLevel alongside it).
        regions_raw = params.get("regions")
        if regions_raw is not None:
            regions = self._build_country_regions(regions_raw)
            out["conditions"] = {
                "regionsCondition": {"regions": regions},
            }

        return out

    def _build_update_input(self, params: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}

        name = params.get("name")
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise AdapterValidationError(
                    self.name, "'name' must be a non-empty string",
                )
            out["name"] = name.strip()

        handle = params.get("handle")
        if handle is not None:
            if not isinstance(handle, str) or not handle.strip():
                raise AdapterValidationError(
                    self.name, "'handle' must be a non-empty string",
                )
            out["handle"] = handle.strip()

        status = self._coerce_status(params)
        if status is not None:
            out["status"] = status

        # Power-user: pass conditions directly with conditionsToAdd /
        # conditionsToDelete already shaped to MarketConditionsUpdateInput.
        conditions = params.get("conditions")
        if conditions is not None:
            if not isinstance(conditions, dict):
                raise AdapterValidationError(
                    self.name, "'conditions' must be a dict",
                )
            out["conditions"] = conditions

        return out

    def _coerce_status(self, params: dict[str, Any]) -> str | None:
        # Accept friendly forms (enabled True/False) for backwards-friendly
        # ergonomics; they map to ACTIVE/DRAFT under the new schema.
        if "status" in params:
            raw = params["status"]
            if not isinstance(raw, str):
                raise AdapterValidationError(
                    self.name, "'status' must be a string",
                )
            up = raw.strip().upper()
            if up not in _VALID_STATUSES:
                raise AdapterValidationError(
                    self.name,
                    f"'status' must be one of {sorted(_VALID_STATUSES)}",
                )
            return up
        if "enabled" in params:
            return "ACTIVE" if bool(params["enabled"]) else "DRAFT"
        return None

    def _build_country_regions(self, raw: Any) -> list[dict[str, Any]]:
        """Translate friendly region shapes to MarketConditionsRegionInput.

        Accepts any of:
          * ``["US", "CA"]``       — bare ISO codes (most common).
          * ``[{"country_code": "US"}, {"country_code": "CA"}]``
          * ``[{"countryCode": "US"}]``
        """
        if not isinstance(raw, list) or not raw:
            raise AdapterValidationError(
                self.name,
                "'regions' must be a non-empty list of country codes "
                "or {country_code: 'XX'} dicts",
            )
        out: list[dict[str, Any]] = []
        for i, r in enumerate(raw):
            if isinstance(r, str):
                code = r.strip().upper()
            elif isinstance(r, dict):
                code_raw = (
                    r.get("country_code")
                    or r.get("countryCode")
                    or r.get("code")
                )
                if not isinstance(code_raw, str):
                    raise AdapterValidationError(
                        self.name,
                        f"regions[{i}] missing 'country_code'",
                    )
                code = code_raw.strip().upper()
            else:
                raise AdapterValidationError(
                    self.name,
                    f"regions[{i}] must be a string or dict",
                )
            if len(code) != _VALID_COUNTRY_CODE_LEN:
                raise AdapterValidationError(
                    self.name,
                    f"regions[{i}] '{code}' is not a 2-letter ISO code",
                )
            out.append({"countryCode": code})
        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _extract_regions(market: dict[str, Any]) -> list[dict[str, str]]:
        if not isinstance(market, dict):
            return []
        conditions = market.get("conditions") or {}
        regions_cond = (
            conditions.get("regionsCondition")
            if isinstance(conditions, dict) else None
        ) or {}
        edges = (regions_cond.get("regions") or {}).get("edges") or []
        regions: list[dict[str, str]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node") or {}
            regions.append({
                "id": node.get("id", "") or "",
                "name": node.get("name", "") or "",
                "country_code": node.get("code", "") or "",
            })
        return regions

    @classmethod
    def _normalise_market(cls, node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        conditions = node.get("conditions") or {}
        regions_cond = (
            conditions.get("regionsCondition")
            if isinstance(conditions, dict) else None
        ) or {}
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "handle": node.get("handle", "") or "",
            "status": node.get("status", "") or "",
            "type": node.get("type", "") or "",
            "regions": cls._extract_regions(node),
            "application_level": (
                regions_cond.get("applicationLevel", "")
                if isinstance(regions_cond, dict) else ""
            ) or "",
        }
