"""Shopify webhook subscription helper.

Registers the ``orders/create``, ``orders/paid``, and ``products/update``
webhooks so the reward-loop bridge at ``/api/webhook/shopify`` starts
receiving live events. Idempotent — re-running against an already-
subscribed address is a no-op (Shopify returns the existing record).

Usage (CLI)::

    python -m core.webhooks.register \\
        --shop  ts0efe-ih.myshopify.com \\
        --token shpat_xxx \\
        --url   https://public.example.com/api/webhook/shopify

Usage (Python)::

    from core.webhooks.register import register_all
    status = register_all(shop, token, public_url)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from utils.logger import get_logger


logger = get_logger("webhooks.register")


# Topics we care about for the reward loop and pattern promotion.
# Keep this short — every topic is an extra HTTP round trip per event.
_TOPICS = (
    "orders/create",      # primary revenue signal
    "orders/paid",        # confirmed payment (distinct from create)
    "orders/cancelled",   # negative signal
    "products/update",    # catalog mutation notice
    "app/uninstalled",    # lets us stop pinging a disabled store
    "checkouts/update",   # abandoned-cart — fires ~1-3h after
                          # checkout stalls without conversion
    "customers/create",   # welcome email flow — fires on
                          # first-contact opt-in signup
)


def register_all(
    shop: str,
    token: str,
    callback_url: str,
    topics: tuple[str, ...] = _TOPICS,
    api_version: str = "2024-01",
) -> dict[str, Any]:
    """Create each webhook idempotently. Returns ``{topic: status}``.

    ``status`` values:
        "created"    — new subscription persisted
        "exists"     — identical subscription already present
        "error:<msg>" — Shopify refused (4xx / 5xx / network)
    """
    if not shop or not token:
        raise ValueError("shop and token are required")
    if not callback_url.startswith("https://"):
        # Shopify requires https for webhook addresses (staging / prod).
        # ngrok, cloudflare tunnel, or fly.io all give free https URLs.
        raise ValueError(
            "callback_url must be https:// (Shopify rejects http endpoints)"
        )

    existing = _list_existing(shop, token, api_version)
    existing_by_topic = {w["topic"]: w for w in existing}

    result: dict[str, Any] = {}
    for topic in topics:
        cur = existing_by_topic.get(topic)
        if cur and cur.get("address") == callback_url:
            result[topic] = "exists"
            continue
        if cur:
            # Different callback URL — update in place instead of
            # leaving a stale subscription pointing at an old host.
            result[topic] = _update(shop, token, cur["id"], callback_url, api_version)
        else:
            result[topic] = _create(shop, token, topic, callback_url, api_version)
    return result


def _list_existing(
    shop: str, token: str, api_version: str,
) -> list[dict[str, Any]]:
    url = f"https://{shop}/admin/api/{api_version}/webhooks.json"
    req = urllib.request.Request(
        url,
        headers={"X-Shopify-Access-Token": token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        logger.warning("Listing existing webhooks failed: %s", exc)
        return []
    return payload.get("webhooks", []) or []


def _create(
    shop: str, token: str, topic: str, address: str, api_version: str,
) -> str:
    body = json.dumps({
        "webhook": {"topic": topic, "address": address, "format": "json"},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://{shop}/admin/api/{api_version}/webhooks.json",
        data=body,
        headers={
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return "created"
    except urllib.error.HTTPError as exc:
        return f"error:{exc.code} {exc.read().decode('utf-8', errors='replace')[:200]}"
    except urllib.error.URLError as exc:
        return f"error:{exc.reason}"


def _update(
    shop: str, token: str, webhook_id: int, address: str, api_version: str,
) -> str:
    body = json.dumps({"webhook": {"id": webhook_id, "address": address}}).encode("utf-8")
    req = urllib.request.Request(
        f"https://{shop}/admin/api/{api_version}/webhooks/{webhook_id}.json",
        data=body,
        headers={
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return "updated"
    except urllib.error.HTTPError as exc:
        return f"error:{exc.code} {exc.read().decode('utf-8', errors='replace')[:200]}"
    except urllib.error.URLError as exc:
        return f"error:{exc.reason}"


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Register Shopify webhooks")
    parser.add_argument(
        "--shop",
        default=os.environ.get("SHOPAI_SHOPIFY_URL", ""),
        help="myshopify.com domain (e.g. mystore.myshopify.com)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("SHOPAI_SHOPIFY_KEY", ""),
        help="Admin API access token (shpat_...)",
    )
    parser.add_argument(
        "--url", required=True,
        help="Public https URL for the webhook receiver (e.g. https://host/api/webhook/shopify)",
    )
    args = parser.parse_args()
    if not args.shop or not args.token:
        print("ERR: --shop and --token required (or set SHOPAI_SHOPIFY_URL/_KEY)",
              file=sys.stderr)
        return 2
    result = register_all(args.shop, args.token, args.url)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
