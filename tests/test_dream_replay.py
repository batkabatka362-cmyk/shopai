"""Dream replay tests."""
from __future__ import annotations

import random
import unittest

from core.brain import dream_replay as dr


class TestReplay(unittest.TestCase):
    def setUp(self) -> None:
        self.vocab = {
            "niche": ["audio", "fashion", "gardening"],
            "copy_tone": ["friendly", "urgent", "luxury"],
        }

    def _predict(self, event):
        return (2.0, 0.8)

    def test_rare_event_spawns_dreams(self) -> None:
        events = [{"id": "e1", "niche": "audio",
                    "copy_tone": "friendly"}]
        report = dr.replay(
            events,
            is_rare=lambda e: True,
            vocab=self.vocab,
            predictor=self._predict,
            fan_out=3,
            rng=random.Random(42),
        )
        self.assertEqual(report.rare_events, 1)
        self.assertEqual(len(report.dreams), 3)

    def test_non_rare_skipped(self) -> None:
        events = [{"id": "e1", "niche": "audio"}]
        report = dr.replay(
            events,
            is_rare=lambda e: False,
            vocab=self.vocab,
            predictor=self._predict,
            fan_out=3,
        )
        self.assertEqual(report.considered_events, 1)
        self.assertEqual(report.rare_events, 0)
        self.assertEqual(len(report.dreams), 0)

    def test_perturbed_field_differs_from_original(self) -> None:
        events = [{"id": "e1", "niche": "audio",
                    "copy_tone": "friendly"}]
        report = dr.replay(
            events,
            is_rare=lambda e: True,
            vocab=self.vocab,
            predictor=self._predict,
            fan_out=5,
            rng=random.Random(7),
        )
        for d in report.dreams:
            self.assertNotEqual(d.dream_value, d.original_value)

    def test_no_perturbable_fields_yields_nothing(self) -> None:
        # Event has fields, but vocab has only the same values
        events = [{"id": "e1", "niche": "audio"}]
        vocab = {"niche": ["audio"]}     # no alternatives
        report = dr.replay(
            events,
            is_rare=lambda e: True,
            vocab=vocab,
            predictor=self._predict,
            fan_out=3,
        )
        self.assertEqual(len(report.dreams), 0)

    def test_synthetic_weight_propagates(self) -> None:
        events = [{"id": "e1", "niche": "audio"}]
        report = dr.replay(
            events,
            is_rare=lambda e: True,
            vocab=self.vocab,
            predictor=self._predict,
            fan_out=1,
            synthetic_weight=0.5,
            rng=random.Random(0),
        )
        self.assertAlmostEqual(
            report.dreams[0].synthetic_weight, 0.5,
        )

    def test_predictor_output_captured(self) -> None:
        events = [{"id": "e1", "niche": "audio"}]
        def pred(event):
            return (3.3, 0.7)
        report = dr.replay(
            events,
            is_rare=lambda e: True,
            vocab=self.vocab,
            predictor=pred,
            fan_out=1,
            rng=random.Random(1),
        )
        self.assertAlmostEqual(
            report.dreams[0].predicted_outcome, 3.3,
        )
        self.assertAlmostEqual(report.dreams[0].confidence, 0.7)


class TestFoldDreams(unittest.TestCase):
    def test_fold_calls_fn_per_dream(self) -> None:
        dreams = [
            dr.DreamSample(
                source_event_id="e1",
                perturbed_field="niche",
                original_value="audio",
                dream_value="fashion",
                predicted_outcome=2.0,
                confidence=0.8,
                synthetic_weight=0.3,
            ),
            dr.DreamSample(
                source_event_id="e1",
                perturbed_field="copy_tone",
                original_value="friendly",
                dream_value="luxury",
                predicted_outcome=2.2,
                confidence=0.9,
                synthetic_weight=0.3,
            ),
        ]
        called: list[tuple] = []
        def fold(perturbed, weight):
            called.append((perturbed, weight))
        count = dr.fold_dreams(dreams, fold)
        self.assertEqual(count, 2)
        self.assertEqual(len(called), 2)
        # Weight should equal synthetic_weight × confidence
        self.assertAlmostEqual(called[0][1], 0.3 * 0.8, places=3)

    def test_zero_weight_dream_skipped(self) -> None:
        d = dr.DreamSample(
            source_event_id="e1",
            perturbed_field="x",
            original_value="a",
            dream_value="b",
            predicted_outcome=0.0,
            confidence=0.0,
            synthetic_weight=0.0,
        )
        called: list[tuple] = []
        count = dr.fold_dreams([d], lambda p, w: called.append((p, w)))
        self.assertEqual(count, 0)
        self.assertEqual(called, [])


class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_dreams(self) -> None:
        events = [{"id": "e1", "niche": "audio",
                    "copy_tone": "friendly"}]
        vocab = {
            "niche": ["audio", "fashion", "gardening"],
            "copy_tone": ["friendly", "urgent", "luxury"],
        }
        def pred(e): return (2.0, 0.8)
        r1 = dr.replay(
            events, is_rare=lambda e: True, vocab=vocab,
            predictor=pred, fan_out=3, rng=random.Random(123),
        )
        r2 = dr.replay(
            events, is_rare=lambda e: True, vocab=vocab,
            predictor=pred, fan_out=3, rng=random.Random(123),
        )
        pairs_1 = [(d.perturbed_field, d.dream_value)
                    for d in r1.dreams]
        pairs_2 = [(d.perturbed_field, d.dream_value)
                    for d in r2.dreams]
        self.assertEqual(pairs_1, pairs_2)


if __name__ == "__main__":
    unittest.main()
