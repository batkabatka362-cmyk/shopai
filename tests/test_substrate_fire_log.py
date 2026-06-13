"""Tests for core.automation.substrate_fire_log (Wave 840)."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

from core.automation.substrate_fire_log import (
    SubstrateFireLogEntry,
    record_substrate_fire,
    recent_substrate_fires,
    substrate_fire_log_size,
)


@dataclass
class FakeOutcome:
    domain: str = ""
    store_id: str | None = None
    discovered: int = 0
    invoked: bool = False
    events: int = 0
    duration_ms: float = 0.0
    reason: str = ""
    error: str = ""


class TestRecord:
    """Pattern J: action_log skips writes under pytest, so we
    verify behaviour via the synthetic in-memory layer that
    bypasses _is_test_environment."""

    def test_log_size_starts_zero_or_more(self):
        # Just confirm no exception
        n = substrate_fire_log_size()
        assert isinstance(n, int)
        assert n >= 0

    def test_record_no_ops_under_pytest(self):
        before = substrate_fire_log_size()
        record_substrate_fire(FakeOutcome(
            domain="shipping_alert", reason="fired",
            invoked=True, discovered=5, events=5,
        ))
        # Pattern J: should NOT have grown the persistent log
        assert substrate_fire_log_size() == before

    def test_record_skips_no_actionable_outcome(self):
        # no_discoverer + 0 rows -> dropped at the recorder
        # boundary regardless of pytest guard
        before = substrate_fire_log_size()
        record_substrate_fire(FakeOutcome(
            domain="shipping_alert",
            reason="no_discoverer", discovered=0,
        ))
        # Either Pattern J or the recorder filter -> no growth
        assert substrate_fire_log_size() == before

    def test_record_drops_missing_domain(self):
        # Should not raise; just no-op
        record_substrate_fire(FakeOutcome())
        # No assertion beyond no-raise; record path bails early.


class TestRecentSubstrateFires:

    def test_empty_window_no_rows(self):
        rows = recent_substrate_fires(window_hours=0.0)
        # Tight window -> always empty
        assert rows == []

    def test_filter_by_store_returns_empty_in_dev(self):
        rows = recent_substrate_fires(
            window_hours=168.0,
            store_id="nonexistent-store",
        )
        assert rows == []

    def test_filter_by_domain_returns_empty_in_dev(self):
        rows = recent_substrate_fires(
            window_hours=168.0,
            domain="nonexistent_domain",
        )
        assert rows == []

    def test_disable_test_guard_persists(self):
        """When Pattern J is lifted, record_substrate_fire
        actually appends + recent_substrate_fires reads it."""
        with patch(
            "core.automation.action_log."
            "is_test_environment",
            return_value=False,
        ):
            # Use a tmp file so we don't pollute the real log
            with patch(
                "core.automation.substrate_fire_log."
                "_LOG_PATH",
                __import__("pathlib").Path(
                    __import__("tempfile").mkstemp(
                        suffix="_sf_test.json",
                    )[1],
                ),
            ):
                from core.automation import (
                    substrate_fire_log as _sfl,
                )
                # File at the patched path is empty/missing
                record_substrate_fire(FakeOutcome(
                    domain="shipping_alert",
                    store_id="store-1",
                    reason="fired",
                    invoked=True,
                    discovered=3,
                    events=3,
                    duration_ms=42.0,
                ))
                rows = _sfl.recent_substrate_fires(
                    window_hours=168.0,
                )
                assert len(rows) == 1
                assert rows[0]["domain"] == "shipping_alert"
                assert rows[0]["store_id"] == "store-1"


class TestEntryDataclass:

    def test_defaults(self):
        e = SubstrateFireLogEntry(domain="x")
        assert e.store_id == ""
        assert not e.invoked
        assert e.discovered == 0
        assert e.recorded_at > 0
