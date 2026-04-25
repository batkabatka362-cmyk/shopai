"""Launch learner tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from agents.learning import launch_learner as ll


def _make_episode(
    *,
    situation_terms=(),
    outcome="win",
):
    ep = MagicMock()
    ep.situation_terms = tuple(situation_terms)
    ep.outcome = outcome
    return ep


class _FakeSummariser:
    def __init__(self, episodes):
        self._episodes = list(episodes)

    def recent(self, *, limit):
        return self._episodes[: limit]


class _FakeExtractor:
    def __init__(self):
        self.calls = []

    def extract(self, rules):
        self.calls.append(list(rules))
        return []


class _FakeArbiter:
    def __init__(self, verdict="accept", reason="ok"):
        self._verdict = verdict
        self._reason = reason
        self.calls = []

    def arbitrate(
        self, *, target, proposals, current_value,
    ):
        self.calls.append(
            (target, list(proposals), current_value),
        )
        result = MagicMock()
        result.verdict = self._verdict
        result.reason = self._reason
        return result


class _FakeJournal:
    def __init__(self, raise_exc=False):
        self._raise = raise_exc
        self.calls = []

    def propose(self, **kw):
        self.calls.append(kw)
        if self._raise:
            raise RuntimeError("journal down")
        result = MagicMock()
        result.id = "rev_abc"
        return result


# ── Config ──────────────────────────────────────────────────


class TestConfig(unittest.TestCase):
    def test_bad_min_episodes_raises(self):
        with self.assertRaises(ValueError):
            ll.LaunchLearner(min_episodes=1)

    def test_bad_min_confidence_raises(self):
        with self.assertRaises(ValueError):
            ll.LaunchLearner(min_confidence=1.5)

    def test_bad_min_confidence_zero_raises(self):
        with self.assertRaises(ValueError):
            ll.LaunchLearner(min_confidence=0)


# ── Signature ───────────────────────────────────────────────


class TestSignature(unittest.TestCase):
    def test_picks_interesting_keys(self):
        ep = _make_episode(
            situation_terms=(
                "niche=pet",
                "margin_band=hi",
                "goal=maximize",   # ignored
            ),
        )
        sig = ll._situation_signature(ep)
        self.assertIn("niche=pet", sig)
        self.assertIn("margin_band=hi", sig)
        self.assertNotIn("goal=maximize", sig)

    def test_fallback_when_no_interesting(self):
        ep = _make_episode(
            situation_terms=(
                "goal=x",
                "health_grade=A",
            ),
        )
        sig = ll._situation_signature(ep)
        # Fallback takes all
        self.assertNotEqual(sig, "generic")

    def test_generic_when_empty(self):
        ep = _make_episode()
        sig = ll._situation_signature(ep)
        self.assertEqual(sig, "generic")

    def test_same_input_same_signature(self):
        a = _make_episode(
            situation_terms=("niche=pet", "source=ali"),
        )
        b = _make_episode(
            situation_terms=("source=ali", "niche=pet"),
        )
        self.assertEqual(
            ll._situation_signature(a),
            ll._situation_signature(b),
        )


# ── Distill ─────────────────────────────────────────────────


class TestDistill(unittest.TestCase):
    def test_below_min_episodes_returns_empty(self):
        summariser = _FakeSummariser([
            _make_episode(
                situation_terms=("niche=pet",),
                outcome="win",
            ),
            _make_episode(
                situation_terms=("niche=pet",),
                outcome="win",
            ),
        ])
        learner = ll.LaunchLearner(
            episode_summariser=summariser,
            principle_extractor=_FakeExtractor(),
            proposal_arbiter=_FakeArbiter(),
            revision_journal=_FakeJournal(),
            min_episodes=5,
            min_confidence=0.5,
        )
        report = learner.distill()
        self.assertEqual(report.episodes_examined, 2)
        self.assertEqual(report.clusters_formed, 0)
        self.assertEqual(report.proposals, [])

    def test_pending_episodes_ignored(self):
        summariser = _FakeSummariser(
            [
                _make_episode(
                    situation_terms=("niche=pet",),
                    outcome="pending",
                )
            ] * 10,
        )
        learner = ll.LaunchLearner(
            episode_summariser=summariser,
            principle_extractor=_FakeExtractor(),
            proposal_arbiter=_FakeArbiter(),
            revision_journal=_FakeJournal(),
            min_episodes=5,
        )
        report = learner.distill()
        # All 10 episodes examined but none relevant
        self.assertEqual(report.clusters_formed, 0)

    def test_clusters_by_niche(self):
        episodes = (
            [
                _make_episode(
                    situation_terms=("niche=pet",),
                    outcome="win",
                )
            ] * 5
        ) + (
            [
                _make_episode(
                    situation_terms=("niche=kitchen",),
                    outcome="loss",
                )
            ] * 5
        )
        summariser = _FakeSummariser(episodes)
        learner = ll.LaunchLearner(
            episode_summariser=summariser,
            principle_extractor=_FakeExtractor(),
            proposal_arbiter=_FakeArbiter(),
            revision_journal=_FakeJournal(),
            min_episodes=5,
            min_confidence=0.3,
        )
        report = learner.distill()
        self.assertEqual(report.clusters_formed, 2)

    def test_mixed_outcome_skipped(self):
        """Cluster with ~50% win rate gets 'skip' verdict."""
        episodes = (
            [_make_episode(
                situation_terms=("niche=pet",),
                outcome="win",
            )] * 5
            + [_make_episode(
                situation_terms=("niche=pet",),
                outcome="loss",
            )] * 5
        )
        summariser = _FakeSummariser(episodes)
        learner = ll.LaunchLearner(
            episode_summariser=summariser,
            principle_extractor=_FakeExtractor(),
            proposal_arbiter=_FakeArbiter(),
            revision_journal=_FakeJournal(),
            min_episodes=5,
        )
        report = learner.distill()
        self.assertEqual(len(report.proposals), 1)
        proposal = report.proposals[0]
        self.assertEqual(
            proposal.arbitration_verdict, "skip",
        )
        self.assertIn("mixed", proposal.note)

    def test_strong_win_accepts(self):
        episodes = [
            _make_episode(
                situation_terms=("niche=pet",),
                outcome="win",
            )
        ] * 8
        summariser = _FakeSummariser(episodes)
        arbiter = _FakeArbiter(
            verdict="accept", reason="strong pattern",
        )
        journal = _FakeJournal()
        learner = ll.LaunchLearner(
            episode_summariser=summariser,
            principle_extractor=_FakeExtractor(),
            proposal_arbiter=arbiter,
            revision_journal=journal,
            min_episodes=5,
            min_confidence=0.5,
        )
        report = learner.distill()
        self.assertEqual(report.accepted, 1)
        proposal = report.proposals[0]
        self.assertEqual(
            proposal.arbitration_verdict, "accept",
        )
        self.assertEqual(
            proposal.journal_revision_id, "rev_abc",
        )
        # Journal propose was called
        self.assertEqual(len(journal.calls), 1)

    def test_strong_loss_avoids(self):
        episodes = [
            _make_episode(
                situation_terms=("niche=beauty",),
                outcome="loss",
            )
        ] * 8
        summariser = _FakeSummariser(episodes)
        learner = ll.LaunchLearner(
            episode_summariser=summariser,
            principle_extractor=_FakeExtractor(),
            proposal_arbiter=_FakeArbiter(
                verdict="accept", reason="strong",
            ),
            revision_journal=_FakeJournal(),
            min_episodes=5,
            min_confidence=0.5,
        )
        report = learner.distill()
        proposal = report.proposals[0]
        self.assertIn("avoid_pattern", proposal.statement)

    def test_low_confidence_skipped(self):
        """Fewer episodes → low confidence → skip."""
        episodes = [
            _make_episode(
                situation_terms=("niche=pet",),
                outcome="win",
            )
        ] * 3
        summariser = _FakeSummariser(episodes)
        learner = ll.LaunchLearner(
            episode_summariser=summariser,
            principle_extractor=_FakeExtractor(),
            proposal_arbiter=_FakeArbiter(),
            revision_journal=_FakeJournal(),
            min_episodes=3,
            min_confidence=0.5,
        )
        report = learner.distill()
        proposal = report.proposals[0]
        self.assertEqual(
            proposal.arbitration_verdict, "skip",
        )
        self.assertIn("min_confidence", proposal.note)

    def test_arbiter_defer_not_accepted(self):
        episodes = [
            _make_episode(
                situation_terms=("niche=pet",),
                outcome="win",
            )
        ] * 10
        summariser = _FakeSummariser(episodes)
        arbiter = _FakeArbiter(verdict="defer", reason="wait")
        journal = _FakeJournal()
        learner = ll.LaunchLearner(
            episode_summariser=summariser,
            principle_extractor=_FakeExtractor(),
            proposal_arbiter=arbiter,
            revision_journal=journal,
            min_episodes=5,
        )
        report = learner.distill()
        proposal = report.proposals[0]
        self.assertEqual(
            proposal.arbitration_verdict, "defer",
        )
        # Journal NOT called
        self.assertEqual(journal.calls, [])

    def test_journal_failure_downgrades_to_skip(self):
        episodes = [
            _make_episode(
                situation_terms=("niche=pet",),
                outcome="win",
            )
        ] * 10
        summariser = _FakeSummariser(episodes)
        learner = ll.LaunchLearner(
            episode_summariser=summariser,
            principle_extractor=_FakeExtractor(),
            proposal_arbiter=_FakeArbiter(verdict="accept"),
            revision_journal=_FakeJournal(raise_exc=True),
            min_episodes=5,
        )
        report = learner.distill()
        proposal = report.proposals[0]
        self.assertEqual(
            proposal.arbitration_verdict, "skip",
        )
        self.assertIn("journal", proposal.note)


# ── Queries ─────────────────────────────────────────────────


class TestQueries(unittest.TestCase):
    def test_recent_and_stats(self):
        summariser = _FakeSummariser([
            _make_episode(
                situation_terms=("niche=pet",),
                outcome="win",
            )
        ] * 6)
        learner = ll.LaunchLearner(
            episode_summariser=summariser,
            principle_extractor=_FakeExtractor(),
            proposal_arbiter=_FakeArbiter(),
            revision_journal=_FakeJournal(),
            min_episodes=5,
        )
        learner.distill()
        learner.distill()
        self.assertEqual(len(learner.recent()), 2)
        stats = learner.stats()
        self.assertEqual(stats["runs"], 2)
        self.assertEqual(stats["total_proposals"], 2)

    def test_reset(self):
        learner = ll.LaunchLearner(
            episode_summariser=_FakeSummariser([]),
            principle_extractor=_FakeExtractor(),
            proposal_arbiter=_FakeArbiter(),
            revision_journal=_FakeJournal(),
        )
        learner.distill()
        self.assertEqual(learner.reset(), 1)


class TestDict(unittest.TestCase):
    def test_proposal_serialises(self):
        p = ll.DistilledProposal(
            id="x", statement="y",
            source_episode_count=5,
            win_rate=0.8,
            avg_confidence=0.7,
            arbitration_verdict="accept",
        )
        d = p.as_dict()
        self.assertEqual(d["id"], "x")
        self.assertAlmostEqual(d["win_rate"], 0.8)

    def test_report_serialises(self):
        learner = ll.LaunchLearner(
            episode_summariser=_FakeSummariser([]),
            principle_extractor=_FakeExtractor(),
            proposal_arbiter=_FakeArbiter(),
            revision_journal=_FakeJournal(),
        )
        report = learner.distill()
        d = report.as_dict()
        self.assertIn("proposals", d)
        self.assertIn("accepted", d)


if __name__ == "__main__":
    unittest.main()
