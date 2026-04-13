"""Input validation for API boundaries.

Provides lightweight validators for request parameters that
enter the system through HTTP endpoints. No external deps —
uses stdlib only (matching the server pattern).

Each validator returns ``(cleaned_value, error_message)``.
If ``error_message`` is not None, the input is invalid.
"""
from __future__ import annotations

import re
from typing import Any

# ── Constants ───────────────────────────────────────���────
MAX_STORE_ID_LEN = 64
MAX_STRING_FIELD_LEN = 256
MAX_URL_LEN = 512
MAX_BATCH_ITEMS = 500
MAX_BODY_FIELDS = 50

# Shopify store IDs: alphanumeric, hyphens, underscores
_STORE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-_]{0,63}$")

# Shopify shop domains: xxx.myshopify.com or custom domains
_SHOP_DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9\-]*\.myshopify\.com$"
    r"|^[a-zA-Z0-9][a-zA-Z0-9\-]*(\.[a-zA-Z0-9\-]+)+$"
)

# Engine / agent / workflow names: alphanumeric + underscores
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")

# Webhook topics: namespace/event format
_WEBHOOK_TOPIC_RE = re.compile(r"^[a-z_]+/[a-z_]+$")


def validate_store_id(value: Any) -> tuple[str, str | None]:
    """Validate and clean a store ID."""
    if not isinstance(value, str):
        return "", "store_id must be a string"
    value = value.strip()
    if not value:
        return "", "store_id is required"
    if len(value) > MAX_STORE_ID_LEN:
        return "", f"store_id exceeds {MAX_STORE_ID_LEN} characters"
    if not _STORE_ID_RE.match(value):
        return "", "store_id must be alphanumeric (hyphens/underscores allowed)"
    return value, None


def validate_safe_name(value: Any, field: str = "name") -> tuple[str, str | None]:
    """Validate an engine/agent/workflow/chain name."""
    if not isinstance(value, str):
        return "", f"{field} must be a string"
    value = value.strip()
    if not value:
        return "", f"{field} is required"
    if not _SAFE_NAME_RE.match(value):
        return "", f"{field} must be alphanumeric with underscores (max 64 chars)"
    return value, None


def validate_shop_url(value: Any) -> tuple[str, str | None]:
    """Validate a Shopify shop URL/domain."""
    if not isinstance(value, str):
        return "", "shop URL must be a string"
    value = value.strip().lower()
    if not value:
        return "", "shop URL is required"
    if len(value) > MAX_URL_LEN:
        return "", f"shop URL exceeds {MAX_URL_LEN} characters"
    if not _SHOP_DOMAIN_RE.match(value):
        return "", "shop URL must be a valid domain (e.g. store.myshopify.com)"
    return value, None


def validate_webhook_topic(value: Any) -> tuple[str, str | None]:
    """Validate a Shopify webhook topic."""
    if not isinstance(value, str):
        return "", "webhook topic must be a string"
    value = value.strip().lower()
    if not value:
        return "", "webhook topic is required"
    if not _WEBHOOK_TOPIC_RE.match(value):
        return "", "webhook topic must be in format 'resource/event'"
    return value, None


def validate_string(value: Any, field: str = "value",
                    required: bool = True,
                    max_len: int = MAX_STRING_FIELD_LEN) -> tuple[str, str | None]:
    """Validate a general string field."""
    if not isinstance(value, str):
        if required:
            return "", f"{field} must be a string"
        return "", None
    value = value.strip()
    if required and not value:
        return "", f"{field} is required"
    if len(value) > max_len:
        return "", f"{field} exceeds {max_len} characters"
    return value, None


def validate_batch_items(items: Any) -> tuple[list, str | None]:
    """Validate a batch items list."""
    if not isinstance(items, list):
        return [], "items must be a list"
    if not items:
        return [], "items list is empty"
    if len(items) > MAX_BATCH_ITEMS:
        return [], f"items list exceeds maximum of {MAX_BATCH_ITEMS}"
    return items, None


def validate_params(params: Any) -> tuple[dict, str | None]:
    """Validate a params dict (basic shape check)."""
    if params is None:
        return {}, None
    if not isinstance(params, dict):
        return {}, "params must be a dict"
    if len(params) > MAX_BODY_FIELDS:
        return {}, f"params has too many fields (max {MAX_BODY_FIELDS})"
    return params, None
