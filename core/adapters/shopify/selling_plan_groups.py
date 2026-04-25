"""ShopifySellingPlanGroupsAdapter — subscription offer rules read.

Selling plan groups are the "subscribe & save" offer container —
each group has 1..N selling plans (e.g. "deliver every week, 10%
off", "deliver every month, 15% off"), and each is attached to one
or more products / variants. ShopAI's subscription engine reads them
to:

  * Quote subscription pricing in cart preview (alongside one-time
    pricing).
  * Pick the right plan for an auto-replenishment recommendation
    based on customer purchase cadence.
  * Surface "product is subscribable" badges in the storefront /
    AI-generated marketing copy.

Companion to ``subscriptions.py`` (which manages live
SubscriptionContracts — actual customer subscriptions). Selling
plans are the OFFER side; contracts are the EXECUTION side.

Capabilities (read-only — write API exists but is rich and Plus-tier
gated, out of scope for autonomous default):

  * ``SHOPIFY_LIST_SELLING_PLAN_GROUPS`` — paginated list with filter.
  * ``SHOPIFY_GET_SELLING_PLAN_GROUP``   — single group with full
    plan + pricing-policy detail.

Pattern E note: ``sellingPlanGroups`` is gated by the
``read_products`` scope (selling plans live alongside products in
the catalog API).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


# Compact list-view fields. We expose plan count + product count so
# engines can pick the right group without paying for the full plan
# + product expansion.
_GROUP_LIST_FIELDS = """
id
name
merchantCode
options
position
description
appId
sellingPlans(first: 1) {
  edges {
    node {
      id
    }
  }
}
products(first: 1) {
  edges {
    node {
      id
    }
  }
}
""".strip()


# Full fields for the single-get path.
_GROUP_FULL_FIELDS = """
id
name
merchantCode
options
position
description
summary
appId
createdAt
sellingPlans(first: 50) {
  edges {
    node {
      id
      name
      description
      options
      position
      category
      billingPolicy {
        __typename
        ... on SellingPlanRecurringBillingPolicy {
          interval
          intervalCount
          minCycles
          maxCycles
          anchors {
            day
            month
            type
          }
        }
        ... on SellingPlanFixedBillingPolicy {
          checkoutCharge {
            type
          }
          remainingBalanceChargeTrigger
          remainingBalanceChargeExactTime
          remainingBalanceChargeTimeAfterCheckout
        }
      }
      deliveryPolicy {
        __typename
        ... on SellingPlanRecurringDeliveryPolicy {
          interval
          intervalCount
          preAnchorBehavior
          cutoff
          intent
        }
      }
      pricingPolicies {
        __typename
        ... on SellingPlanFixedPricingPolicy {
          adjustmentType
          adjustmentValue {
            __typename
            ... on MoneyV2 {
              amount
              currencyCode
            }
            ... on SellingPlanPricingPolicyPercentageValue {
              percentage
            }
          }
        }
        ... on SellingPlanRecurringPricingPolicy {
          afterCycle
          adjustmentType
          adjustmentValue {
            __typename
            ... on MoneyV2 {
              amount
              currencyCode
            }
            ... on SellingPlanPricingPolicyPercentageValue {
              percentage
            }
          }
        }
      }
    }
  }
}
products(first: 50) {
  edges {
    node {
      id
      title
      handle
    }
  }
}
""".strip()


_LIST_GROUPS_QUERY = f"""
query sellingPlanGroups(
  $first: Int!,
  $after: String,
  $query: String
) {{
  sellingPlanGroups(
    first: $first,
    after: $after,
    query: $query
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_GROUP_LIST_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_GROUP_QUERY = f"""
query sellingPlanGroup($id: ID!) {{
  sellingPlanGroup(id: $id) {{
    {_GROUP_FULL_FIELDS}
  }}
}}
""".strip()


_DEFAULT_LIST_LIMIT = 25
_MAX_LIST_LIMIT = 100


class ShopifySellingPlanGroupsAdapter(ShopifyBaseAdapter):
    name = "shopify_selling_plan_groups"
    capabilities = {
        Capability.SHOPIFY_LIST_SELLING_PLAN_GROUPS,
        Capability.SHOPIFY_GET_SELLING_PLAN_GROUP,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_SELLING_PLAN_GROUPS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_SELLING_PLAN_GROUP:
            return self._get(params)
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

        variables: dict[str, Any] = {"first": limit, "after": cursor}

        query_filter = params.get("query")
        if query_filter is not None:
            if not isinstance(query_filter, str):
                raise AdapterValidationError(
                    self.name, "'query' must be a string",
                )
            variables["query"] = query_filter

        data = self._gql(_LIST_GROUPS_QUERY, variables)
        envelope = data.get("sellingPlanGroups") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        groups = [
            self._normalise_group_compact(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_SELLING_PLAN_GROUPS,
            data={
                "groups": groups,
                "count": len(groups),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        group_id = params.get("id") or params.get("group_id")
        if not isinstance(group_id, str) or not group_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the selling plan group) is required",
            )
        data = self._gql(_GET_GROUP_QUERY, {"id": group_id.strip()})
        node = data.get("sellingPlanGroup") or {}
        return self._success(
            Capability.SHOPIFY_GET_SELLING_PLAN_GROUP,
            data={
                "group": self._normalise_group_full(node),
                "found": bool(node),
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_group_compact(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        # We asked for only the first edge of plans / products to get
        # an existence indicator. The actual count comes from the
        # connection-level field if present, but Shopify doesn't
        # expose totalCount on these connections — return whether at
        # least one exists rather than fabricating a fake count.
        plan_edges = (node.get("sellingPlans") or {}).get("edges") or []
        product_edges = (node.get("products") or {}).get("edges") or []
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "merchant_code": node.get("merchantCode", "") or "",
            "description": node.get("description", "") or "",
            "options": list(node.get("options") or []),
            "position": int(node.get("position") or 0),
            "app_id": node.get("appId", "") or "",
            "has_plans": len(plan_edges) > 0,
            "has_products": len(product_edges) > 0,
        }

    @classmethod
    def _normalise_group_full(cls, node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        plan_edges = (node.get("sellingPlans") or {}).get("edges") or []
        plans = [
            cls._normalise_plan(e.get("node") or {})
            for e in plan_edges if isinstance(e, dict)
        ]
        product_edges = (node.get("products") or {}).get("edges") or []
        products = [
            {
                "id": (e.get("node") or {}).get("id", "") or "",
                "title": (e.get("node") or {}).get("title", "") or "",
                "handle": (e.get("node") or {}).get("handle", "") or "",
            }
            for e in product_edges if isinstance(e, dict)
        ]
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "merchant_code": node.get("merchantCode", "") or "",
            "description": node.get("description", "") or "",
            "summary": node.get("summary", "") or "",
            "options": list(node.get("options") or []),
            "position": int(node.get("position") or 0),
            "app_id": node.get("appId", "") or "",
            "created_at": node.get("createdAt", "") or "",
            "selling_plans": plans,
            "products": products,
        }

    @classmethod
    def _normalise_plan(cls, node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        billing = node.get("billingPolicy") or {}
        delivery = node.get("deliveryPolicy") or {}
        pricing_raw = node.get("pricingPolicies") or []
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "description": node.get("description", "") or "",
            "options": list(node.get("options") or []),
            "position": int(node.get("position") or 0),
            "category": node.get("category", "") or "",
            "billing": cls._normalise_billing(billing),
            "delivery": cls._normalise_delivery(delivery),
            "pricing": [
                cls._normalise_pricing(p) for p in pricing_raw
                if isinstance(p, dict)
            ],
        }

    @staticmethod
    def _normalise_billing(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        kind = node.get("__typename", "") or ""
        if kind == "SellingPlanRecurringBillingPolicy":
            anchors_raw = node.get("anchors") or []
            anchors = [
                {
                    "day": int(a.get("day") or 0),
                    "month": int(a.get("month") or 0),
                    "type": a.get("type", "") or "",
                }
                for a in anchors_raw if isinstance(a, dict)
            ]
            return {
                "kind": "RECURRING",
                "interval": node.get("interval", "") or "",
                "interval_count": int(node.get("intervalCount") or 0),
                "min_cycles": int(node.get("minCycles") or 0),
                "max_cycles": int(node.get("maxCycles") or 0),
                "anchors": anchors,
            }
        if kind == "SellingPlanFixedBillingPolicy":
            checkout = node.get("checkoutCharge") or {}
            return {
                "kind": "FIXED",
                "checkout_charge_type": (
                    checkout.get("type", "")
                    if isinstance(checkout, dict) else ""
                ) or "",
                "remaining_balance_trigger": (
                    node.get("remainingBalanceChargeTrigger", "") or ""
                ),
                "remaining_balance_exact_time": (
                    node.get("remainingBalanceChargeExactTime", "") or ""
                ),
                "remaining_balance_after_checkout": (
                    node.get("remainingBalanceChargeTimeAfterCheckout", "") or ""
                ),
            }
        return {"kind": kind}

    @staticmethod
    def _normalise_delivery(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        kind = node.get("__typename", "") or ""
        if kind == "SellingPlanRecurringDeliveryPolicy":
            return {
                "kind": "RECURRING",
                "interval": node.get("interval", "") or "",
                "interval_count": int(node.get("intervalCount") or 0),
                "pre_anchor_behavior": (
                    node.get("preAnchorBehavior", "") or ""
                ),
                "cutoff": int(node.get("cutoff") or 0),
                "intent": node.get("intent", "") or "",
            }
        return {"kind": kind}

    @staticmethod
    def _normalise_pricing(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        kind = node.get("__typename", "") or ""
        adj_value = node.get("adjustmentValue") or {}
        adj_kind = (
            adj_value.get("__typename", "")
            if isinstance(adj_value, dict) else ""
        ) or ""
        out: dict[str, Any] = {
            "kind": "FIXED" if kind == "SellingPlanFixedPricingPolicy"
                   else "RECURRING" if kind == "SellingPlanRecurringPricingPolicy"
                   else kind,
            "adjustment_type": node.get("adjustmentType", "") or "",
        }
        if kind == "SellingPlanRecurringPricingPolicy":
            out["after_cycle"] = int(node.get("afterCycle") or 0)
        if adj_kind == "MoneyV2":
            out["adjustment_money_amount"] = (
                adj_value.get("amount", "")
                if isinstance(adj_value, dict) else ""
            ) or ""
            out["adjustment_money_currency"] = (
                adj_value.get("currencyCode", "")
                if isinstance(adj_value, dict) else ""
            ) or ""
        elif adj_kind == "SellingPlanPricingPolicyPercentageValue":
            try:
                out["adjustment_percentage"] = float(
                    (adj_value.get("percentage") or 0)
                    if isinstance(adj_value, dict) else 0
                )
            except (TypeError, ValueError):
                out["adjustment_percentage"] = 0.0
        return out
