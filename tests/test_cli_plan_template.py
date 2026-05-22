"""Tests for ``shopai plan-template`` CLI subcommands."""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "shopai_cli", "cli.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kw):
    defaults = dict(
        plan_template_action="list",
        name=None,
        goal=None,
        description="",
        execute=False,
        yes=False,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class TestList:

    def test_empty_list(self, cli):
        with patch(
            "core.capability_planner.plan_templates."
            "list_templates",
            return_value=[],
        ):
            out, code = _capture(
                cli._cmd_plan_template,
                _ns(plan_template_action="list"),
            )
        assert code == 0
        assert "No plan templates saved" in out

    def test_list_rows_render(self, cli):
        from core.capability_planner.plan_templates import (
            PlanTemplate,
        )
        with patch(
            "core.capability_planner.plan_templates."
            "list_templates",
            return_value=[
                PlanTemplate(
                    name="daily",
                    goal="advance fleet",
                    description="morning",
                    created_at=1700000000.0,
                ),
            ],
        ):
            out, code = _capture(
                cli._cmd_plan_template,
                _ns(plan_template_action="list"),
            )
        assert code == 0
        assert "daily" in out
        assert "advance fleet" in out

    def test_list_json(self, cli):
        from core.capability_planner.plan_templates import (
            PlanTemplate,
        )
        with patch(
            "core.capability_planner.plan_templates."
            "list_templates",
            return_value=[
                PlanTemplate(
                    name="t",
                    goal="g",
                    description="",
                    created_at=0,
                ),
            ],
        ):
            out, _ = _capture(
                cli._cmd_plan_template,
                _ns(
                    plan_template_action="list",
                    json=True,
                ),
            )
        data = json.loads(out)
        assert len(data) == 1
        assert data[0]["name"] == "t"

    def test_default_action_list(self, cli):
        """No subcommand -> list (default)."""
        with patch(
            "core.capability_planner.plan_templates."
            "list_templates",
            return_value=[],
        ):
            out, _ = _capture(
                cli._cmd_plan_template,
                _ns(plan_template_action=None),
            )
        assert "No plan templates saved" in out


class TestSave:

    def test_save_calls_module(self, cli):
        with patch(
            "core.capability_planner.plan_templates."
            "save_template",
            return_value=True,
        ) as mock_save:
            out, code = _capture(
                cli._cmd_plan_template,
                _ns(
                    plan_template_action="save",
                    name="daily",
                    goal="advance fleet",
                    description="morning",
                ),
            )
        assert code == 0
        mock_save.assert_called_once_with(
            "daily",
            "advance fleet",
            description="morning",
        )
        assert "Saved template 'daily'" in out

    def test_save_missing_args_exits(self, cli):
        out, code = _capture(
            cli._cmd_plan_template,
            _ns(
                plan_template_action="save",
                name="",
                goal="g",
            ),
        )
        assert code == 1


class TestDelete:

    def test_delete_calls_module(self, cli):
        with patch(
            "core.capability_planner.plan_templates."
            "delete_template",
            return_value=True,
        ) as mock_del:
            out, code = _capture(
                cli._cmd_plan_template,
                _ns(
                    plan_template_action="delete",
                    name="daily",
                ),
            )
        assert code == 0
        mock_del.assert_called_once_with("daily")
        assert "Deleted template 'daily'" in out


class TestShow:

    def test_show_unknown_exits_1(self, cli):
        with patch(
            "core.capability_planner.plan_templates."
            "load_template",
            return_value=None,
        ):
            out, code = _capture(
                cli._cmd_plan_template,
                _ns(
                    plan_template_action="show",
                    name="ghost",
                ),
            )
        assert code == 1

    def test_show_renders_fields(self, cli):
        from core.capability_planner.plan_templates import (
            PlanTemplate,
        )
        with patch(
            "core.capability_planner.plan_templates."
            "load_template",
            return_value=PlanTemplate(
                name="daily",
                goal="advance fleet",
                description="morning",
                created_at=1700000000.0,
            ),
        ):
            out, code = _capture(
                cli._cmd_plan_template,
                _ns(
                    plan_template_action="show",
                    name="daily",
                ),
            )
        assert code == 0
        assert "Template: daily" in out
        assert "advance fleet" in out
        assert "morning" in out


class TestRun:

    def test_run_unknown_exits_1(self, cli):
        with patch(
            "core.capability_planner.plan_templates."
            "load_template",
            return_value=None,
        ):
            out, code = _capture(
                cli._cmd_plan_template,
                _ns(
                    plan_template_action="run",
                    name="ghost",
                ),
            )
        assert code == 1

    def test_run_passes_goal_to_plan(self, cli):
        from core.capability_planner.plan_templates import (
            PlanTemplate,
        )
        with patch(
            "core.capability_planner.plan_templates."
            "load_template",
            return_value=PlanTemplate(
                name="daily",
                goal="advance fleet",
                description="",
                created_at=0,
            ),
        ), patch.object(
            cli, "_cmd_plan",
        ) as mock_plan:
            _capture(
                cli._cmd_plan_template,
                _ns(
                    plan_template_action="run",
                    name="daily",
                    yes=True,
                    execute=True,
                ),
            )
        # _cmd_plan called with synthesized namespace
        assert mock_plan.call_count == 1
        inner = mock_plan.call_args.args[0]
        assert inner.goal == "advance fleet"
        assert inner.yes is True
        assert inner.execute is True
