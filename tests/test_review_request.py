"""Tests for engines.review_request — W963-16."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from engines.review_request import ReviewRequestEngine
from engines.review_request.sender import (
    BatchReport,
    build_batch,
    send_batch,
)
from engines.review_request.templates import (
    EmailTemplate,
    get_template,
    render,
)


# ── Templates ─────────────────────────────────────────────


class TestTemplates:
    def test_known_niches_have_subject_and_body(self):
        for niche in ("beauty", "fashion", "home", "tech", "food"):
            t = get_template(niche)
            assert "{customer_name}" in t.subject or "{customer_name}" in t.body_html  # noqa: E501
            assert "{product_title}" in t.subject or "{product_title}" in t.body_html  # noqa: E501

    def test_unknown_niche_falls_back_to_baseline(self):
        t = get_template("automotive")
        assert isinstance(t, EmailTemplate)
        assert "{customer_name}" in t.body_html

    def test_none_niche_falls_back(self):
        t = get_template(None)
        assert isinstance(t, EmailTemplate)

    def test_render_substitutes_first_name_only(self):
        t = EmailTemplate(
            subject="Hi {customer_name}",
            body_html="<p>{customer_name}, {product_title}</p>",
        )
        subj, body = render(
            t,
            customer_name="Jane Doe",
            product_title="Serum",
            store_name="Glow",
            review_link="https://x.com/r/1",
        )
        assert subj == "Hi Jane"
        assert "Jane" in body and "Doe" not in body

    def test_render_falls_back_to_there_on_no_name(self):
        t = EmailTemplate(
            subject="Hi {customer_name}", body_html="x",
        )
        subj, _ = render(
            t,
            customer_name=None,
            product_title="P",
            store_name=None,
            review_link=None,
        )
        assert "there" in subj


# ── Tracking ──────────────────────────────────────────────


class TestTracking:
    def test_has_asked_empty(self, tmp_path):
        from engines.review_request import tracking
        tracking.reset_path(tmp_path / "rr.json")
        assert not tracking.has_asked("order-1")

    def test_mark_asked_is_guarded_under_pytest(self, tmp_path):
        # mark_asked short-circuits under PYTEST_CURRENT_TEST.
        from engines.review_request import tracking
        tracking.reset_path(tmp_path / "rr.json")
        wrote = tracking.mark_asked(
            order_id="order-1",
            customer_email="x@y.com",
            product_title="P",
        )
        assert wrote is False  # Pattern J guard

    def test_clear_asked_test_guard(self, tmp_path):
        from engines.review_request import tracking
        tracking.reset_path(tmp_path / "rr.json")
        assert tracking.clear_asked("nope") is False


# ── Sender: build_batch ───────────────────────────────────


def _make_order(
    order_id: str = "1001",
    *,
    age_days: float = 14.0,
    email: str = "buyer@example.com",
    cancelled: bool = False,
    product_title: str = "Serum",
):
    now = time.time()
    created = now - (age_days * 86400)
    from datetime import datetime, timezone
    return {
        "id": order_id,
        "created_at": datetime.fromtimestamp(
            created, tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer_email": email,
        "customer_first_name": "Jane",
        "customer_last_name": "Doe",
        "line_items": [{"title": product_title}],
        "cancelled_at": "2024-01-01T00:00:00Z" if cancelled else None,
    }


class TestBuildBatch:
    def test_no_orders_returns_empty(self):
        r = build_batch(orders=[])
        assert r.queued == 0
        assert r.eligible == 0

    def test_recent_order_skipped_too_recent(self):
        order = _make_order(age_days=1.0)
        r = build_batch(orders=[order], window_days=14.0)
        assert r.queued == 0
        assert r.skipped_reasons.get("too_recent") == 1

    def test_old_order_skipped_too_old(self):
        order = _make_order(age_days=100.0)
        r = build_batch(orders=[order], window_days=14.0)
        assert r.queued == 0
        assert r.skipped_reasons.get("too_old") == 1

    def test_eligible_in_window(self):
        order = _make_order(age_days=20.0)
        r = build_batch(orders=[order], window_days=14.0)
        assert r.eligible == 1
        assert r.queued == 1
        assert r.requests[0].customer_email == (
            "buyer@example.com"
        )

    def test_cancelled_skipped(self):
        order = _make_order(age_days=20.0, cancelled=True)
        r = build_batch(orders=[order])
        assert r.queued == 0
        assert r.skipped_reasons.get("cancelled") == 1

    def test_missing_email_skipped(self):
        order = _make_order(age_days=20.0, email="")
        r = build_batch(orders=[order])
        assert r.queued == 0
        assert r.skipped_reasons.get("no_customer_email") == 1

    def test_limit_respected(self):
        orders = [
            _make_order(order_id=str(i), age_days=20.0)
            for i in range(10)
        ]
        r = build_batch(orders=orders, limit=3)
        assert r.queued == 3

    def test_niche_changes_subject(self):
        order = _make_order(age_days=20.0)
        r_beauty = build_batch(
            orders=[order], niche="beauty",
        )
        r_tech = build_batch(
            orders=[order], niche="tech",
        )
        assert r_beauty.requests[0].subject != (
            r_tech.requests[0].subject
        )


# ── Sender: send_batch ────────────────────────────────────


class TestSendBatch:
    def test_router_unavailable_marks_failed(self):
        order = _make_order(age_days=20.0)
        with patch(
            "core.adapters.router.get_router",
            side_effect=Exception("no router"),
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            r = send_batch(orders=[order])
        assert r.sent == 0
        assert r.failed == 1

    def test_router_unavailable_records_writeback(self):
        # Regression: BUG-9 — Pattern Z gap on router-
        # unavailable path.
        order = _make_order(age_days=20.0)
        wb_calls = []
        def _capture(**kwargs):
            wb_calls.append(kwargs)
        with patch(
            "core.adapters.router.get_router",
            side_effect=Exception("no router"),
        ), patch(
            "engines._writeback_recorder.record_writeback",
            side_effect=_capture,
        ):
            send_batch(orders=[order])
        assert len(wb_calls) == 1
        assert wb_calls[0]["success"] is False
        assert "router unavailable" in wb_calls[0]["error"]

    def test_success(self):
        order = _make_order(age_days=20.0)
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True, data={"sent": True}, error="",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            r = send_batch(orders=[order])
        assert r.sent == 1
        assert r.failed == 0


# ── Engine Pattern Q envelope ─────────────────────────────


class TestEngineEnvelope:
    def test_empty_input_returns_status(self):
        result = ReviewRequestEngine().run({})
        assert result["status"] == "success"
        assert result["data"]["action"] == "status"

    def test_none_input(self):
        result = ReviewRequestEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_input_error(self):
        result = ReviewRequestEngine().run("nope")
        assert result["status"] == "error"

    def test_fail_upstream(self):
        result = ReviewRequestEngine().run({
            "status": "fail", "error": "broken",
        })
        assert result["status"] == "error"

    def test_unknown_action_error(self):
        result = ReviewRequestEngine().run({
            "data": {"action": "blast"},
        })
        assert result["status"] == "error"

    def test_non_string_action_does_not_crash(self):
        # Regression: action=42 used to AttributeError on
        # .lower() and break Pattern Q.
        for bad in (42, 3.14, [], {}, True):
            result = ReviewRequestEngine().run({
                "data": {"action": bad},
            })
            assert result["status"] in {"success", "error"}
            assert isinstance(result["data"], (dict, type(None)))


# ── Engine actions ────────────────────────────────────────


class TestEngineActions:
    def test_status_envelope_shape(self):
        result = ReviewRequestEngine().run({
            "data": {"action": "status"},
        })
        assert result["status"] == "success"
        d = result["data"]
        assert "esp_ready" in d
        assert "asked_so_far" in d
        assert "next_action" in d

    def test_preview_shape_no_orders(self):
        # No router/hydrator -> graceful empty.
        result = ReviewRequestEngine().run({
            "data": {"action": "preview", "limit": 3},
        })
        assert result["status"] == "success"
        d = result["data"]
        assert d["report"]["queued"] == 0
        assert "next_action" in d

    def test_send_batch_with_mocked_router(self):
        order = _make_order(age_days=20.0)
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True, data={"sent": True}, error="",
        )
        with patch(
            "engines.review_request.sender._hydrate_orders",
            return_value=[order],
        ), patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            result = ReviewRequestEngine().run({
                "data": {
                    "action": "send-batch", "limit": 1,
                },
            })
        assert result["status"] == "success"
        assert result["data"]["report"]["sent"] == 1
