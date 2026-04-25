"""Tests for core.brain.moby_vote_comparator (A7)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.adapters.triplewhale.moby import (
    MobyAdapter,
    MobyRecommendation,
)
from core.brain.moby_vote_comparator import (
    MobyVoteComparator,
    ShopAIVote,
    _normalize,
    get_moby_vote_comparator,
    reset_moby_vote_comparator_for_tests,
)


def _tmp_adapter() -> MobyAdapter:
    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".db",
    )
    tmp.close()
    return MobyAdapter(
        api_key="",  # offline; we only exercise the SQLite path
        db_path=tmp.name,
    )


def _rec(entity_id: str, recommendation: str,
         confidence: float = 0.7,
         expected_roas_delta: float = 0.0,
         scope: str = "campaigns") -> MobyRecommendation:
    return MobyRecommendation(
        scope=scope,
        entity_id=entity_id,
        recommendation=recommendation,
        confidence=confidence,
        expected_roas_delta=expected_roas_delta,
    )


class TestNormalize(unittest.TestCase):
    def test_synonyms_collapse(self):
        self.assertEqual(
            _normalize("scale_up"), "increase_budget",
        )
        self.assertEqual(_normalize("STOP"), "pause")
        self.assertEqual(
            _normalize("UNPAUSE"), "resume",
        )

    def test_unknown_passes_through(self):
        self.assertEqual(
            _normalize("split_test"), "split_test",
        )


class TestCompareAgreement(unittest.TestCase):
    def test_same_action_is_agreement(self):
        adapter = _tmp_adapter()
        comparator = MobyVoteComparator(adapter=adapter)
        vote = ShopAIVote(
            decision_id="dec1",
            entity_id="camp-1",
            action="pause",
        )
        rec = _rec("camp-1", "pause")
        report = comparator.compare_votes([vote], [rec])
        self.assertEqual(
            report.agreements, ("dec1",),
        )
        self.assertEqual(
            report.disagreements_logged, (),
        )

    def test_synonym_collapses_to_agreement(self):
        adapter = _tmp_adapter()
        comparator = MobyVoteComparator(adapter=adapter)
        vote = ShopAIVote(
            decision_id="dec1",
            entity_id="c-1",
            action="scale_up",
        )
        rec = _rec("c-1", "increase_budget")
        report = comparator.compare_votes([vote], [rec])
        self.assertEqual(
            report.agreements, ("dec1",),
        )


class TestDisagreement(unittest.TestCase):
    def test_disagreement_logged(self):
        adapter = _tmp_adapter()
        comparator = MobyVoteComparator(adapter=adapter)
        vote = ShopAIVote(
            decision_id="dec1",
            entity_id="c-1",
            action="pause",
        )
        rec = _rec("c-1", "increase_budget")
        report = comparator.compare_votes([vote], [rec])
        self.assertEqual(
            report.disagreements_logged, ("dec1",),
        )
        rows = adapter.recent_disagreements()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].decision_id, "dec1")
        self.assertEqual(rows[0].moby_vote, "increase_budget")
        self.assertEqual(rows[0].shopai_vote, "pause")

    def test_missing_moby_rec_records_no_match(self):
        adapter = _tmp_adapter()
        comparator = MobyVoteComparator(adapter=adapter)
        vote = ShopAIVote(
            decision_id="dec1",
            entity_id="unknown",
            action="pause",
        )
        report = comparator.compare_votes([vote], [])
        self.assertEqual(report.no_moby_rec, ("dec1",))
        self.assertEqual(report.disagreements_logged, ())

    def test_no_adapter_disagreement_becomes_error(self):
        comparator = MobyVoteComparator(adapter=None)
        comparator._get_adapter = lambda: None  # type: ignore[method-assign]
        vote = ShopAIVote(
            decision_id="dec1",
            entity_id="c-1",
            action="pause",
        )
        rec = _rec("c-1", "increase_budget")
        report = comparator.compare_votes([vote], [rec])
        self.assertIn("dec1", report.errors)
        self.assertEqual(report.errors["dec1"], "no adapter")


class TestResolve(unittest.TestCase):
    def test_resolve_logs_actual_outcome(self):
        adapter = _tmp_adapter()
        comparator = MobyVoteComparator(adapter=adapter)
        vote = ShopAIVote(
            decision_id="dec1",
            entity_id="c-1",
            action="pause",
        )
        rec = _rec("c-1", "increase_budget")
        comparator.compare_votes([vote], [rec])
        # Actual outcome was pause (shopai was right)
        updated = comparator.resolve_outcome(
            decision_id="dec1", actual="pause",
        )
        self.assertTrue(updated)
        row = adapter.recent_disagreements()[0]
        self.assertEqual(row.actual_outcome, "pause")
        self.assertTrue(row.resolved)
        self.assertEqual(row.winner, "shopai")

    def test_resolve_noop_without_match(self):
        adapter = _tmp_adapter()
        comparator = MobyVoteComparator(adapter=adapter)
        self.assertFalse(
            comparator.resolve_outcome(
                decision_id="nothing",
                actual="pause",
            ),
        )

    def test_resolve_normalises_synonym(self):
        adapter = _tmp_adapter()
        comparator = MobyVoteComparator(adapter=adapter)
        vote = ShopAIVote(
            decision_id="dec1",
            entity_id="c-1",
            action="scale_up",
        )
        rec = _rec("c-1", "pause")
        comparator.compare_votes([vote], [rec])
        comparator.resolve_outcome(
            decision_id="dec1", actual="scale",
        )
        row = adapter.recent_disagreements()[0]
        self.assertEqual(
            row.actual_outcome, "increase_budget",
        )


class TestWinRate(unittest.TestCase):
    def test_win_rate_flows_from_adapter(self):
        adapter = _tmp_adapter()
        comparator = MobyVoteComparator(adapter=adapter)
        votes = [
            ShopAIVote(
                decision_id=f"dec{i}",
                entity_id=f"c-{i}",
                action="pause",
            )
            for i in range(4)
        ]
        recs = [
            _rec(f"c-{i}", "increase_budget")
            for i in range(4)
        ]
        comparator.compare_votes(votes, recs)
        # shopai was right 3 of 4 times
        for i, actual in enumerate([
            "pause", "pause", "pause",
            "increase_budget",
        ]):
            comparator.resolve_outcome(
                decision_id=f"dec{i}", actual=actual,
            )
        rate = comparator.win_rate()
        self.assertEqual(rate["total_resolved"], 4)
        self.assertEqual(rate["shopai_only"], 3)
        self.assertEqual(rate["moby_only"], 1)


class TestSingleton(unittest.TestCase):
    def test_singleton_returns_same_instance(self):
        reset_moby_vote_comparator_for_tests()
        a = get_moby_vote_comparator()
        b = get_moby_vote_comparator()
        self.assertIs(a, b)
        reset_moby_vote_comparator_for_tests()


class TestOutcomeRecorderIntegration(unittest.TestCase):
    """OutcomeRecorder.record() → auto-resolve disagreements."""

    def test_launch_purchase_resolves_to_activate(self):
        import os
        from core.attribution.outcome_recorder import (
            OutcomeEvent, OutcomeRecorder,
        )
        from core.brain import moby_vote_comparator as mvc
        adapter = _tmp_adapter()
        # Register our test adapter through the singleton
        mvc.reset_moby_vote_comparator_for_tests()
        real_singleton = mvc.get_moby_vote_comparator()
        real_singleton._adapter = adapter
        # log a disagreement first
        real_singleton.compare_votes(
            [ShopAIVote(
                decision_id="dec_launch_1",
                entity_id="c-1",
                action="activate",
            )],
            [_rec("c-1", "pause")],
        )
        self.assertEqual(
            len(adapter.recent_disagreements()), 1,
        )
        # Turn brain hooks on but stub the brain to avoid pulling
        # full singleton load
        orig = os.environ.get("SHOPAI_BRAIN_HOOKS")
        os.environ["SHOPAI_BRAIN_HOOKS"] = "1"
        try:
            OutcomeRecorder().record(OutcomeEvent(
                kind="purchase",
                ok=True,
                decision_id="dec_launch_1",
                capability_name="launch_sku",
                revenue=30.0,
            ))
        finally:
            if orig is None:
                os.environ.pop(
                    "SHOPAI_BRAIN_HOOKS", None,
                )
            else:
                os.environ["SHOPAI_BRAIN_HOOKS"] = orig
        row = adapter.recent_disagreements()[0]
        self.assertEqual(row.actual_outcome, "activate")
        self.assertTrue(row.resolved)
        self.assertEqual(row.winner, "shopai")
        mvc.reset_moby_vote_comparator_for_tests()


if __name__ == "__main__":
    unittest.main()
