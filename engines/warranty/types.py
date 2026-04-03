"""Warranty Engine — all TypedDicts and type aliases."""
from __future__ import annotations
from typing import Any, TypedDict

class WarrantyInputData(TypedDict, total=False):
    products: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    policies: list[dict[str, Any]]

class WarrantyData(TypedDict):
    claims_processed: dict[str, Any]
    costs: dict[str, Any]
    risk_analysis: list[dict[str, Any]]
    policy_recommendations: list[str]

class WarrantyMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float

class WarrantyOutput(TypedDict):
    status: str
    data: WarrantyData | None
    meta: WarrantyMeta
    error: str | None
