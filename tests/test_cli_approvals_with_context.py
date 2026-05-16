"""Tests for ``shopai approvals show --with-context`` -- the
AGI decision-retrieval enrichment of single-action drilldowns.

When an operator triages a PENDING action, knowing how similar
past actions turned out (positive / negative outcomes,
relevance, revenue) is the cheapest decision-support signal we
can surface. This is also the natural follow-up to the AGI
Phase 2 stack: world model + decision retrieval feed both
auto-capture (zero-touch for all writers) and this explicit
operator surface.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
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
        action_id="a1",
        no_outcomes=False,
        with_context=False,
        context_k=3,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_action(**fields):
    a = MagicMock()
    a.id = fields.get("id", "a1")
    a.engine = fields.get("engine", "loyalty")
    a.action_type = fields.get("action_type", "mint_loyalty_code")
    a.capability = fields.get("capability", "SHOPIFY_CREATE_DISCOUNT")
    a.params = fields.get("params", {})
    a.status = MagicMock(value=fields.get("status", "pending"))
    a.proposed_at = fields.get("proposed_at", time.time() - 60)
    a.decided_at = fields.get("decided_at", None)
    a.decided_by = fields.get("decided_by", None)
    a.decision_reason = fields.get("decision_reason", None)
    a.confidence = fields.get("confidence", 0.5)
    a.narrative = fields.get("narrative", "")
    a.result = fields.get("result", None)
    a.to_dict.return_value = {
        "id": a.id,
        "engine": a.engine,
        "action_type": a.action_type,
        "capability": a.capability,
        "params": a.params,
        "status": a.status.value,
    }
    return a


def _fake_queue(action, *, outcomes=None):
    q = MagicMock()
    q.get.return_value = action
    q.get_outcomes.return_value = outcomes or []
    return q


# ─── Flag is opt-in: default behavior unchanged ──────────────


class TestDefaultBehaviorUnchanged:

    def test_no_flag_does_not_embed_context(self, cli):
        action = _fake_action(status="pending")
        q = _fake_queue(action)
        with patch(
            "core.approval.get_approval_queue", return_value=q,
        ):
            out, _ = _capture(cli._cmd_approvals_show, _ns())
        data = json.loads(out)
        assert "agi_context" not in data


# ─── --with-context happy path ───────────────────────────────


class TestWithContextSection:

    def test_embeds_similar_and_summary(self, cli):
        action = _fake_action(
            status="pending",
            params={"customer_id": "x"},
        )
        q = _fake_queue(action)
        retrieval_results = [
            {
                "action_id": "past1",
                "relevance": 0.9,
                "outcome_summary": {
                    "has_positive": True,
                    "has_negative": False,
                    "total_revenue": 100.0,
                },
            },
            {
                "action_id": "past2",
                "relevance": 0.6,
                "outcome_summary": {
                    "has_positive": False,
                    "has_negative": True,
                    "total_revenue": -20.0,
                },
            },
        ]
        with patch(
            "core.approval.get_approval_queue", return_value=q,
        ), patch(
            "core.decision_retrieval.DecisionRetrieval",
        ) as retriever_cls:
            retriever_cls.return_value.retrieve.return_value = retrieval_results
            out, _ = _capture(
                cli._cmd_approvals_show, _ns(with_context=True),
            )
        data = json.loads(out)
        assert "agi_context" in data
        ctx = data["agi_context"]
        assert ctx["k"] == 3
        assert len(ctx["similar"]) == 2
        s = ctx["summary"]
        assert s["similar_count"] == 2
        assert s["recent_positive"] is True
        assert s["recent_negative"] is True
        # (0.9 + 0.6) / 2 = 0.75
        assert abs(s["avg_relevance"] - 0.75) < 0.01
        # 100.0 + (-20.0) = 80.0
        assert s["total_revenue"] == 80.0

    def test_context_k_propagates_to_retrieval(self, cli):
        action = _fake_action()
        q = _fake_queue(action)
        with patch(
            "core.approval.get_approval_queue", return_value=q,
        ), patch(
            "core.decision_retrieval.DecisionRetrieval",
        ) as retriever_cls:
            retriever_cls.return_value.retrieve.return_value = []
            _capture(
                cli._cmd_approvals_show,
                _ns(with_context=True, context_k=10),
            )
        # k=10 should have been passed to retrieve()
        call_kwargs = retriever_cls.return_value.retrieve.call_args.kwargs
        assert call_kwargs.get("k") == 10

    def test_empty_results_render_zero_summary(self, cli):
        action = _fake_action()
        q = _fake_queue(action)
        with patch(
            "core.approval.get_approval_queue", return_value=q,
        ), patch(
            "core.decision_retrieval.DecisionRetrieval",
        ) as retriever_cls:
            retriever_cls.return_value.retrieve.return_value = []
            out, _ = _capture(
                cli._cmd_approvals_show, _ns(with_context=True),
            )
        data = json.loads(out)
        ctx = data["agi_context"]
        assert ctx["similar"] == []
        assert ctx["summary"]["similar_count"] == 0
        assert ctx["summary"]["recent_positive"] is False
        assert ctx["summary"]["recent_negative"] is False
        assert ctx["summary"]["avg_relevance"] == 0.0


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_retrieval_failure_surfaces_error_section(self, cli):
        action = _fake_action()
        q = _fake_queue(action)
        with patch(
            "core.approval.get_approval_queue", return_value=q,
        ), patch(
            "core.decision_retrieval.DecisionRetrieval",
            side_effect=RuntimeError("retrieval down"),
        ):
            out, _ = _capture(
                cli._cmd_approvals_show, _ns(with_context=True),
            )
        data = json.loads(out)
        # Context section present with error -- the main payload
        # still rendered (action details + outcomes).
        assert "agi_context" in data
        assert "error" in data["agi_context"]
        assert "retrieval down" in data["agi_context"]["error"]


# ─── Helper: _summarize_context ───────────────────────────────


class TestSummarizeContext:

    def test_empty(self, cli):
        s = cli._summarize_context([])
        assert s["similar_count"] == 0
        assert s["recent_positive"] is False
        assert s["recent_negative"] is False

    def test_missing_outcome_summary(self, cli):
        # Entries without ``outcome_summary`` should not crash
        s = cli._summarize_context([
            {"relevance": 0.5},  # no outcome_summary
        ])
        assert s["similar_count"] == 1
        assert s["recent_positive"] is False
        assert s["avg_relevance"] == 0.5
