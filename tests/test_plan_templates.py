"""Tests for ``core.capability_planner.plan_templates``.

Plan templates persistence layer. Pattern J guards.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.capability_planner import plan_templates as pt


@pytest.fixture
def tmp_templates(tmp_path):
    path = tmp_path / "plan_templates.json"
    pt._reset_for_tests(path)
    yield path
    pt._reset_for_tests(
        Path("data/plan_templates.json"),
    )


class TestPatternJ:

    def test_save_short_circuits(self, tmp_templates):
        ok = pt.save_template("d", "advance fleet")
        assert ok is False
        assert not tmp_templates.exists()

    def test_delete_short_circuits(self, tmp_templates):
        tmp_templates.write_text(json.dumps({
            "d": {
                "name": "d", "goal": "g",
                "description": "", "created_at": 0,
            },
        }))
        ok = pt.delete_template("d")
        assert ok is False
        assert tmp_templates.exists()  # not removed

    def test_save_with_guard_off(self, tmp_templates):
        with patch(
            "core.capability_planner.plan_templates."
            "_is_test_environment",
            return_value=False,
        ):
            ok = pt.save_template(
                "d", "advance fleet",
            )
        assert ok is True
        assert tmp_templates.exists()


class TestSaveLoad:

    def _w(self):
        return patch(
            "core.capability_planner.plan_templates."
            "_is_test_environment",
            return_value=False,
        )

    def test_round_trip(self, tmp_templates):
        with self._w():
            pt.save_template(
                "daily",
                "advance fleet",
                description="morning routine",
            )
        t = pt.load_template("daily")
        assert t is not None
        assert t.name == "daily"
        assert t.goal == "advance fleet"
        assert t.description == "morning routine"
        assert t.created_at > 0

    def test_overwrite_preserves_created_at(
        self, tmp_templates,
    ):
        with self._w():
            pt.save_template("d", "g1")
            first = pt.load_template("d")
            pt.save_template("d", "g2")
            second = pt.load_template("d")
        assert second.goal == "g2"
        assert second.created_at == first.created_at

    def test_load_missing_returns_none(
        self, tmp_templates,
    ):
        assert pt.load_template("nope") is None

    def test_invalid_args_rejected(self, tmp_templates):
        with self._w():
            assert (
                pt.save_template("", "g") is False
            )
            assert (
                pt.save_template("n", "") is False
            )

    def test_corrupt_file_fails_open(
        self, tmp_templates,
    ):
        tmp_templates.write_text("not json{")
        assert pt.list_templates() == []
        assert pt.load_template("any") is None


class TestList:

    def _w(self):
        return patch(
            "core.capability_planner.plan_templates."
            "_is_test_environment",
            return_value=False,
        )

    def test_empty(self, tmp_templates):
        assert pt.list_templates() == []

    def test_sorted_by_name(self, tmp_templates):
        with self._w():
            pt.save_template("zeta", "g")
            pt.save_template("alpha", "g")
            pt.save_template("mid", "g")
        rows = pt.list_templates()
        names = [r.name for r in rows]
        assert names == ["alpha", "mid", "zeta"]


class TestDelete:

    def _w(self):
        return patch(
            "core.capability_planner.plan_templates."
            "_is_test_environment",
            return_value=False,
        )

    def test_delete_existing(self, tmp_templates):
        with self._w():
            pt.save_template("d", "g")
            ok = pt.delete_template("d")
        assert ok is True
        assert pt.load_template("d") is None

    def test_delete_missing_returns_false(
        self, tmp_templates,
    ):
        with self._w():
            ok = pt.delete_template("nope")
        assert ok is False


class TestCap:

    def _w(self):
        return patch(
            "core.capability_planner.plan_templates."
            "_is_test_environment",
            return_value=False,
        )

    def test_cap_refuses_new_when_full(
        self, tmp_templates,
    ):
        # Fill to MAX
        with self._w():
            for i in range(pt._MAX_TEMPLATES):
                pt.save_template(f"t_{i}", "g")
            # New template refused
            ok = pt.save_template("overflow", "g")
        assert ok is False

    def test_cap_allows_overwrite_when_full(
        self, tmp_templates,
    ):
        with self._w():
            for i in range(pt._MAX_TEMPLATES):
                pt.save_template(f"t_{i}", "g")
            # Overwrite EXISTING is allowed
            ok = pt.save_template("t_0", "new_goal")
        assert ok is True
        t = pt.load_template("t_0")
        assert t.goal == "new_goal"


class TestClear:

    def test_under_pytest_no_op(self, tmp_templates):
        tmp_templates.write_text("{}")
        pt.clear()
        assert tmp_templates.exists()

    def test_with_guard_off(self, tmp_templates):
        tmp_templates.write_text("{}")
        with patch(
            "core.capability_planner.plan_templates."
            "_is_test_environment",
            return_value=False,
        ):
            pt.clear()
        assert not tmp_templates.exists()
