"""Tests for core.crisis.response — LX.4 kill switch."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from core.crisis.response import (
    CrisisEvent,
    CrisisResponder,
    CrisisState,
    get_crisis_responder,
    reset_crisis_responder_for_tests,
)


def _fresh(tmp: tempfile.TemporaryDirectory, **kw) -> CrisisResponder:
    kw.setdefault("window_s", 3600.0)
    kw.setdefault("red_threshold", 2)
    return CrisisResponder(
        db_path=Path(tmp.name) / "crisis.db",
        **kw,
    )


class TestConfig(unittest.TestCase):
    def test_bad_window(self):
        with self.assertRaises(ValueError):
            CrisisResponder(window_s=0)

    def test_bad_threshold(self):
        with self.assertRaises(ValueError):
            CrisisResponder(red_threshold=0)


class TestEventRegistration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cr = _fresh(self._tmp)

    def tearDown(self):
        self.cr.close()
        self._tmp.cleanup()

    def test_blank_kind_raises(self):
        with self.assertRaises(ValueError):
            self.cr.register_event(kind="")

    def test_invalid_severity_raises(self):
        with self.assertRaises(ValueError):
            self.cr.register_event(
                kind="fraud_velocity",
                severity="sky-high",
            )

    def test_event_stored_and_retrieved(self):
        ev = self.cr.register_event(
            kind="chargeback_spike",
            severity="warning",
            note="3 chargebacks in 1h",
            meta={"orders": 3},
        )
        self.assertEqual(ev.kind, "chargeback_spike")
        recent = self.cr.recent_events()
        self.assertEqual(len(recent), 1)
        self.assertEqual(
            recent[0].meta["orders"], 3,
        )


class TestStateTransitions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cr = _fresh(self._tmp, red_threshold=2)
        # Ensure env vars aren't leaking across tests
        os.environ.pop("SHOPAI_EMERGENCY_HALT", None)
        os.environ.pop("SHOPAI_CRISIS_WARN", None)

    def tearDown(self):
        self.cr.close()
        self._tmp.cleanup()
        os.environ.pop("SHOPAI_EMERGENCY_HALT", None)
        os.environ.pop("SHOPAI_CRISIS_WARN", None)

    def test_green_when_quiet(self):
        state = self.cr.detect_state()
        self.assertEqual(state.level, "green")
        self.assertFalse(state.halted)

    def test_yellow_on_single_event(self):
        self.cr.register_event(
            kind="auth_failure_burst", severity="warning",
        )
        state = self.cr.detect_state()
        self.assertEqual(state.level, "yellow")
        self.assertFalse(state.halted)

    def test_red_on_two_events(self):
        self.cr.register_event(kind="auth_failure_burst")
        self.cr.register_event(kind="fraud_velocity")
        state = self.cr.detect_state()
        self.assertEqual(state.level, "red")
        self.assertTrue(state.halted)

    def test_red_on_single_critical(self):
        self.cr.register_event(
            kind="platform_ban", severity="critical",
        )
        state = self.cr.detect_state()
        self.assertEqual(state.level, "red")
        self.assertTrue(state.halted)
        self.assertIn(
            "platform_ban", state.triggered_kinds,
        )

    def test_old_events_expire_from_window(self):
        # Register as if it happened an hour ago
        old_now = time.time() - 2 * 3600.0
        self.cr._now_fn = lambda: old_now
        self.cr.register_event(kind="fraud_velocity")
        self.cr.register_event(kind="auth_failure_burst")
        self.cr._now_fn = time.time
        state = self.cr.detect_state()
        # Outside the 1h window → green again
        self.assertEqual(state.level, "green")

    def test_env_warn_promotes_green_to_yellow(self):
        os.environ["SHOPAI_CRISIS_WARN"] = "1"
        try:
            state = self.cr.detect_state()
            self.assertEqual(state.level, "yellow")
        finally:
            os.environ.pop("SHOPAI_CRISIS_WARN", None)

    def test_env_halt_forces_red(self):
        os.environ["SHOPAI_EMERGENCY_HALT"] = "1"
        try:
            state = self.cr.detect_state()
            self.assertEqual(state.level, "red")
            self.assertTrue(state.halted)
            self.assertIn("kill switch", state.reason)
        finally:
            os.environ.pop(
                "SHOPAI_EMERGENCY_HALT", None,
            )


class TestManualHalt(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cr = _fresh(self._tmp)

    def tearDown(self):
        self.cr.close()
        self._tmp.cleanup()

    def test_halt_sets_red(self):
        self.cr.halt(reason="payment fraud wave")
        state = self.cr.detect_state()
        self.assertEqual(state.level, "red")
        self.assertTrue(state.halted)
        events = self.cr.recent_events()
        self.assertTrue(
            any(
                e.kind == "owner_halt" for e in events
            ),
        )

    def test_resume_returns_to_green(self):
        self.cr.halt()
        self.cr.resume()
        # The halt() call wrote an owner_halt event which can
        # leave us in yellow. Verify not halted:
        state = self.cr.detect_state()
        self.assertFalse(state.halted)

    def test_halt_persists_across_instances(self):
        self.cr.halt()
        self.cr.close()
        cr2 = _fresh(self._tmp)
        try:
            self.assertTrue(cr2.is_halted())
        finally:
            cr2.close()

    def test_is_halted_convenience(self):
        self.assertFalse(self.cr.is_halted())
        self.cr.halt()
        self.assertTrue(self.cr.is_halted())


class TestSingleton(unittest.TestCase):
    def test_singleton_reused(self):
        reset_crisis_responder_for_tests()
        try:
            a = get_crisis_responder()
            b = get_crisis_responder()
            self.assertIs(a, b)
        finally:
            reset_crisis_responder_for_tests()


class TestDiagnostics(unittest.TestCase):
    def test_stats_shape(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            cr = _fresh(tmp)
            cr.register_event(kind="fraud_velocity")
            s = cr.stats()
            self.assertIn("state", s)
            self.assertEqual(s["total_events"], 1)
            self.assertEqual(
                s["state"]["level"], "yellow",
            )
            cr.close()
        finally:
            tmp.cleanup()


class TestDict(unittest.TestCase):
    def test_event_dict(self):
        ev = CrisisEvent(
            id="e1", ts=1.0, kind="fraud_velocity",
            severity="warning", note="x", meta={"a": 1},
        )
        d = ev.as_dict()
        self.assertEqual(d["meta"]["a"], 1)

    def test_state_dict(self):
        s = CrisisState(
            level="red", triggered_kinds=("fraud_velocity",),
            recent_event_count=2, halted=True,
            reason="test",
        )
        d = s.as_dict()
        self.assertEqual(d["level"], "red")


if __name__ == "__main__":
    unittest.main()
