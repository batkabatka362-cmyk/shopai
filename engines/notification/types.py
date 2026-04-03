"""Notification Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the notification engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class CustomerInfo(TypedDict, total=False):
    """Customer receiving the notification."""
    id: str
    name: str
    email: str
    phone: str
    timezone: str
    preferred_channel: str
    opted_out_channels: list[str]


class NotificationPreferences(TypedDict, total=False):
    """Customer notification preferences."""
    quiet_hours_start: str
    quiet_hours_end: str
    frequency_cap_daily: int
    enabled_channels: list[str]


class NotificationInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    event_type: str
    customer: CustomerInfo
    data: dict[str, Any]
    preferences: NotificationPreferences


# ---------------------------------------------------------------------------
# Intermediate types — template
# ---------------------------------------------------------------------------

class TemplateResult(TypedDict):
    """Resolved template from template_manager."""
    template_id: str
    channel: str
    subject: str
    body_template: str
    variables: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — channel selection
# ---------------------------------------------------------------------------

class ChannelSelection(TypedDict):
    """Channel selection result from channel_selector."""
    selected_channel: str
    fallback_channel: str
    reason: str
    opt_out_checked: bool


# ---------------------------------------------------------------------------
# Intermediate types — personalization
# ---------------------------------------------------------------------------

class PersonalizedContent(TypedDict):
    """Personalized notification content from personalization_engine."""
    subject: str
    body: str
    personalized: bool
    variables_used: list[str]


# ---------------------------------------------------------------------------
# Intermediate types — delivery tracking
# ---------------------------------------------------------------------------

class DeliveryStatus(TypedDict):
    """Delivery tracking result from delivery_tracker."""
    notification_id: str
    channel: str
    status: str
    scheduled_at: str
    estimated_delivery: str


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class NotificationItem(TypedDict):
    """Single notification in engine output."""
    channel: str
    template: str
    content: str
    personalized: bool
    scheduled_at: str


class NotificationOutputData(TypedDict):
    """The 'data' block of the engine output."""
    notifications: list[NotificationItem]
    delivery_status: list[DeliveryStatus]
    opt_out_check: bool


class NotificationMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class NotificationOutput(TypedDict):
    """Final output of the notification engine."""
    status: str
    data: NotificationOutputData | None
    meta: NotificationMeta
    error: str | None
