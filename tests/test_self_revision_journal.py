"""Self-revision journal tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import self_revision_journal as srj


class TestRevisionDataclass(unittest.TestCase):
    def test_bad_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            srj.Revision(
                id="x", kind="bogus",  # type: ignore[arg-type]
                target="y", old_value=None, new_value=None,
                reason="z", evidence_score=0.5,
                status="proposed", ts=0,
            )

    def test_bad_status_raises(self) -> None:
        with self.assertRaises(ValueError):
            srj.Revision(
                id="x", kind="rule", target="y",
                old_value=None, new_value=None,
                reason="z", evidence_score=0.5,
                status="maybe",  # type: ignore[arg-type]
                ts=0,
            )

    def test_bad_evidence_raises(self) -> None:
        with self.assertRaises(ValueError):
            srj.Revision(
                id="x", kind="rule", target="y",
                old_value=None, new_value=None,
                reason="z", evidence_score=2.0,
                status="proposed", ts=0,
            )


class TestSetup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.j = srj.SelfRevisionJournal(
            Path(self._tmp.name) / "j.db",
        )

    def tearDown(self) -> None:
        self.j.close()
        self._tmp.cleanup()


class TestPropose(TestSetup):
    def test_propose_returns_entry(self) -> None:
        rev = self.j.propose(
            kind="rule",
            target="kill_at_roas",
            old_value=1.5, new_value=1.3,
            reason="seen too many false negatives",
            evidence_score=0.8,
        )
        self.assertEqual(rev.status, "proposed")

    def test_blank_target_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.j.propose(
                kind="rule", target="",
                old_value=None, new_value=None,
                reason="x",
            )

    def test_blank_reason_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.j.propose(
                kind="rule", target="x",
                old_value=None, new_value=None,
                reason="",
            )


class TestTransitions(TestSetup):
    def setUp(self) -> None:
        super().setUp()
        self.rev = self.j.propose(
            kind="rule", target="t",
            old_value=1, new_value=2,
            reason="r",
        )

    def test_accept(self) -> None:
        r = self.j.accept(self.rev.id)
        self.assertEqual(r.status, "accepted")
        self.assertIsNotNone(r.resolved_ts)

    def test_reject(self) -> None:
        r = self.j.reject(self.rev.id)
        self.assertEqual(r.status, "rejected")

    def test_mark_applied(self) -> None:
        self.j.accept(self.rev.id)
        r = self.j.mark_applied(self.rev.id)
        self.assertEqual(r.status, "applied")

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.j.accept("never")


class TestQueries(TestSetup):
    def test_by_status(self) -> None:
        r1 = self.j.propose(
            kind="rule", target="a", old_value=1, new_value=2,
            reason="x",
        )
        r2 = self.j.propose(
            kind="rule", target="b", old_value=1, new_value=2,
            reason="x",
        )
        self.j.accept(r1.id)
        accepted = self.j.by_status("accepted")
        proposed = self.j.by_status("proposed")
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(proposed), 1)
        self.assertEqual(accepted[0].id, r1.id)

    def test_by_target(self) -> None:
        self.j.propose(
            kind="rule", target="same_target",
            old_value=1, new_value=2, reason="r",
        )
        self.j.propose(
            kind="knob", target="same_target",
            old_value=1, new_value=2, reason="r",
        )
        same = self.j.by_target("same_target")
        self.assertEqual(len(same), 2)
        rules_only = self.j.by_target("same_target", kind="rule")
        self.assertEqual(len(rules_only), 1)

    def test_recent_newest_first(self) -> None:
        a = self.j.propose(
            kind="rule", target="a",
            old_value=0, new_value=1, reason="r",
        )
        b = self.j.propose(
            kind="rule", target="b",
            old_value=0, new_value=1, reason="r",
        )
        recent = self.j.recent()
        self.assertEqual(recent[0].id, b.id)
        self.assertEqual(recent[1].id, a.id)


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "j.db"
        first = srj.SelfRevisionJournal(path)
        rev = first.propose(
            kind="rule", target="x",
            old_value={"a": 1}, new_value={"a": 2},
            reason="r",
        )
        first.close()
        second = srj.SelfRevisionJournal(path)
        r = second.get(rev.id)
        self.assertIsNotNone(r)
        self.assertEqual(r.new_value, {"a": 2})
        second.close()
        tmp.cleanup()


class TestStats(TestSetup):
    def test_stats_shape(self) -> None:
        r = self.j.propose(
            kind="rule", target="x",
            old_value=1, new_value=2, reason="r",
        )
        self.j.accept(r.id)
        self.j.propose(
            kind="knob", target="y",
            old_value=1, new_value=2, reason="r",
        )
        s = self.j.stats()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["by_status"].get("accepted"), 1)


class TestDict(TestSetup):
    def test_serialises(self) -> None:
        r = self.j.propose(
            kind="rule", target="x",
            old_value="A", new_value="B",
            reason="r",
        )
        d = r.as_dict()
        self.assertEqual(d["new_value"], "B")
        self.assertEqual(d["status"], "proposed")


if __name__ == "__main__":
    unittest.main()
