"""Tests for ``shopai approvals history`` — decision audit trail CLI.

Two reading modes:
  - per-action: chronological lifecycle of one action (oldest first)
  - global: newest first ticker, optionally filtered by actor
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
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


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
        action_id=None, by=None, limit=50, json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _enqueue_and_decide(q, *, decided_by="alice", reason="lgtm"):
    a = q.enqueue(
        engine="x", action_type="y", capability="z",
        params={}, narrative="",
    )
    q.approve(a.id, decided_by=decided_by, reason=reason)
    q.attach_result(a.id, success=True, result={"k": "v"})
    return a


class TestPerActionLifecycle:

    def test_renders_two_transitions(self, cli, isolated_queue):
        a = _enqueue_and_decide(isolated_queue)
        out, code = _capture(
            cli._cmd_approvals_history, _ns(action_id=a.id),
        )
        assert code == 0
        assert "Decision history" in out
        assert "approved" in out
        assert "executed" in out
        # Reason from operator appears
        assert "lgtm" in out
        # System actor for the execute row
        assert "system" in out

    def test_missing_action_renders_friendly_message(
        self, cli, isolated_queue,
    ):
        out, code = _capture(
            cli._cmd_approvals_history,
            _ns(action_id="appr_does_not_exist"),
        )
        assert code == 0
        assert "No decisions recorded" in out
        assert "appr_does_not_exist" in out


class TestGlobalTicker:

    def test_global_no_args_renders_all(self, cli, isolated_queue):
        _enqueue_and_decide(isolated_queue)
        _enqueue_and_decide(isolated_queue)
        out, _ = _capture(cli._cmd_approvals_history, _ns())
        assert "Recent decisions" in out
        # Two actions × (approve + execute) = 4 transitions
        assert out.count("approved") >= 2
        assert out.count("executed") >= 2

    def test_empty_global_friendly(self, cli, isolated_queue):
        out, _ = _capture(cli._cmd_approvals_history, _ns())
        assert "No decisions recorded globally" in out


class TestActorFilter:

    def test_by_system_isolates_executor_rows(
        self, cli, isolated_queue,
    ):
        _enqueue_and_decide(isolated_queue, decided_by="alice")
        out, _ = _capture(
            cli._cmd_approvals_history,
            _ns(by="system", json=True),
        )
        data = json.loads(out)
        assert all(r["decided_by"] == "system" for r in data)
        assert any(r["decision"] == "executed" for r in data)

    def test_by_specific_human_isolates(
        self, cli, isolated_queue,
    ):
        _enqueue_and_decide(isolated_queue, decided_by="alice")
        _enqueue_and_decide(isolated_queue, decided_by="bob")
        out, _ = _capture(
            cli._cmd_approvals_history,
            _ns(by="alice", json=True),
        )
        data = json.loads(out)
        assert len(data) == 1
        assert data[0]["decided_by"] == "alice"
        assert data[0]["decision"] == "approved"


class TestJsonMode:

    def test_json_emits_array(self, cli, isolated_queue):
        a = _enqueue_and_decide(isolated_queue)
        out, _ = _capture(
            cli._cmd_approvals_history,
            _ns(action_id=a.id, json=True),
        )
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["decision"] == "approved"
        assert data[1]["decision"] == "executed"

    def test_json_empty_is_empty_array(self, cli, isolated_queue):
        out, _ = _capture(
            cli._cmd_approvals_history, _ns(json=True),
        )
        assert json.loads(out) == []


class TestResilience:

    def test_queue_failure_renders_empty(self, cli, isolated_queue):
        with patch.object(
            isolated_queue, "list_decisions",
            side_effect=RuntimeError("db lock"),
        ):
            out, code = _capture(
                cli._cmd_approvals_history, _ns(),
            )
        assert code == 0
        assert "No decisions recorded" in out
