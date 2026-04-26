"""ShopifySubscriptionContractsAdapter — read + lifecycle on subscriptions.

ShopAI's subscription / retention engine watches per-contract events:
when a recurring billing fails, the engine pauses the contract until
the customer updates their card; when payment-on-file is restored,
the engine resumes; after N consecutive failures or an explicit
cancel signal, the engine ends the contract. All four signals
(read / pause / resume / cancel) need GraphQL access — without this
adapter the retention engine had to be wired through a third-party
subscription app.

Capabilities:

  * ``SHOPIFY_LIST_SUBSCRIPTION_CONTRACTS``   — paginate contracts
    with optional sort key / direction. Engines often want
    "all contracts where status = paused for > 30 days".
  * ``SHOPIFY_GET_SUBSCRIPTION_CONTRACT``     — fetch one with full
    line items + billing schedule + customer.
  * ``SHOPIFY_PAUSE_SUBSCRIPTION_CONTRACT``   —
    ``subscriptionContractPause``. Idempotent server-side; pausing
    an already-paused contract is a no-op userError that the
    adapter surfaces as a validation error.
  * ``SHOPIFY_RESUME_SUBSCRIPTION_CONTRACT``  —
    ``subscriptionContractActivate`` (Shopify's mutation name —
    "activate" reads as create-but-it-isn't, so the friendly cap
    name normalises to "resume").
  * ``SHOPIFY_CANCEL_SUBSCRIPTION_CONTRACT``  —
    ``subscriptionContractCancel``. Final state — there's no
    un-cancel; engines that want soft-cancel use pause instead.

Contract creation is intentionally NOT in this adapter — new
subscriptions originate from a checkout or a Selling Plan-attached
purchase, both merchant-driven. Engines mutate existing contracts.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CONTRACT_NODE_FIELDS = """
id
status
createdAt
updatedAt
nextBillingDate
currencyCode
customer {
  id
  email
  displayName
}
lines(first: 50) {
  edges {
    node {
      id
      title
      variantTitle
      sku
      quantity
      currentPrice {
        amount
        currencyCode
      }
    }
  }
}
""".strip()


_LIST_CONTRACTS_QUERY = f"""
query subscriptionContracts(
  $first: Int!, $after: String,
  $sortKey: SubscriptionContractsSortKeys, $reverse: Boolean
) {{
  subscriptionContracts(
    first: $first, after: $after,
    sortKey: $sortKey, reverse: $reverse
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_CONTRACT_NODE_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_CONTRACT_QUERY = f"""
query subscriptionContract($id: ID!) {{
  subscriptionContract(id: $id) {{
    {_CONTRACT_NODE_FIELDS}
  }}
}}
""".strip()


# Each mutation takes ``subscriptionContractId: ID!`` directly at the
# field level (Pattern A — identifier outside the input). Returns the
# updated contract + userErrors.
_PAUSE_MUTATION = """
mutation subscriptionContractPause($id: ID!) {
  subscriptionContractPause(subscriptionContractId: $id) {
    contract {
      id
      status
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_RESUME_MUTATION = """
mutation subscriptionContractActivate($id: ID!) {
  subscriptionContractActivate(subscriptionContractId: $id) {
    contract {
      id
      status
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_CANCEL_MUTATION = """
mutation subscriptionContractCancel($id: ID!) {
  subscriptionContractCancel(subscriptionContractId: $id) {
    contract {
      id
      status
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifySubscriptionContractsAdapter(ShopifyBaseAdapter):
    name = "shopify_subscription_contracts"
    capabilities = {
        Capability.SHOPIFY_LIST_SUBSCRIPTION_CONTRACTS,
        Capability.SHOPIFY_GET_SUBSCRIPTION_CONTRACT,
        Capability.SHOPIFY_PAUSE_SUBSCRIPTION_CONTRACT,
        Capability.SHOPIFY_RESUME_SUBSCRIPTION_CONTRACT,
        Capability.SHOPIFY_CANCEL_SUBSCRIPTION_CONTRACT,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_SUBSCRIPTION_CONTRACTS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_SUBSCRIPTION_CONTRACT:
            return self._get(params)
        if capability == Capability.SHOPIFY_PAUSE_SUBSCRIPTION_CONTRACT:
            return self._lifecycle(
                params,
                mutation=_PAUSE_MUTATION,
                mutation_name="subscriptionContractPause",
                capability=Capability.SHOPIFY_PAUSE_SUBSCRIPTION_CONTRACT,
            )
        if capability == Capability.SHOPIFY_RESUME_SUBSCRIPTION_CONTRACT:
            return self._lifecycle(
                params,
                mutation=_RESUME_MUTATION,
                # Shopify's mutation name is ``Activate`` (re-activate
                # a paused contract). The capability-side name reads
                # as "resume" because that's what the engine actually
                # does — "activate" implies create-from-nothing.
                mutation_name="subscriptionContractActivate",
                capability=Capability.SHOPIFY_RESUME_SUBSCRIPTION_CONTRACT,
            )
        if capability == Capability.SHOPIFY_CANCEL_SUBSCRIPTION_CONTRACT:
            return self._lifecycle(
                params,
                mutation=_CANCEL_MUTATION,
                mutation_name="subscriptionContractCancel",
                capability=Capability.SHOPIFY_CANCEL_SUBSCRIPTION_CONTRACT,
            )
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
                "shopify_subscription_contracts",
                "'cursor' must be a string or None",
            )
        sort_key = params.get("sort_key") or params.get("sortKey")
        if sort_key is not None:
            if not isinstance(sort_key, str):
                raise AdapterValidationError(
                    "shopify_subscription_contracts",
                    "'sort_key' must be a string or None",
                )
            sort_key = sort_key.upper()
        reverse = bool(params.get("reverse", False))

        data = self._gql(_LIST_CONTRACTS_QUERY, {
            "first": limit,
            "after": cursor,
            "sortKey": sort_key,
            "reverse": reverse,
        })
        envelope = data.get("subscriptionContracts") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        contracts = [
            self._normalise_contract(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_SUBSCRIPTION_CONTRACTS,
            data={
                "contracts": contracts,
                "count": len(contracts),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        contract_id = params.get("id") or params.get("contract_id")
        if not isinstance(contract_id, str) or not contract_id.strip():
            raise AdapterValidationError(
                "shopify_subscription_contracts",
                "'id' (Shopify GID for the subscription contract) "
                "is required",
            )
        data = self._gql(_GET_CONTRACT_QUERY, {"id": contract_id.strip()})
        node = data.get("subscriptionContract")
        if not isinstance(node, dict):
            return self._success(
                Capability.SHOPIFY_GET_SUBSCRIPTION_CONTRACT,
                data={"found": False, "contract": None},
            )
        return self._success(
            Capability.SHOPIFY_GET_SUBSCRIPTION_CONTRACT,
            data={"found": True,
                  "contract": self._normalise_contract(node)},
        )

    # ── Lifecycle (pause / resume / cancel — shared shape) ────────

    def _lifecycle(
        self,
        params: dict[str, Any],
        *,
        mutation: str,
        mutation_name: str,
        capability: Capability,
    ) -> Any:
        contract_id = params.get("id") or params.get("contract_id")
        if not isinstance(contract_id, str) or not contract_id.strip():
            raise AdapterValidationError(
                "shopify_subscription_contracts",
                "'id' (Shopify GID for the subscription contract) "
                "is required",
            )
        data = self._gql(mutation, {"id": contract_id.strip()})
        self._check_user_errors(data, mutation_name)
        payload = data.get(mutation_name) or {}
        contract = payload.get("contract") or {}
        return self._success(
            capability,
            data={
                "id": contract.get("id", "") or "",
                "status": contract.get("status", "") or "",
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_contract(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        customer = node.get("customer") or {}
        lines_raw = (node.get("lines") or {}).get("edges") or []
        lines: list[dict[str, Any]] = []
        for edge in lines_raw:
            if not isinstance(edge, dict):
                continue
            ln = edge.get("node") or {}
            price_money = ln.get("currentPrice") or {}
            try:
                price = float(price_money.get("amount", 0) or 0)
            except (TypeError, ValueError):
                price = 0.0
            lines.append({
                "id": ln.get("id", "") or "",
                "title": ln.get("title", "") or "",
                "variant_title": ln.get("variantTitle", "") or "",
                "sku": ln.get("sku", "") or "",
                "quantity": int(ln.get("quantity", 0) or 0),
                "current_price": price,
                "currency": price_money.get("currencyCode", "") or "",
            })
        return {
            "id": node.get("id", "") or "",
            "status": node.get("status", "") or "",
            "currency": node.get("currencyCode", "") or "",
            "next_billing_date": node.get("nextBillingDate", "") or "",
            "customer_id": (
                customer.get("id", "") if isinstance(customer, dict) else ""
            ) or "",
            "customer_email": (
                customer.get("email", "") if isinstance(customer, dict) else ""
            ) or "",
            "customer_name": (
                customer.get("displayName", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "lines": lines,
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }
