"""Tests for Wave 2 of shopify_admin: fulfillments + refunds
+ customers."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)
from core.adapters.shopify_admin.customers import (
    Customers, CustomerAddresses, _split_tags,
)
from core.adapters.shopify_admin.fulfillments import (
    Fulfillments, FulfillmentOrders,
)
from core.adapters.shopify_admin.refunds import (
    Refunds, Transactions,
)


def _fake_client():
    return MagicMock(spec=ShopifyAdminClient)


# ── FulfillmentOrders ───────────────────────────────────


class TestFulfillmentOrdersRead:
    def test_list_for_order(self):
        c = _fake_client()
        c.get.return_value = {"fulfillment_orders": [
            {"id": 1, "status": "open"},
            {"id": 2, "status": "closed"},
        ]}
        rows = FulfillmentOrders.list_for_order(c, 42)
        assert len(rows) == 2
        path = c.get.call_args[0][0]
        assert "orders/42/fulfillment_orders.json" in path

    def test_get_not_returned_raises(self):
        c = _fake_client()
        c.get.return_value = {"error": "missing"}
        with pytest.raises(ShopifyAdminError):
            FulfillmentOrders.get(c, 99)

    def test_cancel_returns_fo(self):
        c = _fake_client()
        c.post.return_value = {"fulfillment_order": {"id": 5}}
        fo = FulfillmentOrders.cancel(c, 5)
        assert fo["id"] == 5
        assert "cancel.json" in c.post.call_args[0][0]

    def test_close_with_message(self):
        c = _fake_client()
        c.post.return_value = {"fulfillment_order": {"id": 5}}
        FulfillmentOrders.close(
            c, 5, message="owner cancelled",
        )
        body = c.post.call_args[0][1]
        assert body == {"message": "owner cancelled"}

    def test_close_without_message_empty_body(self):
        c = _fake_client()
        c.post.return_value = {}
        FulfillmentOrders.close(c, 5)
        body = c.post.call_args[0][1]
        assert body == {}

    def test_move_location(self):
        c = _fake_client()
        c.post.return_value = {
            "original_fulfillment_order": {"id": 5},
            "moved_fulfillment_order": {"id": 6},
        }
        FulfillmentOrders.move(c, 5, new_location_id=42)
        body = c.post.call_args[0][1]
        assert body == {
            "fulfillment_order": {"new_location_id": 42},
        }


# ── Fulfillments ────────────────────────────────────────


class TestFulfillmentsCreate:
    def test_requires_line_items(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Fulfillments.create(
                c, line_items_by_fulfillment_order=[],
            )

    def test_happy_path_with_tracking(self):
        c = _fake_client()
        c.post.return_value = {"fulfillment": {"id": 77}}
        Fulfillments.create(
            c,
            line_items_by_fulfillment_order=[{
                "fulfillment_order_id": 5,
                "fulfillment_order_line_items": [
                    {"id": 1, "quantity": 1},
                ],
            }],
            tracking_number="1Z99",
            tracking_url="https://ups.com/track/1Z99",
            tracking_company="UPS",
        )
        body = c.post.call_args[0][1]
        assert body["fulfillment"]["tracking_info"] == {
            "number": "1Z99",
            "url": "https://ups.com/track/1Z99",
            "company": "UPS",
        }

    def test_without_tracking_skips_tracking_info(self):
        c = _fake_client()
        c.post.return_value = {"fulfillment": {"id": 77}}
        Fulfillments.create(
            c,
            line_items_by_fulfillment_order=[{
                "fulfillment_order_id": 5,
            }],
        )
        body = c.post.call_args[0][1]
        assert "tracking_info" not in body["fulfillment"]

    def test_notify_customer_default_true(self):
        c = _fake_client()
        c.post.return_value = {"fulfillment": {}}
        Fulfillments.create(
            c,
            line_items_by_fulfillment_order=[{
                "fulfillment_order_id": 5,
            }],
        )
        body = c.post.call_args[0][1]
        assert body["fulfillment"]["notify_customer"] is True


class TestFulfillmentsUpdateTracking:
    def test_update_tracking(self):
        c = _fake_client()
        c.post.return_value = {"fulfillment": {"id": 99}}
        Fulfillments.update_tracking(
            c, 99,
            tracking_number="1Z99X",
            tracking_company="UPS",
        )
        path = c.post.call_args[0][0]
        assert "/99/update_tracking.json" in path
        body = c.post.call_args[0][1]
        assert body["fulfillment"]["tracking_info"][
            "number"
        ] == "1Z99X"

    def test_cancel(self):
        c = _fake_client()
        c.post.return_value = {"fulfillment": {"id": 99}}
        Fulfillments.cancel(c, 99)
        assert "/99/cancel.json" in c.post.call_args[0][0]

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {"error": "gone"}
        with pytest.raises(ShopifyAdminError):
            Fulfillments.get(c, 99)

    def test_list_for_order(self):
        c = _fake_client()
        c.get.return_value = {"fulfillments": [
            {"id": 1}, {"id": 2}, "not-a-dict",
        ]}
        rows = Fulfillments.list_for_order(c, 42)
        # Non-dict filtered
        assert len(rows) == 2


# ── Refunds ─────────────────────────────────────────────


class TestRefundsRead:
    def test_list_for_order(self):
        c = _fake_client()
        c.get.return_value = {"refunds": [{"id": 1}]}
        assert len(Refunds.list_for_order(c, 42)) == 1

    def test_get_refund(self):
        c = _fake_client()
        c.get.return_value = {"refund": {"id": 77}}
        r = Refunds.get(c, 42, 77)
        assert r["id"] == 77

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            Refunds.get(c, 42, 77)


class TestRefundsCalculate:
    def test_calculate_minimal(self):
        c = _fake_client()
        c.post.return_value = {"refund": {
            "transactions": [{
                "amount": "20.00", "kind": "refund",
            }],
        }}
        preview = Refunds.calculate(c, 42)
        assert preview["transactions"][0]["amount"] == "20.00"
        path = c.post.call_args[0][0]
        assert "refunds/calculate.json" in path

    def test_calculate_with_items_and_shipping(self):
        c = _fake_client()
        c.post.return_value = {"refund": {}}
        Refunds.calculate(
            c, 42,
            refund_line_items=[{
                "line_item_id": 1, "quantity": 1,
                "restock_type": "return",
            }],
            shipping={"full_refund": True},
            currency="USD",
        )
        body = c.post.call_args[0][1]
        assert body["refund"]["refund_line_items"][0][
            "line_item_id"
        ] == 1
        assert body["refund"]["shipping"] == {
            "full_refund": True,
        }
        assert body["refund"]["currency"] == "USD"


class TestRefundsCreate:
    def test_create_with_transactions(self):
        c = _fake_client()
        c.post.return_value = {"refund": {"id": 99}}
        Refunds.create(
            c, 42,
            transactions=[{
                "parent_id": 100, "amount": "20.00",
                "kind": "refund",
            }],
            note="buyer returned item",
        )
        body = c.post.call_args[0][1]
        assert body["refund"]["transactions"][0][
            "amount"
        ] == "20.00"
        assert body["refund"]["note"] == "buyer returned item"
        assert body["refund"]["notify"] is True

    def test_create_notify_false(self):
        c = _fake_client()
        c.post.return_value = {"refund": {"id": 1}}
        Refunds.create(c, 42, notify=False)
        body = c.post.call_args[0][1]
        assert body["refund"]["notify"] is False

    def test_create_not_returned_raises(self):
        c = _fake_client()
        c.post.return_value = {"error": "bad"}
        with pytest.raises(ShopifyAdminError):
            Refunds.create(c, 42)


class TestTransactions:
    def test_list_for_order(self):
        c = _fake_client()
        c.get.return_value = {"transactions": [{"id": 1}]}
        assert len(Transactions.list_for_order(c, 42)) == 1

    def test_create_manual_sale(self):
        c = _fake_client()
        c.post.return_value = {"transaction": {"id": 1}}
        Transactions.create(
            c, 42,
            kind="sale", amount=29.99,
            gateway="manual",
        )
        body = c.post.call_args[0][1]
        assert body["transaction"]["amount"] == "29.99"
        assert body["transaction"]["kind"] == "sale"
        assert body["transaction"]["gateway"] == "manual"

    def test_create_amount_string_preserved(self):
        """Caller passed already-formatted string — don't
        re-format (avoids rounding surprises)."""
        c = _fake_client()
        c.post.return_value = {"transaction": {"id": 1}}
        Transactions.create(
            c, 42, kind="refund", amount="19.99",
            parent_id=100,
        )
        body = c.post.call_args[0][1]
        assert body["transaction"]["amount"] == "19.99"
        assert body["transaction"]["parent_id"] == 100

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            Transactions.get(c, 42, 1)


# ── Customers ──────────────────────────────────────────


class TestCustomersRead:
    def test_list_with_filters(self):
        c = _fake_client()
        c.get.return_value = {"customers": [
            {"id": 1}, {"id": 2},
        ]}
        Customers.list_customers(
            c, limit=100, ids=[1, 2, 3], since_id=5,
        )
        params = c.get.call_args[1]["params"]
        assert params["limit"] == 100
        assert params["ids"] == "1,2,3"
        assert params["since_id"] == "5"

    def test_get(self):
        c = _fake_client()
        c.get.return_value = {"customer": {"id": 42}}
        assert Customers.get(c, 42)["id"] == 42

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            Customers.get(c, 42)

    def test_count(self):
        c = _fake_client()
        c.get.return_value = {"count": 42}
        assert Customers.count(c) == 42

    def test_search_query_required(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Customers.search(c, "")

    def test_search_passes_query(self):
        c = _fake_client()
        c.get.return_value = {"customers": []}
        Customers.search(c, "email:jane*", limit=100)
        params = c.get.call_args[1]["params"]
        assert params["query"] == "email:jane*"
        assert params["limit"] == 100


class TestCustomersWrite:
    def test_create_validates_email(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Customers.create(c, email="")
        with pytest.raises(ValueError):
            Customers.create(c, email="not-an-email")

    def test_create_happy_path(self):
        c = _fake_client()
        c.post.return_value = {"customer": {"id": 1}}
        Customers.create(
            c, email="JANE@X.COM",
            first_name="Jane",
            last_name="Doe",
            phone="+1555",
            tags=["VIP", "bedroom"],
            accepts_marketing=True,
            note="enrolled 2026-04-22",
        )
        body = c.post.call_args[0][1]
        cust = body["customer"]
        assert cust["email"] == "jane@x.com"  # lowercased
        assert cust["first_name"] == "Jane"
        assert cust["tags"] == "VIP, bedroom"
        assert cust["accepts_marketing"] is True
        assert cust["note"] == "enrolled 2026-04-22"

    def test_create_respects_send_email_flags(self):
        c = _fake_client()
        c.post.return_value = {"customer": {"id": 1}}
        Customers.create(
            c, email="a@b.c",
            send_email_invite=True,
            send_email_welcome=False,
        )
        body = c.post.call_args[0][1]
        cust = body["customer"]
        assert cust["send_email_invite"] is True
        assert cust["send_email_welcome"] is False

    def test_update_injects_id(self):
        c = _fake_client()
        c.put.return_value = {"customer": {"id": 42}}
        Customers.update(
            c, 42, fields={"first_name": "Janet"},
        )
        body = c.put.call_args[0][1]
        assert body["customer"]["id"] == 42
        assert body["customer"]["first_name"] == "Janet"

    def test_update_empty_fields_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Customers.update(c, 42, fields={})

    def test_delete(self):
        c = _fake_client()
        Customers.delete(c, 42)
        c.delete.assert_called_once()


class TestCustomerTags:
    def test_add_tags_merges(self):
        c = _fake_client()
        c.get.return_value = {"customer": {
            "id": 42, "tags": "VIP, bedroom",
        }}
        c.put.return_value = {"customer": {"id": 42}}
        Customers.add_tags(c, 42, ["loyal", "spring-2026"])
        body = c.put.call_args[0][1]
        tags = set(
            body["customer"]["tags"].split(", "),
        )
        assert tags == {
            "VIP", "bedroom", "loyal", "spring-2026",
        }

    def test_add_tags_empty_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Customers.add_tags(c, 42, [])

    def test_remove_tags_case_insensitive(self):
        c = _fake_client()
        c.get.return_value = {"customer": {
            "id": 42, "tags": "VIP, bedroom, loyal",
        }}
        c.put.return_value = {"customer": {"id": 42}}
        Customers.remove_tags(c, 42, ["LOYAL"])
        body = c.put.call_args[0][1]
        tags = set(
            body["customer"]["tags"].split(", "),
        )
        assert tags == {"VIP", "bedroom"}

    def test_split_tags_list_input(self):
        assert _split_tags(["a", "b"]) == ["a", "b"]

    def test_split_tags_empty(self):
        assert _split_tags("") == []
        assert _split_tags(None) == []

    def test_split_tags_string(self):
        assert _split_tags("a, b,c") == ["a", "b", "c"]


# ── CustomerAddresses ──────────────────────────────────


class TestCustomerAddresses:
    def test_list(self):
        c = _fake_client()
        c.get.return_value = {"addresses": [
            {"id": 1}, {"id": 2},
        ]}
        assert len(
            CustomerAddresses.list_addresses(c, 42),
        ) == 2

    def test_create(self):
        c = _fake_client()
        c.post.return_value = {"customer_address": {"id": 1}}
        CustomerAddresses.create(c, 42, address={
            "address1": "1 Main St",
            "city": "Boston",
            "country": "US",
            "first_name": "Jane",
            "last_name": "Doe",
            "zip": "02101",
        })
        body = c.post.call_args[0][1]
        assert body["address"]["city"] == "Boston"

    def test_create_empty_address_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            CustomerAddresses.create(c, 42, address={})

    def test_update(self):
        c = _fake_client()
        c.put.return_value = {"customer_address": {"id": 1}}
        CustomerAddresses.update(
            c, 42, 1, fields={"zip": "02102"},
        )
        body = c.put.call_args[0][1]
        assert body["address"]["zip"] == "02102"

    def test_delete(self):
        c = _fake_client()
        CustomerAddresses.delete(c, 42, 1)
        c.delete.assert_called_once()

    def test_set_default(self):
        c = _fake_client()
        c.put.return_value = {"customer_address": {
            "id": 1, "default": True,
        }}
        CustomerAddresses.set_default(c, 42, 1)
        path = c.put.call_args[0][0]
        assert "/addresses/1/default.json" in path
