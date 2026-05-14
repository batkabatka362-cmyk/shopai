"""Legal Document Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Business/Policies → Template Selector → Content Generator →
  Compliance Validator → Formatter → Memory Writer → Output

Engine contract:
  Input:  {status, data: {business, policies}, meta, error}
  Output: {status, data: {documents, compliance_check, missing_sections}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .template_selector import select_templates
from .content_generator import generate_content
from .compliance_validator import validate_compliance
from .formatter import format_documents
from .page_applier import (
    apply_legal_documents,
    enqueue_legal_documents_for_approval,
)
from .memory_reader import read_past_documents
from .memory_writer import write_document_result


class LegalDocumentEngine:
    """Legal Document Engine — orchestrator only, no logic."""

    ENGINE_NAME = "legal_document"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full legal document pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            LegalDocumentOutput dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation (no mutation) ----
        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        business = data.get("business", {})
        policies = data.get("policies", {})

        if not isinstance(business, dict) or not business.get("name"):
            return self._fail("Business info with 'name' is required", 0.0)

        # ---- Stage 1: Read past documents (non-blocking) ----
        _past = read_past_documents(limit=5)

        # ---- Stage 2: Template Selector ----
        template_result = select_templates(
            business=business,
        )
        if template_result.get("status") == "error":
            return self._fail(
                f"Template selection failed: {template_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        templates = template_result.get("templates", [])

        # ---- Stage 3: Content Generator ----
        content_result = generate_content(
            templates=templates,
            business=business,
            policies=policies,
        )
        if content_result.get("status") == "error":
            return self._fail(
                f"Content generation failed: {content_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        documents = content_result.get("documents", [])

        # ---- Stage 4: Compliance Validator ----
        compliance_result = validate_compliance(
            documents=documents,
            templates=templates,
        )
        if compliance_result.get("status") == "error":
            return self._fail(
                f"Compliance validation failed: {compliance_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        compliance_check = compliance_result.get("compliance_check", {})
        missing_sections = compliance_result.get("missing_sections", [])

        # ---- Stage 5: Formatter ----
        format_result = format_documents(
            documents=documents,
            business=business,
        )
        if format_result.get("status") == "error":
            return self._fail(
                f"Formatting failed: {format_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        formatted_documents = format_result.get("documents", [])

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write_result = write_document_result(
            documents=formatted_documents,
            compliance_check=compliance_check,
            missing_sections=missing_sections,
        )

        # ---- Stage 6.5: Legal-page writeback (opt-in) ----
        # Default OFF — existing callers keep their pure-
        # recommendation contract. Two opt-in modes mirror the
        # established Phase 6/7 pattern:
        #
        #   data.apply_legal_docs=True + data.require_approval=False
        #     → SHOPIFY_CREATE_PAGE immediately per document
        #   data.apply_legal_docs=True + data.require_approval=True
        #     → enqueue per-document to core.approval; merchant
        #       approves before each mutation lands
        #
        # Pages land as UNPUBLISHED — legal copy goes LIVE the
        # moment it's published and a typo in a privacy policy
        # is a compliance risk. Staged gives the merchant a
        # review pass before exposure.
        page_apply_results: list[dict[str, Any]] = []
        if data.get("apply_legal_docs") is True:
            if data.get("require_approval") is True:
                page_apply_results = enqueue_legal_documents_for_approval(
                    documents=formatted_documents,
                    compliance_check=compliance_check,
                )
            else:
                page_apply_results = apply_legal_documents(
                    documents=formatted_documents,
                    compliance_check=compliance_check,
                )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "documents": formatted_documents,
                "compliance_check": compliance_check,
                "missing_sections": missing_sections,
                # Stage 6.5 output. Empty list when default-
                # off; one entry per legal-doc otherwise
                # (carries pending_action_id when the approval-
                # queue branch fired).
                "page_apply_results": page_apply_results,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Error output
    # -------------------------------------------------------------------

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
