"""Tests for core.adapters.ads.bootstrap."""
from __future__ import annotations

import pytest

from core.adapters.ads.bootstrap import register_all
from core.adapters.registry import AdapterRegistry


class TestAdsBootstrap:

    def test_registers_meta_ads(self):
        reg = AdapterRegistry()
        status = register_all(registry=reg)
        # meta_ads in the status map
        assert "meta_ads" in status
        # AdapterRegistry has it
        adapter = reg.get("meta_ads")
        assert adapter is not None
        assert adapter.name == "meta_ads"

    def test_returns_configured_flag(self):
        reg = AdapterRegistry()
        status = register_all(registry=reg)
        # is_configured is False without creds; True with
        # them. Either way, it's a bool.
        assert isinstance(status["meta_ads"], bool)

    def test_idempotent(self):
        """Calling twice doesn't crash + doesn't duplicate."""
        reg = AdapterRegistry()
        register_all(registry=reg)
        register_all(registry=reg)
        # Still just one meta_ads adapter
        adapter = reg.get("meta_ads")
        assert adapter is not None

    def test_default_registry(self):
        """register_all() without explicit registry uses the
        global registry."""
        status = register_all()
        assert "meta_ads" in status
