"""Wishlist Engine — all TypedDicts and type aliases."""
from __future__ import annotations
from typing import Any, TypedDict

class WishlistInputData(TypedDict, total=False):
    wishlists: list[dict[str, Any]]
    products: list[dict[str, Any]]
    customers: list[dict[str, Any]]

class WishlistData(TypedDict):
    analysis: dict[str, Any]
    price_alerts: list[dict[str, Any]]
    conversion_recommendations: list[dict[str, Any]]
    social_proof_data: dict[str, Any]

class WishlistMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float

class WishlistOutput(TypedDict):
    status: str
    data: WishlistData | None
    meta: WishlistMeta
    error: str | None
