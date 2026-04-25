"""Shopify attribution — close the UTM-to-order-note leg.

publisher_bundle.py already embeds ``shopai_decision_id`` in the
destination URL's query string. For that decision_id to survive to
the Shopify order and fire OrderWebhookHandler's calibration path,
**two extra pieces** need to exist on the owner's Shopify side:

  1. A tiny JavaScript snippet that, on page load, reads any
     ``shopai_*`` URL parameter and stores it as a cart attribute
     via ``/cart/update.js``. Shopify carries cart attributes into
     the order's ``note_attributes`` when the order is placed.
  2. An ``orders/paid`` webhook registered on the shop pointing at
     the ShopAI ingress URL so that OrderWebhookHandler ever gets
     called in the first place.

``build_liquid_snippet`` returns the owner-pasteable snippet (one
markdown block with HTML + JS plus install instructions).
``register_order_webhook`` hits Shopify Admin API to create the
webhook if it's not already registered. ``ensure_attribution`` is
the one-call helper that checks webhook presence, (re)registers if
missing, and returns a WebhookState with the outcome.

This closes AUDIT_LOG P2 (missing decision_id on webhook) and makes
the v33-v38 brain learners actually see decision→outcome pairs on
real Shopify orders, not just synthetic test data.

Pure stdlib + requests (already a shared dep of the ads/shopify
adapter base). Idempotent — repeat calls detect existing webhooks
and don't duplicate.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("execution.launch.shopify_attribution")


# ── Constants ────────────────────────────────────────────────

_ATTRIBUTION_KEYS: tuple[str, ...] = (
    "shopai_decision_id",
    "shopai_campaign_id",
    "utm_source",
    "utm_medium",
    "utm_campaign",
)

# The snippet is designed to be pasted into ``layout/theme.liquid``
# just before ``</body>`` or into a dedicated section. It's ~1.5KB
# minified and does one POST on first pageview per session.
_LIQUID_SNIPPET = """{%- comment -%}
ShopAI attribution snippet — DO NOT EDIT.

Reads ``shopai_*`` and ``utm_*`` URL parameters on the first
pageview per session and writes them to cart.attributes via
``/cart/update.js`` so the resulting Shopify order's
``note_attributes`` carries them through to
``OrderWebhookHandler.handle_order_paid``.

Installed via ``execution.launch.shopify_attribution``.
Idempotent: checks sessionStorage before posting.
{%- endcomment -%}
<script>
(function () {
  try {
    var keys = [{KEYS_JS}];
    var params = new URLSearchParams(window.location.search);
    var attrs = {};
    var found = false;
    for (var i = 0; i < keys.length; i++) {
      var v = params.get(keys[i]);
      if (v) {
        attrs[keys[i]] = v;
        found = true;
      }
    }
    if (!found) return;
    var stamp = "shopai_attr_" + Object.keys(attrs).sort().join("_")
                + "_" + (attrs.shopai_decision_id || "_");
    if (sessionStorage.getItem(stamp)) return;
    var body = new FormData();
    Object.keys(attrs).forEach(function (k) {
      body.append("attributes[" + k + "]", attrs[k]);
    });
    fetch("/cart/update.js", {
      method: "POST",
      body: body,
      credentials: "same-origin"
    }).then(function () {
      sessionStorage.setItem(stamp, "1");
    }).catch(function () { /* non-fatal */ });
  } catch (e) { /* silent */ }
})();
</script>
"""


# ── Snippet builder ──────────────────────────────────────────


def build_liquid_snippet(
    *,
    extra_keys: tuple[str, ...] = (),
) -> str:
    """Return the Shopify-theme snippet as a string.

    ``extra_keys`` lets owners wire additional UTM params (e.g.
    ``fbclid``). The default set is the minimum needed for the
    OutcomeRecorder closed loop.
    """
    keys = list(_ATTRIBUTION_KEYS) + [
        str(k) for k in extra_keys if k
    ]
    keys_js = ", ".join(f'"{k}"' for k in keys)
    return _LIQUID_SNIPPET.replace("{KEYS_JS}", keys_js)


def install_instructions(shop_url: str = "") -> str:
    """Owner-friendly markdown instructions for pasting the snippet.

    Can be echoed by ``shopai doctor`` or included in an email."""
    shop = shop_url or "your-store.myshopify.com"
    return (
        "# ShopAI attribution install (one-time)\n\n"
        "1. Open the Shopify admin: "
        f"https://{shop}/admin/themes\n"
        "2. **Online Store → Themes → Actions → Edit code** on\n"
        "   your live theme.\n"
        "3. Open ``layout/theme.liquid`` (the file is ~600 lines).\n"
        "4. Paste the ShopAI snippet (``shopai doctor --snippet``)\n"
        "   just before the closing ``</body>`` tag.\n"
        "5. Save. No theme deploy needed; takes effect on next\n"
        "   pageview.\n"
        "\n"
        "Verify: open your store, append ``?shopai_decision_id=test``\n"
        "to any product URL, add the item to cart, check out. The\n"
        "resulting test order's note_attributes will contain\n"
        "shopai_decision_id=test.\n"
    )


# ── Webhook registration ─────────────────────────────────────


@dataclass
class WebhookState:
    topic: str
    address: str
    id: str = ""
    registered: bool = False
    already_existed: bool = False
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "address": self.address,
            "id": self.id,
            "registered": self.registered,
            "already_existed": self.already_existed,
            "error": self.error,
        }


def _shopify_base(shop_url: str) -> str:
    base = shop_url.strip()
    if not base.startswith("http"):
        base = f"https://{base}"
    return base.rstrip("/")


def _shopify_headers(api_key: str) -> dict[str, str]:
    return {
        "X-Shopify-Access-Token": api_key,
        "Content-Type": "application/json",
    }


def list_registered_webhooks(
    shop_url: str, api_key: str,
    *,
    http: Any = None,
) -> list[dict[str, Any]]:
    """Return every webhook registered on the shop. Best-effort —
    returns an empty list on any failure and logs.
    """
    if not shop_url or not api_key:
        raise ValueError("shop_url + api_key required")
    import requests
    client = http or requests
    url = (
        f"{_shopify_base(shop_url)}"
        f"/admin/api/2024-01/webhooks.json"
    )
    try:
        resp = client.get(
            url, headers=_shopify_headers(api_key), timeout=20,
        )
        if resp.status_code >= 400:
            logger.debug(
                "webhooks list returned %s: %s",
                resp.status_code, resp.text[:200],
            )
            return []
        return list(resp.json().get("webhooks", []))
    except Exception as exc:  # noqa: BLE001
        logger.debug("webhooks list failed: %s", exc)
        return []


def register_order_webhook(
    shop_url: str,
    api_key: str,
    callback_url: str,
    *,
    topic: str = "orders/paid",
    http: Any = None,
) -> WebhookState:
    """Idempotently register an orders/paid webhook pointing at
    ``callback_url``. If a webhook with the same (topic, address)
    already exists, return its id without creating a duplicate.
    """
    if not shop_url or not api_key or not callback_url:
        raise ValueError(
            "shop_url + api_key + callback_url required",
        )
    if not re.match(r"^https?://", callback_url):
        raise ValueError(
            "callback_url must be a fully-qualified http(s) URL",
        )
    state = WebhookState(topic=topic, address=callback_url)
    existing = list_registered_webhooks(
        shop_url, api_key, http=http,
    )
    for wh in existing:
        if (
            wh.get("topic") == topic
            and wh.get("address") == callback_url
        ):
            state.id = str(wh.get("id", ""))
            state.already_existed = True
            state.registered = True
            return state
    import requests
    client = http or requests
    url = (
        f"{_shopify_base(shop_url)}"
        f"/admin/api/2024-01/webhooks.json"
    )
    body = {
        "webhook": {
            "topic": topic,
            "address": callback_url,
            "format": "json",
        },
    }
    try:
        resp = client.post(
            url,
            headers=_shopify_headers(api_key),
            data=json.dumps(body),
            timeout=20,
        )
        if resp.status_code in (200, 201):
            wh = resp.json().get("webhook", {})
            state.id = str(wh.get("id", ""))
            state.registered = True
        else:
            state.error = (
                f"HTTP {resp.status_code}: "
                f"{resp.text[:200]}"
            )
    except Exception as exc:  # noqa: BLE001
        state.error = (
            f"{type(exc).__name__}: {exc}"
        )
    return state


def ensure_attribution(
    *,
    shop_url: str,
    api_key: str,
    callback_url: str,
    topics: tuple[str, ...] = (
        "orders/paid", "orders/cancelled",
    ),
    http: Any = None,
) -> list[WebhookState]:
    """One-call helper: (re)register every required webhook
    idempotently. Returns one WebhookState per requested topic."""
    states: list[WebhookState] = []
    for topic in topics:
        states.append(register_order_webhook(
            shop_url, api_key, callback_url,
            topic=topic, http=http,
        ))
    return states


# ── Module stats ────────────────────────────────────────────

_lock = threading.Lock()
_activity: dict[str, int] = {
    "snippets_built": 0,
    "webhooks_checked": 0,
    "webhooks_created": 0,
}


def stats() -> dict[str, Any]:
    with _lock:
        return dict(_activity)


def _bump(key: str, n: int = 1) -> None:
    with _lock:
        _activity[key] = _activity.get(key, 0) + n


# Wrap the public helpers so stats() reflects usage. These are at
# module bottom so the code above reads as a linear narrative.

_orig_build = build_liquid_snippet
_orig_list = list_registered_webhooks
_orig_register = register_order_webhook


def build_liquid_snippet(  # noqa: F811
    *, extra_keys: tuple[str, ...] = (),
) -> str:
    _bump("snippets_built")
    return _orig_build(extra_keys=extra_keys)


def list_registered_webhooks(  # noqa: F811
    shop_url: str, api_key: str, *, http: Any = None,
) -> list[dict[str, Any]]:
    _bump("webhooks_checked")
    return _orig_list(shop_url, api_key, http=http)


def register_order_webhook(  # noqa: F811
    shop_url: str,
    api_key: str,
    callback_url: str,
    *,
    topic: str = "orders/paid",
    http: Any = None,
) -> WebhookState:
    state = _orig_register(
        shop_url, api_key, callback_url,
        topic=topic, http=http,
    )
    if state.registered and not state.already_existed:
        _bump("webhooks_created")
    return state
