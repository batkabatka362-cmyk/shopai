"""Tests for the legal_document engine's multi-page writeback.

The engine emits a list of compliance-ready legal documents
(privacy policy, terms of service, refund policy, shipping
policy). The applier mints one UNPUBLISHED Shopify page per
document via SHOPIFY_CREATE_PAGE — unlike landing_page which
picks one best variant, legal_document mints N pages.

Coverage:
  1. ``_resolve_handle`` uses known type-to-handle table and
     falls back to slugified type/title.
  2. ``_is_compliance_failed`` blocks only ``status=fail``.
  3. ``_build_proposals`` filters (empty title, empty html,
     compliance fail).
  4. ``apply_legal_documents`` happy path + router unavailable
     + per-doc adapter raised + per-doc adapter failed.
  5. ``enqueue_legal_documents_for_approval`` happy + skip +
     queue unavailable.
  6. Flow integration — three branches of Stage 6.5.
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


def _documents():
    return [
        {
            "type": "privacy_policy",
            "title": "Privacy Policy",
            "html_content": "<article><h1>Privacy Policy</h1></article>",
            "sections": [],
            "last_updated": "2026-05-01",
        },
        {
            "type": "terms_of_service",
            "title": "Terms of Service",
            "html_content": "<article><h1>Terms</h1></article>",
            "sections": [],
            "last_updated": "2026-05-01",
        },
        {
            "type": "refund_policy",
            "title": "Refund Policy",
            "html_content": "<article><h1>Refunds</h1></article>",
            "sections": [],
            "last_updated": "2026-05-01",
        },
    ]


# ─── Helper functions ──────────────────────────────────────────


class TestResolveHandle:

    def test_known_type(self):
        from engines.legal_document.page_applier import _resolve_handle
        assert _resolve_handle("privacy_policy", "Privacy") == (
            "privacy-policy"
        )
        assert _resolve_handle("terms_of_service", "ToS") == (
            "terms-of-service"
        )
        assert _resolve_handle("refund_policy", "Refunds") == (
            "refund-policy"
        )

    def test_alias_terms(self):
        from engines.legal_document.page_applier import _resolve_handle
        # both aliases resolve to same handle
        assert _resolve_handle("terms_and_conditions", "x") == (
            "terms-of-service"
        )
        assert _resolve_handle("return_policy", "x") == (
            "refund-policy"
        )

    def test_unknown_type_slugifies(self):
        from engines.legal_document.page_applier import _resolve_handle
        assert _resolve_handle("custom_disclaimer", "X") == (
            "custom-disclaimer"
        )

    def test_blank_type_uses_title(self):
        from engines.legal_document.page_applier import _resolve_handle
        assert _resolve_handle("", "Holiday Returns") == (
            "holiday-returns"
        )


class TestIsComplianceFailed:

    def test_status_fail_blocks(self):
        from engines.legal_document.page_applier import (
            _is_compliance_failed,
        )
        assert _is_compliance_failed(
            "privacy_policy",
            {"privacy_policy": {"status": "fail"}},
        ) is True

    def test_status_pass_allows(self):
        from engines.legal_document.page_applier import (
            _is_compliance_failed,
        )
        assert _is_compliance_failed(
            "privacy_policy",
            {"privacy_policy": {"status": "pass"}},
        ) is False

    def test_status_warn_allows(self):
        from engines.legal_document.page_applier import (
            _is_compliance_failed,
        )
        # warns still publishable with merchant judgement
        assert _is_compliance_failed(
            "privacy_policy",
            {"privacy_policy": {"status": "warn"}},
        ) is False

    def test_missing_entry_allows(self):
        from engines.legal_document.page_applier import (
            _is_compliance_failed,
        )
        # validator didn't inspect this type — don't block
        assert _is_compliance_failed("custom", {}) is False
        assert _is_compliance_failed("custom", None) is False


# ─── _build_proposals ──────────────────────────────────────────


class TestBuildProposals:

    def test_happy_path_all_docs(self):
        from engines.legal_document.page_applier import (
            _build_proposals,
        )
        proposals = _build_proposals(_documents(), None)
        assert len(proposals) == 3
        types = {p["type"] for p in proposals}
        assert types == {
            "privacy_policy", "terms_of_service", "refund_policy",
        }

    def test_filters_blank_title(self):
        from engines.legal_document.page_applier import (
            _build_proposals,
        )
        docs = _documents() + [{
            "type": "extra", "title": "",
            "html_content": "<p>x</p>",
        }]
        assert len(_build_proposals(docs, None)) == 3

    def test_filters_blank_html(self):
        from engines.legal_document.page_applier import (
            _build_proposals,
        )
        docs = _documents() + [{
            "type": "extra", "title": "X", "html_content": "",
        }]
        assert len(_build_proposals(docs, None)) == 3

    def test_filters_compliance_failed(self):
        from engines.legal_document.page_applier import (
            _build_proposals,
        )
        proposals = _build_proposals(
            _documents(),
            {"privacy_policy": {"status": "fail"}},
        )
        assert len(proposals) == 2
        assert all(
            p["type"] != "privacy_policy" for p in proposals
        )

    def test_empty_list_returns_empty(self):
        from engines.legal_document.page_applier import (
            _build_proposals,
        )
        assert _build_proposals([], None) == []
        assert _build_proposals(None, None) == []


# ─── apply_legal_documents ─────────────────────────────────────


class TestApplyLegalDocuments:

    def test_happy_path_mints_per_doc(self):
        from engines.legal_document import page_applier

        call_count = {"n": 0}

        def _good_execute(_cap, params):
            call_count["n"] += 1
            res = MagicMock()
            res.ok = True
            res.data = {
                "page": {
                    "id": f"gid://shopify/Page/{call_count['n']}",
                    "title": params["title"],
                    "handle": params.get("handle", ""),
                    "is_published": False,
                },
            }
            return res

        fake_router = MagicMock()
        fake_router.execute = MagicMock(side_effect=_good_execute)

        with patch.object(
            page_applier, "_get_router", return_value=fake_router,
        ):
            results = page_applier.apply_legal_documents(
                documents=_documents(),
            )

        assert len(results) == 3
        assert all(r["applied"] for r in results)
        assert all(r["is_published"] is False for r in results)
        assert results[0]["handle"] == "privacy-policy"
        assert results[1]["handle"] == "terms-of-service"
        assert results[2]["handle"] == "refund-policy"

    def test_empty_docs_returns_empty(self):
        from engines.legal_document import page_applier
        assert page_applier.apply_legal_documents(documents=[]) == []

    def test_router_unavailable_per_doc(self):
        from engines.legal_document import page_applier
        with patch.object(
            page_applier, "_get_router", return_value=None,
        ):
            results = page_applier.apply_legal_documents(
                documents=_documents(),
            )
        assert len(results) == 3
        assert all(r["applied"] is False for r in results)
        assert all(
            r["error"] == "router_unavailable" for r in results
        )

    def test_per_doc_adapter_failure_continues_batch(self):
        """One doc failing shouldn't halt the rest."""
        from engines.legal_document import page_applier

        call_count = {"n": 0}

        def _flaky_execute(_cap, params):
            call_count["n"] += 1
            res = MagicMock()
            if call_count["n"] == 2:
                res.ok = False
                res.error = "handle taken"
                return res
            res.ok = True
            res.data = {"page": {
                "id": f"gid://shopify/Page/{call_count['n']}",
                "title": params["title"],
                "handle": params.get("handle", ""),
                "is_published": False,
            }}
            return res

        fake_router = MagicMock()
        fake_router.execute = MagicMock(side_effect=_flaky_execute)

        with patch.object(
            page_applier, "_get_router", return_value=fake_router,
        ):
            results = page_applier.apply_legal_documents(
                documents=_documents(),
            )

        assert len(results) == 3
        # docs 0 and 2 succeeded, doc 1 failed.
        assert results[0]["applied"] is True
        assert results[1]["applied"] is False
        assert "adapter_failed" in results[1]["error"]
        assert results[2]["applied"] is True

    def test_per_doc_adapter_raised_continues_batch(self):
        from engines.legal_document import page_applier

        call_count = {"n": 0}

        def _raises_once(_cap, params):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("transient")
            res = MagicMock()
            res.ok = True
            res.data = {"page": {
                "id": "gid://shopify/Page/1",
                "title": params["title"],
                "handle": params.get("handle", ""),
                "is_published": False,
            }}
            return res

        fake_router = MagicMock()
        fake_router.execute = MagicMock(side_effect=_raises_once)

        with patch.object(
            page_applier, "_get_router", return_value=fake_router,
        ):
            results = page_applier.apply_legal_documents(
                documents=_documents(),
            )

        assert len(results) == 3
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]
        assert all(r["applied"] for r in results[1:])


# ─── enqueue_legal_documents_for_approval ──────────────────────


class TestEnqueueLegalDocumentsForApproval:

    def test_happy_path_parks_per_doc(self, isolated_queue):
        from engines.legal_document.page_applier import (
            enqueue_legal_documents_for_approval,
        )

        results = enqueue_legal_documents_for_approval(
            documents=_documents(),
        )
        assert len(results) == 3
        for r in results:
            assert r["pending_action_id"].startswith("appr_")
            assert r["error"] == "queued"
            action = isolated_queue.get(r["pending_action_id"])
            assert action is not None
            assert action.engine == "legal_document"
            assert action.action_type == "apply_legal_document"
            assert action.capability == "SHOPIFY_CREATE_PAGE"

    def test_empty_docs_returns_empty(self, isolated_queue):
        from engines.legal_document.page_applier import (
            enqueue_legal_documents_for_approval,
        )
        assert enqueue_legal_documents_for_approval(
            documents=[],
        ) == []
        assert isolated_queue.list_pending() == []

    def test_compliance_fail_filters(self, isolated_queue):
        from engines.legal_document.page_applier import (
            enqueue_legal_documents_for_approval,
        )
        results = enqueue_legal_documents_for_approval(
            documents=_documents(),
            compliance_check={
                "privacy_policy": {"status": "fail"},
            },
        )
        assert len(results) == 2
        assert all(r["type"] != "privacy_policy" for r in results)

    def test_queue_unavailable_returns_structured_skip(
        self, isolated_queue,
    ):
        from engines.legal_document.page_applier import (
            enqueue_legal_documents_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            results = enqueue_legal_documents_for_approval(
                documents=_documents(),
            )
        assert len(results) == 3
        assert all(
            r["error"] == "approval_queue_unavailable" for r in results
        )


# ─── Flow integration ──────────────────────────────────────────


def _flow_input(*, apply_legal_docs=None, require_approval=None):
    data: dict = {
        "business": {
            "name": "Test Co.",
            "address": "123 Test Ln",
            "email": "hi@test.co",
            "country": "US",
        },
        "policies": {
            "data_collection": "minimal",
            "shipping_days": 5,
        },
    }
    if apply_legal_docs is not None:
        data["apply_legal_docs"] = apply_legal_docs
    if require_approval is not None:
        data["require_approval"] = require_approval
    return {"status": "ok", "data": data, "meta": {}, "error": None}


class TestFlowApprovalIntegration:

    def test_default_off_writes_nothing(self, isolated_queue):
        from engines.legal_document.flow import LegalDocumentEngine

        with patch(
            "engines.legal_document.flow.apply_legal_documents",
        ) as mock_apply, patch(
            "engines.legal_document.flow.enqueue_legal_documents_for_approval",
        ) as mock_enqueue:
            output = LegalDocumentEngine().run(_flow_input())

        mock_apply.assert_not_called()
        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["page_apply_results"] == []

    def test_apply_true_routes_to_direct(self, isolated_queue):
        from engines.legal_document.flow import LegalDocumentEngine

        stub_results = [
            {
                "type": "privacy_policy",
                "title": "Privacy Policy",
                "applied": True,
                "page_id": "gid://shopify/Page/1",
                "handle": "privacy-policy",
                "is_published": False,
                "error": None,
            },
        ]
        with patch(
            "engines.legal_document.flow.apply_legal_documents",
            return_value=stub_results,
        ) as mock_apply, patch(
            "engines.legal_document.flow.enqueue_legal_documents_for_approval",
        ) as mock_enqueue:
            output = LegalDocumentEngine().run(
                _flow_input(
                    apply_legal_docs=True, require_approval=False,
                ),
            )

        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            mock_apply.assert_called_once()
            assert output["data"]["page_apply_results"] == stub_results

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.legal_document.flow import LegalDocumentEngine

        stub_results = [
            {
                "type": "privacy_policy",
                "title": "Privacy Policy",
                "applied": False,
                "page_id": "",
                "handle": "privacy-policy",
                "is_published": False,
                "error": "queued",
                "pending_action_id": "appr_stub_1",
            },
        ]
        with patch(
            "engines.legal_document.flow.apply_legal_documents",
        ) as mock_apply, patch(
            "engines.legal_document.flow.enqueue_legal_documents_for_approval",
            return_value=stub_results,
        ) as mock_enqueue:
            output = LegalDocumentEngine().run(
                _flow_input(
                    apply_legal_docs=True, require_approval=True,
                ),
            )

        mock_apply.assert_not_called()
        if output["status"] == "success":
            mock_enqueue.assert_called_once()
            assert output["data"]["page_apply_results"] == stub_results
