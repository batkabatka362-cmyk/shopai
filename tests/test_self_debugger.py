"""Self-debugger tests."""
from __future__ import annotations

import unittest

from core.brain import self_debugger as sd


class TestFingerprint(unittest.TestCase):
    def test_strips_numeric_noise(self) -> None:
        fp1 = sd._fingerprint("HTTP 429 at 2026-04-19 14:22:01")
        fp2 = sd._fingerprint("HTTP 429 at 2026-04-19 14:25:33")
        self.assertEqual(fp1, fp2)

    def test_strips_hex_ids(self) -> None:
        fp = sd._fingerprint("request id aabbcc112233 failed")
        self.assertNotIn("aabbcc112233", fp)

    def test_truncated_to_bound(self) -> None:
        fp = sd._fingerprint("x" * 500)
        self.assertLessEqual(len(fp), 180)


class TestConfig(unittest.TestCase):
    def test_bad_threshold_raises(self) -> None:
        with self.assertRaises(ValueError):
            sd.SelfDebugger(repeat_threshold=1)

    def test_rule_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            sd.DiagnosticRule(
                name="", match=lambda c: True, hypothesis="x",
            )


class TestNote(unittest.TestCase):
    def test_first_failure_no_case(self) -> None:
        d = sd.SelfDebugger()
        self.assertIsNone(d.note("fetch", "HTTP 429"))

    def test_threshold_emits_case(self) -> None:
        d = sd.SelfDebugger(repeat_threshold=3)
        # Three errors with same fingerprint class (only the ids differ).
        self.assertIsNone(d.note("fetch", "HTTP 429 request 1111"))
        self.assertIsNone(d.note("fetch", "HTTP 429 request 2222"))
        case = d.note("fetch", "HTTP 429 request 3333")
        self.assertIsNotNone(case)
        self.assertEqual(case.phase, "fetch")
        self.assertGreaterEqual(case.repeat_count, 3)

    def test_different_fingerprints_independent(self) -> None:
        d = sd.SelfDebugger(repeat_threshold=2)
        d.note("fetch", "HTTP 429")
        # Completely different error → fresh streak
        self.assertIsNone(d.note("fetch", "KeyError 'abc'"))

    def test_blank_phase_raises(self) -> None:
        d = sd.SelfDebugger()
        with self.assertRaises(ValueError):
            d.note("", "x")


class TestReset(unittest.TestCase):
    def test_reset_all(self) -> None:
        d = sd.SelfDebugger()
        d.note("a", "x")
        d.note("b", "y")
        n = d.reset()
        self.assertEqual(n, 2)
        self.assertEqual(d.stats()["active_streaks"], 0)

    def test_reset_single_phase(self) -> None:
        d = sd.SelfDebugger()
        d.note("a", "x")
        d.note("b", "y")
        self.assertEqual(d.reset(phase="a"), 1)
        self.assertEqual(d.stats()["active_streaks"], 1)


class TestDefaultRules(unittest.TestCase):
    def setUp(self) -> None:
        self.d = sd.SelfDebugger(repeat_threshold=2)
        self.d.register_defaults()

    def _case(self, phase: str, err: str) -> sd.FailureCase:
        self.d.note(phase, err)
        return self.d.note(phase, err)   # second call crosses threshold

    def test_rate_limit_rule(self) -> None:
        case = self._case("ads", "HTTP 429 Too Many Requests")
        diag = self.d.diagnose(case)
        self.assertIsNotNone(diag)
        self.assertEqual(diag.rule, "rate_limit")
        self.assertEqual(diag.remedy, "backoff_and_retry")

    def test_unauthorized_rule(self) -> None:
        case = self._case("shopify", "HTTP 401 Unauthorized token expired")
        diag = self.d.diagnose(case)
        self.assertEqual(diag.rule, "unauthorized")
        self.assertEqual(diag.remedy, "oauth_refresh")

    def test_schema_drift_rule(self) -> None:
        case = self._case(
            "parse", "KeyError missing 'shipping' in payload",
        )
        diag = self.d.diagnose(case)
        self.assertEqual(diag.rule, "schema_drift")

    def test_timeout_rule(self) -> None:
        case = self._case("fetch", "socket timed out after 30s")
        diag = self.d.diagnose(case)
        self.assertEqual(diag.rule, "timeout")

    def test_unmatched_error_no_diag(self) -> None:
        case = self._case("phase", "totally unique cosmic ray bit flip")
        self.assertIsNone(self.d.diagnose(case))


class TestCustomProbe(unittest.TestCase):
    def test_probe_required_true_confirms(self) -> None:
        d = sd.SelfDebugger(repeat_threshold=2)
        d.register(sd.DiagnosticRule(
            name="x",
            match=lambda c: "boom" in c.fingerprint,
            hypothesis="h",
            probe=lambda ctx: ctx.get("verified") is True,
            remedy="r",
        ))
        d.note("p", "boom"); case = d.note("p", "boom")
        diag = d.diagnose(case, probe_context={"verified": True})
        self.assertTrue(diag.confirmed)

    def test_probe_false_unconfirmed(self) -> None:
        d = sd.SelfDebugger(repeat_threshold=2)
        d.register(sd.DiagnosticRule(
            name="x",
            match=lambda c: "boom" in c.fingerprint,
            hypothesis="h",
            probe=lambda ctx: False,
            remedy="r",
        ))
        d.note("p", "boom"); case = d.note("p", "boom")
        diag = d.diagnose(case)
        self.assertFalse(diag.confirmed)

    def test_probe_exception_unconfirmed(self) -> None:
        def boom(_):
            raise RuntimeError("x")

        d = sd.SelfDebugger(repeat_threshold=2)
        d.register(sd.DiagnosticRule(
            name="x",
            match=lambda c: True,
            hypothesis="h", probe=boom, remedy="r",
        ))
        d.note("p", "anything"); case = d.note("p", "anything")
        diag = d.diagnose(case)
        self.assertFalse(diag.confirmed)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        d = sd.SelfDebugger(repeat_threshold=2)
        d.note("p", "x"); d.note("p", "x")
        s = d.stats()
        self.assertEqual(s["active_streaks"], 1)
        self.assertGreaterEqual(s["over_threshold"], 1)


class TestDict(unittest.TestCase):
    def test_case_and_diagnosis_serialise(self) -> None:
        d = sd.SelfDebugger(repeat_threshold=2)
        d.register_defaults()
        d.note("p", "HTTP 429"); case = d.note("p", "HTTP 429")
        diag = d.diagnose(case)
        self.assertIn("rule", diag.as_dict())
        self.assertIn("fingerprint", case.as_dict())


if __name__ == "__main__":
    unittest.main()
