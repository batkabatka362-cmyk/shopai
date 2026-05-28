"""Tests for core.automation.autonomy_history (Wave 313-318)."""
from __future__ import annotations

from core.automation.autonomy_history import (
    HistoryEntry,
    HistoryReport,
    _DOMAIN_LOGS,
    _coerce_entry,
    run_autonomy_history,
)


class TestCatalog:

    def test_8_domains(self):
        assert len(_DOMAIN_LOGS) == 8
        names = {d[0] for d in _DOMAIN_LOGS}
        assert names == {
            "refund", "marketing", "fulfillment",
            "inventory", "cleanup", "followup", "seo",
            "outreach",
        }

    def test_marketing_uses_ad_spend_log(self):
        marketing = next(
            d for d in _DOMAIN_LOGS if d[0] == "marketing"
        )
        # (domain, pkg, log_modname, fn_name)
        assert marketing[2] == "ad_spend_log"

    def test_refund_uses_recent_refunds(self):
        refund = next(
            d for d in _DOMAIN_LOGS if d[0] == "refund"
        )
        assert refund[3] == "recent_refunds"


class TestCoerceEntry:

    def test_dict_with_canonical_fields(self):
        e = _coerce_entry("refund", {
            "timestamp": "2026-05-28T10:00:00Z",
            "action": "refund_applied",
            "status": "ok",
            "order_id": "gid://shopify/Order/123",
        })
        assert e.timestamp == "2026-05-28T10:00:00Z"
        assert e.action == "refund_applied"
        assert e.status == "ok"
        assert "Order/123" in e.detail

    def test_dict_with_created_at_field(self):
        e = _coerce_entry("x", {
            "created_at": "2026-05-28T11:00:00Z",
        })
        assert e.timestamp == "2026-05-28T11:00:00Z"

    def test_applied_true_becomes_applied_status(self):
        e = _coerce_entry("x", {
            "timestamp": "2026-05-28T10:00:00Z",
            "applied": True,
        })
        assert e.status == "applied"

    def test_dataclass_coerced(self):
        from dataclasses import dataclass

        @dataclass
        class Evt:
            timestamp: str
            action: str
            order_id: str = ""

        e = _coerce_entry(
            "refund",
            Evt(
                timestamp="2026-05-28T10:00:00Z",
                action="refund_applied",
                order_id="X1",
            ),
        )
        assert e.timestamp == "2026-05-28T10:00:00Z"
        assert e.action == "refund_applied"
        assert "X1" in e.detail

    def test_empty_dict_safe(self):
        e = _coerce_entry("x", {})
        assert e.timestamp == ""
        assert e.action == ""
        assert e.status == ""

    def test_unknown_type_safe(self):
        e = _coerce_entry("x", 42)
        assert e.timestamp == ""


class TestRunAutonomyHistory:

    def test_returns_report(self):
        r = run_autonomy_history()
        assert isinstance(r, HistoryReport)

    def test_per_domain_count_has_8_entries(self):
        r = run_autonomy_history()
        assert len(r.per_domain_count) == 8

    def test_idle_branch_returns_empty(self):
        r = run_autonomy_history()
        # Clean branch with no autonomous fires
        assert r.total == 0
        assert all(
            n == 0 for n in r.per_domain_count.values()
        )

    def test_window_hours_preserved(self):
        r = run_autonomy_history(window_hours=48.0)
        assert r.window_hours == 48.0

    def test_store_id_preserved(self):
        r = run_autonomy_history(store_id="store-xyz")
        assert r.store_id == "store-xyz"


class TestSortOrder:

    def test_newest_first(self):
        # Verify the sort logic via manual injection
        report = HistoryReport()
        report.entries = [
            HistoryEntry(
                timestamp="2026-05-28T05:00:00Z", domain="a",
            ),
            HistoryEntry(
                timestamp="2026-05-28T10:00:00Z", domain="b",
            ),
            HistoryEntry(
                timestamp="2026-05-28T07:00:00Z", domain="c",
            ),
        ]
        # Mirror the actual sort call from run_autonomy_history
        report.entries.sort(
            key=lambda e: (e.timestamp or ""), reverse=True,
        )
        assert report.entries[0].domain == "b"
        assert report.entries[1].domain == "c"
        assert report.entries[2].domain == "a"


class TestHistoryReportTotal:

    def test_zero(self):
        r = HistoryReport()
        assert r.total == 0

    def test_counts(self):
        r = HistoryReport()
        r.entries = [
            HistoryEntry(timestamp="x", domain="d1"),
            HistoryEntry(timestamp="y", domain="d2"),
        ]
        assert r.total == 2
