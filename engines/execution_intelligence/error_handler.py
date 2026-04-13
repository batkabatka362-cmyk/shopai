"""Execution Intelligence — error handler.

Categorizes errors (transient, permanent, partial) and determines
the appropriate recovery strategy for each failure.

Model note: Would use Mistral for error classification and recovery reasoning.
"""
from __future__ import annotations

import copy
import re
from typing import Any


# ---------------------------------------------------------------------------
# Error pattern definitions
# ---------------------------------------------------------------------------

# Transient errors: typically resolve on retry
_TRANSIENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"timeout", re.IGNORECASE),
    re.compile(r"rate.?limit", re.IGNORECASE),
    re.compile(r"too many requests", re.IGNORECASE),
    re.compile(r"429", re.IGNORECASE),
    re.compile(r"503", re.IGNORECASE),
    re.compile(r"502", re.IGNORECASE),
    re.compile(r"connection.?(reset|refused|aborted)", re.IGNORECASE),
    re.compile(r"temporary", re.IGNORECASE),
    re.compile(r"service.?unavailable", re.IGNORECASE),
    re.compile(r"network.?error", re.IGNORECASE),
    re.compile(r"ECONNREFUSED", re.IGNORECASE),
    re.compile(r"ETIMEDOUT", re.IGNORECASE),
]

# Permanent errors: will not resolve on retry
_PERMANENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"401", re.IGNORECASE),
    re.compile(r"403", re.IGNORECASE),
    re.compile(r"404", re.IGNORECASE),
    re.compile(r"not.?found", re.IGNORECASE),
    re.compile(r"unauthorized", re.IGNORECASE),
    re.compile(r"forbidden", re.IGNORECASE),
    re.compile(r"invalid.?(api.?key|token|credential)", re.IGNORECASE),
    re.compile(r"permission.?denied", re.IGNORECASE),
    re.compile(r"unsupported", re.IGNORECASE),
    re.compile(r"malformed", re.IGNORECASE),
]

# Partial errors: some part of the action succeeded
_PARTIAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"partial", re.IGNORECASE),
    re.compile(r"incomplete", re.IGNORECASE),
    re.compile(r"some.?items.?failed", re.IGNORECASE),
    re.compile(r"partially.?(completed|processed)", re.IGNORECASE),
]

# Error category mapping by keyword
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "network": ["timeout", "connection", "network", "dns", "socket", "econnrefused", "etimedout"],
    "auth": ["unauthorized", "forbidden", "401", "403", "api_key", "token", "credential", "permission"],
    "validation": ["invalid", "malformed", "missing", "required", "type_error", "format"],
    "rate_limit": ["rate_limit", "rate limit", "too many requests", "429", "throttl"],
    "not_found": ["not_found", "not found", "404", "does not exist"],
    "server": ["500", "502", "503", "internal server", "service unavailable"],
}

# Severity by error type
_SEVERITY_MAP: dict[str, str] = {
    "transient": "medium",
    "permanent": "high",
    "partial": "low",
    "unknown": "medium",
}


def classify_error(
    task_id: str,
    error_message: str,
    action_type: str = "",
) -> dict[str, Any]:
    """Classify an error and determine recovery strategy.

    Args:
        task_id: ID of the failed task.
        error_message: The error message string.
        action_type: The action type that failed (for context-aware classification).

    Returns:
        Structured dict with error classification and recovery strategy.
    """
    try:
        safe_message = str(error_message) if error_message else "unknown error"

        error_type = _determine_error_type(safe_message)
        category = _determine_category(safe_message)
        severity = _determine_severity(error_type, category, action_type)
        recoverable = _is_recoverable(error_type, category)
        recovery_strategy = _determine_recovery_strategy(
            error_type, category, action_type,
        )

        return {
            "status": "success",
            "classification": {
                "task_id": task_id,
                "error_type": error_type,
                "error_message": safe_message,
                "recoverable": recoverable,
                "recovery_strategy": recovery_strategy,
                "severity": severity,
                "category": category,
            },
        }
    except Exception as exc:
        return {
            "status": "success",
            "classification": {
                "task_id": task_id,
                "error_type": "unknown",
                "error_message": str(error_message),
                "recoverable": False,
                "recovery_strategy": "skip",
                "severity": "medium",
                "category": "unknown",
            },
            "note": f"Classification fallback used: {exc}",
        }


def classify_errors_batch(
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify multiple errors at once.

    Args:
        failures: List of dicts with task_id, error_message, and optionally action_type.

    Returns:
        Structured dict with all classifications.
    """
    try:
        safe_failures = copy.deepcopy(failures)
        classifications: list[dict[str, Any]] = []

        for failure in safe_failures:
            task_id = failure.get("task_id", "unknown")
            error_message = failure.get("error_message", failure.get("error", ""))
            action_type = failure.get("action_type", "")

            result = classify_error(task_id, error_message, action_type)
            classifications.append(result["classification"])

        # Compute aggregate stats
        type_counts: dict[str, int] = {}
        strategy_counts: dict[str, int] = {}
        for cls in classifications:
            t = cls["error_type"]
            s = cls["recovery_strategy"]
            type_counts[t] = type_counts.get(t, 0) + 1
            strategy_counts[s] = strategy_counts.get(s, 0) + 1

        return {
            "status": "success",
            "classifications": classifications,
            "summary": {
                "total": len(classifications),
                "by_type": type_counts,
                "by_strategy": strategy_counts,
                "retryable_count": sum(1 for c in classifications if c["recoverable"]),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "classifications": [],
            "summary": {},
            "error": f"Batch classification failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal classification logic
# ---------------------------------------------------------------------------

def _determine_error_type(message: str) -> str:
    """Determine if error is transient, permanent, or partial.

    Model note: Mistral would analyze error semantics for ambiguous cases.
    """
    for pattern in _PARTIAL_PATTERNS:
        if pattern.search(message):
            return "partial"

    for pattern in _TRANSIENT_PATTERNS:
        if pattern.search(message):
            return "transient"

    for pattern in _PERMANENT_PATTERNS:
        if pattern.search(message):
            return "permanent"

    return "unknown"


def _determine_category(message: str) -> str:
    """Determine the error category (network, auth, validation, etc.)."""
    message_lower = message.lower()

    best_category = "unknown"
    best_score = 0

    for category, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in message_lower)
        if score > best_score:
            best_score = score
            best_category = category

    return best_category


def _determine_severity(
    error_type: str,
    category: str,
    action_type: str,
) -> str:
    """Determine error severity considering type, category, and action context."""
    base_severity = _SEVERITY_MAP.get(error_type, "medium")

    # Auth errors are always high severity
    if category == "auth":
        return "critical"

    # Rate limits on ads are medium (expected), elsewhere high
    if category == "rate_limit":
        return "medium"

    # Inventory failures are high severity (business-critical)
    if action_type == "update_inventory" and error_type != "partial":
        return "high"

    return base_severity


def _is_recoverable(error_type: str, category: str) -> bool:
    """Determine if the error can be recovered from."""
    if error_type == "transient":
        return True
    if error_type == "partial":
        return True
    if category == "rate_limit":
        return True
    if category == "network":
        return True
    # Auth and not_found are not recoverable
    if category in ("auth", "not_found"):
        return False
    if error_type == "permanent":
        return False
    # Unknown errors: cautiously allow one retry
    return True


def _determine_recovery_strategy(
    error_type: str,
    category: str,
    action_type: str,
) -> str:
    """Determine the recovery strategy.

    Model note: Mistral would select strategy based on full context.

    Returns one of: "retry", "skip", "fallback", "abort"
    """
    # Transient errors: retry
    if error_type == "transient":
        return "retry"

    # Rate limits: retry with backoff
    if category == "rate_limit":
        return "retry"

    # Network errors: retry
    if category == "network":
        return "retry"

    # Partial: retry the failed portion
    if error_type == "partial":
        return "retry"

    # Auth errors: abort (need credentials fix)
    if category == "auth":
        return "abort"

    # Not found: skip (resource doesn't exist)
    if category == "not_found":
        return "skip"

    # Validation errors: skip (data is wrong, retry won't fix it)
    if category == "validation":
        return "skip"

    # Permanent server errors: fallback
    if error_type == "permanent" and category == "server":
        return "fallback"

    # Permanent errors: skip
    if error_type == "permanent":
        return "skip"

    # Unknown: retry once, then skip
    return "retry"
