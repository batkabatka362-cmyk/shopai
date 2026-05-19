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
    defaults = dict(engine_name="loyalty", json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _make_health(
    *, score: int = 10,
    verdict: str = "healthy",
    concerns=None,
    signals=None,
):
    return EngineHealth(
        engine="loyalty",
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
