"""Tests for ``shopai transfer suggest`` -- the empire-AGI
cross-store transfer recommender.

For each (engine, action_type) tuple that succeeded on the
source store and was NOT tried on the target, surface it as a
transfer candidate. Built on PR #239's per-store filter on
pending_actions.

Covers:

  - Source success / target gap → candidate surfaces
  - Target has already tried it → excluded
  - --engine filter narrows the scan
  - --from == --to rejected
  - Outcome aggregation (positive / negative / revenue)
  - Ranking (positive outcomes first, then revenue, then count)
  - JSON envelope shape
  - Pre-#239 queue (no store_id kwarg) → clean error
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import MagicMock, patch

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
        from_store="a", to_store="b",
        engine="", k=5, json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _action(
    *, id_, engine, action_type, capability="CAP",
    store_id=None, params=None,
):
    a = MagicMock()
    a.id = id_
    a.engine = engine
    a.action_type = action_type
    a.capability = capability
    a.store_id = store_id
    a.params = params or {}
    return a


def _fake_queue(
    *,
    source_executed=None,
    target_actions_by_status=None,
    outcomes=None,
):
    from core.approval.queue import ApprovalStatus

    q = MagicMock()
    source_executed = source_executed or []
    target_actions_by_status = target_actions_by_status or {}
    outcomes = outcomes or {}

    def _list(status, *, engine=None, store_id=None, limit=2000):
        if store_id == "a":
            if status == ApprovalStatus.EXECUTED:
                base = list(source_executed)
            else:
                base = []
        elif store_id == "b":
            base = list(
                target_actions_by_status.get(status.value, []),
            )
        else:
            return []
        if engine:
            base = [a for a in base if a.engine == engine]
        return base[:limit]

    q.list_by_status.side_effect = _list

    def _outcomes(action_id):
        return outcomes.get(action_id, [])

    q.get_outcomes.side_effect = _outcomes
    return q


# ─── Argument validation ─────────────────────────────────────


class TestArgValidation:

    def test_from_eq_to_fails(self, cli):
        out, code = _capture(
            cli._cmd_transfer_suggest,
            _ns(from_store="a", to_store="a"),
        )
        assert code == 1
        assert "must be different" in out


# ─── Source success / target gap surfaces candidate ──────────


class TestCandidateSurfaces:

    def test_action_only_on_source_surfaces(self, cli):
        q = _fake_queue(
            source_executed=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                    store_id="a",
                ),
            ],
            target_actions_by_status={},  # nothing on target
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_suggest, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert len(data["suggestions"]) == 1
        s = data["suggestions"][0]
        assert s["engine"] == "loyalty"
        assert s["action_type"] == "mint_loyalty_code"

    def test_action_on_target_excluded(self, cli):
        from core.approval.queue import ApprovalStatus
        q = _fake_queue(
            source_executed=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
            ],
            target_actions_by_status={
                "executed": [
                    _action(
                        id_="tgt1", engine="loyalty",
                        action_type="mint_loyalty_code",
                    ),
                ],
            },
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_suggest, _ns(json=True),
            )
        data = json.loads(out)
        assert data["suggestions"] == []

    def test_pending_or_rejected_on_target_also_excluded(self, cli):
        """Any record on the target -- pending, rejected, failed --
        means the operator has at least considered it. Exclude."""
        q = _fake_queue(
            source_executed=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
            ],
            target_actions_by_status={
                "pending": [
                    _action(
                        id_="tgt_pending", engine="loyalty",
                        action_type="mint_loyalty_code",
                    ),
                ],
            },
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_suggest, _ns(json=True),
            )
        data = json.loads(out)
        assert data["suggestions"] == []


# ─── --engine filter ─────────────────────────────────────────


class TestEngineFilter:

    def test_engine_filter_narrows(self, cli):
        q = _fake_queue(
            source_executed=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
                _action(
                    id_="src2", engine="cart_recovery",
                    action_type="mint_cart_recovery_code",
                ),
            ],
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_suggest,
                _ns(engine="loyalty", json=True),
            )
        data = json.loads(out)
        assert len(data["suggestions"]) == 1
        assert data["suggestions"][0]["engine"] == "loyalty"


# ─── Outcome aggregation ─────────────────────────────────────


class TestOutcomeAggregation:

    def test_revenue_and_polarity_aggregated(self, cli):
        q = _fake_queue(
            source_executed=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
                _action(
                    id_="src2", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
            ],
            outcomes={
                "src1": [
                    {"polarity": "positive",
                     "metrics": {"revenue": 100.0}},
                ],
                "src2": [
                    {"polarity": "positive",
                     "metrics": {"revenue": 50.0}},
                    {"polarity": "negative",
                     "metrics": {"revenue": -10.0}},
                ],
            },
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_suggest, _ns(json=True),
            )
        data = json.loads(out)
        s = data["suggestions"][0]
        assert s["success_count"] == 2
        assert s["positive_outcomes"] == 2
        assert s["negative_outcomes"] == 1
        # 100 + 50 + (-10) = 140
        assert s["total_revenue"] == 140.0

    def test_ranking_prefers_positive_outcomes(self, cli):
        q = _fake_queue(
            source_executed=[
                _action(
                    id_="a1", engine="e1", action_type="t1",
                ),
                _action(
                    id_="b1", engine="e2", action_type="t2",
                ),
            ],
            outcomes={
                "a1": [],  # no outcomes
                "b1": [
                    {"polarity": "positive",
                     "metrics": {"revenue": 50.0}},
                ],
            },
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_suggest, _ns(json=True),
            )
        data = json.loads(out)
        # e2/t2 (positive outcome) ranks first; e1/t1 (no outcome) second
        assert data["suggestions"][0]["engine"] == "e2"
        assert data["suggestions"][1]["engine"] == "e1"


# ─── JSON envelope shape ─────────────────────────────────────


class TestJsonEnvelope:

    def test_envelope_fields(self, cli):
        q = _fake_queue(source_executed=[])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_suggest, _ns(json=True),
            )
        data = json.loads(out)
        for key in (
            "from_store", "to_store", "engine_filter", "k",
            "source_executed_count", "source_unique_actions",
            "already_tried_count", "suggestions",
        ):
            assert key in data
        assert data["from_store"] == "a"
        assert data["to_store"] == "b"
        assert data["k"] == 5
        assert data["suggestions"] == []


# ─── Drill-down hint ─────────────────────────────────────────


class TestDrillDownHint:
    """When there's at least one suggestion, text view ends
    with a `transfer apply --dry-run` hint pre-filled with
    the top suggestion's engine + action_type so operators
    can paste-and-run."""

    def test_hint_renders_when_suggestion_present(self, cli):
        q = _fake_queue(
            source_executed=[
                _action(
                    id_="src1", engine="loyalty",
                    action_type="mint_loyalty_code",
                ),
            ],
            target_actions_by_status={},
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_suggest, _ns(),
            )
        # Hint includes both stores + the top suggestion's
        # engine/action_type, and `--dry-run` for safety.
        assert "shopai transfer apply" in out
        assert "--from a" in out
        assert "--to b" in out
        assert "--engine loyalty" in out
        assert "--action-type mint_loyalty_code" in out
        assert "--dry-run" in out

    def test_hint_absent_when_no_suggestions(self, cli):
        q = _fake_queue(source_executed=[])
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_transfer_suggest, _ns(),
            )
        assert "shopai transfer apply" not in out


# ─── Pre-#239 queue without store_id kwarg ───────────────────


class TestLegacyQueueRejection:

    def test_typeerror_on_store_id_kwarg_surfaces_clear_error(self, cli):
        q = MagicMock()
        # Pre-#239 list_by_status doesn't accept store_id
        q.list_by_status.side_effect = TypeError(
            "unexpected keyword argument 'store_id'"
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_transfer_suggest, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
        assert "per-store" in data["error"]
