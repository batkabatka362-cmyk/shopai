"""Observation fuser tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.memory import observation_fuser as of


class TestReport(unittest.TestCase):
    def test_blank_source_raises(self) -> None:
        f = of.ObservationFuser()
        with self.assertRaises(ValueError):
            f.report(source="", fusion_key="o1", payload={})

    def test_blank_fusion_key_raises(self) -> None:
        f = of.ObservationFuser()
        with self.assertRaises(ValueError):
            f.report(source="a", fusion_key="", payload={})

    def test_confidence_clamped(self) -> None:
        f = of.ObservationFuser()
        r = f.report(
            source="a", fusion_key="o1",
            payload={"x": 1}, confidence=5.0,
        )
        self.assertEqual(r.confidence, 1.0)


class TestFuseSingle(unittest.TestCase):
    def test_single_report_roundtrips(self) -> None:
        f = of.ObservationFuser()
        f.report(
            source="shopify", fusion_key="o1",
            payload={"amount": 47.50},
        )
        fo = f.fuse("o1")
        self.assertIsNotNone(fo)
        self.assertEqual(fo.fields["amount"].value, 47.50)
        self.assertEqual(fo.fields["amount"].voters, ["shopify"])

    def test_unknown_key_returns_none(self) -> None:
        self.assertIsNone(of.ObservationFuser().fuse("nope"))


class TestFuseAgreement(unittest.TestCase):
    def test_unanimous_sources_agreement_note(self) -> None:
        f = of.ObservationFuser()
        f.report(
            source="shopify", fusion_key="o1",
            payload={"amount": 47.50},
        )
        f.report(
            source="meta", fusion_key="o1",
            payload={"amount": 47.50},
        )
        fo = f.fuse("o1")
        self.assertEqual(fo.reconciliation_note, "agreement")
        self.assertEqual(fo.fields["amount"].agreement, 1.0)

    def test_float_drift_same_bucket(self) -> None:
        f = of.ObservationFuser()
        # 4-dp rounding → 47.499961 and 47.500036 both become 47.5
        f.report(
            source="shopify", fusion_key="o1",
            payload={"amount": 47.499961},
        )
        f.report(
            source="meta", fusion_key="o1",
            payload={"amount": 47.500036},
        )
        fo = f.fuse("o1")
        self.assertEqual(fo.reconciliation_note, "agreement")


class TestFuseDisagreement(unittest.TestCase):
    def test_weighted_vote_resolves(self) -> None:
        # Trusted source (1.0) disagrees with noisy (0.1) → trusted wins
        trust = {"trusted": 1.0, "noisy": 0.1}
        f = of.ObservationFuser(trust_fn=lambda s: trust.get(s, 0.5))
        f.report(
            source="trusted", fusion_key="o1",
            payload={"amount": 100.0},
        )
        f.report(
            source="noisy", fusion_key="o1",
            payload={"amount": 99.0},
        )
        fo = f.fuse("o1")
        self.assertEqual(fo.fields["amount"].value, 100.0)
        self.assertIn("disagreement", fo.reconciliation_note)

    def test_trust_fn_raise_defaults_full_trust(self) -> None:
        def boom(_):
            raise RuntimeError("x")

        f = of.ObservationFuser(trust_fn=boom)
        f.report(
            source="a", fusion_key="o1",
            payload={"amount": 10.0},
        )
        fo = f.fuse("o1")
        # No crash, single voter
        self.assertEqual(fo.fields["amount"].value, 10.0)

    def test_zero_weight_reports_skipped(self) -> None:
        f = of.ObservationFuser(trust_fn=lambda s: 0.0)
        f.report(
            source="a", fusion_key="o1",
            payload={"amount": 10.0},
            confidence=0.5,
        )
        fo = f.fuse("o1")
        # Zero total weight → no fields
        self.assertEqual(fo.fields, {})


class TestFuseAll(unittest.TestCase):
    def test_returns_one_per_key(self) -> None:
        f = of.ObservationFuser()
        f.report(
            source="a", fusion_key="o1",
            payload={"amount": 10},
        )
        f.report(
            source="a", fusion_key="o2",
            payload={"amount": 20},
        )
        fos = f.fuse_all()
        keys = {fo.fusion_key for fo in fos}
        self.assertEqual(keys, {"o1", "o2"})


class TestDisagreements(unittest.TestCase):
    def test_disagreement_filter(self) -> None:
        f = of.ObservationFuser()
        # o1: agreement
        f.report(
            source="a", fusion_key="o1",
            payload={"amount": 10},
        )
        f.report(
            source="b", fusion_key="o1",
            payload={"amount": 10},
        )
        # o2: disagreement
        f.report(
            source="a", fusion_key="o2",
            payload={"amount": 10},
        )
        f.report(
            source="b", fusion_key="o2",
            payload={"amount": 20},
        )
        disagr = f.disagreements(min_sources=2)
        keys = {fo.fusion_key for fo in disagr}
        self.assertEqual(keys, {"o2"})


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "f.db"
        first = of.ObservationFuser(db_path=path)
        first.report(
            source="shopify", fusion_key="o1",
            payload={"amount": 47.5},
        )
        first.close()
        second = of.ObservationFuser(db_path=path)
        fo = second.fuse("o1")
        self.assertIsNotNone(fo)
        self.assertEqual(fo.fields["amount"].value, 47.5)
        second.close()
        tmp.cleanup()


class TestStatsReset(unittest.TestCase):
    def test_stats_shape(self) -> None:
        f = of.ObservationFuser()
        f.report(source="a", fusion_key="o1", payload={"x": 1})
        f.report(source="a", fusion_key="o2", payload={"x": 1})
        s = f.stats()
        self.assertEqual(s["keys"], 2)
        self.assertEqual(s["reports"], 2)

    def test_reset_single(self) -> None:
        f = of.ObservationFuser()
        f.report(source="a", fusion_key="o1", payload={"x": 1})
        f.report(source="a", fusion_key="o2", payload={"x": 1})
        self.assertEqual(f.reset("o1"), 1)
        self.assertEqual(f.stats()["keys"], 1)

    def test_reset_all(self) -> None:
        f = of.ObservationFuser()
        f.report(source="a", fusion_key="o1", payload={"x": 1})
        self.assertEqual(f.reset(), 1)


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        f = of.ObservationFuser()
        f.report(
            source="a", fusion_key="o1",
            payload={"amount": 10},
        )
        fo = f.fuse("o1")
        d = fo.as_dict()
        self.assertIn("fields", d)
        self.assertIn("sources", d)

    def test_report_serialises(self) -> None:
        r = of.Report(
            source="a", fusion_key="o",
            payload={"x": 1}, confidence=0.8, ts=1.0,
        )
        self.assertEqual(r.as_dict()["confidence"], 0.8)


if __name__ == "__main__":
    unittest.main()
