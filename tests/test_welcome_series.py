"""Tests for engines.welcome_series — W963-22."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from engines.welcome_series import WelcomeSeriesEngine
from engines.welcome_series.sender import (
    build_batch,
    send_batch,
)
from engines.welcome_series.templates import (
    WelcomeEmail,
    all_stages,
    get_stage,
    render,
)
from engines.welcome_series import tracking


# ── Templates ─────────────────────────────────────────────


class TestTemplates:
    def test_all_three_stages_have_subject_and_body(self):
        for stage in (1, 2, 3):
            t = get_stage(stage)
            assert t.subject
            assert t.body_html

    def test_unknown_stage_falls_back_to_stage_1(self):
        t = get_stage(99)
        assert t.stage == 1

    def test_all_stages_returns_three(self):
        assert all_stages() == [1, 2, 3]

    def test_render_first_name_only(self):
        t = WelcomeEmail(
            stage=1,
            subject="Hi {customer_name}",
            body_html="<p>{store_name}</p>",
        )
        subj, body = render(
            t,
            customer_name="John Smith",
            store_name="Glow",
            discount_code="W15",
            shop_url="https://x.com",
        )
        assert subj == "Hi John"
        assert "Glow" in body

    def test_render_defaults_when_missing(self):
        t = get_stage(1)
        subj, body = render(
            t,
            customer_name=None,
            store_name=None,
            discount_code=None,
            shop_url=None,
        )
        assert "there" in subj
        assert "WELCOME15" in body


# ── Tracking ──────────────────────────────────────────────


class TestTracking:
    def test_empty_state_no_stages(self, tmp_path):
        tracking.reset_path(tmp_path / "ws.json")
        assert tracking.stages_sent("c1") == []
        assert tracking.next_stage("c1") == 1

    def test_next_stage_progression(self, tmp_path):
        # No persistence in test env -- but next_stage runs
        # against an empty state, returns 1.
        tracking.reset_path(tmp_path / "ws.json")
        assert tracking.next_stage("c1") == 1

    def test_has_completed_false_initially(self, tmp_path):
        tracking.reset_path(tmp_path / "ws.json")
        assert not tracking.has_completed("c1")

    def test_mark_sent_blocked_under_pytest(self, tmp_path):
        tracking.reset_path(tmp_path / "ws.json")
        ok = tracking.mark_sent(
            customer_id="c1", stage=1, status="sent",
        )
        assert ok is False  # Pattern J guard

    def test_mark_sent_invalid_stage(self, tmp_path):
        tracking.reset_path(tmp_path / "ws.json")
        assert tracking.mark_sent(
            customer_id="c1", stage=99,
        ) is False

    def test_welcomed_count_empty(self, tmp_path):
        tracking.reset_path(tmp_path / "ws.json")
        assert tracking.welcomed_count() == 0


# ── Sender: build_batch ───────────────────────────────────


def _make_customer(
    cid: str = "1",
    email: str = "buyer@example.com",
    age_hours: float = 0.5,
):
    now = time.time()
    created = now - (age_hours * 3600.0)
    return {
        "id": cid,
        "email": email,
        "first_name": "Jane",
        "last_name": "Doe",
        "created_at": datetime.fromtimestamp(
            created, tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


class TestBuildBatch:
    def test_empty_returns_empty(self, tmp_path):
        tracking.reset_path(tmp_path / "ws.json")
        r = build_batch(customers=[])
        assert r.queued == 0

    def test_new_customer_eligible_for_stage_1(self, tmp_path):
        tracking.reset_path(tmp_path / "ws.json")
        c = _make_customer(age_hours=0.1)
        r = build_batch(customers=[c])
        assert r.queued == 1
        assert r.requests[0].stage == 1

    def test_missing_email_skipped(self, tmp_path):
        tracking.reset_path(tmp_path / "ws.json")
        c = _make_customer(email="")
        r = build_batch(customers=[c])
        assert r.queued == 0
        assert r.skipped_reasons.get("no_email") == 1

    def test_missing_id_skipped(self, tmp_path):
        tracking.reset_path(tmp_path / "ws.json")
        c = _make_customer()
        c["id"] = ""
        r = build_batch(customers=[c])
        assert r.skipped_reasons.get("no_customer_id") == 1

    def test_limit_respected(self, tmp_path):
        tracking.reset_path(tmp_path / "ws.json")
        cs = [
            _make_customer(cid=str(i)) for i in range(10)
        ]
        r = build_batch(customers=cs, limit=4)
        assert r.queued == 4

    def test_missing_created_at_stage_1_ok(self, tmp_path):
        # Stage 1 has gate=0, so a missing/malformed
        # created_at is still eligible.
        tracking.reset_path(tmp_path / "ws.json")
        c = _make_customer()
        c["created_at"] = ""
        r = build_batch(customers=[c])
        assert r.queued == 1
        assert r.requests[0].stage == 1

    def test_missing_created_at_higher_stages_fail_closed(
        self, tmp_path, monkeypatch,
    ):
        # If created_at is unparseable, stage 2 and 3 MUST
        # not fire — we don't know if the cadence gate
        # (48h / 120h) has elapsed.
        from engines.welcome_series import sender as snd
        monkeypatch.setattr(
            snd, "next_stage",
            lambda cid: 2,
        )
        c = _make_customer()
        c["created_at"] = "not-a-date"
        r = build_batch(customers=[c])
        assert r.queued == 0
        assert r.skipped_reasons.get("bad_created_at") == 1

    def test_malformed_created_at_stage_1_still_ok(
        self, tmp_path,
    ):
        # Stage 1: even garbage date is fine because
        # gate=0 fires immediately.
        tracking.reset_path(tmp_path / "ws.json")
        c = _make_customer()
        c["created_at"] = "2026-13-45T99:99:99Z"
        r = build_batch(customers=[c])
        assert r.queued == 1


# ── Sender: send_batch ────────────────────────────────────


class TestSendBatch:
    def test_router_unavailable_marks_failed(self, tmp_path):
        tracking.reset_path(tmp_path / "ws.json")
        c = _make_customer()
        with patch(
            "core.adapters.router.get_router",
            side_effect=Exception("no router"),
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            r = send_batch(customers=[c])
        assert r.sent == 0
        assert r.failed == 1

    def test_router_unavailable_records_writeback(
        self, tmp_path,
    ):
        # Regression: BUG-9 — router-unavailable path used
        # to return early WITHOUT calling record_writeback,
        # so attribution never saw the failure.
        tracking.reset_path(tmp_path / "ws.json")
        c = _make_customer()
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
            send_batch(customers=[c])
        assert len(wb_calls) == 1
        assert wb_calls[0]["success"] is False
        assert "router unavailable" in wb_calls[0]["error"]

    def test_success(self, tmp_path):
        tracking.reset_path(tmp_path / "ws.json")
        c = _make_customer()
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
            r = send_batch(customers=[c])
        assert r.sent == 1
        assert r.failed == 0


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_input_status(self):
        r = WelcomeSeriesEngine().run({})
        assert r["status"] == "success"
        assert r["data"]["action"] == "status"

    def test_none_input(self):
        r = WelcomeSeriesEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = WelcomeSeriesEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = WelcomeSeriesEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_unknown_action(self):
        r = WelcomeSeriesEngine().run({
            "data": {"action": "blast"},
        })
        assert r["status"] == "error"

    def test_non_string_action_does_not_crash(self):
        # Regression: BUG-7 — non-string action used to
        # AttributeError on .lower() in flow.py.
        for bad in (42, 3.14, [], {}, True):
            r = WelcomeSeriesEngine().run({
                "data": {"action": bad},
            })
            assert r["status"] in {"success", "error"}

    def test_carries_engine_name(self):
        r = WelcomeSeriesEngine().run({})
        assert r["meta"]["engine"] == "welcome_series"


class TestEngineActions:
    def test_preview_no_customers_shape(self):
        r = WelcomeSeriesEngine().run({
            "data": {"action": "preview", "limit": 3},
        })
        assert r["status"] == "success"
        assert "report" in r["data"]
        assert r["data"]["report"]["queued"] == 0

    def test_send_with_mocked_router(self, tmp_path):
        tracking.reset_path(tmp_path / "ws.json")
        c = _make_customer()
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True, data={"sent": True}, error="",
        )
        with patch(
            "engines.welcome_series.sender._hydrate_customers",
            return_value=[c],
        ), patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            r = WelcomeSeriesEngine().run({
                "data": {
                    "action": "send-batch", "limit": 1,
                },
            })
        assert r["status"] == "success"
        assert r["data"]["report"]["sent"] == 1
