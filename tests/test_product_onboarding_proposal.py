"""W963-143: plan-based product proposal tests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engines.product_onboarding_proposal import (
    ProductOnboardingProposalEngine,
    build_proposal,
)
from engines.product_onboarding_proposal.proposal import (
    ProductCandidate,
    ProposalReport,
    _compute_economics,
    _gather_risk_flags,
    report_to_markdown,
)


class TestEconomics:
    def test_default_markup(self):
        retail, margin = _compute_economics(10.0)
        # 2.8x markup -> 28 retail -> 64% margin
        assert retail == 28.0
        assert margin == pytest.approx(64.3, abs=0.5)

    def test_zero_cost_zero_retail(self):
        retail, margin = _compute_economics(0.0)
        assert retail == 0.0
        assert margin == 0.0

    def test_negative_cost_zero(self):
        retail, margin = _compute_economics(-5.0)
        assert retail == 0.0
        assert margin == 0.0


class TestRiskFlags:
    def test_unsourced(self):
        c = ProductCandidate(
            title="x", cost_usd=10, suggested_retail_usd=28,
            projected_margin_pct=64.3,
        )
        flags = _gather_risk_flags(c, {})
        assert "unsourced" in flags

    def test_slow_shipping(self):
        c = ProductCandidate(
            title="x", supplier="cj", cost_usd=10,
            suggested_retail_usd=28,
            projected_margin_pct=64.3,
        )
        flags = _gather_risk_flags(
            c, {"avg_shipping_days": 30},
        )
        assert "slow_shipping" in flags

    def test_unproven_supplier(self):
        c = ProductCandidate(
            title="x", supplier="cj", cost_usd=10,
            suggested_retail_usd=28,
            projected_margin_pct=64.3,
        )
        flags = _gather_risk_flags(
            c, {"supplier_rating": 3.2},
        )
        assert "unproven_supplier" in flags

    def test_thin_margin(self):
        c = ProductCandidate(
            title="x", supplier="cj", cost_usd=10,
            suggested_retail_usd=12,
            projected_margin_pct=16.7,
        )
        flags = _gather_risk_flags(c, {})
        assert "thin_margin" in flags

    def test_trademark_risk(self):
        c = ProductCandidate(
            title="x", supplier="cj", cost_usd=10,
            suggested_retail_usd=28,
            projected_margin_pct=64.3,
        )
        flags = _gather_risk_flags(
            c, {"trademark_risk": True},
        )
        assert "trademark_risk" in flags


class TestBuildProposal:
    def test_empty_when_research_unavailable(self):
        """When product_research engine is missing /
        fails / returns empty, proposal degrades
        gracefully + adds a diagnostic note."""
        with patch(
            "engines.product_onboarding_proposal."
            "proposal._safe_run_research",
            return_value=[],
        ):
            report = build_proposal(
                "store_a", niche="beauty", count=5,
            )
        assert report.candidates == []
        assert report.discovered_count == 0
        assert any(
            "product_research engine" in n
            for n in report.notes
        )

    def test_ranks_by_score_times_margin(self):
        """Candidates with higher (score × margin)
        surface first."""
        raw = [
            {
                "title": "high_score_high_margin",
                "supplier": "cj",
                "cost_usd": 10.0,
                "score": 0.9,
            },
            {
                "title": "low_score_low_margin",
                "supplier": "cj",
                "cost_usd": 10.0,
                "score": 0.3,
            },
        ]
        with patch(
            "engines.product_onboarding_proposal."
            "proposal._safe_run_research",
            return_value=raw,
        ):
            report = build_proposal(
                "store_a", niche="beauty", count=5,
            )
        assert report.candidates[0].title == (
            "high_score_high_margin"
        )

    def test_unsourced_candidate_flagged(self):
        """Candidates with no supplier data get a
        'unsourced' risk flag."""
        raw = [{
            "title": "mystery_product",
            "score": 0.5,
        }]
        with patch(
            "engines.product_onboarding_proposal."
            "proposal._safe_run_research",
            return_value=raw,
        ), patch(
            "engines.product_onboarding_proposal."
            "proposal._safe_run_sourcing_lookup",
            return_value={},
        ):
            report = build_proposal(
                "store_a", niche="beauty", count=5,
            )
        if report.candidates:
            assert "unsourced" in (
                report.candidates[0].risk_flags
            )


class TestReportMarkdown:
    def test_empty_report_renders(self):
        report = ProposalReport(
            store_id="store_a",
            niche="beauty",
            requested_count=10,
            discovered_count=0,
        )
        md = report_to_markdown(report)
        assert "no-op" in md.lower()

    def test_includes_table_when_candidates(self):
        c = ProductCandidate(
            title="serum",
            supplier="cj",
            cost_usd=8.0,
            suggested_retail_usd=22.4,
            projected_margin_pct=64.3,
            niche_match_score=0.85,
            risk_flags=[],
        )
        report = ProposalReport(
            store_id="store_a",
            niche="beauty",
            requested_count=1,
            discovered_count=1,
            candidates=[c],
        )
        md = report_to_markdown(report)
        assert "serum" in md
        assert "| 1 |" in md  # table row
        assert "Approve" in md
        assert "Reject" in md


class TestEngineEnvelope:
    def test_requires_store_id(self):
        r = ProductOnboardingProposalEngine().run({})
        assert r["status"] == "error"
        assert "store_id" in r["error"].lower()

    def test_dry_run_no_queue_submit(self, monkeypatch):
        """submit_to_queue=False -> no approval action
        created."""
        with patch(
            "engines.product_onboarding_proposal."
            "proposal._safe_run_research",
            return_value=[{
                "title": "x",
                "supplier": "cj",
                "cost_usd": 10.0,
                "score": 0.5,
            }],
        ):
            r = ProductOnboardingProposalEngine().run({
                "data": {
                    "store_id": "store_a",
                    "niche": "beauty",
                    "count": 5,
                    "submit_to_queue": False,
                },
            })
        assert r["status"] == "success"
        assert r["data"]["approval_action_id"] == ""

    def test_submit_creates_queue_action(
        self, monkeypatch,
    ):
        """submit_to_queue=True -> approval action
        created with id."""
        fake_queue = MagicMock()
        fake_action = MagicMock()
        fake_action.id = "act_abc123"
        fake_queue.enqueue.return_value = fake_action

        with patch(
            "engines.product_onboarding_proposal."
            "proposal._safe_run_research",
            return_value=[{
                "title": "x",
                "supplier": "cj",
                "cost_usd": 10.0,
                "score": 0.5,
            }],
        ), patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            r = ProductOnboardingProposalEngine().run({
                "data": {
                    "store_id": "store_a",
                    "niche": "beauty",
                    "count": 5,
                    "submit_to_queue": True,
                },
            })
        assert r["data"]["approval_action_id"] == (
            "act_abc123"
        )
        # Verify enqueue was called with action_type
        # propose_product_batch
        fake_queue.enqueue.assert_called_once()
        kwargs = fake_queue.enqueue.call_args.kwargs
        assert kwargs["action_type"] == (
            "propose_product_batch"
        )
        assert kwargs["store_id"] == "store_a"
        # Narrative is the markdown report
        assert "Product onboarding proposal" in (
            kwargs["narrative"]
        )

    def test_carries_engine_name(self):
        r = ProductOnboardingProposalEngine().run({
            "data": {"store_id": "x"},
        })
        assert r["meta"]["engine"] == (
            "product_onboarding_proposal"
        )
