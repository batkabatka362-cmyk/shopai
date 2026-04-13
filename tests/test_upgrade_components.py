"""Tests for Phase A upgrade: GraphQL, AIWriter, EventCollector."""
import tempfile
import pytest


class TestShopifyGraphQL:
    def test_init(self):
        from data_pipeline.ingestion.api.shopify_graphql import ShopifyGraphQL
        gql = ShopifyGraphQL("test.myshopify.com", "token")
        assert gql is not None
        assert gql._url.endswith("/graphql.json")

    def test_normalize_product(self):
        from data_pipeline.ingestion.api.shopify_graphql import ShopifyGraphQL
        product = ShopifyGraphQL._normalize_product({
            "id": "gid://shopify/Product/123",
            "title": "Test Widget",
            "vendor": "TestVendor",
            "productType": "Electronics",
            "tags": ["sale", "new"],
            "status": "ACTIVE",
            "variants": {"edges": [{"node": {
                "id": "gid://shopify/ProductVariant/456",
                "price": "29.99",
                "inventoryQuantity": 50,
                "inventoryItem": {"unitCost": {"amount": "10.00", "currencyCode": "USD"}},
            }}]},
            "images": {"edges": [{"node": {"url": "https://img.jpg", "altText": "test"}}]},
        })
        assert product["id"] == "123"
        assert product["name"] == "Test Widget"
        assert product["price"] == 29.99
        assert product["cost"] == 10.0
        assert product["inventory_quantity"] == 50
        assert product["image_url"] == "https://img.jpg"

    def test_normalize_order(self):
        from data_pipeline.ingestion.api.shopify_graphql import ShopifyGraphQL
        order = ShopifyGraphQL._normalize_order({
            "id": "gid://shopify/Order/789",
            "name": "#1001",
            "totalPriceSet": {"shopMoney": {"amount": "99.99"}},
            "subtotalPriceSet": {"shopMoney": {"amount": "89.99"}},
            "displayFinancialStatus": "PAID",
            "lineItems": {"edges": [{"node": {"title": "Widget", "quantity": 2}}]},
            "customer": {"id": "gid://shopify/Customer/111", "email": "test@test.com"},
        })
        assert order["id"] == "789"
        assert order["total"] == 99.99
        assert order["items"] == 1

    def test_normalize_customer(self):
        from data_pipeline.ingestion.api.shopify_graphql import ShopifyGraphQL
        customer = ShopifyGraphQL._normalize_customer({
            "id": "gid://shopify/Customer/111",
            "firstName": "John",
            "lastName": "Doe",
            "email": "john@test.com",
            "numberOfOrders": "5",
            "amountSpent": {"amount": "250.00"},
            "tags": ["vip"],
        })
        assert customer["name"] == "John Doe"
        assert customer["orders"] == 5
        assert customer["total_spent"] == 250.0


class TestAIWriter:
    def test_init(self):
        from execution.content.ai_writer import AIWriter
        writer = AIWriter()
        assert writer is not None

    def test_template_description(self):
        from execution.content.ai_writer import AIWriter
        writer = AIWriter()
        result = writer.generate_description({
            "name": "Cool Widget", "price": 29.99, "category": "Electronics",
        })
        assert result["success"]
        assert "Cool Widget" in result["headline"]
        assert result["method"] == "template"
        assert "<p>" in result["body_html"]

    def test_optimize_title_rules(self):
        from execution.content.ai_writer import AIWriter
        writer = AIWriter()
        result = writer.optimize_title(
            "Bedroom Anti-Gravity Humidifier with Clock Water Drop Backflow Aroma Diffuser Large Capacity Office Bedroom Mute Heavy Fog Household Sprayer"
        )
        assert result["success"]
        assert len(result["optimized"]) < len(result["original"])

    def test_generate_ad_copy_template(self):
        from execution.content.ai_writer import AIWriter
        writer = AIWriter()
        result = writer.generate_ad_copy({"name": "Widget Pro", "price": 24.99})
        assert result["success"]
        assert result["headline"]
        assert result["cta"]

    def test_generate_meta_description(self):
        from execution.content.ai_writer import AIWriter
        writer = AIWriter()
        result = writer.generate_meta_description({"name": "Widget", "price": 20, "category": "Home"})
        assert result["success"]
        assert len(result["meta"]) <= 160


class TestEventCollector:
    def _make(self):
        from data_pipeline.tracking.event_collector import EventCollector
        return EventCollector(tempfile.mktemp(suffix=".db"))

    def test_init(self):
        ec = self._make()
        assert ec is not None
        ec.close()

    def test_track_and_flush(self):
        ec = self._make()
        ec.track("store1", "test_event", "product", "p1", {"key": "value"})
        ec.flush()
        events = ec.get_events("store1")
        assert len(events) == 1
        assert events[0]["event_type"] == "test_event"
        ec.close()

    def test_track_order(self):
        ec = self._make()
        ec.track_order("s1", {"id": "o1", "total": 99.99, "items": 2})
        ec.flush()
        events = ec.get_events("s1", "order_created")
        assert len(events) == 1
        ec.close()

    def test_track_price_change(self):
        ec = self._make()
        ec.track_price_change("s1", "p1", 29.99, 24.99, "competition")
        history = ec.get_price_history("s1", "p1")
        assert len(history) == 1
        assert history[0]["old_price"] == 29.99
        assert history[0]["new_price"] == 24.99
        ec.close()

    def test_training_data(self):
        ec = self._make()
        ec.add_training_sample("pricing", {"price": 20, "margin": 0.6}, {"success": True})
        data = ec.get_training_data("pricing")
        assert len(data) == 1
        assert data[0]["features"]["price"] == 20
        ec.close()

    def test_stats(self):
        ec = self._make()
        ec.track("s1", "order_created", "order", "o1")
        ec.track("s1", "price_changed", "product", "p1")
        ec.flush()
        stats = ec.get_stats("s1")
        assert stats["total_events"] == 2
        assert stats["by_type"]["order_created"] == 1
        ec.close()

    def test_singleton(self):
        from data_pipeline.tracking.event_collector import get_event_collector
        e1 = get_event_collector()
        e2 = get_event_collector()
        assert e1 is e2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
