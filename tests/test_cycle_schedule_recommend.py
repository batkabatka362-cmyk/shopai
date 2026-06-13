"""Tests for cycle schedule --recommend wireup (W963-60)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import cli


# ── canonical frequency tables ────────────────────────────


class TestFrequencyTables:
    def test_all_three_tables_have_same_keys(self):
        keys = set(cli._CRON_FREQUENCY.keys())
        assert keys == set(cli._SYSTEMD_ON_CALENDAR.keys())
        assert keys == set(cli._WINDOWS_TASK_TRIGGER.keys())

    def test_every_2h_present(self):
        assert "every-2h" in cli._CRON_FREQUENCY
        assert cli._CRON_FREQUENCY["every-2h"] == (
            "0 */2 * * *"
        )

    def test_every_4h_present(self):
        assert "every-4h" in cli._CRON_FREQUENCY
        assert cli._CRON_FREQUENCY["every-4h"] == (
            "0 */4 * * *"
        )


# ── _INTERVAL_TO_FREQ ─────────────────────────────────────


class TestIntervalToFreq:
    def test_known_intervals(self):
        assert cli._INTERVAL_TO_FREQ[1.0] == "hourly"
        assert cli._INTERVAL_TO_FREQ[2.0] == "every-2h"
        assert cli._INTERVAL_TO_FREQ[4.0] == "every-4h"
        assert cli._INTERVAL_TO_FREQ[24.0] == "daily"

    def test_unknown_falls_through(self):
        assert cli._INTERVAL_TO_FREQ.get(3.5) is None


# ── _cmd_cycle_schedule --recommend ───────────────────────


def _args(**kwargs):
    defaults = {
        "frequency": "hourly",
        "platform": "cron",
        "log_file": None,
        "recommend": False,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestRecommendOverride:
    def test_recommend_off_uses_frequency(self, capsys):
        cli._cmd_cycle_schedule(_args(frequency="every-6h"))
        out = capsys.readouterr().out
        assert "every-6h" in out
        # No recommender message when --recommend off
        assert "[W963-60]" not in out

    def test_recommend_picks_hourly(self, capsys):
        fake = SimpleNamespace(
            interval_hours=1.0,
            confidence="low",
            reason="Empty empire test.",
        )
        with patch(
            "engines.cron_recommender.recommender.recommend",
            return_value=fake,
        ):
            cli._cmd_cycle_schedule(
                _args(recommend=True, frequency="daily"),
            )
        out = capsys.readouterr().out
        assert "[W963-60]" in out
        # daily was overridden to hourly
        assert "(hourly," in out
        assert "Empty empire test" in out

    def test_recommend_picks_2h(self, capsys):
        fake = SimpleNamespace(
            interval_hours=2.0,
            confidence="medium",
            reason="Steady-state.",
        )
        with patch(
            "engines.cron_recommender.recommender.recommend",
            return_value=fake,
        ):
            cli._cmd_cycle_schedule(
                _args(recommend=True, frequency="hourly"),
            )
        out = capsys.readouterr().out
        assert "(every-2h," in out

    def test_recommend_picks_4h(self, capsys):
        fake = SimpleNamespace(
            interval_hours=4.0,
            confidence="high",
            reason="Waste reduce.",
        )
        with patch(
            "engines.cron_recommender.recommender.recommend",
            return_value=fake,
        ):
            cli._cmd_cycle_schedule(_args(recommend=True))
        out = capsys.readouterr().out
        assert "(every-4h," in out

    def test_recommend_picks_daily(self, capsys):
        fake = SimpleNamespace(
            interval_hours=24.0,
            confidence="medium",
            reason="Low activity.",
        )
        with patch(
            "engines.cron_recommender.recommender.recommend",
            return_value=fake,
        ):
            cli._cmd_cycle_schedule(_args(recommend=True))
        out = capsys.readouterr().out
        assert "(daily," in out

    def test_recommend_unmapped_interval(self, capsys):
        # 3.5h has no canned mapping -- handler falls back to
        # --frequency (default hourly).
        fake = SimpleNamespace(
            interval_hours=3.5,
            confidence="low",
            reason="weird.",
        )
        with patch(
            "engines.cron_recommender.recommender.recommend",
            return_value=fake,
        ):
            cli._cmd_cycle_schedule(
                _args(
                    recommend=True, frequency="every-6h",
                ),
            )
        out = capsys.readouterr().out
        # Recommender ran but mapping missed; uses default
        assert "(every-6h," in out
        assert "no canned freq match" in out

    def test_recommend_raises_falls_back(self, capsys):
        with patch(
            "engines.cron_recommender.recommender.recommend",
            side_effect=RuntimeError("boom"),
        ):
            cli._cmd_cycle_schedule(
                _args(
                    recommend=True, frequency="every-6h",
                ),
            )
        out = capsys.readouterr().out
        assert "(every-6h," in out
        assert "Recommender unavailable" in out


# ── platforms render the new freqs ─────────────────────────


class TestNewFrequenciesRenderPerPlatform:
    @pytest.mark.parametrize("freq,expect", [
        ("every-2h", "0 */2 * * *"),
        ("every-4h", "0 */4 * * *"),
        ("every-6h", "0 */6 * * *"),
    ])
    def test_cron_renders(self, capsys, freq, expect):
        cli._cmd_cycle_schedule(
            _args(frequency=freq, platform="cron"),
        )
        out = capsys.readouterr().out
        assert expect in out

    @pytest.mark.parametrize("freq,expect", [
        ("every-2h", "0/2:00:00"),
        ("every-4h", "0/4:00:00"),
        ("every-6h", "0/6:00:00"),
    ])
    def test_systemd_renders(self, capsys, freq, expect):
        cli._cmd_cycle_schedule(
            _args(frequency=freq, platform="systemd"),
        )
        out = capsys.readouterr().out
        assert expect in out

    @pytest.mark.parametrize("freq,expect", [
        ("every-2h", "/sc HOURLY /mo 2"),
        ("every-4h", "/sc HOURLY /mo 4"),
        ("every-6h", "/sc HOURLY /mo 6"),
    ])
    def test_windows_renders(self, capsys, freq, expect):
        cli._cmd_cycle_schedule(
            _args(frequency=freq, platform="windows-task"),
        )
        out = capsys.readouterr().out
        assert expect in out
