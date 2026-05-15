"""Tests for ``shopai learning stats`` -- surfaces what Phase 8
has recorded across MemoryIntelligence + DataArchitecture +
LearningLoop.

This is the operator's first window into the OUTPUT of the
autonomous loop (writebacks are the INPUT side). Tests verify
the command:

  - Renders all three sections in the live environment.
  - Honors ``--top N`` for the per-engine + per-domain rankings.
  - Emits a structured JSON envelope.
  - Degrades gracefully when one backend raises -- the other
    two still render.
  - Best-effort: command never crashes the operator's terminal
    even when every backend is broken.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
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
        learning_action="stats",
        json=False,
        top=10,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Default render ──────────────────────────────────────────


class TestDefaultRender:

    def test_renders_all_three_sections(self, cli):
        out, code = _capture(cli._cmd_learning_stats, _ns())
        assert code == 0
        # Three section headers
        assert "Memory Intelligence" in out
        assert "Data Architecture" in out
        assert "Learning Loop" in out

    def test_shows_top_engines(self, cli):
        out, _ = _capture(cli._cmd_learning_stats, _ns(top=5))
        # The "top engines by memory count" sub-header
        assert "top engines by memory count" in out

    def test_top_n_respected(self, cli):
        out_3, _ = _capture(cli._cmd_learning_stats, _ns(top=3))
        out_10, _ = _capture(cli._cmd_learning_stats, _ns(top=10))
        # More entries with top=10 than top=3 (assuming the live
        # MI has at least 10 distinct categories, which it does)
        # Count the indented engine-name lines under "top engines"
        # by counting whitespace+identifier+digits lines
        def _count_cat_rows(text: str) -> int:
            in_section = False
            count = 0
            for line in text.splitlines():
                if "top engines by memory count" in line:
                    in_section = True
                    continue
                if not in_section:
                    continue
                if line.startswith("    "):
                    count += 1
                else:
                    break
            return count
        assert _count_cat_rows(out_3) == 3
        assert _count_cat_rows(out_10) >= 5  # at least more


# ─── JSON envelope ───────────────────────────────────────────


class TestJsonEnvelope:

    def test_json_emits_all_three_sections(self, cli):
        out, code = _capture(
            cli._cmd_learning_stats, _ns(json=True),
        )
        assert code == 0
        data = json.loads(out)
        assert set(data.keys()) == {
            "memory_intelligence",
            "data_architecture",
            "learning_loop",
        }

    def test_mi_section_shape(self, cli):
        out, _ = _capture(
            cli._cmd_learning_stats, _ns(json=True),
        )
        data = json.loads(out)
        mi = data["memory_intelligence"]
        assert "total_memories" in mi
        assert "by_level" in mi
        assert "failures" in mi
        assert "top_categories" in mi
        assert isinstance(mi["top_categories"], list)

    def test_da_section_includes_attach_rate(self, cli):
        out, _ = _capture(
            cli._cmd_learning_stats, _ns(json=True),
        )
        data = json.loads(out)
        da = data["data_architecture"]
        # The KPI operators care about: do actions get outcomes
        # attached?
        assert "result_rate_pct" in da
        # And the top-domains breakdown
        assert "top_domains" in da
        assert isinstance(da["top_domains"], list)


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_mi_failure_doesnt_block_others(self, cli):
        with patch(
            "core.memory.intelligence.MemoryIntelligence",
            side_effect=RuntimeError("MI broken"),
        ):
            out, code = _capture(
                cli._cmd_learning_stats, _ns(),
            )
        # Doesn't crash
        assert code == 0
        # Surfaces the failure inline
        assert "[??] Memory Intelligence" in out
        assert "MI broken" in out
        # Other sections still render
        assert "Data Architecture" in out
        assert "Learning Loop" in out

    def test_da_failure_isolated(self, cli):
        with patch(
            "core.data.architecture.DataArchitecture",
            side_effect=RuntimeError("DA down"),
        ):
            out, code = _capture(
                cli._cmd_learning_stats, _ns(),
            )
        assert code == 0
        assert "[??] Data Architecture" in out

    def test_ll_failure_isolated(self, cli):
        with patch(
            "core.brain.learning_loop.LearningLoop",
            side_effect=RuntimeError("LL down"),
        ):
            out, code = _capture(
                cli._cmd_learning_stats, _ns(),
            )
        assert code == 0
        assert "[??] Learning Loop" in out

    def test_all_three_failing_still_renders(self, cli):
        with patch(
            "core.memory.intelligence.MemoryIntelligence",
            side_effect=RuntimeError("broken"),
        ), patch(
            "core.data.architecture.DataArchitecture",
            side_effect=RuntimeError("broken"),
        ), patch(
            "core.brain.learning_loop.LearningLoop",
            side_effect=RuntimeError("broken"),
        ):
            out, code = _capture(
                cli._cmd_learning_stats, _ns(),
            )
        assert code == 0
        assert "[??] Memory Intelligence" in out
        assert "[??] Data Architecture" in out
        assert "[??] Learning Loop" in out


# ─── Dispatcher ──────────────────────────────────────────────


class TestDispatcher:

    def test_unknown_verb_shows_usage(self, cli):
        out, code = _capture(
            cli._cmd_learning,
            argparse.Namespace(learning_action="not_a_verb"),
        )
        assert code == 1
        assert "Usage" in out
        assert "shopai learning stats" in out

    def test_stats_verb_dispatches(self, cli):
        """`shopai learning stats` reaches _cmd_learning_stats
        through the verb dispatcher."""
        ns = argparse.Namespace(
            learning_action="stats", json=True, top=3,
        )
        out, code = _capture(cli._cmd_learning, ns)
        assert code == 0
        # JSON envelope rendered (the stats command emitted it)
        data = json.loads(out)
        assert "memory_intelligence" in data
