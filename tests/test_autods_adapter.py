"""Tests for AutoDSAdapter -- W963-102."""
from __future__ import annotations

from unittest.mock import patch

from core.adapters.base import Capability
from core.adapters.errors import (
    AdapterNotConfigured,
    AdapterValidationError,
)
from core.adapters.sourcing.autods import AutoDSAdapter


# ── Configuration ─────────────────────────────────────────


class TestAutoDSConfiguration:
    def test_is_configured_returns_false_without_token(self):
        with patch(
            "core.adapters.sourcing._base.get_config"
        ) as mock_cfg:
            mock_cfg.return_value.get.return_value = ""
            adapter = AutoDSAdapter()
            assert adapter.is_configured() is False

    def test_is_configured_returns_true_with_token(self):
        with patch(
            "core.adapters.sourcing._base.get_config"
        ) as mock_cfg:
            mock_cfg.return_value.get.return_value = "AT-token-123"
            adapter = AutoDSAdapter()
            assert adapter.is_configured() is True

    def test_config_alias_is_autods(self):
        adapter = AutoDSAdapter()
        assert adapter.config_alias == "autods"


# ── Metadata ───────────────────────────────────────────────


class TestAutoDSMetadata:
    def test_name(self):
        assert AutoDSAdapter.name == "autods"

    def test_capabilities_cover_full_sourcing_lifecycle(self):
        caps = AutoDSAdapter.capabilities
        assert Capability.SOURCING_SEARCH_PRODUCTS in caps
        assert Capability.SOURCING_GET_PRODUCT in caps
        assert Capability.SOURCING_CREATE_ORDER in caps
        assert Capability.SOURCING_GET_ORDER_STATUS in caps

    def test_priority_below_cj_dropshipping(self):
        """CJ is the free / default sourcing adapter; AutoDS
        slots below CJ in router preference so CJ wins ties
        on identical capability declarations."""
        from core.adapters.sourcing.cj_dropshipping import (
            CJDropshippingAdapter,
        )
        assert (
            AutoDSAdapter.priority
            < CJDropshippingAdapter.priority
        )

    def test_requires_key(self):
        assert AutoDSAdapter.requires_key is True


# ── Dispatch ───────────────────────────────────────────────


class TestAutoDSDispatch:
    """W963-102: skeleton adapter returns honest 'not yet
    wired' failures so the router's fallback chain naturally
    tries the next sourcing adapter (typically CJ). Input
    validation still runs (catches bad params before falling
    back)."""

    def _adapter_with_token(self) -> AutoDSAdapter:
        # Patch _base.get_config so is_configured + _api_key
        # both return a valid token without touching env vars.
        patcher = patch(
            "core.adapters.sourcing._base.get_config"
        )
        mock_cfg = patcher.start()
        mock_cfg.return_value.get.return_value = "AT-test-token"
        self._patcher = patcher
        return AutoDSAdapter()

    def teardown_method(self, method):
        try:
            self._patcher.stop()
        except Exception:
            pass

    def test_search_validates_query(self):
        adapter = self._adapter_with_token()
        try:
            adapter._do_search_products(
                Capability.SOURCING_SEARCH_PRODUCTS,
                {},  # missing query
            )
            raise AssertionError("expected validation error")
        except AdapterValidationError as exc:
            assert "query" in str(exc).lower()

    def test_search_with_valid_params_returns_not_wired(self):
        adapter = self._adapter_with_token()
        result = adapter._do_search_products(
            Capability.SOURCING_SEARCH_PRODUCTS,
            {"query": "wireless earbuds", "limit": 10},
        )
        assert result.ok is False
        assert "not yet wired" in str(result.error).lower()

    def test_get_product_validates_id(self):
        adapter = self._adapter_with_token()
        try:
            adapter._do_get_product(
                Capability.SOURCING_GET_PRODUCT,
                {},  # missing sourcing_id
            )
            raise AssertionError("expected validation error")
        except AdapterValidationError as exc:
            assert (
                "sourcing_id" in str(exc).lower()
                or "product_id" in str(exc).lower()
            )

    def test_create_order_validates_items(self):
        adapter = self._adapter_with_token()
        try:
            adapter._do_create_order(
                Capability.SOURCING_CREATE_ORDER,
                {"items": [], "shipping": {}},
            )
            raise AssertionError("expected validation error")
        except AdapterValidationError as exc:
            assert "items" in str(exc).lower()

    def test_create_order_validates_shipping(self):
        adapter = self._adapter_with_token()
        try:
            adapter._do_create_order(
                Capability.SOURCING_CREATE_ORDER,
                {
                    "items": [{
                        "variant_id": "v1",
                        "quantity": 1,
                    }],
                    "shipping": {},  # missing required fields
                },
            )
            raise AssertionError("expected validation error")
        except AdapterValidationError as exc:
            assert "shipping" in str(exc).lower()

    def test_get_order_status_validates_order_id(self):
        adapter = self._adapter_with_token()
        try:
            adapter._do_get_order_status(
                Capability.SOURCING_GET_ORDER_STATUS,
                {},  # missing order_id
            )
            raise AssertionError("expected validation error")
        except AdapterValidationError as exc:
            assert "order_id" in str(exc).lower()

    def test_handler_without_token_raises_not_configured(self):
        """When no token is set, the not-yet-wired path
        STILL surfaces the missing-config error first."""
        with patch(
            "core.adapters.sourcing._base.get_config"
        ) as mock_cfg:
            mock_cfg.return_value.get.return_value = ""
            mock_cfg.return_value.env_var_for.return_value = (
                "AUTODS_API_TOKEN"
            )
            adapter = AutoDSAdapter()
            try:
                adapter._do_search_products(
                    Capability.SOURCING_SEARCH_PRODUCTS,
                    {"query": "x", "limit": 5},
                )
                raise AssertionError(
                    "expected AdapterNotConfigured"
                )
            except AdapterNotConfigured as exc:
                assert "AUTODS_API_TOKEN" in str(exc)


# ── Bootstrap registration ─────────────────────────────────


class TestAutoDSBootstrap:
    def test_register_all_includes_autods(self):
        from core.adapters.sourcing.bootstrap import (
            _SOURCING_ADAPTER_CLASSES,
        )
        names = [cls.name for cls in _SOURCING_ADAPTER_CLASSES]
        assert "autods" in names
        assert "cj_dropshipping" in names
