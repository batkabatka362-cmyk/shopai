"""Skill library tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import skill_library as sl


def _kill_recipe(ctx):
    return {"ad_status": "paused"}


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.lib = sl.SkillLibrary(Path(self._tmp.name) / "sk.db")

    def tearDown(self) -> None:
        self.lib.close()
        self._tmp.cleanup()

    def test_register_and_get(self) -> None:
        s = sl.Skill(name="s1", recipe=_kill_recipe)
        self.lib.register(s)
        self.assertIs(self.lib.get("s1"), s)

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.lib.register(sl.Skill(name=""))

    def test_duplicate_rejected(self) -> None:
        self.lib.register(sl.Skill(name="s1"))
        with self.assertRaises(ValueError):
            self.lib.register(sl.Skill(name="s1"))

    def test_overwrite_allowed(self) -> None:
        self.lib.register(sl.Skill(name="s1", description="v1"))
        self.lib.register(
            sl.Skill(name="s1", description="v2"), overwrite=True,
        )
        self.assertEqual(self.lib.get("s1").description, "v2")


class TestPreconditionDSL(unittest.TestCase):
    def test_lt_gt(self) -> None:
        self.assertTrue(sl._check_precondition(
            {"roas": 1.2}, {"roas_lt": 1.5},
        ))
        self.assertFalse(sl._check_precondition(
            {"roas": 2.0}, {"roas_lt": 1.5},
        ))
        self.assertTrue(sl._check_precondition(
            {"age": 5}, {"age_gt": 3},
        ))

    def test_eq(self) -> None:
        self.assertTrue(sl._check_precondition(
            {"status": "active"}, {"status_eq": "active"},
        ))
        self.assertFalse(sl._check_precondition(
            {"status": "paused"}, {"status_eq": "active"},
        ))

    def test_in(self) -> None:
        self.assertTrue(sl._check_precondition(
            {"niche": "audio"},
            {"niche_in": ["audio", "fashion"]},
        ))
        self.assertFalse(sl._check_precondition(
            {"niche": "home"},
            {"niche_in": ["audio", "fashion"]},
        ))

    def test_exists(self) -> None:
        self.assertTrue(sl._check_precondition(
            {"tracking_id": "TRK1"}, {"tracking_id_exists": True},
        ))
        self.assertFalse(sl._check_precondition(
            {}, {"tracking_id_exists": True},
        ))

    def test_missing_field_fails_lt(self) -> None:
        self.assertFalse(sl._check_precondition({}, {"roas_lt": 1.5}))

    def test_plain_key_equality(self) -> None:
        self.assertTrue(sl._check_precondition(
            {"env": "prod"}, {"env": "prod"},
        ))
        self.assertFalse(sl._check_precondition(
            {"env": "dev"}, {"env": "prod"},
        ))

    def test_type_error_is_mismatch(self) -> None:
        # "unparsable" vs numeric threshold should fail cleanly
        self.assertFalse(sl._check_precondition(
            {"x": "not a number"}, {"x_lt": 5},
        ))


class TestCandidates(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.lib = sl.SkillLibrary(Path(self._tmp.name) / "sk.db")
        self.lib.register(sl.Skill(
            name="kill_bad_ad",
            preconditions={"roas_lt": 1.5, "age_gt": 3},
        ))
        self.lib.register(sl.Skill(
            name="scale_winner",
            preconditions={"roas_gt": 3.0},
        ))

    def tearDown(self) -> None:
        self.lib.close()
        self._tmp.cleanup()

    def test_candidates_match_context(self) -> None:
        c = self.lib.candidates({"roas": 1.2, "age": 5})
        names = [s.name for s in c]
        self.assertIn("kill_bad_ad", names)
        self.assertNotIn("scale_winner", names)

    def test_no_match_empty(self) -> None:
        self.assertEqual(
            self.lib.candidates({"roas": 2.0, "age": 1}), [],
        )


class TestBest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.lib = sl.SkillLibrary(Path(self._tmp.name) / "sk.db")
        for n in ("a", "b", "c"):
            self.lib.register(sl.Skill(name=n))

    def tearDown(self) -> None:
        self.lib.close()
        self._tmp.cleanup()

    def test_best_picks_highest_winrate_over_min_support(self) -> None:
        for _ in range(5):
            self.lib.record_outcome("a", success=True)
        for _ in range(5):
            self.lib.record_outcome("b", success=False)
        best = self.lib.best(self.lib.all_skills(), min_support=3)
        self.assertEqual(best.name, "a")

    def test_untested_falls_back_to_exploration(self) -> None:
        # Only 'a' is tested and bad; others get exploration score.
        for _ in range(10):
            self.lib.record_outcome("a", success=False)
        best = self.lib.best(
            self.lib.all_skills(),
            min_support=3, exploration=0.5,
        )
        self.assertIn(best.name, ("b", "c"))


class TestRun(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.lib = sl.SkillLibrary(Path(self._tmp.name) / "sk.db")

    def tearDown(self) -> None:
        self.lib.close()
        self._tmp.cleanup()

    def test_run_records_win(self) -> None:
        self.lib.register(sl.Skill(
            name="kill",
            preconditions={"roas_lt": 1.5},
            recipe=_kill_recipe,
            post_check=lambda c: c.get("ad_status") == "paused",
        ))
        r = self.lib.run("kill", {"roas": 1.2})
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r["success"])
        self.assertEqual(self.lib.stats("kill").wins, 1)

    def test_run_precondition_blocks(self) -> None:
        self.lib.register(sl.Skill(
            name="kill", preconditions={"roas_lt": 1.5},
            recipe=_kill_recipe,
        ))
        r = self.lib.run("kill", {"roas": 2.0})
        self.assertEqual(r["status"], "precondition_failed")
        self.assertEqual(self.lib.stats("kill").uses, 0)

    def test_unknown_skill(self) -> None:
        r = self.lib.run("nope", {})
        self.assertEqual(r["status"], "unknown_skill")

    def test_no_recipe(self) -> None:
        self.lib.register(sl.Skill(name="noop"))
        r = self.lib.run("noop", {})
        self.assertEqual(r["status"], "no_recipe")

    def test_post_check_failure_records_loss(self) -> None:
        self.lib.register(sl.Skill(
            name="try", recipe=_kill_recipe,
            post_check=lambda c: False,
        ))
        self.lib.run("try", {})
        self.assertEqual(self.lib.stats("try").wins, 0)
        self.assertEqual(self.lib.stats("try").uses, 1)

    def test_post_check_raises_counts_as_loss(self) -> None:
        def boom(_):
            raise RuntimeError("bad")

        self.lib.register(sl.Skill(
            name="flaky", recipe=_kill_recipe, post_check=boom,
        ))
        r = self.lib.run("flaky", {})
        self.assertFalse(r["success"])


class TestRank(unittest.TestCase):
    def test_rank_orders_by_support_x_winrate(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        lib = sl.SkillLibrary(Path(tmp.name) / "sk.db")
        for n in ("a", "b", "c"):
            lib.register(sl.Skill(name=n))
        for _ in range(20):
            lib.record_outcome("a", success=True)  # 20 wins
        for _ in range(5):
            lib.record_outcome("b", success=True)  # 5 wins
        for _ in range(10):
            lib.record_outcome("c", success=False)  # 0 wins
        ranked = lib.rank(min_support=3)
        self.assertEqual(ranked[0].name, "a")
        self.assertIn("c", [s.name for s in ranked])
        lib.close()
        tmp.cleanup()


class TestDict(unittest.TestCase):
    def test_skill_as_dict(self) -> None:
        s = sl.Skill(
            name="s", preconditions={"x_lt": 1},
            tags=("t",), description="d",
        )
        d = s.as_dict()
        self.assertEqual(d["name"], "s")
        self.assertEqual(d["tags"], ["t"])

    def test_stats_as_dict(self) -> None:
        d = sl.SkillStats("s", 10, 7, 123.0).as_dict()
        self.assertEqual(d["win_rate"], 0.7)


if __name__ == "__main__":
    unittest.main()
