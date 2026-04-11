"""Supplier scorer rules — hard constraints on supplier selection and ordering.

Hard rules that override scoring:
  - Minimum reliability threshold (70% on-time delivery)
  - No suppliers with active scam flags
  - Sample required before bulk order
  - Backup supplier required for any critical product
  - Payment protection required for first orders
"""
from __future__ import annotations

import time
from typing import Any

from .data import RED_FLAG_INDICATORS


# Absolute minimums
MIN_RELIABILITY_PCT = 70
MIN_QUALITY_SCORE = 40
MAX_RED_FLAGS = 1
MIN_ACCOUNT_AGE_YEARS = 0.5
SAMPLE_REQUIRED_BEFORE_BULK = True
BACKUP_SUPPLIER_REQUIRED = True
PAYMENT_PROTECTION_REQUIRED = True

RULES = [
    {
        "id": "min_reliability",
        "name": "Minimum reliability threshold",
        "description": "Supplier must have 70%+ on-time delivery rate",
        "severity": "blocker",
        "check": lambda ctx: ctx.get("reliability_score", 0) >= MIN_RELIABILITY_PCT,
        "action": "Supplier rejected — on-time delivery below 70% is unacceptable risk",
    },
    {
        "id": "no_scam_flags",
        "name": "No active scam indicators",
        "description": "Supplier must have zero high-severity red flags",
        "severity": "blocker",
        "check": lambda ctx: _count_severe_flags(ctx) == 0,
        "action": "Supplier rejected — scam indicators detected. Do not proceed.",
    },
    {
        "id": "max_red_flags",
        "name": "Maximum red flags limit",
        "description": "Supplier must not exceed 1 total red flag of any severity",
        "severity": "warning",
        "check": lambda ctx: len(ctx.get("red_flags", [])) <= MAX_RED_FLAGS,
        "action": "Supplier has multiple red flags — proceed with extreme caution or reject",
    },
    {
        "id": "sample_before_bulk",
        "name": "Sample required before bulk order",
        "description": "Must order and approve samples before placing any bulk order",
        "severity": "blocker",
        "check": lambda ctx: not ctx.get("is_bulk_order", False) or ctx.get("sample_approved", False),
        "action": "Cannot place bulk order without approved sample — order samples first",
    },
    {
        "id": "backup_supplier",
        "name": "Backup supplier required",
        "description": "Must have at least one backup supplier identified before committing",
        "severity": "warning",
        "check": lambda ctx: ctx.get("backup_supplier_identified", False),
        "action": "No backup supplier — identify at least one alternative before placing order",
    },
    {
        "id": "payment_protection",
        "name": "Payment protection required",
        "description": "First orders must use Trade Assurance, escrow, or equivalent protection",
        "severity": "blocker",
        "check": lambda ctx: (
            ctx.get("has_payment_protection", False)
            or ctx.get("is_repeat_supplier", False)
        ),
        "action": "Payment protection required — use Trade Assurance or escrow for first orders",
    },
    {
        "id": "min_quality_score",
        "name": "Minimum quality score",
        "description": "Supplier quality score must be at least 40/100",
        "severity": "warning",
        "check": lambda ctx: ctx.get("quality_score", 0) >= MIN_QUALITY_SCORE,
        "action": "Quality score below threshold — only suitable for disposable/low-value items",
    },
    {
        "id": "min_account_age",
        "name": "Minimum account age",
        "description": "Supplier account must be at least 6 months old",
        "severity": "warning",
        "check": lambda ctx: ctx.get("account_age_years", 0) >= MIN_ACCOUNT_AGE_YEARS,
        "action": "New supplier account — higher scam risk. Require extra due diligence.",
    },
    {
        "id": "verified_contact",
        "name": "Verified contact information",
        "description": "Supplier must have verified business address and phone number",
        "severity": "warning",
        "check": lambda ctx: ctx.get("contact_verified", False),
        "action": "Unverified contact info — cannot confirm supplier legitimacy",
    },
]


def evaluate_rules(context: dict[str, Any]) -> dict[str, Any]:
    """Evaluate all rules against the supplier context."""
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for rule in RULES:
        try:
            passed = rule["check"](context)
        except Exception:
            passed = True  # Do not block on evaluation errors

        if not passed:
            entry = {"rule_id": rule["id"], "name": rule["name"], "action": rule["action"]}
            if rule["severity"] == "blocker":
                blockers.append(entry)
            else:
                warnings.append(entry)

    return {
        "passed": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "rules_evaluated": len(RULES),
        "supplier_cleared": len(blockers) == 0 and len(warnings) <= 1,
    }


def _count_severe_flags(ctx: dict[str, Any]) -> int:
    """Count red flags with severity >= 0.7 (high severity)."""
    flags = ctx.get("red_flags", [])
    count = 0
    for flag_id in flags:
        indicator = RED_FLAG_INDICATORS.get(flag_id, {})
        if indicator.get("severity", 0) >= 0.7:
            count += 1
    return count
