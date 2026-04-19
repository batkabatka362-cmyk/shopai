"""Commitment verifier tests."""
from __future__ import annotations

import unittest

from core.brain import commitment_verifier as cv


class TestMeasurableClaim(unittest.TestCase):
    def test_blank_kpi_raises(self) -> None:
        with self.assertRaises(ValueError):
            cv.MeasurableClaim(
                kpi="", operator="ge", threshold=0.0,
            )

    def test_bad_operator_raises(self) -> None:
        with self.assertRaises(ValueError):
            cv.MeasurableClaim(
                kpi="roas", operator="zzz", threshold=1.0,
            )  # type: ignore[arg-type]

    def test_bad_window_raises(self) -> None:
        with self.assertRaises(ValueError):
            cv.MeasurableClaim(
                kpi="roas", operator="ge", threshold=1.0,
                window_s=0,
            )

    def test_satisfied_operators(self) -> None:
        ge = cv.MeasurableClaim(kpi="x", operator="ge", threshold=5)
        self.assertTrue(ge.satisfied(5.0))
        self.assertTrue(ge.satisfied(6.0))
        self.assertFalse(ge.satisfied(4.0))
        lt = cv.MeasurableClaim(kpi="x", operator="lt", threshold=5)
        self.assertTrue(lt.satisfied(4.0))
        self.assertFalse(lt.satisfied(5.0))
        eq = cv.MeasurableClaim(kpi="x", operator="eq", threshold=5)
        self.assertTrue(eq.satisfied(5.0))
        self.assertFalse(eq.satisfied(5.1))


class TestConfig(unittest.TestCase):
    def test_bad_min_samples_raises(self) -> None:
        with self.assertRaises(ValueError):
            cv.CommitmentVerifier(min_samples=0)


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        self.v = cv.CommitmentVerifier()
        self.claim = cv.MeasurableClaim(
            kpi="roas", operator="ge", threshold=1.5,
        )

    def test_register_and_lookup(self) -> None:
        self.v.register_claim(
            "c1", self.claim, fulfillment_ts=1000.0,
        )
        self.assertIsNotNone(self.v.claim_for("c1"))

    def test_blank_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.v.register_claim(
                "", self.claim, fulfillment_ts=1000,
            )

    def test_bad_ts_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.v.register_claim(
                "c1", self.claim, fulfillment_ts=-1,
            )

    def test_unregister(self) -> None:
        self.v.register_claim(
            "c1", self.claim, fulfillment_ts=1000,
        )
        self.assertTrue(self.v.unregister_claim("c1"))
        self.assertFalse(self.v.unregister_claim("c1"))


class TestVerifyUnknown(unittest.TestCase):
    def test_unknown_commitment_returns_unknown(self) -> None:
        v = cv.CommitmentVerifier()
        result = v.verify("nope")
        self.assertEqual(result.verdict, "unknown")


class TestVerifyVerdicts(unittest.TestCase):
    def _setup(self, samples):
        def measurement(kpi, from_ts, to_ts):
            return samples

        v = cv.CommitmentVerifier(measurement_fn=measurement)
        v.register_claim(
            "c1",
            cv.MeasurableClaim(
                kpi="roas", operator="ge", threshold=1.5,
            ),
            fulfillment_ts=1000.0,
        )
        return v

    def test_verified(self) -> None:
        v = self._setup([1.6, 1.7, 1.8])
        result = v.verify("c1")
        self.assertEqual(result.verdict, "verified")
        self.assertAlmostEqual(result.observed_value, 1.7)

    def test_unfulfilled(self) -> None:
        v = self._setup([1.1, 1.2, 1.0])
        result = v.verify("c1")
        self.assertEqual(result.verdict, "unfulfilled")

    def test_inconclusive_no_samples(self) -> None:
        v = self._setup([])
        result = v.verify("c1")
        self.assertEqual(result.verdict, "inconclusive")
        self.assertEqual(result.observed_samples, 0)

    def test_inconclusive_too_few_samples(self) -> None:
        v = cv.CommitmentVerifier(
            measurement_fn=lambda k, f, t: [1.9],
            min_samples=3,
        )
        v.register_claim(
            "c1",
            cv.MeasurableClaim(
                kpi="roas", operator="ge", threshold=1.5,
            ),
            fulfillment_ts=1000.0,
        )
        result = v.verify("c1")
        self.assertEqual(result.verdict, "inconclusive")


class TestMeasurementException(unittest.TestCase):
    def test_raising_measurement_fn_inconclusive(self) -> None:
        def boom(k, f, t):
            raise RuntimeError("x")

        v = cv.CommitmentVerifier(measurement_fn=boom)
        v.register_claim(
            "c1",
            cv.MeasurableClaim(
                kpi="roas", operator="ge", threshold=1.5,
            ),
            fulfillment_ts=1000.0,
        )
        result = v.verify("c1")
        self.assertEqual(result.verdict, "inconclusive")


class TestVerifyAll(unittest.TestCase):
    def test_all_claims_checked(self) -> None:
        v = cv.CommitmentVerifier(
            measurement_fn=lambda k, f, t: [1.6, 1.7],
        )
        v.register_claim(
            "c1",
            cv.MeasurableClaim("roas", "ge", 1.5),
            fulfillment_ts=1000.0,
        )
        v.register_claim(
            "c2",
            cv.MeasurableClaim("cpa", "le", 20),
            fulfillment_ts=1000.0,
        )
        results = v.verify_all()
        self.assertEqual(len(results), 2)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        v = cv.CommitmentVerifier()
        v.register_claim(
            "c1",
            cv.MeasurableClaim("roas", "ge", 1.5),
            fulfillment_ts=1000.0,
        )
        s = v.stats()
        self.assertEqual(s["registered_claims"], 1)
        self.assertEqual(s["min_samples"], 1)


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        v = cv.CommitmentVerifier(
            measurement_fn=lambda k, f, t: [1.6],
        )
        v.register_claim(
            "c1",
            cv.MeasurableClaim("roas", "ge", 1.5),
            fulfillment_ts=1000.0,
        )
        d = v.verify("c1").as_dict()
        self.assertIn("verdict", d)
        self.assertIn("observed_value", d)


if __name__ == "__main__":
    unittest.main()
