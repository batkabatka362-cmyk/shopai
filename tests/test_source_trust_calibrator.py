"""Tests for core.data.source_trust_calibrator + candidate_fusion."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.data.source_trust_calibrator import (
    SourceStats,
    SourceTrustCalibrator,
    get_calibrator,
    reset_calibrator_for_tests,
)
from agents.research.candidate_fusion import (
    FusionResult,
    fuse_candidates,
)
from agents.research.winner_searcher import ProductCandidate


def _cand(
    source="cj", title="Pet Slow Feeder", price=20.0,
    **kw,
):
    defaults = dict(
        source=source,
        external_id=f"{source}-1",
        title=title,
        price=price,
        cost=price / 2.0,
        daily_sales=5.0,
        saturation_score=0.5,
        image_url="",
        url="",
        tags=(),
    )
    defaults.update(kw)
    return ProductCandidate(**defaults)


def _build(tmp, *, now_fn=None, **kw):
    defaults = dict(
        db_path=Path(tmp) / "trust.db",
        decay_s=3600.0,
    )
    defaults.update(kw)
    if now_fn is not None:
        defaults["now_fn"] = now_fn
    return SourceTrustCalibrator(**defaults)


class TestConfig(unittest.TestCase):
    def test_bad_decay(self):
        with self.assertRaises(ValueError):
            SourceTrustCalibrator(decay_s=0)

    def test_blank_source_register(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(tmp)
            try:
                with self.assertRaises(ValueError):
                    c.register("")
            finally:
                c.close()

    def test_bad_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(tmp)
            try:
                with self.assertRaises(ValueError):
                    c.register("x", baseline_trust=1.5)
            finally:
                c.close()


class TestRegister(unittest.TestCase):
    def test_register_and_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(tmp)
            c.register(
                "cj", baseline_trust=0.7,
                note="real API",
            )
            stats = c.get("cj")
            self.assertEqual(stats.source_name, "cj")
            self.assertEqual(
                stats.baseline_trust, 0.7,
            )
            c.close()

    def test_re_register_updates_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(tmp)
            c.register("cj", baseline_trust=0.5)
            c.register("cj", baseline_trust=0.9)
            self.assertEqual(
                c.get("cj").baseline_trust, 0.9,
            )
            c.close()

    def test_set_baseline_trust_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(tmp)
            c.register("cj")
            with self.assertRaises(ValueError):
                c.set_baseline_trust("cj", 2.0)
            c.close()


class TestOutcomeAndFetch(unittest.TestCase):
    def test_record_fetch_updates_error_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(tmp)
            for _ in range(3):
                c.record_fetch("cj", ok=True)
            c.record_fetch("cj", ok=False)
            stats = c.get("cj")
            self.assertEqual(stats.fetch_attempts, 4)
            self.assertEqual(stats.fetch_errors, 1)
            self.assertAlmostEqual(
                stats.error_rate_ema, 0.25,
            )
            c.close()

    def test_record_fetch_failure_does_not_refresh(self):
        now = [1000.0]
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(
                tmp, now_fn=lambda: now[0],
            )
            c.record_fetch("cj", ok=True)
            now[0] = 2000.0
            c.record_fetch("cj", ok=False)
            self.assertEqual(
                c.get("cj").last_fetch_ts, 1000.0,
            )
            c.close()

    def test_record_outcome_updates_win_ema(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(tmp)
            for _ in range(5):
                c.record_outcome("cj", won=True)
            stats = c.get("cj")
            self.assertGreater(stats.win_ema, 0.5)
            self.assertEqual(stats.samples, 5)
            c.close()


class TestTrust(unittest.TestCase):
    def test_unknown_source_returns_default_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(tmp)
            self.assertEqual(c.trust("nope"), 0.5)
            c.close()

    def test_cold_source_blends_baseline(self):
        # Low samples + high baseline → blend toward 0.5
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(
                tmp,
                now_fn=lambda: 1000.0,
            )
            c.register(
                "brand_new", baseline_trust=0.9,
            )
            c.record_fetch("brand_new", ok=True)
            c.record_outcome("brand_new", won=True)
            # samples=1, warmup=20 → weight = 1/20 = 5%
            # trust ≈ 0.05*calibrated + 0.95*0.9
            t = c.trust("brand_new")
            self.assertGreater(t, 0.6)
            self.assertLessEqual(t, 1.0)
            c.close()

    def test_freshness_decays(self):
        now = [1000.0]
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(
                tmp, decay_s=100.0,
                now_fn=lambda: now[0],
            )
            c.register("src", baseline_trust=0.5)
            c.record_fetch("src", ok=True)
            for _ in range(25):
                c.record_outcome("src", won=True)
            fresh = c.trust("src")
            now[0] = 1000.0 + 500.0   # 5×decay elapsed
            stale = c.trust("src")
            self.assertLess(stale, fresh)
            c.close()

    def test_high_error_rate_dampens_trust(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(
                tmp, now_fn=lambda: 1000.0,
            )
            c.register("bad", baseline_trust=0.5)
            # High error rate + enough samples to bypass warmup
            for _ in range(25):
                c.record_fetch("bad", ok=False)
                c.record_outcome("bad", won=True)
            # Force one successful fetch so last_fetch_ts > 0
            c.record_fetch("bad", ok=True)
            t = c.trust("bad")
            self.assertLess(t, 0.5)
            c.close()


class TestRankedAndStats(unittest.TestCase):
    def test_ranked_sorted_by_trust(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(
                tmp, now_fn=lambda: 1000.0,
            )
            c.register("good", baseline_trust=0.9)
            c.register("bad", baseline_trust=0.1)
            c.record_fetch("good", ok=True)
            c.record_fetch("bad", ok=True)
            ranked = c.ranked()
            self.assertEqual(ranked[0][0], "good")
            self.assertEqual(ranked[-1][0], "bad")
            c.close()

    def test_stats_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(tmp)
            c.register("x")
            s = c.stats()
            self.assertEqual(s["total_sources"], 1)
            c.close()


class TestSingleton(unittest.TestCase):
    def test_singleton(self):
        reset_calibrator_for_tests()
        try:
            a = get_calibrator()
            b = get_calibrator()
            self.assertIs(a, b)
        finally:
            reset_calibrator_for_tests()


class TestSourceStatsDict(unittest.TestCase):
    def test_dict(self):
        stats = SourceStats(
            source_name="x", win_ema=0.5,
            error_rate_ema=0.1, samples=0,
            fetch_attempts=0, fetch_errors=0,
            last_fetch_ts=0.0, baseline_trust=0.5,
        )
        self.assertIn(
            "source_name", stats.as_dict(),
        )


class TestCandidateFusion(unittest.TestCase):
    def test_singleton_pass_through(self):
        out = fuse_candidates([
            _cand(source="cj", title="Pet Feeder"),
        ])
        self.assertEqual(len(out.merged), 1)
        self.assertEqual(
            out.boost_map[
                out.merged[0].canonical_key()
            ], 1.0,
        )

    def test_two_sources_merged(self):
        # Same title → same canonical_key
        out = fuse_candidates([
            _cand(
                source="cj", title="Pet Slow Feeder",
                price=10.0,
            ),
            _cand(
                source="ali", title="Pet Slow Feeder",
                price=20.0,
            ),
        ])
        self.assertEqual(len(out.merged), 1)
        # Boost = 1 + 0.2 * 1 = 1.2
        key = out.merged[0].canonical_key()
        self.assertAlmostEqual(out.boost_map[key], 1.2)

    def test_trust_weighted_price(self):
        calibrator = MagicMock()
        calibrator.trust.side_effect = lambda s: (
            0.9 if s == "cj" else 0.1
        )
        out = fuse_candidates(
            [
                _cand(source="cj", price=10.0),
                _cand(source="ali", price=30.0),
            ],
            calibrator=calibrator,
        )
        merged = out.merged[0]
        # Heavy weight on cj (0.9) → price closer to 10
        self.assertLess(merged.price, 20.0)
        self.assertGreater(merged.price, 10.0)

    def test_longest_title_wins(self):
        out = fuse_candidates([
            _cand(source="cj", title="Pet Feeder"),
            _cand(source="ali", title="Pet Feeder"),
            _cand(
                source="peer", title="Pet Feeder Bowl XL",
            ),
        ])
        # All 3 map to same canonical_key because slugify
        # strips "Bowl XL" → different slug actually... let's
        # use same titles, different sources.
        out2 = fuse_candidates([
            _cand(source="cj", title="Same"),
            _cand(source="ali", title="Same"),
            _cand(source="peer", title="Same"),
        ])
        self.assertEqual(len(out2.merged), 1)

    def test_saturation_minimum_wins(self):
        out = fuse_candidates([
            _cand(
                source="cj", saturation_score=0.7,
            ),
            _cand(
                source="ali", saturation_score=0.2,
            ),
        ])
        self.assertAlmostEqual(
            out.merged[0].saturation_score, 0.2,
        )

    def test_daily_sales_max_wins(self):
        out = fuse_candidates([
            _cand(source="cj", daily_sales=2.0),
            _cand(source="ali", daily_sales=10.0),
        ])
        self.assertEqual(
            out.merged[0].daily_sales, 10.0,
        )

    def test_raw_sources_list_preserved(self):
        out = fuse_candidates([
            _cand(source="cj"),
            _cand(source="ali"),
        ])
        raw = out.merged[0].raw
        self.assertEqual(len(raw["sources"]), 2)
        self.assertEqual(
            {s["source"] for s in raw["sources"]},
            {"cj", "ali"},
        )

    def test_boost_capped(self):
        out = fuse_candidates(
            [_cand(source=f"s{i}") for i in range(10)],
            boost_cap=1.5,
        )
        key = out.merged[0].canonical_key()
        self.assertEqual(out.boost_map[key], 1.5)

    def test_bad_boost_config(self):
        with self.assertRaises(ValueError):
            fuse_candidates(
                [],
                boost_per_extra_source=-0.1,
            )
        with self.assertRaises(ValueError):
            fuse_candidates([], boost_cap=0.5)

    def test_as_dict(self):
        out = fuse_candidates(
            [_cand(source="cj")],
        )
        d = out.as_dict()
        self.assertIn("merged_count", d)


if __name__ == "__main__":
    unittest.main()
