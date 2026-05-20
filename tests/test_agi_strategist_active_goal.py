"""Tests for ``engines.agi_strategist.active_goal``.

The persistence + controller-bias layer for the AGI
Strategist. Tested:

  1. ``set_active_goal`` runs the strategist + persists.
  2. Strategist failure -> no file written (preserves any
     prior plan).
  3. ``get_active_goal`` reads what was set.
  4. ``clear_active_goal`` removes the file.
  5. ``recommended_engines_for_active_plan`` flattens
     substrategies in priority order with dedup.
  6. Pattern J: the goal file under pytest goes to a temp
     dir so tests don't pollute the operator's real file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from engines.agi_strategist import active_goal as ag
from engines.agi_strategist import (
    clear_active_goal,
    get_active_goal,
    recommended_engines_for_active_plan,
    set_active_goal,
)


def _ok(data):
    return SimpleNamespace(ok=True, data=data, error=None)


def _isolate_goal_file(tmp_path, monkeypatch):
    """Redirect the active-goal file to a tmp path for tests."""
    p = tmp_path / "active_goal.json"
    monkeypatch.setenv("SHOPAI_ACTIVE_GOAL_PATH", str(p))
    return p


# ---------------------------------------------------------------------------
# Set / Get / Clear
# ---------------------------------------------------------------------------


class TestSetGetClear:

    def test_set_then_get_roundtrip(self, tmp_path, monkeypatch):
        goal_file = _isolate_goal_file(tmp_path, monkeypatch)
        # Pattern J is on by default in pytest, so the strategist
        # runs the template path. That's fine -- we're testing
        # persistence, not LLM specifically.
        rec = set_active_goal(goal="Increase revenue 10%")
        assert rec["status"] == "success"
        assert goal_file.exists()

        loaded = get_active_goal()
        assert loaded is not None
        assert loaded["goal"] == "Increase revenue 10%"
        # Plan present + substrategies non-empty
        assert loaded["plan"]["substrategies"]

    def test_clear_removes_file(self, tmp_path, monkeypatch):
        _isolate_goal_file(tmp_path, monkeypatch)
        set_active_goal(goal="Increase revenue")
        assert get_active_goal() is not None
        assert clear_active_goal() is True
        assert get_active_goal() is None
        # Clearing again returns False (file gone)
        assert clear_active_goal() is False

    def test_get_with_no_file_returns_none(self, tmp_path, monkeypatch):
        _isolate_goal_file(tmp_path, monkeypatch)
        assert get_active_goal() is None

    def test_get_with_corrupt_file_returns_none(
        self, tmp_path, monkeypatch,
    ):
        goal_file = _isolate_goal_file(tmp_path, monkeypatch)
        goal_file.write_text("not valid JSON {{{")
        assert get_active_goal() is None


# ---------------------------------------------------------------------------
# Strategist failure -> file NOT clobbered
# ---------------------------------------------------------------------------


class TestStrategistFailurePreservesPrior:

    def test_empty_goal_does_not_overwrite(self, tmp_path, monkeypatch):
        _isolate_goal_file(tmp_path, monkeypatch)
        # First, set a valid plan
        first = set_active_goal(goal="Increase revenue 10%")
        assert first["status"] == "success"
        # Now try with empty goal -- should fail, prior file
        # should remain intact.
        bad = set_active_goal(goal="")
        assert bad["status"] == "error"
        # The previously-set plan is still there
        loaded = get_active_goal()
        assert loaded is not None
        assert loaded["goal"] == "Increase revenue 10%"


# ---------------------------------------------------------------------------
# recommended_engines_for_active_plan -- priority + dedup
# ---------------------------------------------------------------------------


def _write_plan(path: Path, substrategies: list[dict]) -> None:
    """Write a synthetic plan file -- skips the strategist."""
    record = {
        "goal": "Test goal",
        "set_at": 0,
        "horizon_days": 90,
        "plan": {
            "goal": "Test goal",
            "horizon_days": 90,
            "substrategies": substrategies,
            "confidence": 0.5,
            "model_note": "synthetic",
        },
        "status": "success",
        "error": None,
    }
    path.write_text(json.dumps(record))


class TestRecommendedEngines:

    def test_empty_when_no_plan(self, tmp_path, monkeypatch):
        _isolate_goal_file(tmp_path, monkeypatch)
        assert recommended_engines_for_active_plan() == []

    def test_priority_ordering(self, tmp_path, monkeypatch):
        goal_file = _isolate_goal_file(tmp_path, monkeypatch)
        _write_plan(goal_file, [
            {
                "label": "Low priority",
                "priority": 3,
                "recommended_engines": ["upsell"],
            },
            {
                "label": "High priority",
                "priority": 1,
                "recommended_engines": ["bundle", "content_generation"],
            },
            {
                "label": "Mid priority",
                "priority": 2,
                "recommended_engines": ["loyalty"],
            },
        ])
        engines = recommended_engines_for_active_plan()
        # P1 substrategy's engines first, then P2, then P3
        assert engines == [
            "bundle", "content_generation", "loyalty", "upsell",
        ]

    def test_dedup_preserves_first_occurrence(
        self, tmp_path, monkeypatch,
    ):
        goal_file = _isolate_goal_file(tmp_path, monkeypatch)
        _write_plan(goal_file, [
            {
                "label": "A",
                "priority": 1,
                "recommended_engines": ["bundle", "content_generation"],
            },
            {
                "label": "B",
                "priority": 2,
                "recommended_engines": [
                    "content_generation", "loyalty", "bundle",
                ],
            },
        ])
        engines = recommended_engines_for_active_plan()
        # No duplicates; first-occurrence order kept
        assert engines == ["bundle", "content_generation", "loyalty"]

    def test_malformed_substrategies_skipped(
        self, tmp_path, monkeypatch,
    ):
        goal_file = _isolate_goal_file(tmp_path, monkeypatch)
        _write_plan(goal_file, [
            "not a dict",
            {
                "label": "Real",
                "priority": 1,
                "recommended_engines": ["bundle"],
            },
            {
                # Missing recommended_engines key
                "label": "No engines",
                "priority": 1,
            },
        ])
        engines = recommended_engines_for_active_plan()
        assert engines == ["bundle"]

    def test_priority_default_when_missing(
        self, tmp_path, monkeypatch,
    ):
        goal_file = _isolate_goal_file(tmp_path, monkeypatch)
        _write_plan(goal_file, [
            {
                # No priority -- defaults to 3
                "label": "Default",
                "recommended_engines": ["loyalty"],
            },
            {
                "label": "Explicit P1",
                "priority": 1,
                "recommended_engines": ["bundle"],
            },
        ])
        engines = recommended_engines_for_active_plan()
        # P1 before default (P3)
        assert engines == ["bundle", "loyalty"]


# ---------------------------------------------------------------------------
# Pattern J -- pytest path redirected to temp
# ---------------------------------------------------------------------------


class TestPatternJTestIsolation:

    def test_pytest_env_redirects_to_temp(self, monkeypatch):
        """Without the env override, pytest auto-redirects to
        the system temp dir so we never write to the real
        data/.active_goal.json."""
        monkeypatch.delenv("SHOPAI_ACTIVE_GOAL_PATH", raising=False)
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "active")
        path = ag._goal_file()
        # Should be in temp, not under the repo's data/
        assert "shopai_test_active_goal" in str(path)
        # Repo's real path is data/.active_goal.json; ensure
        # we're not pointing there.
        assert "data" + os.sep + ".active_goal.json" not in str(path)
