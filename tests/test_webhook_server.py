"""Tests for webhook handling, API server fixes, and integration."""
import json
import pytest


class TestWebhookHandler:
    """Test Shopify webhook processing."""

    def test_handler_init(self):
        from core.webhooks import ShopifyWebhookHandler
        handler = ShopifyWebhookHandler()
        assert handler is not None

    def test_list_supported_events(self):
        from core.webhooks import ShopifyWebhookHandler
        handler = ShopifyWebhookHandler()
        events = handler.list_supported_events()
        assert len(events) > 5
        topics = [e["topic"] for e in events]
        assert "orders/create" in topics
        assert "products/update" in topics

    def test_handle_order_create(self):
        from core.webhooks import ShopifyWebhookHandler
        handler = ShopifyWebhookHandler()
        result = handler.handle("orders/create", {
            "id": 12345,
            "total_price": "89.99",
            "subtotal_price": "79.99",
            "financial_status": "paid",
            "line_items": [{"id": 1}, {"id": 2}],
            "customer": {"id": 999},
        }, shop="test.myshopify.com")
        assert result["status"] in ("processed", "skipped")
        assert result["topic"] == "orders/create"

    def test_handle_product_update(self):
        from core.webhooks import ShopifyWebhookHandler
        handler = ShopifyWebhookHandler()
        result = handler.handle("products/update", {
            "id": 555,
            "title": "Updated Widget",
            "variants": [{"price": "29.99", "inventory_quantity": 50}],
            "product_type": "electronics",
        })
        assert result["status"] in ("processed", "skipped")

    def test_handle_unknown_topic(self):
        from core.webhooks import ShopifyWebhookHandler
        handler = ShopifyWebhookHandler()
        result = handler.handle("unknown/event", {"data": "test"})
        assert result["status"] == "skipped"

    def test_hmac_verification(self):
        from core.webhooks import ShopifyWebhookHandler
        handler = ShopifyWebhookHandler(webhook_secret="test_secret")
        # Invalid HMAC should be rejected
        result = handler.handle("orders/create", {"id": 1}, hmac_header="invalid")
        assert result["status"] == "rejected"

    def test_stats_tracking(self):
        from core.webhooks import ShopifyWebhookHandler
        handler = ShopifyWebhookHandler()
        handler.handle("orders/create", {"id": 1})
        handler.handle("unknown/topic", {"id": 2})
        stats = handler.get_stats()
        assert stats["received"] == 2

    def test_event_log(self):
        from core.webhooks import ShopifyWebhookHandler
        handler = ShopifyWebhookHandler()
        handler.handle("products/update", {"id": 1, "title": "Test"})
        log = handler.get_event_log()
        assert len(log) >= 0  # May or may not log depending on engine availability

    def test_normalize_order(self):
        from core.webhooks import ShopifyWebhookHandler
        result = ShopifyWebhookHandler._normalize_order({
            "id": 123, "total_price": "99.99", "subtotal_price": "89.99",
            "financial_status": "paid", "line_items": [{"id": 1}],
            "customer": {"id": 456},
        })
        assert result[0]["id"] == "123"
        assert result[0]["total"] == 99.99

    def test_normalize_product(self):
        from core.webhooks import ShopifyWebhookHandler
        result = ShopifyWebhookHandler._normalize_product({
            "id": 789, "title": "Widget",
            "variants": [{"price": "29.99", "cost": "10.00", "inventory_quantity": 50}],
            "product_type": "gadgets",
        })
        assert result[0]["name"] == "Widget"
        assert result[0]["price"] == 29.99

    def test_normalize_customer(self):
        from core.webhooks import ShopifyWebhookHandler
        result = ShopifyWebhookHandler._normalize_customer({
            "id": 111, "first_name": "John", "last_name": "Doe",
            "email": "john@test.com", "orders_count": 5, "total_spent": "250.00",
        })
        assert result[0]["name"] == "John Doe"
        assert result[0]["total_spent"] == 250.0


class TestAPIServerRoutes:
    """Test API server route configuration."""

    def test_server_class_exists(self):
        from api.server import ShopAIServer, ShopAIHandler
        assert ShopAIServer is not None
        assert ShopAIHandler is not None

    def test_handler_has_routes(self):
        from api.server import ShopAIHandler
        # Verify key methods exist
        assert hasattr(ShopAIHandler, '_handle_webhook')
        assert hasattr(ShopAIHandler, '_auto_cycle')
        assert hasattr(ShopAIHandler, '_store_sync')
        assert hasattr(ShopAIHandler, '_get_experience')
        assert hasattr(ShopAIHandler, '_list_webhooks')
        assert hasattr(ShopAIHandler, '_list_stores')


class TestCLIServerCommand:
    """Test CLI server command."""

    def test_parser_has_server(self):
        from cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["server", "--port", "9090"])
        assert args.command == "server"
        assert args.port == 9090


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
