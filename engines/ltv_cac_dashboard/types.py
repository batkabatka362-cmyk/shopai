"""LTV:CAC Dashboard Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the LTV:CAC dashboard engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class LtvCacInputData(TypedDict, total=False):
    customers: list[dict[str, Any]]
    orders: list[dict[str, Any]]
    marketing_spend: list[dict[str, Any]]
    channels: list[str]


class LtvResult(TypedDict):
    average: float
    by_segment: dict[str, float]


class CacResult(TypedDict):
    average: float
    by_channel: dict[str, float]


class LtvCacAlert(TypedDict):
    alert_type: str
    severity: str
    message: str
    channel: str


class LtvCacData(TypedDict):
    ltv: LtvResult
    cac: CacResult
    ratio: float
    trend: str
    alerts: list[LtvCacAlert]
    payback_months: float


class LtvCacMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class LtvCacOutput(TypedDict):
    status: str
    data: LtvCacData | None
    meta: LtvCacMeta
    error: str | None
