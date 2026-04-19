"""Concept former tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.memory import concept_former as cf


class TestObserve(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.c = cf.ConceptFormer(Path(self._tmp.name) / "c.db")

    def tearDown(self) -> None:
        self.c.close()
        self._tmp.cleanup()

    def test_blank_fields_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.c.observe({})

    def test_drops_high_cardinality(self) -> None:
        sig_a = self.c.observe({
            "niche": "audio", "price": 30,
            "ts": 1000, "id": "o1",
        })
        sig_b = self.c.observe({
            "niche": "audio", "price": 30,
            "ts": 2000, "id": "o2",
        })
        self.assertEqual(sig_a, sig_b)

    def test_signature_stable_across_key_order(self) -> None:
        a = self.c.observe({"a": 1, "b": 2})
        b = self.c.observe({"b": 2, "a": 1})
        self.assertEqual(a, b)

    def test_float_rounded(self) -> None:
        # Both round to 0.1234 at 4dp
        a = self.c.observe({"x": 0.12341, "y": "z"})
        b = self.c.observe({"x": 0.12344, "y": "z"})
        self.assertEqual(a, b)


class TestForm(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.c = cf.ConceptFormer(Path(self._tmp.name) / "c.db")

    def tearDown(self) -> None:
        self.c.close()
        self._tmp.cleanup()

    def test_min_support_invalid_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.c.form(min_support=0)

    def test_small_clusters_filtered(self) -> None:
        for _ in range(2):
            self.c.observe({"niche": "audio"})
        self.assertEqual(self.c.form(min_support=3), [])

    def test_big_clusters_emerge(self) -> None:
        for _ in range(5):
            self.c.observe({"niche": "audio", "price": 29})
        for _ in range(3):
            self.c.observe({"niche": "fashion", "price": 99})
        # "fashion" just makes the 3-support threshold
        concepts = self.c.form(min_support=3)
        self.assertEqual(len(concepts), 2)
        self.assertEqual(concepts[0].support, 5)
        self.assertEqual(concepts[0].examples_signature["niche"],
                         "audio")

    def test_outcome_sign_majority(self) -> None:
        for _ in range(4):
            self.c.observe(
                {"niche": "audio"},
                outcome_sign="win",
            )
        for _ in range(1):
            self.c.observe(
                {"niche": "audio"},
                outcome_sign="loss",
            )
        concepts = self.c.form(min_support=3)
        self.assertEqual(concepts[0].majority_outcome, "win")
        self.assertEqual(
            concepts[0].outcome_sign_counts["win"], 4,
        )


class TestNameConcept(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.c = cf.ConceptFormer(Path(self._tmp.name) / "c.db")

    def tearDown(self) -> None:
        self.c.close()
        self._tmp.cleanup()

    def test_name_returns_id(self) -> None:
        sig = self.c.observe({"x": 1})
        cid = self.c.name_concept(sig, label="the_thing")
        self.assertTrue(cid)

    def test_blank_signature_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.c.name_concept("", label="x")

    def test_blank_label_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.c.name_concept("sig", label="")

    def test_rename_keeps_id(self) -> None:
        sig = self.c.observe({"x": 1})
        first_id = self.c.name_concept(sig, label="v1")
        second_id = self.c.name_concept(sig, label="v2")
        self.assertEqual(first_id, second_id)


class TestLabelledConcepts(unittest.TestCase):
    def test_only_labelled_returned(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        c = cf.ConceptFormer(Path(tmp.name) / "c.db")
        sig = c.observe({"niche": "audio"})
        c.observe({"niche": "fashion"})
        c.name_concept(sig, label="audio_cluster")
        labelled = c.labelled_concepts()
        self.assertEqual(len(labelled), 1)
        self.assertEqual(labelled[0].label, "audio_cluster")
        c.close()
        tmp.cleanup()


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "c.db"
        first = cf.ConceptFormer(path)
        sig = first.observe({"niche": "audio"})
        first.observe({"niche": "audio"})
        first.observe({"niche": "audio"})
        first.name_concept(sig, label="tested")
        first.close()
        second = cf.ConceptFormer(path)
        concepts = second.form(min_support=2)
        self.assertEqual(len(concepts), 1)
        self.assertEqual(concepts[0].label, "tested")
        second.close()
        tmp.cleanup()


class TestStatsReset(unittest.TestCase):
    def test_stats(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        c = cf.ConceptFormer(Path(tmp.name) / "c.db")
        for _ in range(3):
            c.observe({"niche": "audio"})
        c.name_concept("niche=audio", label="x")
        s = c.stats()
        self.assertEqual(s["total_observations"], 3)
        self.assertEqual(s["distinct_signatures"], 1)
        self.assertEqual(s["named_concepts"], 1)
        c.close()
        tmp.cleanup()

    def test_reset(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        c = cf.ConceptFormer(Path(tmp.name) / "c.db")
        for _ in range(3):
            c.observe({"x": 1})
        n = c.reset()
        self.assertEqual(n, 3)
        self.assertEqual(c.stats()["total_observations"], 0)
        c.close()
        tmp.cleanup()


class TestDict(unittest.TestCase):
    def test_concept_serialises(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        c = cf.ConceptFormer(Path(tmp.name) / "c.db")
        for _ in range(3):
            c.observe(
                {"niche": "audio"}, outcome_sign="win",
            )
        concept = c.form(min_support=2)[0]
        d = concept.as_dict()
        self.assertIn("signature", d)
        self.assertEqual(d["majority_outcome"], "win")
        c.close()
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
