"""Tests for audit-pass-48 fixes — defensive + thread-safety
hardening across ``data_pipeline.store`` (db.py, sync_service.py,
store_manager.py, data_provider.py).

Real bugs fixed:

  * ``ShopAIDatabase.upsert_products`` /``upsert_orders`` /
    ``upsert_customers`` used bare ``float()`` / ``int()`` on
    user-supplied product fields. Shopify / scraper / CSV
    data regularly delivers these as currency strings
    (``"$99.99"``), comma-formatted numbers (``"1,234"``), or
    None. Pre-audit any non-numeric value crashed the entire
    batch — a single bad row took out every subsequent row
    in the transaction. Replaced with ``safe_float`` /
    ``safe_int`` and per-row try/except so one bad row just
    gets logged and skipped.

  * ``upsert_*`` did not guard against non-dict rows —
    ``"bad string" in products`` crashed ``str(row.get(...))``.
    Now skipped.

  * ``_product_to_dict`` / ``_order_to_dict`` /
    ``_customer_to_dict`` did bare ``json.loads(d.get("tags",
    "[]"))`` on DB columns. A corrupted JSON column (from a
    crash mid-write or manual DB edit) propagated
    JSONDecodeError to the caller, taking down whatever
    engine was reading the data. Now wrapped in a
    ``_safe_json_loads`` helper.

  * ``save_snapshot`` used bare ``json.dumps(data)`` which
    crashed on non-serialisable values (sets, datetimes,
    custom objects). Now uses ``_safe_json_dumps`` with
    ``default=str``.

  * ``sync_service._normalize_products`` /``_orders`` /
    ``_customers`` had the same bare ``float()`` / ``int()``
    crashes plus ``p.get("variants", [{}])[0]`` which crashed
    when variants was a non-list dict.

  * ``sync_service._normalize_products`` did
    ``.split(", ")`` on the tags field — crashed with
    AttributeError on ``"tags": null``.

  * ``sync_service._sync_product_costs`` had the same
    double-scheme URL bug fixed in pass 43 — produced
    ``https://https://shop.../`` when shop_url had a scheme
    prefix. Now uses ``_normalize_shop_url`` from pass 43.

  * ``store_manager._get_auth_instance`` did check-then-assign
    without a lock — two concurrent first-callers for the
    same key both constructed a ShopifyAuth instance, the
    second overwrite silently discarding the first's token
    cache.

  * ``store_manager._store_credentials`` / ``_active_store_id``
    had no lock protection. Concurrent ``add_store`` /
    ``set_active_store`` / ``get_credentials`` could race and
    see torn state.

  * ``store_manager.add_store`` wrote to
    ``_store_credentials`` BEFORE calling ``db.add_store()``.
    If the DB write failed the in-memory credentials cache
    was left hanging. Now DB first, memory second.

  * ``store_manager.list_stores`` mutated the DB row dicts
    in place — if another caller held a reference to those
    rows they saw the in-place ``is_active`` mutation. Now
    returns deep-copied rows.

  * ``data_provider._engine_data_needs`` did
    ``engine_name.lower()`` which crashed on None.
"""
from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from unittest import mock

import pytest

from data_pipeline.store.data_provider import DataProvider
from data_pipeline.store.db import (
    ShopAIDatabase,
    _safe_json_dumps,
    _safe_json_loads,
)
from data_pipeline.store.store_manager import (
    StoreManager,
    _get_auth_instance,
    _auth_instances,
    _auth_lock,
)
from data_pipeline.store.sync_service import SyncService


@pytest.fixture
def fresh_db():
    """Give each test its own isolated SQLite file."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.db"
        db = ShopAIDatabase(db_path=path)
        yield db
        db.close()


# ═══════════════════════════════════════════════════════════
# JSON helpers
# ═══════════════════════════════════════════════════════════


class TestJsonHelpers:
    def test_safe_loads_none(self):
        assert _safe_json_loads(None, default=[]) == []

    def test_safe_loads_bad(self):
        assert _safe_json_loads("{not json", default={}) == {}

    def test_safe_loads_valid(self):
        assert _safe_json_loads("[1,2,3]", default=[]) == [1, 2, 3]

    def test_safe_loads_non_string(self):
        assert _safe_json_loads(42, default=[]) == []

    def test_safe_dumps_valid(self):
        assert _safe_json_dumps({"a": 1}) == '{"a": 1}'

    def test_safe_dumps_non_serializable_set(self):
        """Regression: pre-audit ``save_snapshot`` crashed on
        a set in the data dict."""
        result = _safe_json_dumps({"tags": {"a", "b"}})
        # default=str coerces the set — exact string form is
        # implementation-defined, just verify no crash.
        assert isinstance(result, str)
        assert len(result) > 0


# ═══════════════════════════════════════════════════════════
# ShopAIDatabase upsert_* defensive
# ═══════════════════════════════════════════════════════════


class TestUpsertProducts:
    def test_none_products(self, fresh_db):
        fresh_db.add_store("s1", "test.myshopify.com")
        assert fresh_db.upsert_products("s1", None) == 0

    def test_non_list_products(self, fresh_db):
        fresh_db.add_store("s1", "test.myshopify.com")
        assert fresh_db.upsert_products("s1", "not a list") == 0

    def test_empty_store_id(self, fresh_db):
        assert fresh_db.upsert_products("", [{"id": "p1", "title": "x"}]) == 0

    def test_non_dict_rows_skipped(self, fresh_db):
        fresh_db.add_store("s1", "test.myshopify.com")
        count = fresh_db.upsert_products("s1", [
            "bad string",
            None,
            42,
            {"id": "p1", "title": "Good", "price": 99.99},
            ["list"],
        ])
        assert count == 1

    def test_currency_string_prices(self, fresh_db):
        """Regression: bare ``float("$99.99")`` crashed the
        entire batch."""
        fresh_db.add_store("s1", "test.myshopify.com")
        count = fresh_db.upsert_products("s1", [
            {"id": "p1", "title": "T1", "price": "$99.99", "cost": "$50.00"},
            {"id": "p2", "title": "T2", "price": "N/A", "cost": None},
            {"id": "p3", "title": "T3", "price": 30, "cost": 10},
        ])
        assert count == 3
        products = {p["id"]: p for p in fresh_db.get_products("s1")}
        assert products["p1"]["price"] == 99.99
        assert products["p1"]["cost"] == 50.0
        # "N/A" → 0.0
        assert products["p2"]["price"] == 0.0
        assert products["p3"]["price"] == 30.0


class TestUpsertOrders:
    def test_none_orders(self, fresh_db):
        fresh_db.add_store("s1", "test.myshopify.com")
        assert fresh_db.upsert_orders("s1", None) == 0

    def test_currency_total(self, fresh_db):
        fresh_db.add_store("s1", "test.myshopify.com")
        count = fresh_db.upsert_orders("s1", [
            {"id": "o1", "total": "$500.00", "subtotal": "$450.00"},
        ])
        assert count == 1
        orders = fresh_db.get_all_orders("s1")
        assert orders[0]["total"] == 500.0
        assert orders[0]["subtotal"] == 450.0

    def test_non_list_line_items(self, fresh_db):
        fresh_db.add_store("s1", "test.myshopify.com")
        count = fresh_db.upsert_orders("s1", [
            {"id": "o1", "line_items": "not a list"},
        ])
        assert count == 1


class TestUpsertCustomers:
    def test_none_customers(self, fresh_db):
        fresh_db.add_store("s1", "test.myshopify.com")
        assert fresh_db.upsert_customers("s1", None) == 0

    def test_currency_total_spent(self, fresh_db):
        fresh_db.add_store("s1", "test.myshopify.com")
        count = fresh_db.upsert_customers("s1", [
            {"id": "c1", "total_spent": "$1,234.56", "orders_count": "5"},
        ])
        assert count == 1


# ═══════════════════════════════════════════════════════════
# ShopAIDatabase _*_to_dict JSON decode safety
# ═══════════════════════════════════════════════════════════


class TestToDictJsonSafety:
    def test_corrupted_tags_column(self, fresh_db):
        """Regression: pre-audit a corrupted JSON column
        propagated JSONDecodeError to the caller."""
        fresh_db.add_store("s1", "test.myshopify.com")
        # Insert a product then corrupt its tags column directly.
        fresh_db.upsert_products("s1", [{"id": "p1", "title": "T"}])
        conn = fresh_db._get_conn()
        conn.execute("UPDATE products SET tags = '{not json' WHERE id = ?", ("p1",))
        conn.commit()
        # Read should not crash.
        products = fresh_db.get_products("s1")
        assert len(products) == 1
        assert products[0]["tags"] == []


# ═══════════════════════════════════════════════════════════
# save_snapshot / get_snapshots
# ═══════════════════════════════════════════════════════════


class TestSnapshots:
    def test_non_serializable_data(self, fresh_db):
        """Regression: bare ``json.dumps(data)`` crashed on sets."""
        fresh_db.add_store("s1", "test.myshopify.com")
        # Must not raise.
        snap_id = fresh_db.save_snapshot("s1", "test", {"tags": {"a", "b", "c"}})
        assert isinstance(snap_id, int)

    def test_corrupted_snapshot_column(self, fresh_db):
        fresh_db.add_store("s1", "test.myshopify.com")
        fresh_db.save_snapshot("s1", "test", {"ok": True})
        conn = fresh_db._get_conn()
        conn.execute(
            "UPDATE analytics_snapshots SET data = '{not json' WHERE store_id = ?",
            ("s1",),
        )
        conn.commit()
        snaps = fresh_db.get_snapshots("s1", "test")
        assert len(snaps) == 1
        assert snaps[0]["data"] == {}


# ═══════════════════════════════════════════════════════════
# SyncService normalizers
# ═══════════════════════════════════════════════════════════


class TestSyncNormalizers:
    def test_products_none(self):
        assert SyncService._normalize_products(None) == []

    def test_products_currency_strings(self):
        result = SyncService._normalize_products([
            {
                "id": 1,
                "title": "T",
                "variants": [{"price": "$99.99", "cost": "$50.00", "inventory_quantity": "10"}],
            },
        ])
        assert len(result) == 1
        assert result[0]["price"] == 99.99
        assert result[0]["cost"] == 50.0
        assert result[0]["inventory_quantity"] == 10

    def test_products_non_list_variants(self):
        """Regression: ``p.get("variants", [{}])[0]`` crashed
        when variants was a dict."""
        result = SyncService._normalize_products([
            {"id": 1, "title": "T", "variants": {"not": "a list"}},
        ])
        assert len(result) == 1
        assert result[0]["variants"] == []
        assert result[0]["price"] == 0.0

    def test_products_null_tags(self):
        """Regression: ``p.get("tags", "").split(", ")``
        crashed on ``"tags": null``."""
        result = SyncService._normalize_products([
            {"id": 1, "title": "T", "tags": None},
        ])
        assert result[0]["tags"] == []

    def test_products_string_tags(self):
        result = SyncService._normalize_products([
            {"id": 1, "title": "T", "tags": "a, b, c"},
        ])
        assert result[0]["tags"] == ["a", "b", "c"]

    def test_products_non_dict_items_skipped(self):
        result = SyncService._normalize_products([
            None,
            "bad",
            {"id": 1, "title": "Good"},
        ])
        assert len(result) == 1

    def test_orders_none(self):
        assert SyncService._normalize_orders(None) == []

    def test_orders_null_customer(self):
        """Regression: ``customer`` key present-but-None
        crashed the ``.get("id")`` chain."""
        result = SyncService._normalize_orders([
            {"id": 1, "customer": None, "total_price": "$500"},
        ])
        assert result[0]["customer_id"] == ""
        assert result[0]["total"] == 500.0

    def test_orders_null_line_items(self):
        result = SyncService._normalize_orders([
            {"id": 1, "line_items": None},
        ])
        assert result[0]["item_count"] == 0

    def test_customers_none(self):
        assert SyncService._normalize_customers(None) == []

    def test_customers_null_names(self):
        result = SyncService._normalize_customers([
            {"id": 1, "first_name": None, "last_name": None},
        ])
        # Empty name, not "None None".
        assert result[0]["name"] == ""

    def test_customers_currency_total_spent(self):
        result = SyncService._normalize_customers([
            {"id": 1, "total_spent": "$1,234.56", "orders_count": "5"},
        ])
        assert result[0]["total_spent"] == 1234.56
        assert result[0]["orders_count"] == 5


# ═══════════════════════════════════════════════════════════
# StoreManager thread safety
# ═══════════════════════════════════════════════════════════


class TestStoreManagerThreadSafety:
    def test_concurrent_add_store(self, fresh_db):
        """Concurrent add_store calls must not crash or produce
        torn state."""
        sm = StoreManager(db=fresh_db)
        errors: list[Exception] = []
        barrier = threading.Barrier(8)

        def add(i: int):
            try:
                barrier.wait()
                sm.add_store(f"s{i}", f"store{i}.myshopify.com", api_key=f"k{i}")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=add, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(sm.list_stores()) == 8

    def test_list_stores_returns_copies(self, fresh_db):
        """Regression: pre-audit mutated DB row dicts in place.
        A caller mutating the returned list must NOT affect a
        subsequent call."""
        sm = StoreManager(db=fresh_db)
        sm.add_store("s1", "s1.myshopify.com")
        stores_a = sm.list_stores()
        stores_a[0]["extra"] = "mutated"
        stores_b = sm.list_stores()
        assert "extra" not in stores_b[0]

    def test_add_store_rollback_on_empty_args(self, fresh_db):
        sm = StoreManager(db=fresh_db)
        result = sm.add_store("", "url")
        assert "error" in result
        result2 = sm.add_store("s1", "")
        assert "error" in result2
        # No stores added
        assert sm.list_stores() == []


class TestAuthInstanceCache:
    def test_auth_lock_exists(self):
        """Sanity: the lock is actually a lock object."""
        assert hasattr(_auth_lock, "acquire")

    def test_concurrent_get_auth_instance(self):
        """Regression: pre-audit two concurrent first-callers
        could both construct a new ShopifyAuth; the second
        overwrite silently discarded the first. Now locked."""
        # Clear cache
        _auth_instances.clear()

        instances: list = []
        barrier = threading.Barrier(8)

        # Use a FakeShopifyAuth that counts constructions.
        import sys

        construction_count = [0]

        class FakeAuth:
            def __init__(self, shop_url, client_id, client_secret):
                construction_count[0] += 1
                self.shop_url = shop_url

        # Install a fake ShopifyAuth
        fake_mod = type(sys)("fake_shopify_auth")
        fake_mod.ShopifyAuth = FakeAuth  # type: ignore[attr-defined]
        sys.modules["core.auth.shopify_auth"] = fake_mod

        try:
            def fire():
                barrier.wait()
                instances.append(_get_auth_instance("shop.com", "cid", "csec"))

            threads = [threading.Thread(target=fire) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Exactly ONE FakeAuth construction, all 8 threads
            # got the same instance.
            assert construction_count[0] == 1
            assert len({id(i) for i in instances}) == 1
        finally:
            sys.modules.pop("core.auth.shopify_auth", None)
            _auth_instances.clear()


# ═══════════════════════════════════════════════════════════
# DataProvider defensive
# ═══════════════════════════════════════════════════════════


class TestDataProviderDefensive:
    def test_engine_data_needs_none(self):
        """Regression: ``engine_name.lower()`` crashed on None."""
        assert DataProvider._engine_data_needs(None) == {"products"}

    def test_engine_data_needs_non_string(self):
        assert DataProvider._engine_data_needs(42) == {"products"}

    def test_engine_data_needs_pricing(self):
        assert "products" in DataProvider._engine_data_needs("pricing_engine")

    def test_engine_data_needs_customer(self):
        assert "customers" in DataProvider._engine_data_needs("customer_segmentation")
