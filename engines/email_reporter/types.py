"""Email Reporter Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the email reporter engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


class EmailReporterInputData(TypedDict, total=False):
    report_type: str
    recipients: list[str]
    data: dict[str, Any]


class CompiledReport(TypedDict):
    title: str
    sections: list[dict[str, Any]]
    metrics_summary: dict[str, Any]
    period: str


class RenderedEmail(TypedDict):
    subject: str
    html_content: str
    text_content: str


class Schedule(TypedDict):
    frequency: str
    next_send: str
    timezone: str


class RecipientList(TypedDict):
    recipients: list[str]
    valid_count: int
    invalid_count: int


class EmailReporterData(TypedDict):
    report: RenderedEmail
    schedule: Schedule
    recipients: RecipientList
    delivery_status: str


class EmailReporterMeta(TypedDict):
    engine: str
    timestamp: str
    elapsed_seconds: float


class EmailReporterOutput(TypedDict):
    status: str
    data: EmailReporterData | None
    meta: EmailReporterMeta
    error: str | None
