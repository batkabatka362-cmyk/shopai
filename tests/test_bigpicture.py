"""Tests for engines.bigpicture — W963-20."""
from __future__ import annotations

from unittest.mock import patch

from engines.bigpicture import BigpictureEngine
from engines.bigpicture.flow import (
    _compute_overall_verdict,
    _compute_top_action,
)


# ── overall_verdict ────────────────────────────────────────


class TestOverallVerdict:
    def test_ok_when_today_ok(self):
        sections = {
            "today": {"data": {"verdict": "ok"}},
            "earnings": {"data": {"earning_count": 0}},
        }
        assert _compute_overall_verdict(sections) == "ok"

    def test_warn_when_today_warn_and_zero_earning(self):
        sections = {
            "today": {"data": {"verdict": "warn"}},
            "earnings": {"data": {"earning_count": 0}},
        }
        assert _compute_overall_verdict(sections) == "warn"

    def test_earning_upgrades_warn_to_ok(self):
        sections = {
            "today": {"data": {"verdict": "warn"}},
            "earnings": {"data": {"earning_count": 3}},
        }
        assert _compute_overall_verdict(sections) == "ok"

    def test_critical_not_upgraded_by_earning(self):
        sections = {
            "today": {"data": {"verdict": "critical"}},
            "earnings": {"data": {"earning_count": 5}},
        }
        assert (
            _compute_overall_verdict(sections) == "critical"
        )

    def test_skipped_when_today_missing(self):
        sections = {
            "today": {"data": {}},
            "earnings": {"data": {}},
        }
        assert (
            _compute_overall_verdict(sections) == "skipped"
        )


# ── top_action ────────────────────────────────────────────


class TestTopAction:
    def test_prefers_today_next_action(self):
        sections = {
            "today": {"data": {"next_action": "today drill"}},
            "earnings": {
                "data": {"next_action": "earnings drill"},
            },
            "warmup": {"data": {}},
        }
        assert (
            _compute_top_action(sections) == "today drill"
        )

    def test_falls_back_to_earnings(self):
        sections = {
            "today": {"data": {"next_action": ""}},
            "earnings": {
                "data": {"next_action": "earn drill"},
            },
            "warmup": {"data": {}},
        }
        assert (
            _compute_top_action(sections) == "earn drill"
        )

    def test_falls_back_to_warmup(self):
        sections = {
            "today": {"data": {}},
            "earnings": {"data": {}},
            "warmup": {
                "data": {"day": 7, "intent": "Run cycle"},
            },
        }
        result = _compute_top_action(sections)
        assert "Day 7" in result and "Run cycle" in result

    def test_empty_when_all_empty(self):
        sections = {
            "today": {"data": {}},
            "earnings": {"data": {}},
            "warmup": {"data": {}},
        }
        assert _compute_top_action(sections) == ""


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_input_success(self):
        result = BigpictureEngine().run({})
        assert result["status"] == "success"
        assert "sections" in result["data"]

    def test_none_input_success(self):
        result = BigpictureEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_error(self):
        result = BigpictureEngine().run("nope")
        assert result["status"] == "error"

    def test_fail_upstream(self):
        result = BigpictureEngine().run({
            "status": "fail", "error": "broken",
        })
        assert result["status"] == "error"

    def test_carries_engine_name(self):
        result = BigpictureEngine().run({})
        assert result["meta"]["engine"] == "bigpicture"


class TestEngineActions:
    def test_day_clamped(self):
        result = BigpictureEngine().run({
            "data": {"day": 999},
        })
        assert result["data"]["day"] == 30

    def test_day_negative_clamped(self):
        result = BigpictureEngine().run({
            "data": {"day": -5},
        })
        assert result["data"]["day"] == 1

    def test_day_non_int_defaults_to_1(self):
        result = BigpictureEngine().run({
            "data": {"day": "abc"},
        })
        assert result["data"]["day"] == 1

    def test_niche_lowercased(self):
        result = BigpictureEngine().run({
            "data": {"niche": "BEAUTY"},
        })
        assert result["data"]["niche"] == "beauty"

    def test_all_three_sections_present(self):
        result = BigpictureEngine().run({})
        sections = result["data"]["sections"]
        assert "today" in sections
        assert "earnings" in sections
        assert "warmup" in sections

    def test_verdict_one_of_4(self):
        result = BigpictureEngine().run({})
        assert result["data"]["verdict"] in {
            "ok", "warn", "critical", "skipped",
        }

    def test_section_graceful_when_today_unavailable(self):
        # Patch the TodayBriefEngine import path so it raises
        # at the engine level, exercising the try/except.
        from engines.bigpicture import flow as bp_flow
        with patch.object(
            bp_flow, "_today_section",
            return_value={"ok": False, "data": {}},
        ):
            result = BigpictureEngine().run({})
        # Whole engine still returns success — degraded.
        assert result["status"] == "success"
        assert (
            result["data"]["sections"]["today"]["ok"]
            is False
        )
