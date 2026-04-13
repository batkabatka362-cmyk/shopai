"""Gift Card Engine — all TypedDicts and type aliases."""
from __future__ import annotations
from typing import Any, TypedDict

class GiftCardInputData(TypedDict, total=False):
    gift_cards: list[dict[str, Any]]
    redemptions: list[dict[str, Any]]
    program_config: dict[str, Any]

class GiftCardData(TypedDict):
    program_health: dict[str, Any]
    breakage_estimate: dict[str, Any]
    active_cards: list[dict[str, Any]]
    promotions: list[dict[str, Any]]

class GiftCardMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float

class GiftCardOutput(TypedDict):
    status: str
    data: GiftCardData | None
    meta: GiftCardMeta
    error: str | None
