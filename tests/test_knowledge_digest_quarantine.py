"""Tests for the Engine health section in the digest.

The InsightDigest renders a "## Engine health" section between
"Goal leaderboard" and "Recent decisions" when:

  * any engine is exempt / released / alert-paused, or
  * any AlertEvent fired in the last 7 days.

Both signals fail open: a raising quarantine read or alert-history
read records a ``skipped`` entry and the section degrades to the
remaining available data (or is omitted entirely when both empty).

Coverage:
  1. Section omitted when no flagged engines + no alerts.
  2. Paused-engines table renders with flag + store columns.
  3. Recent-alerts bullet list renders scope + drop.
  4. Source-failure isolation -- quarantine raises, alerts raise.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.knowledge import InsightDigest


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
    """Write the alert_history.json payload directly (bypassing
    the pytest test-env guard in record_alerts)."""
    (data_dir / "alert_history.json").write_text(
        json.dumps(events), encoding="utf-8",
    )


class TestSectionPresence:

    def test_omitted_when_nothing_flagged(self, isolated_data):
        markdown, _ = InsightDigest().render()
        assert "## Engine health" not in markdown

    def test_present_when_paused_engine(self, isolated_data):
        _write_quarantine_state(
            isolated_data,
            alert_paused=[("loyalty", None)],
        )
        markdown, _ = InsightDigest().render()
        assert "## Engine health" in markdown
        assert "Currently flagged engines" in markdown
        assert "[[loyalty]]" in markdown
        assert "alert_paused_fleet" in markdown

    def test_present_when_recent_alert(self, isolated_data):
        now = time.time()
        _seed_alert_events(
            isolated_data,
            [{
                "engine": "loyalty",
                "recorded_at": now - 3600.0,
                "drop": 0.45,
                "recent_score": 1.2,
                "baseline_score": 2.5,
                "store_id": None,
            }],
        )
        markdown, _ = InsightDigest().render()
        assert "## Engine health" in markdown
        assert "Recent degradation alerts" in markdown
        assert "[[loyalty]]" in markdown
        assert "(fleet)" in markdown
        assert "45%" in markdown


class TestPausedEnginesTable:

    def test_per_store_pauses_list_stores(self, isolated_data):
        _write_quarantine_state(
            isolated_data,
            alert_paused=[
                ("loyalty", "store_a"),
                ("loyalty", "store_b"),
            ],
        )
        markdown, _ = InsightDigest().render()
        assert "alert_paused_per_store" in markdown
        assert "`store_a`" in markdown
        assert "`store_b`" in markdown

    def test_exempt_and_released_flags(self, isolated_data):
        _write_quarantine_state(
            isolated_data,
            exemptions=["dynamic_pricing"],
            released=["cart_recovery"],
        )
        markdown, _ = InsightDigest().render()
        assert "exempt" in markdown
        assert "released" in markdown
        assert "[[dynamic_pricing]]" in markdown
        assert "[[cart_recovery]]" in markdown


class TestRecentAlertsBullets:

    def test_scope_and_drop_rendered(self, isolated_data):
        now = time.time()
        _seed_alert_events(
            isolated_data,
            [{
                "engine": "loyalty",
                "recorded_at": now - 1800.0,
                "drop": 0.32,
                "recent_score": 0.9,
                "baseline_score": 2.0,
                "store_id": "store_a",
            }],
        )
        markdown, _ = InsightDigest().render()
        assert "@store_a" in markdown
        assert "32%" in markdown

    def test_capped_at_five(self, isolated_data):
        now = time.time()
        # 7 fresh events; renderer caps to 5
        _seed_alert_events(
            isolated_data,
            [
                {
                    "engine": f"eng_{i}",
                    "recorded_at": now - i * 60.0,
                    "drop": 0.30,
                    "recent_score": 1.0,
                    "baseline_score": 2.0,
                    "store_id": None,
                }
                for i in range(7)
            ],
        )
        markdown, _ = InsightDigest().render()
        for i in range(5):
            assert f"[[eng_{i}]]" in markdown
        for i in (5, 6):
            assert f"[[eng_{i}]]" not in markdown


class TestSourceFailureIsolation:

    def test_quarantine_raise_records_skipped(self, isolated_data):
        with patch(
            "core.approval.quarantine.load_state",
            side_effect=RuntimeError("disk gone"),
        ):
            markdown, stats = InsightDigest().render()
        assert any(
            "engine_health_quarantine" in s
            for s in (stats.skipped or [])
        )
        # Without alerts + without quarantine the section is omitted
        assert "## Engine health" not in markdown

    def test_alerts_raise_records_skipped(self, isolated_data):
        # Quarantine present so the section IS rendered, but alerts
        # raise so the bullet list is absent.
        _write_quarantine_state(
            isolated_data,
            alert_paused=[("loyalty", None)],
        )
        with patch(
            "core.approval.alert_history.recent_history",
            side_effect=RuntimeError("history corrupted"),
        ):
            markdown, stats = InsightDigest().render()
        assert "## Engine health" in markdown
        assert "Currently flagged engines" in markdown
        assert "Recent degradation alerts" not in markdown
        assert any(
            "engine_health_alerts" in s
            for s in (stats.skipped or [])
        )
