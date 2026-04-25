"""Ads-base retry + idempotency + brain-hook tests.

The shared ``AdsBaseAdapter`` gained three hardening layers:

  * exponential backoff on 429 / 5xx / timeout
  * auto-generated idempotency key on write verbs
  * brain outcome_recorder hook on every successful write

These are vendor-agnostic so we exercise them against a minimal
concrete subclass; Meta/Google inherit without extra wiring.
"""
from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import patch

from core.adapters.ads import _base as ads_base
from core.adapters.base import Capability, AdapterResult
from core.adapters.errors import (
    AdapterError,
    AdapterRateLimited,
    AdapterUnavailable,
)


class _FakeAdapter(ads_base.AdsBaseAdapter):
    name = "fake_ads"
    base_url = "https://example.test"
    config_alias = "fake_ads_key"
    max_retries = 2
    backoff_base_s = 0.0  # no sleep in tests

    def is_configured(self) -> bool:
        # Bypass config lookup
        return True

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer test"}

    def _do_create_campaign(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        raw = self._http_request(
            "POST",
            f"{self.base_url}/campaigns",
            body={"name": params["name"]},
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"campaign_id": raw.get("id", "")},
            raw=raw,
        )

    def _do_pause_campaign(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        raw = self._http_request(
            "POST",
            f"{self.base_url}/{params['campaign_id']}",
            body={"status": "PAUSED"},
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"campaign_id": params["campaign_id"]},
            raw=raw,
        )

    def _do_get_performance(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        raw = self._http_request(
            "GET", f"{self.base_url}/insights",
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"rows": raw.get("data", [])},
            raw=raw,
        )

    def _do_update_budget(
        self, capability, params,
    ) -> AdapterResult:
        raw = self._http_request(
            "POST",
            f"{self.base_url}/{params['campaign_id']}",
            body={"daily_budget": params["daily_budget"]},
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"campaign_id": params["campaign_id"]},
            raw=raw,
        )

    def _do_resume_campaign(
        self, capability, params,
    ) -> AdapterResult:
        raw = self._http_request(
            "POST",
            f"{self.base_url}/{params['campaign_id']}",
            body={"status": "ACTIVE"},
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"campaign_id": params["campaign_id"]},
            raw=raw,
        )


class TestRetry(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = _FakeAdapter()

    def test_succeeds_first_try(self) -> None:
        with patch.object(
            _FakeAdapter, "_do_http_once",
            return_value={"id": "c1"},
        ) as mock:
            result = self.adapter._do_create_campaign(
                Capability.ADS_CREATE_CAMPAIGN,
                {"name": "test"},
            )
        self.assertTrue(result.success)
        self.assertEqual(result.data["campaign_id"], "c1")
        self.assertEqual(mock.call_count, 1)

    def test_retries_on_429(self) -> None:
        # Fail twice with 429, then succeed
        rate_limit = AdapterRateLimited(
            "fake_ads", "rate limit (429): slowdown",
        )
        with patch.object(
            _FakeAdapter, "_do_http_once",
            side_effect=[rate_limit, rate_limit, {"id": "c1"}],
        ) as mock:
            result = self.adapter._do_create_campaign(
                Capability.ADS_CREATE_CAMPAIGN,
                {"name": "test"},
            )
        self.assertTrue(result.success)
        # max_retries=2 → up to 3 attempts total
        self.assertEqual(mock.call_count, 3)

    def test_retries_on_5xx(self) -> None:
        unavailable = AdapterUnavailable(
            "fake_ads", "vendor 5xx (503): down",
        )
        with patch.object(
            _FakeAdapter, "_do_http_once",
            side_effect=[unavailable, {"id": "c2"}],
        ):
            result = self.adapter._do_create_campaign(
                Capability.ADS_CREATE_CAMPAIGN,
                {"name": "x"},
            )
        self.assertTrue(result.success)

    def test_exhausts_retries(self) -> None:
        rate_limit = AdapterRateLimited(
            "fake_ads", "still limited",
        )
        with patch.object(
            _FakeAdapter, "_do_http_once",
            side_effect=[rate_limit] * 5,
        ):
            with self.assertRaises(AdapterRateLimited):
                self.adapter._do_create_campaign(
                    Capability.ADS_CREATE_CAMPAIGN,
                    {"name": "x"},
                )

    def test_no_retry_on_auth_error(self) -> None:
        from core.adapters.errors import AdapterAuthError
        with patch.object(
            _FakeAdapter, "_do_http_once",
            side_effect=AdapterAuthError(
                "fake_ads", "(401): bad token",
            ),
        ) as mock:
            with self.assertRaises(AdapterAuthError):
                self.adapter._do_create_campaign(
                    Capability.ADS_CREATE_CAMPAIGN,
                    {"name": "x"},
                )
        # Should NOT retry auth errors — fail fast
        self.assertEqual(mock.call_count, 1)


class TestIdempotency(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = _FakeAdapter()

    def test_idempotency_key_attached_to_writes(self) -> None:
        captured: list[dict[str, Any]] = []

        def fake_once(self, method, url, body, headers):
            captured.append(dict(body or {}))
            return {"id": "c1"}

        with patch.object(
            _FakeAdapter, "_do_http_once", fake_once,
        ):
            self.adapter._do_create_campaign(
                Capability.ADS_CREATE_CAMPAIGN,
                {"name": "x"},
            )
        self.assertEqual(len(captured), 1)
        self.assertIn("_client_request_id", captured[0])
        self.assertTrue(
            captured[0]["_client_request_id"].startswith("req_"),
        )

    def test_same_key_on_retries(self) -> None:
        """Retried writes must carry the SAME idempotency key so
        the vendor can dedupe."""
        captured_keys: list[str] = []

        def fake_once(self, method, url, body, headers):
            captured_keys.append(
                (body or {}).get("_client_request_id", ""),
            )
            if len(captured_keys) < 3:
                raise AdapterRateLimited(
                    "fake_ads", "retry me",
                )
            return {"id": "c1"}

        with patch.object(
            _FakeAdapter, "_do_http_once", fake_once,
        ):
            self.adapter._do_create_campaign(
                Capability.ADS_CREATE_CAMPAIGN,
                {"name": "x"},
            )
        self.assertEqual(len(captured_keys), 3)
        # All three attempts share the same idempotency key
        self.assertEqual(
            len(set(captured_keys)), 1,
            f"expected single key, got {captured_keys}",
        )

    def test_get_has_no_idempotency_key(self) -> None:
        captured_bodies: list[Any] = []

        def fake_once(self, method, url, body, headers):
            captured_bodies.append(body)
            return {"data": []}

        with patch.object(
            _FakeAdapter, "_do_http_once", fake_once,
        ):
            self.adapter._do_get_performance(
                Capability.ADS_GET_PERFORMANCE, {},
            )
        self.assertEqual(captured_bodies, [None])


class TestBrainHook(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = _FakeAdapter()
        self._orig = os.environ.get("SHOPAI_BRAIN_HOOKS")
        os.environ["SHOPAI_BRAIN_HOOKS"] = "1"
        # Reset brain singletons
        from core.brain import brain_facade
        brain_facade._META_REASONER = None
        brain_facade._CAPABILITY_REGISTRY = None
        brain_facade._REVENUE_FUNNEL = None
        brain_facade._PREDICTIVE_ALERTER = None
        brain_facade._MOOD_MODEL = None

    def tearDown(self) -> None:
        if self._orig is None:
            os.environ.pop("SHOPAI_BRAIN_HOOKS", None)
        else:
            os.environ["SHOPAI_BRAIN_HOOKS"] = self._orig

    def test_write_fires_brain_hook(self) -> None:
        with patch.object(
            _FakeAdapter, "_do_http_once",
            return_value={"id": "c1"},
        ):
            self.adapter.execute(
                Capability.ADS_CREATE_CAMPAIGN,
                {
                    "name": "x",
                    "decision_id": "dec_1",
                    "claimed_confidence": 0.8,
                },
            )
        from core.brain.brain_facade import brain
        calib = brain().introspect().meta_reasoning
        self.assertGreaterEqual(calib.get("n_records", 0), 1)

    def test_read_skips_brain_hook(self) -> None:
        with patch.object(
            _FakeAdapter, "_do_http_once",
            return_value={"data": []},
        ):
            self.adapter.execute(
                Capability.ADS_GET_PERFORMANCE, {},
            )
        from core.brain.brain_facade import brain
        calib = brain().introspect().meta_reasoning
        self.assertEqual(calib.get("n_records", 0), 0)


class TestBrainHookDisabled(unittest.TestCase):
    def test_no_hook_when_flag_off(self) -> None:
        os.environ.pop("SHOPAI_BRAIN_HOOKS", None)
        # Reset singletons
        from core.brain import brain_facade
        brain_facade._META_REASONER = None

        adapter = _FakeAdapter()
        with patch.object(
            _FakeAdapter, "_do_http_once",
            return_value={"id": "c1"},
        ):
            adapter.execute(
                Capability.ADS_CREATE_CAMPAIGN,
                {"name": "x"},
            )
        from core.brain.brain_facade import brain
        calib = brain().introspect().meta_reasoning
        self.assertEqual(calib.get("n_records", 0), 0)


if __name__ == "__main__":
    unittest.main()
