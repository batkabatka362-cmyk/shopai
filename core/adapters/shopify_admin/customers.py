"""Shopify customers — CRUD + addresses + search + tags.

Covers the customer.json REST surface + the related
customer_addresses sub-resource. Customer metafields follow
the same pattern as product metafields (handled by the
generic Metafields module — not yet shipped).

Customer segments (GraphQL) is NOT in this module —
segmentation is a separate resource landing in Wave 3+.
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger(
    "shopai.shopify_admin.customers",
)


class Customers:
    """Customer CRUD, search, tags."""

    # ── Read ────────────────────────────────────────────

    @staticmethod
    def list_customers(
        client: ShopifyAdminClient,
        *,
        limit: int = 50,
        page_info: str = "",
        ids: list[int | str] | None = None,
        since_id: int | str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
        }
        if page_info:
            params["page_info"] = page_info
        if ids:
            params["ids"] = ",".join(str(i) for i in ids)
        if since_id is not None:
            params["since_id"] = str(since_id)
        result = client.get("customers.json", params=params)
        rows = result.get("customers") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        customer_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"customers/{customer_id}.json",
        )
        customer = result.get("customer")
        if not isinstance(customer, dict):
            raise ShopifyAdminError(
                f"customer {customer_id} not returned",
                path=f"customers/{customer_id}.json",
            )
        return customer

    @staticmethod
    def count(client: ShopifyAdminClient) -> int:
        result = client.get("customers/count.json")
        return int(result.get("count") or 0)

    @staticmethod
    def search(
        client: ShopifyAdminClient,
        query: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Shopify's customer query language — ``email:jane*``,
        ``tag:VIP``, ``accepts_marketing:true``, etc. See
        Shopify docs for the full grammar."""
        if not query or not isinstance(query, str):
            raise ValueError("query: non-empty string required")
        result = client.get(
            "customers/search.json",
            params={
                "query": query,
                "limit": max(1, min(int(limit), 250)),
            },
        )
        rows = result.get("customers") or []
        return [r for r in rows if isinstance(r, dict)]

    # ── Write ───────────────────────────────────────────

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        *,
        email: str,
        first_name: str = "",
        last_name: str = "",
        phone: str = "",
        tags: list[str] | None = None,
        accepts_marketing: bool | None = None,
        addresses: list[dict[str, Any]] | None = None,
        note: str = "",
        send_email_invite: bool = False,
        send_email_welcome: bool = True,
    ) -> dict[str, Any]:
        """Create a customer. Email is required; Shopify
        rejects duplicates with a 422 we surface as
        ``ShopifyAdminError`` with status=422."""
        if not email or "@" not in email:
            raise ValueError(
                f"email: valid address required "
                f"(got {email!r})",
            )
        body: dict[str, Any] = {
            "customer": {
                "email": email.strip().lower(),
            },
        }
        c = body["customer"]
        if first_name:
            c["first_name"] = str(first_name)
        if last_name:
            c["last_name"] = str(last_name)
        if phone:
            c["phone"] = str(phone)
        if tags:
            c["tags"] = ", ".join(str(t) for t in tags)
        if accepts_marketing is not None:
            c["accepts_marketing"] = bool(accepts_marketing)
        if addresses:
            c["addresses"] = list(addresses)
        if note:
            c["note"] = str(note)
        if send_email_invite:
            c["send_email_invite"] = True
        if not send_email_welcome:
            c["send_email_welcome"] = False

        result = client.post("customers.json", body)
        created = result.get("customer")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "customer not returned by create",
                path="customers.json", body=str(result),
            )
        return created

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        customer_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Partial update. Shopify requires ``id`` on the
        payload — helper injects it so callers don't have to.

        Tag write convention: ``fields["tags"]`` is a
        comma-joined string that REPLACES the existing tag
        list. For add/remove semantics use ``add_tags`` /
        ``remove_tags`` below.
        """
        if not fields:
            raise ValueError("fields: non-empty dict required")
        body = {
            "customer": {
                "id": int(customer_id),
                **fields,
            },
        }
        result = client.put(
            f"customers/{customer_id}.json", body,
        )
        updated = result.get("customer")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "customer not returned by update",
                path=f"customers/{customer_id}.json",
            )
        return updated

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        customer_id: int | str,
    ) -> None:
        """Permanent delete (GDPR-compliant)."""
        client.delete(f"customers/{customer_id}.json")

    # ── Tags helpers ───────────────────────────────────

    @staticmethod
    def add_tags(
        client: ShopifyAdminClient,
        customer_id: int | str,
        tags: list[str],
    ) -> dict[str, Any]:
        """Additive merge with existing tags — preserves
        anything the store already set."""
        if not tags:
            raise ValueError("tags: non-empty list required")
        existing = Customers.get(client, customer_id)
        current = _split_tags(existing.get("tags", ""))
        merged = sorted({*current, *(t.strip() for t in tags if t)})
        return Customers.update(
            client, customer_id,
            fields={"tags": ", ".join(merged)},
        )

    @staticmethod
    def remove_tags(
        client: ShopifyAdminClient,
        customer_id: int | str,
        tags: list[str],
    ) -> dict[str, Any]:
        if not tags:
            raise ValueError("tags: non-empty list required")
        drop = {t.strip().lower() for t in tags if t}
        existing = Customers.get(client, customer_id)
        current = _split_tags(existing.get("tags", ""))
        kept = sorted(
            t for t in current
            if t.strip().lower() not in drop
        )
        return Customers.update(
            client, customer_id,
            fields={"tags": ", ".join(kept)},
        )


class CustomerAddresses:
    """Address CRUD under a customer."""

    @staticmethod
    def list_addresses(
        client: ShopifyAdminClient,
        customer_id: int | str,
    ) -> list[dict[str, Any]]:
        result = client.get(
            f"customers/{customer_id}/addresses.json",
        )
        rows = result.get("addresses") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def create(
        client: ShopifyAdminClient,
        customer_id: int | str,
        *,
        address: dict[str, Any],
    ) -> dict[str, Any]:
        """Required fields per Shopify: address1, city, country
        (ISO alpha-2), first_name, last_name, zip.
        Phone + province recommended for shipping-rate quoting.
        """
        if not isinstance(address, dict) or not address:
            raise ValueError(
                "address: non-empty dict required",
            )
        result = client.post(
            f"customers/{customer_id}/addresses.json",
            {"address": dict(address)},
        )
        created = result.get("customer_address")
        if not isinstance(created, dict):
            raise ShopifyAdminError(
                "customer_address not returned by create",
                path=(
                    f"customers/{customer_id}/addresses.json"
                ),
                body=str(result),
            )
        return created

    @staticmethod
    def update(
        client: ShopifyAdminClient,
        customer_id: int | str,
        address_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"customers/{customer_id}/"
            f"addresses/{address_id}.json",
            {"address": dict(fields)},
        )
        updated = result.get("customer_address")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "customer_address not returned by update",
                path=(
                    f"customers/{customer_id}/"
                    f"addresses/{address_id}.json"
                ),
            )
        return updated

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        customer_id: int | str,
        address_id: int | str,
    ) -> None:
        client.delete(
            f"customers/{customer_id}/"
            f"addresses/{address_id}.json",
        )

    @staticmethod
    def set_default(
        client: ShopifyAdminClient,
        customer_id: int | str,
        address_id: int | str,
    ) -> dict[str, Any]:
        """Mark this address as the customer's default
        shipping destination."""
        result = client.put(
            f"customers/{customer_id}/"
            f"addresses/{address_id}/default.json",
            {},
        )
        updated = result.get("customer_address")
        if not isinstance(updated, dict):
            raise ShopifyAdminError(
                "customer_address not returned by set_default",
                path=(
                    f"customers/{customer_id}/"
                    f"addresses/{address_id}/default.json"
                ),
            )
        return updated


def _split_tags(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    return [
        t.strip() for t in str(raw).split(",") if t.strip()
    ]
