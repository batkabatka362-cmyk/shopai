"""Tests for ``GET /api/outcomes`` — recent webhook outcomes
endpoint.

HTTP parity for the CLI's ``shopai outcomes``. Returns a list of
flat dicts joining each outcome to its source action.
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest


def _make_handler(query: str = ""):
    from api.server import ShopAIHandler
    handler = ShopAIHandler.__new__(ShopAIHandler)
    handler.path = f"/api/outcomes{query}"
    responses: list[tuple[int, dict]] = []
    handler._json_response = (
        lambda s, b: responses.append((s, b))
    )
    return handler, responses


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _seed(queue, *, engine, polarity, topic, revenue=None):
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


class TestEmpty:

    def test_empty_returns_200_with_empty_list(self, isolated_queue):
        handler, responses = _make_handler()
        handler._recent_outcomes()
        status, body = responses[0]
        assert status == 200
        assert body == {"outcomes": [], "count": 0}


class TestPayload:

    def test_outcomes_envelope_shape(self, isolated_queue):
        _seed(
            isolated_queue, engine="cart_recovery",
            polarity="positive", topic="orders/create",
            revenue=42.0,
        )
        handler, responses = _make_handler()
        handler._recent_outcomes()
        status, body = responses[0]
        assert status == 200
        assert set(body.keys()) == {"outcomes", "count"}
        assert body["count"] == 1
        assert len(body["outcomes"]) == 1
        row = body["outcomes"][0]
        assert row["engine"] == "cart_recovery"
        assert row["topic"] == "orders/create"
        assert row["polarity"] == "positive"
        assert row["metrics"]["revenue"] == 42.0


class TestQueryParams:

    def test_default_limit_20(self, isolated_queue):
        for i in range(25):
            _seed(
                isolated_queue, engine=f"e{i}",
                polarity="positive", topic="orders/create",
            )
        handler, responses = _make_handler()
        handler._recent_outcomes()
        body = responses[0][1]
        assert len(body["outcomes"]) == 20
        assert body["count"] == 20

    def test_explicit_limit_honored(self, isolated_queue):
        for i in range(5):
            _seed(
                isolated_queue, engine=f"e{i}",
                polarity="positive", topic="orders/create",
            )
        handler, responses = _make_handler("?limit=3")
        handler._recent_outcomes()
        body = responses[0][1]
        assert len(body["outcomes"]) == 3

    def test_limit_clamped_above(self, isolated_queue):
        """``?limit=9999`` clamps to 500 — DoS guard."""
        handler, responses = _make_handler("?limit=9999")
        handler._recent_outcomes()
        # No outcomes, but the clamp logic ran without raising
        assert responses[0][0] == 200

    def test_limit_invalid_falls_to_default(self, isolated_queue):
        handler, responses = _make_handler("?limit=garbage")
        handler._recent_outcomes()
        assert responses[0][0] == 200

    def test_engine_filter(self, isolated_queue):
        _seed(
            isolated_queue, engine="cart_recovery",
            polarity="positive", topic="orders/create",
        )
        _seed(
            isolated_queue, engine="loyalty",
            polarity="positive", topic="orders/create",
        )
        handler, responses = _make_handler(
            "?engine=cart_recovery",
        )
        handler._recent_outcomes()
        body = responses[0][1]
        assert body["count"] == 1
        assert body["outcomes"][0]["engine"] == "cart_recovery"

    def test_polarity_filter(self, isolated_queue):
        _seed(
            isolated_queue, engine="x",
            polarity="positive", topic="orders/create",
        )
        _seed(
            isolated_queue, engine="x",
            polarity="negative", topic="refunds/create",
        )
        handler, responses = _make_handler("?polarity=negative")
        handler._recent_outcomes()
        body = responses[0][1]
        assert body["count"] == 1
        assert body["outcomes"][0]["polarity"] == "negative"

    def test_invalid_polarity_silently_dropped(
        self, isolated_queue,
    ):
        """Unknown polarity strings are dropped (treated as no
        filter) rather than 400'd — query-param validation in a
        read-only endpoint shouldn't be punitive."""
        _seed(
            isolated_queue, engine="x",
            polarity="positive", topic="orders/create",
        )
        handler, responses = _make_handler("?polarity=cosmic")
        handler._recent_outcomes()
        body = responses[0][1]
        # Unknown polarity → ignored, all rows returned
        assert body["count"] == 1


class TestResilience:

    def test_queue_failure_returns_empty_200(self, isolated_queue):
        """Queue lookup raising must NOT 500 — dashboard endpoints
        return empty arrays on failure."""
        with patch.object(
            isolated_queue, "list_recent_outcomes",
            side_effect=RuntimeError("db lock"),
        ):
            handler, responses = _make_handler()
            handler._recent_outcomes()
        status, body = responses[0]
        assert status == 200
        assert body == {"outcomes": [], "count": 0}


class TestRouteRegistration:

    def test_route_in_get_table(self):
        import inspect
        from api.server import ShopAIHandler

        src = inspect.getsource(ShopAIHandler.do_GET)
        assert '"/api/outcomes"' in src
        assert "_recent_outcomes" in src
