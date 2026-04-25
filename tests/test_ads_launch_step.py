"""AdsLaunchStep wire-up tests.

Previously a stub raised StepSkip with "not implemented". This
batch wires it to the real MetaAdsAdapter via the shared
Capability dispatch path. Tests lock:
  * env-missing → StepSkip (doesn't regress)
  * adapter called with expected params
  * result populated into context.ad_campaign
  * adapter failure → RuntimeError (not silently skipped)
  * PAUSED status hard-coded (§4b.G paranoid mode)
  * daily_budget converted to cents correctly
"""
from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from workflows.launch.context import LaunchContext, LaunchGoal
from workflows.launch.steps._base import StepSkip
from workflows.launch.steps.ads_launch import AdsLaunchStep


def _context(
    *,
    ad_budget_day: float = 20.0,
    kill_roas: float = 1.5,
    kill_after: int = 3,
    storefront_url: str = "https://my.shop/products/x",
    variants: list | None = None,
) -> LaunchContext:
    goal = LaunchGoal(
        ad_budget_day=ad_budget_day,
        ad_kill_roas=kill_roas,
        ad_kill_after_days=kill_after,
    )
    ctx = LaunchContext(
        goal=goal, launch_id="test_launch_123",
    )
    ctx.shopify_product = {"storefront_url": storefront_url}
    ctx.creative = {
        "variants": (
            variants
            if variants is not None
            else [{"id": "v1", "media": "x.png"}]
        ),
    }
    return ctx


_FULL_ENV = {
    "META_ADS_ACCESS_TOKEN": "token",
    "META_ADS_ACCOUNT_ID": "act_123",
    "META_ADS_PIXEL_ID": "pix_456",
    "META_ADS_PAGE_ID": "page_789",
}


class TestEnvGate(unittest.TestCase):
    def test_missing_env_raises_step_skip(self):
        # Ensure at least one is missing
        with patch.dict(
            "os.environ",
            {
                "META_ADS_ACCESS_TOKEN": "",
                "META_ADS_ACCOUNT_ID": "",
                "META_ADS_PIXEL_ID": "",
                "META_ADS_PAGE_ID": "",
            },
            clear=False,
        ):
            step = AdsLaunchStep()
            with self.assertRaises(StepSkip) as ex:
                step.execute(_context())
            self.assertIn(
                "Meta Ads not configured", str(ex.exception),
            )

    def test_missing_storefront_raises_step_skip(self):
        with patch.dict(
            "os.environ", _FULL_ENV, clear=False,
        ):
            step = AdsLaunchStep()
            with self.assertRaises(StepSkip) as ex:
                step.execute(
                    _context(storefront_url=""),
                )
            self.assertIn(
                "storefront", str(ex.exception),
            )

    def test_missing_variants_raises_step_skip(self):
        with patch.dict(
            "os.environ", _FULL_ENV, clear=False,
        ):
            step = AdsLaunchStep()
            with self.assertRaises(StepSkip) as ex:
                step.execute(_context(variants=[]))
            self.assertIn("variants", str(ex.exception))


class TestAdapterCall(unittest.TestCase):
    def _mock_adapter(
        self, *, ok: bool = True, campaign_id: str = "c_42",
    ):
        from core.adapters.base import AdapterResult

        adapter = MagicMock()
        adapter.is_configured.return_value = True
        if ok:
            adapter.execute.return_value = (
                AdapterResult.success(
                    adapter="meta_ads",
                    capability="ads_create_campaign",
                    data={
                        "campaign_id": campaign_id,
                        "name": "n",
                        "status": "PAUSED",
                    },
                    raw={},
                )
            )
        else:
            adapter.execute.return_value = (
                AdapterResult.failure(
                    adapter="meta_ads",
                    capability="ads_create_campaign",
                    error="rate limited",
                    raw={},
                )
            )
        return adapter

    def test_happy_path_populates_context_and_returns(self):
        with patch.dict(
            "os.environ", _FULL_ENV, clear=False,
        ):
            adapter = self._mock_adapter(
                campaign_id="camp_abc",
            )
            with patch(
                "core.adapters.ads.meta_ads."
                "MetaAdsAdapter",
                return_value=adapter,
            ):
                step = AdsLaunchStep()
                ctx = _context(ad_budget_day=25.0)
                out = step.execute(ctx)
        self.assertEqual(out["campaign_id"], "camp_abc")
        self.assertEqual(ctx.ad_campaign["campaign_id"], "camp_abc")
        self.assertEqual(
            ctx.ad_campaign["daily_budget_usd"], 25.0,
        )

    def test_daily_budget_converted_to_cents(self):
        with patch.dict(
            "os.environ", _FULL_ENV, clear=False,
        ):
            adapter = self._mock_adapter()
            with patch(
                "core.adapters.ads.meta_ads."
                "MetaAdsAdapter",
                return_value=adapter,
            ):
                step = AdsLaunchStep()
                step.execute(_context(ad_budget_day=20.0))
        params = adapter.execute.call_args[0][1]
        self.assertEqual(params["daily_budget"], 2000)

    def test_status_is_paused_not_active(self):
        """§4b.G paranoid mode — always PAUSED on create."""
        with patch.dict(
            "os.environ", _FULL_ENV, clear=False,
        ):
            adapter = self._mock_adapter()
            with patch(
                "core.adapters.ads.meta_ads."
                "MetaAdsAdapter",
                return_value=adapter,
            ):
                step = AdsLaunchStep()
                step.execute(_context())
        params = adapter.execute.call_args[0][1]
        self.assertEqual(params["status"], "PAUSED")

    def test_campaign_name_includes_launch_id(self):
        with patch.dict(
            "os.environ", _FULL_ENV, clear=False,
        ):
            adapter = self._mock_adapter()
            with patch(
                "core.adapters.ads.meta_ads."
                "MetaAdsAdapter",
                return_value=adapter,
            ):
                step = AdsLaunchStep()
                step.execute(_context())
        params = adapter.execute.call_args[0][1]
        self.assertEqual(
            params["name"], "shopai_test_launch_123",
        )

    def test_kill_rule_stored_in_context(self):
        with patch.dict(
            "os.environ", _FULL_ENV, clear=False,
        ):
            adapter = self._mock_adapter()
            with patch(
                "core.adapters.ads.meta_ads."
                "MetaAdsAdapter",
                return_value=adapter,
            ):
                step = AdsLaunchStep()
                ctx = _context(
                    kill_roas=1.8, kill_after=5,
                )
                step.execute(ctx)
        self.assertEqual(
            ctx.ad_campaign["kill_rule"]["roas_below"], 1.8,
        )
        self.assertEqual(
            ctx.ad_campaign["kill_rule"]["after_days"], 5,
        )

    def test_adapter_failure_raises_runtime_error(self):
        """Adapter error must bubble as RuntimeError — not
        silent StepSkip. Pipeline runner marks the step failed
        via the error; caller keeps a record of what broke."""
        with patch.dict(
            "os.environ", _FULL_ENV, clear=False,
        ):
            adapter = self._mock_adapter(ok=False)
            with patch(
                "core.adapters.ads.meta_ads."
                "MetaAdsAdapter",
                return_value=adapter,
            ):
                step = AdsLaunchStep()
                with self.assertRaises(RuntimeError) as ex:
                    step.execute(_context())
                self.assertIn(
                    "rate limited", str(ex.exception),
                )

    def test_unconfigured_adapter_raises_step_skip(self):
        """If env is present but the adapter's is_configured
        rejects (e.g., token format wrong), we StepSkip
        rather than hit the API with bad creds."""
        with patch.dict(
            "os.environ", _FULL_ENV, clear=False,
        ):
            adapter = MagicMock()
            adapter.is_configured.return_value = False
            with patch(
                "core.adapters.ads.meta_ads."
                "MetaAdsAdapter",
                return_value=adapter,
            ):
                step = AdsLaunchStep()
                with self.assertRaises(StepSkip):
                    step.execute(_context())


if __name__ == "__main__":
    unittest.main()
