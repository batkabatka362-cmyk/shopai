"""Launch digest tests."""
from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock

from agents.learning import launch_digest as ld


def _fake_run(
    started_ts: float,
    *,
    launches: int = 1,
    successful: int = 1,
    blocked: int = 0,
):
    run = MagicMock()
    run.started_ts = started_ts
    run.successful_launches = successful
    run.launches = []
    remaining_blocked = blocked
    for _ in range(launches):
        l = MagicMock()
        l.activate_verdict = (
            "blocked" if remaining_blocked > 0 else "activated"
        )
        l.publish_verdict = "ok"
        if remaining_blocked > 0:
            remaining_blocked -= 1
        run.launches.append(l)
    return run


def _fake_report(
    ts: float,
    *,
    proposals: int = 0,
    accepted: int = 0,
):
    r = MagicMock()
    r.ts = ts
    r.proposals = [MagicMock() for _ in range(proposals)]
    r.accepted = accepted
    return r


def _fake_revision(
    status: str, resolved_ts: float = 0.0,
):
    r = MagicMock()
    r.status = status
    r.resolved_ts = resolved_ts
    return r


def _fake_cycle(ended_ts: float, usd_spent: float):
    c = MagicMock()
    c.ended_ts = ended_ts
    c.spent_by_kind = {"usd": usd_spent}
    return c


def _fake_insight(severity: str, statement: str):
    i = MagicMock()
    i.severity = severity
    i.statement = statement
    i.kind = "funnel"
    return i


class TestLabel(unittest.TestCase):
    def test_24h_label(self):
        self.assertEqual(ld._period_label(24), "last 24h")

    def test_7d_label(self):
        self.assertEqual(ld._period_label(7 * 24), "last 7d")

    def test_longer_label(self):
        self.assertEqual(
            ld._period_label(30 * 24), "last 30d",
        )


class TestEmpty(unittest.TestCase):
    def test_all_zero_when_no_inputs(self):
        digest = ld.compose_digest(
            period_hours=1,
            autopilot=MagicMock(
                recent=MagicMock(return_value=[]),
            ),
            launch_learner=MagicMock(
                recent=MagicMock(return_value=[]),
            ),
            revision_journal=MagicMock(
                by_status=MagicMock(return_value=[]),
            ),
            compute_budget=MagicMock(
                archive=MagicMock(return_value=[]),
            ),
            insight_synthesizer=MagicMock(
                active=MagicMock(return_value=[]),
            ),
            mood_model=MagicMock(
                snapshot=MagicMock(
                    return_value=MagicMock(
                        label="balanced",
                    ),
                ),
            ),
            bottleneck_detector=MagicMock(
                top_bottleneck=MagicMock(
                    return_value=None,
                ),
            ),
        )
        self.assertEqual(digest.launches_total, 0)
        self.assertEqual(digest.journal_pending, 0)
        self.assertEqual(digest.mood_label, "balanced")
        self.assertEqual(digest.bottleneck_phase, "(none)")


class TestCounts(unittest.TestCase):
    def setUp(self):
        self.now = time.time()
        self.past = self.now - 3600 * 2    # 2h ago
        self.too_old = self.now - 3600 * 48  # 48h ago

    def test_launches_within_window(self):
        autopilot = MagicMock()
        autopilot.recent.return_value = [
            _fake_run(
                self.past, launches=3,
                successful=2, blocked=1,
            ),
            _fake_run(
                self.too_old, launches=5, successful=5,
            ),
        ]
        digest = ld.compose_digest(
            period_hours=24,
            autopilot=autopilot,
            launch_learner=MagicMock(
                recent=MagicMock(return_value=[]),
            ),
            revision_journal=MagicMock(
                by_status=MagicMock(return_value=[]),
            ),
            compute_budget=MagicMock(
                archive=MagicMock(return_value=[]),
            ),
            insight_synthesizer=MagicMock(
                active=MagicMock(return_value=[]),
            ),
            mood_model=MagicMock(
                snapshot=MagicMock(
                    return_value=MagicMock(label="flow"),
                ),
            ),
            bottleneck_detector=MagicMock(
                top_bottleneck=MagicMock(
                    return_value=None,
                ),
            ),
        )
        # Only the recent run counts
        self.assertEqual(digest.launches_total, 3)
        self.assertEqual(digest.launches_successful, 2)
        self.assertEqual(digest.launches_blocked, 1)

    def test_proposals_counted(self):
        learner = MagicMock()
        learner.recent.return_value = [
            _fake_report(
                self.past, proposals=3, accepted=2,
            ),
            _fake_report(
                self.too_old, proposals=10, accepted=7,
            ),
        ]
        digest = ld.compose_digest(
            period_hours=24,
            autopilot=MagicMock(
                recent=MagicMock(return_value=[]),
            ),
            launch_learner=learner,
            revision_journal=MagicMock(
                by_status=MagicMock(return_value=[]),
            ),
            compute_budget=MagicMock(
                archive=MagicMock(return_value=[]),
            ),
            insight_synthesizer=MagicMock(
                active=MagicMock(return_value=[]),
            ),
            mood_model=MagicMock(
                snapshot=MagicMock(
                    return_value=MagicMock(label="flow"),
                ),
            ),
            bottleneck_detector=MagicMock(
                top_bottleneck=MagicMock(
                    return_value=None,
                ),
            ),
        )
        self.assertEqual(digest.distill_proposals, 3)
        self.assertEqual(digest.distill_accepted, 2)

    def test_journal_window(self):
        journal = MagicMock()
        def by_status(status):
            if status == "proposed":
                return [_fake_revision("proposed")] * 2
            if status == "applied":
                return [
                    _fake_revision(
                        "applied",
                        resolved_ts=self.past,
                    ),
                    _fake_revision(
                        "applied",
                        resolved_ts=self.too_old,
                    ),
                ]
            return []
        journal.by_status = by_status
        digest = ld.compose_digest(
            period_hours=24,
            autopilot=MagicMock(
                recent=MagicMock(return_value=[]),
            ),
            launch_learner=MagicMock(
                recent=MagicMock(return_value=[]),
            ),
            revision_journal=journal,
            compute_budget=MagicMock(
                archive=MagicMock(return_value=[]),
            ),
            insight_synthesizer=MagicMock(
                active=MagicMock(return_value=[]),
            ),
            mood_model=MagicMock(
                snapshot=MagicMock(
                    return_value=MagicMock(label="flow"),
                ),
            ),
            bottleneck_detector=MagicMock(
                top_bottleneck=MagicMock(
                    return_value=None,
                ),
            ),
        )
        self.assertEqual(digest.journal_pending, 2)
        self.assertEqual(digest.journal_applied, 1)

    def test_compute_spend_window(self):
        cb = MagicMock()
        cb.archive.return_value = [
            _fake_cycle(self.past, 0.05),
            _fake_cycle(self.past, 0.03),
            _fake_cycle(self.too_old, 5.0),
        ]
        digest = ld.compose_digest(
            period_hours=24,
            autopilot=MagicMock(
                recent=MagicMock(return_value=[]),
            ),
            launch_learner=MagicMock(
                recent=MagicMock(return_value=[]),
            ),
            revision_journal=MagicMock(
                by_status=MagicMock(return_value=[]),
            ),
            compute_budget=cb,
            insight_synthesizer=MagicMock(
                active=MagicMock(return_value=[]),
            ),
            mood_model=MagicMock(
                snapshot=MagicMock(
                    return_value=MagicMock(label="flow"),
                ),
            ),
            bottleneck_detector=MagicMock(
                top_bottleneck=MagicMock(
                    return_value=None,
                ),
            ),
        )
        self.assertAlmostEqual(
            digest.compute_spent_usd, 0.08, places=4,
        )


class TestRecommendations(unittest.TestCase):
    def _digest(self, **overrides):
        defaults = dict(
            period_hours=24,
            autopilot=MagicMock(
                recent=MagicMock(return_value=[]),
            ),
            launch_learner=MagicMock(
                recent=MagicMock(return_value=[]),
            ),
            revision_journal=MagicMock(
                by_status=MagicMock(return_value=[]),
            ),
            compute_budget=MagicMock(
                archive=MagicMock(return_value=[]),
            ),
            insight_synthesizer=MagicMock(
                active=MagicMock(return_value=[]),
            ),
            mood_model=MagicMock(
                snapshot=MagicMock(
                    return_value=MagicMock(label="flow"),
                ),
            ),
            bottleneck_detector=MagicMock(
                top_bottleneck=MagicMock(
                    return_value=None,
                ),
            ),
        )
        defaults.update(overrides)
        return ld.compose_digest(**defaults)

    def test_no_launches_recs(self):
        d = self._digest()
        self.assertTrue(
            any("No launches" in r for r in d.recommendations),
        )

    def test_high_block_rate_recs(self):
        now = time.time()
        autopilot = MagicMock()
        autopilot.recent.return_value = [
            _fake_run(
                now - 3600,
                launches=5, successful=1, blocked=3,
            ),
        ]
        d = self._digest(autopilot=autopilot)
        self.assertTrue(
            any(
                "High block rate" in r
                for r in d.recommendations
            ),
        )

    def test_pending_recs(self):
        journal = MagicMock()
        journal.by_status.side_effect = lambda s: (
            [_fake_revision("proposed")] * 3
            if s == "proposed" else []
        )
        d = self._digest(revision_journal=journal)
        self.assertTrue(
            any(
                "pending" in r
                for r in d.recommendations
            ),
        )

    def test_stressed_mood_recs(self):
        mood = MagicMock()
        mood.snapshot.return_value = MagicMock(
            label="stressed",
        )
        d = self._digest(mood_model=mood)
        self.assertTrue(
            any(
                "stressed" in r.lower()
                for r in d.recommendations
            ),
        )


class TestRendering(unittest.TestCase):
    def test_as_text_includes_all_fields(self):
        now = time.time()
        d = ld.LaunchDigest(
            period_label="last 24h",
            generated_ts=now,
            launches_total=5,
            launches_successful=4,
            launches_blocked=1,
            distill_proposals=2,
            distill_accepted=1,
            journal_pending=3,
            journal_applied=0,
            compute_spent_usd=0.12,
            mood_label="flow",
            bottleneck_phase="intelligence",
            top_insights=[
                {
                    "severity": "warn",
                    "statement": "cpm trending up",
                    "kind": "pre_breach",
                },
            ],
            recommendations=["Do X", "Do Y"],
            period_start_ts=0.0,
            period_end_ts=now,
        )
        text = d.as_text()
        self.assertIn("last 24h", text)
        self.assertIn("4/5 successful", text)
        self.assertIn("cpm trending up", text)
        self.assertIn("Do X", text)

    def test_as_dict(self):
        d = ld.LaunchDigest(
            period_label="last 24h",
            generated_ts=0.0,
            launches_total=0,
            launches_successful=0,
            launches_blocked=0,
            distill_proposals=0,
            distill_accepted=0,
            journal_pending=0,
            journal_applied=0,
            compute_spent_usd=0.0,
            mood_label="balanced",
            bottleneck_phase="(none)",
            top_insights=[],
            recommendations=[],
            period_start_ts=0.0,
            period_end_ts=0.0,
        )
        serialised = d.as_dict()
        self.assertIn("mood_label", serialised)


class TestExceptionHandling(unittest.TestCase):
    def test_autopilot_raise_survives(self):
        """If one module raises, digest still renders."""
        autopilot = MagicMock()
        autopilot.recent.side_effect = RuntimeError("boom")
        d = ld.compose_digest(
            period_hours=24,
            autopilot=autopilot,
            launch_learner=MagicMock(
                recent=MagicMock(return_value=[]),
            ),
            revision_journal=MagicMock(
                by_status=MagicMock(return_value=[]),
            ),
            compute_budget=MagicMock(
                archive=MagicMock(return_value=[]),
            ),
            insight_synthesizer=MagicMock(
                active=MagicMock(return_value=[]),
            ),
            mood_model=MagicMock(
                snapshot=MagicMock(
                    return_value=MagicMock(label="flow"),
                ),
            ),
            bottleneck_detector=MagicMock(
                top_bottleneck=MagicMock(
                    return_value=None,
                ),
            ),
        )
        # Still renders, launches just 0
        self.assertEqual(d.launches_total, 0)


if __name__ == "__main__":
    unittest.main()
