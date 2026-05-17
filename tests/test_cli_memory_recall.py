"""Tests for ``shopai memory-recall`` -- Decision-time RAG CLI
inspector. Layer 2 of the AGI orchestration stack.

Focuses on what's CLI-specific:
  - Argument plumbing (engine, action_type, capability,
    params, store, k)
  - --store flag propagates through to
    DecisionRetrieval.retrieve(store_id=...)
  - Pre-#241 retriever (no store_id kwarg) → graceful fallback
    + warning in text mode
  - JSON envelope shape includes store_id in query block
  - Empty result rendering
  - --params-json validation (invalid JSON / non-dict)

Retrieval-layer behaviour (relevance scoring, candidate pool,
outcome join) is covered in tests/test_decision_retrieval.py.
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
        engine="loyalty",
        action_type="",
        capability="",
        params_json="",
        k=5,
        store_id="",
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_retriever(results=None, raises=None,
                    raises_on_store_id_only=False):
    """Build a DecisionRetrieval stub.

    If ``raises_on_store_id_only`` is True, the first call (with
    store_id kwarg) raises TypeError mimicking the pre-#241
    retriever, and the second call (without store_id) returns
    ``results``.
    """
    results = results or []
    inst = MagicMock()
    state = {"calls": 0}

    def _retrieve(**kwargs):
        state["calls"] += 1
        if raises is not None:
            raise raises
        if raises_on_store_id_only and "store_id" in kwargs:
            raise TypeError(
                "unexpected keyword argument 'store_id'"
            )
        return list(results)

    inst.retrieve.side_effect = _retrieve
    return inst


# ─── Argument plumbing ───────────────────────────────────────


class TestArgPlumbing:

    def test_basic_retrieve_call(self, cli):
        inst = _fake_retriever(results=[])
        with patch(
            "core.decision_retrieval.DecisionRetrieval",
            return_value=inst,
        ):
            out, code = _capture(
                cli._cmd_memory_recall,
                _ns(engine="loyalty", json=True),
            )
        assert code == 0
        # Retrieve was called with the supplied args.
        kw = inst.retrieve.call_args.kwargs
        assert kw["engine"] == "loyalty"
        assert kw["k"] == 5

    def test_action_type_capability_passed_through(self, cli):
        inst = _fake_retriever(results=[])
        with patch(
            "core.decision_retrieval.DecisionRetrieval",
            return_value=inst,
        ):
            _capture(
                cli._cmd_memory_recall,
                _ns(
                    engine="loyalty",
                    action_type="mint_loyalty_code",
                    capability="SHOPIFY_CREATE_DISCOUNT",
                    json=True,
                ),
            )
        kw = inst.retrieve.call_args.kwargs
        assert kw["action_type"] == "mint_loyalty_code"
        assert kw["capability"] == "SHOPIFY_CREATE_DISCOUNT"

    def test_empty_filters_become_none(self, cli):
        """Empty strings on optional filters should be normalised
        to None so the retriever doesn't waste cycles comparing
        empty strings to candidate values."""
        inst = _fake_retriever(results=[])
        with patch(
            "core.decision_retrieval.DecisionRetrieval",
            return_value=inst,
        ):
            _capture(
                cli._cmd_memory_recall,
                _ns(engine="loyalty", json=True),
            )
        kw = inst.retrieve.call_args.kwargs
        assert kw["action_type"] is None
        assert kw["capability"] is None


# ─── --store flag ────────────────────────────────────────────


class TestStoreFlag:

    def test_store_flag_propagates_to_retriever(self, cli):
        inst = _fake_retriever(results=[])
        with patch(
            "core.decision_retrieval.DecisionRetrieval",
            return_value=inst,
        ):
            _capture(
                cli._cmd_memory_recall,
                _ns(engine="loyalty", store_id="store-a",
                    json=True),
            )
        kw = inst.retrieve.call_args.kwargs
        assert kw["store_id"] == "store-a"

    def test_store_empty_means_fleet_wide(self, cli):
        """Omitted / empty --store should send store_id=None,
        matching cross-store transfer semantics."""
        inst = _fake_retriever(results=[])
        with patch(
            "core.decision_retrieval.DecisionRetrieval",
            return_value=inst,
        ):
            _capture(
                cli._cmd_memory_recall,
                _ns(engine="loyalty", store_id="", json=True),
            )
        kw = inst.retrieve.call_args.kwargs
        assert kw["store_id"] is None

    def test_pre_pr_241_retriever_falls_back(self, cli):
        """If DecisionRetrieval.retrieve doesn't accept
        store_id (pre-PR #241), the handler should retry
        without it and still return results."""
        inst = _fake_retriever(
            results=[{"action_id": "a1", "engine": "loyalty"}],
            raises_on_store_id_only=True,
        )
        with patch(
            "core.decision_retrieval.DecisionRetrieval",
            return_value=inst,
        ):
            out, code = _capture(
                cli._cmd_memory_recall,
                _ns(engine="loyalty", store_id="store-a",
                    json=True),
            )
        assert code == 0
        # Should have called twice: first with store_id (TypeError),
        # second without.
        assert inst.retrieve.call_count == 2
        data = json.loads(out)
        assert len(data["results"]) == 1

    def test_pre_pr_241_text_mode_warns(self, cli):
        inst = _fake_retriever(
            results=[],
            raises_on_store_id_only=True,
        )
        with patch(
            "core.decision_retrieval.DecisionRetrieval",
            return_value=inst,
        ):
            out, code = _capture(
                cli._cmd_memory_recall,
                _ns(engine="loyalty", store_id="store-a"),
            )
        assert code == 0
        assert "store" in out.lower()
        assert "ignored" in out.lower()

    def test_store_filter_surfaces_in_query_envelope(self, cli):
        inst = _fake_retriever(results=[])
        with patch(
            "core.decision_retrieval.DecisionRetrieval",
            return_value=inst,
        ):
            out, _ = _capture(
                cli._cmd_memory_recall,
                _ns(engine="loyalty", store_id="store-a",
                    json=True),
            )
        data = json.loads(out)
        assert data["query"]["store_id"] == "store-a"

    def test_store_filter_shows_in_text_query_line(self, cli):
        inst = _fake_retriever(results=[])
        with patch(
            "core.decision_retrieval.DecisionRetrieval",
            return_value=inst,
        ):
            out, _ = _capture(
                cli._cmd_memory_recall,
                _ns(engine="loyalty", store_id="store-a"),
            )
        assert "store=store-a" in out


# ─── --params-json validation ────────────────────────────────


class TestParamsJsonValidation:

    def test_invalid_json_rejected(self, cli):
        with patch(
            "core.decision_retrieval.DecisionRetrieval",
            return_value=_fake_retriever(results=[]),
        ):
            out, code = _capture(
                cli._cmd_memory_recall,
                _ns(params_json="not-json{{", json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
        assert "not valid JSON" in data["error"]

    def test_non_dict_rejected(self, cli):
        with patch(
            "core.decision_retrieval.DecisionRetrieval",
            return_value=_fake_retriever(results=[]),
        ):
            out, code = _capture(
                cli._cmd_memory_recall,
                _ns(params_json='["a", "b"]', json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert "must be a JSON object" in data["error"]


# ─── Empty result rendering ──────────────────────────────────


class TestEmptyResults:

    def test_no_results_text_friendly(self, cli):
        inst = _fake_retriever(results=[])
        with patch(
            "core.decision_retrieval.DecisionRetrieval",
            return_value=inst,
        ):
            out, code = _capture(
                cli._cmd_memory_recall,
                _ns(engine="loyalty"),
            )
        assert code == 0
        assert "no similar past decisions" in out
