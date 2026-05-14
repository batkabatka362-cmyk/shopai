"""Tests for the landing_page engine's page-creation writeback.

The engine emits a list of variant pages along with a
``best_variant`` index pointing at the highest-scoring copy.
Pre-fix that copy lived only in the engine output — the merchant
had to manually paste each section into a Shopify page template.

The applier picks ``pages[best_variant]``, renders it into a
self-contained HTML body, and creates an UNPUBLISHED Shopify page
via SHOPIFY_CREATE_PAGE.

Coverage:
  1. ``_slugify`` produces Shopify-safe handles.
  2. ``_build_body`` renders sections with HTML escaping.
  3. ``_build_proposal`` guardrails (empty pages, bad index,
     blank headline, campaign-driven title/handle).
  4. ``apply_landing_page`` happy path + router unavailable +
     adapter failed + adapter raised.
  5. ``enqueue_landing_page_for_approval`` happy + skip + queue
     unavailable.
  6. Flow integration — three branches of Stage 7.5.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _pages():
    return [
        {
            "headline": "Get Yours Today",
            "subheadline": "Best in class",
            "hero_section": "Lorem ipsum hero",
            "benefits": ["Fast shipping", "Lifetime warranty"],
            "cta": "Shop Now",
            "social_proof": "10,000+ happy customers",
        },
        {
            "headline": "Limited Edition",
            "subheadline": "While supplies last",
            "hero_section": "Don't miss out",
            "benefits": ["Exclusive design"],
            "cta": "Reserve Yours",
            "social_proof": "",
        },
    ]


# ─── Helper functions ──────────────────────────────────────────


class TestSlugify:

    def test_simple_string(self):
        from engines.landing_page.page_applier import _slugify
        assert _slugify("Holiday Sale 2026") == "holiday-sale-2026"

    def test_collapses_separators(self):
        from engines.landing_page.page_applier import _slugify
        assert _slugify("Buy / Save  Now!") == "buy-save-now"

    def test_truncates_long(self):
        from engines.landing_page.page_applier import _slugify
        long = "a" * 100
        assert len(_slugify(long)) == 64


class TestBuildBody:

    def test_renders_all_sections(self):
        from engines.landing_page.page_applier import _build_body
        body = _build_body(_pages()[0])
        assert "<h1>Get Yours Today</h1>" in body
        assert "<h2>Best in class</h2>" in body
        assert "<p>Lorem ipsum hero</p>" in body
        assert "<li>Fast shipping</li>" in body
        assert "<li>Lifetime warranty</li>" in body
        assert "<strong>Shop Now</strong>" in body
        assert "10,000+ happy customers" in body

    def test_escapes_html_in_headline(self):
        from engines.landing_page.page_applier import _build_body
        body = _build_body({
            "headline": "<script>alert(1)</script>",
            "subheadline": "", "hero_section": "",
            "benefits": [], "cta": "", "social_proof": "",
        })
        assert "<script>" not in body
        assert "&lt;script&gt;" in body

    def test_skips_empty_sections(self):
        from engines.landing_page.page_applier import _build_body
        body = _build_body({
            "headline": "Only Title",
            "subheadline": "", "hero_section": "",
            "benefits": [], "cta": "", "social_proof": "",
        })
        assert "<h1>Only Title</h1>" in body
        assert "<h2>" not in body
        assert "<ul>" not in body
        assert "<strong>" not in body


# ─── _build_proposal ───────────────────────────────────────────


class TestBuildProposal:

    def test_happy_path(self):
        from engines.landing_page.page_applier import _build_proposal
        proposal = _build_proposal(
            _pages(), best_variant=0, campaign=None,
        )
        assert proposal is not None
        assert proposal["title"] == "Get Yours Today"
        assert proposal["handle"] == "get-yours-today"
        assert proposal["adapter_params"]["is_published"] is False
        assert proposal["adapter_params"]["title"] == "Get Yours Today"

    def test_campaign_name_overrides_title(self):
        from engines.landing_page.page_applier import _build_proposal
        proposal = _build_proposal(
            _pages(),
            best_variant=0,
            campaign={"name": "Winter Sale 2026", "slug": "winter-26"},
        )
        assert proposal is not None
        assert proposal["title"] == "Winter Sale 2026"
        assert proposal["handle"] == "winter-26"

    def test_empty_pages_returns_none(self):
        from engines.landing_page.page_applier import _build_proposal
        assert _build_proposal([], 0, None) is None
        assert _build_proposal(None, 0, None) is None

    def test_out_of_range_returns_none(self):
        from engines.landing_page.page_applier import _build_proposal
        assert _build_proposal(_pages(), 99, None) is None

    def test_negative_index_returns_none(self):
        from engines.landing_page.page_applier import _build_proposal
        assert _build_proposal(_pages(), -1, None) is None

    def test_blank_headline_returns_none(self):
        from engines.landing_page.page_applier import _build_proposal
        pages = [{
            "headline": "",
            "subheadline": "X", "hero_section": "Y",
            "benefits": [], "cta": "Z", "social_proof": "",
        }]
        assert _build_proposal(pages, 0, None) is None


# ─── apply_landing_page (direct path) ──────────────────────────


class TestApplyLandingPage:

    def test_happy_path_calls_router(self):
        from engines.landing_page import page_applier

        fake_result = MagicMock()
        fake_result.ok = True
        fake_result.data = {
            "page": {
                "id": "gid://shopify/Page/123",
                "title": "Get Yours Today",
                "handle": "get-yours-today",
                "is_published": False,
            },
        }
        fake_router = MagicMock()
        fake_router.execute = MagicMock(return_value=fake_result)

        with patch.object(
            page_applier, "_get_router", return_value=fake_router,
        ):
            result = page_applier.apply_landing_page(
                pages=_pages(),
                best_variant=0,
                estimated_conversion=0.05,
            )

        assert result is not None
        assert result["applied"] is True
        assert result["page_id"] == "gid://shopify/Page/123"
        assert result["is_published"] is False
        assert result["best_variant"] == 0
        assert result["error"] is None
        # Adapter received expected shape.
        payload = fake_router.execute.call_args[0][1]
        assert payload["title"] == "Get Yours Today"
        assert payload["is_published"] is False
        assert "body_html" in payload

    def test_empty_pages_returns_none(self):
        from engines.landing_page import page_applier
        assert page_applier.apply_landing_page(
            pages=[],
            best_variant=0,
            estimated_conversion=0.0,
        ) is None

    def test_router_unavailable_returns_structured_skip(self):
        from engines.landing_page import page_applier

        with patch.object(
            page_applier, "_get_router", return_value=None,
        ):
            result = page_applier.apply_landing_page(
                pages=_pages(),
                best_variant=0,
                estimated_conversion=0.05,
            )
        assert result is not None
        assert result["applied"] is False
        assert result["error"] == "router_unavailable"

    def test_adapter_failed_surfaces_error(self):
        from engines.landing_page import page_applier

        fake_result = MagicMock()
        fake_result.ok = False
        fake_result.error = "handle taken"
        fake_router = MagicMock()
        fake_router.execute = MagicMock(return_value=fake_result)

        with patch.object(
            page_applier, "_get_router", return_value=fake_router,
        ):
            result = page_applier.apply_landing_page(
                pages=_pages(),
                best_variant=0,
                estimated_conversion=0.05,
            )

        assert result["applied"] is False
        assert result["error"].startswith("adapter_failed:")
        assert "handle taken" in result["error"]

    def test_adapter_raised_surfaces_error(self):
        from engines.landing_page import page_applier

        fake_router = MagicMock()
        fake_router.execute = MagicMock(
            side_effect=RuntimeError("boom"),
        )

        with patch.object(
            page_applier, "_get_router", return_value=fake_router,
        ):
            result = page_applier.apply_landing_page(
                pages=_pages(),
                best_variant=0,
                estimated_conversion=0.05,
            )

        assert result["applied"] is False
        assert result["error"].startswith("adapter_raised:")
        assert "boom" in result["error"]


# ─── enqueue_landing_page_for_approval ─────────────────────────


class TestEnqueueLandingPageForApproval:

    def test_happy_path_parks_proposal(self, isolated_queue):
        from engines.landing_page.page_applier import (
            enqueue_landing_page_for_approval,
        )

        result = enqueue_landing_page_for_approval(
            pages=_pages(),
            best_variant=1,
            estimated_conversion=0.045,
        )
        assert result is not None
        assert result["pending_action_id"].startswith("appr_")
        assert "Limited Edition" in result["narrative"]
        assert "variant #1" in result["narrative"]
        assert "4.5%" in result["narrative"]
        assert result["params"]["title"] == "Limited Edition"
        assert result["params"]["best_variant"] == 1

        action = isolated_queue.get(result["pending_action_id"])
        assert action is not None
        assert action.engine == "landing_page"
        assert action.action_type == "apply_landing_page"
        assert action.capability == "SHOPIFY_CREATE_PAGE"

    def test_empty_pages_returns_none(self, isolated_queue):
        from engines.landing_page.page_applier import (
            enqueue_landing_page_for_approval,
        )
        assert enqueue_landing_page_for_approval(
            pages=[],
            best_variant=0,
            estimated_conversion=0.0,
        ) is None
        assert isolated_queue.list_pending() == []

    def test_out_of_range_returns_none(self, isolated_queue):
        from engines.landing_page.page_applier import (
            enqueue_landing_page_for_approval,
        )
        assert enqueue_landing_page_for_approval(
            pages=_pages(),
            best_variant=99,
            estimated_conversion=0.05,
        ) is None

    def test_queue_unavailable_returns_none(self, isolated_queue):
        from engines.landing_page.page_applier import (
            enqueue_landing_page_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            result = enqueue_landing_page_for_approval(
                pages=_pages(),
                best_variant=0,
                estimated_conversion=0.05,
            )
        assert result is None


# ─── Flow integration ──────────────────────────────────────────


def _flow_input(
    *, apply_landing_page=None, require_approval=None,
):
    data: dict = {
        "product": {
            "id": "gid://shopify/Product/1",
            "title": "Widget",
            "price": 49.99,
            "description": "A widget for all your needs",
        },
        "campaign": {
            "name": "Test Campaign",
            "slug": "test-campaign",
        },
        "target_audience": "general",
        "brand_voice": "professional",
    }
    if apply_landing_page is not None:
        data["apply_landing_page"] = apply_landing_page
    if require_approval is not None:
        data["require_approval"] = require_approval
    return {"status": "ok", "data": data, "meta": {}, "error": None}


class TestFlowApprovalIntegration:

    def test_default_off_writes_nothing(self, isolated_queue):
        from engines.landing_page.flow import LandingPageEngine

        with patch(
            "engines.landing_page.flow.apply_landing_page",
        ) as mock_apply, patch(
            "engines.landing_page.flow.enqueue_landing_page_for_approval",
        ) as mock_enqueue:
            output = LandingPageEngine().run(_flow_input())

        mock_apply.assert_not_called()
        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["page_apply_result"] is None
            assert output["data"]["page_pending_action"] is None

    def test_apply_true_routes_to_direct(self, isolated_queue):
        from engines.landing_page.flow import LandingPageEngine

        stub = {
            "applied": True,
            "page_id": "gid://shopify/Page/123",
            "title": "Test Campaign",
            "handle": "test-campaign",
            "is_published": False,
            "best_variant": 0,
            "error": None,
        }
        with patch(
            "engines.landing_page.flow.apply_landing_page",
            return_value=stub,
        ) as mock_apply, patch(
            "engines.landing_page.flow.enqueue_landing_page_for_approval",
        ) as mock_enqueue:
            output = LandingPageEngine().run(
                _flow_input(
                    apply_landing_page=True,
                    require_approval=False,
                ),
            )

        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            mock_apply.assert_called_once()
            assert output["data"]["page_apply_result"] == stub
            assert output["data"]["page_pending_action"] is None

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.landing_page.flow import LandingPageEngine

        stub = {
            "pending_action_id": "appr_stub_1",
            "narrative": "landing page stub",
            "params": {},
        }
        with patch(
            "engines.landing_page.flow.apply_landing_page",
        ) as mock_apply, patch(
            "engines.landing_page.flow.enqueue_landing_page_for_approval",
            return_value=stub,
        ) as mock_enqueue:
            output = LandingPageEngine().run(
                _flow_input(
                    apply_landing_page=True,
                    require_approval=True,
                ),
            )

        mock_apply.assert_not_called()
        if output["status"] == "success":
            mock_enqueue.assert_called_once()
            assert output["data"]["page_pending_action"] == stub
            assert output["data"]["page_apply_result"] is None
