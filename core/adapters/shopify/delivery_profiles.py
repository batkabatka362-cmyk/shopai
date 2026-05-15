"""ShopifyDeliveryProfilesAdapter — shipping zones + rates read.

Delivery profiles are how Shopify configures shipping: which products
ship to which countries / regions, and what rates apply (flat,
weight-based, price-based, calculated, free above threshold). ShopAI's
delivery + fulfillment engines read these to:

  * Quote shipping correctly in the cart preview / draft order calc.
  * Choose the right warehouse for an order based on the destination
    zone match.
  * Surface "you don't ship here" diagnostics when an ad campaign
    targets a region with no rate.

Capabilities (read-only — write API is rich but out of scope for an
autonomous operator; merchants configure shipping in the admin UI):

  * ``SHOPIFY_LIST_DELIVERY_PROFILES`` — list profiles + their zones.
  * ``SHOPIFY_GET_DELIVERY_PROFILE``   — single profile with full
    zone / location / rate detail.
  * ``SHOPIFY_GET_DELIVERY_SETTINGS``  — store-wide delivery config
    (legacy mode flag, default profile).

Pattern E note: the connection ``deliveryProfiles`` is gated by
``read_shipping`` scope. Stores without the scope hit a precise
ACCESS_DENIED at the field level.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


# Compact fields for the list view — no nested rates per zone since
# that explodes the response payload for stores with many profiles.
_PROFILE_LIST_FIELDS = """
id
name
default
legacyMode
profileLocationGroups {
  locationGroup {
    id
    locations(first: 50) {
      edges {
        node {
          id
          name
        }
      }
    }
  }
  locationGroupZones(first: 50) {
    edges {
      node {
        zone {
          id
          name
          countries {
            id
            code { countryCode }
            provinces {
              id
              code
            }
          }
        }
        methodDefinitionCounts {
          participantDefinitionsCount
          rateDefinitionsCount
        }
      }
    }
  }
}
""".strip()


# Full fields for the single-get path — includes per-zone rate detail.
_PROFILE_FULL_FIELDS = """
id
name
default
legacyMode
profileLocationGroups {
  locationGroup {
    id
    locations(first: 50) {
      edges {
        node {
          id
          name
        }
      }
    }
  }
  locationGroupZones(first: 50) {
    edges {
      node {
        zone {
          id
          name
          countries {
            id
            code { countryCode }
            provinces {
              id
              code
              name
            }
          }
        }
        methodDefinitions(first: 100) {
          edges {
            node {
              id
              name
              active
              description
              rateProvider {
                __typename
                ... on DeliveryRateDefinition {
                  id
                  price {
                    amount
                    currencyCode
                  }
                }
                ... on DeliveryParticipant {
                  id
                  carrierService {
                    id
                    name
                  }
                  fixedFee {
                    amount
                    currencyCode
                  }
                  percentageOfRateFee
                }
              }
            }
          }
        }
      }
    }
  }
}
""".strip()


_LIST_PROFILES_QUERY = f"""
query deliveryProfiles($first: Int!, $after: String) {{
  deliveryProfiles(first: $first, after: $after) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_PROFILE_LIST_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_PROFILE_QUERY = f"""
query deliveryProfile($id: ID!) {{
  deliveryProfile(id: $id) {{
    {_PROFILE_FULL_FIELDS}
  }}
}}
""".strip()


_GET_SETTINGS_QUERY = """
query deliverySettings {
  deliverySettings {
    legacyModeBlocked {
      blocked
      reasons
    }
    legacyModeProfiles
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 25  # profiles can be heavy
_MAX_LIST_LIMIT = 100


class ShopifyDeliveryProfilesAdapter(ShopifyBaseAdapter):
    name = "shopify_delivery_profiles"
    capabilities = {
        Capability.SHOPIFY_LIST_DELIVERY_PROFILES,
        Capability.SHOPIFY_GET_DELIVERY_PROFILE,
        Capability.SHOPIFY_GET_DELIVERY_SETTINGS,
    }
    required_scopes = frozenset({"read_shipping"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_DELIVERY_PROFILES:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_DELIVERY_PROFILE:
            return self._get(params)
        if capability == Capability.SHOPIFY_GET_DELIVERY_SETTINGS:
            return self._get_settings(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ───────────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                self.name, "'cursor' must be a string or None",
            )

        data = self._gql(_LIST_PROFILES_QUERY, {
            "first": limit, "after": cursor,
        })
        envelope = data.get("deliveryProfiles") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        profiles = [
            self._normalise_profile(edge.get("node") or {}, with_rates=False)
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_DELIVERY_PROFILES,
            data={
                "profiles": profiles,
                "count": len(profiles),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get single profile ────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        profile_id = params.get("id") or params.get("profile_id")
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the delivery profile) is required",
            )
        data = self._gql(_GET_PROFILE_QUERY, {"id": profile_id.strip()})
        node = data.get("deliveryProfile") or {}
        return self._success(
            Capability.SHOPIFY_GET_DELIVERY_PROFILE,
            data={
                "profile": self._normalise_profile(node, with_rates=True),
                "found": bool(node),
            },
        )

    # ── Get settings ───────────────────────────────────────────────

    def _get_settings(self, _params: dict[str, Any]) -> Any:
        data = self._gql(_GET_SETTINGS_QUERY, {})
        settings = data.get("deliverySettings") or {}
        legacy_blocked = settings.get("legacyModeBlocked") or {}
        return self._success(
            Capability.SHOPIFY_GET_DELIVERY_SETTINGS,
            data={
                "legacy_mode_blocked": bool(
                    legacy_blocked.get("blocked", False)
                    if isinstance(legacy_blocked, dict) else False
                ),
                "legacy_blocked_reasons": list(
                    legacy_blocked.get("reasons", [])
                    if isinstance(legacy_blocked, dict) else []
                ),
                "legacy_mode_profiles": bool(
                    settings.get("legacyModeProfiles", False)
                ),
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @classmethod
    def _normalise_profile(
        cls, node: dict[str, Any], with_rates: bool,
    ) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        location_groups_raw = node.get("profileLocationGroups") or []
        location_groups = []
        for lg in location_groups_raw:
            if not isinstance(lg, dict):
                continue
            group = lg.get("locationGroup") or {}
            location_edges = (
                (group.get("locations") or {}).get("edges") or []
            ) if isinstance(group, dict) else []
            locations = [
                {
                    "id": (e.get("node") or {}).get("id", "") or "",
                    "name": (e.get("node") or {}).get("name", "") or "",
                }
                for e in location_edges if isinstance(e, dict)
            ]
            zone_edges = (
                (lg.get("locationGroupZones") or {}).get("edges") or []
            )
            zones = [
                cls._normalise_zone(e.get("node") or {}, with_rates=with_rates)
                for e in zone_edges if isinstance(e, dict)
            ]
            location_groups.append({
                "location_group_id": (
                    group.get("id", "") if isinstance(group, dict) else ""
                ) or "",
                "locations": locations,
                "zones": zones,
            })
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "default": bool(node.get("default", False)),
            "legacy_mode": bool(node.get("legacyMode", False)),
            "location_groups": location_groups,
        }

    @classmethod
    def _normalise_zone(
        cls, group_zone: dict[str, Any], with_rates: bool,
    ) -> dict[str, Any]:
        if not isinstance(group_zone, dict):
            return {}
        zone = group_zone.get("zone") or {}
        countries_raw = zone.get("countries") or []
        countries = []
        for c in countries_raw:
            if not isinstance(c, dict):
                continue
            code = c.get("code") or {}
            country_code = (
                code.get("countryCode", "") if isinstance(code, dict) else ""
            ) or ""
            provinces_raw = c.get("provinces") or []
            provinces = [
                {
                    "id": p.get("id", "") or "",
                    "code": p.get("code", "") or "",
                    "name": p.get("name", "") or "",
                }
                for p in provinces_raw if isinstance(p, dict)
            ]
            countries.append({
                "id": c.get("id", "") or "",
                "country_code": country_code,
                "provinces": provinces,
            })

        out: dict[str, Any] = {
            "zone_id": (
                zone.get("id", "") if isinstance(zone, dict) else ""
            ) or "",
            "zone_name": (
                zone.get("name", "") if isinstance(zone, dict) else ""
            ) or "",
            "countries": countries,
        }

        if with_rates:
            method_edges = (
                (group_zone.get("methodDefinitions") or {}).get("edges") or []
            )
            out["methods"] = [
                cls._normalise_method(e.get("node") or {})
                for e in method_edges if isinstance(e, dict)
            ]
        else:
            counts = group_zone.get("methodDefinitionCounts") or {}
            out["rate_count"] = int(
                (counts.get("rateDefinitionsCount") or 0)
                if isinstance(counts, dict) else 0
            )
            out["participant_count"] = int(
                (counts.get("participantDefinitionsCount") or 0)
                if isinstance(counts, dict) else 0
            )

        return out

    @staticmethod
    def _normalise_method(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        provider = node.get("rateProvider") or {}
        kind = (
            provider.get("__typename", "")
            if isinstance(provider, dict) else ""
        ) or ""
        out = {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "active": bool(node.get("active", False)),
            "description": node.get("description", "") or "",
            "kind": kind,
        }
        if kind == "DeliveryRateDefinition":
            price = (
                provider.get("price", {})
                if isinstance(provider, dict) else {}
            ) or {}
            out["price"] = (
                price.get("amount", "") if isinstance(price, dict) else ""
            ) or ""
            out["currency_code"] = (
                price.get("currencyCode", "")
                if isinstance(price, dict) else ""
            ) or ""
        elif kind == "DeliveryParticipant":
            carrier = (
                provider.get("carrierService", {})
                if isinstance(provider, dict) else {}
            ) or {}
            out["carrier_id"] = (
                carrier.get("id", "") if isinstance(carrier, dict) else ""
            ) or ""
            out["carrier_name"] = (
                carrier.get("name", "")
                if isinstance(carrier, dict) else ""
            ) or ""
            fixed = (
                provider.get("fixedFee", {})
                if isinstance(provider, dict) else {}
            ) or {}
            out["fixed_fee"] = (
                fixed.get("amount", "") if isinstance(fixed, dict) else ""
            ) or ""
            pct = (
                provider.get("percentageOfRateFee", 0)
                if isinstance(provider, dict) else 0
            )
            try:
                out["percentage_fee"] = float(pct or 0)
            except (TypeError, ValueError):
                out["percentage_fee"] = 0.0
        return out
