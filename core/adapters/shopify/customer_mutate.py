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
      emailMarketingConsent { marketingState marketingOptInLevel }
      smsMarketingConsent { marketingState marketingOptInLevel }
    }
    userErrors { field message code }
  }
}
""".strip()


# Atomic tag-delta mutations — these avoid the read-then-write
# lost-update race that plain customerUpdate(tags=[...]) suffers
# when multiple agents (loyalty, CS, dunning) tag the same
# customer concurrently. Shopify runs them server-side as
# indivisible set-union / set-difference operations.
_TAGS_ADD_MUTATION = """
mutation TagsAdd($id: ID!, $tags: [String!]!) {
  tagsAdd(id: $id, tags: $tags) {
    node { ... on Customer { id tags } }
    userErrors { field message }
  }
}
""".strip()

_TAGS_REMOVE_MUTATION = """
mutation TagsRemove($id: ID!, $tags: [String!]!) {
  tagsRemove(id: $id, tags: $tags) {
    node { ... on Customer { id tags } }
    userErrors { field message }
  }
}
""".strip()


# Only states the API allows callers to SET. ``pending`` and
# ``redacted`` are server-controlled and get rejected if posted
# by a client — reject them up front to avoid a round-trip.
_MARKETING_STATES = {"subscribed", "unsubscribed", "not_subscribed"}
_MARKETING_OPT_IN_LEVELS = {
    "single_opt_in", "confirmed_opt_in", "unknown",
}


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

        # add_tags + remove_tags with overlap is almost always a
        # caller bug — "add 'vip' but also remove 'VIP'" makes no
        # sense. Surface it instead of silently picking a winner.
        if add_tags and remove_tags:
            add_lc = {str(t).strip().lower() for t in (add_tags or [])}
            rm_lc = {str(t).strip().lower() for t in (remove_tags or [])}
            overlap = add_lc & rm_lc
            if overlap:
                raise AdapterValidationError(
                    self.name,
                    f"'add_tags' and 'remove_tags' overlap: {sorted(overlap)}",
                )

        # Deferred relative-edit plan. We execute these AFTER the
        # main customerUpdate so the other field mutations can't
        # be invalidated by a transient tags fetch, and so the
        # tagsAdd/tagsRemove atomic deltas avoid the lost-update
        # race that read-then-write had.
        tags_add_list: list[str] = []
        tags_remove_list: list[str] = []

        if tags_abs is not None:
            if not isinstance(tags_abs, list):
                raise AdapterValidationError(
                    self.name, "'tags' must be a list of strings",
                )
            cleaned = self._clean_tags(tags_abs)
            input_payload["tags"] = cleaned
            updated_fields.append("tags")
        elif add_tags or remove_tags:
            if add_tags is not None and not isinstance(add_tags, list):
                raise AdapterValidationError(
                    self.name, "'add_tags' must be a list of strings",
                )
            if remove_tags is not None and not isinstance(remove_tags, list):
                raise AdapterValidationError(
                    self.name, "'remove_tags' must be a list of strings",
                )
            tags_add_list = self._clean_tags(add_tags or [])
            tags_remove_list = self._clean_tags(remove_tags or [])
            if tags_add_list or tags_remove_list:
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
        # Shopify REQUIRES marketingOptInLevel when transitioning
        # a subscription state to SUBSCRIBED — without it, the
        # API returns userError "marketingOptInLevel can't be blank"
        # and the whole update fails.
        email_opt_in = params.get("email_marketing_opt_in_level")
        email_consent = self._build_consent(
            params.get("email_marketing_state"),
            email_opt_in,
            field_name="email_marketing_state",
        )
        if email_consent:
            input_payload["emailMarketingConsent"] = email_consent
            updated_fields.append("email_marketing_state")

        sms_opt_in = params.get("sms_marketing_opt_in_level")
        sms_consent = self._build_consent(
            params.get("sms_marketing_state"),
            sms_opt_in,
            field_name="sms_marketing_state",
        )
        if sms_consent:
            input_payload["smsMarketingConsent"] = sms_consent
            updated_fields.append("sms_marketing_state")

        # Nothing to update → refuse rather than round-trip.
        has_update_fields = len(input_payload) > 1
        has_tag_delta = bool(tags_add_list or tags_remove_list)
        if not has_update_fields and not has_tag_delta:
            raise AdapterValidationError(
                self.name,
                "no mutable fields provided (tags, note, email, phone, "
                "first_name, last_name, *_marketing_state)",
            )

        # Run the main customerUpdate only if there's something
        # for it to do. Pure relative-tag edits skip it entirely.
        customer: dict[str, Any] = {}
        if has_update_fields:
            data = self._gql(
                _CUSTOMER_UPDATE_MUTATION, {"input": input_payload},
            )
            self._check_user_errors(data, "customerUpdate")
            payload = data.get("customerUpdate") or {}
            customer = payload.get("customer") or {}
            # Shopify returns customer: null on missing write_customers
            # scope — with NO userErrors. Surface it loudly.
            if not customer:
                from ..errors import AdapterError
                raise AdapterError(
                    self.name,
                    "customerUpdate returned a null customer — "
                    "check that the access token has write_customers scope",
                )

        # Atomic relative tag edits. tagsAdd and tagsRemove run
        # server-side as set operations — no lost-update race
        # even if a parallel agent is retagging the customer.
        if tags_add_list:
            add_data = self._gql(
                _TAGS_ADD_MUTATION, {"id": gid, "tags": tags_add_list},
            )
            self._check_user_errors(add_data, "tagsAdd")
            node = (add_data.get("tagsAdd") or {}).get("node") or {}
            if node:
                customer = customer or {}
                customer["tags"] = list(node.get("tags") or customer.get("tags") or [])
        if tags_remove_list:
            rm_data = self._gql(
                _TAGS_REMOVE_MUTATION, {"id": gid, "tags": tags_remove_list},
            )
            self._check_user_errors(rm_data, "tagsRemove")
            node = (rm_data.get("tagsRemove") or {}).get("node") or {}
            if node:
                customer = customer or {}
                customer["tags"] = list(node.get("tags") or customer.get("tags") or [])

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

    def _build_consent(
        self,
        state: Any,
        opt_in_level: Any,
        *,
        field_name: str,
    ) -> dict[str, Any] | None:
        """Validate and build a CustomerEmail/SmsMarketingConsentInput.

        Returns ``None`` when the caller passed no state.

        Shopify requires ``marketingOptInLevel`` when the
        ``marketingState`` is ``SUBSCRIBED``; without it, every
        subscribe mutation fails at userErrors. Opt-in-level is
        optional for UNSUBSCRIBED / NOT_SUBSCRIBED.
        """
        if state is None:
            return None
        state_s = str(state).strip().lower()
        if state_s not in _MARKETING_STATES:
            raise AdapterValidationError(
                self.name,
                f"'{field_name}' must be one of {sorted(_MARKETING_STATES)}",
            )
        consent: dict[str, Any] = {"marketingState": state_s.upper()}
        if opt_in_level is not None:
            level_s = str(opt_in_level).strip().lower()
            if level_s not in _MARKETING_OPT_IN_LEVELS:
                raise AdapterValidationError(
                    self.name,
                    f"'{field_name}' opt-in level must be one of "
                    f"{sorted(_MARKETING_OPT_IN_LEVELS)}",
                )
            consent["marketingOptInLevel"] = level_s.upper()
        elif state_s == "subscribed":
            raise AdapterValidationError(
                self.name,
                f"'{field_name}' = subscribed requires "
                f"'{field_name.replace('_state', '_opt_in_level')}' "
                f"(one of {sorted(_MARKETING_OPT_IN_LEVELS)})",
            )
        return consent

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
