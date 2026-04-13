"""Tag Management Engine — all TypedDicts and type aliases."""
from __future__ import annotations
from typing import Any, TypedDict

class TagManagementInputData(TypedDict, total=False):
    products: list[dict[str, Any]]
    existing_tags: list[str]
    taxonomy: dict[str, Any]

class TagManagementData(TypedDict):
    tags: list[dict[str, Any]]
    taxonomy_updates: dict[str, Any]
    optimization_suggestions: list[str]
    consistency_score: float

class TagManagementMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float

class TagManagementOutput(TypedDict):
    status: str
    data: TagManagementData | None
    meta: TagManagementMeta
    error: str | None
