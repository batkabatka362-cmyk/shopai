"""Curriculum planner tests."""
from __future__ import annotations

import unittest

from core.brain import curriculum_planner as cp


class TestSkillNode(unittest.TestCase):
    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            cp.SkillNode(name="")

    def test_invalid_difficulty_raises(self) -> None:
        with self.assertRaises(ValueError):
            cp.SkillNode(name="x", difficulty=0)


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        self.p = cp.CurriculumPlanner()

    def test_add_and_list(self) -> None:
        self.p.add(cp.SkillNode(name="a"))
        self.p.add(cp.SkillNode(name="b", prerequisites=("a",)))
        names = {s.name for s in self.p.skills()}
        self.assertEqual(names, {"a", "b"})

    def test_duplicate_rejected(self) -> None:
        self.p.add(cp.SkillNode(name="a"))
        with self.assertRaises(ValueError):
            self.p.add(cp.SkillNode(name="a"))

    def test_overwrite_allowed(self) -> None:
        self.p.add(cp.SkillNode(name="a", difficulty=1))
        self.p.add(
            cp.SkillNode(name="a", difficulty=5), overwrite=True,
        )
        self.assertEqual(self.p.skills()[0].difficulty, 5)

    def test_remove(self) -> None:
        self.p.add(cp.SkillNode(name="a"))
        self.assertTrue(self.p.remove("a"))
        self.assertFalse(self.p.remove("a"))


class TestPath(unittest.TestCase):
    def _three_level(self) -> cp.CurriculumPlanner:
        p = cp.CurriculumPlanner()
        p.add(cp.SkillNode(name="basics"))
        p.add(cp.SkillNode(
            name="intermediate", prerequisites=("basics",),
        ))
        p.add(cp.SkillNode(
            name="advanced", prerequisites=("intermediate",),
        ))
        return p

    def test_topological_order(self) -> None:
        path = self._three_level().path_to("advanced")
        self.assertEqual(
            path.ordered,
            ["basics", "intermediate", "advanced"],
        )

    def test_unknown_goal(self) -> None:
        path = self._three_level().path_to("nobody")
        self.assertEqual(path.unreachable, ["nobody"])
        self.assertEqual(path.ordered, [])

    def test_cycle_detected(self) -> None:
        p = cp.CurriculumPlanner()
        p.add(cp.SkillNode(name="a", prerequisites=("b",)))
        p.add(cp.SkillNode(name="b", prerequisites=("a",)))
        path = p.path_to("a")
        self.assertTrue(path.cycle)

    def test_unknown_prerequisite(self) -> None:
        p = cp.CurriculumPlanner()
        p.add(cp.SkillNode(
            name="a", prerequisites=("missing",),
        ))
        path = p.path_to("a")
        self.assertIn("missing", path.unreachable)

    def test_difficulty_ties_break(self) -> None:
        p = cp.CurriculumPlanner()
        p.add(cp.SkillNode(name="a", difficulty=5))
        p.add(cp.SkillNode(name="b", difficulty=1))
        p.add(cp.SkillNode(
            name="goal", prerequisites=("a", "b"),
        ))
        path = p.path_to("goal")
        # Easy-first within same depth — b before a
        self.assertLess(
            path.ordered.index("b"), path.ordered.index("a"),
        )


class TestNextSkill(unittest.TestCase):
    def test_returns_basics_when_nothing_mastered(self) -> None:
        p = cp.CurriculumPlanner(mastery_fn=lambda n: False)
        p.add(cp.SkillNode(name="basics"))
        p.add(cp.SkillNode(
            name="intermediate", prerequisites=("basics",),
        ))
        rep = p.next_skill()
        self.assertEqual(rep.recommended, "basics")

    def test_returns_intermediate_when_basics_mastered(self) -> None:
        mastered = {"basics"}
        p = cp.CurriculumPlanner(mastery_fn=lambda n: n in mastered)
        p.add(cp.SkillNode(name="basics"))
        p.add(cp.SkillNode(
            name="intermediate", prerequisites=("basics",),
        ))
        p.add(cp.SkillNode(
            name="advanced", prerequisites=("intermediate",),
        ))
        rep = p.next_skill()
        self.assertEqual(rep.recommended, "intermediate")

    def test_none_when_all_mastered(self) -> None:
        p = cp.CurriculumPlanner(mastery_fn=lambda n: True)
        p.add(cp.SkillNode(name="a"))
        rep = p.next_skill()
        self.assertIsNone(rep.recommended)
        self.assertIn("no skill", rep.why)

    def test_goal_restricts_candidates(self) -> None:
        # Include a skill outside the goal's ancestry — should be ignored
        p = cp.CurriculumPlanner(mastery_fn=lambda n: False)
        p.add(cp.SkillNode(name="basics"))
        p.add(cp.SkillNode(
            name="intermediate", prerequisites=("basics",),
        ))
        p.add(cp.SkillNode(name="unrelated"))   # not in ancestry
        rep = p.next_skill(goal="intermediate")
        self.assertEqual(rep.recommended, "basics")

    def test_mastery_fn_exception_defaults_false(self) -> None:
        def boom(_n):
            raise RuntimeError("x")

        p = cp.CurriculumPlanner(mastery_fn=boom)
        p.add(cp.SkillNode(name="a"))
        rep = p.next_skill()
        # Nothing mastered → recommend the single skill
        self.assertEqual(rep.recommended, "a")

    def test_no_mastery_fn_defaults_false(self) -> None:
        p = cp.CurriculumPlanner()
        p.add(cp.SkillNode(name="a"))
        rep = p.next_skill()
        self.assertEqual(rep.recommended, "a")

    def test_cycle_reported_in_next_skill(self) -> None:
        p = cp.CurriculumPlanner()
        p.add(cp.SkillNode(name="a", prerequisites=("b",)))
        p.add(cp.SkillNode(name="b", prerequisites=("a",)))
        rep = p.next_skill(goal="a")
        self.assertIsNone(rep.recommended)
        self.assertIn("cycle", rep.why)


class TestStats(unittest.TestCase):
    def test_stats_counts(self) -> None:
        mastered = {"basics"}
        p = cp.CurriculumPlanner(mastery_fn=lambda n: n in mastered)
        p.add(cp.SkillNode(name="basics"))
        p.add(cp.SkillNode(name="adv"))
        s = p.stats()
        self.assertEqual(s["skills"], 2)
        self.assertEqual(s["mastered"], 1)
        self.assertEqual(s["remaining"], 1)


class TestDict(unittest.TestCase):
    def test_path_serialises(self) -> None:
        p = cp.CurriculumPlanner()
        p.add(cp.SkillNode(name="a"))
        d = p.path_to("a").as_dict()
        self.assertIn("ordered", d)
        self.assertIn("cycle", d)

    def test_next_skill_serialises(self) -> None:
        p = cp.CurriculumPlanner()
        p.add(cp.SkillNode(name="a"))
        d = p.next_skill().as_dict()
        self.assertIn("recommended", d)
        self.assertIn("why", d)


if __name__ == "__main__":
    unittest.main()
