"""Tests for the scope-health cache layer.

``compare_to_live`` makes a fresh Shopify round-trip on every
call. Cron-able no-live-probe surfaces (daily-brief, world-model
bulk renders) can't afford that. The cache layer
(``save_report_to_cache`` / ``load_report_from_cache``)
persists the latest snapshot so those surfaces can show
current drift without re-probing.

These tests cover:
  - Save → load round-trip (the headline case)
  - Pattern J guard: save is a no-op under pytest, except
    when ``_is_test_environment`` is patched to ``False``
    (which is how this file exercises the save path)
  - ``SHOPAI_DATA_DIR`` env-var redirection so the prod cache
    file is never touched
  - Fails-open semantics for load (missing / malformed)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# Every test in this module exercises the save path, so we
# globally disable the Pattern J pytest guard for the module
# and rely on ``SHOPAI_DATA_DIR`` redirection (via the
# ``cache_dir`` fixture) to keep the prod cache file safe.
@pytest.fixture(autouse=True)
def _disable_test_env_guard():
    with patch(
        "core.adapters.shopify.scope_health._is_test_environment",
        return_value=False,
    ):
        yield


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Redirect ``SHOPAI_DATA_DIR`` to a tmp path so the cache
    file lives inside the test sandbox."""
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    return tmp_path


def _build_report(missing=None, extra=None, healthy=True):
    from core.adapters.shopify.scope_health import ScopeHealthReport
    return ScopeHealthReport(
        granted_scopes=frozenset({"read_orders", "read_products"}),
        required_scopes=frozenset({"read_orders", "read_products"}),
        missing_from_app=missing or [],
        extra_in_app=extra or [],
        is_healthy=healthy,
    )


class TestSaveReportToCache:

    def test_save_writes_file(self, cache_dir):
        from core.adapters.shopify.scope_health import (
            save_report_to_cache,
        )
        ok = save_report_to_cache(_build_report())
        assert ok is True
        cache_file = cache_dir / ".scope_health.json"
        assert cache_file.exists()
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert data["is_healthy"] is True
        assert data["granted_count"] == 2
        assert data["required_count"] == 2
        assert data["missing_from_app"] == []
        assert data["extra_in_app"] == []
        assert isinstance(data["generated_at"], float)
        assert data["generated_at"] > 0

    def test_save_with_drift_persists_lists(self, cache_dir):
        from core.adapters.shopify.scope_health import (
            save_report_to_cache,
        )
        report = _build_report(
            missing=["write_orders", "read_customers"],
            extra=["read_unused"],
            healthy=False,
        )
        assert save_report_to_cache(report) is True
        data = json.loads(
            (cache_dir / ".scope_health.json").read_text(),
        )
        assert data["is_healthy"] is False
        assert sorted(data["missing_from_app"]) == [
            "read_customers", "write_orders",
        ]
        assert data["extra_in_app"] == ["read_unused"]

    def test_save_creates_data_dir(self, tmp_path, monkeypatch):
        # Point at a subdir that doesn't exist yet
        nested = tmp_path / "nested" / "deeper"
        monkeypatch.setenv("SHOPAI_DATA_DIR", str(nested))
        from core.adapters.shopify.scope_health import (
            save_report_to_cache,
        )
        assert save_report_to_cache(_build_report()) is True
        assert (nested / ".scope_health.json").exists()

    def test_save_returns_false_under_pytest_guard(
        self, cache_dir,
    ):
        # Re-enable the guard for THIS test to verify it
        # short-circuits.
        from core.adapters.shopify.scope_health import (
            save_report_to_cache,
        )
        with patch(
            "core.adapters.shopify.scope_health"
            "._is_test_environment",
            return_value=True,
        ):
            ok = save_report_to_cache(_build_report())
        assert ok is False
        assert not (cache_dir / ".scope_health.json").exists()

    def test_save_returns_false_on_unwritable_path(
        self, tmp_path, monkeypatch,
    ):
        # Point SHOPAI_DATA_DIR at an existing FILE (not a
        # directory) so mkdir fails. The save must return
        # False, not raise.
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir")
        monkeypatch.setenv(
            "SHOPAI_DATA_DIR", str(blocker / "sub"),
        )
        from core.adapters.shopify.scope_health import (
            save_report_to_cache,
        )
        ok = save_report_to_cache(_build_report())
        assert ok is False


class TestLoadReportFromCache:

    def test_load_returns_none_when_missing(self, cache_dir):
        from core.adapters.shopify.scope_health import (
            load_report_from_cache,
        )
        # No file written yet
        assert load_report_from_cache() is None

    def test_round_trip(self, cache_dir):
        from core.adapters.shopify.scope_health import (
            load_report_from_cache,
            save_report_to_cache,
        )
        report = _build_report(
            missing=["write_orders"],
            extra=[],
            healthy=False,
        )
        assert save_report_to_cache(report) is True
        cached = load_report_from_cache()
        assert cached is not None
        assert cached["is_healthy"] is False
        assert cached["missing_from_app"] == ["write_orders"]
        assert cached["extra_in_app"] == []
        assert cached["granted_count"] == 2
        assert cached["required_count"] == 2
        assert isinstance(cached["generated_at"], float)

    def test_load_returns_none_on_malformed_json(self, cache_dir):
        from core.adapters.shopify.scope_health import (
            load_report_from_cache,
        )
        (cache_dir / ".scope_health.json").write_text(
            "not valid json {{{",
        )
        assert load_report_from_cache() is None

    def test_load_returns_none_when_not_dict(self, cache_dir):
        from core.adapters.shopify.scope_health import (
            load_report_from_cache,
        )
        # JSON list instead of dict
        (cache_dir / ".scope_health.json").write_text(
            json.dumps([1, 2, 3]),
        )
        assert load_report_from_cache() is None

    def test_load_tolerates_missing_keys(self, cache_dir):
        """Partial data shape still loads; defaults fill gaps."""
        from core.adapters.shopify.scope_health import (
            load_report_from_cache,
        )
        (cache_dir / ".scope_health.json").write_text(
            json.dumps({"generated_at": 12345.0}),
        )
        cached = load_report_from_cache()
        assert cached is not None
        assert cached["generated_at"] == 12345.0
        assert cached["is_healthy"] is False  # default
        assert cached["missing_from_app"] == []
        assert cached["extra_in_app"] == []

    def test_load_coerces_string_scope_lists(self, cache_dir):
        """If something hand-wrote the file with int IDs, the
        loader still produces a usable shape (strings)."""
        from core.adapters.shopify.scope_health import (
            load_report_from_cache,
        )
        (cache_dir / ".scope_health.json").write_text(
            json.dumps({
                "missing_from_app": ["write_orders", 42],
                "extra_in_app": ["read_x"],
            }),
        )
        cached = load_report_from_cache()
        assert cached is not None
        assert cached["missing_from_app"] == ["write_orders", "42"]
        assert cached["extra_in_app"] == ["read_x"]


class TestEnvVarHonoring:
    """Both save and load must read ``SHOPAI_DATA_DIR`` fresh on
    every call, so tests (and ops) can redirect the cache to
    different locations without restarting the process."""

    def test_save_and_load_target_same_dir(self, cache_dir):
        from core.adapters.shopify.scope_health import (
            load_report_from_cache,
            save_report_to_cache,
        )
        assert save_report_to_cache(_build_report()) is True
        # Same env-var → same file → load sees it
        cached = load_report_from_cache()
        assert cached is not None

    def test_load_misses_when_env_changed_between_calls(
        self, tmp_path, monkeypatch,
    ):
        """Save at dir A, then switch SHOPAI_DATA_DIR to dir B.
        Load now sees no cache (B is empty)."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        monkeypatch.setenv("SHOPAI_DATA_DIR", str(dir_a))
        from core.adapters.shopify.scope_health import (
            load_report_from_cache,
            save_report_to_cache,
        )
        save_report_to_cache(_build_report())
        monkeypatch.setenv("SHOPAI_DATA_DIR", str(dir_b))
        assert load_report_from_cache() is None

    def test_default_path_when_env_unset(self, monkeypatch):
        """When ``SHOPAI_DATA_DIR`` is unset, the path falls
        back to ``./data/.scope_health.json``."""
        monkeypatch.delenv("SHOPAI_DATA_DIR", raising=False)
        from core.adapters.shopify.scope_health import _cache_path
        assert _cache_path() == Path("data") / ".scope_health.json"
