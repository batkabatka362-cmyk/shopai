"""Tests for engines.outcome_backfill — W963-44."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from engines.outcome_backfill import OutcomeBackfillEngine
from engines.outcome_backfill.backfiller import (
    BackfillReport,
    _matches_action_to_orders,
    _order_total,
    _parse_iso,
    run_backfill,
)


def _make_action(
    aid="a1",
    engine="loyalty",
    action_type="mint_code",
    store_id="s1",
    decided_at=None,
):
    a = MagicMock()
    a.id = aid
    a.engine = engine
    a.action_type = action_type
    a.store_id = store_id
    a.decided_at = decided_at
    return a


def _make_order(
    days_ago=1.0,
    total="100.00",
    cancelled=False,
    store_id="",
):
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=days_ago)
    return {
        "id": "o1",
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_price": total,
        "cancelled_at": (
            "2024-01-01" if cancelled else None
        ),
        "store_id": store_id,
    }


# ── _parse_iso ────────────────────────────────────────────


class TestParseIso:
    def test_string_iso(self):
        dt = _parse_iso("2026-06-04T12:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_unix_float(self):
        dt = _parse_iso(1780000000.5)
        assert dt is not None

    def test_unix_int(self):
        dt = _parse_iso(1780000000)
        assert dt is not None

    def test_datetime_passthrough(self):
        d = datetime(2026, 6, 4, tzinfo=timezone.utc)
        assert _parse_iso(d) == d

    def test_naive_datetime_gets_utc(self):
        d = datetime(2026, 6, 4)
        out = _parse_iso(d)
        assert out.tzinfo is not None

    def test_garbage_returns_none(self):
        assert _parse_iso("not-a-date") is None
        assert _parse_iso(None) is None
        assert _parse_iso("") is None


# ── _order_total ─────────────────────────────────────────


class TestOrderTotal:
    def test_total_price(self):
        assert _order_total({"total_price": "50"}) == 50.0

    def test_fallback_keys(self):
        assert _order_total({
            "current_total_price": "10",
        }) == 10.0

    def test_garbage(self):
        assert _order_total({"total_price": "x"}) == 0.0

    def test_missing(self):
        assert _order_total({}) == 0.0


# ── _matches_action_to_orders ─────────────────────────────


class TestMatches:
    def test_no_orders(self):
        decided = datetime(2026, 6, 1, tzinfo=timezone.utc)
        n, rev = _matches_action_to_orders(
            decided, [], action_store_id="s1",
        )
        assert n == 0
        assert rev == 0.0

    def test_order_after_action_counted(self):
        decided = datetime.now(timezone.utc) - timedelta(
            days=10,
        )
        order = _make_order(days_ago=5.0, total="100")
        n, rev = _matches_action_to_orders(
            decided, [order], action_store_id="",
        )
        assert n == 1
        assert rev == 100.0

    def test_order_before_action_skipped(self):
        decided = datetime.now(timezone.utc) - timedelta(
            days=1,
        )
        order = _make_order(days_ago=5.0)  # before decided
        n, rev = _matches_action_to_orders(
            decided, [order], action_store_id="",
        )
        assert n == 0

    def test_cancelled_excluded(self):
        decided = datetime.now(timezone.utc) - timedelta(
            days=10,
        )
        order = _make_order(
            days_ago=5.0, cancelled=True,
        )
        n, _ = _matches_action_to_orders(
            decided, [order], action_store_id="",
        )
        assert n == 0

    def test_store_mismatch_excluded(self):
        decided = datetime.now(timezone.utc) - timedelta(
            days=10,
        )
        order = _make_order(days_ago=5.0, store_id="sB")
        n, _ = _matches_action_to_orders(
            decided, [order], action_store_id="sA",
        )
        assert n == 0


# ── run_backfill ──────────────────────────────────────────


def _fake_queue(actions=None, outcomes_dict=None):
    q = MagicMock()
    q.list_by_status.return_value = actions or []
    q.get_outcomes.side_effect = (
        lambda aid: (outcomes_dict or {}).get(aid, [])
    )
    q.record_outcome.return_value = True
    return q


class TestRunBackfill:
    def test_no_actions(self):
        fake = _fake_queue()
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake,
        ):
            r = run_backfill(
                confirmed=False,
                executed_override=[],
            )
        assert r.total_executed_scanned == 0

    def test_no_action_id_skipped(self):
        action = _make_action(aid="")
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            r = run_backfill(
                confirmed=False,
                executed_override=[action],
            )
        assert r.skip_reasons.get("no_action_id") == 1

    def test_already_recorded_skipped(self):
        action = _make_action(decided_at=1780000000.0)
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                outcomes_dict={"a1": [{"x": 1}]},
            ),
        ):
            r = run_backfill(
                confirmed=False,
                executed_override=[action],
            )
        assert r.already_recorded == 1
        assert r.skip_reasons.get("already_recorded") == 1

    def test_bad_decided_at_skipped(self):
        action = _make_action(decided_at="not-a-time")
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            r = run_backfill(
                confirmed=False,
                executed_override=[action],
            )
        assert r.skip_reasons.get("bad_decided_at") == 1

    def test_too_recent_skipped(self):
        # decided 1 hour ago, min_age = 24h
        recent = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).timestamp()
        action = _make_action(decided_at=recent)
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            r = run_backfill(
                confirmed=False,
                min_age_hours=24.0,
                executed_override=[action],
                orders_override=[],
            )
        assert r.too_recent == 1

    def test_positive_outcome_matched_orders(self):
        decided = (
            datetime.now(timezone.utc) - timedelta(days=2)
        )
        action = _make_action(
            decided_at=decided.timestamp(),
        )
        order = _make_order(days_ago=1.0, total="50")
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            r = run_backfill(
                confirmed=False,
                min_age_hours=1.0,
                executed_override=[action],
                orders_override=[order],
            )
        # Dry-run: outcome computed but not recorded
        assert r.positive_count == 1
        assert r.decisions[0].outcome == "positive"

    def test_negative_outcome_after_grace(self):
        decided = (
            datetime.now(timezone.utc) - timedelta(days=10)
        )
        action = _make_action(
            decided_at=decided.timestamp(),
        )
        # No matching orders
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            r = run_backfill(
                confirmed=False,
                min_age_hours=24.0,
                grace_hours=168.0,
                executed_override=[action],
                orders_override=[],
            )
        assert r.negative_count == 1
        assert r.decisions[0].outcome == "negative"

    def test_awaiting_grace_no_outcome(self):
        # decided 2 days ago, grace 7 days
        decided = (
            datetime.now(timezone.utc) - timedelta(days=2)
        )
        action = _make_action(
            decided_at=decided.timestamp(),
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            r = run_backfill(
                confirmed=False,
                min_age_hours=24.0,
                grace_hours=168.0,
                executed_override=[action],
                orders_override=[],
            )
        assert r.skip_reasons.get("awaiting_grace") == 1

    def test_confirmed_records_outcome(self):
        decided = (
            datetime.now(timezone.utc) - timedelta(days=2)
        )
        action = _make_action(
            decided_at=decided.timestamp(),
        )
        order = _make_order(days_ago=1.0)
        fake = _fake_queue()
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=fake,
        ):
            r = run_backfill(
                confirmed=True,
                min_age_hours=1.0,
                executed_override=[action],
                orders_override=[order],
            )
        # record_outcome was called
        assert fake.record_outcome.called
        kwargs = fake.record_outcome.call_args.kwargs
        assert kwargs.get("polarity") == "positive"


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = OutcomeBackfillEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = OutcomeBackfillEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = OutcomeBackfillEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = OutcomeBackfillEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = OutcomeBackfillEngine().run({})
        assert r["meta"]["engine"] == "outcome_backfill"


class TestEngineActions:
    def test_double_gate_blocks(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(
                "SHOPAI_OUTCOME_BACKFILL_ENABLED", None,
            )
            r = OutcomeBackfillEngine().run({
                "data": {"confirmed": True},
            })
        assert r["data"]["confirmed"] is False

    def test_both_gates_set(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_OUTCOME_BACKFILL_ENABLED": "1"},
            clear=False,
        ):
            r = OutcomeBackfillEngine().run({
                "data": {"confirmed": True},
            })
        assert r["data"]["confirmed"] is True

    def test_invalid_min_age_falls_back(self):
        r = OutcomeBackfillEngine().run({
            "data": {"min_age_hours": "abc"},
        })
        assert r["data"]["min_age_hours"] == 24.0
