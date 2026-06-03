"""Tests for engines.checkup — W963-21."""
from __future__ import annotations

from unittest.mock import patch

from engines.checkup import CheckupEngine
from engines.checkup.probe import (
    HealthRow,
    _safe_probe,
    collect_health,
    first_drill,
    overall_verdict,
    summarise,
)


# ── _safe_probe wrapper ────────────────────────────────────


class TestSafeProbe:
    def test_passes_through_success(self):
        def fn():
            return HealthRow(
                engine="x", verdict="ready",
            )
        row = _safe_probe("x", fn)
        assert row.verdict == "ready"

    def test_import_error_becomes_missing(self):
        def fn():
            raise ImportError("nope")
        row = _safe_probe("x", fn)
        assert row.verdict == "missing"
        assert "nope" in row.detail

    def test_other_exception_becomes_error(self):
        def fn():
            raise RuntimeError("boom")
        row = _safe_probe("x", fn)
        assert row.verdict == "error"
        assert "boom" in row.detail


# ── summarise ─────────────────────────────────────────────


class TestSummarise:
    def test_empty(self):
        assert summarise([]) == {
            "ready": 0, "partial": 0,
            "missing": 0, "error": 0,
        }

    def test_all_classes(self):
        rows = [
            HealthRow(engine="a", verdict="ready"),
            HealthRow(engine="b", verdict="ready"),
            HealthRow(engine="c", verdict="partial"),
            HealthRow(engine="d", verdict="missing"),
            HealthRow(engine="e", verdict="error"),
        ]
        counts = summarise(rows)
        assert counts == {
            "ready": 2, "partial": 1,
            "missing": 1, "error": 1,
        }


# ── overall_verdict ────────────────────────────────────────


class TestOverallVerdict:
    def test_empty(self):
        assert overall_verdict([]) == "missing"

    def test_error_dominates(self):
        rows = [
            HealthRow(engine="a", verdict="ready"),
            HealthRow(engine="b", verdict="error"),
        ]
        assert overall_verdict(rows) == "error"

    def test_missing_dominates_partial(self):
        rows = [
            HealthRow(engine="a", verdict="ready"),
            HealthRow(engine="b", verdict="partial"),
            HealthRow(engine="c", verdict="missing"),
        ]
        assert overall_verdict(rows) == "missing"

    def test_all_ready_returns_ready(self):
        rows = [
            HealthRow(engine=str(i), verdict="ready")
            for i in range(10)
        ]
        assert overall_verdict(rows) == "ready"

    def test_80pct_ready_threshold(self):
        # 8 ready, 2 partial -> 80% -> ready
        rows = (
            [HealthRow(engine=str(i), verdict="ready") for i in range(8)]
            + [
                HealthRow(engine="x", verdict="partial"),
                HealthRow(engine="y", verdict="partial"),
            ]
        )
        assert overall_verdict(rows) == "ready"

    def test_below_80pct_returns_partial(self):
        rows = (
            [HealthRow(engine=str(i), verdict="ready") for i in range(5)]
            + [
                HealthRow(engine="x", verdict="partial"),
                HealthRow(engine="y", verdict="partial"),
                HealthRow(engine="z", verdict="partial"),
                HealthRow(engine="w", verdict="partial"),
                HealthRow(engine="v", verdict="partial"),
            ]
        )
        assert overall_verdict(rows) == "partial"


# ── first_drill ────────────────────────────────────────────


class TestFirstDrill:
    def test_empty(self):
        assert first_drill([]) == ""

    def test_all_ready_returns_empty(self):
        rows = [
            HealthRow(
                engine="a", verdict="ready", drill="x",
            ),
        ]
        assert first_drill(rows) == ""

    def test_returns_first_non_ready_drill(self):
        rows = [
            HealthRow(
                engine="a", verdict="ready", drill="ready-drill",
            ),
            HealthRow(
                engine="b", verdict="partial",
                drill="partial-drill",
            ),
            HealthRow(
                engine="c", verdict="error",
                drill="error-drill",
            ),
        ]
        assert first_drill(rows) == "partial-drill"

    def test_skips_rows_without_drill(self):
        rows = [
            HealthRow(
                engine="a", verdict="partial", drill="",
            ),
            HealthRow(
                engine="b", verdict="error",
                drill="error-drill",
            ),
        ]
        assert first_drill(rows) == "error-drill"


# ── collect_health ─────────────────────────────────────────


class TestCollectHealth:
    def test_returns_18_rows(self):
        rows = collect_health()
        assert len(rows) == 18

    def test_all_rows_have_verdict(self):
        rows = collect_health()
        for r in rows:
            assert r.verdict in {
                "ready", "partial", "missing", "error",
            }

    def test_rows_carry_engine_name(self):
        rows = collect_health()
        names = {r.engine for r in rows}
        assert "revenue_readiness" in names
        assert "review_request" in names
        assert "today_brief" in names


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_input_success(self):
        result = CheckupEngine().run({})
        assert result["status"] == "success"
        assert result["data"]["engine_count"] == 18

    def test_none_input_success(self):
        result = CheckupEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_error(self):
        result = CheckupEngine().run("nope")
        assert result["status"] == "error"

    def test_fail_upstream(self):
        result = CheckupEngine().run({
            "status": "fail", "error": "broken",
        })
        assert result["status"] == "error"

    def test_carries_engine_name(self):
        result = CheckupEngine().run({})
        assert result["meta"]["engine"] == "checkup"

    def test_store_id_threaded(self):
        result = CheckupEngine().run({
            "data": {"store_id": "main"},
        })
        assert result["data"]["store_id"] == "main"

    def test_overall_verdict_valid(self):
        result = CheckupEngine().run({})
        assert result["data"]["verdict"] in {
            "ready", "partial", "missing", "error",
        }

    def test_counts_sum_to_engine_count(self):
        result = CheckupEngine().run({})
        data = result["data"]
        counts = data["counts"]
        total = sum(counts.values())
        assert total == data["engine_count"]
