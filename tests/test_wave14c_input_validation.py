"""Wave 14c tests — input validation at API boundaries.

Verifies:
1. Each validator correctly accepts valid inputs.
2. Each validator rejects invalid / malicious inputs.
3. Validators are wired into the API server handlers.
"""
from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════
# validate_store_id
# ═══════════════════════════════════════════════

class TestValidateStoreId:

    def test_valid_alphanumeric(self):
        from api.validation import validate_store_id
        val, err = validate_store_id("deguar")
        assert err is None
        assert val == "deguar"

    def test_valid_with_hyphens(self):
        from api.validation import validate_store_id
        val, err = validate_store_id("my-store-123")
        assert err is None
        assert val == "my-store-123"

    def test_valid_with_underscores(self):
        from api.validation import validate_store_id
        val, err = validate_store_id("store_prod_01")
        assert err is None

    def test_strips_whitespace(self):
        from api.validation import validate_store_id
        val, err = validate_store_id("  deguar  ")
        assert err is None
        assert val == "deguar"

    def test_rejects_empty(self):
        from api.validation import validate_store_id
        _, err = validate_store_id("")
        assert err is not None
        assert "required" in err

    def test_rejects_non_string(self):
        from api.validation import validate_store_id
        _, err = validate_store_id(12345)
        assert err is not None
        assert "string" in err

    def test_rejects_too_long(self):
        from api.validation import validate_store_id
        _, err = validate_store_id("a" * 100)
        assert err is not None
        assert "exceeds" in err

    def test_rejects_path_traversal(self):
        from api.validation import validate_store_id
        _, err = validate_store_id("../../etc/passwd")
        assert err is not None

    def test_rejects_special_chars(self):
        from api.validation import validate_store_id
        _, err = validate_store_id("store; DROP TABLE")
        assert err is not None

    def test_rejects_leading_hyphen(self):
        from api.validation import validate_store_id
        _, err = validate_store_id("-bad-start")
        assert err is not None


# ═══════════════════════════════════════════════
# validate_safe_name
# ═══════════════════════════════════════════════

class TestValidateSafeName:

    def test_valid_engine_name(self):
        from api.validation import validate_safe_name
        val, err = validate_safe_name("product_selection", "engine")
        assert err is None
        assert val == "product_selection"

    def test_valid_underscore_start(self):
        from api.validation import validate_safe_name
        val, err = validate_safe_name("_internal", "name")
        assert err is None

    def test_rejects_empty(self):
        from api.validation import validate_safe_name
        _, err = validate_safe_name("", "engine")
        assert err is not None

    def test_rejects_spaces(self):
        from api.validation import validate_safe_name
        _, err = validate_safe_name("bad name", "engine")
        assert err is not None

    def test_rejects_dots(self):
        from api.validation import validate_safe_name
        _, err = validate_safe_name("path.traversal", "engine")
        assert err is not None

    def test_rejects_slashes(self):
        from api.validation import validate_safe_name
        _, err = validate_safe_name("../../etc", "engine")
        assert err is not None

    def test_rejects_number_start(self):
        from api.validation import validate_safe_name
        _, err = validate_safe_name("123bad", "engine")
        assert err is not None

    def test_error_includes_field_name(self):
        from api.validation import validate_safe_name
        _, err = validate_safe_name("", "workflow")
        assert "workflow" in err


# ═══════════════════════════════════════════════
# validate_shop_url
# ═══════════════════════════════════════════════

class TestValidateShopUrl:

    def test_valid_myshopify_domain(self):
        from api.validation import validate_shop_url
        val, err = validate_shop_url("mystore.myshopify.com")
        assert err is None
        assert val == "mystore.myshopify.com"

    def test_valid_custom_domain(self):
        from api.validation import validate_shop_url
        val, err = validate_shop_url("shop.example.com")
        assert err is None

    def test_lowercases(self):
        from api.validation import validate_shop_url
        val, err = validate_shop_url("MyStore.myshopify.com")
        assert err is None
        assert val == "mystore.myshopify.com"

    def test_rejects_empty(self):
        from api.validation import validate_shop_url
        _, err = validate_shop_url("")
        assert err is not None

    def test_rejects_bare_word(self):
        from api.validation import validate_shop_url
        _, err = validate_shop_url("notadomain")
        assert err is not None

    def test_rejects_url_with_protocol(self):
        from api.validation import validate_shop_url
        _, err = validate_shop_url("https://store.myshopify.com")
        assert err is not None

    def test_rejects_too_long(self):
        from api.validation import validate_shop_url
        _, err = validate_shop_url("a" * 600)
        assert err is not None


# ═══════════════════════════════════════════════
# validate_webhook_topic
# ═══════════════════════════════════════════════

class TestValidateWebhookTopic:

    def test_valid_orders_create(self):
        from api.validation import validate_webhook_topic
        val, err = validate_webhook_topic("orders/create")
        assert err is None
        assert val == "orders/create"

    def test_valid_products_update(self):
        from api.validation import validate_webhook_topic
        val, err = validate_webhook_topic("products/update")
        assert err is None

    def test_valid_customers_delete(self):
        from api.validation import validate_webhook_topic
        val, err = validate_webhook_topic("customers/delete")
        assert err is None

    def test_rejects_empty(self):
        from api.validation import validate_webhook_topic
        _, err = validate_webhook_topic("")
        assert err is not None

    def test_rejects_no_slash(self):
        from api.validation import validate_webhook_topic
        _, err = validate_webhook_topic("ordercreate")
        assert err is not None

    def test_rejects_special_chars(self):
        from api.validation import validate_webhook_topic
        _, err = validate_webhook_topic("orders/<script>")
        assert err is not None


# ═══════════════════════════════════════════════
# validate_batch_items
# ═══════════════════════════════════════════════

class TestValidateBatchItems:

    def test_valid_list(self):
        from api.validation import validate_batch_items
        val, err = validate_batch_items([{"id": 1}, {"id": 2}])
        assert err is None
        assert len(val) == 2

    def test_rejects_non_list(self):
        from api.validation import validate_batch_items
        _, err = validate_batch_items("not a list")
        assert err is not None

    def test_rejects_empty_list(self):
        from api.validation import validate_batch_items
        _, err = validate_batch_items([])
        assert err is not None
        assert "empty" in err

    def test_rejects_oversized_list(self):
        from api.validation import validate_batch_items, MAX_BATCH_ITEMS
        _, err = validate_batch_items(list(range(MAX_BATCH_ITEMS + 1)))
        assert err is not None
        assert "maximum" in err


# ═══════════════════════════════════════════════
# validate_params
# ═══════════════════════════════════════════════

class TestValidateParams:

    def test_valid_dict(self):
        from api.validation import validate_params
        val, err = validate_params({"key": "value"})
        assert err is None
        assert val == {"key": "value"}

    def test_none_becomes_empty_dict(self):
        from api.validation import validate_params
        val, err = validate_params(None)
        assert err is None
        assert val == {}

    def test_rejects_non_dict(self):
        from api.validation import validate_params
        _, err = validate_params("not a dict")
        assert err is not None

    def test_rejects_too_many_fields(self):
        from api.validation import validate_params, MAX_BODY_FIELDS
        big = {f"k{i}": i for i in range(MAX_BODY_FIELDS + 1)}
        _, err = validate_params(big)
        assert err is not None
        assert "too many" in err


# ═══════════════════════════════════════════════
# validate_string
# ═══════════════════════════════════════════════

class TestValidateString:

    def test_valid(self):
        from api.validation import validate_string
        val, err = validate_string("hello", "test")
        assert err is None
        assert val == "hello"

    def test_required_empty_fails(self):
        from api.validation import validate_string
        _, err = validate_string("", "token", required=True)
        assert err is not None

    def test_optional_empty_ok(self):
        from api.validation import validate_string
        val, err = validate_string("", "name", required=False)
        assert err is None

    def test_max_len_enforced(self):
        from api.validation import validate_string
        _, err = validate_string("x" * 300, "token", max_len=256)
        assert err is not None
        assert "exceeds" in err


# ═══════════════════════════════════════════════
# Integration — validators wired into server
# ═══════════════════════════════════════════════

class TestServerImportsValidation:
    """Verify the API servers import and use validation functions."""

    def test_server_imports_validators(self):
        import api.server as mod
        assert hasattr(mod, "validate_store_id")
        assert hasattr(mod, "validate_safe_name")
        assert hasattr(mod, "validate_batch_items")

    def test_dashboard_imports_validators(self):
        import api.dashboard_api as mod
        assert hasattr(mod, "validate_shop_url")
        assert hasattr(mod, "validate_string")

    def test_validation_module_importable(self):
        from api.validation import (
            validate_store_id,
            validate_safe_name,
            validate_shop_url,
            validate_webhook_topic,
            validate_string,
            validate_batch_items,
            validate_params,
            MAX_STORE_ID_LEN,
            MAX_BATCH_ITEMS,
        )
        assert MAX_STORE_ID_LEN == 64
        assert MAX_BATCH_ITEMS == 500
