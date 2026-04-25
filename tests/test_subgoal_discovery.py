"""Subgoal discovery tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import subgoal_discovery as sg


def _trace(
    tid: str, kinds: list[str], succeeded: bool = True,
) -> sg.Trace:
    return sg.Trace(
        trace_id=tid,
        steps=[sg.Step(kind=k) for k in kinds],
        succeeded=succeeded,
    )


class TestCanonical(unittest.TestCase):
    def test_step_canonical_deterministic(self) -> None:
        a = sg.Step(kind="launch", params={"x": 1, "y": 2})
        b = sg.Step(kind="launch", params={"y": 2, "x": 1})
        self.assertEqual(a.canonical(), b.canonical())

    def test_different_params_different_canonical(self) -> None:
        a = sg.Step(kind="launch", params={"x": 1})
        b = sg.Step(kind="launch", params={"x": 2})
        self.assertNotEqual(a.canonical(), b.canonical())


class TestDiscover(unittest.TestCase):
    def test_common_pair_surfaces(self) -> None:
        traces = [
            _trace("t1", ["launch", "wait", "kill"]),
            _trace("t2", ["launch", "wait", "scale"]),
            _trace("t3", ["launch", "wait", "hold"]),
            _trace("t4", ["launch", "wait", "wait"]),
        ]
        candidates = sg.discover(traces, min_support=3)
        sigs = [tuple(x[0]) for x in candidates]
        # The pair (launch, wait) appears in all 4 traces.
        self.assertTrue(
            any(len(s) == 2 and s[0].startswith("launch") for s in sigs),
        )

    def test_rare_sequence_skipped(self) -> None:
        traces = [
            _trace("t1", ["a", "b"]),
            _trace("t2", ["c", "d"]),
            _trace("t3", ["e", "f"]),
        ]
        candidates = sg.discover(traces, min_support=3)
        self.assertEqual(candidates, [])

    def test_failing_traces_drop_win_rate(self) -> None:
        traces = [
            _trace("t1", ["a", "b"], succeeded=False),
            _trace("t2", ["a", "b"], succeeded=False),
            _trace("t3", ["a", "b"], succeeded=False),
        ]
        # win_rate = 0 < 0.5 → filtered
        self.assertEqual(sg.discover(traces, min_support=3), [])

    def test_dedup_within_trace(self) -> None:
        # Same trace repeated pattern shouldn't inflate support
        traces = [
            _trace("t1", ["a", "b", "a", "b"]),
            _trace("t2", ["c", "d"]),
            _trace("t3", ["e", "f"]),
        ]
        candidates = sg.discover(traces, min_support=2)
        ab_support = next(
            (s for sig, s, _ in candidates
             if len(sig) == 2 and sig[0].startswith("a")),
            None,
        )
        # (a, b) only appears in t1 → support = 1, below min 2
        self.assertIsNone(ab_support)

    def test_max_len_truncates(self) -> None:
        traces = [
            _trace("t1", ["a", "b", "c", "d", "e"]),
            _trace("t2", ["a", "b", "c", "d", "e"]),
            _trace("t3", ["a", "b", "c", "d", "e"]),
        ]
        candidates = sg.discover(traces, min_support=3, max_len=2)
        max_found = max(len(sig) for sig, *_ in candidates)
        self.assertLessEqual(max_found, 2)


class TestLibrary(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.lib = sg.SubgoalLibrary(Path(self._tmp.name) / "s.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_promote_then_get(self) -> None:
        pattern = [sg.Step(kind="launch"), sg.Step(kind="wait")]
        s = self.lib.promote(pattern, support=5, win_rate=0.8)
        fetched = self.lib.get(s.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.support, 5)

    def test_promote_is_idempotent_on_signature(self) -> None:
        pattern = [sg.Step(kind="launch"), sg.Step(kind="wait")]
        a = self.lib.promote(pattern, support=5, win_rate=0.8)
        b = self.lib.promote(pattern, support=7, win_rate=0.9)
        self.assertEqual(a.id, b.id)
        # Latest values take effect.
        self.assertEqual(b.support, 7)
        self.assertEqual(self.lib.size(), 1)

    def test_record_application_updates_counts(self) -> None:
        s = self.lib.promote(
            [sg.Step(kind="x")], support=3, win_rate=0.6,
        )
        self.lib.record_application(s.id, success=True)
        self.lib.record_application(s.id, success=False)
        fetched = self.lib.get(s.id)
        self.assertEqual(fetched.applications, 2)
        self.assertEqual(fetched.successes, 1)

    def test_top_returns_highest_support(self) -> None:
        self.lib.promote(
            [sg.Step(kind="a")], support=10, win_rate=0.8,
        )
        self.lib.promote(
            [sg.Step(kind="b")], support=3, win_rate=0.9,
        )
        top = self.lib.top(k=1)
        self.assertEqual(top[0].pattern[0].kind, "a")


class TestOneShot(unittest.TestCase):
    def test_discover_and_promote_populates_library(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        lib = sg.SubgoalLibrary(Path(tmp.name) / "s.db")
        traces = [
            _trace("t1", ["launch", "wait"]),
            _trace("t2", ["launch", "wait"]),
            _trace("t3", ["launch", "wait"]),
        ]
        n = sg.discover_and_promote(
            traces, lib, min_support=3, min_len=2, max_len=2,
        )
        self.assertGreaterEqual(n, 1)
        self.assertGreaterEqual(lib.size(), 1)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
