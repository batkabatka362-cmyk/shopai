"""Tests for autonomy-overview-history CLI (Wave 901)."""
from __future__ import annotations

import contextlib
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import cli
from core.automation.autonomy_overview import OverviewSnapshot
from core.automation.autonomy_overview_history import (
    record_snapshot,
)


@pytest.fixture(autouse=True)
def _disable_test_env_guard():
    with patch(
        "core.automation.autonomy_overview_history."
        "_is_test_environment",
        return_value=False,
    ):
        yield


def _seed(path, **kw):
    s = OverviewSnapshot()
    for k, v in kw.items():
        setattr(s, k, v)
    record_snapshot(s, path=path)


def _run(args, history_path):
    """Patch _DEFAULT_PATH so the CLI reads our temp file."""
    from core.automation import autonomy_overview_history
    buf = io.StringIO()
    with patch.object(
        autonomy_overview_history,
        "_DEFAULT_PATH",
        history_path,
    ), contextlib.redirect_stdout(buf):
        cli._cmd_autonomy_overview_history(args)
    return buf.getvalue()


class TestCLI:

    def test_empty_history(self, tmp_path):
        p = tmp_path / "h.json"
        ns = SimpleNamespace(
            store="", limit=20, window_hours=0.0,
            transitions=False, json=False,
        )
        out = _run(ns, p)
        assert "no history yet" in out
        assert "shopai autonomy-overview" in out

    def test_renders_entries(self, tmp_path):
        p = tmp_path / "h.json"
        for i in range(3):
            _seed(p, armed_total=i, captured_at=1000 + i)
        ns = SimpleNamespace(
            store="", limit=20, window_hours=0.0,
            transitions=False, json=False,
        )
        out = _run(ns, p)
        assert "3 entry/entries" in out
        # Has the table header
        assert "verdict" in out
        assert "armed" in out

    def test_transitions_view(self, tmp_path):
        p = tmp_path / "h.json"
        _seed(p, captured_at=1000)  # idle
        _seed(p, armed_total=2, captured_at=2000)  # armed
        ns = SimpleNamespace(
            store="", limit=20, window_hours=0.0,
            transitions=True, json=False,
        )
        out = _run(ns, p)
        assert "Verdict transitions" in out
        assert "idle" in out
        assert "armed" in out

    def test_json_envelope(self, tmp_path):
        p = tmp_path / "h.json"
        _seed(p, armed_total=5)
        ns = SimpleNamespace(
            store="", limit=20, window_hours=0.0,
            transitions=False, json=True,
        )
        out = _run(ns, p)
        env = json.loads(out)
        assert "entries" in env
        assert len(env["entries"]) == 1
        assert env["entries"][0]["armed_total"] == 5

    def test_store_filter(self, tmp_path):
        p = tmp_path / "h.json"
        _seed(p, store_id="a")
        _seed(p, store_id="b")
        ns = SimpleNamespace(
            store="a", limit=20, window_hours=0.0,
            transitions=False, json=True,
        )
        env = json.loads(_run(ns, p))
        assert len(env["entries"]) == 1
        assert env["entries"][0]["store_id"] == "a"
