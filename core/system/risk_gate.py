"""Per-action risk classification + approval policy.

Phase 2 of the 4×4 matrix work (docs/BUSINESS_MODEL_MATRIX.md).
Owner's architectural principle: **this is CORE logic** — brain
domain knowledge about which store actions are safe vs
dangerous. Not commodity. Built ourselves, no LLM, no
third-party rules engine.

Separation of concerns:
  * This module: rule-based classification + policy. Pure
    function, deterministic, 0 LLM calls. § 4a 95/5 rule.
  * ``core/system/approval_queue.py``: storage for queued
    HIGH/CRITICAL requests. Also core (our logic).
  * ``core/adapters/telegram_bot/*``: delivery to owner.
    Commodity — swap-able. Any ``core.notify`` adapter works.

Usage (intended consumer pattern):

    from core.system.risk_gate import classify, is_auto_approved
    from core.system.approval_queue import get_queue

    level = classify("ad_campaign_create", {
        "daily_budget_usd": 20, "store": "deguar",
    })
    if is_auto_approved(level, auto_approve=True,
                        live_execution=True):
        # proceed with the write
        ...
    else:
        req_id = get_queue().enqueue(
            "ad_campaign_create", payload, level,
        )
        # caller either blocks until resolved, or schedules
        # follow-up via webhook on the approve/deny event

The caller owns the "block vs async" choice — some actions can
wait, some (eg cycle-blocking decisions) should degrade to a
dry-run response instead of blocking.
"""
from __future__ import annotations

import logging
from typing import Any

from core.contracts import RiskLevel

_logger = logging.getLogger("shopai.risk_gate")


# ── Action → base risk rules ─────────────────────────────
# One row per canonical action_type. Callers passing a novel
# action_type get MEDIUM by default — safe middle ground that
# errs on the side of asking the owner rather than silently
# auto-approving.

_ACTION_RULES: dict[str, RiskLevel] = {
    # ── LOW — reversible in < 1 min, no money flow ──
    "metafield_write": RiskLevel.LOW,
    "metafield_delete": RiskLevel.LOW,  # cheap to re-create
    "tag_add": RiskLevel.LOW,
    "tag_remove": RiskLevel.LOW,
    "collection_membership": RiskLevel.LOW,
    "page_update": RiskLevel.LOW,
    "page_create": RiskLevel.LOW,
    "redirect_create": RiskLevel.LOW,
    "seo_rewrite": RiskLevel.LOW,

    # ── MEDIUM — reversible in < 10 min, internal only ──
    "product_draft": RiskLevel.MEDIUM,
    "product_publish": RiskLevel.MEDIUM,
    "product_update": RiskLevel.MEDIUM,
    "image_upload": RiskLevel.MEDIUM,
    "blog_publish": RiskLevel.MEDIUM,
    "smart_collection_create": RiskLevel.MEDIUM,
    "script_tag_create": RiskLevel.MEDIUM,  # pixel install
    "webhook_subscribe": RiskLevel.MEDIUM,
    "shipping_zone_update": RiskLevel.MEDIUM,
    "price_change": RiskLevel.MEDIUM,  # escalates by delta
    "inventory_update": RiskLevel.MEDIUM,

    # ── HIGH — commits money / external surface ──
    "ad_campaign_create": RiskLevel.HIGH,
    "ad_campaign_resume": RiskLevel.HIGH,
    "ad_budget_set": RiskLevel.HIGH,   # escalates by $ amount
    "discount_code_create": RiskLevel.HIGH,
    "supplier_order_place": RiskLevel.HIGH,
    "email_blast_send": RiskLevel.HIGH,
    "community_broadcast": RiskLevel.HIGH,
    "product_delete": RiskLevel.HIGH,  # NOT reversible via API
    "variant_delete": RiskLevel.HIGH,
    "order_refund": RiskLevel.HIGH,

    # ── CRITICAL — irreversible or expensive rollback ──
    "live_execution_toggle": RiskLevel.CRITICAL,
    "policy_rewrite": RiskLevel.CRITICAL,
    "checkout_config_change": RiskLevel.CRITICAL,
    "new_store_connect": RiskLevel.CRITICAL,
    "store_delete": RiskLevel.CRITICAL,
    "theme_publish": RiskLevel.CRITICAL,  # changes whole look
    "dns_change": RiskLevel.CRITICAL,
    "scope_grant": RiskLevel.CRITICAL,
    "emergency_halt_clear": RiskLevel.CRITICAL,
}


def classify(
    action_type: str,
    payload: dict[str, Any] | None = None,
) -> RiskLevel:
    """Rule-based risk classification. Pure function.

    ``action_type`` lookup → base level. Some levels escalate
    based on ``payload`` fields:

      * ``price_change`` with ``|delta_pct| ≥ 10`` → HIGH
        (sitewide re-pricing affects CVR + margin significantly)
      * ``ad_budget_set`` / ``ad_campaign_create`` with
        ``daily_budget_usd > 100`` → CRITICAL
        (above $3k/month per campaign — outside "test" budget)
      * ``ad_campaign_create`` with ``daily_budget_usd > 500``
        → CRITICAL regardless of other fields
      * ``inventory_update`` with ``delta_units < -100`` (big
        drawdown) → HIGH (could zero out fast-movers)

    Unknown ``action_type`` → MEDIUM — forces owner visibility
    on actions we haven't classified yet rather than silently
    auto-approving.
    """
    p = payload or {}
    base = _ACTION_RULES.get(action_type, RiskLevel.MEDIUM)

    # ── Escalation overrides ──────────────────────────────

    if action_type == "price_change":
        try:
            delta_pct = abs(float(p.get("delta_pct", 0) or 0))
        except (TypeError, ValueError):
            delta_pct = 0.0
        if delta_pct >= 10.0:
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM

    if action_type in ("ad_budget_set", "ad_campaign_create"):
        try:
            budget = float(p.get("daily_budget_usd", 0) or 0)
        except (TypeError, ValueError):
            budget = 0.0
        if budget > 500:
            return RiskLevel.CRITICAL
        if budget > 100:
            return RiskLevel.CRITICAL
        return RiskLevel.HIGH

    if action_type == "inventory_update":
        try:
            delta = float(p.get("delta_units", 0) or 0)
        except (TypeError, ValueError):
            delta = 0.0
        if delta < -100:
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM

    return base


def is_auto_approved(
    level: RiskLevel,
    *,
    auto_approve: bool = False,
    live_execution: bool = False,
) -> bool:
    """Policy from BUSINESS_MODEL_MATRIX.md §Risk classification.

    Encoding:

        LOW       → always auto (even without live_execution —
                    these are read-side-effects or store-internal
                    meta, no money commit)
        MEDIUM    → auto ONLY if BOTH auto_approve=True AND
                    live_execution=True. Either off → queue.
        HIGH      → always queue (owner must confirm)
        CRITICAL  → always queue (owner must double-confirm)

    The ``auto_approve`` flag maps to the existing
    ``AutonomousController(auto_approve=...)`` knob so Phase 1
    behaviour stays identical — LOW + MEDIUM-with-both-flags-on
    still auto-approves. HIGH+CRITICAL are the only new
    behaviour, and callers opt in by invoking ``classify()``
    + ``is_auto_approved()`` at their commit points.
    """
    if level == RiskLevel.LOW:
        return True
    if level == RiskLevel.MEDIUM:
        return bool(auto_approve and live_execution)
    # HIGH, CRITICAL — never
    return False


def known_actions() -> list[str]:
    """Sorted list of canonical action names — used by the CLI
    ``shopai pending-approvals`` help output and by tests to
    verify we don't forget to classify a new kind of write."""
    return sorted(_ACTION_RULES.keys())


def describe(level: RiskLevel) -> str:
    """Owner-facing one-liner for each level. Used by the
    approval-queue notification message so owner sees WHY the
    action is gated."""
    return {
        RiskLevel.LOW: (
            "Reversible in < 1 min, no money flow — "
            "auto-approved."
        ),
        RiskLevel.MEDIUM: (
            "Reversible in < 10 min, internal only — "
            "auto-approved if both `auto_approve` and "
            "`live_execution` are on."
        ),
        RiskLevel.HIGH: (
            "Commits money or touches an external surface. "
            "Owner must approve before the write runs."
        ),
        RiskLevel.CRITICAL: (
            "Irreversible or expensive rollback. Owner must "
            "double-confirm before the write runs."
        ),
    }[level]
