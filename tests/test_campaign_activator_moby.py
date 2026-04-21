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


class TestRationaleStamp(unittest.TestCase):
    """Verify the moby step now adds a rationale-ledger gate
    entry so ``shopai explain <id>`` shows the trust signal."""

    def _capturing_rationale(self):
        rationale = MagicMock()
        rationale.added = []

        def _add(decision_id, **kw):
            rationale.added.append({
                "decision_id": decision_id, **kw,
            })
            return MagicMock()

        rationale.add.side_effect = _add
        return rationale

    def test_agreement_logs_rationale_gate(self):
        adapter = _tmp_moby()
        adapter.recommendations = MagicMock(
            return_value=[_rec("camp_abc", "activate")],
        )
        comparator = MobyVoteComparator(adapter=adapter)
        rationale = self._capturing_rationale()
        activator = _activator_with_moby(comparator)
        activator._rationale = rationale  # type: ignore[attr-defined]
        activator.activate(_req())
        gate_adds = [
            r for r in rationale.added
            if r.get("kind") == "gate"
            and "moby:" in r.get("headline", "")
        ]
        self.assertEqual(len(gate_adds), 1)
        self.assertIn(
            "agreement", gate_adds[0]["headline"],
        )

    def test_disagreement_higher_weight(self):
        adapter = _tmp_moby()
        adapter.recommendations = MagicMock(
            return_value=[_rec("camp_abc", "pause")],
        )
        comparator = MobyVoteComparator(adapter=adapter)
        rationale = self._capturing_rationale()
        activator = _activator_with_moby(comparator)
        activator._rationale = rationale  # type: ignore[attr-defined]
        activator.activate(_req())
        gate = next(
            r for r in rationale.added
            if "moby:" in r.get("headline", "")
        )
        self.assertIn("disagreement", gate["headline"])
        # Disagreement weight (0.85) > agreement weight (0.5)
        self.assertGreater(gate["weight"], 0.7)

    def test_no_recs_records_no_recs_outcome(self):
        adapter = _tmp_moby()
        adapter.recommendations = MagicMock(return_value=[])
        comparator = MobyVoteComparator(adapter=adapter)
        rationale = self._capturing_rationale()
        activator = _activator_with_moby(comparator)
        activator._rationale = rationale  # type: ignore[attr-defined]
        activator.activate(_req())
        gate = next(
            r for r in rationale.added
            if "moby:" in r.get("headline", "")
        )
        self.assertIn("no_recs", gate["headline"])

    def test_unavailable_comparator_records(self):
        # When the activator's _get_moby() returns None
        # (e.g. moby_vote_comparator import failed), the
        # rationale gate captures "unavailable".
        rationale = self._capturing_rationale()
        activator = _activator_with_moby(comparator=None)
        activator._get_moby = lambda: None  # type: ignore[method-assign]
        activator._rationale = rationale  # type: ignore[attr-defined]
        activator.activate(_req())
        gate = next(
            r for r in rationale.added
            if "moby:" in r.get("headline", "")
        )
        self.assertIn("unavailable", gate["headline"])

    def test_no_adapter_records_no_recs(self):
        # When the comparator exists but its underlying
        # adapter is None, we get the no_recs outcome.
        comparator = MobyVoteComparator(adapter=None)
        comparator._get_adapter = lambda: None  # type: ignore[method-assign]
        rationale = self._capturing_rationale()
        activator = _activator_with_moby(comparator)
        activator._rationale = rationale  # type: ignore[attr-defined]
        activator.activate(_req())
        gate = next(
            r for r in rationale.added
            if "moby:" in r.get("headline", "")
        )
        self.assertIn("no_recs", gate["headline"])

    def test_rationale_failure_does_not_block(self):
        adapter = _tmp_moby()
        adapter.recommendations = MagicMock(
            return_value=[_rec("camp_abc", "pause")],
        )
        comparator = MobyVoteComparator(adapter=adapter)
        rationale = MagicMock()
        rationale.add.side_effect = RuntimeError("ledger down")
        activator = _activator_with_moby(comparator)
        activator._rationale = rationale  # type: ignore[attr-defined]
        # Activation must still complete despite rationale failure
        result = activator.activate(_req())
        self.assertNotEqual(result.verdict, "blocked")


class TestEngineOutcomeBusEmission(unittest.TestCase):
    def test_activation_reports_to_bus(self):
        comparator = MobyVoteComparator(adapter=None)
        comparator._get_adapter = lambda: None  # type: ignore[method-assign]
        activator = _activator_with_moby(comparator)

        reported = []

        class _FakeBus:
            def report(self, ev):
                reported.append(ev)

        with unittest.mock.patch(
            "core.integration.engine_outcome_bus"
            ".get_engine_outcome_bus",
            return_value=_FakeBus(),
        ):
            activator.activate(_req())
        self.assertEqual(len(reported), 1)
        ev = reported[0]
        self.assertEqual(ev.engine, "campaign_activator")
        self.assertEqual(ev.kpi, "activation")
        self.assertEqual(ev.value, 1.0)
        self.assertEqual(ev.source, "meta_ads")
        self.assertIn(
            "campaign_id", ev.context,
        )


import unittest.mock  # placed here to minimise diff footprint


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
