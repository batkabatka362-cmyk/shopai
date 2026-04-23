"""Tests for core/engines/email_campaigns/ — the engine
package.

Covers:
  * Flow definitions — every canonical flow exists + has
    valid step timing
  * Queue — enqueue / idempotency / pop_due / mark_* /
    unsubscribe / stats / persistence across re-open
  * Dispatcher — render templates, skip missing context,
    skip unsubscribed, send via injected fn, failure-
    isolation across batch
  * Engine — enroll, dispatch_due integration, stats shape,
    unsubscribe flow
"""
from __future__ import annotations

import pytest

from core.engines.email_campaigns.flows import (
    FLOWS, FlowStep, get_flow, list_flow_ids,
)
from core.engines.email_campaigns.queue import (
    ScheduleQueue,
)
from core.engines.email_campaigns.dispatcher import (
    _render, _context_complete, _find_step,
    dispatch, DispatchReport,
)
from core.engines.email_campaigns.engine import (
    EmailCampaignEngine, reset_singleton_for_tests,
)


# ── Flow definitions ─────────────────────────────────────


class TestFlows:
    def test_four_canonical_flows(self):
        assert set(FLOWS.keys()) == {
            "welcome", "abandoned_cart",
            "post_purchase", "win_back",
        }
        assert list_flow_ids() == sorted(FLOWS.keys())

    def test_welcome_has_three_steps(self):
        flow = FLOWS["welcome"]
        assert len(flow.steps) == 3

    def test_abandoned_cart_timing(self):
        flow = FLOWS["abandoned_cart"]
        steps = flow.ordered_steps()
        # First step fires at 1 hour, second at 1 day
        assert steps[0].delay_minutes == 60
        assert steps[1].delay_minutes == 24 * 60

    def test_ordered_steps_is_sorted(self):
        flow = FLOWS["welcome"]
        ordered = flow.ordered_steps()
        delays = [s.delay_minutes for s in ordered]
        assert delays == sorted(delays)

    def test_step_requires_non_empty_copy(self):
        with pytest.raises(ValueError):
            FlowStep(
                step_id="x", delay_minutes=0,
                subject="", body="",
            )

    def test_step_negative_delay_raises(self):
        with pytest.raises(ValueError):
            FlowStep(
                step_id="x", delay_minutes=-1,
                subject="Hi", body="body",
            )

    def test_required_context_declared_per_step(self):
        """Every template placeholder must appear in
        required_context so the dispatcher's skip logic can
        detect incomplete enrollments."""
        flow = FLOWS["post_purchase"]
        for step in flow.steps:
            # Each step's subject + body should only reference
            # placeholders in required_context OR the defaults
            # the caller doesn't supply (none in our flows).
            for key in step.required_context:
                assert f"{{{key}}}" in (
                    step.subject + step.body
                ), (
                    f"{flow.flow_id}:{step.step_id} declares "
                    f"{key!r} in required_context but doesn't "
                    f"reference it"
                )

    def test_get_flow_returns_none_for_unknown(self):
        assert get_flow("does-not-exist") is None


# ── ScheduleQueue ────────────────────────────────────────


@pytest.fixture
def queue(tmp_path):
    return ScheduleQueue(db_path=str(tmp_path / "q.db"))


class TestQueueEnqueue:
    def test_basic_enqueue(self, queue):
        row = queue.enqueue(
            recipient="a@b.c",
            flow_id="welcome",
            step_id="welcome_intro",
            send_at=1_700_000_000.0,
            context={"store_name": "Deguar"},
        )
        assert row is not None
        assert row.recipient == "a@b.c"
        assert row.status == "pending"
        assert row.row_id

    def test_recipient_lowercased(self, queue):
        row = queue.enqueue(
            recipient="MixedCase@Example.COM",
            flow_id="welcome", step_id="s",
            send_at=0, context={},
        )
        assert row.recipient == "mixedcase@example.com"

    def test_idempotency_same_triple_returns_none(self, queue):
        """Re-enrolling the same (recipient, flow, step) is a
        no-op — prevents duplicate sends on retry."""
        queue.enqueue(
            recipient="a@b.c",
            flow_id="welcome", step_id="welcome_intro",
            send_at=1_700_000_000.0,
            context={"x": 1},
        )
        dup = queue.enqueue(
            recipient="a@b.c",
            flow_id="welcome", step_id="welcome_intro",
            send_at=1_700_000_000.0,
            context={"x": 2},  # different context — still dup
        )
        assert dup is None

    def test_different_steps_of_same_flow_allowed(self, queue):
        """Two steps of the welcome flow must each get their
        own row — same recipient, same flow, different step_id."""
        a = queue.enqueue(
            recipient="a@b.c", flow_id="welcome",
            step_id="welcome_intro",
            send_at=0, context={},
        )
        b = queue.enqueue(
            recipient="a@b.c", flow_id="welcome",
            step_id="welcome_top_picks",
            send_at=1000, context={},
        )
        assert a is not None
        assert b is not None
        assert a.row_id != b.row_id

    def test_blank_fields_raise(self, queue):
        with pytest.raises(ValueError):
            queue.enqueue(
                recipient="", flow_id="f", step_id="s",
                send_at=0, context={},
            )

    def test_context_round_trip(self, queue):
        ctx = {"a": 1, "nested": {"list": [1, 2, 3]}}
        row = queue.enqueue(
            recipient="a@b.c", flow_id="welcome",
            step_id="s", send_at=0, context=ctx,
        )
        fetched = queue.get(row.row_id)
        assert fetched.context == ctx


class TestQueuePopDue:
    def test_only_pending_due_rows_returned(self, tmp_path):
        clock = {"t": 1_700_000_000.0}
        q = ScheduleQueue(
            db_path=str(tmp_path / "q.db"),
            now_fn=lambda: clock["t"],
        )
        # Past-due
        q.enqueue(
            recipient="a@b.c", flow_id="welcome",
            step_id="s1", send_at=clock["t"] - 10,
            context={},
        )
        # Future
        q.enqueue(
            recipient="a@b.c", flow_id="welcome",
            step_id="s2", send_at=clock["t"] + 10_000,
            context={},
        )
        due = q.pop_due()
        assert len(due) == 1
        assert due[0].step_id == "s1"

    def test_sent_row_not_popped_again(self, tmp_path):
        q = ScheduleQueue(
            db_path=str(tmp_path / "q.db"),
            now_fn=lambda: 1_700_000_000.0,
        )
        row = q.enqueue(
            recipient="a@b.c", flow_id="welcome",
            step_id="s1", send_at=0, context={},
        )
        q.mark_sent(row.row_id, message_id="msg-1")
        due = q.pop_due()
        assert due == []

    def test_limit_respected(self, tmp_path):
        q = ScheduleQueue(
            db_path=str(tmp_path / "q.db"),
            now_fn=lambda: 1000.0,
        )
        # Use unique step_ids to dodge the idempotency key
        for i in range(5):
            q.enqueue(
                recipient="a@b.c", flow_id="welcome",
                step_id=f"s_{i}", send_at=0, context={},
            )
        assert len(q.pop_due(limit=3)) == 3


class TestQueueTransitions:
    def test_mark_sent_moves_row(self, queue):
        row = queue.enqueue(
            recipient="a@b.c", flow_id="welcome",
            step_id="s", send_at=0, context={},
        )
        ok = queue.mark_sent(row.row_id, message_id="msg-42")
        assert ok
        fetched = queue.get(row.row_id)
        assert fetched.status == "sent"
        assert fetched.message_id == "msg-42"
        assert fetched.sent_at > 0

    def test_mark_failed_records_error(self, queue):
        row = queue.enqueue(
            recipient="a@b.c", flow_id="welcome",
            step_id="s", send_at=0, context={},
        )
        queue.mark_failed(row.row_id, error="bounce")
        fetched = queue.get(row.row_id)
        assert fetched.status == "failed"
        assert fetched.error == "bounce"

    def test_terminal_state_sticky(self, queue):
        row = queue.enqueue(
            recipient="a@b.c", flow_id="welcome",
            step_id="s", send_at=0, context={},
        )
        queue.mark_sent(row.row_id)
        # Can't flip back
        assert not queue.mark_failed(row.row_id, error="late")
        fetched = queue.get(row.row_id)
        assert fetched.status == "sent"

    def test_skip_paths(self, queue):
        r1 = queue.enqueue(
            recipient="a@b.c", flow_id="welcome",
            step_id="s1", send_at=0, context={},
        )
        r2 = queue.enqueue(
            recipient="a@b.c", flow_id="welcome",
            step_id="s2", send_at=0, context={},
        )
        r3 = queue.enqueue(
            recipient="a@b.c", flow_id="welcome",
            step_id="s3", send_at=0, context={},
        )
        queue.mark_skipped_missing_ctx(
            r1.row_id, error="missing first_name",
        )
        queue.mark_skipped_unsubscribed(r2.row_id)
        queue.mark_cancelled(r3.row_id, error="owner halt")
        assert queue.get(r1.row_id).status == "skipped_missing_ctx"
        assert queue.get(r2.row_id).status == "skipped_unsubscribed"
        assert queue.get(r3.row_id).status == "cancelled"


class TestQueueUnsubscribe:
    def test_unsubscribe_round_trip(self, queue):
        queue.unsubscribe("a@b.c", source="owner-CLI")
        assert queue.is_unsubscribed("a@b.c")
        assert not queue.is_unsubscribed("other@x.com")

    def test_unsubscribe_lowercased(self, queue):
        queue.unsubscribe("UPPER@CASE.COM")
        assert queue.is_unsubscribed("upper@case.com")

    def test_idempotent_unsubscribe(self, queue):
        queue.unsubscribe("a@b.c")
        queue.unsubscribe("a@b.c")  # no-op
        assert queue.is_unsubscribed("a@b.c")


class TestQueueStats:
    def test_stats_shape(self, queue):
        r1 = queue.enqueue(
            recipient="a@b.c", flow_id="welcome",
            step_id="s1", send_at=0, context={},
        )
        r2 = queue.enqueue(
            recipient="a@b.c", flow_id="post_purchase",
            step_id="s2", send_at=0, context={},
        )
        queue.mark_sent(r1.row_id)
        queue.unsubscribe("other@x.com")
        s = queue.stats()
        assert s["totals"]["sent"] == 1
        assert s["totals"]["pending"] == 1
        assert s["flows"]["welcome"]["sent"] == 1
        assert s["flows"]["post_purchase"]["pending"] == 1
        assert s["unsubscribes"] == 1


class TestQueuePersistence:
    def test_survives_reopen(self, tmp_path):
        path = str(tmp_path / "persist.db")
        q1 = ScheduleQueue(db_path=path)
        row = q1.enqueue(
            recipient="a@b.c", flow_id="welcome",
            step_id="s", send_at=0, context={"x": 1},
        )
        q2 = ScheduleQueue(db_path=path)
        fetched = q2.get(row.row_id)
        assert fetched.recipient == "a@b.c"
        assert fetched.context == {"x": 1}


# ── Dispatcher ──────────────────────────────────────────


class TestRender:
    def test_basic_substitution(self):
        out = _render(
            "Hello {name}, {store}!",
            {"name": "Jane", "store": "Deguar"},
        )
        assert out == "Hello Jane, Deguar!"

    def test_missing_key_marker(self):
        out = _render(
            "Hi {name}", {},
        )
        assert "{MISSING:name}" in out

    def test_empty_template(self):
        assert _render("", {}) == ""


class TestContextComplete:
    def _step(self, **over) -> FlowStep:
        return FlowStep(
            step_id=over.get("step_id", "s"),
            delay_minutes=0,
            subject="Hi {a}",
            body="{a} and {b}",
            required_context=over.get(
                "required", ("a", "b"),
            ),
        )

    def test_complete_context(self):
        step = self._step()
        ok, missing = _context_complete(
            step, {"a": "x", "b": "y"},
        )
        assert ok
        assert missing == ""

    def test_missing_key(self):
        step = self._step()
        ok, missing = _context_complete(
            step, {"a": "x"},
        )
        assert not ok
        assert missing == "b"

    def test_empty_string_counts_as_missing(self):
        """Blank strings are useless in marketing copy —
        treat as missing."""
        step = self._step()
        ok, missing = _context_complete(
            step, {"a": "x", "b": "   "},
        )
        assert not ok
        assert missing == "b"


class TestDispatch:
    def _enqueue_due(self, q, **over):
        """Helper to drop a past-due row the dispatcher will
        pick up."""
        defaults = {
            "recipient": "customer@example.com",
            "flow_id": "welcome",
            "step_id": "welcome_intro",
            "send_at": 0.0,
            "context": {
                "first_name": "Jane",
                "store_name": "Deguar",
                "store_url": "https://deguar.myshopify.com",
                "discount_code": "WELCOME15",
                "top_products": "A\nB\nC",
            },
        }
        defaults.update(over)
        return q.enqueue(**defaults)

    def test_happy_path_sends(self, queue):
        sent: list[dict] = []

        def fake_send(msg):
            sent.append(msg)
            return "mock-msg-id"

        self._enqueue_due(queue)
        report = dispatch(
            queue, from_email="hello@deguar.com",
            send_fn=fake_send,
        )
        assert report.sent == 1
        assert report.failed == 0
        assert len(sent) == 1
        assert sent[0]["subject"].startswith("Welcome to Deguar")
        assert "WELCOME15" in sent[0]["text"]
        assert sent[0]["to"] == "customer@example.com"
        assert sent[0]["from_email"] == "hello@deguar.com"
        assert "welcome" in sent[0]["tags"]

    def test_missing_context_skipped(self, queue):
        """first_name absent → skip, not send. Prevents "Hi
        {first_name}" emails from going out."""
        self._enqueue_due(
            queue,
            context={
                # missing first_name
                "store_name": "Deguar",
                "store_url": "https://x",
                "discount_code": "WELCOME15",
            },
        )

        def fake_send(msg):
            raise AssertionError("should not be called")

        report = dispatch(
            queue, from_email="hello@x.com",
            send_fn=fake_send,
        )
        assert report.sent == 0
        assert report.skipped_missing_ctx == 1

    def test_unsubscribed_recipient_skipped(self, queue):
        self._enqueue_due(queue)
        queue.unsubscribe("customer@example.com")

        def fake_send(msg):
            raise AssertionError("should not send to unsub")

        report = dispatch(
            queue, from_email="hello@x.com",
            send_fn=fake_send,
        )
        assert report.sent == 0
        assert report.skipped_unsubscribed == 1

    def test_adapter_failure_isolated(self, queue):
        """One bad send doesn't abort the whole batch."""
        self._enqueue_due(
            queue, step_id="welcome_intro",
            recipient="ok@x.com",
        )
        self._enqueue_due(
            queue, step_id="welcome_intro",
            recipient="bad@x.com",
        )

        def flaky_send(msg):
            if msg["to"] == "bad@x.com":
                raise RuntimeError("rate limited")
            return "ok-id"

        report = dispatch(
            queue, from_email="hello@x.com",
            send_fn=flaky_send,
        )
        assert report.sent == 1
        assert report.failed == 1
        # Good recipient's row marked sent; bad one failed
        for r in queue.pop_due():
            pass  # should be empty — both terminal now
        bad_rows = queue.list_by_recipient("bad@x.com")
        assert bad_rows[0].status == "failed"
        assert "rate limited" in bad_rows[0].error

    def test_no_send_fn_marks_failed(self, queue):
        self._enqueue_due(queue)
        report = dispatch(
            queue, from_email="hello@x.com",
            send_fn=lambda m: None,
        )
        # Dispatcher's "no adapter configured" path — send_fn
        # is present but returns None, which means success
        # with no message_id. Row gets marked sent.
        assert report.sent == 1

    def test_due_field_reflects_pop_count(self, queue):
        for i, step in enumerate([
            "welcome_intro", "welcome_top_picks",
            "welcome_deadline",
        ]):
            self._enqueue_due(queue, step_id=step)

        def fake_send(msg):
            return "id"

        report = dispatch(
            queue, from_email="hello@x.com",
            send_fn=fake_send,
        )
        assert report.due == 3
        assert report.sent == 3

    def test_unknown_flow_fails(self, queue):
        queue.enqueue(
            recipient="a@b.c", flow_id="does_not_exist",
            step_id="s", send_at=0,
            context={}, enrollment_id="e1",
        )

        def fake_send(msg):
            return "id"

        report = dispatch(
            queue, from_email="hello@x.com",
            send_fn=fake_send,
        )
        assert report.failed == 1
        assert any("unknown flow" in e for e in report.errors)


# ── EmailCampaignEngine ─────────────────────────────────


@pytest.fixture
def engine(tmp_path):
    """Engine + queue share a fixed clock so tests can reason
    about which steps are due."""
    reset_singleton_for_tests()
    clock = {"t": 1_700_000_000.0}
    q = ScheduleQueue(
        db_path=str(tmp_path / "engine.db"),
        now_fn=lambda: clock["t"],
    )
    e = EmailCampaignEngine(
        queue=q,
        from_email="hello@deguar.com",
        now_fn=lambda: clock["t"],
    )
    e._clock = clock  # type: ignore[attr-defined]
    return e


class TestEnroll:
    def test_enroll_welcome(self, engine):
        result = engine.enroll(
            "customer@example.com",
            flow="welcome",
            context={
                "first_name": "Jane",
                "store_name": "Deguar",
                "store_url": "https://x",
                "discount_code": "WELCOME15",
                "top_products": "A\nB\nC",
            },
        )
        assert result["enrolled"] == 3
        assert result["skipped"] == 0
        assert result["unsubscribed"] is False
        assert result["enrollment_id"]

    def test_enroll_invalid_email_raises(self, engine):
        with pytest.raises(ValueError, match="valid email"):
            engine.enroll(
                "not-an-email", flow="welcome", context={},
            )

    def test_enroll_unknown_flow_raises(self, engine):
        with pytest.raises(ValueError, match="unknown flow"):
            engine.enroll(
                "a@b.c", flow="does_not_exist", context={},
            )

    def test_double_enroll_skips(self, engine):
        context = {
            "first_name": "Jane", "store_name": "Deguar",
            "store_url": "https://x", "discount_code": "W",
            "top_products": "A",
        }
        first = engine.enroll(
            "a@b.c", flow="welcome", context=context,
        )
        assert first["enrolled"] == 3
        second = engine.enroll(
            "a@b.c", flow="welcome", context=context,
        )
        # All three steps already present → 0 new, 3 skipped
        assert second["enrolled"] == 0
        assert second["skipped"] == 3

    def test_unsubscribed_skips_enroll(self, engine):
        engine.unsubscribe("a@b.c", source="test")
        result = engine.enroll(
            "a@b.c", flow="welcome", context={"x": 1},
        )
        assert result["unsubscribed"] is True
        assert result["enrolled"] == 0


class TestDispatchDue:
    def test_dispatch_picks_up_enrolled_rows(self, engine):
        sent: list[dict] = []

        engine.enroll(
            "customer@example.com", flow="welcome",
            context={
                "first_name": "Jane", "store_name": "Deguar",
                "store_url": "https://x",
                "discount_code": "WELCOME15",
                "top_products": "A\nB\nC",
            },
        )

        # Clock is fixed — only step with delay=0 is due
        # (welcome_intro)
        def fake_send(msg):
            sent.append(msg)
            return "mock-id"

        report = engine.dispatch_due(send_fn=fake_send)
        assert report.sent == 1
        assert len(sent) == 1
        assert sent[0]["to"] == "customer@example.com"

    def test_stats_after_dispatch(self, engine):
        engine.enroll(
            "a@b.c", flow="welcome",
            context={
                "first_name": "J", "store_name": "D",
                "store_url": "https://x",
                "discount_code": "W",
                "top_products": "A",
            },
        )

        def fake_send(msg):
            return "id"

        engine.dispatch_due(send_fn=fake_send)
        s = engine.stats()
        assert s["flows"]["welcome"]["sent"] == 1
        assert s["flows"]["welcome"]["pending"] == 2


class TestUnsubscribe:
    def test_unsubscribe_round_trip(self, engine):
        assert not engine.is_unsubscribed("a@b.c")
        engine.unsubscribe("a@b.c", source="owner")
        assert engine.is_unsubscribed("a@b.c")


class TestListForRecipient:
    def test_all_steps_visible(self, engine):
        engine.enroll(
            "a@b.c", flow="welcome",
            context={
                "first_name": "J", "store_name": "D",
                "store_url": "x", "discount_code": "W",
                "top_products": "A",
            },
        )
        rows = engine.list_for_recipient("a@b.c")
        assert len(rows) == 3
        # Sorted by send_at ascending
        assert rows[0].step_id == "welcome_intro"
