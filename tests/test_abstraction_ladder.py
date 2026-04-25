"""Abstraction ladder tests — generalise / specialise / climb."""
from __future__ import annotations

import unittest

from core.brain import abstraction_ladder as al


class TestGeneralise(unittest.TestCase):
    def test_replaces_concrete_with_parameter(self) -> None:
        rule = {
            "id": "r1",
            "when": {"niche": "audio", "roas_lt": 1.5},
            "then": {"action": "kill"},
            "height": 0,
        }
        report = al.generalise(rule, parameters={
            "niche:audio": "$niche",
        })
        self.assertEqual(report.after["when"]["niche"], "$niche")
        self.assertEqual(report.after["parameters"]["$niche"], "audio")
        self.assertEqual(report.after["height"], 1)

    def test_skips_unmatched_params(self) -> None:
        rule = {"when": {"niche": "fashion"}, "then": {"action": "scale"}}
        report = al.generalise(rule, parameters={"niche:audio": "$niche"})
        self.assertEqual(report.after["when"]["niche"], "fashion")


class TestSpecialise(unittest.TestCase):
    def test_binds_parameters_back(self) -> None:
        abstract = {
            "when": {"niche": "$niche", "roas_lt": 1.5},
            "then": {"action": "kill"},
            "parameters": {"$niche": None},
            "height": 1,
        }
        report = al.specialise(abstract, bindings={"$niche": "audio"})
        self.assertEqual(report.after["when"]["niche"], "audio")
        self.assertNotIn("$niche", report.after["parameters"])
        self.assertEqual(report.after["height"], 0)

    def test_ignores_unknown_bindings(self) -> None:
        rule = {"when": {"x": "$a"}, "then": {"action": "y"},
                "parameters": {"$a": None}, "height": 1}
        report = al.specialise(rule, bindings={"$b": "x"})
        # $a not bound → still $a
        self.assertEqual(report.after["when"]["x"], "$a")


class TestClimb(unittest.TestCase):
    def test_two_rules_differ_on_niche_climb_to_abstract(self) -> None:
        rules = [
            {"id": "r1",
             "when": {"niche": "audio", "roas_lt": 1.5},
             "then": {"action": "kill"}, "height": 0},
            {"id": "r2",
             "when": {"niche": "fashion", "roas_lt": 1.5},
             "then": {"action": "kill"}, "height": 0},
        ]
        report = al.climb(rules)
        self.assertIsNotNone(report)
        self.assertEqual(report.after["when"]["niche"], "$niche")
        self.assertEqual(report.after["when"]["roas_lt"], 1.5)
        self.assertEqual(report.after["height"], 1)
        self.assertIn("r1", report.after["source_rules"])
        self.assertIn("r2", report.after["source_rules"])

    def test_different_actions_no_climb(self) -> None:
        rules = [
            {"id": "r1", "when": {"niche": "x"},
             "then": {"action": "kill"}},
            {"id": "r2", "when": {"niche": "y"},
             "then": {"action": "scale"}},
        ]
        self.assertIsNone(al.climb(rules))

    def test_different_when_keys_no_climb(self) -> None:
        rules = [
            {"id": "r1", "when": {"niche": "x"},
             "then": {"action": "kill"}},
            {"id": "r2", "when": {"niche": "y", "roas_lt": 1.0},
             "then": {"action": "kill"}},
        ]
        self.assertIsNone(al.climb(rules))

    def test_identical_rules_no_climb(self) -> None:
        rules = [
            {"id": "r1", "when": {"niche": "audio", "roas_lt": 1.5},
             "then": {"action": "kill"}},
            {"id": "r2", "when": {"niche": "audio", "roas_lt": 1.5},
             "then": {"action": "kill"}},
        ]
        self.assertIsNone(al.climb(rules))

    def test_climb_parametrises_multiple_fields(self) -> None:
        rules = [
            {"id": "r1",
             "when": {"niche": "audio", "margin": "high"},
             "then": {"action": "scale"}},
            {"id": "r2",
             "when": {"niche": "fashion", "margin": "mid"},
             "then": {"action": "scale"}},
        ]
        report = al.climb(rules)
        self.assertIsNotNone(report)
        self.assertEqual(report.after["when"]["niche"], "$niche")
        self.assertEqual(report.after["when"]["margin"], "$margin")


class TestCluster(unittest.TestCase):
    def test_groups_by_signature(self) -> None:
        rules = [
            {"when": {"niche": "a"}, "then": {"action": "kill"}},
            {"when": {"niche": "b"}, "then": {"action": "kill"}},
            {"when": {"niche": "c"}, "then": {"action": "scale"}},
        ]
        groups = al.cluster_climbable(rules)
        # Only the two kill-rules share a signature → one group.
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

    def test_singleton_groups_filtered_out(self) -> None:
        rules = [
            {"when": {"niche": "a"}, "then": {"action": "kill"}},
            {"when": {"niche": "b", "margin": "high"},
             "then": {"action": "kill"}},
        ]
        groups = al.cluster_climbable(rules)
        self.assertEqual(groups, [])


if __name__ == "__main__":
    unittest.main()
