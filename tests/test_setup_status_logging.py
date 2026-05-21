"""Tests for ``infrastructure.setup.ShopAISetup.status`` --
silent-fail fix on the StoreManager probe.

Before: when ``StoreManager().list_stores()`` raised (DB
schema mismatch, import error), the status check silently
omitted the ``stores`` key. The dashboard / wizard then showed
""no stores registered"" -- indistinguishable from a fresh
install with no stores yet.

After: a warning log fires AND the status dict gains a
``stores_error`` key so callers can distinguish the two
states.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from infrastructure import setup as _setup_mod  # noqa: F401


_LOGGER = "shopai.setup"


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def setup_log() -> _ListHandler:
    handler = _ListHandler()
    target = logging.getLogger(_LOGGER)
    original = target.level
    target.setLevel(logging.DEBUG)
    target.addHandler(handler)
    try:
        yield handler
    finally:
        target.removeHandler(handler)
        target.setLevel(original)


class TestStatusProbeLogging:

    def test_store_manager_raise_logs_and_marks_error(
        self, setup_log, tmp_path,
    ):
        from infrastructure.setup import ShopAISetup
        instance = ShopAISetup()
        # Stub DB-exists check + force StoreManager to raise.
        with patch("pathlib.Path.exists", return_value=True), \
             patch(
                "data_pipeline.store.store_manager.StoreManager",
                side_effect=RuntimeError("schema mismatch"),
            ):
            result = instance.get_setup_status()
        # Behavior contract: status() still returns; ``stores``
        # stays as the pre-initialised empty list because the
        # probe didn't get to overwrite it.
        assert result["stores"] == []
        # New: error key surfaces so callers can distinguish
        # ""DB broken"" from ""no stores yet"".
        assert result.get("stores_error") == "schema mismatch"
        # Log fired
        msgs = [r.getMessage() for r in setup_log.records]
        assert any(
            "StoreManager probe failed" in m
            and "schema mismatch" in m
            for m in msgs
        )

    def test_store_manager_success_no_log(self, setup_log, tmp_path):
        from infrastructure.setup import ShopAISetup

        class _FakeSM:
            def list_stores(self):
                return [
                    {"store_id": "a", "shop_url": "x.myshopify.com"},
                ]

        with patch("pathlib.Path.exists", return_value=True), \
             patch(
                "data_pipeline.store.store_manager.StoreManager",
                return_value=_FakeSM(),
            ):
            result = ShopAISetup().get_setup_status()
        assert result["stores"] == [
            {"id": "a", "url": "x.myshopify.com"},
        ]
        assert "stores_error" not in result
        warnings = [
            r for r in setup_log.records
            if r.levelno >= logging.WARNING
        ]
        assert warnings == []

    def test_no_db_skips_probe_silently(self, setup_log):
        from infrastructure.setup import ShopAISetup
        with patch("pathlib.Path.exists", return_value=False):
            result = ShopAISetup().get_setup_status()
        # DB doesn't exist -> probe skipped. ``stores`` stays
        # as the pre-initialised empty list; no error key, no
        # log.
        assert result["stores"] == []
        assert "stores_error" not in result
        assert setup_log.records == []
