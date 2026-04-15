"""ShopifyCustomerMutateAdapter — update customer records.

Complements the read-only ``ShopifyCustomersAdapter`` by
providing write access to core customer attributes: tags, note,
email, phone, first/last name, and email/SMS marketing consent.

This is the adapter the loyalty agent calls to promote a VIP
(``tags: ["vip", "tier3"]``), the CS agent calls to suppress
spam after a chargeback (``email_marketing_state: "unsubscribed"``),
and the dunning flow calls to flag risky accounts with a note.

WRITE-ONLY (single customer). Bulk tag edits and customer
creation remain future work.

Params shape::

    {
        "customer_id":    "123" | "gid://shopify/Customer/123",  # required
        "tags":           ["vip", "early-access"],     # REPLACES existing tags
        "add_tags":       ["winback-2026"],            # union with existing
        "remove_tags":    ["inactive"],                # difference
        "note":           "VIP — flagged by CS 2026-04",
        "email":          "new@example.com",
        "phone":          "+15551234567",
        "first_name":     "...",
        "last_name":      "...",
        "email_marketing_state": "subscribed"|"unsubscribed",
        "sms_marketing_state":   "subscribed"|"unsubscribed",
    }

At least one mutation field must be present; otherwise the
adapter raises ``AdapterValidationError`` rather than making a
no-op GraphQL call.

Tag semantics:

  * ``tags`` (if present) is the authoritative full list — it
    REPLACES Shopify's existing tags.
  * ``add_tags`` / ``remove_tags`` are relative edits that
    require an extra read-then-write so the adapter can compute
    the new set without stomping unrelated tags.
  * If both ``tags`` and ``add_tags``/``remove_tags`` are given,
    the absolute ``tags`` wins and the deltas are ignored.

Returns::

    {
        "customer_id":         "gid://shopify/Customer/123",
        "tags":                [...],       # final tag set
        "updated_fields":      ["tags", "note", ...],
    }
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


_CUSTOMER_UPDATE_MUTATION = """
mutation UpdateCustomer($input: CustomerInput!) {
  customerUpdate(input: $input) {
    customer {
      id
      tags
      note
      email
      phone
      firstName
      lastName
      emailMarketingConsent { marketingState }
      smsMarketingConsent { marketingState }
    }
    userErrors { field message code }
  }
}
""".strip()


_FETCH_TAGS_QUERY = """
query CustomerTags($id: ID!) {
  customer(id: $id) {
    id
    tags
  }
}
""".strip()


_MARKETING_STATES = {"subscribed", "unsubscribed", "pending", "not_subscribed"}


class ShopifyCustomerMutateAdapter(ShopifyBaseAdapter):
    """Update a single customer record via customerUpdate."""

    name = "shopify_customer_mutate"
    capabilities = {Capability.SHOPIFY_UPDATE_CUSTOMER}

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability != Capability.SHOPIFY_UPDATE_CUSTOMER:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        customer_id = params.get("customer_id")
        if not customer_id:
            raise AdapterValidationError(
                self.name, "'customer_id' is required",
            )
        gid = self._to_gid(customer_id)

        input_payload: dict[str, Any] = {"id": gid}
        updated_fields: list[str] = []

        # ── Tags — absolute vs. relative ──────────────────────
        tags_abs = params.get("tags")
        add_tags = params.get("add_tags")
        remove_tags = params.get("remove_tags")

        if tags_abs is not None:
            if not isinstance(tags_abs, list):
                raise AdapterValidationError(
                    self.name, "'tags' must be a list of strings",
                )
            cleaned = self._clean_tags(tags_abs)
            input_payload["tags"] = cleaned
            updated_fields.append("tags")
        elif add_tags or remove_tags:
            # Relative edit: read current tags, apply delta.
            # We do this BEFORE the mutation (not inside) because
            # Shopify's tags field is an absolute replace, not a
            # delta.
            if add_tags is not None and not isinstance(add_tags, list):
                raise AdapterValidationError(
                    self.name, "'add_tags' must be a list of strings",
                )
            if remove_tags is not None and not isinstance(remove_tags, list):
                raise AdapterValidationError(
                    self.name, "'remove_tags' must be a list of strings",
                )
            current = self._fetch_current_tags(gid)
            merged = list(current)
            for t in self._clean_tags(add_tags or []):
                if t not in merged:
                    merged.append(t)
            remove_set = {t.lower() for t in self._clean_tags(remove_tags or [])}
            merged = [t for t in merged if t.lower() not in remove_set]
            input_payload["tags"] = merged
            updated_fields.append("tags")

        # ── Scalar fields ─────────────────────────────────────
        for local_key, remote_key in (
            ("note", "note"),
            ("email", "email"),
            ("phone", "phone"),
            ("first_name", "firstName"),
            ("last_name", "lastName"),
        ):
            if local_key in params and params[local_key] is not None:
                input_payload[remote_key] = str(params[local_key])
                updated_fields.append(local_key)

        # ── Marketing consent ─────────────────────────────────
        email_state = params.get("email_marketing_state")
        if email_state is not None:
            state = str(email_state).strip().lower()
            if state not in _MARKETING_STATES:
                raise AdapterValidationError(
                    self.name,
                    f"'email_marketing_state' must be one of "
                    f"{sorted(_MARKETING_STATES)}",
                )
            input_payload["emailMarketingConsent"] = {
                "marketingState": state.upper(),
            }
            updated_fields.append("email_marketing_state")

        sms_state = params.get("sms_marketing_state")
        if sms_state is not None:
            state = str(sms_state).strip().lower()
            if state not in _MARKETING_STATES:
                raise AdapterValidationError(
                    self.name,
                    f"'sms_marketing_state' must be one of "
                    f"{sorted(_MARKETING_STATES)}",
                )
            input_payload["smsMarketingConsent"] = {
                "marketingState": state.upper(),
            }
            updated_fields.append("sms_marketing_state")

        # Nothing to update → refuse rather than round-trip.
        # customerUpdate with just {id} is a waste of quota and
        # the caller's intent is almost certainly a bug.
        if len(input_payload) == 1:
            raise AdapterValidationError(
                self.name,
                "no mutable fields provided (tags, note, email, phone, "
                "first_name, last_name, *_marketing_state)",
            )

        data = self._gql(
            _CUSTOMER_UPDATE_MUTATION, {"input": input_payload},
        )
        self._check_user_errors(data, "customerUpdate")

        payload = data.get("customerUpdate") or {}
        customer = payload.get("customer") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_CUSTOMER,
            data={
                "customer_id": customer.get("id", gid) or gid,
                "tags": list(customer.get("tags") or []),
                "note": customer.get("note", "") or "",
                "email": customer.get("email", "") or "",
                "phone": customer.get("phone", "") or "",
                "first_name": customer.get("firstName", "") or "",
                "last_name": customer.get("lastName", "") or "",
                "email_marketing_state": (
                    ((customer.get("emailMarketingConsent") or {})
                     .get("marketingState", "") or "").lower()
                ),
                "sms_marketing_state": (
                    ((customer.get("smsMarketingConsent") or {})
                     .get("marketingState", "") or "").lower()
                ),
                "updated_fields": updated_fields,
            },
        )

    # ── Helpers ────────────────────────────────────────────────

    def _fetch_current_tags(self, gid: str) -> list[str]:
        """Fetch the customer's current tags so relative
        add/remove deltas can be applied without clobbering
        unrelated tags. Raises AdapterValidationError if the
        customer doesn't exist."""
        data = self._gql(_FETCH_TAGS_QUERY, {"id": gid})
        customer = data.get("customer")
        if not customer:
            raise AdapterValidationError(
                self.name, f"customer not found: {gid}",
            )
        return list(customer.get("tags") or [])

    @staticmethod
    def _clean_tags(tags: list[Any]) -> list[str]:
        """Stringify, strip, drop empties, de-dup (case-insensitive
        — Shopify stores tags case-insensitively)."""
        seen: set[str] = set()
        out: list[str] = []
        for t in tags:
            s = str(t).strip()
            if not s:
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out

    @staticmethod
    def _to_gid(customer_id: Any) -> str:
        """Accept ``"123"`` / ``123`` / ``"gid://shopify/Customer/123"``
        and return the canonical GID."""
        s = str(customer_id)
        if s.startswith("gid://"):
            return s
        return f"gid://shopify/Customer/{s}"
