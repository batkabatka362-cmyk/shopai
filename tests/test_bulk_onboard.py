"""Tests for engines.store_setup.bulk_onboard."""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from engines.store_setup.bulk_onboard import (
    BulkOnboardReport,
    BulkOnboardRow,
    _parse_csv,
    bulk_onboard,
)
from engines.store_setup.onboarding_wizard import (
    OnboardingResult,
    OnboardingStage,
)


@pytest.fixture
def tmp_csv(tmp_path):
    """Build a CSV file in a temp dir and return its path."""
    def _make(content: str) -> str:
        p = tmp_path / "stores.csv"
        p.write_text(content, encoding="utf-8")
        return str(p)
    return _make


class TestParseCsv:

    def test_missing_file_returns_error(self, tmp_path):
        rows, err = _parse_csv(str(tmp_path / "nope.csv"))
        assert rows == []
        assert "file not found" in err

    def test_missing_required_column_returns_error(
        self, tmp_csv,
    ):
        path = tmp_csv("name,niche\nfoo,bar\n")
        rows, err = _parse_csv(path)
        assert rows == []
        assert "missing required column" in err
        assert "store_id" in err

    def test_strips_whitespace_and_comments(self, tmp_csv):
        path = tmp_csv(
            "store_id,shop_url,api_key\n"
            "  s1  , s1.myshopify.com , token1 \n"
            "#  comment row,ignored,ignored\n"
            "\n"
            "s2,s2.myshopify.com,token2\n"
        )
        rows, err = _parse_csv(path)
        assert err == ""
        assert len(rows) == 2
        assert rows[0]["store_id"] == "s1"
        assert rows[0]["api_key"] == "token1"
        assert rows[1]["store_id"] == "s2"

    def test_ignores_unknown_columns(self, tmp_csv):
        path = tmp_csv(
            "store_id,shop_url,api_key,email,priority\n"
            "s1,s1.myshopify.com,t,ops@x.com,P0\n"
        )
        rows, err = _parse_csv(path)
        assert err == ""
        assert "email" not in rows[0]
        assert "priority" not in rows[0]
        assert rows[0]["store_id"] == "s1"


class TestBulkOnboardSkipReasons:
    """Rows with missing credentials should skip cleanly rather
    than fail the wizard."""

    def test_skip_when_no_credentials(self, tmp_csv):
        path = tmp_csv(
            "store_id,shop_url\n"
            "s1,s1.myshopify.com\n"
        )
        # Don't pass store_manager -- the row should skip before
        # the wizard is invoked.
        report = bulk_onboard(path)
        assert report.total_rows == 1
        row = report.rows[0]
        assert row.status == "skipped"
        assert "no credentials" in row.skip_reason

    def test_empty_csv_returns_error(self, tmp_csv):
        # Header only, no data rows
        path = tmp_csv("store_id,shop_url,api_key\n")
        report = bulk_onboard(path)
        assert report.error == "no usable rows in CSV"
        assert report.total_rows == 0


class TestBulkOnboardDryRun:
    """--dry-run threads through to every row."""

    def test_dry_run_all_rows_produce_preview(self, tmp_csv):
        path = tmp_csv(
            "store_id,shop_url,api_key\n"
            "s1,s1.myshopify.com,t1\n"
            "s2,s2.myshopify.com,t2\n"
            "s3,s3.myshopify.com,t3\n"
        )
        report = bulk_onboard(path, dry_run=True)
        assert report.total_rows == 3
        # Every row hits the wizard's dry-run path
        for row in report.rows:
            assert row.result is not None
            assert row.result.final_verdict == "dry_run"


class TestBulkOnboardAggregation:
    """Counts + report-level aggregates."""

    def test_status_counts_mix(self, tmp_csv):
        path = tmp_csv(
            "store_id,shop_url,api_key\n"
            "ok1,ok1.myshopify.com,t\n"
            "ok2,ok2.myshopify.com,t\n"
            "fail1,fail1.myshopify.com,t\n"
        )
        # Fake wizard: first 2 rows succeed, third fails
        def fake_onboard(store_id, **kw):
            if store_id == "fail1":
                return OnboardingResult(
                    store_id=store_id,
                    shop_url=kw.get("shop_url", ""),
                    final_verdict="failed",
                    next_action="x",
                    stages=[OnboardingStage(
                        name="validation", status="fail",
                        detail="boom",
                    )],
                )
            return OnboardingResult(
                store_id=store_id,
                shop_url=kw.get("shop_url", ""),
                final_verdict="ready",
                next_action="",
                stages=[OnboardingStage(
                    name="register", status="success",
                    detail="",
                )],
            )
        with patch(
            "engines.store_setup.bulk_onboard.onboard_store",
            side_effect=fake_onboard,
        ):
            report = bulk_onboard(path)
        assert report.ready_count == 2
        assert report.failed_count == 1
        counts = report.status_counts
        assert counts["ready"] == 2
        assert counts["failed"] == 1


class TestBulkOnboardMaxFailures:
    """--max-failures stops the chain after N fails."""

    def test_stops_after_max_failures_reached(self, tmp_csv):
        path = tmp_csv(
            "store_id,shop_url,api_key\n"
            "s1,s1.myshopify.com,t\n"
            "s2,s2.myshopify.com,t\n"
            "s3,s3.myshopify.com,t\n"
            "s4,s4.myshopify.com,t\n"
            "s5,s5.myshopify.com,t\n"
        )
        def all_fail(store_id, **kw):
            return OnboardingResult(
                store_id=store_id,
                shop_url=kw.get("shop_url", ""),
                final_verdict="failed",
                next_action="x",
                stages=[OnboardingStage(
                    name="register", status="fail",
                    detail="x",
                )],
            )
        with patch(
            "engines.store_setup.bulk_onboard.onboard_store",
            side_effect=all_fail,
        ):
            report = bulk_onboard(path, max_failures=2)
        assert report.stopped_early is True
        # Stopped at row 2 (second failure triggered the stop)
        assert report.total_rows == 2

    def test_max_failures_zero_processes_all_rows(
        self, tmp_csv,
    ):
        path = tmp_csv(
            "store_id,shop_url,api_key\n"
            "s1,s1.myshopify.com,t\n"
            "s2,s2.myshopify.com,t\n"
            "s3,s3.myshopify.com,t\n"
        )
        def all_fail(store_id, **kw):
            return OnboardingResult(
                store_id=store_id,
                shop_url=kw.get("shop_url", ""),
                final_verdict="failed",
                next_action="x",
            )
        with patch(
            "engines.store_setup.bulk_onboard.onboard_store",
            side_effect=all_fail,
        ):
            report = bulk_onboard(path, max_failures=0)
        assert report.stopped_early is False
        assert report.total_rows == 3


class TestBulkOnboardRobustness:
    """The wrapper must survive wizard exceptions."""

    def test_wizard_raises_row_marked_skipped(self, tmp_csv):
        path = tmp_csv(
            "store_id,shop_url,api_key\n"
            "boom,boom.myshopify.com,t\n"
        )
        with patch(
            "engines.store_setup.bulk_onboard.onboard_store",
            side_effect=RuntimeError("synthetic"),
        ):
            report = bulk_onboard(path)
        # Wrapper caught the exception + marked the row skipped
        assert report.total_rows == 1
        row = report.rows[0]
        assert row.status == "skipped"
        assert "synthetic" in row.skip_reason
