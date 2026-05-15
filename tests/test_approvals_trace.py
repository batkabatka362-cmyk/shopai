"""Tests for ``shopai approvals trace <action_id>`` — dry-run
inspection of an approval action.

The trace builds a structured snapshot of what executing the
action would do (dispatcher + adapter + scopes + params) WITHOUT
making any external call. Useful before pushing the button on
high-stakes actions (price changes, archives, gift-card mints).

Tests cover:
  - Happy path: pending action renders all fields cleanly
  - Already-resolved actions surface as 'issue' but still print
  - Unknown id exits 1 with ``unknown_action_id`` in issues
  - JSON mode echoes the same structured shape
  - Missing-dispatcher / missing-adapter cases surface as
    explicit issues
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


@pytest.fixture
def isolated_queue(tmp_path, monkeypatch):
    """Fresh in-temp queue so tests don't depend on existing
    actions in the live SQLite DB."""
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


def _ns(action_id: str, **kw):
    defaults = dict(json=False)
    defaults.update(kw)
    defaults["action_id"] = action_id
    return argparse.Namespace(**defaults)


# ─── Happy path: real action, real dispatcher, real adapter ───


class TestHappyPath:

    def test_trace_renders_pending_action(self, cli, isolated_queue):
        action = isolated_queue.enqueue(
            engine="tag_management",
            action_type="apply_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params={
                "product_id": "p1",
                "merged_tags": ["sale", "summer"],
                "tags_added": ["summer"],
                "new_tags": ["summer"],
            },
            narrative="Add seasonal tag",
            confidence=0.9,
        )
        out, code = _capture(
            cli._cmd_approvals_trace, _ns(action.id),
        )
        # Pending → no issues → exit 0
        assert code == 0
        assert action.id in out
        assert "tag_management" in out
        assert "apply_tags" in out
        assert "SHOPIFY_UPDATE_PRODUCT" in out
        assert "dispatcher:    registered" in out
        # The adapter that claims SHOPIFY_UPDATE_PRODUCT should
        # surface (product adapter)
        assert "routes to:" in out
        # The friendly params line
        assert "product_id" in out
        # "No side effects" sign-off
        assert "No side effects executed" in out

    def test_trace_includes_scopes(self, cli, isolated_queue):
        action = isolated_queue.enqueue(
            engine="tag_management",
            action_type="apply_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params={"product_id": "p1", "merged_tags": ["x"]},
            narrative="",
            confidence=0.8,
        )
        out, _ = _capture(
            cli._cmd_approvals_trace, _ns(action.id),
        )
        # Either explicit scopes or scope-independent / none-
        # declared marker — but the line must appear
        assert "scopes:" in out


# ─── JSON envelope ─────────────────────────────────────────────


class TestJson:

    def test_json_shape(self, cli, isolated_queue):
        action = isolated_queue.enqueue(
            engine="tag_management",
            action_type="apply_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params={"product_id": "p1", "merged_tags": ["x"]},
            narrative="",
            confidence=0.8,
        )
        out, code = _capture(
            cli._cmd_approvals_trace, _ns(action.id, json=True),
        )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert data["action"]["id"] == action.id
        assert data["action"]["engine"] == "tag_management"
        assert data["action"]["capability"] == "SHOPIFY_UPDATE_PRODUCT"
        assert data["dispatcher"]["registered"] is True
        assert isinstance(data["adapters"], list)
        assert isinstance(
            data["aggregate_required_scopes"], list,
        )
        assert data["params"]["product_id"] == "p1"


# ─── Error cases ──────────────────────────────────────────────


class TestErrors:

    def test_unknown_action_id_exits_1(self, cli, isolated_queue):
        out, code = _capture(
            cli._cmd_approvals_trace, _ns("appr_does_not_exist"),
        )
        assert code == 1
        assert "unknown_action_id" in out

    def test_unknown_action_id_json(self, cli, isolated_queue):
        out, code = _capture(
            cli._cmd_approvals_trace,
            _ns("appr_does_not_exist", json=True),
        )
        assert code == 1
        data = json.loads(out)
        assert data["ok"] is False
        assert "unknown_action_id" in data["issues"]

    def test_already_executed_surfaces_issue(self, cli, isolated_queue):
        from core.approval.queue import ApprovalStatus
        action = isolated_queue.enqueue(
            engine="x",
            action_type="apply_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params={"product_id": "p1", "merged_tags": ["x"]},
            narrative="",
            confidence=0.8,
        )
        # Approve + attach a fake result to flip to EXECUTED
        isolated_queue.approve(action.id, decided_by="test", reason="")
        isolated_queue.attach_result(
            action.id, success=True, result={"ok": True},
        )
        out, code = _capture(
            cli._cmd_approvals_trace, _ns(action.id),
        )
        # Already-resolved is an issue → exit 1
        assert code == 1
        assert "already_resolved" in out

    def test_unknown_capability_surfaces_no_adapter_claims(
        self, cli, isolated_queue,
    ):
        action = isolated_queue.enqueue(
            engine="x",
            action_type="apply_tags",
            capability="SHOPIFY_TOTALLY_FAKE_CAP",
            params={"product_id": "p1", "merged_tags": ["x"]},
            narrative="",
            confidence=0.8,
        )
        out, code = _capture(
            cli._cmd_approvals_trace, _ns(action.id),
        )
        # No adapter claims a fake capability → issue
        assert code == 1
        assert "no_adapter_claims" in out

    def test_unknown_action_type_surfaces_no_dispatcher(
        self, cli, isolated_queue,
    ):
        action = isolated_queue.enqueue(
            engine="x",
            action_type="apply_invented_thing",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params={},
            narrative="",
            confidence=0.8,
        )
        out, code = _capture(
            cli._cmd_approvals_trace, _ns(action.id),
        )
        assert code == 1
        assert "no_dispatcher_registered" in out
        assert "NOT REGISTERED" in out
