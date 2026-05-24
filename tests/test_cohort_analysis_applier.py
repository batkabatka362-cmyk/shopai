"""Tests for engines.cohort_analysis.tag_applier + flow."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.cohort_analysis.tag_applier import apply_cohort_tags


def _cohort(period="2026-05", customer_ids=None):
    return {
        "period": period,
        "customer_ids": list(customer_ids or []),
        "size": len(customer_ids or []),
    }


def _ok_router():
    router = MagicMock()
    router.execute.return_value = SimpleNamespace(
        ok=True, data={"id": "c1", "tags": []},
        error=None,
    )
    return router


class TestBasic:

    def test_tags_each_customer_per_cohort(self):
        router = _ok_router()
        with patch(
            "engines.cohort_analysis.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.cohort_analysis.tag_applier.record_writeback",
        ):
            results = apply_cohort_tags([
                _cohort("2026-05", ["c1", "c2"]),
                _cohort("2026-04", ["c3"]),
            ])
        assert len(results) == 3
        assert all(r["applied"] for r in results)
        assert {r["cohort"] for r in results} == {"2026-05", "2026-04"}

    def test_tag_format_is_cohort_colon_period(self):
        router = _ok_router()
        with patch(
            "engines.cohort_analysis.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.cohort_analysis.tag_applier.record_writeback",
        ):
            apply_cohort_tags([_cohort("2026-05", ["c1"])])
        params = router.execute.call_args.args[1]
        assert params["tags"] == ["cohort:2026-05"]
        assert params["id"] == "c1"

    def test_empty_returns_empty(self):
        assert apply_cohort_tags([]) == []

    def test_blank_period_skipped(self):
        router = _ok_router()
        with patch(
            "engines.cohort_analysis.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.cohort_analysis.tag_applier.record_writeback",
        ):
            results = apply_cohort_tags([
                _cohort("", ["c1"]),
                _cohort("2026-05", ["c2"]),
            ])
        assert len(results) == 1
        assert results[0]["customer_id"] == "c2"

    def test_blank_customer_id_skipped(self):
        router = _ok_router()
        with patch(
            "engines.cohort_analysis.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.cohort_analysis.tag_applier.record_writeback",
        ):
            results = apply_cohort_tags([
                _cohort("2026-05", ["", "c1"]),
            ])
        assert len(results) == 1
        assert results[0]["customer_id"] == "c1"


class TestPatternZ:

    def test_success_records(self):
        with patch(
            "engines.cohort_analysis.tag_applier._get_router",
            return_value=_ok_router(),
        ), patch(
            "engines.cohort_analysis.tag_applier.record_writeback",
        ) as record_mock:
            apply_cohort_tags([_cohort("2026-05", ["c1"])])
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["engine"] == "cohort_analysis"
        assert kw["action_type"] == "apply_cohort_tags"
        assert kw["capability"] == "SHOPIFY_TAG_CUSTOMER"
        assert kw["success"] is True

    def test_failure_records(self):
        router = MagicMock()
        router.execute.return_value = SimpleNamespace(
            ok=False, data=None, error="adapter_says_no",
        )
        with patch(
            "engines.cohort_analysis.tag_applier._get_router",
            return_value=router,
        ), patch(
            "engines.cohort_analysis.tag_applier.record_writeback",
        ) as record_mock:
            results = apply_cohort_tags([_cohort("2026-05", ["c1"])])
        record_mock.assert_called_once()
        kw = record_mock.call_args.kwargs
        assert kw["success"] is False
        assert "adapter_failed" in kw["error"]
        assert results[0]["applied"] is False


class TestRouterUnavailable:

    def test_router_none_returns_skipped_results(self):
        with patch(
            "engines.cohort_analysis.tag_applier._get_router",
            return_value=None,
        ):
            results = apply_cohort_tags([
                _cohort("2026-05", ["c1", "c2"]),
            ])
        assert len(results) == 2
        assert all(r["applied"] is False for r in results)
        assert all(r["error"] == "router_unavailable" for r in results)


class TestFlowOptIn:

    def _seed(self, *, apply_tags=False):
        return {
            "status": "success",
            "data": {
                "customers": [
                    {"id": "c1", "created_at": "2026-05-10T00:00:00Z"},
                    {"id": "c2", "created_at": "2026-05-20T00:00:00Z"},
                ],
                "orders": [
                    {
                        "customer_id": "c1",
                        "created_at": "2026-05-15T00:00:00Z",
                        "total_price": 50,
                    },
                ],
                "cohort_type": "monthly",
                "apply_cohort_tags": apply_tags,
            },
            "meta": {}, "error": None,
        }

    def test_no_flag_no_apply(self):
        from engines.cohort_analysis.flow import CohortAnalysisEngine
        with patch(
            "engines.cohort_analysis.tag_applier.apply_cohort_tags",
        ) as apply_mock:
            result = CohortAnalysisEngine().run(self._seed(apply_tags=False))
        apply_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["tagged_cohorts"] == []

    def test_opt_in_invokes_applier(self):
        from engines.cohort_analysis.flow import CohortAnalysisEngine
        with patch(
            "engines.cohort_analysis.tag_applier.apply_cohort_tags",
            return_value=[
                {
                    "customer_id": "c1", "cohort": "2026-05",
                    "applied": True, "error": None,
                },
            ],
        ) as apply_mock:
            result = CohortAnalysisEngine().run(self._seed(apply_tags=True))
        apply_mock.assert_called_once()
        assert result["data"]["tagged_cohorts"]

    def test_apply_raise_doesnt_break_envelope(self):
        from engines.cohort_analysis.flow import CohortAnalysisEngine
        with patch(
            "engines.cohort_analysis.tag_applier.apply_cohort_tags",
            side_effect=RuntimeError("boom"),
        ):
            result = CohortAnalysisEngine().run(self._seed(apply_tags=True))
        assert result["status"] == "success"
        assert result["data"]["tagged_cohorts"] == []
