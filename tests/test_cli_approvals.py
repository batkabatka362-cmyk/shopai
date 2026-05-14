"""Tests for the ``shopai approvals`` CLI commands.

These verbs wrap the modern ``ApprovalQueue`` + ``execute_action``
path (PR #57/#69/#102), distinct from the legacy
``shopai actions ...`` shell that targets the older
``ActionExecutor`` abstraction. CLI and the
``/api/pending-actions`` endpoints share the same SQLite-backed
queue, so the CLI surface is the local-terminal equivalent of
hitting the API directly.

Coverage:
  1. ``pending`` — empty queue + populated queue + engine filter.
  2. ``stats`` — counts per status.
  3. ``show`` — full action JSON + operator_context enrichment.
  4. ``approve`` — flips state, optionally auto-executes.
  5. ``reject`` — flips state.
  6. ``execute`` — runs the dispatcher on an APPROVED action.
  7. Idempotency — verbs on already-resolved actions exit 1.

All tests subprocess-run ``python cli.py approvals <verb> ...``
with a tmp_path-scoped queue injected via the
``SHOPAI_APPROVAL_DB`` (no such var yet — we set ``data/`` to a
tmp via cwd manipulation OR construct a fresh queue with
monkeypatch on ``core.approval.queue._INSTANCE``). The latter
only works in-process, so subprocess tests share the real
default queue; we clean up after.

A simpler approach for now: in-process invocation of the CLI
handlers (no subprocess) via the same module-import trick as
test_recommendations_api.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_cli():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "shopai_cli", "cli.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    """Each test gets a fresh SQLite-backed queue."""
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, args):
    """Call ``fn(args)`` capturing stdout + exit code."""
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(args)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kwargs):
    return argparse.Namespace(**kwargs)


# ─── pending ────────────────────────────────────────────────────


class TestPending:

    def test_empty_queue_prints_message(
        self, isolated_queue, cli,
    ):
        out, code = _capture(
            cli._cmd_approvals_pending,
            _ns(engine=None, limit=20),
        )
        assert code == 0
        assert "No pending actions" in out

    def test_populated_queue_lists_actions(
        self, isolated_queue, cli,
    ):
        action = isolated_queue.enqueue(
            engine="cart_recovery",
            action_type="mint_cart_recovery_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={"token": "t"},
            narrative="recovery for cust_1",
            confidence=0.85,
        )
        out, code = _capture(
            cli._cmd_approvals_pending,
            _ns(engine=None, limit=20),
        )
        assert code == 0
        assert "Pending actions (1)" in out
        assert action.id in out
        assert "cart_recovery/mint_cart_recovery_code" in out
        assert "conf=0.85" in out
        assert "recovery for cust_1" in out

    def test_engine_filter(self, isolated_queue, cli):
        isolated_queue.enqueue(
            engine="cart_recovery", action_type="mint_cart_recovery_code",
            capability="SHOPIFY_CREATE_DISCOUNT", params={}, narrative="",
        )
        isolated_queue.enqueue(
            engine="loyalty", action_type="mint_loyalty_code",
            capability="SHOPIFY_CREATE_DISCOUNT", params={}, narrative="",
        )
        out, code = _capture(
            cli._cmd_approvals_pending,
            _ns(engine="loyalty", limit=20),
        )
        assert code == 0
        assert "loyalty/" in out
        assert "cart_recovery/" not in out

    def test_engine_filter_no_matches(
        self, isolated_queue, cli,
    ):
        isolated_queue.enqueue(
            engine="cart_recovery", action_type="x",
            capability="y", params={}, narrative="",
        )
        out, _ = _capture(
            cli._cmd_approvals_pending,
            _ns(engine="loyalty", limit=20),
        )
        assert "No pending actions for engine 'loyalty'" in out


# ─── stats ──────────────────────────────────────────────────────


class TestStats:

    def test_empty_stats(self, isolated_queue, cli):
        out, code = _capture(cli._cmd_approvals_stats, _ns())
        assert code == 0
        assert "approved" in out
        assert "pending" in out
        # Each status renders with a 0 count
        assert "0" in out


# ─── show ───────────────────────────────────────────────────────


class TestShow:

    def test_show_unknown_id_exits_1(
        self, isolated_queue, cli,
    ):
        out, code = _capture(
            cli._cmd_approvals_show,
            _ns(action_id="appr_does_not_exist_xyz"),
        )
        assert code == 1
        assert "Unknown action id" in out

    def test_show_returns_full_payload_json(
        self, isolated_queue, cli,
    ):
        action = isolated_queue.enqueue(
            engine="cart_recovery",
            action_type="mint_cart_recovery_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={"token": "tok"},
            narrative="test narrative",
            confidence=0.9,
        )
        out, code = _capture(
            cli._cmd_approvals_show,
            _ns(action_id=action.id),
        )
        assert code == 0
        payload = json.loads(out)
        assert payload["id"] == action.id
        assert payload["engine"] == "cart_recovery"
        assert payload["narrative"] == "test narrative"
        # operator_context field present (None when no note)
        assert "operator_context" in payload


# ─── approve ────────────────────────────────────────────────────


class TestApprove:

    def test_approve_flips_state(self, isolated_queue, cli):
        action = isolated_queue.enqueue(
            engine="catalog", action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS", params={"product_id": "p1"},
            narrative="",
        )
        out, code = _capture(
            cli._cmd_approvals_approve,
            _ns(
                action_id=action.id, reason="test",
                by="operator", execute=False,
            ),
        )
        assert code == 0
        assert "Approved" in out
        assert action.id in out
        # Queue state reflects the decision
        current = isolated_queue.get(action.id)
        from core.approval.queue import ApprovalStatus
        assert current.status == ApprovalStatus.APPROVED
        assert current.decided_by == "operator"

    def test_approve_unknown_id_exits_1(
        self, isolated_queue, cli,
    ):
        out, code = _capture(
            cli._cmd_approvals_approve,
            _ns(
                action_id="appr_does_not_exist_xyz",
                reason="", by="operator", execute=False,
            ),
        )
        assert code == 1
        assert "Cannot approve" in out

    def test_approve_with_execute_runs_dispatcher(
        self, isolated_queue, cli,
    ):
        action = isolated_queue.enqueue(
            engine="catalog", action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["test"]},
            narrative="",
        )
        with patch(
            "core.approval.dispatchers._router_call",
            return_value=(True, {"applied": True}),
        ):
            out, code = _capture(
                cli._cmd_approvals_approve,
                _ns(
                    action_id=action.id, reason="", by="op",
                    execute=True,
                ),
            )
        assert code == 0
        assert "Approved" in out
        assert "Executed" in out
        assert "executed" in out  # status string
        # Queue state reflects executed
        from core.approval.queue import ApprovalStatus
        assert isolated_queue.get(action.id).status == (
            ApprovalStatus.EXECUTED
        )


# ─── reject ─────────────────────────────────────────────────────


class TestReject:

    def test_reject_flips_state(self, isolated_queue, cli):
        action = isolated_queue.enqueue(
            engine="cart_recovery", action_type="mint_cart_recovery_code",
            capability="SHOPIFY_CREATE_DISCOUNT", params={},
            narrative="",
        )
        out, code = _capture(
            cli._cmd_approvals_reject,
            _ns(
                action_id=action.id, reason="too risky",
                by="operator",
            ),
        )
        assert code == 0
        assert "Rejected" in out
        from core.approval.queue import ApprovalStatus
        current = isolated_queue.get(action.id)
        assert current.status == ApprovalStatus.REJECTED
        assert current.decision_reason == "too risky"

    def test_reject_already_resolved_exits_1(
        self, isolated_queue, cli,
    ):
        action = isolated_queue.enqueue(
            engine="cart_recovery", action_type="mint_cart_recovery_code",
            capability="SHOPIFY_CREATE_DISCOUNT", params={},
            narrative="",
        )
        isolated_queue.approve(action.id, decided_by="op")
        # Re-reject the already-approved action — must refuse
        out, code = _capture(
            cli._cmd_approvals_reject,
            _ns(
                action_id=action.id, reason="oops", by="op",
            ),
        )
        assert code == 1


# ─── execute ────────────────────────────────────────────────────


class TestExecute:

    def test_execute_runs_dispatcher_on_approved(
        self, isolated_queue, cli,
    ):
        action = isolated_queue.enqueue(
            engine="catalog", action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["t"]},
            narrative="",
        )
        isolated_queue.approve(action.id)
        with patch(
            "core.approval.dispatchers._router_call",
            return_value=(True, {"applied": True}),
        ):
            out, code = _capture(
                cli._cmd_approvals_execute,
                _ns(action_id=action.id),
            )
        assert code == 0
        assert "executed" in out

    def test_execute_pending_action_exits_1(
        self, isolated_queue, cli,
    ):
        action = isolated_queue.enqueue(
            engine="catalog", action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS", params={}, narrative="",
        )
        # Not approved — execute is a no-op (returns None)
        out, code = _capture(
            cli._cmd_approvals_execute,
            _ns(action_id=action.id),
        )
        assert code == 1
        assert "no-op" in out

    def test_execute_unknown_id_exits_1(
        self, isolated_queue, cli,
    ):
        out, code = _capture(
            cli._cmd_approvals_execute,
            _ns(action_id="appr_does_not_exist_xyz"),
        )
        assert code == 1


# ─── dispatcher ──────────────────────────────────────────────────


class TestDispatcher:

    def test_unknown_verb_prints_usage(self, cli):
        out, code = _capture(
            cli._cmd_approvals,
            _ns(approvals_cmd=None),
        )
        assert code == 1
        assert "Usage:" in out
        assert "shopai approvals" in out

    def test_dispatches_pending(self, isolated_queue, cli):
        out, code = _capture(
            cli._cmd_approvals,
            _ns(approvals_cmd="pending", engine=None, limit=20),
        )
        assert code == 0
        assert "No pending actions" in out
