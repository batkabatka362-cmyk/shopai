"""Deliberation → rationale ledger mirror tests.

The 5 pillars (outcome / directions / constraints / chosen /
awareness) now mirror into the rationale ledger via
``Deliberation.as_rationale_entries()``. ``shopai explain
<decision_id>`` shows the structured reasoning alongside
the existing gate-level entries.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.brain.structured_decision import (
    reset_recent_for_tests,
)
from execution.launch import campaign_activator as ca
from execution.launch import publisher_bundle as pb

from tests.test_campaign_activator import (  # type: ignore[import]
    _activator,
    _req,
)
from tests.test_publisher_bundle import (  # type: ignore[import]
    _FakeAds,
    _FakeContent,
    _FakeOutcomes,
    _FakeProducts,
    _FakeRationale,
    _request,
)


class _CapturingRationale:
    """Expanded fake that records every .add call so we can
    assert the pillar shape ended up in the ledger."""

    def __init__(self):
        self.started = []
        self.added: list[dict] = []
        self.committed = []

    def start(self, *, decision_id, summary):
        self.started.append((decision_id, summary))
        return MagicMock()

    def add(self, decision_id, **kw):
        self.added.append({
            "decision_id": decision_id, **kw,
        })
        return MagicMock()

    def commit(self, decision_id):
        self.committed.append(decision_id)
        return MagicMock()


# ── Activator wire ──────────────────────────────────────


class TestActivatorMirror(unittest.TestCase):
    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def _make(self):
        rationale = _CapturingRationale()
        activator = _activator(
            rationale_builder=rationale,
        )
        return activator, rationale

    def test_activation_mirrors_pillars(self):
        activator, rationale = self._make()
        activator.activate(_req())
        # every pillar appears once (plus the final
        # "verdict=..." gate already added by _finalise)
        kinds = [e.get("kind") for e in rationale.added]
        self.assertIn("goal", kinds)
        self.assertIn("option", kinds)
        self.assertIn("constraint", kinds)
        self.assertIn("meta", kinds)
        # a gate entry for the chosen direction exists
        gates = [
            e for e in rationale.added
            if e.get("kind") == "gate"
        ]
        self.assertTrue(gates)

    def test_pillar_headlines_readable(self):
        activator, rationale = self._make()
        activator.activate(_req(
            campaign_id="camp-readable",
        ))
        goal_entry = next(
            e for e in rationale.added
            if e.get("kind") == "goal"
        )
        self.assertIn(
            "camp-readable",
            goal_entry["headline"],
        )
        meta_entry = next(
            e for e in rationale.added
            if e.get("kind") == "meta"
        )
        self.assertIn("loop=", meta_entry["headline"])
        self.assertIn(
            "dollar_distance=",
            meta_entry["headline"],
        )

    def test_headlines_truncated_to_120(self):
        # Even for a weird long campaign_id, headlines stay
        # under the ledger's per-entry budget.
        activator, rationale = self._make()
        activator.activate(_req(
            campaign_id="x" * 300,
        ))
        for e in rationale.added:
            self.assertLessEqual(
                len(e.get("headline", "")), 120,
            )

    def test_rationale_failure_soft(self):
        rationale = MagicMock()
        rationale.add.side_effect = RuntimeError("boom")
        rationale.start.return_value = MagicMock()
        rationale.commit.return_value = MagicMock()
        activator = _activator(
            rationale_builder=rationale,
        )
        # Activation must still complete
        result = activator.activate(_req())
        self.assertIn(
            result.verdict, ("dry_run", "activated"),
        )


# ── Publisher wire ──────────────────────────────────────


class TestPublisherMirror(unittest.TestCase):
    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def _make(self):
        rationale = _CapturingRationale()
        bundle = pb.PublisherBundle(
            content_generator=_FakeContent(),
            product_creator=_FakeProducts(),
            ad_adapter=_FakeAds(),
            outcome_recorder=_FakeOutcomes(),
            rationale_builder=rationale,
        )
        return bundle, rationale

    def test_launch_mirrors_pillars(self):
        bundle, rationale = self._make()
        bundle.launch(_request())
        kinds = [e.get("kind") for e in rationale.added]
        self.assertIn("goal", kinds)
        self.assertIn("option", kinds)
        self.assertIn("meta", kinds)

    def test_launch_gate_uses_chosen_direction(self):
        bundle, rationale = self._make()
        bundle.launch(_request())
        # exactly one gate entry from as_rationale_entries
        # ("chose launch") plus any pre-existing gates from
        # publisher_bundle's own pipeline
        five_pillar_gates = [
            e for e in rationale.added
            if e.get("kind") == "gate"
            and "chose " in str(e.get("headline", ""))
        ]
        self.assertEqual(len(five_pillar_gates), 1)
        self.assertIn(
            "chose launch",
            five_pillar_gates[0]["headline"],
        )

    def test_rationale_failure_soft(self):
        rationale = MagicMock()
        rationale.add.side_effect = RuntimeError("boom")
        rationale.start.return_value = MagicMock()
        rationale.commit.return_value = MagicMock()
        bundle = pb.PublisherBundle(
            content_generator=_FakeContent(),
            product_creator=_FakeProducts(),
            ad_adapter=_FakeAds(),
            outcome_recorder=_FakeOutcomes(),
            rationale_builder=rationale,
        )
        # Launch must still succeed — never blocked by
        # ledger push failure.
        result = bundle.launch(_request())
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
