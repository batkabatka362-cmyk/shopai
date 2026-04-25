"""Skill composer tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import skill_composer as sc


class _FakeSkillLibrary:
    """Deterministic in-memory stand-in for SkillLibrary.run()."""

    def __init__(self, results: dict[str, dict]):
        self._results = results
        self.calls: list[tuple[str, dict]] = []

    def run(self, name, context):
        self.calls.append((name, dict(context)))
        return dict(self._results.get(name, {"status": "ok", "success": True}))


class TestSetup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def composer(self, results: dict | None = None) -> sc.SkillComposer:
        lib = _FakeSkillLibrary(results or {})
        comp = sc.SkillComposer(
            db_path=Path(self._tmp.name) / "c.db",
            skill_library=lib,
        )
        comp._fake_lib = lib   # for assertions
        return comp


class TestRegister(TestSetup):
    def test_register_and_get(self) -> None:
        c = self.composer()
        m = sc.MacroSkill(
            name="launch", kind="sequence",
            steps=[sc.MacroStep(skill="ingest")],
        )
        c.register(m)
        self.assertIs(c.get("launch"), m)

    def test_blank_name_raises(self) -> None:
        c = self.composer()
        with self.assertRaises(ValueError):
            c.register(sc.MacroSkill(
                name="", kind="sequence",
                steps=[sc.MacroStep(skill="x")],
            ))

    def test_bad_kind_raises(self) -> None:
        c = self.composer()
        with self.assertRaises(ValueError):
            c.register(sc.MacroSkill(
                name="m", kind="random",       # type: ignore
                steps=[sc.MacroStep(skill="x")],
            ))

    def test_no_steps_raises(self) -> None:
        c = self.composer()
        with self.assertRaises(ValueError):
            c.register(sc.MacroSkill(
                name="m", kind="sequence", steps=[],
            ))

    def test_duplicate_rejected(self) -> None:
        c = self.composer()
        m = sc.MacroSkill(
            name="m", kind="sequence",
            steps=[sc.MacroStep(skill="x")],
        )
        c.register(m)
        with self.assertRaises(ValueError):
            c.register(m)


class TestSequence(TestSetup):
    def test_all_succeed(self) -> None:
        c = self.composer(results={
            "a": {"status": "ok", "success": True,
                   "output": {"a_done": True}},
            "b": {"status": "ok", "success": True},
        })
        c.register(sc.MacroSkill(
            name="m", kind="sequence",
            steps=[sc.MacroStep("a"), sc.MacroStep("b")],
        ))
        rep = c.run("m", context={"seed": 1})
        self.assertTrue(rep.success)
        self.assertEqual([s.skill for s in rep.steps], ["a", "b"])
        # b should see a's output merged into context
        second_call_ctx = c._fake_lib.calls[1][1]
        self.assertTrue(second_call_ctx.get("a_done"))

    def test_fail_fast_on_hard_step(self) -> None:
        c = self.composer(results={
            "a": {"status": "ok", "success": True},
            "bad": {"status": "failed", "success": False,
                     "error": "nope"},
            "c": {"status": "ok", "success": True},
        })
        c.register(sc.MacroSkill(
            name="m", kind="sequence",
            steps=[
                sc.MacroStep("a"),
                sc.MacroStep("bad"),
                sc.MacroStep("c"),
            ],
        ))
        rep = c.run("m")
        self.assertFalse(rep.success)
        self.assertEqual(len(rep.steps), 2)  # c never ran

    def test_optional_step_failure_does_not_block(self) -> None:
        c = self.composer(results={
            "a": {"status": "ok", "success": True},
            "opt": {"status": "failed", "success": False},
            "c": {"status": "ok", "success": True},
        })
        c.register(sc.MacroSkill(
            name="m", kind="sequence",
            steps=[
                sc.MacroStep("a"),
                sc.MacroStep("opt", optional=True),
                sc.MacroStep("c"),
            ],
        ))
        rep = c.run("m")
        self.assertTrue(rep.success)
        self.assertEqual(len(rep.steps), 3)


class TestFallback(TestSetup):
    def test_first_success_wins(self) -> None:
        c = self.composer(results={
            "try1": {"status": "failed", "success": False},
            "try2": {"status": "ok", "success": True},
            "try3": {"status": "ok", "success": True},
        })
        c.register(sc.MacroSkill(
            name="m", kind="fallback",
            steps=[
                sc.MacroStep("try1"),
                sc.MacroStep("try2"),
                sc.MacroStep("try3"),
            ],
        ))
        rep = c.run("m")
        self.assertTrue(rep.success)
        self.assertEqual(len(rep.steps), 2)  # try3 never ran

    def test_all_fail_macro_fails(self) -> None:
        c = self.composer(results={
            "a": {"status": "failed", "success": False},
            "b": {"status": "failed", "success": False},
        })
        c.register(sc.MacroSkill(
            name="m", kind="fallback",
            steps=[sc.MacroStep("a"), sc.MacroStep("b")],
        ))
        rep = c.run("m")
        self.assertFalse(rep.success)


class TestParallel(TestSetup):
    def test_all_succeed(self) -> None:
        c = self.composer(results={
            "a": {"status": "ok", "success": True},
            "b": {"status": "ok", "success": True},
        })
        c.register(sc.MacroSkill(
            name="m", kind="parallel",
            steps=[sc.MacroStep("a"), sc.MacroStep("b")],
        ))
        rep = c.run("m")
        self.assertTrue(rep.success)

    def test_any_required_failure_fails_macro(self) -> None:
        c = self.composer(results={
            "a": {"status": "ok", "success": True},
            "b": {"status": "failed", "success": False},
        })
        c.register(sc.MacroSkill(
            name="m", kind="parallel",
            steps=[sc.MacroStep("a"), sc.MacroStep("b")],
        ))
        rep = c.run("m")
        self.assertFalse(rep.success)

    def test_parallel_with_optional_failure(self) -> None:
        c = self.composer(results={
            "a": {"status": "ok", "success": True},
            "b": {"status": "failed", "success": False},
        })
        c.register(sc.MacroSkill(
            name="m", kind="parallel",
            steps=[sc.MacroStep("a"), sc.MacroStep("b", optional=True)],
        ))
        rep = c.run("m")
        self.assertTrue(rep.success)


class TestPrepare(TestSetup):
    def test_prepare_mutates_context(self) -> None:
        c = self.composer(results={
            "a": {"status": "ok", "success": True},
        })
        c.register(sc.MacroSkill(
            name="m", kind="sequence",
            steps=[
                sc.MacroStep(
                    "a",
                    prepare=lambda ctx: {**ctx, "prepared": True},
                ),
            ],
        ))
        c.run("m", context={})
        self.assertTrue(c._fake_lib.calls[0][1].get("prepared"))

    def test_prepare_raising_falls_back(self) -> None:
        def bad(_):
            raise RuntimeError("x")
        c = self.composer(results={
            "a": {"status": "ok", "success": True},
        })
        c.register(sc.MacroSkill(
            name="m", kind="sequence",
            steps=[sc.MacroStep("a", prepare=bad)],
        ))
        rep = c.run("m")
        self.assertTrue(rep.success)


class TestSkillRaises(TestSetup):
    def test_skill_run_raising_treated_as_failure(self) -> None:
        class Boomy:
            def run(self, name, ctx):
                raise RuntimeError("boom")

        comp = sc.SkillComposer(
            db_path=Path(self._tmp.name) / "boom.db",
            skill_library=Boomy(),
        )
        comp.register(sc.MacroSkill(
            name="m", kind="sequence",
            steps=[sc.MacroStep("a")],
        ))
        rep = comp.run("m")
        self.assertFalse(rep.success)
        self.assertEqual(rep.steps[0].error, "boom")


class TestStats(TestSetup):
    def test_outcome_recorded(self) -> None:
        c = self.composer(results={
            "a": {"status": "ok", "success": True},
        })
        c.register(sc.MacroSkill(
            name="m", kind="sequence",
            steps=[sc.MacroStep("a")],
        ))
        c.run("m")
        c.run("m")
        s = c.stats("m")
        self.assertEqual(s["uses"], 2)
        self.assertEqual(s["wins"], 2)

    def test_rank_sorts_by_wins_times_rate(self) -> None:
        c = self.composer(results={
            "a": {"status": "ok", "success": True},
            "b": {"status": "failed", "success": False},
        })
        c.register(sc.MacroSkill(
            name="hot", kind="sequence",
            steps=[sc.MacroStep("a")],
        ))
        c.register(sc.MacroSkill(
            name="cold", kind="sequence",
            steps=[sc.MacroStep("b")],
        ))
        for _ in range(5):
            c.run("hot")
        for _ in range(5):
            c.run("cold")
        ranked = c.rank(min_support=3)
        self.assertEqual(ranked[0]["name"], "hot")


class TestUnknown(TestSetup):
    def test_unknown_macro_returns_unsuccess(self) -> None:
        c = self.composer()
        rep = c.run("nobody")
        self.assertFalse(rep.success)


class TestDict(TestSetup):
    def test_macro_and_report_serialise(self) -> None:
        c = self.composer(results={
            "a": {"status": "ok", "success": True},
        })
        m = sc.MacroSkill(
            name="m", kind="sequence",
            steps=[sc.MacroStep("a")],
            description="demo", tags=("t",),
        )
        c.register(m)
        rep = c.run("m")
        self.assertIn("name", m.as_dict())
        self.assertIn("steps", rep.as_dict())


if __name__ == "__main__":
    unittest.main()
