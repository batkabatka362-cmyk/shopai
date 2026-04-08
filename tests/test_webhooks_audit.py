"""Tests for audit-pass-42 fixes — defensive + security hardening
across ``core.webhooks`` (ShopifyWebhookHandler, OrderWebhookHandler).

Pre-audit bugs fixed:

  * CRITICAL SECURITY: HMAC verification was computed over
    ``json.dumps(payload).encode()`` — re-serialised JSON,
    NOT the raw request body Shopify actually signed.
    Python's ``json.dumps`` produces different whitespace,
    key ordering, and escaping than what the upstream sent,
    so the computed digest never matched the header. Also,
    the code used ``hexdigest()`` while Shopify sends HMAC
    base64-encoded, so even IF the bytes had matched, the
    formats wouldn't have lined up. Net effect: whenever a
    webhook secret was configured, every legitimate webhook
    was silently rejected (status=rejected, reason=invalid_hmac).

  * Same ``handle_async`` event-id mismatch pattern that pass
    38 fixed in EventReactor: the async path generated its
    own id locally and returned it to the caller, but the
    spawned thread called ``handle()`` which minted a
    DIFFERENT id internally. The caller's id never appeared
    in stats or recent events.

  * ``_normalize_order`` / ``_normalize_product`` /
    ``_normalize_customer`` used bare ``float()`` / ``int()``
    on fields that Shopify sometimes returns as strings or
    ``None``: "$99.99 USD", "N/A", null on guest orders.
    Replaced with ``safe_float`` / ``safe_int``.

  * ``_normalize_order`` did ``payload.get("customer", {}).
    get("id", "")`` — on guest orders Shopify sends
    ``"customer": null``, which crashed the chained ``.get``
    (same ``.get(k, {})`` vs present-but-None pattern fixed
    in passes 32/36/40/41).

  * ``_normalize_product`` did ``payload.get("variants",
    [{}])[0]`` — if ``variants`` was a dict (not a list),
    ``[0]`` on a dict raised KeyError.

  * ``OrderWebhookHandler._processed += 1`` was not
    thread-safe; webhooks arrive on multiple threads.

  * ``register_handler`` wrote to ``_custom_handlers`` without
    the lock.

Fail-closed HMAC:
  Pre-audit ``if self._secret and hmac_header`` skipped
  verification when the attacker omitted the header. Now
  configured secret + missing header = rejected.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import threading
import time

import pytest

from core.webhooks import ShopifyWebhookHandler, WebhookEvent
from core.webhooks.order_handler import OrderWebhookHandler


def _sign(secret: str, body: bytes) -> str:
    """Produce a valid Shopify-format HMAC header."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


# ═══════════════════════════════════════════════════════════
# HMAC verification
# ═══════════════════════════════════════════════════════════


class TestHMACVerification:
    def test_no_secret_skips_verification(self):
        h = ShopifyWebhookHandler()
        r = h.handle("orders/create", {"id": 1})
        assert r["status"] != "rejected"

    def test_secret_and_no_header_rejects(self):
        """Fail-closed: configured secret + missing HMAC header
        must be rejected, not silently accepted."""
        h = ShopifyWebhookHandler(webhook_secret="test")
        r = h.handle("orders/create", {"id": 1})
        assert r["status"] == "rejected"
        assert r["reason"] == "missing_hmac_header"

    def test_secret_and_header_but_no_raw_body_rejects(self):
        """Fail-closed: without the raw bytes we can't verify,
        so reject instead of falling back to the broken
        re-serialisation path."""
        h = ShopifyWebhookHandler(webhook_secret="test")
        r = h.handle("orders/create", {"id": 1}, hmac_header="anything")
        assert r["status"] == "rejected"
        assert r["reason"] == "raw_body_required_for_hmac"

    def test_valid_base64_hmac_passes(self):
        """Regression: pre-audit used hexdigest, but Shopify
        sends HMAC base64-encoded."""
        secret = "test_secret"
        raw = b'{"id":1,"total_price":"99.99"}'
        valid = _sign(secret, raw)
        h = ShopifyWebhookHandler(webhook_secret=secret)
        r = h.handle(
            "orders/create",
            {"id": 1, "total_price": "99.99"},
            hmac_header=valid,
            raw_body=raw,
        )
        assert r["status"] == "processed"

    def test_invalid_hmac_rejects(self):
        h = ShopifyWebhookHandler(webhook_secret="test")
        raw = b'{"id":1}'
        r = h.handle(
            "orders/create",
            {"id": 1},
            hmac_header="wrong_base64_string",
            raw_body=raw,
        )
        assert r["status"] == "rejected"
        assert r["reason"] == "invalid_hmac"

    def test_hmac_verified_against_raw_not_reserialized(self):
        """Regression: the pre-audit code did
        ``hmac.new(secret, json.dumps(payload).encode())`` —
        which almost never matches Shopify's digest because
        json.dumps changes whitespace and key order. Signing
        the EXACT bytes Shopify sent must work even when those
        bytes are NOT what json.dumps would produce."""
        secret = "test_secret"
        # Pick an unusual byte stream (extra whitespace, specific
        # key order) that json.dumps would never reproduce
        # verbatim.
        raw = b'{  "id"   :1,\n  "total_price": "5.00"  }'
        valid = _sign(secret, raw)
        h = ShopifyWebhookHandler(webhook_secret=secret)
        r = h.handle(
            "orders/create",
            {"id": 1, "total_price": "5.00"},
            hmac_header=valid,
            raw_body=raw,
        )
        assert r["status"] == "processed"

    def test_hmac_compare_is_constant_time(self):
        """Sanity check that compare_digest is used (not ==)."""
        secret = "test_secret"
        raw = b'{"id":1}'
        h = ShopifyWebhookHandler(webhook_secret=secret)
        # Just confirm rejection behavior is not timing-correlated
        # with header length / similarity. We're not timing the
        # calls — only asserting rejection works for various
        # wrong headers of various lengths.
        for bad in ["", "short", "x" * 50, "a" * 200]:
            r = h.handle("orders/create", {}, hmac_header=bad, raw_body=raw)
            assert r["status"] == "rejected"


# ═══════════════════════════════════════════════════════════
# handle_async event-id round-trip
# ═══════════════════════════════════════════════════════════


class TestHandleAsync:
    def test_async_event_id_matches_processed(self):
        """Regression: pre-audit ``handle_async`` returned its
        own id but the spawned thread minted a new one inside
        ``handle()``. Same bug as pass 38 EventReactor."""
        h = ShopifyWebhookHandler()
        seen_ids: list[str] = []

        def custom(event: WebhookEvent) -> None:
            seen_ids.append(event.event_id)

        h.register_handler("custom.test", custom)
        returned_id = h.handle_async("custom.test", {"x": 1})

        # Give the background thread a moment.
        for _ in range(50):
            if seen_ids:
                break
            time.sleep(0.01)

        # custom.test isn't in EVENT_ENGINE_MAP so the handler
        # for "custom.test" only runs if mappings are empty —
        # in which case handle() returns early with "skipped"
        # BEFORE custom handlers run. Use an event type that
        # IS mapped.
        h2 = ShopifyWebhookHandler()
        seen_ids_2: list[str] = []

        def custom2(event: WebhookEvent) -> None:
            seen_ids_2.append(event.event_id)

        h2.register_handler("orders/create", custom2)
        returned_id2 = h2.handle_async("orders/create", {"id": 1})
        for _ in range(50):
            if seen_ids_2:
                break
            time.sleep(0.01)

        assert seen_ids_2, "custom handler did not run"
        assert returned_id2 in seen_ids_2


# ═══════════════════════════════════════════════════════════
# Normalize helpers
# ═══════════════════════════════════════════════════════════


class TestNormalizers:
    def test_normalize_order_with_null_customer(self):
        """Regression: guest orders ship ``"customer": null``;
        the chained .get used to crash."""
        result = ShopifyWebhookHandler._normalize_order({
            "id": 1,
            "customer": None,
            "total_price": "9.99",
        })
        assert result[0]["customer_id"] == ""
        assert result[0]["total"] == 9.99

    def test_normalize_order_with_non_numeric_total(self):
        result = ShopifyWebhookHandler._normalize_order({
            "id": 1,
            "total_price": "N/A",
            "subtotal_price": None,
        })
        assert result[0]["total"] == 0.0
        assert result[0]["subtotal"] == 0.0

    def test_normalize_order_with_non_list_line_items(self):
        result = ShopifyWebhookHandler._normalize_order({
            "id": 1,
            "line_items": "not a list",
        })
        assert result[0]["items"] == 0

    def test_normalize_order_none_payload(self):
        result = ShopifyWebhookHandler._normalize_order(None)
        assert result == [{}]

    def test_normalize_product_with_dict_variants(self):
        """Regression: ``payload.get("variants", [{}])[0]``
        crashed when ``variants`` was a dict (which happens
        with some malformed Shopify scraper output)."""
        result = ShopifyWebhookHandler._normalize_product({
            "id": 1,
            "title": "Test",
            "variants": {"not": "a list"},
        })
        assert result[0]["id"] == "1"
        assert result[0]["price"] == 0.0

    def test_normalize_product_with_non_numeric_price(self):
        result = ShopifyWebhookHandler._normalize_product({
            "id": 1,
            "variants": [{"price": "$99.99", "inventory_quantity": "25"}],
        })
        assert result[0]["price"] == 99.99
        assert result[0]["inventory_quantity"] == 25

    def test_normalize_customer_with_none_names(self):
        """first_name / last_name can be None; f-string would
        stringify "None None" pre-audit."""
        result = ShopifyWebhookHandler._normalize_customer({
            "id": 1,
            "first_name": None,
            "last_name": None,
            "email": "test@example.com",
        })
        assert result[0]["name"] == ""

    def test_normalize_customer_with_string_orders_count(self):
        result = ShopifyWebhookHandler._normalize_customer({
            "id": 1,
            "orders_count": "5",
            "total_spent": "$1,234.50",
        })
        assert result[0]["orders"] == 5
        assert result[0]["total_spent"] == 1234.5

    def test_normalize_inventory_non_numeric(self):
        result = ShopifyWebhookHandler._normalize_inventory_level({
            "inventory_item_id": 1,
            "available": "25",
        })
        assert result["available"] == 25


# ═══════════════════════════════════════════════════════════
# Defensive entry coercion
# ═══════════════════════════════════════════════════════════


class TestDefensiveEntry:
    def test_none_topic(self):
        h = ShopifyWebhookHandler()
        r = h.handle(None, {"id": 1})
        assert isinstance(r, dict)

    def test_none_payload(self):
        h = ShopifyWebhookHandler()
        r = h.handle("orders/create", None)
        assert isinstance(r, dict)
        assert r["status"] != "error"

    def test_non_dict_payload(self):
        h = ShopifyWebhookHandler()
        r = h.handle("orders/create", "raw string")
        assert isinstance(r, dict)

    def test_register_handler_rejects_non_callable(self):
        h = ShopifyWebhookHandler()
        h.register_handler("orders/create", "not callable")  # type: ignore[arg-type]
        # Should not have added anything.
        r = h.handle("orders/create", {"id": 1})
        # Still succeeds via the engine path.
        assert r["status"] == "processed"

    def test_register_handler_concurrent_safe(self):
        """register_handler used to write without the lock —
        concurrent register + handle crashed."""
        h = ShopifyWebhookHandler()
        stop = threading.Event()

        def noop(event):
            return None

        def reg_loop():
            i = 0
            while not stop.is_set():
                h.register_handler(f"topic_{i % 3}", noop)
                i += 1

        def handle_loop():
            while not stop.is_set():
                h.handle("orders/create", {"id": 1})

        t1 = threading.Thread(target=reg_loop)
        t2 = threading.Thread(target=handle_loop)
        t1.start()
        t2.start()
        time.sleep(0.1)
        stop.set()
        t1.join(timeout=2)
        t2.join(timeout=2)
        assert not t1.is_alive() and not t2.is_alive()


# ═══════════════════════════════════════════════════════════
# OrderWebhookHandler
# ═══════════════════════════════════════════════════════════


class TestOrderWebhookHandler:
    def test_none_order_data_does_not_crash(self):
        h = OrderWebhookHandler()
        r = h.handle_order_paid(None)
        assert isinstance(r, dict)
        assert r["order_id"] == ""

    def test_null_customer_on_guest_order(self):
        """Same guest-order null-customer bug as the normalizer."""
        h = OrderWebhookHandler()
        r = h.handle_order_paid({
            "id": 1,
            "customer": None,
            "total_price": "50",
        })
        assert isinstance(r, dict)
        assert r["order_id"] == "1"

    def test_cancelled_none_data(self):
        h = OrderWebhookHandler()
        r = h.handle_order_cancelled(None)
        assert r["order_id"] == ""
        assert r["outcome_tracked"] is False

    def test_processed_counter_thread_safe(self):
        """Regression: ``self._processed += 1`` was not
        thread-safe. Hammer it from 8 threads and verify the
        final count is exact."""
        h = OrderWebhookHandler()
        barrier = threading.Barrier(8)

        def fire():
            barrier.wait()
            for _ in range(50):
                h.handle_order_paid({"id": 1, "total_price": "1"})

        threads = [threading.Thread(target=fire) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 8 threads × 50 calls = 400 expected.
        assert h.get_stats()["orders_processed"] == 400

    def test_non_list_note_attributes(self):
        h = OrderWebhookHandler()
        r = h.handle_order_paid({
            "id": 1,
            "note_attributes": "not a list",
            "total_price": "10",
        })
        assert r["order_id"] == "1"
