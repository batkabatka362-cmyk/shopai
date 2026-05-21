"""Tests for ``shopai store design-history``.

Read-only audit of past store_design runs from local memory.
Pairs with ``store design`` (preview) and ``store design-apply``
(writer) -- this is the "how has this engine been performing
over time?" view.
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
    defaults = dict(limit=10, json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _records(n=3):
    return [
        {
            "timestamp": f"2026-05-{i:02d}T12:00:00Z",
            "estimated_conversion_lift": 0.12 + 0.01 * i,
            "recommendations_count": 5 + i,
        }
        for i in range(1, n + 1)
    ]


class TestHistoryFound:

    def test_text_rendering(self, cli):
        with patch(
            "engines.store_design.memory_reader."
            "read_past_designs",
            return_value={
                "status": "success",
                "records": _records(3),
                "count": 3,
                "summary": {
                    "avg_conversion_lift": 0.13,
                    "avg_recommendations_count": 7.0,
                    "total_runs": 3,
                },
            },
        ):
            out, code = _capture(
                cli._cmd_store_design_history, _ns(),
            )
        assert code == 0
        assert "3 run" in out
        assert "13.0%" in out or "13%" in out
        # Per-run rows
        assert "2026-05-01" in out
        assert "2026-05-03" in out

    def test_json_round_trips(self, cli):
        records = _records(2)
        with patch(
            "engines.store_design.memory_reader."
            "read_past_designs",
            return_value={
                "status": "success",
                "records": records,
                "count": 2,
                "summary": {
                    "avg_conversion_lift": 0.125,
                    "avg_recommendations_count": 6.5,
                    "total_runs": 2,
                },
            },
        ):
            out, code = _capture(
                cli._cmd_store_design_history,
                _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["count"] == 2
        assert data["summary"]["total_runs"] == 2
        # First record's lift round-trips
        assert data["records"][0][
            "estimated_conversion_lift"
        ] == records[0]["estimated_conversion_lift"]


class TestNoHistory:

    def test_no_records_text(self, cli):
        with patch(
            "engines.store_design.memory_reader."
            "read_past_designs",
            return_value={
                "status": "success",
                "records": [], "count": 0,
                "summary": {},
            },
        ):
            out, code = _capture(
                cli._cmd_store_design_history, _ns(),
            )
        assert code == 0
        assert "No past" in out
        # Surfacing hint points operators at the memory dir
        assert ".memory" in out

    def test_no_records_json(self, cli):
        with patch(
            "engines.store_design.memory_reader."
            "read_past_designs",
            return_value={
                "status": "success",
                "records": [], "count": 0,
                "summary": {},
            },
        ):
            out, code = _capture(
                cli._cmd_store_design_history,
                _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["count"] == 0
        assert data["records"] == []


class TestResilience:

    def test_memory_read_raise_friendly(self, cli):
        with patch(
            "engines.store_design.memory_reader."
            "read_past_designs",
            side_effect=RuntimeError("memory broken"),
        ):
            out, code = _capture(
                cli._cmd_store_design_history, _ns(),
            )
        assert code == 0
        assert "unavailable" in out.lower()

    def test_memory_read_raise_json(self, cli):
        with patch(
            "engines.store_design.memory_reader."
            "read_past_designs",
            side_effect=RuntimeError("memory broken"),
        ):
            out, code = _capture(
                cli._cmd_store_design_history,
                _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is None
        assert data["error"] == "history_unavailable"
        assert "memory broken" in data["message"]


class TestLimitPropagation:

    def test_limit_passed_to_reader(self, cli):
        with patch(
            "engines.store_design.memory_reader."
            "read_past_designs",
            return_value={
                "status": "success",
                "records": [], "count": 0,
                "summary": {},
            },
        ) as reader_mock:
            _capture(
                cli._cmd_store_design_history, _ns(limit=25),
            )
        reader_mock.assert_called_once()
        kwargs = reader_mock.call_args.kwargs
        assert kwargs["limit"] == 25
