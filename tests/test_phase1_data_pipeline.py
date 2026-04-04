"""Tests for Phase 1: Real Data Pipeline components.

Tests: ShopAIDatabase, StoreManager, DataProvider, SyncService, ShopifyAdapter.
"""
import json
import os
import tempfile
import time
import pytest


# ── ShopAIDatabase Tests ─────────────────────────────────────

class TestShopAIDatabase:
    """Test SQLite database operations."""

    def _make_db(self):
        from data_pipeline.store.db import ShopAIDatabase
        tmp = tempfile.mktemp(suffix=".db")
        return ShopAIDatabase(tmp), tmp

    def test_init_creates_schema(self):
        db, path = self._make_db()
        assert os.path.exists(path)
        db.close()

    def test_add_and_get_store(self):
        db, _ = self._make_db()
        result = db.add_store("test-store", "test.myshopify.com", name="Test Store", niche="electronics")
        assert result["store_id"] == "test-store"
        store = db.get_store("test-store")
        assert store is not None
        assert store["shop_url"] == "test.myshopify.com"
        db.close()

    def test_list_stores(self):
        db, _ = self._make_db()
        db.add_store("store-1", "s1.myshopify.com")
        db.add_store("store-2", "s2.myshopify.com")
        stores = db.list_stores()
        assert len(stores) == 2
        db.close()

    def test_upsert_and_get_products(self):
        db, _ = self._make_db()
        db.add_store("s1", "s1.myshopify.com")
        products = [
            {"id": "p1", "title": "Widget A", "price": 29.99, "cost": 10, "status": "active"},
            {"id": "p2", "title": "Widget B", "price": 49.99, "cost": 20, "status": "active"},
        ]
        count = db.upsert_products("s1", products)
        assert count == 2
        fetched = db.get_products("s1")
        assert len(fetched) == 2
        assert fetched[0]["name"] in ("Widget A", "Widget B")
        db.close()

    def test_upsert_and_get_orders(self):
        db, _ = self._make_db()
        db.add_store("s1", "s1.myshopify.com")
        orders = [
            {"id": "o1", "total": 89.99, "financial_status": "paid", "item_count": 2},
            {"id": "o2", "total": 45.00, "financial_status": "refunded", "item_count": 1},
        ]
        count = db.upsert_orders("s1", orders)
        assert count == 2
        fetched = db.get_all_orders("s1")
        assert len(fetched) == 2
        db.close()

    def test_upsert_and_get_customers(self):
        db, _ = self._make_db()
        db.add_store("s1", "s1.myshopify.com")
        customers = [
            {"id": "c1", "name": "Alice", "email": "alice@test.com", "orders_count": 5, "total_spent": 300},
        ]
        count = db.upsert_customers("s1", customers)
        assert count == 1
        fetched = db.get_customers("s1")
        assert len(fetched) == 1
        assert fetched[0]["name"] == "Alice"
        db.close()

    def test_store_stats(self):
        db, _ = self._make_db()
        db.add_store("s1", "s1.myshopify.com")
        db.upsert_products("s1", [{"id": "p1", "title": "X", "price": 10}])
        db.upsert_orders("s1", [{"id": "o1", "total": 99.99}])
        db.upsert_customers("s1", [{"id": "c1", "name": "Bob"}])
        stats = db.get_store_stats("s1")
        assert stats["products"] == 1
        assert stats["orders"] == 1
        assert stats["customers"] == 1
        assert stats["total_revenue"] == 99.99
        db.close()

    def test_sync_log(self):
        db, _ = self._make_db()
        db.add_store("s1", "s1.myshopify.com")
        db.log_sync("s1", "products", "success", records=10, duration_s=1.5)
        history = db.get_sync_history("s1")
        assert len(history) == 1
        assert history[0]["sync_type"] == "products"
        last = db.get_last_sync("s1", "products")
        assert last is not None
        assert last["records"] == 10
        db.close()

    def test_analytics_snapshots(self):
        db, _ = self._make_db()
        db.add_store("s1", "s1.myshopify.com")
        db.save_snapshot("s1", "daily", {"revenue": 1000, "orders": 15})
        snapshots = db.get_snapshots("s1", "daily")
        assert len(snapshots) == 1
        assert snapshots[0]["data"]["revenue"] == 1000
        db.close()

    def test_product_upsert_updates_existing(self):
        db, _ = self._make_db()
        db.add_store("s1", "s1.myshopify.com")
        db.upsert_products("s1", [{"id": "p1", "title": "Old Name", "price": 10}])
        db.upsert_products("s1", [{"id": "p1", "title": "New Name", "price": 20}])
        products = db.get_products("s1")
        assert len(products) == 1
        assert products[0]["name"] == "New Name"
        assert products[0]["price"] == 20
        db.close()


# ── StoreManager Tests ───────────────────────────────────────

class TestStoreManager:
    """Test multi-store management."""

    def _make_sm(self):
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        tmp = tempfile.mktemp(suffix=".db")
        db = ShopAIDatabase(tmp)
        return StoreManager(db)

    def test_add_store(self):
        sm = self._make_sm()
        result = sm.add_store("store1", "s1.myshopify.com", "shpat_xxx", name="Store 1")
        assert result["store_id"] == "store1"
        assert sm.active_store_id == "store1"

    def test_multiple_stores(self):
        sm = self._make_sm()
        sm.add_store("store1", "s1.myshopify.com", "key1")
        sm.add_store("store2", "s2.myshopify.com", "key2")
        stores = sm.list_stores()
        assert len(stores) == 2

    def test_switch_active_store(self):
        sm = self._make_sm()
        sm.add_store("store1", "s1.myshopify.com", "key1")
        sm.add_store("store2", "s2.myshopify.com", "key2")
        sm.set_active_store("store2")
        assert sm.active_store_id == "store2"

    def test_get_credentials(self):
        sm = self._make_sm()
        sm.add_store("store1", "s1.myshopify.com", "shpat_test123")
        creds = sm.get_credentials("store1")
        assert creds["shop_url"] == "s1.myshopify.com"
        assert creds["api_key"] == "shpat_test123"

    def test_remove_store(self):
        sm = self._make_sm()
        sm.add_store("store1", "s1.myshopify.com", "key1")
        result = sm.remove_store("store1")
        assert result["status"] == "removed"
        stores = sm.list_stores()
        assert len(stores) == 0

    def test_get_stats(self):
        sm = self._make_sm()
        sm.add_store("store1", "s1.myshopify.com", "key1")
        stats = sm.get_stats("store1")
        assert stats["store_id"] == "store1"
        assert stats["products"] == 0


# ── DataProvider Tests ───────────────────────────────────────

class TestDataProvider:
    """Test unified data provider for engines."""

    def _make_provider(self):
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        from data_pipeline.store.data_provider import DataProvider
        tmp = tempfile.mktemp(suffix=".db")
        db = ShopAIDatabase(tmp)
        sm = StoreManager(db)
        sm.add_store("test", "test.myshopify.com", "key")
        # Add some test data
        db.upsert_products("test", [
            {"id": "p1", "title": "Test Product", "price": 29.99, "status": "active"},
        ])
        db.upsert_orders("test", [
            {"id": "o1", "total": 59.99, "financial_status": "paid"},
        ])
        db.upsert_customers("test", [
            {"id": "c1", "name": "Test Customer", "email": "test@example.com"},
        ])
        # Log sync so data isn't considered stale
        db.log_sync("test", "products", "success", 1, 0.1)
        db.log_sync("test", "orders", "success", 1, 0.1)
        db.log_sync("test", "customers", "success", 1, 0.1)
        return DataProvider(sm)

    def test_get_products(self):
        dp = self._make_provider()
        products = dp.get_products()
        assert len(products) >= 1
        assert products[0]["name"] == "Test Product"

    def test_get_orders(self):
        dp = self._make_provider()
        orders = dp.get_orders()
        assert len(orders) >= 1

    def test_get_customers(self):
        dp = self._make_provider()
        customers = dp.get_customers()
        assert len(customers) >= 1

    def test_get_data_for_product_engine(self):
        dp = self._make_provider()
        data = dp.get_data_for_engine("pricing")
        assert "products" in data
        assert data["source"] == "database"

    def test_get_data_for_customer_engine(self):
        dp = self._make_provider()
        data = dp.get_data_for_engine("customer_segmentation")
        assert "customer_data" in data

    def test_get_data_for_order_engine(self):
        dp = self._make_provider()
        data = dp.get_data_for_engine("analytics")
        assert "order_data" in data

    def test_fallback_to_mock_when_no_store(self):
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        from data_pipeline.store.data_provider import DataProvider
        tmp = tempfile.mktemp(suffix=".db")
        db = ShopAIDatabase(tmp)
        sm = StoreManager(db)
        dp = DataProvider(sm)
        data = dp.get_data_for_engine("pricing")
        assert data["source"] == "mock"
        assert len(data["products"]) > 0

    def test_engine_data_needs_mapping(self):
        from data_pipeline.store.data_provider import DataProvider
        needs = DataProvider._engine_data_needs("pricing_optimizer")
        assert "products" in needs
        needs = DataProvider._engine_data_needs("customer_segmentation")
        assert "customers" in needs
        needs = DataProvider._engine_data_needs("revenue_forecasting")
        assert "orders" in needs


# ── SyncService Tests ────────────────────────────────────────

class TestSyncService:
    """Test data sync service."""

    def _make_sync(self):
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        from data_pipeline.store.sync_service import SyncService
        tmp = tempfile.mktemp(suffix=".db")
        db = ShopAIDatabase(tmp)
        sm = StoreManager(db)
        sm.add_store("test", "test.myshopify.com", "shpat_test")
        return SyncService(sm)

    def test_sync_service_init(self):
        sync = self._make_sync()
        assert sync is not None

    def test_get_status(self):
        sync = self._make_sync()
        status = sync.get_status()
        assert "auto_sync_running" in status
        assert status["auto_sync_running"] is False
        assert len(status["stores"]) == 1

    def test_normalize_products(self):
        from data_pipeline.store.sync_service import SyncService
        raw = [{"id": 123, "title": "Test", "variants": [{"price": "29.99", "inventory_quantity": 5}],
                "vendor": "V", "product_type": "widget", "tags": "sale, new", "status": "active"}]
        normalized = SyncService._normalize_products(raw)
        assert len(normalized) == 1
        assert normalized[0]["title"] == "Test"
        assert normalized[0]["price"] == 29.99
        assert "sale" in normalized[0]["tags"]

    def test_normalize_orders(self):
        from data_pipeline.store.sync_service import SyncService
        raw = [{"id": 456, "total_price": "99.99", "subtotal_price": "89.99",
                "financial_status": "paid", "fulfillment_status": "fulfilled",
                "line_items": [{"id": 1}, {"id": 2}], "customer": {"id": 789}}]
        normalized = SyncService._normalize_orders(raw)
        assert len(normalized) == 1
        assert normalized[0]["total"] == 99.99
        assert normalized[0]["item_count"] == 2

    def test_normalize_customers(self):
        from data_pipeline.store.sync_service import SyncService
        raw = [{"id": 789, "first_name": "John", "last_name": "Doe",
                "email": "john@test.com", "orders_count": 3, "total_spent": "150.00",
                "tags": "vip, repeat"}]
        normalized = SyncService._normalize_customers(raw)
        assert len(normalized) == 1
        assert normalized[0]["name"] == "John Doe"
        assert normalized[0]["total_spent"] == 150.0


# ── ShopifyAdapter Tests ─────────────────────────────────────

class TestShopifyAdapter:
    """Test Shopify tool adapter."""

    def test_adapter_init(self):
        from tools.adapters.shopify import ShopifyAdapter
        adapter = ShopifyAdapter()
        assert adapter.tool_name == "shopify"
        assert adapter.version == "2.0.0"

    def test_capabilities(self):
        from tools.adapters.shopify import ShopifyAdapter
        adapter = ShopifyAdapter()
        caps = adapter.capabilities()
        assert "fetch_products" in caps
        assert "update_price" in caps
        assert len(caps) == 9

    def test_health_check_unconfigured(self):
        from tools.adapters.shopify import ShopifyAdapter
        adapter = ShopifyAdapter()
        health = adapter.health_check()
        assert health.healthy is False

    def test_execute_unknown_action(self):
        from tools.adapters.shopify import ShopifyAdapter
        adapter = ShopifyAdapter()
        result = adapter.execute("nonexistent", {})
        assert result.success is False
        assert "Unknown action" in result.error

    def test_fetch_products_no_connection(self):
        from tools.adapters.shopify import ShopifyAdapter
        adapter = ShopifyAdapter()
        adapter._shop_domain = "test.myshopify.com"
        result = adapter.execute("fetch_products", {})
        assert result.success is True
        # Should return empty or cached data
        assert "products" in result.data or "total" in result.data

    def test_rate_config(self):
        from tools.adapters.shopify import ShopifyAdapter
        adapter = ShopifyAdapter()
        config = adapter.get_rate_config()
        assert config.requests_per_second == 2.0

    def test_create_product_requires_title(self):
        from tools.adapters.shopify import ShopifyAdapter
        adapter = ShopifyAdapter()
        result = adapter.execute("create_product", {})
        assert result.success is False
        assert "title" in result.error.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
