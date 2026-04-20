"""Tests for core.risk.tripwire — L7 governance safety gate."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from core.risk.tripwire import (
    RiskTripwire,
    TripwireLimits,
    TripwireBlocked,
    TripwireVerdict,
    get_risk_tripwire,
    reset_risk_tripwire_for_tests,
)


def _fresh(tmpdir: str, **limit_kwargs) -> RiskTripwire:
    limits = TripwireLimits(**{
        "daily_ad_spend_usd": 100.0,
        "per_campaign_cap_usd": 30.0,
        "min_margin_ratio": 0.10,
        "max_chargeback_rate": 0.01,
        "escalate_pct": 0.8,
        **limit_kwargs,
    })
    return RiskTripwire(
        db_path=Path(tmpdir) / "risk.db",
        limits=limits,
    )


class TestTripwireLimits(unittest.TestCase):
    def test_defaults(self):
        lim = TripwireLimits()
        self.assertEqual(lim.daily_ad_spend_usd, 50.0)
        self.assertEqual(lim.per_campaign_cap_usd, 20.0)
        self.assertAlmostEqual(lim.min_margin_ratio, 0.10)
        self.assertAlmostEqual(lim.max_chargeback_rate, 0.01)

    def test_env_override(self):
        env_backup = {
            k: os.environ.get(k)
            for k in (
                "SHOPAI_RISK_DAILY_CAP_USD",
                "SHOPAI_RISK_PER_CAMPAIGN_CAP_USD",
                "SHOPAI_RISK_MIN_MARGIN",
                "SHOPAI_RISK_MAX_CHARGEBACK",
                "SHOPAI_RISK_ESCALATE_PCT",
            )
        }
        try:
            os.environ["SHOPAI_RISK_DAILY_CAP_USD"] = "250"
            os.environ["SHOPAI_RISK_PER_CAMPAIGN_CAP_USD"] = "40"
            os.environ["SHOPAI_RISK_MIN_MARGIN"] = "0.15"
            os.environ["SHOPAI_RISK_MAX_CHARGEBACK"] = "0.005"
            os.environ["SHOPAI_RISK_ESCALATE_PCT"] = "0.5"
            lim = TripwireLimits.from_env()
            self.assertEqual(lim.daily_ad_spend_usd, 250.0)
            self.assertEqual(lim.per_campaign_cap_usd, 40.0)
            self.assertAlmostEqual(lim.min_margin_ratio, 0.15)
            self.assertAlmostEqual(lim.max_chargeback_rate, 0.005)
            self.assertAlmostEqual(lim.escalate_pct, 0.5)
        finally:
            for k, v in env_backup.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_env_invalid_falls_back(self):
        try:
            os.environ["SHOPAI_RISK_DAILY_CAP_USD"] = "not_a_number"
            lim = TripwireLimits.from_env()
            self.assertEqual(lim.daily_ad_spend_usd, 50.0)
        finally:
            os.environ.pop("SHOPAI_RISK_DAILY_CAP_USD", None)


class TestAllowance(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tw = _fresh(self._tmp.name)

    def tearDown(self):
        self.tw.close()
        self._tmp.cleanup()

    def test_allow_within_limits(self):
        v = self.tw.check_before_spend(
            amount_usd=5.0,
            campaign_id="cmp_1",
        )
        self.assertEqual(v.action, "allow")
        self.assertEqual(v.rule, "")

    def test_negative_amount_blocked(self):
        v = self.tw.check_before_spend(amount_usd=-1.0)
        self.assertEqual(v.action, "block")
        self.assertEqual(v.rule, "amount_sanity")


class TestMarginFloor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tw = _fresh(self._tmp.name, min_margin_ratio=0.20)

    def tearDown(self):
        self.tw.close()
        self._tmp.cleanup()

    def test_margin_below_floor_blocks(self):
        v = self.tw.check_before_spend(
            amount_usd=5.0, margin_ratio=0.10,
        )
        self.assertEqual(v.action, "block")
        self.assertEqual(v.rule, "min_margin_ratio")
        self.assertIn("10.00%", v.reason)

    def test_margin_at_floor_allows(self):
        v = self.tw.check_before_spend(
            amount_usd=5.0, margin_ratio=0.20,
        )
        self.assertEqual(v.action, "allow")

    def test_invalid_margin_blocked(self):
        v = self.tw.check_before_spend(
            amount_usd=5.0, margin_ratio="abc",
        )
        self.assertEqual(v.action, "block")
        self.assertEqual(v.rule, "min_margin_ratio")

    def test_floor_disabled_allows_any(self):
        tw = _fresh(self._tmp.name, min_margin_ratio=0.0)
        v = tw.check_before_spend(
            amount_usd=5.0, margin_ratio=0.01,
        )
        self.assertEqual(v.action, "allow")
        tw.close()


class TestPerCampaignCap(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tw = _fresh(
            self._tmp.name, per_campaign_cap_usd=20.0,
        )

    def tearDown(self):
        self.tw.close()
        self._tmp.cleanup()

    def test_new_campaign_within_cap(self):
        v = self.tw.check_before_spend(
            amount_usd=10.0, campaign_id="cmp_a",
        )
        self.assertEqual(v.action, "allow")

    def test_campaign_over_cap_blocks(self):
        self.tw.record_spend(
            amount_usd=15.0, campaign_id="cmp_a",
        )
        v = self.tw.check_before_spend(
            amount_usd=10.0, campaign_id="cmp_a",
        )
        self.assertEqual(v.action, "block")
        self.assertEqual(v.rule, "per_campaign_cap_usd")
        self.assertIn("cmp_a", v.reason)

    def test_other_campaign_unaffected(self):
        self.tw.record_spend(
            amount_usd=20.0, campaign_id="cmp_a",
        )
        v = self.tw.check_before_spend(
            amount_usd=5.0, campaign_id="cmp_b",
        )
        self.assertEqual(v.action, "allow")


class TestDailyCap(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tw = _fresh(
            self._tmp.name,
            daily_ad_spend_usd=100.0,
            per_campaign_cap_usd=1000.0,   # don't trip this first
            escalate_pct=0.8,
        )

    def tearDown(self):
        self.tw.close()
        self._tmp.cleanup()

    def test_daily_cap_blocks_when_over(self):
        self.tw.record_spend(
            amount_usd=95.0, campaign_id="cmp_a",
        )
        v = self.tw.check_before_spend(
            amount_usd=10.0, campaign_id="cmp_b",
        )
        self.assertEqual(v.action, "block")
        self.assertEqual(v.rule, "daily_ad_spend_usd")

    def test_escalate_before_block(self):
        # 85 spent + 5 new = 90 > 80 (escalate_pct) but < 100 cap
        self.tw.record_spend(
            amount_usd=85.0, campaign_id="cmp_a",
        )
        v = self.tw.check_before_spend(
            amount_usd=5.0, campaign_id="cmp_b",
        )
        self.assertEqual(v.action, "escalate")
        self.assertEqual(v.rule, "daily_ad_spend_usd_escalate")

    def test_non_ad_category_ignored_by_daily(self):
        self.tw.record_spend(
            amount_usd=200.0, category="other",
        )
        v = self.tw.check_before_spend(
            amount_usd=10.0, category="ad_spend",
        )
        self.assertEqual(v.action, "allow")


class TestChargebackRate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tw = _fresh(
            self._tmp.name, max_chargeback_rate=0.05,
        )

    def tearDown(self):
        self.tw.close()
        self._tmp.cleanup()

    def test_insufficient_volume_allows(self):
        for _ in range(5):
            self.tw.record_outcome(kind="order", is_bad=True)
        v = self.tw.check_before_spend(amount_usd=5.0)
        self.assertEqual(v.action, "allow")

    def test_rate_over_threshold_blocks(self):
        # 30 total, 6 bad = 20% > 5% cap
        for _ in range(24):
            self.tw.record_outcome(kind="order", is_bad=False)
        for _ in range(6):
            self.tw.record_outcome(
                kind="chargeback", is_bad=True,
            )
        v = self.tw.check_before_spend(amount_usd=5.0)
        self.assertEqual(v.action, "block")
        self.assertEqual(v.rule, "max_chargeback_rate")
        self.assertIn("6/30", v.reason)

    def test_old_outcomes_expire(self):
        now = time.time()

        def past():
            return now - 60 * 86400.0

        self.tw._now_fn = past
        for _ in range(30):
            self.tw.record_outcome(
                kind="chargeback", is_bad=True,
            )
        self.tw._now_fn = time.time
        v = self.tw.check_before_spend(amount_usd=5.0)
        self.assertEqual(v.action, "allow")


class TestIdempotency(unittest.TestCase):
    def test_dedupe_key_prevents_double_count(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            tw = _fresh(tmp.name)
            id1 = tw.record_spend(
                amount_usd=10.0, campaign_id="cmp_x",
                dedupe_key="req-42",
            )
            id2 = tw.record_spend(
                amount_usd=10.0, campaign_id="cmp_x",
                dedupe_key="req-42",
            )
            self.assertEqual(id1, id2)
            self.assertEqual(
                tw._daily_spend("ad_spend"), 10.0,
            )
            tw.close()
        finally:
            tmp.cleanup()

    def test_no_dedupe_key_always_new(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            tw = _fresh(tmp.name)
            id1 = tw.record_spend(amount_usd=5.0)
            id2 = tw.record_spend(amount_usd=5.0)
            self.assertNotEqual(id1, id2)
            self.assertEqual(
                tw._daily_spend("ad_spend"), 10.0,
            )
            tw.close()
        finally:
            tmp.cleanup()


class TestStatus(unittest.TestCase):
    def test_status_shape(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            tw = _fresh(tmp.name)
            tw.record_spend(amount_usd=25.0, campaign_id="c1")
            s = tw.status()
            self.assertIn("limits", s)
            self.assertIn("today", s)
            self.assertIn("chargebacks", s)
            self.assertAlmostEqual(
                s["today"]["ad_spend_usd"], 25.0,
            )
            self.assertGreater(s["today"]["utilisation"], 0)
            self.assertGreater(
                s["today"]["remaining_usd"], 0,
            )
            tw.close()
        finally:
            tmp.cleanup()

    def test_recent_spend(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            tw = _fresh(tmp.name)
            for i in range(3):
                tw.record_spend(
                    amount_usd=float(i + 1),
                    campaign_id=f"c{i}",
                    meta={"iter": i},
                )
            recent = tw.recent_spend(limit=10)
            self.assertEqual(len(recent), 3)
            # DESC order → last recorded first
            self.assertEqual(recent[0]["campaign_id"], "c2")
            self.assertEqual(recent[0]["meta"]["iter"], 2)
            tw.close()
        finally:
            tmp.cleanup()


class TestSingleton(unittest.TestCase):
    def test_singleton_reused(self):
        reset_risk_tripwire_for_tests()
        try:
            a = get_risk_tripwire()
            b = get_risk_tripwire()
            self.assertIs(a, b)
        finally:
            reset_risk_tripwire_for_tests()


class TestBlockedException(unittest.TestCase):
    def test_raises_with_verdict(self):
        v = TripwireVerdict(
            action="block", reason="test",
            rule="daily_ad_spend_usd",
        )
        with self.assertRaises(TripwireBlocked) as ctx:
            raise TripwireBlocked(v)
        self.assertEqual(
            ctx.exception.verdict.rule, "daily_ad_spend_usd",
        )
        self.assertIn("test", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
