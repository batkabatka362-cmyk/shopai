"""Tests for ``shopai outcomes`` — chronological view of recent
webhook outcomes across engines.

The companion to ``shopai loop`` (snapshot) and ``approvals show``
(everything about one action). ``outcomes`` is the across-engine
ticker: "what's happening downstream right now?".

Coverage:
  - default text render
  - --json mode (valid JSON, jq-friendly)
  - filters compose (engine + polarity + --since AGE)
  - invalid --since → exits 1 with friendly message
  - empty result renders a clear message
  - queue-lookup failure renders empty instead of crashing
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
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


def _seed_one(queue, *, engine, polarity, topic, revenue=None):
    """Helper: enqueue → approve → attach_result → record_outcome."""
    a = queue.enqueue(
        engine=engine, action_type="mint_code",
        capability="X", params={"token": f"cust_{engine}"},
        narrative="t", confidence=0.85,
    )
    queue.approve(a.id, decided_by="op")
    queue.attach_result(
        a.id, success=True, result={"code": "X"},
    )
    metrics = {"revenue": revenue} if revenue is not None else {}
    queue.record_outcome(
        a.id, topic=topic, polarity=polarity,
        metrics=metrics, source_event=f"ev_{a.id}",
    )
    return a


def _ns(**kw):
    """argparse Namespace with `outcomes`-shaped defaults."""
    defaults = dict(
        limit=20, engine=None, polarity=None, since=None,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class TestTextRender:

    def test_renders_recent_outcomes(self, cli, isolated_queue):
        _seed_one(
            isolated_queue, engine="cart_recovery",
            polarity="positive", topic="orders/create",
            revenue=50.0,
        )
        out, code = _capture(cli._cmd_outcomes, _ns())
        assert code == 0
        assert "Recent outcomes" in out
        assert "cart_recovery/mint_code" in out
        assert "positive" in out
        assert "orders/create" in out
        # Revenue surfaced inline when present
        assert "rev=50.00" in out
        # Drill-down hint points at the top action
        assert "Drill down: `shopai approvals show" in out

    def test_empty_renders_friendly_message(self, cli, isolated_queue):
        out, code = _capture(cli._cmd_outcomes, _ns())
        assert code == 0
        assert "No recent outcomes" in out

    def test_empty_with_filters_shows_filter_summary(
        self, cli, isolated_queue,
    ):
        out, _ = _capture(
            cli._cmd_outcomes,
            _ns(engine="cart_recovery", polarity="positive"),
        )
        assert "engine=cart_recovery" in out
        assert "polarity=positive" in out


class TestJsonMode:

    def test_json_emits_array(self, cli, isolated_queue):
        _seed_one(
            isolated_queue, engine="x", polarity="positive",
            topic="orders/create",
        )
        out, code = _capture(cli._cmd_outcomes, _ns(json=True))
        assert code == 0
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) == 1
        row = data[0]
        assert row["engine"] == "x"
        assert row["topic"] == "orders/create"
        assert row["polarity"] == "positive"
        assert "action_id" in row
        assert "recorded_at" in row

    def test_json_empty_is_empty_array(self, cli, isolated_queue):
        out, _ = _capture(cli._cmd_outcomes, _ns(json=True))
        data = json.loads(out)
        assert data == []

    def test_json_first_char_is_bracket(self, cli, isolated_queue):
        """jq-friendly: no text prefix."""
        out, _ = _capture(cli._cmd_outcomes, _ns(json=True))
        assert out.strip()[0] == "["


class TestFilters:

    def test_engine_filter_isolates(self, cli, isolated_queue):
        _seed_one(
            isolated_queue, engine="cart_recovery",
            polarity="positive", topic="orders/create",
        )
        _seed_one(
            isolated_queue, engine="loyalty",
            polarity="positive", topic="orders/create",
        )
        out, _ = _capture(
            cli._cmd_outcomes,
            _ns(json=True, engine="cart_recovery"),
        )
        data = json.loads(out)
        assert len(data) == 1
        assert data[0]["engine"] == "cart_recovery"

    def test_polarity_filter_isolates(self, cli, isolated_queue):
        _seed_one(
            isolated_queue, engine="x", polarity="positive",
            topic="orders/create",
        )
        _seed_one(
            isolated_queue, engine="x", polarity="negative",
            topic="refunds/create",
        )
        out, _ = _capture(
            cli._cmd_outcomes,
            _ns(json=True, polarity="negative"),
        )
        data = json.loads(out)
        assert len(data) == 1
        assert data[0]["polarity"] == "negative"
        assert data[0]["topic"] == "refunds/create"

    def test_limit_caps_output(self, cli, isolated_queue):
        for i in range(5):
            _seed_one(
                isolated_queue, engine=f"e{i}",
                polarity="positive", topic="orders/create",
            )
        out, _ = _capture(
            cli._cmd_outcomes, _ns(json=True, limit=2),
        )
        data = json.loads(out)
        assert len(data) == 2

    def test_since_filter_age_spec_parsed(self, cli, isolated_queue):
        """``--since 1h`` translates to since_seconds=3600."""
        _seed_one(
            isolated_queue, engine="x",
            polarity="positive", topic="orders/create",
        )
        out, code = _capture(
            cli._cmd_outcomes,
            _ns(json=True, since="1h"),
        )
        assert code == 0
        data = json.loads(out)
        # Recently seeded → within 1h window
        assert len(data) == 1

    def test_invalid_since_exits_1(self, cli, isolated_queue):
        out, code = _capture(
            cli._cmd_outcomes,
            _ns(since="bogus"),
        )
        assert code == 1
        assert "Invalid --since" in out


class TestResilience:

    def test_queue_lookup_failure_renders_empty(
        self, cli, isolated_queue,
    ):
        """If the queue raises, render an empty result rather
        than 500'ing the operator's terminal."""
        with patch.object(
            isolated_queue, "list_recent_outcomes",
            side_effect=RuntimeError("db lock"),
        ):
            out, code = _capture(cli._cmd_outcomes, _ns())
        assert code == 0
        assert "No recent outcomes" in out


class TestOrdering:

    def test_newest_first(self, cli, isolated_queue):
        first = _seed_one(
            isolated_queue, engine="a",
            polarity="positive", topic="orders/create",
        )
        # Ensure a measurable gap so SQLite's TIME() comparison is
        # deterministic across fast machines
        time.sleep(0.01)
        second = _seed_one(
            isolated_queue, engine="b",
            polarity="positive", topic="orders/create",
        )
        out, _ = _capture(cli._cmd_outcomes, _ns(json=True))
        data = json.loads(out)
        # Newest first → engine "b" before "a"
        assert data[0]["engine"] == "b"
        assert data[1]["engine"] == "a"
