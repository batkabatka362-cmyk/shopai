"""ShopifyPaymentsPayoutsAdapter — Shopify Payments payout history.

Companion to ``disputes.py`` (chargeback reads via Shopify Payments).
The payouts surface returns the ledger of money Shopify has wired to
the merchant's bank account: gross sales, fees, refunds, dispute
losses, and the net amount actually deposited.

ShopAI's analytics + finance engines read these to:

  * Reconcile gross-to-net revenue ("we sold $X, kept $Y after
    Shopify Payments fees + chargebacks").
  * Detect cash-flow anomalies ("payout dropped 60% week-over-week,
    investigate").
  * Surface the running balance + next scheduled payout in the
    operator dashboard.

Capabilities (read-only — initiating ad-hoc payouts is merchant-
driven via the admin UI; engines only consume the history):

  * ``SHOPIFY_LIST_PAYOUTS``           — paginated list with status
    filter.
  * ``SHOPIFY_GET_PAYOUT``             — single payout with full
    summary.
  * ``SHOPIFY_GET_PAYMENTS_BALANCE``   — current available + pending
    balance across all currencies.

Pattern E note: the same `read_shopify_payments_accounts` /
`read_shopify_payments` scope gate as disputes. Stores not on
Shopify Payments hit ACCESS_DENIED at the field level (the
shopifyPaymentsAccount field is null when Shopify Payments isn't
enabled).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


# Pattern D: ShopifyPaymentsPayoutSummary's per-bucket field names
# (chargesGrossAmount, chargesFeeAmount, refundsGrossAmount, ...)
# don't exist in the 2024-01 schema — the summary type was
# restructured. Keeping the wire query to the stable subset that's
# documented across versions: id, status, issuedAt, gross, net, plus
# the bankAccount id + bankName (last4 / accountType also drifted).
# Engines that need fee-bucket detail run the bulk-query path or
# the third-party Shopify Payments API.
_PAYOUT_FIELDS = """
id
status
issuedAt
bankAccount {
  id
  bankName
}
gross {
  amount
  currencyCode
}
net {
  amount
  currencyCode
}
""".strip()


_LIST_PAYOUTS_QUERY = f"""
query shopifyPaymentsPayouts($first: Int!, $after: String) {{
  shopifyPaymentsAccount {{
    payouts(first: $first, after: $after) {{
      pageInfo {{
        hasNextPage
        endCursor
      }}
      edges {{
        node {{
          {_PAYOUT_FIELDS}
        }}
      }}
    }}
  }}
}}
""".strip()


_GET_PAYOUT_QUERY = f"""
query shopifyPaymentsPayout($id: ID!) {{
  node(id: $id) {{
    ... on ShopifyPaymentsPayout {{
      {_PAYOUT_FIELDS}
    }}
  }}
}}
""".strip()


_GET_BALANCE_QUERY = """
query shopifyPaymentsBalance {
  shopifyPaymentsAccount {
    balance {
      amount
      currencyCode
    }
    defaultCurrency
    payoutSchedule {
      interval
      monthlyAnchor
      weeklyAnchor
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifyPaymentsPayoutsAdapter(ShopifyBaseAdapter):
    name = "shopify_payments_payouts"
    capabilities = {
        Capability.SHOPIFY_LIST_PAYOUTS,
        Capability.SHOPIFY_GET_PAYOUT,
        Capability.SHOPIFY_GET_PAYMENTS_BALANCE,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_PAYOUTS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_PAYOUT:
            return self._get(params)
        if capability == Capability.SHOPIFY_GET_PAYMENTS_BALANCE:
            return self._get_balance(params)
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

        # Pattern D-adjacent: shopifyPaymentsAccount.payouts (like
        # .disputes from Phase 9.5) does NOT accept query/sortKey
        # arguments. Pagination only.
        data = self._gql(_LIST_PAYOUTS_QUERY, {
            "first": limit, "after": cursor,
        })
        account = data.get("shopifyPaymentsAccount") or {}
        envelope = account.get("payouts") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        payouts = [
            self._normalise_payout(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_PAYOUTS,
            data={
                "payouts": payouts,
                "count": len(payouts),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
                "shop_uses_shopify_payments": bool(account),
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        payout_id = params.get("id") or params.get("payout_id")
        if not isinstance(payout_id, str) or not payout_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the payout) is required",
            )
        data = self._gql(_GET_PAYOUT_QUERY, {"id": payout_id.strip()})
        node = data.get("node") or {}
        return self._success(
            Capability.SHOPIFY_GET_PAYOUT,
            data={
                "payout": self._normalise_payout(node),
                "found": bool(node),
            },
        )

    # ── Get balance ────────────────────────────────────────────────

    def _get_balance(self, _params: dict[str, Any]) -> Any:
        data = self._gql(_GET_BALANCE_QUERY, {})
        account = data.get("shopifyPaymentsAccount") or {}
        balance_raw = account.get("balance") or []
        balances = [
            {
                "amount": b.get("amount", "") or "",
                "currency_code": b.get("currencyCode", "") or "",
            }
            for b in balance_raw if isinstance(b, dict)
        ]
        schedule = account.get("payoutSchedule") or {}
        return self._success(
            Capability.SHOPIFY_GET_PAYMENTS_BALANCE,
            data={
                "balances": balances,
                "default_currency": (
                    account.get("defaultCurrency", "")
                    if isinstance(account, dict) else ""
                ) or "",
                "payout_interval": (
                    schedule.get("interval", "")
                    if isinstance(schedule, dict) else ""
                ) or "",
                "payout_monthly_anchor": int(
                    (schedule.get("monthlyAnchor") or 0)
                    if isinstance(schedule, dict) else 0
                ),
                "payout_weekly_anchor": (
                    schedule.get("weeklyAnchor", "")
                    if isinstance(schedule, dict) else ""
                ) or "",
                "shop_uses_shopify_payments": bool(account),
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _money(envelope: Any) -> tuple[str, str]:
        if not isinstance(envelope, dict):
            return "", ""
        return (
            envelope.get("amount", "") or "",
            envelope.get("currencyCode", "") or "",
        )

    @classmethod
    def _normalise_payout(cls, node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        gross_amount, currency = cls._money(node.get("gross"))
        net_amount, _ = cls._money(node.get("net"))
        bank = node.get("bankAccount") or {}
        return {
            "id": node.get("id", "") or "",
            "status": node.get("status", "") or "",
            "issued_at": node.get("issuedAt", "") or "",
            "gross_amount": gross_amount,
            "net_amount": net_amount,
            "currency_code": currency,
            "bank_account_id": (
                bank.get("id", "") if isinstance(bank, dict) else ""
            ) or "",
            "bank_name": (
                bank.get("bankName", "")
                if isinstance(bank, dict) else ""
            ) or "",
        }
