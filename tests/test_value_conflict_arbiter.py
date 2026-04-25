"""Value conflict arbiter tests."""
from __future__ import annotations

import unittest

from core.brain import value_conflict_arbiter as vca


class TestConfig(unittest.TestCase):
    def test_bad_margin_raises(self) -> None:
        with self.assertRaises(ValueError):
            vca.ValueConflictArbiter(tie_margin=1.0)


class TestCase(unittest.TestCase):
    def test_one_option_raises(self) -> None:
        with self.assertRaises(ValueError):
            vca.ConflictCase(
                id="c",
                options=[vca.OptionScore(
                    option_id="a", name="A",
                    scores={"x": 1.0},
                )],
            )


class TestArbitrate(unittest.TestCase):
    def setUp(self) -> None:
        self.arb = vca.ValueConflictArbiter(tie_margin=0.01)

    def test_margin_picks_winner(self) -> None:
        case = vca.ConflictCase(
            id="c",
            options=[
                vca.OptionScore(
                    option_id="A", name="raise",
                    scores={"margin": 0.9, "novelty": 0.1},
                ),
                vca.OptionScore(
                    option_id="B", name="keep",
                    scores={"margin": 0.4, "novelty": 0.4},
                ),
            ],
        )
        weights = {"margin": 0.7, "novelty": 0.3}
        r = self.arb.arbitrate(case, value_weights=weights)
        self.assertEqual(r.verdict, "pick")
        self.assertEqual(r.winner_option, "A")

    def test_tie_verdict(self) -> None:
        case = vca.ConflictCase(
            id="c",
            options=[
                vca.OptionScore(
                    option_id="A", name="a",
                    scores={"x": 0.5, "y": 0.5},
                ),
                vca.OptionScore(
                    option_id="B", name="b",
                    scores={"x": 0.5, "y": 0.5},
                ),
            ],
        )
        r = self.arb.arbitrate(
            case,
            value_weights={"x": 0.5, "y": 0.5},
        )
        self.assertEqual(r.verdict, "tie")

    def test_contested_value_identified(self) -> None:
        case = vca.ConflictCase(
            id="c",
            options=[
                vca.OptionScore(
                    option_id="A", name="a",
                    scores={"margin": 0.9, "novelty": 0.0},
                ),
                vca.OptionScore(
                    option_id="B", name="b",
                    scores={"margin": 0.6, "novelty": 0.8},
                ),
            ],
        )
        # Margin > novelty weight → A should win, but novelty
        # is contested
        r = self.arb.arbitrate(
            case,
            value_weights={"margin": 0.9, "novelty": 0.1},
        )
        self.assertEqual(r.winner_option, "A")
        self.assertEqual(r.contested_value, "novelty")

    def test_missing_weights_filled(self) -> None:
        case = vca.ConflictCase(
            id="c",
            options=[
                vca.OptionScore(
                    option_id="A", name="a",
                    scores={"unseen": 1.0},
                ),
                vca.OptionScore(
                    option_id="B", name="b",
                    scores={"unseen": 0.0},
                ),
            ],
        )
        r = self.arb.arbitrate(case, value_weights={})
        self.assertEqual(r.winner_option, "A")

    def test_no_value_dimension_raises(self) -> None:
        case = vca.ConflictCase(
            id="c",
            options=[
                vca.OptionScore(
                    option_id="A", name="a", scores={},
                ),
                vca.OptionScore(
                    option_id="B", name="b", scores={},
                ),
            ],
        )
        with self.assertRaises(ValueError):
            self.arb.arbitrate(case)


class TestTieMargin(unittest.TestCase):
    def test_set_tie_margin(self) -> None:
        arb = vca.ValueConflictArbiter(tie_margin=0.01)
        arb.set_tie_margin(0.5)
        case = vca.ConflictCase(
            id="c",
            options=[
                vca.OptionScore(
                    option_id="A", name="a",
                    scores={"x": 0.9},
                ),
                vca.OptionScore(
                    option_id="B", name="b",
                    scores={"x": 0.5},
                ),
            ],
        )
        r = arb.arbitrate(
            case, value_weights={"x": 1.0},
        )
        # 0.9 - 0.5 = 0.4 < tie_margin 0.5 → tie
        self.assertEqual(r.verdict, "tie")

    def test_bad_margin_raises(self) -> None:
        arb = vca.ValueConflictArbiter()
        with self.assertRaises(ValueError):
            arb.set_tie_margin(1.5)


class TestQueries(unittest.TestCase):
    def test_recent(self) -> None:
        arb = vca.ValueConflictArbiter()
        for _ in range(3):
            case = vca.ConflictCase(
                id="c",
                options=[
                    vca.OptionScore(
                        option_id="A", name="a",
                        scores={"x": 0.9},
                    ),
                    vca.OptionScore(
                        option_id="B", name="b",
                        scores={"x": 0.1},
                    ),
                ],
            )
            arb.arbitrate(
                case, value_weights={"x": 1.0},
            )
        self.assertEqual(len(arb.recent(limit=2)), 2)

    def test_stats(self) -> None:
        arb = vca.ValueConflictArbiter()
        case = vca.ConflictCase(
            id="c",
            options=[
                vca.OptionScore(
                    option_id="A", name="a",
                    scores={"x": 0.9},
                ),
                vca.OptionScore(
                    option_id="B", name="b",
                    scores={"x": 0.1},
                ),
            ],
        )
        arb.arbitrate(case, value_weights={"x": 1.0})
        s = arb.stats()
        self.assertEqual(s["arbitrations"], 1)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        arb = vca.ValueConflictArbiter()
        case = vca.ConflictCase(
            id="c",
            options=[
                vca.OptionScore(
                    option_id="A", name="a",
                    scores={"x": 0.9},
                ),
                vca.OptionScore(
                    option_id="B", name="b",
                    scores={"x": 0.1},
                ),
            ],
        )
        arb.arbitrate(case, value_weights={"x": 1.0})
        self.assertEqual(arb.reset(), 1)


class TestDict(unittest.TestCase):
    def test_option_serialises(self) -> None:
        o = vca.OptionScore(
            option_id="A", name="a", scores={"x": 0.5},
        )
        d = o.as_dict()
        self.assertEqual(d["option_id"], "A")

    def test_resolution_serialises(self) -> None:
        arb = vca.ValueConflictArbiter()
        case = vca.ConflictCase(
            id="c",
            options=[
                vca.OptionScore(
                    option_id="A", name="a",
                    scores={"x": 0.9},
                ),
                vca.OptionScore(
                    option_id="B", name="b",
                    scores={"x": 0.1},
                ),
            ],
        )
        r = arb.arbitrate(case, value_weights={"x": 1.0})
        d = r.as_dict()
        self.assertIn("reasoning", d)


if __name__ == "__main__":
    unittest.main()
