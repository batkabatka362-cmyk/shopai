"""Order Quality Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the order quality engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class QualityInputData(TypedDict, total=False):
    orders: list[dict[str, Any]]
    defects: list[dict[str, Any]]
    suppliers: list[dict[str, Any]]


class DefectRate(TypedDict):
    entity: str
    entity_type: str
    total_orders: int
    defect_count: int
    defect_rate: float


class SupplierQualityScore(TypedDict):
    supplier_id: str
    supplier_name: str
    quality_score: float
    defect_rate: float
    severity_breakdown: dict[str, int]
    grade: str


class InspectionPlan(TypedDict):
    supplier_id: str
    supplier_name: str
    inspection_frequency: str
    priority: str
    focus_areas: list[str]


class ImprovementAction(TypedDict):
    supplier_id: str
    action: str
    priority: str
    expected_impact: str


class QualityData(TypedDict):
    defect_rates: list[DefectRate]
    supplier_quality_scores: list[SupplierQualityScore]
    inspection_plan: list[InspectionPlan]
    improvement_actions: list[ImprovementAction]


class QualityMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class QualityOutput(TypedDict):
    status: str
    data: QualityData | None
    meta: QualityMeta
    error: str | None
