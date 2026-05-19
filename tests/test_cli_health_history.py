"""Tests for ``shopai approvals health-history``.

Mirrors the alert-history CLI: list / filter / clear / prune
modes over the engine_health_history persisted log.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from pathlib import Path
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


@pytest.fixture
def isolated_data(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def no_test_guard():
    """Lift the engine_health_history Pattern J guard so seed
    events can be persisted inside the test."""
    with patch(
        "core.approval.engine_health_history."
        "_is_test_environment",
        return_value=False,
    ):
        yield


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
        engine=None, since_days=30.0, limit=20,
        clear=False, prune_older_than_days=None, json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _seed(*entries):
    """Seed events with a default ``now`` of "right now" so the
    CLI's default 30-day window includes them. Callers can
    override per-entry for absolute-time tests."""
    import time as _t
    from core.approval.engine_health_history import record_score
    default_now = _t.time()
    for e in entries:
        record_score(
            e["engine"],
            score=e["score"],
            verdict=e["verdict"],
            now=e.get("now", default_now),
        )


class TestList:

    def test_empty_log_renders_no_events(
        self, cli, isolated_data,
    ):
        out, code = _capture(
            cli._cmd_approvals_health_history, _ns(),
        )
        assert code == 0
        assert "no events" in out
        assert "0 event(s)" in out

    def test_populated_log_renders_rows(
        self, cli, isolated_data, no_test_guard,
    ):
        # Seed with default ``now`` so the events fall inside
        # the CLI's default 30-day window.
        _seed(
            {"engine": "loyalty", "score": 8,
             "verdict": "healthy"},
            {"engine": "cart_recovery", "score": 4,
             "verdict": "unhealthy"},
        )
        out, code = _capture(
            cli._cmd_approvals_health_history, _ns(),
        )
        assert code == 0
        assert "loyalty" in out
        assert "cart_recovery" in out
        assert "8/10" in out
        assert "4/10" in out

    def test_engine_filter(
        self, cli, isolated_data, no_test_guard,
    ):
        _seed(
            {"engine": "loyalty", "score": 8,
             "verdict": "healthy"},
            {"engine": "cart_recovery", "score": 4,
             "verdict": "unhealthy"},
        )
        out, _ = _capture(
            cli._cmd_approvals_health_history,
            _ns(engine="loyalty"),
        )
        assert "loyalty" in out
        assert "cart_recovery" not in out

    def test_limit_caps_rows(
        self, cli, isolated_data, no_test_guard,
    ):
        # Seed 5 events with timestamps inside the 30-day window
        import time as _t
        base = _t.time()
        for i in range(5):
            _seed({
                "engine": "loyalty", "score": 7,
                "verdict": "healthy",
                "now": base - i * 60.0,
            })
        out, _ = _capture(
            cli._cmd_approvals_health_history,
            _ns(limit=2, json=True),
        )
        data = json.loads(out)
        assert len(data["events"]) == 2
        # total_in_window is full count, limit only affects rows
        assert data["total_in_window"] == 5


class TestJsonEnvelope:

    def test_envelope_shape(
        self, cli, isolated_data, no_test_guard,
    ):
        _seed({
            "engine": "loyalty", "score": 8,
            "verdict": "healthy",
        })
        out, _ = _capture(
            cli._cmd_approvals_health_history, _ns(json=True),
        )
        data = json.loads(out)
        assert data["engine"] is None
        assert data["since_days"] == 30.0
        assert data["limit"] == 20
        assert data["total_in_window"] == 1
        assert len(data["events"]) == 1
        r = data["events"][0]
        assert r["engine"] == "loyalty"
        assert r["score"] == 8
        assert r["verdict"] == "healthy"


class TestClear:

    def test_clear_wipes_log(
        self, cli, isolated_data, no_test_guard,
    ):
        _seed({
            "engine": "loyalty", "score": 8,
            "verdict": "healthy",
        })
        out, code = _capture(
            cli._cmd_approvals_health_history,
            _ns(clear=True),
        )
        assert code == 0
        assert "Health history cleared" in out
        # Confirm the log is now empty
        from core.approval.engine_health_history import (
            _load_raw_events,
        )
        assert _load_raw_events() == []

    def test_clear_json_envelope(
        self, cli, isolated_data,
    ):
        out, code = _capture(
            cli._cmd_approvals_health_history,
            _ns(clear=True, json=True),
        )
        assert code == 0
        data = json.loads(out)
        assert data["cleared"] is True


class TestPrune:

    def test_prune_drops_old(
        self, cli, isolated_data, no_test_guard,
    ):
        import time as _t
        now = _t.time()
        day = 86400.0
        _seed(
            {"engine": "old", "score": 8,
             "verdict": "healthy", "now": now - 100 * day},
            {"engine": "fresh", "score": 5,
             "verdict": "warning", "now": now - 10 * day},
        )
        out, code = _capture(
            cli._cmd_approvals_health_history,
            _ns(prune_older_than_days=30.0),
        )
        assert code == 0
        assert "Pruned 1 event" in out
        # Confirm only the fresh one remains
        from core.approval.engine_health_history import (
            _load_raw_events,
        )
        remaining = _load_raw_events()
        assert len(remaining) == 1
        assert remaining[0].engine == "fresh"

    def test_prune_json_envelope(
        self, cli, isolated_data,
    ):
        out, _ = _capture(
            cli._cmd_approvals_health_history,
            _ns(prune_older_than_days=30.0, json=True),
        )
        data = json.loads(out)
        assert data["status"] == "ok"
        assert data["dropped"] == 0
        assert data["prune_older_than_days"] == 30.0


class TestErrorPath:

    def test_recent_history_raise_renders_empty(
        self, cli, isolated_data,
    ):
        with patch(
            "core.approval.engine_health_history."
            "recent_history",
            side_effect=RuntimeError("disk gone"),
        ):
            out, code = _capture(
                cli._cmd_approvals_health_history, _ns(),
            )
        # The list path swallows the error and renders empty
        assert code == 0
        assert "no events" in out
