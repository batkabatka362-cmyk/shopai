"""Skill distiller tests."""
from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any

from core.brain import skill_distiller as sd


@dataclass
class _Case:
    id: str
    situation: dict[str, Any]
    action: str
    outcome_score: float


class _FakeReasoner:
    def __init__(self, cases):
        self._cases = cases

    def _all_cases(self):
        return list(self._cases)


class _FakeLib:
    def __init__(self):
        self.registered = []

    def register(self, skill, overwrite=False):
        for s in self.registered:
            if s.name == skill.name and not overwrite:
                raise ValueError(f"already registered {skill.name}")
        # Replace if overwrite
        self.registered = [
            s for s in self.registered if s.name != skill.name
        ]
        self.registered.append(skill)


class TestDistill(unittest.TestCase):
    def test_clean_winner_distilled(self) -> None:
        cases = [
            _Case(
                f"c{i}",
                {"niche": "audio", "price": 30},
                "scale", 4.0,
            )
            for i in range(5)
        ]
        d = sd.SkillDistiller(case_reasoner=_FakeReasoner(cases))
        report = d.distill(min_support=3, min_score=3.0)
        self.assertEqual(len(report.candidates), 1)
        self.assertEqual(report.candidates[0].action, "scale")

    def test_below_support_not_distilled(self) -> None:
        cases = [
            _Case("c1", {"niche": "audio"}, "scale", 5.0),
        ]
        d = sd.SkillDistiller(case_reasoner=_FakeReasoner(cases))
        report = d.distill(min_support=3)
        self.assertEqual(report.candidates, [])

    def test_below_score_not_distilled(self) -> None:
        cases = [
            _Case(f"c{i}", {"niche": "audio"}, "kill", 1.0)
            for i in range(5)
        ]
        d = sd.SkillDistiller(case_reasoner=_FakeReasoner(cases))
        report = d.distill(min_support=3, min_score=3.0)
        self.assertEqual(report.candidates, [])

    def test_signature_keys_filter(self) -> None:
        cases = [
            _Case(
                f"c{i}",
                {"niche": "audio", "noise_field": f"x{i}"},
                "scale", 4.0,
            )
            for i in range(5)
        ]
        d = sd.SkillDistiller(case_reasoner=_FakeReasoner(cases))
        # Default keys = all → noise_field would split the cases
        # because it differs per case → no clusters of ≥3
        report_no_filter = d.distill(min_support=3)
        self.assertEqual(report_no_filter.candidates, [])
        # With explicit keys, only niche → cases collapse → distilled
        report_filter = d.distill(
            signature_keys=["niche"], min_support=3,
        )
        self.assertEqual(len(report_filter.candidates), 1)

    def test_actions_split_buckets(self) -> None:
        cases = (
            [_Case(f"a{i}", {"x": 1}, "scale", 4.0) for i in range(5)]
            + [_Case(f"b{i}", {"x": 1}, "kill", 4.0) for i in range(3)]
        )
        d = sd.SkillDistiller(case_reasoner=_FakeReasoner(cases))
        report = d.distill(min_support=3)
        actions = {c.action for c in report.candidates}
        self.assertEqual(actions, {"scale", "kill"})

    def test_blank_action_skipped(self) -> None:
        cases = [
            _Case(f"c{i}", {"x": 1}, "", 5.0)
            for i in range(5)
        ]
        d = sd.SkillDistiller(case_reasoner=_FakeReasoner(cases))
        self.assertEqual(d.distill(min_support=3).candidates, [])

    def test_min_support_lt_2_raises(self) -> None:
        d = sd.SkillDistiller(case_reasoner=_FakeReasoner([]))
        with self.assertRaises(ValueError):
            d.distill(min_support=1)


class TestPromote(unittest.TestCase):
    def test_promote_registers(self) -> None:
        cases = [
            _Case(f"c{i}", {"niche": "audio"}, "scale", 4.0)
            for i in range(5)
        ]
        lib = _FakeLib()
        d = sd.SkillDistiller(
            case_reasoner=_FakeReasoner(cases),
            skill_library=lib,
        )
        report = d.distill(min_support=3)
        n = d.promote_all(report)
        self.assertEqual(n, 1)
        self.assertEqual(len(lib.registered), 1)
        self.assertIn("distilled.scale", lib.registered[0].name)

    def test_promote_idempotent(self) -> None:
        cases = [
            _Case(f"c{i}", {"x": "y"}, "scale", 5.0)
            for i in range(5)
        ]
        lib = _FakeLib()
        d = sd.SkillDistiller(
            case_reasoner=_FakeReasoner(cases),
            skill_library=lib,
        )
        report = d.distill(min_support=3)
        d.promote_all(report)
        # Re-promoting the same report without overwrite should
        # silently skip duplicates.
        n2 = d.promote_all(report)
        self.assertEqual(n2, 0)
        self.assertEqual(len(lib.registered), 1)

    def test_promote_overwrite(self) -> None:
        cases = [
            _Case(f"c{i}", {"x": "y"}, "scale", 5.0)
            for i in range(5)
        ]
        lib = _FakeLib()
        d = sd.SkillDistiller(
            case_reasoner=_FakeReasoner(cases),
            skill_library=lib,
        )
        report = d.distill(min_support=3)
        d.promote_all(report)
        n2 = d.promote_all(report, overwrite=True)
        self.assertEqual(n2, 1)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        cases = [
            _Case(f"c{i}", {"x": 1}, "scale", 4.0)
            for i in range(3)
        ]
        d = sd.SkillDistiller(case_reasoner=_FakeReasoner(cases))
        s = d.stats()
        self.assertEqual(s["case_count"], 3)


class TestDict(unittest.TestCase):
    def test_report_serialises(self) -> None:
        cases = [
            _Case(f"c{i}", {"x": 1}, "scale", 4.0)
            for i in range(5)
        ]
        d = sd.SkillDistiller(case_reasoner=_FakeReasoner(cases))
        rep = d.distill(min_support=3)
        rd = rep.as_dict()
        self.assertIn("candidates", rd)
        self.assertIn("inspected", rd)


if __name__ == "__main__":
    unittest.main()
