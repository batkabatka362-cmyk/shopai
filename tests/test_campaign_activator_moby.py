"""Integration tests for CampaignActivator ↔ MobyVoteComparator (A7 wire-in)."""
from __future__ import annotations

import tempfile
import unittest
from unittest.mock import MagicMock

from execution.launch import campaign_activator as ca
from core.adapters.triplewhale.moby import (
    MobyAdapter,
    MobyRecommendation,
)
from core.brain.moby_vote_comparator import (
    MobyVoteComparator,
)

# Import the existing fakes directly
from tests.test_campaign_activator import (  # type: ignore[import]
    _FakeAds,
    _FakeConstraints,
    _FakeOutcomes,
    _FakeRationale,
    _FakeReadiness,
    _green_crisis,
    _permissive_tripwire,
    _req,
)


def _tmp_moby() -> MobyAdapter:
    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".db",
    )
    tmp.close()
    return MobyAdapter(api_key="", db_path=tmp.name)


def _rec(entity_id: str, recommendation: str):
    return MobyRecommendation(
        scope="campaigns",
        entity_id=entity_id,
        recommendation=recommendation,
        confidence=0.7,
    )


def _activator_with_moby(comparator):
    return ca.CampaignActivator(
        ad_adapter=_FakeAds(),
        readiness_checker=_FakeReadiness(),
        constraint_registry=_FakeConstraints(),
        outcome_recorder=_FakeOutcomes(),
        rationale_builder=_FakeRationale(),
        risk_tripwire=_permissive_tripwire(),
        crisis_responder=_green_crisis(),
        moby_comparator=comparator,
    )


class TestMobyStepPresence(unittest.TestCase):
    def test_step_runs_even_without_adapter(self):
        # comparator has no adapter → step is a no-op but still logs
        comparator = MobyVoteComparator(adapter=None)
        comparator._get_adapter = lambda: None  # type: ignore[method-assign]
        activator = _activator_with_moby(comparator)
        res = activator.activate(_req())
        names = [s.name for s in res.steps]
        self.assertIn("moby_vote_compare", names)

    def test_step_runs_before_execute(self):
        comparator = MobyVoteComparator(adapter=None)
        comparator._get_adapter = lambda: None  # type: ignore[method-assign]
        activator = _activator_with_moby(comparator)
        res = activator.activate(_req())
        names = [s.name for s in res.steps]
        self.assertLess(
            names.index("moby_vote_compare"),
            names.index("execute"),
        )


class TestAgreementAndDisagreement(unittest.TestCase):
    def test_agreement_when_actions_match(self):
        adapter = _tmp_moby()
        adapter.recommendations = MagicMock(
            return_value=[_rec("camp_abc", "activate")],
        )
        comparator = MobyVoteComparator(adapter=adapter)
        activator = _activator_with_moby(comparator)
        res = activator.activate(_req())
        step = next(
            s for s in res.steps
            if s.name == "moby_vote_compare"
        )
        self.assertEqual(step.status, "ok")
        self.assertIn("agreement", step.note)
        # No disagreement row persisted
        self.assertEqual(
            len(adapter.recent_disagreements()), 0,
        )

    def test_disagreement_logged_when_actions_differ(self):
        adapter = _tmp_moby()
        adapter.recommendations = MagicMock(
            return_value=[_rec("camp_abc", "pause")],
        )
        comparator = MobyVoteComparator(adapter=adapter)
        activator = _activator_with_moby(comparator)
        res = activator.activate(_req())
        step = next(
            s for s in res.steps
            if s.name == "moby_vote_compare"
        )
        self.assertEqual(step.status, "ok")
        self.assertIn("disagreement", step.note)
        rows = adapter.recent_disagreements()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].shopai_vote, "activate")
        self.assertEqual(rows[0].moby_vote, "pause")

    def test_no_matching_rec_logs_none(self):
        adapter = _tmp_moby()
        adapter.recommendations = MagicMock(
            return_value=[_rec("other_camp", "pause")],
        )
        comparator = MobyVoteComparator(adapter=adapter)
        activator = _activator_with_moby(comparator)
        res = activator.activate(_req())
        step = next(
            s for s in res.steps
            if s.name == "moby_vote_compare"
        )
        self.assertEqual(step.status, "ok")
        self.assertIn("no matching", step.note)


class TestFailureIsolation(unittest.TestCase):
    def test_moby_raise_does_not_block_activation(self):
        adapter = _tmp_moby()
        adapter.recommendations = MagicMock(
            side_effect=RuntimeError("api down"),
        )
        comparator = MobyVoteComparator(adapter=adapter)
        activator = _activator_with_moby(comparator)
        res = activator.activate(_req())
        # Step still logs; activation proceeds
        step = next(
            s for s in res.steps
            if s.name == "moby_vote_compare"
        )
        self.assertEqual(step.status, "ok")
        names = [s.name for s in res.steps]
        self.assertIn("execute", names)


if __name__ == "__main__":
    unittest.main()
