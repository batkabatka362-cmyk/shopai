"""Tests for ``core.approval.engine_health``.

The scorer composes approval-queue + quarantine + alert-history
signals into a 1..10 score with a verdict. Tests cover:

  1. Healthy engine -> score 10, verdict ``healthy``.
  2. Each penalty rule fires the expected score deduction:
     alert_paused (-4), alert streak per-day (-2 each, capped -4),
     low outcome_score (-2 when polarised >=5), failure rate
     (-1 when recent_total >=5), released (-1).
  3. Bonus rule: high outcome_score (+1) when polarised >=5.
  4. Score is clamped to [1, 10] -- multi-failure stack doesn't
     push score below 1.
  5. Verdict transitions on threshold boundaries (5, 8).
  6. Concerns list mentions every penalty that fired.
  7. Source-failure isolation: a raising quarantine load OR
     alert_history read produces a valid (possibly conservative)
     EngineHealth rather than crashing.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.approval.engine_health import (
    EngineHealth,
    score_engine,
)


@pytest.fixture
def isolated_data(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    return tmp_path


def _write_quarantine_state(
    data_dir: Path,
    *,
    exemptions=(),
    released=(),
    alert_paused=(),
) -> None:
    payload = {
        "exemptions": list(exemptions),
        "released": list(released),
        "alert_paused": [list(p) for p in alert_paused],
    }
    (data_dir / "quarantine_state.json").write_text(
        json.dumps(payload), encoding="utf-8",
    )


def _seed_alert_events(
    data_dir: Path,
    events: list[dict],
) -> None:
    (data_dir / "alert_history.json").write_text(
        json.dumps(events), encoding="utf-8",
    )


def _fake_queue(
    *,
    executed: int = 0,
    failed: int = 0,
    pending: int = 0,
    outcome_score=None,
    positive: int = 0,
    negative: int = 0,
):
    q = MagicMock()
    q.stats_by_engine.return_value = {
        "loyalty": {
            "executed": executed,
            "failed": failed,
            "pending": pending,
        },
    }
    q.engine_outcome_stats.return_value = {
        "outcome_score": outcome_score,
        "positive_count": positive,
        "negative_count": negative,
        "neutral_count": 0,
        "total_outcomes": positive + negative,
        "total_revenue": 0.0,
    }
    return q


# --- Healthy path ----------------------------------------------


class TestHealthy:

    def test_clean_engine_scores_ten(self, isolated_data):
        health = score_engine(
            "loyalty", queue=_fake_queue(executed=10),
        )
        assert health.score == 10
        assert health.verdict == "healthy"
        assert health.concerns == []

    def test_high_outcome_score_clamped_at_ten(
        self, isolated_data,
    ):
        health = score_engine(
            "loyalty",
            queue=_fake_queue(
                executed=10,
                outcome_score=0.85,
                positive=8, negative=1,
            ),
        )
        # Bonus would push past 10; clamp keeps it at 10
        assert health.score == 10


# --- Individual penalties --------------------------------------


class TestAlertPaused:

    def test_alert_paused_deducts_four(self, isolated_data):
        _write_quarantine_state(
            isolated_data,
            alert_paused=[("loyalty", None)],
        )
        health = score_engine(
            "loyalty", queue=_fake_queue(executed=10),
        )
        # 10 - 4 = 6
        assert health.score == 6
        assert health.verdict == "warning"
        assert any("alert_paused" in c for c in health.concerns)

    def test_per_store_pause_also_counts(self, isolated_data):
        _write_quarantine_state(
            isolated_data,
            alert_paused=[("loyalty", "store_a")],
        )
        health = score_engine(
            "loyalty", queue=_fake_queue(executed=10),
        )
        # is_alert_paused() returns True for fleet OR any store
        # match when checking with store_id=None, since the
        # quarantine.is_alert_paused(engine) (no store_id)
        # only matches the fleet pause.
        # So per-store pause does NOT score-penalize the fleet
        # health-check here.
        # Actually: signals["alert_paused"] comes from
        # state.is_alert_paused(engine) with no store_id, which
        # only returns True for (engine, None) entries.
        # So this test verifies that per-store pauses don't
        # accidentally fire the fleet penalty.
        assert health.score == 10


class TestAlertStreak:

    def test_one_day_streak_deducts_two(self, isolated_data):
        now = time.time()
        _seed_alert_events(isolated_data, [{
            "engine": "loyalty",
            "recorded_at": now - 3600.0,
            "drop": 0.30,
            "recent_score": 1.0,
            "baseline_score": 2.0,
            "store_id": None,
        }])
        health = score_engine(
            "loyalty",
            queue=_fake_queue(executed=10),
            now=now,
        )
        assert health.score == 8
        assert health.verdict == "healthy"

    def test_three_day_streak_capped_at_four(
        self, isolated_data,
    ):
        now = time.time()
        events = [
            {
                "engine": "loyalty",
                "recorded_at": now - day * 86400.0,
                "drop": 0.30,
                "recent_score": 1.0,
                "baseline_score": 2.0,
                "store_id": None,
            }
            for day in range(3)
        ]
        _seed_alert_events(isolated_data, events)
        health = score_engine(
            "loyalty",
            queue=_fake_queue(executed=10),
            now=now,
        )
        # 2 * 3 = 6 raw penalty, capped at -4 -> 10 - 4 = 6
        assert health.score == 6


class TestOutcomeScorePenalty:

    def test_low_outcome_score_deducts_two(self, isolated_data):
        health = score_engine(
            "loyalty",
            queue=_fake_queue(
                executed=10,
                outcome_score=0.30,
                positive=3, negative=7,
            ),
        )
        assert health.score == 8

    def test_low_outcome_but_low_sample_no_penalty(
        self, isolated_data,
    ):
        # polarised=2 -> below 5 sample threshold
        health = score_engine(
            "loyalty",
            queue=_fake_queue(
                executed=10,
                outcome_score=0.20,
                positive=1, negative=1,
            ),
        )
        assert health.score == 10


class TestFailureRate:

    def test_high_failure_rate_deducts_one(
        self, isolated_data,
    ):
        # 5 executed, 5 failed -> 50% failure rate
        health = score_engine(
            "loyalty",
            queue=_fake_queue(executed=5, failed=5),
        )
        assert health.score == 9

    def test_low_failure_rate_no_penalty(self, isolated_data):
        # 9 executed, 1 failed -> 10% failure rate
        health = score_engine(
            "loyalty",
            queue=_fake_queue(executed=9, failed=1),
        )
        assert health.score == 10


class TestReleased:

    def test_released_deducts_one(self, isolated_data):
        _write_quarantine_state(
            isolated_data,
            released=["loyalty"],
        )
        health = score_engine(
            "loyalty", queue=_fake_queue(executed=10),
        )
        assert health.score == 9
        assert any("released" in c for c in health.concerns)


# --- Clamping + verdict thresholds ----------------------------


class TestClamping:

    def test_multi_penalty_clamped_to_one(self, isolated_data):
        now = time.time()
        _write_quarantine_state(
            isolated_data,
            released=["loyalty"],
            alert_paused=[("loyalty", None)],
        )
        events = [
            {
                "engine": "loyalty",
                "recorded_at": now - day * 86400.0,
                "drop": 0.50,
                "recent_score": 0.5,
                "baseline_score": 2.5,
                "store_id": None,
            }
            for day in range(4)
        ]
        _seed_alert_events(isolated_data, events)
        # alert_paused -4, streak capped -4, low score -2,
        # failure_rate -1, released -1 = 12 penalty -> floor to 1
        health = score_engine(
            "loyalty",
            queue=_fake_queue(
                executed=5,
                failed=5,
                outcome_score=0.20,
                positive=1, negative=8,
            ),
            now=now,
        )
        assert health.score == 1
        assert health.verdict == "unhealthy"


class TestVerdictThresholds:

    def test_score_eight_is_healthy(self, isolated_data):
        # Force score=8 via one-day alert streak (-2)
        now = time.time()
        _seed_alert_events(isolated_data, [{
            "engine": "loyalty",
            "recorded_at": now - 3600.0,
            "drop": 0.30,
            "recent_score": 1.0,
            "baseline_score": 2.0,
            "store_id": None,
        }])
        health = score_engine(
            "loyalty",
            queue=_fake_queue(executed=10),
            now=now,
        )
        assert health.score == 8
        assert health.verdict == "healthy"

    def test_score_five_is_warning(self, isolated_data):
        _write_quarantine_state(
            isolated_data,
            alert_paused=[("loyalty", None)],
        )
        # alert_paused -4, low outcome -2 = score 4 -> unhealthy
        # adjust to get score=5 -> only alert_paused + released
        # (-4 -1 = score 5)
        _write_quarantine_state(
            isolated_data,
            alert_paused=[("loyalty", None)],
            released=["loyalty"],
        )
        health = score_engine(
            "loyalty",
            queue=_fake_queue(executed=10),
        )
        assert health.score == 5
        assert health.verdict == "warning"

    def test_score_four_is_unhealthy(self, isolated_data):
        _write_quarantine_state(
            isolated_data,
            alert_paused=[("loyalty", None)],
        )
        # alert_paused -4, low outcome -2 -> score 4
        health = score_engine(
            "loyalty",
            queue=_fake_queue(
                executed=10,
                outcome_score=0.20,
                positive=1, negative=8,
            ),
        )
        assert health.score == 4
        assert health.verdict == "unhealthy"


# --- Source-failure isolation ---------------------------------


class TestSourceFailureIsolation:

    def test_quarantine_raise_still_returns_health(
        self, isolated_data,
    ):
        with patch(
            "core.approval.quarantine.load_state",
            side_effect=RuntimeError("disk gone"),
        ):
            health = score_engine(
                "loyalty",
                queue=_fake_queue(executed=10),
            )
        # Falls back to "no signal" -> score reflects only other
        # readable signals.
        assert isinstance(health, EngineHealth)
        assert health.engine == "loyalty"
        assert health.signals["alert_paused"] is False

    def test_alert_history_raise_still_returns_health(
        self, isolated_data,
    ):
        with patch(
            "core.approval.alert_history.recent_history",
            side_effect=RuntimeError("history corrupted"),
        ):
            health = score_engine(
                "loyalty",
                queue=_fake_queue(executed=10),
            )
        assert isinstance(health, EngineHealth)
        assert health.signals["alert_streak_7d"] == 0
        assert health.signals["last_alert_at"] is None

    def test_queue_raise_still_returns_health(
        self, isolated_data,
    ):
        q = MagicMock()
        q.stats_by_engine.side_effect = RuntimeError("queue dead")
        q.engine_outcome_stats.side_effect = RuntimeError("queue dead")
        health = score_engine("loyalty", queue=q)
        assert isinstance(health, EngineHealth)
        assert health.signals["executed"] == 0
        assert health.signals["failed"] == 0


# --- Serialization --------------------------------------------


class TestToDict:

    def test_to_dict_roundtrips_all_fields(self, isolated_data):
        health = score_engine(
            "loyalty",
            queue=_fake_queue(executed=10),
        )
        d = health.to_dict()
        assert d["engine"] == "loyalty"
        assert d["score"] == 10
        assert d["verdict"] == "healthy"
        assert "signals" in d
        assert "concerns" in d
