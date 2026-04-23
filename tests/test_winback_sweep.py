"""Tests for core/engines/budget_buyer/winback.py + the
autopilot cycle wire.

Verifies:
  * Sweep pulls dormant customers from LTV + enrols them into
    the email win_back flow.
  * ``max_per_cycle`` cap honoured when backlog exceeds it.
  * Customers already in win_back are skipped (tallied as
    already_enrolled, not re-enrolled).
  * Unsubscribed recipients silently skip.
  * Missing email in LTV row is ignored.
  * Autopilot CycleSummary surfaces winback_enrolled count.
  * Failure in sweep doesn't crash the cycle.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.engines.budget_buyer import (
    BudgetBuyerEngine, LTVTracker,
    reset_singleton_for_tests as _reset_bb,
)
from core.engines.budget_buyer.winback import (
    DEFAULT_MAX_PER_CYCLE, WinBackReport, sweep,
)
from core.engines.email_campaigns import (
    EmailCampaignEngine, ScheduleQueue,
    reset_singleton_for_tests as _reset_ec,
)


@pytest.fixture
def engines(tmp_path, monkeypatch):
    """Fresh BB + email engines sharing the same fixed clock
    so segmentation + scheduling are deterministic."""
    _reset_bb()
    _reset_ec()

    now_fn = lambda: 1_700_000_000.0

    tracker = LTVTracker(
        db_path=str(tmp_path / "ltv.db"), now_fn=now_fn,
    )
    bb = BudgetBuyerEngine(
        ltv_tracker=tracker, now_fn=now_fn,
    )

    eq = ScheduleQueue(
        db_path=str(tmp_path / "email.db"), now_fn=now_fn,
    )
    ec = EmailCampaignEngine(
        queue=eq, from_email="hello@deguar.com",
        now_fn=now_fn,
    )

    monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "deguar.myshopify.com")
    monkeypatch.setenv("SHOPAI_STORE_NAME", "Deguar")

    yield {"bb": bb, "ec": ec, "tracker": tracker, "queue": eq}
    _reset_bb()
    _reset_ec()


def _seed_dormant(
    tracker: LTVTracker, *, emails: list[str],
    days_ago: float = 500,
) -> None:
    """Plant LTV rows that classify as DORMANT."""
    now = 1_700_000_000.0
    old_ts = now - days_ago * 86400
    for email in emails:
        tracker.record_order(
            email=email, amount_usd=25, ts=old_ts,
        )


# ── sweep() ─────────────────────────────────────────────


class TestSweepBasic:
    def test_empty_dormant_reports_zero(self, engines):
        report = sweep(
            bb_engine=engines["bb"],
            email_engine=engines["ec"],
        )
        assert report.dormant_total == 0
        assert report.newly_enrolled == 0

    def test_single_dormant_enrolled(self, engines):
        _seed_dormant(
            engines["tracker"], emails=["ghost@x.com"],
        )
        report = sweep(
            bb_engine=engines["bb"],
            email_engine=engines["ec"],
        )
        assert report.dormant_total == 1
        assert report.newly_enrolled == 1
        # Flow is queued
        rows = engines["ec"].list_for_recipient("ghost@x.com")
        assert len(rows) == 1
        assert rows[0].flow_id == "win_back"

    def test_context_populated_from_env(self, engines):
        _seed_dormant(
            engines["tracker"], emails=["ghost@x.com"],
        )
        sweep(
            bb_engine=engines["bb"],
            email_engine=engines["ec"],
        )
        rows = engines["ec"].list_for_recipient("ghost@x.com")
        ctx = rows[0].context
        assert ctx["store_name"] == "Deguar"
        assert "deguar.myshopify.com" in ctx["store_url"]
        assert ctx["first_name"] == "Ghost"  # derived from email

    def test_first_name_derived_from_local_part(self, engines):
        _seed_dormant(
            engines["tracker"],
            emails=["jane.doe@example.com"],
        )
        sweep(
            bb_engine=engines["bb"],
            email_engine=engines["ec"],
        )
        rows = engines["ec"].list_for_recipient(
            "jane.doe@example.com",
        )
        # "jane.doe" → "Jane Doe" (dot replaced + title case)
        assert rows[0].context["first_name"] == "Jane Doe"


# ── Rate limit ───────────────────────────────────────────


class TestRateLimit:
    def test_cap_honoured(self, engines):
        # 10 dormant customers, cap=3
        emails = [f"ghost{i}@x.com" for i in range(10)]
        _seed_dormant(engines["tracker"], emails=emails)
        report = sweep(
            bb_engine=engines["bb"],
            email_engine=engines["ec"],
            max_per_cycle=3,
        )
        assert report.newly_enrolled == 3
        assert report.dormant_total == 10
        # 7 still waiting for next cycle
        enrolled = [
            e for e in emails
            if engines["ec"].list_for_recipient(e)
        ]
        assert len(enrolled) == 3

    def test_cap_zero_returns_early(self, engines):
        _seed_dormant(
            engines["tracker"],
            emails=[f"g{i}@x.com" for i in range(5)],
        )
        report = sweep(
            bb_engine=engines["bb"],
            email_engine=engines["ec"],
            max_per_cycle=0,
        )
        assert report.newly_enrolled == 0


# ── Already-enrolled skip ────────────────────────────────


class TestAlreadyEnrolled:
    def test_skips_customer_in_winback(self, engines):
        """Customer already queued for win_back from a prior
        sweep should not be re-enrolled — engine idempotency
        would dedupe steps, but the sweep short-circuits for
        cleaner reporting."""
        _seed_dormant(
            engines["tracker"], emails=["ghost@x.com"],
        )
        # First sweep enrolls
        sweep(
            bb_engine=engines["bb"],
            email_engine=engines["ec"],
        )
        # Second sweep: cap=5 but this one's already in
        report = sweep(
            bb_engine=engines["bb"],
            email_engine=engines["ec"],
            max_per_cycle=5,
        )
        assert report.newly_enrolled == 0
        assert report.already_enrolled == 1

    def test_other_flow_doesnt_block(self, engines):
        """Customer in the welcome flow but not win_back
        should still get win_back."""
        _seed_dormant(
            engines["tracker"], emails=["ghost@x.com"],
        )
        engines["ec"].enroll(
            "ghost@x.com", flow="welcome",
            context={
                "first_name": "Ghost", "store_name": "D",
                "store_url": "https://x",
                "discount_code": "W15",
                "top_products": "A",
            },
        )
        report = sweep(
            bb_engine=engines["bb"],
            email_engine=engines["ec"],
        )
        assert report.newly_enrolled == 1


# ── Unsubscribes + missing email ────────────────────────


class TestSkipPaths:
    def test_unsubscribed_tallied_as_already(self, engines):
        _seed_dormant(
            engines["tracker"], emails=["unsub@x.com"],
        )
        engines["ec"].unsubscribe("unsub@x.com", source="test")
        report = sweep(
            bb_engine=engines["bb"],
            email_engine=engines["ec"],
        )
        assert report.newly_enrolled == 0
        assert report.already_enrolled == 1

    def test_missing_email_skipped(self, engines):
        """A dormant LTV row without an email string — should
        silently skip without crashing."""
        # Plant a row with empty email
        from core.engines.budget_buyer.ltv import CustomerLTV
        engines["tracker"]._storage.upsert(CustomerLTV(
            customer_id="c1", email="",
            orders_count=1, total_spent_usd=20,
            first_order_at=1_700_000_000.0 - 500 * 86400,
            last_order_at=1_700_000_000.0 - 500 * 86400,
        ))
        report = sweep(
            bb_engine=engines["bb"],
            email_engine=engines["ec"],
        )
        # Counted as dormant but no enrollment
        assert report.dormant_total == 1
        assert report.newly_enrolled == 0


# ── Failure isolation ───────────────────────────────────


class TestFailureIsolation:
    def test_enroll_exception_per_customer(self, engines):
        """One enroll raising an exception shouldn't abort
        the rest of the batch."""
        _seed_dormant(
            engines["tracker"],
            emails=["a@x.com", "b@x.com", "c@x.com"],
        )
        orig = engines["ec"].enroll
        call_count = {"n": 0}

        def flaky(email, **kw):
            call_count["n"] += 1
            if email == "b@x.com":
                raise RuntimeError("intermittent")
            return orig(email, **kw)

        with patch.object(engines["ec"], "enroll", flaky):
            report = sweep(
                bb_engine=engines["bb"],
                email_engine=engines["ec"],
            )
        assert report.newly_enrolled == 2
        assert report.errors == 1

    def test_lookup_failure_returns_report(self, engines):
        def boom(*a, **kw):
            raise RuntimeError("db down")

        with patch.object(
            engines["bb"], "dormant_customers", boom,
        ):
            report = sweep(
                bb_engine=engines["bb"],
                email_engine=engines["ec"],
            )
        assert report.errors == 1
        assert report.newly_enrolled == 0


# ── WinBackReport shape ─────────────────────────────────


class TestReportShape:
    def test_as_dict(self):
        r = WinBackReport(
            dormant_total=10, already_enrolled=2,
            newly_enrolled=3, errors=0,
        )
        d = r.as_dict()
        assert d["dormant_total"] == 10
        assert d["newly_enrolled"] == 3
        assert d["errors_detail"] == []


# ── Autopilot cycle wire ────────────────────────────────


class TestAutopilotWire:
    def test_cycle_summary_carries_count(self):
        """Autopilot cycle summary should expose
        winback_enrolled after a cycle runs."""
        from scripts import autopilot_loop as al
        s = al.CycleSummary(
            cycle=1, ts=0, mode="live",
            launches=0, successful=0,
            distilled_proposals=0, accepted=0,
            duration_s=0.0,
            winback_enrolled=7,
        )
        assert s.as_dict()["winback_enrolled"] == 7
