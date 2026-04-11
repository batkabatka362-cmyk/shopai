"""Product Validation Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the product validation engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class ValidationProduct(TypedDict, total=False):
    id: str
    title: str
    category: str
    supplier_id: str
    certifications: list[str]
    origin_country: str
    quality_grade: str
    defect_rate_pct: float
    recall_history: bool


class ValidationInputData(TypedDict, total=False):
    products: list[ValidationProduct]
    compliance_standards: list[str]


class ComplianceResult(TypedDict):
    id: str
    compliant: bool
    issues: list[str]
    severity: str


class SourcingResult(TypedDict):
    id: str
    valid: bool
    supplier_verified: bool
    issues: list[str]


class QualityResult(TypedDict):
    id: str
    quality_score: float
    grade: str
    concerns: list[str]


class RiskFlag(TypedDict):
    id: str
    risk_level: str
    flags: list[str]
    recommendation: str


class ValidationOutputData(TypedDict):
    validated_products: list[dict[str, Any]]
    compliance_issues: list[ComplianceResult]
    quality_summary: dict[str, Any]
    risk_flags: list[RiskFlag]


class ValidationMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class ValidationOutput(TypedDict):
    status: str
    data: ValidationOutputData | None
    meta: ValidationMeta
    error: str | None
