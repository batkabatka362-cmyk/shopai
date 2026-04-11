"""Catalog Engine — all TypedDicts and type aliases."""
from __future__ import annotations
from typing import Any, TypedDict

class CatalogInputData(TypedDict, total=False):
    products: list[dict[str, Any]]
    categories: list[dict[str, Any]]
    tags: list[str]

class CatalogData(TypedDict):
    catalog: dict[str, Any]
    tag_assignments: list[dict[str, Any]]
    validation: dict[str, Any]
    completeness_score: float

class CatalogMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float

class CatalogOutput(TypedDict):
    status: str
    data: CatalogData | None
    meta: CatalogMeta
    error: str | None
