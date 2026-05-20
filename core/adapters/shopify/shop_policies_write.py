"""ShopifyShopPoliciesWriteAdapter -- store legal policy WRITE.

Every Shopify store ships with legal pages -- refund policy,
privacy policy, terms of service, shipping policy, etc. These
are surfaced at the footer of every storefront and are
legally required in most jurisdictions for selling online.

The read side already exists (``SHOPIFY_GET_SHOP_POLICIES`` in
``shop.py``). What's been missing is a write path so the
autonomous setup flow can:

  * Generate jurisdiction-appropriate policy text per niche +
    region.
  * Push it via ``shopPolicyUpdate`` so the storefront actually
    reflects the policy.
  * Avoid the manual "the operator must paste policies in
    Settings > Policies" step that previously gated store
    launches.

Capabilities:

  * ``SHOPIFY_UPDATE_SHOP_POLICY`` -- shopPolicyUpdate.
    Friendly call shape::

        {"policy_type": "REFUND_POLICY", "body": "..."}

    The ``policy_type`` is normalised to upper-case + validated
    against Shopify's ``ShopPolicyType`` enum before the
    GraphQL hop. ``body`` is the HTML / Markdown / plain text
    body the storefront renders.

Pattern F: ``shopPolicyUpdate`` uses the bare ``UserError``
type (no ``code`` field) -- confirmed by Shopify's schema.
Don't add ``code`` to the userErrors selection or the query
fails with "Field 'code' doesn't exist on type 'UserError'".

Required scopes: ``write_legal_policies`` (plus ``read_legal_policies``
for the reader half). Shopify renamed these from ``read/write_shop_policies``;
the legacy names are silently dropped from install URLs in 2026+.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── Shopify ShopPolicyType enum (Admin GraphQL 2024-01) ─────────────


_VALID_POLICY_TYPES: frozenset[str] = frozenset({
    "REFUND_POLICY",
    "PRIVACY_POLICY",
    "TERMS_OF_SERVICE",
    "SHIPPING_POLICY",
    "LEGAL_NOTICE",
    "CONTACT_INFORMATION",
    "SUBSCRIPTION_POLICY",
})


# ── GraphQL template ────────────────────────────────────────────────


_UPDATE_POLICY_MUTATION = """
mutation shopPolicyUpdate($shopPolicy: ShopPolicyInput!) {
  shopPolicyUpdate(shopPolicy: $shopPolicy) {
    shopPolicy {
      id
      type
      body
      url
      createdAt
      updatedAt
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


class ShopifyShopPoliciesWriteAdapter(ShopifyBaseAdapter):
    """Write surface for shop legal policies."""

    name = "shopify_shop_policies_write"
    capabilities = {Capability.SHOPIFY_UPDATE_SHOP_POLICY}
    # Shopify renamed these scopes from ``read/write_shop_policies``
    # to ``read/write_legal_policies`` (date unknown; surfaced
    # during a live install audit where the legacy names were
    # silently dropped from the install URL by Shopify and the
    # token came back with only the granted-and-renamed subset).
    required_scopes = frozenset({
        "read_legal_policies", "write_legal_policies",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_UPDATE_SHOP_POLICY:
            return self._update(params)
        raise AdapterValidationError(
            self.name,
            f"unsupported capability: {capability.value}",
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        policy_type = self._resolve_policy_type(
            params.get("policy_type")
            or params.get("type"),
        )
        body = params.get("body")
        if not isinstance(body, str):
            raise AdapterValidationError(
                self.name,
                "'body' (policy text) is required and must be a string",
            )
        if not body.strip():
            raise AdapterValidationError(
                self.name,
                "'body' must be non-empty -- to delete a policy "
                "use shopPolicyDelete instead",
            )

        data = self._gql(_UPDATE_POLICY_MUTATION, {
            "shopPolicy": {
                "type": policy_type,
                "body": body,
            },
        })
        self._check_user_errors(data, "shopPolicyUpdate")
        payload = data.get("shopPolicyUpdate") or {}
        policy = payload.get("shopPolicy") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_SHOP_POLICY,
            data={
                "policy": self._normalise_policy(policy),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _resolve_policy_type(self, raw: Any) -> str:
        """Normalise + validate the policy type.

        Accepts case-insensitive input + a handful of friendly
        aliases (e.g. ``"refund"`` for ``"REFUND_POLICY"``) so
        engines can stay loose without manual translation.
        """
        if not isinstance(raw, str) or not raw.strip():
            raise AdapterValidationError(
                self.name,
                "'policy_type' is required (one of: "
                + ", ".join(sorted(_VALID_POLICY_TYPES))
                + ")",
            )
        normalised = raw.strip().upper().replace("-", "_")
        # Friendly short forms
        if normalised in {"REFUND", "RETURNS"}:
            normalised = "REFUND_POLICY"
        elif normalised in {"PRIVACY"}:
            normalised = "PRIVACY_POLICY"
        elif normalised in {"TERMS", "TOS"}:
            normalised = "TERMS_OF_SERVICE"
        elif normalised in {"SHIPPING"}:
            normalised = "SHIPPING_POLICY"
        elif normalised in {"LEGAL"}:
            normalised = "LEGAL_NOTICE"
        elif normalised in {"CONTACT"}:
            normalised = "CONTACT_INFORMATION"
        elif normalised in {"SUBSCRIPTION"}:
            normalised = "SUBSCRIPTION_POLICY"
        if normalised not in _VALID_POLICY_TYPES:
            raise AdapterValidationError(
                self.name,
                f"unknown policy_type: {raw!r} (expected one of: "
                + ", ".join(sorted(_VALID_POLICY_TYPES))
                + ")",
            )
        return normalised

    @staticmethod
    def _normalise_policy(node: dict[str, Any]) -> dict[str, Any]:
        """Flatten the shopPolicy node into a stable dict shape."""
        if not isinstance(node, dict):
            return {}
        return {
            "id": node.get("id", "") or "",
            "type": node.get("type", "") or "",
            "body": node.get("body", "") or "",
            "url": node.get("url", "") or "",
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }
