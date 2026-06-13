"""W963-142: per-store creds coverage tests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engines.per_store_creds import (
    PerStoreCredsEngine,
    discover_coverage,
)
from engines.per_store_creds.coverage import _scan_envvar


class TestScanEnvvar:
    def test_per_store_openai_key_parses(self):
        result = _scan_envvar(
            "SHOPAI_STORE_STORE_A_OPENAI_API_KEY",
        )
        assert result == ("STORE_A", "OPENAI_API_KEY")

    def test_per_store_meta_account_id_parses(self):
        result = _scan_envvar(
            "SHOPAI_STORE_STORE_A_META_ADS_ACCOUNT_ID",
        )
        assert result == (
            "STORE_A", "META_ADS_ACCOUNT_ID",
        )

    def test_non_per_store_var_rejected(self):
        assert _scan_envvar("OPENAI_API_KEY") is None

    def test_unknown_suffix_rejected(self):
        assert _scan_envvar(
            "SHOPAI_STORE_STORE_A_NOT_A_KNOWN_THING",
        ) is None

    def test_multi_word_sid_parses(self):
        """A store_id with multiple underscores should
        still match. Pre-fix the splitter using
        .split() / fixed indices would lose them."""
        result = _scan_envvar(
            "SHOPAI_STORE_MY_BIG_SHOP_OPENAI_API_KEY",
        )
        # We can't perfectly recover 'my_big_shop' vs
        # 'my' + 'big_shop_openai' etc. -- but we MUST
        # extract the canonical suffix correctly.
        assert result is not None
        assert result[1] == "OPENAI_API_KEY"


class TestDiscoverCoverage:
    def test_finds_per_store_overrides(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_API_KEY",
            "tok",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_KLAVIYO_API_KEY",
            "tok",
        )
        # Stub StoreManager to return no extras
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = [
                {"store_id": "store_a"},
            ]
            cov = discover_coverage()
        store_a = next(
            c for c in cov if c.store_id == "store_a"
        )
        assert store_a.override_count == 2
        assert "OPENAI_API_KEY" in store_a.overrides
        assert "KLAVIYO_API_KEY" in store_a.overrides

    def test_unregistered_stores_with_overrides_shown(
        self, monkeypatch,
    ):
        """Operator may set an env override for a store
        not yet in the DB. Discovery surfaces it
        anyway."""
        monkeypatch.setenv(
            "SHOPAI_STORE_FUTURE_STORE_OPENAI_API_KEY",
            "x",
        )
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = []
            cov = discover_coverage()
        sids = {c.store_id for c in cov}
        assert "future_store" in sids

    def test_registered_store_without_overrides(
        self, monkeypatch,
    ):
        """Stores registered in StoreManager but without
        any per-store env override are still included."""
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = [
                {"store_id": "store_x"},
            ]
            cov = discover_coverage()
        store_x = next(
            c for c in cov if c.store_id == "store_x"
        )
        assert store_x.override_count == 0

    def test_only_store_filter(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_API_KEY", "x",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_B_OPENAI_API_KEY", "x",
        )
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = []
            cov = discover_coverage(only_store="store_a")
        assert len(cov) == 1
        assert cov[0].store_id == "store_a"

    def test_sort_descending_override_count(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_STORE_HEAVY_OPENAI_API_KEY", "x",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_HEAVY_KLAVIYO_API_KEY", "x",
        )
        monkeypatch.setenv(
            "SHOPAI_STORE_LIGHT_OPENAI_API_KEY", "x",
        )
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = []
            cov = discover_coverage()
        # heavy (2 overrides) before light (1)
        idx_heavy = next(
            i for i, c in enumerate(cov)
            if c.store_id == "heavy"
        )
        idx_light = next(
            i for i, c in enumerate(cov)
            if c.store_id == "light"
        )
        assert idx_heavy < idx_light


class TestEnvelope:
    def test_empty_success(self, monkeypatch):
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = []
            r = PerStoreCredsEngine().run({})
        assert r["status"] == "success"
        assert r["meta"]["engine"] == "per_store_creds"

    def test_non_dict_error(self):
        r = PerStoreCredsEngine().run("nope")
        assert r["status"] == "error"

    def test_includes_overrides_in_data(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_STORE_STORE_A_OPENAI_API_KEY", "x",
        )
        with patch(
            "data_pipeline.store.store_manager.StoreManager",
        ) as MockSM:
            MockSM.return_value.list_stores.return_value = []
            r = PerStoreCredsEngine().run({})
        store_a = next(
            s for s in r["data"]["stores"]
            if s["store_id"] == "store_a"
        )
        assert "OPENAI_API_KEY" in store_a["overrides"]
