"""Tests for the Q1 2026 Meta Ads API rollover:
  * base_url resolves v25.0 by default (and picks up the
    SHOPAI_META_API_VERSION env override).
  * Deprecated 7dv/28dv attribution windows translate to
    the 2026 codes 1dv/7dv_click.
  * The opt-out env flag disables translation.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from core.adapters.ads.meta_ads import (
    MetaAdsAdapter,
    _normalize_attribution_windows,
    _resolved_api_version,
)


class _EnvSandbox:
    KEYS = (
        "SHOPAI_META_API_VERSION",
        "SHOPAI_META_ATTRIBUTION_REMAP",
    )

    def __enter__(self):
        self._orig = {
            k: os.environ.get(k) for k in self.KEYS
        }
        for k in self.KEYS:
            os.environ.pop(k, None)
        return self

    def __exit__(self, *a):
        for k, v in self._orig.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestApiVersion(unittest.TestCase):
    def test_default_is_v25(self):
        with _EnvSandbox():
            self.assertEqual(
                _resolved_api_version(), "v25.0",
            )

    def test_env_override(self):
        with _EnvSandbox():
            os.environ[
                "SHOPAI_META_API_VERSION"
            ] = "v26.0"
            self.assertEqual(
                _resolved_api_version(), "v26.0",
            )

    def test_base_url_uses_current_version(self):
        with _EnvSandbox():
            adapter = MetaAdsAdapter()
            self.assertTrue(
                adapter.base_url.endswith("/v25.0"),
            )
            os.environ[
                "SHOPAI_META_API_VERSION"
            ] = "v26.0"
            # Live re-evaluation
            self.assertTrue(
                adapter.base_url.endswith("/v26.0"),
            )

    def test_blank_env_falls_back(self):
        with _EnvSandbox():
            os.environ[
                "SHOPAI_META_API_VERSION"
            ] = "  "
            self.assertEqual(
                _resolved_api_version(), "v25.0",
            )


class TestAttributionRemap(unittest.TestCase):
    def test_none_returns_empty(self):
        with _EnvSandbox():
            self.assertEqual(
                _normalize_attribution_windows(None), [],
            )

    def test_7dv_maps_to_1dv(self):
        with _EnvSandbox():
            self.assertEqual(
                _normalize_attribution_windows(["7dv"]),
                ["1dv"],
            )

    def test_28dv_maps_to_7dv_click(self):
        with _EnvSandbox():
            self.assertEqual(
                _normalize_attribution_windows(["28dv"]),
                ["7dv_click"],
            )

    def test_mixed_windows_translate(self):
        with _EnvSandbox():
            self.assertEqual(
                _normalize_attribution_windows(
                    ["7dv", "28dv", "1d_click"],
                ),
                ["1dv", "7dv_click", "1d_click"],
            )

    def test_new_codes_pass_through(self):
        with _EnvSandbox():
            self.assertEqual(
                _normalize_attribution_windows(
                    ["1dv", "7d_click"],
                ),
                ["1dv", "7d_click"],
            )

    def test_dedup_preserves_order(self):
        with _EnvSandbox():
            # 7dv + 1dv both map to 1dv → dedupe
            self.assertEqual(
                _normalize_attribution_windows(
                    ["7dv", "1dv"],
                ),
                ["1dv"],
            )

    def test_opt_out_disables_remap(self):
        with _EnvSandbox():
            os.environ[
                "SHOPAI_META_ATTRIBUTION_REMAP"
            ] = "0"
            self.assertEqual(
                _normalize_attribution_windows(
                    ["7dv", "28dv"],
                ),
                ["7dv", "28dv"],
            )

    def test_scalar_gets_wrapped(self):
        with _EnvSandbox():
            self.assertEqual(
                _normalize_attribution_windows("7dv"),
                ["1dv"],
            )


class TestPerformanceRequestURL(unittest.TestCase):
    def test_windows_added_to_query(self):
        with _EnvSandbox():
            adapter = MetaAdsAdapter()

            captured = {}

            def _fake_request(method, url, **kw):
                captured["url"] = url
                return {"data": []}

            with patch.object(
                adapter, "_http_request",
                side_effect=_fake_request,
            ), patch.object(
                adapter, "_account_id",
                return_value="act_1",
            ):
                from core.adapters.base import Capability
                adapter._do_get_performance(
                    Capability.ADS_GET_PERFORMANCE,
                    {
                        "action_attribution_windows": [
                            "7dv", "28dv",
                        ],
                    },
                )
            self.assertIn(
                "action_attribution_windows=", captured["url"],
            )
            # URL-encoded 1dv%2C7dv_click OR 1dv,7dv_click
            self.assertTrue(
                "1dv" in captured["url"]
                and "7dv_click" in captured["url"],
                captured["url"],
            )
            self.assertNotIn(
                "28dv", captured["url"],
            )

    def test_no_windows_means_no_query_param(self):
        with _EnvSandbox():
            adapter = MetaAdsAdapter()

            captured = {}

            def _fake_request(method, url, **kw):
                captured["url"] = url
                return {"data": []}

            with patch.object(
                adapter, "_http_request",
                side_effect=_fake_request,
            ), patch.object(
                adapter, "_account_id",
                return_value="act_1",
            ):
                from core.adapters.base import Capability
                adapter._do_get_performance(
                    Capability.ADS_GET_PERFORMANCE, {},
                )
            self.assertNotIn(
                "action_attribution_windows=",
                captured["url"],
            )


if __name__ == "__main__":
    unittest.main()
