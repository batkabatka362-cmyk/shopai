"""Tests for ``shopai engine pulse <engine>``.

The pulse handler is a thin wrapper around
``core.approval.engine_health.score_engine``. These tests verify:

  1. JSON envelope shape matches ``EngineHealth.to_dict``.
  2. Text render carries the verdict line + signals.
  3. Exit code 1 when verdict is ``unhealthy``, 0 otherwise.
  4. Cron usability: short output, structured score.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import patch

import pytest

from core.approval.engine_health import EngineHealth


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
        engine_name="loyalty",
        json=False,
        fleet=False,
        verdict=None,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _make_health(
    *, engine: str = "loyalty",
    score: int = 10,
    verdict: str = "healthy",
    concerns=None,
    signals=None,
):
    return EngineHealth(
        engine=engine,
        score=score,
        verdict=verdict,
        signals=signals or {
            "executed": 5, "failed": 0, "pending": 0,
            "outcome_score": 0.8,
            "alert_streak_7d": 0, "alert_paused": False,
        },
        concerns=concerns or [],
    )


class TestJsonOutput:

    def test_envelope_shape(self, cli):
        with patch(
            "core.approval.engine_health.score_engine",
            return_value=_make_health(),
        ):
            out, code = _capture(
                cli._cmd_engine_pulse, _ns(json=True),
            )
        data = json.loads(out)
        assert data["engine"] == "loyalty"
        assert data["score"] == 10
        assert data["verdict"] == "healthy"
        assert "signals" in data
        assert "concerns" in data
        assert code == 0

    def test_unhealthy_exits_one(self, cli):
        with patch(
            "core.approval.engine_health.score_engine",
            return_value=_make_health(
                score=3, verdict="unhealthy",
                concerns=["engine is alert_paused"],
            ),
        ):
            out, code = _capture(
                cli._cmd_engine_pulse, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["verdict"] == "unhealthy"


class TestTextOutput:

    def test_one_line_summary(self, cli):
        with patch(
            "core.approval.engine_health.score_engine",
            return_value=_make_health(),
        ):
            out, code = _capture(
                cli._cmd_engine_pulse, _ns(),
            )
        assert "Engine pulse: loyalty" in out
        assert "score=10/10" in out
        assert "verdict=healthy" in out
        assert code == 0

    def test_concerns_listed_under_warning(self, cli):
        with patch(
            "core.approval.engine_health.score_engine",
            return_value=_make_health(
                score=6, verdict="warning",
                concerns=["engine is alert_paused"],
            ),
        ):
            out, _ = _capture(cli._cmd_engine_pulse, _ns())
        assert "verdict=warning" in out
        assert "Concerns:" in out
        assert "alert_paused" in out

    def test_signals_block_rendered(self, cli):
        with patch(
            "core.approval.engine_health.score_engine",
            return_value=_make_health(
                signals={
                    "executed": 12, "failed": 2, "pending": 1,
                    "outcome_score": 0.75,
                    "alert_streak_7d": 0,
                    "alert_paused": False,
                },
            ),
        ):
            out, _ = _capture(cli._cmd_engine_pulse, _ns())
        assert "executed=12" in out
        assert "failed=2" in out
        assert "outcome_score=75%" in out

    def test_outcome_score_na_when_none(self, cli):
        with patch(
            "core.approval.engine_health.score_engine",
            return_value=_make_health(
                signals={
                    "executed": 0, "failed": 0, "pending": 0,
                    "outcome_score": None,
                    "alert_streak_7d": 0,
                    "alert_paused": False,
                },
            ),
        ):
            out, _ = _capture(cli._cmd_engine_pulse, _ns())
        assert "outcome_score=n/a" in out


class TestExitCodes:

    @pytest.mark.parametrize(
        "verdict,expected_code",
        [
            ("healthy", 0),
            ("warning", 0),
            ("unhealthy", 1),
        ],
    )
    def test_exit_code_matches_verdict(
        self, cli, verdict, expected_code,
    ):
        with patch(
            "core.approval.engine_health.score_engine",
            return_value=_make_health(verdict=verdict),
        ):
            _, code = _capture(cli._cmd_engine_pulse, _ns())
        assert code == expected_code


# --- Fleet mode -----------------------------------------------


def _engine_map(*names: str) -> dict[str, str]:
    """Build a fake ENGINE_GOAL_MAP for tests so the leaderboard
    iterates a controlled set, not the live roster (which would
    make assertion ordering fragile)."""
    return {name: "maximize_profit" for name in names}


class TestFleetMode:

    def test_fleet_renders_leaderboard_sickest_first(self, cli):
        # Each engine returns a distinct score so sort is testable.
        score_map = {
            "loyalty": _make_health(
                engine="loyalty", score=3, verdict="unhealthy",
            ),
            "cart_recovery": _make_health(
                engine="cart_recovery", score=9, verdict="healthy",
            ),
            "discount_strategy": _make_health(
                engine="discount_strategy",
                score=6, verdict="warning",
            ),
        }
        with patch.dict(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            _engine_map(*score_map.keys()),
            clear=True,
        ), patch(
            "core.approval.engine_health.score_engine",
            side_effect=lambda engine, **kw: score_map[engine],
        ):
            out, code = _capture(
                cli._cmd_engine_pulse, _ns(fleet=True),
            )
        # Exit code 1 because at least one engine is unhealthy
        assert code == 1
        # Sickest first: loyalty (3) before discount_strategy (6)
        # before cart_recovery (9)
        loyalty_pos = out.find("loyalty")
        ds_pos = out.find("discount_strategy")
        cart_pos = out.find("cart_recovery")
        assert -1 < loyalty_pos < ds_pos < cart_pos
        # Header rollup
        assert "healthy=1" in out
        assert "warning=1" in out
        assert "unhealthy=1" in out

    def test_fleet_all_healthy_exits_zero(self, cli):
        with patch.dict(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            _engine_map("loyalty", "cart_recovery"),
            clear=True,
        ), patch(
            "core.approval.engine_health.score_engine",
            return_value=_make_health(),
        ):
            out, code = _capture(
                cli._cmd_engine_pulse, _ns(fleet=True),
            )
        assert code == 0
        assert "unhealthy=0" in out

    def test_fleet_verdict_filter(self, cli):
        score_map = {
            "loyalty": _make_health(
                engine="loyalty", score=3, verdict="unhealthy",
            ),
            "cart_recovery": _make_health(
                engine="cart_recovery", score=9, verdict="healthy",
            ),
        }
        with patch.dict(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            _engine_map(*score_map.keys()),
            clear=True,
        ), patch(
            "core.approval.engine_health.score_engine",
            side_effect=lambda engine, **kw: score_map[engine],
        ):
            out, _ = _capture(
                cli._cmd_engine_pulse,
                _ns(fleet=True, verdict="unhealthy"),
            )
        # Only loyalty surfaces; cart_recovery filtered out
        assert "loyalty" in out
        assert "cart_recovery" not in out

    def test_fleet_json_envelope(self, cli):
        score_map = {
            "loyalty": _make_health(
                engine="loyalty", score=8, verdict="healthy",
            ),
            "cart_recovery": _make_health(
                engine="cart_recovery",
                score=6, verdict="warning",
            ),
        }
        with patch.dict(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            _engine_map(*score_map.keys()),
            clear=True,
        ), patch(
            "core.approval.engine_health.score_engine",
            side_effect=lambda engine, **kw: score_map[engine],
        ):
            out, _ = _capture(
                cli._cmd_engine_pulse, _ns(fleet=True, json=True),
            )
        data = json.loads(out)
        assert "fleet" in data
        assert len(data["fleet"]) == 2
        # Sickest first
        assert data["fleet"][0]["engine"] == "cart_recovery"
        assert data["fleet"][1]["engine"] == "loyalty"
        assert data["verdict_counts"] == {
            "healthy": 1, "warning": 1, "unhealthy": 0,
        }

    def test_fleet_empty_filter_match(self, cli):
        """When the verdict filter excludes every engine, render
        a clear no-match message rather than an empty list."""
        with patch.dict(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            _engine_map("loyalty", "cart_recovery"),
            clear=True,
        ), patch(
            "core.approval.engine_health.score_engine",
            return_value=_make_health(verdict="healthy"),
        ):
            out, code = _capture(
                cli._cmd_engine_pulse,
                _ns(fleet=True, verdict="unhealthy"),
            )
        assert code == 0
        assert "(no engines match)" in out

    def test_no_engine_no_fleet_exits_two(self, cli):
        """Calling pulse with neither a name nor --fleet is a
        usage error -> exit code 2."""
        _, code = _capture(
            cli._cmd_engine_pulse,
            _ns(engine_name=None, fleet=False),
        )
        assert code == 2

    def test_fleet_score_failure_skipped(self, cli):
        """A single engine's score_engine raising doesn't abort
        the whole fleet -- that engine is omitted, the rest
        render."""
        def _maybe_raise(engine, **kw):
            if engine == "broken":
                raise RuntimeError("queue dead")
            return _make_health(verdict="healthy")

        with patch.dict(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            _engine_map("broken", "loyalty"),
            clear=True,
        ), patch(
            "core.approval.engine_health.score_engine",
            side_effect=_maybe_raise,
        ):
            out, code = _capture(
                cli._cmd_engine_pulse, _ns(fleet=True),
            )
        assert code == 0
        assert "loyalty" in out
        assert "broken" not in out
