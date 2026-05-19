"""Tests for ``shopai approvals health-regressions``.

Reads ``engine_health_history.find_regressions`` and renders the
flagged engines. Cron-friendly: exit code 1 when ANY regression
is found, 0 otherwise.

Coverage:
  1. No regressions -> exit 0, text says so.
  2. Regression flagged -> exit 1, text shows engine + drop.
  3. JSON envelope includes thresholds + rows.
  4. Threshold flags propagate to find_regressions kwargs.
  5. find_regressions raise surfaces clean error + exit 1.
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
        min_drop=3.0,
        baseline_days=7.0,
        latest_days=1.0,
        min_baseline_samples=3,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _stub_regression(
    *, engine="loyalty", latest_score=4,
    baseline_score=9.0, drop=5.0,
):
    from core.approval.engine_health_history import HealthRegression
    return HealthRegression(
        engine=engine,
        latest_score=latest_score,
        latest_verdict="unhealthy",
        baseline_score=baseline_score,
        drop=drop,
        samples_in_baseline=5,
    )


class TestNoRegressions:

    def test_text_says_no_regressions(self, cli):
        with patch(
            "core.approval.engine_health_history."
            "find_regressions",
            return_value=[],
        ):
            out, code = _capture(
                cli._cmd_approvals_health_regressions, _ns(),
            )
        assert code == 0
        assert "No regressions flagged" in out

    def test_json_empty_list(self, cli):
        with patch(
            "core.approval.engine_health_history."
            "find_regressions",
            return_value=[],
        ):
            out, code = _capture(
                cli._cmd_approvals_health_regressions,
                _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["regressions"] == []


class TestFlaggedRegressions:

    def test_text_renders_row(self, cli):
        with patch(
            "core.approval.engine_health_history."
            "find_regressions",
            return_value=[_stub_regression()],
        ):
            out, code = _capture(
                cli._cmd_approvals_health_regressions, _ns(),
            )
        assert code == 1
        assert "loyalty" in out
        assert "drop=" in out
        assert "5.0" in out  # drop value
        assert "unhealthy" in out

    def test_text_renders_multiple(self, cli):
        regs = [
            _stub_regression(engine="loyalty", drop=5.0),
            _stub_regression(
                engine="cart_recovery", drop=3.5,
            ),
        ]
        with patch(
            "core.approval.engine_health_history."
            "find_regressions",
            return_value=regs,
        ):
            out, code = _capture(
                cli._cmd_approvals_health_regressions, _ns(),
            )
        assert code == 1
        assert "2 engine(s)" in out
        assert "loyalty" in out
        assert "cart_recovery" in out


class TestJsonEnvelope:

    def test_thresholds_in_envelope(self, cli):
        with patch(
            "core.approval.engine_health_history."
            "find_regressions",
            return_value=[],
        ):
            out, _ = _capture(
                cli._cmd_approvals_health_regressions,
                _ns(min_drop=2.5, baseline_days=14.0, json=True),
            )
        data = json.loads(out)
        assert data["min_drop"] == 2.5
        assert data["baseline_days"] == 14.0
        assert data["latest_days"] == 1.0
        assert data["min_baseline_samples"] == 3

    def test_regression_row_shape(self, cli):
        with patch(
            "core.approval.engine_health_history."
            "find_regressions",
            return_value=[_stub_regression()],
        ):
            out, code = _capture(
                cli._cmd_approvals_health_regressions,
                _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        r = data["regressions"][0]
        assert r["engine"] == "loyalty"
        assert r["latest_score"] == 4
        assert r["baseline_score"] == 9.0
        assert r["drop"] == 5.0
        assert r["latest_verdict"] == "unhealthy"
        assert r["samples_in_baseline"] == 5


class TestThresholdPropagation:

    def test_flags_pass_through(self, cli):
        with patch(
            "core.approval.engine_health_history."
            "find_regressions",
            return_value=[],
        ) as find_mock:
            _capture(
                cli._cmd_approvals_health_regressions,
                _ns(
                    min_drop=2.0,
                    baseline_days=14.0,
                    latest_days=2.0,
                    min_baseline_samples=5,
                ),
            )
        kw = find_mock.call_args.kwargs
        assert kw["min_drop"] == 2.0
        # Days -> seconds conversion
        assert kw["baseline_window_seconds"] == 14.0 * 86400.0
        assert kw["latest_window_seconds"] == 2.0 * 86400.0
        assert kw["min_baseline_samples"] == 5


class TestErrorPath:

    def test_find_raise_surfaces_error_text(self, cli):
        with patch(
            "core.approval.engine_health_history."
            "find_regressions",
            side_effect=RuntimeError("history disk gone"),
        ):
            out, code = _capture(
                cli._cmd_approvals_health_regressions, _ns(),
            )
        assert code == 1
        assert "history disk gone" in out

    def test_find_raise_json_error_envelope(self, cli):
        with patch(
            "core.approval.engine_health_history."
            "find_regressions",
            side_effect=RuntimeError("history disk gone"),
        ):
            out, code = _capture(
                cli._cmd_approvals_health_regressions,
                _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
        assert "history disk gone" in data["error"]
