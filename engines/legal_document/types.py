"""Legal Document Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the legal document engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class BusinessInfo(TypedDict, total=False):
    """Business identity information."""
    name: str
    type: str
    country: str
    products_type: str


class PoliciesInput(TypedDict, total=False):
    """Policy configuration."""
    return_window_days: int
    shipping_policy: str


class LegalDocumentInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    business: BusinessInfo
    policies: PoliciesInput


# ---------------------------------------------------------------------------
# Intermediate types — template selection
# ---------------------------------------------------------------------------

class TemplateSelection(TypedDict):
    """Template selection result from template_selector."""
    template_id: str
    template_name: str
    jurisdiction: str
    business_type: str
    required_sections: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — content generation
# ---------------------------------------------------------------------------

class DocumentSection(TypedDict):
    """Single section within a legal document."""
    heading: str
    content: str
    is_required: bool


class GeneratedDocument(TypedDict):
    """Single generated legal document from content_generator."""
    type: str
    title: str
    content: str
    sections: list[DocumentSection]
    last_updated: str


# ---------------------------------------------------------------------------
# Intermediate types — compliance validation
# ---------------------------------------------------------------------------

class ComplianceCheck(TypedDict):
    """Compliance validation result from compliance_validator."""
    is_compliant: bool
    checks_passed: int
    checks_total: int
    issues: list[str]


class MissingSection(TypedDict):
    """A missing required section."""
    document_type: str
    section_name: str
    reason: str


# ---------------------------------------------------------------------------
# Intermediate types — formatting
# ---------------------------------------------------------------------------

class FormattedDocument(TypedDict):
    """Formatted document from formatter."""
    type: str
    title: str
    content: str
    sections: list[DocumentSection]
    last_updated: str
    html_content: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class LegalDocumentData(TypedDict):
    """The 'data' block of the engine output."""
    documents: list[FormattedDocument]
    compliance_check: ComplianceCheck
    missing_sections: list[MissingSection]


class LegalDocumentMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class LegalDocumentOutput(TypedDict):
    """Final output of the legal document engine."""
    status: str
    data: LegalDocumentData | None
    meta: LegalDocumentMeta
    error: str | None
