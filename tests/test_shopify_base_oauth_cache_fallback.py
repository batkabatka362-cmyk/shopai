"""Tests for the OAuth-cache fallback in ShopifyBaseAdapter.

PRs #418-#421 + #429 wired the adapter layer to 100% scope
coverage. PR #422-#430 made the engines use the resulting
token. The remaining gap was the BOOTSTRAP path:
``ShopifyBaseAdapter._resolve_credentials()`` only read from
the ``SHOPAI_SHOPIFY_KEY`` env var, so the OAuth flow that
wrote a token to ``data/.shopify_tokens.json`` was invisible
to adapter instances unless the operator separately exported
the token as an env var.

This PR closes that gap. After OAuth runs once, every adapter
becomes usable without any extra setup -- including the
``shopify_doctor``'s live scope + webhook drift checks that
were silently SKIPPING because the apps adapter reported
``not configured``.

Coverage:
  1. Env var still wins -- existing behaviour preserved.
  2. OAuth-cache token loaded when env var is unset.
  3. No shop_url -> no fallback attempt (caller knows nothing).
  4. Cache file missing -> empty fallback (graceful).
  5. Cache file corrupt JSON -> empty fallback.
  6. Cache file has different shop -> empty fallback.
  7. In-process memoisation (mtime-stamped) -> rotated tokens
     picked up after the disk write.
  8. is_configured() reflects the OAuth-cache path.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.adapters.base import Capability
from core.adapters.shopify._base import (
    ShopifyBaseAdapter,
    _OAUTH_CACHE_BY_SHOP,
    _load_oauth_cached_token,
)


@pytest.fixture(autouse=True)
def _reset_in_process_cache():
    """Clear the in-process memo before each test."""
    _OAUTH_CACHE_BY_SHOP.clear()
    yield
    _OAUTH_CACHE_BY_SHOP.clear()


@pytest.fixture
def patched_cache_path(tmp_path):
    """Point ``_load_oauth_cached_token`` at a temp file."""
    cache_file = tmp_path / "shopify_tokens.json"
    with patch(
        "core.adapters.shopify._base._oauth_cache_path",
        return_value=str(cache_file),
    ):
        yield cache_file


class _TestAdapter(ShopifyBaseAdapter):
    """Concrete adapter for credential-resolution tests."""

    name = "test_adapter"
    # Tests never dispatch through this adapter -- a non-empty
    # capabilities set is just required by the abstract base.
    capabilities = {Capability.SHOPIFY_GET_SHOP}

    def _execute(self, capability, params):  # noqa: ANN001
        return self._success(capability, data={})


class TestLoadOAuthCachedToken:

    def test_returns_empty_when_shop_url_blank(self, patched_cache_path):
        assert _load_oauth_cached_token("") == ""

    def test_returns_empty_when_cache_file_missing(
        self, patched_cache_path,
    ):
        # No write to patched_cache_path -- it doesn't exist
        assert _load_oauth_cached_token("any-shop.myshopify.com") == ""

    def test_loads_token_for_matching_shop(self, patched_cache_path):
        patched_cache_path.parent.mkdir(parents=True, exist_ok=True)
        patched_cache_path.write_text(json.dumps({
            "ts0efe-ih.myshopify.com": {
                "access_token": "shpat_abc",
                "expires_at": 1779288000,
            }
        }))
        token = _load_oauth_cached_token("ts0efe-ih.myshopify.com")
        assert token == "shpat_abc"

    def test_returns_empty_for_unknown_shop(self, patched_cache_path):
        patched_cache_path.write_text(json.dumps({
            "store-a.myshopify.com": {"access_token": "shpat_a"},
        }))
        assert _load_oauth_cached_token("other.myshopify.com") == ""

    def test_corrupt_json_returns_empty(self, patched_cache_path):
        patched_cache_path.write_text("not json {{{")
        assert _load_oauth_cached_token("any.myshopify.com") == ""

    def test_lowercase_match_fallback(self, patched_cache_path):
        """Shop names compared case-sensitively first, then
        fall back to lowercased lookup."""
        patched_cache_path.write_text(json.dumps({
            "case.myshopify.com": {"access_token": "shpat_lower"},
        }))
        # Caller passes upper but file has lower
        assert (
            _load_oauth_cached_token("CASE.MYSHOPIFY.COM")
            == "shpat_lower"
        )

    def test_in_process_cache_invalidates_on_mtime(
        self, patched_cache_path,
    ):
        """When the disk file rotates (OAuth refresh writes a
        new token), the in-process cache picks it up on the
        next read."""
        patched_cache_path.write_text(json.dumps({
            "x.myshopify.com": {"access_token": "shpat_old"},
        }))
        first = _load_oauth_cached_token("x.myshopify.com")
        assert first == "shpat_old"

        # Sleep enough for mtime to roll forward (Windows
        # filesystems sometimes have 1-second mtime granularity)
        time.sleep(1.1)

        patched_cache_path.write_text(json.dumps({
            "x.myshopify.com": {"access_token": "shpat_new"},
        }))
        second = _load_oauth_cached_token("x.myshopify.com")
        assert second == "shpat_new"


class TestResolveCredentialsFallback:

    def test_env_var_wins_when_set(self, patched_cache_path, monkeypatch):
        """SHOPAI_SHOPIFY_KEY env var takes priority over
        OAuth cache."""
        # OAuth cache has a different token
        patched_cache_path.write_text(json.dumps({
            "x.myshopify.com": {"access_token": "shpat_oauth"},
        }))
        # Env var has the legacy static token
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "x.myshopify.com")
        monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "shpat_env")
        # Force AdapterConfig reload to pick up the monkeypatched env
        from core.adapters.config import get_config
        get_config().reload()

        adapter = _TestAdapter()
        shop, token = adapter._resolve_credentials()
        assert shop == "x.myshopify.com"
        assert token == "shpat_env"  # env wins, NOT OAuth cache

    def test_oauth_cache_used_when_env_var_missing(
        self, patched_cache_path, monkeypatch,
    ):
        """SHOPAI_SHOPIFY_KEY unset -> fall back to OAuth cache."""
        patched_cache_path.write_text(json.dumps({
            "deguar.myshopify.com": {"access_token": "shpat_cache"},
        }))
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "deguar.myshopify.com")
        monkeypatch.delenv("SHOPAI_SHOPIFY_KEY", raising=False)
        from core.adapters.config import get_config
        get_config().reload()

        adapter = _TestAdapter()
        shop, token = adapter._resolve_credentials()
        assert shop == "deguar.myshopify.com"
        assert token == "shpat_cache"

    def test_explicit_kwargs_still_win_over_cache(
        self, patched_cache_path, monkeypatch,
    ):
        """Constructor args take top priority -- override both
        env var AND OAuth cache."""
        patched_cache_path.write_text(json.dumps({
            "x.myshopify.com": {"access_token": "shpat_cache"},
        }))
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "x.myshopify.com")
        monkeypatch.delenv("SHOPAI_SHOPIFY_KEY", raising=False)
        from core.adapters.config import get_config
        get_config().reload()

        adapter = _TestAdapter(
            shop_url="x.myshopify.com", access_token="shpat_explicit",
        )
        shop, token = adapter._resolve_credentials()
        assert token == "shpat_explicit"

    def test_is_configured_true_via_oauth_cache(
        self, patched_cache_path, monkeypatch,
    ):
        """The whole point: ``is_configured()`` returns True when
        only the OAuth cache has the token (no env var) -- which
        means the live scope drift check will actually run."""
        patched_cache_path.write_text(json.dumps({
            "y.myshopify.com": {"access_token": "shpat_x"},
        }))
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "y.myshopify.com")
        monkeypatch.delenv("SHOPAI_SHOPIFY_KEY", raising=False)
        from core.adapters.config import get_config
        get_config().reload()

        adapter = _TestAdapter()
        assert adapter.is_configured() is True

    def test_is_configured_false_when_nothing_available(
        self, patched_cache_path, monkeypatch,
    ):
        """Empty env AND empty cache -> not configured."""
        # Empty cache file
        patched_cache_path.write_text(json.dumps({}))
        monkeypatch.delenv("SHOPAI_SHOPIFY_URL", raising=False)
        monkeypatch.delenv("SHOPAI_SHOPIFY_KEY", raising=False)
        from core.adapters.config import get_config
        get_config().reload()

        adapter = _TestAdapter()
        assert adapter.is_configured() is False
