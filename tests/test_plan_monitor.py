"""Plan monitor tests."""
from __future__ import annotations

import time
import unittest

from core.brain import plan_monitor as pm


class TestExpectedStep(unittest.TestCase):
    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            pm.ExpectedStep(name="")

    def test_negative_duration_raises(self) -> None:
        with self.assertRaises(ValueError):
            pm.ExpectedStep(name="x", expected_duration_s=-1)


class TestStart(unittest.TestCase):
    def test_start_requires_plan_id(self) -> None:
        m = pm.PlanMonitor()
        with self.assertRaises(ValueError):
            m.start("", [pm.ExpectedStep(name="a")])

    def test_start_requires_steps(self) -> None:
        m = pm.PlanMonitor()
        with self.assertRaises(ValueError):
            m.start("p", [])

    def test_invalid_deadline_raises(self) -> None:
        m = pm.PlanMonitor()
        with self.assertRaises(ValueError):
            m.start("p", [pm.ExpectedStep(name="a")], deadline_s=-1)

    def test_duplicate_plan_raises(self) -> None:
        m = pm.PlanMonitor()
        m.start("p", [pm.ExpectedStep(name="a")])
        with self.assertRaises(ValueError):
            m.start("p", [pm.ExpectedStep(name="a")])

    def test_cancel(self) -> None:
        m = pm.PlanMonitor()
        m.start("p", [pm.ExpectedStep(name="a")])
        self.assertTrue(m.cancel("p"))
        self.assertFalse(m.cancel("p"))


class TestRecordStep(unittest.TestCase):
    def test_record_unknown_plan_raises(self) -> None:
        m = pm.PlanMonitor()
        with self.assertRaises(ValueError):
            m.record_step("nope", "step", duration_s=1, state_after={})

    def test_record_negative_duration_raises(self) -> None:
        m = pm.PlanMonitor()
        m.start("p", [pm.ExpectedStep(name="a")])
        with self.assertRaises(ValueError):
            m.record_step("p", "a", duration_s=-1, state_after={})

    def test_ok_status_when_all_clean(self) -> None:
        m = pm.PlanMonitor()
        m.start(
            "p",
            [pm.ExpectedStep(
                name="a", expected_duration_s=10.0,
                expected_state_after={"x": 1},
            )],
        )
        v = m.record_step(
            "p", "a", duration_s=5, state_after={"x": 1},
        )
        self.assertEqual(v.status, "ok")


class TestDurationRatio(unittest.TestCase):
    def test_duration_over_2x_warn(self) -> None:
        m = pm.PlanMonitor()
        m.start(
            "p",
            [pm.ExpectedStep(
                name="a", expected_duration_s=1.0,
            )],
        )
        v = m.record_step(
            "p", "a", duration_s=3.0, state_after={},
        )
        self.assertEqual(v.status, "warn")

    def test_duration_over_5x_abort(self) -> None:
        m = pm.PlanMonitor()
        m.start(
            "p",
            [pm.ExpectedStep(
                name="a", expected_duration_s=1.0,
            )],
        )
        v = m.record_step(
            "p", "a", duration_s=10.0, state_after={},
        )
        self.assertEqual(v.status, "abort")
        self.assertTrue(any("duration" in vv for vv in v.violations))


class TestForbiddenMutation(unittest.TestCase):
    def test_forbidden_key_changed_aborts(self) -> None:
        m = pm.PlanMonitor()
        m.start(
            "p",
            [pm.ExpectedStep(
                name="a",
                forbidden_state_changes=("currency",),
            )],
            initial_state={"currency": "USD"},
        )
        v = m.record_step(
            "p", "a", duration_s=0.1,
            state_after={"currency": "EUR"},
        )
        self.assertEqual(v.status, "abort")
        self.assertTrue(
            any("currency" in vv for vv in v.violations),
        )


class TestExpectedStateAfter(unittest.TestCase):
    def test_mismatch_warns(self) -> None:
        m = pm.PlanMonitor()
        m.start(
            "p",
            [pm.ExpectedStep(
                name="a",
                expected_state_after={"published": True},
            )],
        )
        v = m.record_step(
            "p", "a", duration_s=0.1,
            state_after={"published": False},
        )
        self.assertEqual(v.status, "warn")
        self.assertTrue(
            any("published" in vv for vv in v.violations),
        )


class TestInvariants(unittest.TestCase):
    def test_failing_invariant_aborts(self) -> None:
        m = pm.PlanMonitor()
        m.start(
            "p",
            [pm.ExpectedStep(
                name="a",
                invariants=(lambda s: s.get("inventory", 0) >= 0,),
                invariant_names=("inventory_non_negative",),
            )],
        )
        v = m.record_step(
            "p", "a", duration_s=0.1,
            state_after={"inventory": -1},
        )
        self.assertEqual(v.status, "abort")
        self.assertIn("invariant:inventory_non_negative", v.violations)

    def test_raising_invariant_aborts(self) -> None:
        def boom(_):
            raise RuntimeError("x")

        m = pm.PlanMonitor()
        m.start(
            "p",
            [pm.ExpectedStep(
                name="a",
                invariants=(boom,),
                invariant_names=("boom_inv",),
            )],
        )
        v = m.record_step(
            "p", "a", duration_s=0.1, state_after={},
        )
        self.assertEqual(v.status, "abort")


class TestDeadline(unittest.TestCase):
    def test_past_deadline_aborts(self) -> None:
        m = pm.PlanMonitor()
        m.start(
            "p",
            [pm.ExpectedStep(name="a")],
            deadline_s=0.01,
        )
        time.sleep(0.02)
        v = m.record_step("p", "a", duration_s=0.1, state_after={})
        self.assertEqual(v.status, "abort")
        self.assertTrue(
            any("deadline breached" in vv for vv in v.violations),
        )


class TestUnknownStep(unittest.TestCase):
    def test_off_schedule_step_warns(self) -> None:
        m = pm.PlanMonitor()
        m.start("p", [pm.ExpectedStep(name="a")])
        v = m.record_step("p", "surprise", duration_s=0.1, state_after={})
        self.assertEqual(v.status, "warn")
        self.assertTrue(
            any("not in plan" in n for n in v.notes),
        )


class TestSnapshotFinish(unittest.TestCase):
    def test_snapshot_has_total_duration(self) -> None:
        m = pm.PlanMonitor()
        m.start(
            "p",
            [pm.ExpectedStep(
                name="a", expected_duration_s=1.0,
            )],
        )
        snap = m.snapshot("p")
        self.assertEqual(snap.expected_total_s, 1.0)

    def test_finish_removes_plan(self) -> None:
        m = pm.PlanMonitor()
        m.start("p", [pm.ExpectedStep(name="a")])
        snap = m.finish("p")
        self.assertIsNotNone(snap)
        self.assertFalse(m.is_active("p"))


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        m = pm.PlanMonitor()
        m.start("p", [pm.ExpectedStep(name="a")])
        s = m.stats()
        self.assertEqual(s["active_plans"], 1)
        self.assertIn("p", s["plans"])


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        m = pm.PlanMonitor()
        m.start("p", [pm.ExpectedStep(name="a")])
        v = m.record_step("p", "a", duration_s=0.1, state_after={})
        self.assertIn("status", v.as_dict())
        self.assertIn("plan_id", m.snapshot("p").as_dict())


if __name__ == "__main__":
    unittest.main()
