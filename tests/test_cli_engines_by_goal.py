"""Tests for ``shopai engines --by-goal`` and ``--unmapped`` —
operator views over the engine→goal mapping.

The default ``shopai engines`` lists all 131 engines alphabetically.
That's the right answer to "what engines exist?" but the wrong
answer to two more useful questions:

  1. "Which engines work toward each business goal?" — needs
     grouping by ENGINE_GOAL_MAP.
  2. "Which engines emit actions that nobody attributes a goal
     to?" — the unmapped engines whose outcomes never feed any
     EMA.
"""
from __future__ import annotations

import importlib.util
from io import StringIO
from unittest.mock import patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs) -> str:
    buf = StringIO()
    with patch("sys.stdout", buf):
        fn(*args, **kwargs)
    return buf.getvalue()


# ─── default flat listing ─────────────────────────────────────────


class TestDefaultListing:

    def test_default_lists_all(self, cli):
        out = _capture(cli._cmd_engines)
        assert "Registered engines:" in out
        # Spot-check a few known engines (any of these absent
        # would indicate registry corruption, not test failure)
        for engine in ("pricing", "loyalty", "cart_recovery"):
            assert engine in out

    def test_default_does_not_group(self, cli):
        out = _capture(cli._cmd_engines)
        assert "grouped by goal" not in out
        assert "maximize_profit (" not in out


# ─── --by-goal grouped view ───────────────────────────────────────


class TestByGoal:

    def test_grouped_header(self, cli):
        out = _capture(cli._cmd_engines, by_goal=True)
        assert "grouped by goal" in out

    def test_known_goals_present(self, cli):
        out = _capture(cli._cmd_engines, by_goal=True)
        # The five canonical goals + unmapped bucket
        for goal in (
            "capture_opportunity",
            "grow_customers",
            "increase_aov",
            "maximize_profit",
            "survive_crisis",
            "unmapped",
        ):
            assert goal in out, f"missing group: {goal}"

    def test_engine_appears_under_its_goal(self, cli):
        """cart_recovery → grow_customers per ENGINE_GOAL_MAP."""
        out = _capture(cli._cmd_engines, by_goal=True)
        # Each group block is delimited; cart_recovery should
        # appear after grow_customers and before the next group.
        lines = out.splitlines()
        grow_idx = next(
            i for i, l in enumerate(lines)
            if l.startswith("grow_customers")
        )
        next_group_idx = next(
            i for i, l in enumerate(lines[grow_idx + 1:], grow_idx + 1)
            if l and not l.startswith(" ") and "(" in l
        )
        block = lines[grow_idx:next_group_idx]
        assert any("cart_recovery" in l for l in block)

    def test_unmapped_listed_last(self, cli):
        out = _capture(cli._cmd_engines, by_goal=True)
        # Find indices of all top-level group headers
        group_headers = [
            l for l in out.splitlines()
            if l and not l.startswith(" ") and "(" in l
        ]
        assert group_headers[-1].startswith("unmapped"), (
            f"unmapped should be last; got {group_headers[-1]}"
        )


# ─── --unmapped filter ────────────────────────────────────────────


class TestUnmapped:

    def test_lists_only_unmapped(self, cli):
        """All listed engines are absent from ENGINE_GOAL_MAP."""
        from core.goals.engine_goal_map import ENGINE_GOAL_MAP

        out = _capture(cli._cmd_engines, unmapped=True)
        # Extract engine names from the numbered list
        engine_names = []
        for line in out.splitlines():
            stripped = line.strip()
            # Format: "  N. engine_name"
            if stripped and stripped[0].isdigit() and "." in stripped:
                _, _, name = stripped.partition(". ")
                if name:
                    engine_names.append(name.strip())

        assert engine_names, "no engines parsed from --unmapped output"
        # None of them should be in the goal map
        for name in engine_names:
            assert name not in ENGINE_GOAL_MAP, (
                f"engine {name!r} listed as unmapped but is in the map"
            )

    def test_header_count_matches(self, cli):
        """Header says 'Unmapped engines (N of M registered)' —
        the N should equal the number of engines listed."""
        out = _capture(cli._cmd_engines, unmapped=True)
        first_line = out.splitlines()[0]
        # "Unmapped engines (97 of 131 registered):"
        import re
        m = re.match(
            r"Unmapped engines \((\d+) of (\d+) registered\):",
            first_line,
        )
        assert m, f"unexpected header: {first_line}"
        n_unmapped = int(m.group(1))
        engine_lines = [
            l for l in out.splitlines()
            if l.strip() and l.strip()[0].isdigit()
        ]
        assert len(engine_lines) == n_unmapped

    def test_no_unmapped_clean_message(self, cli):
        """If every engine were mapped, the command says so
        explicitly rather than dumping an empty list."""
        # Mock ENGINE_GOAL_MAP to cover every registered engine
        from engines.registry import list_engines
        full_map = {name: "maximize_profit" for name in list_engines()}
        with patch(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP", full_map,
        ):
            out = _capture(cli._cmd_engines, unmapped=True)
        assert "All registered engines have a primary-goal mapping" in out
