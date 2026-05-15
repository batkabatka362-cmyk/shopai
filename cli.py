"""ShopAI CLI — command-line interface for managing stores and AI operations.

Usage:
    python cli.py store add <store_id> <shop_url> <api_key> [--name NAME] [--niche NICHE]
    python cli.py store list
    python cli.py store switch <store_id>
    python cli.py store status [store_id]
    python cli.py store connect [store_id]

    python cli.py sync [store_id]               # Sync data from Shopify
    python cli.py sync --auto [--interval 300]   # Start auto-sync

    python cli.py run <engine_name> [--store STORE] [--params JSON]
    python cli.py engines                        # List all engines
    python cli.py engine-info <engine_name>

    python cli.py actions pending                # Show pending actions
    python cli.py actions approve <action_id>    # Approve an action
    python cli.py actions approve-all            # Approve all pending
    python cli.py actions log                    # Show action history

    python cli.py health                         # System health check
    python cli.py status                         # Full system status
    python cli.py setup                          # Interactive setup wizard
"""

import argparse
import json
import os
import sys
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("cli")

# Bump this when releasing or cutting a milestone branch. The
# version is surfaced by ``shopai version`` and embedded in
# support-bundle output — operators reporting an issue can
# include it so we know what code they're running.
SHOPAI_VERSION = "0.31.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shopai",
        description="ShopAI — AI-powered autonomous e-commerce system",
    )
    sub = parser.add_subparsers(dest="command")

    # ── Store commands ───────────────────────────────────────
    store_p = sub.add_parser("store", help="Manage Shopify stores")
    store_sub = store_p.add_subparsers(dest="store_action")

    add_p = store_sub.add_parser("add", help="Add a new Shopify store")
    add_p.add_argument("store_id", help="Unique store identifier")
    add_p.add_argument("shop_url", help="Shopify store URL (e.g. mystore.myshopify.com)")
    add_p.add_argument("--client-id", default="", help="OAuth Client ID (2026+)")
    add_p.add_argument("--client-secret", default="", help="OAuth Client Secret (2026+)")
    add_p.add_argument("--api-key", default="", help="Legacy API token (pre-2026)")
    add_p.add_argument("--name", default="", help="Store display name")
    add_p.add_argument("--niche", default="", help="Store niche (e.g. electronics)")
    add_p.add_argument("--type", default="dropshipping", dest="store_type",
                        choices=["dropshipping", "brand", "niche", "general"])

    store_sub.add_parser("list", help="List all stores")

    switch_p = store_sub.add_parser("switch", help="Switch active store")
    switch_p.add_argument("store_id", help="Store to activate")

    status_p = store_sub.add_parser("status", help="Show store stats")
    status_p.add_argument("store_id", nargs="?", help="Store ID (default: active store)")

    connect_p = store_sub.add_parser("connect", help="Test Shopify connection")
    connect_p.add_argument("store_id", nargs="?", help="Store ID (default: active store)")

    remove_p = store_sub.add_parser("remove", help="Remove a store")
    remove_p.add_argument("store_id", help="Store to remove")

    configure_p = store_sub.add_parser(
        "configure",
        help="Auto-configure store settings (collections, discounts, shipping, emails, payments, etc.)",
    )
    configure_p.add_argument(
        "store_id", nargs="?",
        help="Store ID (default: active store)",
    )
    configure_p.add_argument(
        "--dry-run", action="store_true",
        help="Preview what would be done without making changes",
    )
    configure_p.add_argument(
        "--only", default="",
        help=(
            "Comma-separated features to run. Valid: collections, discounts, "
            "shipping, content, product_tags, ai_config, gifts, loyalty, "
            "referral, emails, payments. Default: all."
        ),
    )
    configure_p.add_argument(
        "--niche", default="",
        help="Override store niche (default: use stored niche)",
    )

    # ── Sync commands ────────────────────────────────────────
    sync_p = sub.add_parser("sync", help="Sync data from Shopify")
    sync_p.add_argument("store_id", nargs="?", help="Store ID (default: active)")
    sync_p.add_argument("--auto", action="store_true", help="Start auto-sync")
    sync_p.add_argument("--interval", type=int, default=300, help="Auto-sync interval (seconds)")

    # ── Database schema commands ─────────────────────────────
    db_p = sub.add_parser("db", help="Inspect / migrate databases")
    db_sub = db_p.add_subparsers(dest="db_action")
    db_sub.add_parser("status", help="Show schema version for every DB")
    db_sub.add_parser("migrate", help="Apply pending migrations to all DBs")
    db_sub.add_parser(
        "info",
        help="Inventory all data/ files with size, age, row counts",
    )
    db_backup_p = db_sub.add_parser(
        "backup",
        help="Snapshot data/ to a tar.gz (operator safety net)",
    )
    db_backup_p.add_argument(
        "--out", default=None,
        help="Output path (default: shopai-backup-<UTC ts>.tar.gz)",
    )
    db_restore_p = db_sub.add_parser(
        "restore",
        help="Replace data/ with contents of a backup tarball",
    )
    db_restore_p.add_argument("archive", help="Path to tar.gz")
    db_restore_p.add_argument(
        "--yes", action="store_true",
        help="Skip confirmation (CAUTION: replaces live data)",
    )

    goal_p = sub.add_parser(
        "goal",
        help="Inspect / manage brain-stack goal state (EMA, persistence)",
    )
    goal_sub = goal_p.add_subparsers(dest="goal_action")
    goal_sub.add_parser(
        "show", help="Show current goal + per-goal effectiveness EMA",
    )
    goal_reset_p = goal_sub.add_parser(
        "reset", help="Clear per-goal EMA stats (wipes learned signal)",
    )
    goal_reset_p.add_argument(
        "--yes", action="store_true", help="Skip confirmation prompt",
    )

    # ── Config commands ──────────────────────────────────────
    config_p = sub.add_parser("config", help="Inspect / validate configuration")
    config_sub = config_p.add_subparsers(dest="config_action")
    config_sub.add_parser("check", help="Validate env vars against schema")
    config_sub.add_parser("show", help="Show current config values + defaults")

    # ── Cognitive (Mind) commands ────────────────────────────
    mind_p = sub.add_parser("mind", help="Inspect / drive the cognitive Mind")
    mind_sub = mind_p.add_subparsers(dest="mind_action")
    mind_sub.add_parser("status", help="Show self-narrative + active goals")
    mind_sub.add_parser("cycle", help="Run one cognitive cycle")
    mind_sub.add_parser("reflect", help="Force a reflection pass")
    mind_sub.add_parser("goals", help="List active goals")
    mind_sub.add_parser("skills", help="List registered skills")
    mind_explain = mind_sub.add_parser("explain", help="Explain a goal: plan + imagination")
    mind_explain.add_argument("goal_id", help="Goal ID to explain")

    mind_think = mind_sub.add_parser(
        "think",
        help="Ask the AI a free-form question with cognitive context",
    )
    mind_think.add_argument(
        "question", nargs="+",
        help="The question to think about (can be multiple words)",
    )
    mind_think.add_argument(
        "--no-context", action="store_true",
        help="Skip the self-narrative + goals context block",
    )
    mind_think.add_argument(
        "--role", default="reasoner",
        help="LLM role to use (analyzer, reasoner, creative, worker)",
    )

    mind_sub.add_parser("llm-status", help="Show LLM provider availability and stats")

    # ── Engine commands ──────────────────────────────────────
    engines_p = sub.add_parser(
        "engines", help="List all registered engines",
    )
    engines_p.add_argument(
        "--by-goal", action="store_true",
        help="Group engines by their primary brain-stack goal",
    )
    engines_p.add_argument(
        "--unmapped", action="store_true",
        help="Show only engines without a primary-goal mapping",
    )

    eng_info = sub.add_parser("engine-info", help="Show engine details")
    eng_info.add_argument("engine_name", help="Engine name")
    eng_info.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    eng_calibration = sub.add_parser(
        "engine-calibration",
        help=(
            "Confidence-bucket calibration for an engine "
            "(does high confidence actually correlate with "
            "positive outcomes?)"
        ),
    )
    eng_calibration.add_argument(
        "engine_name", help="Engine to inspect",
    )
    eng_calibration.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    eng_scorecard = sub.add_parser(
        "engine-scorecard",
        help=(
            "Unified per-engine scorecard — volume, outcomes, "
            "calibration, workflow, veto, revenue, governance "
            "in one view"
        ),
    )
    eng_scorecard.add_argument(
        "engine_name", help="Engine to inspect",
    )
    eng_scorecard.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    engs_calibration = sub.add_parser(
        "engines-calibration",
        help=(
            "Calibration sweep across every engine; highlights "
            "miscalibrated allowlisted engines (highest-priority "
            "alerts)"
        ),
    )
    engs_calibration.add_argument(
        "--miscalibrated-only", action="store_true",
        help=(
            "Filter to engines with inverted calibration "
            "(triage mode)"
        ),
    )
    engs_calibration.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    run_p = sub.add_parser("run", help="Run an engine")
    run_p.add_argument("task_type", help="Engine name")
    run_p.add_argument("--store", default="", help="Store ID")
    run_p.add_argument("--params", type=str, default="{}", help="JSON params")

    suggest_p = sub.add_parser(
        "suggest",
        help="Recommend which engines to run next (goal × effectiveness)",
    )
    suggest_p.add_argument(
        "--goal", default=None,
        help="Active goal override (default: current goal from GoalManager)",
    )
    suggest_p.add_argument(
        "--limit", type=int, default=5,
        help="Number of primary recommendations to display (default: 5)",
    )
    suggest_p.add_argument(
        "--no-alternatives", action="store_true",
        help="Skip the cross-goal alternatives section",
    )
    suggest_p.add_argument(
        "--json", action="store_true",
        help="Emit the raw JSON payload instead of the table view",
    )

    knowledge_p = sub.add_parser(
        "knowledge",
        help="Knowledge-vault export (Obsidian-compatible Markdown)",
    )
    knowledge_sub = knowledge_p.add_subparsers(dest="knowledge_action")
    knowledge_export = knowledge_sub.add_parser(
        "export",
        help="Dump ShopAI state to a directory as Markdown",
    )
    knowledge_export.add_argument(
        "target", help="Vault directory (created if missing)",
    )
    knowledge_export.add_argument(
        "--decision-limit", type=int, default=200,
        help="Max decisions exported (default: 200, newest first)",
    )

    knowledge_digest = knowledge_sub.add_parser(
        "digest",
        help="Render a one-page insight digest (briefing)",
    )
    knowledge_digest.add_argument(
        "--since", dest="since_days", type=int, default=7,
        help="Window in days for the recent-activity section (default: 7)",
    )
    knowledge_digest.add_argument(
        "--limit", dest="decision_limit", type=int, default=20,
        help="Max decisions to list (default: 20)",
    )
    knowledge_digest.add_argument(
        "--out", default="",
        help="Write to this path (default: stdout)",
    )

    knowledge_import = knowledge_sub.add_parser(
        "import",
        help="Read operator notes back from a vault into ShopAI",
    )
    knowledge_import.add_argument(
        "source", help="Vault directory to scan",
    )

    knowledge_notes = knowledge_sub.add_parser(
        "notes",
        help="Inspect the persisted operator-notes store",
    )
    knowledge_notes.add_argument(
        "kind", nargs="?", choices=["engine", "goal"],
        default=None,
        help="Filter by kind (default: list both)",
    )
    knowledge_notes.add_argument(
        "name", nargs="?", default=None,
        help="Show notes for a specific engine / goal name",
    )

    knowledge_set = knowledge_sub.add_parser(
        "set-notes",
        help="Add / update an operator note for an engine or goal",
    )
    knowledge_set.add_argument(
        "kind", choices=["engine", "goal"],
        help="Which kind of note to set",
    )
    knowledge_set.add_argument(
        "name",
        help="Engine name (cart_recovery) or goal name (grow_customers)",
    )
    knowledge_set_body = knowledge_set.add_mutually_exclusive_group(
        required=True,
    )
    knowledge_set_body.add_argument(
        "--text",
        help="Note body inline (use '-' to read from stdin)",
    )
    knowledge_set_body.add_argument(
        "--from-file",
        help="Path to a file whose contents become the note body",
    )

    # ── Action commands ──────────────────────────────────────
    action_p = sub.add_parser("actions", help="Manage AI actions")
    action_sub = action_p.add_subparsers(dest="action_cmd")

    action_sub.add_parser("pending", help="Show pending actions")
    action_sub.add_parser("log", help="Show action history")
    action_sub.add_parser("stats", help="Show action stats")

    approve_p = action_sub.add_parser("approve", help="Approve an action")
    approve_p.add_argument("action_id", help="Action ID to approve")

    action_sub.add_parser("approve-all", help="Approve all pending")

    reject_p = action_sub.add_parser("reject", help="Reject an action")
    reject_p.add_argument("action_id", help="Action ID to reject")
    reject_p.add_argument("--reason", default="", help="Rejection reason")

    # ── Approvals (modern ApprovalQueue, distinct from legacy `actions`) ─
    #
    # ``actions ...`` above wires the legacy ``ActionExecutor`` (older
    # in-memory action store). The modern path is the SQLite-backed
    # ``ApprovalQueue`` (PR #57) — engines enqueue via
    # ``data.apply_X=True + data.require_approval=True``; merchants
    # decide via /api/pending-actions or these CLI surfaces; the
    # executor (PR #69 + #102) replays via registered dispatchers.
    approvals_p = sub.add_parser(
        "approvals",
        help="Modern approval-queue commands (ApprovalQueue + executor)",
    )
    approvals_sub = approvals_p.add_subparsers(dest="approvals_cmd")

    approvals_pending = approvals_sub.add_parser(
        "pending", help="List pending approval-queue actions",
    )
    approvals_pending.add_argument(
        "--engine", default=None,
        help="Filter to a single engine namespace",
    )
    approvals_pending.add_argument(
        "--limit", type=int, default=20,
        help="Page size (default: 20)",
    )

    approvals_stats = approvals_sub.add_parser(
        "stats", help="Per-status counts in the approval queue",
    )
    approvals_stats.add_argument(
        "--by-engine", action="store_true",
        help="Break down counts per engine (triage signal)",
    )

    approvals_show = approvals_sub.add_parser(
        "show", help="Show full detail for one action",
    )
    approvals_show.add_argument("action_id", help="Action ID")
    approvals_show.add_argument(
        "--no-outcomes", action="store_true",
        help=(
            "Skip embedding downstream outcomes (default: include "
            "outcomes for EXECUTED actions)"
        ),
    )

    approvals_approve = approvals_sub.add_parser(
        "approve",
        help="Approve a pending action (optionally auto-execute)",
    )
    approvals_approve.add_argument("action_id", help="Action ID")
    approvals_approve.add_argument(
        "--reason", default="",
        help="Operator note attached to the decision",
    )
    approvals_approve.add_argument(
        "--by", default="operator",
        help="Operator name attributed to the decision",
    )
    approvals_approve.add_argument(
        "--execute", action="store_true",
        help="Immediately run the executor on the approved action",
    )

    approvals_reject = approvals_sub.add_parser(
        "reject", help="Reject a pending action",
    )
    approvals_reject.add_argument("action_id", help="Action ID")
    approvals_reject.add_argument(
        "--reason", default="", help="Rejection reason",
    )
    approvals_reject.add_argument(
        "--by", default="operator",
        help="Operator name attributed to the decision",
    )

    approvals_execute = approvals_sub.add_parser(
        "execute", help="Execute an already-approved action",
    )
    approvals_execute.add_argument("action_id", help="Action ID")

    approvals_sweep = approvals_sub.add_parser(
        "sweep",
        help="Expire PENDING actions older than --older-than",
    )
    approvals_sweep.add_argument(
        "--older-than", default="7d",
        help="Age threshold (e.g. 60s, 30m, 24h, 7d). Default: 7d.",
    )
    approvals_sweep.add_argument(
        "--dry-run", action="store_true",
        help="Show what would expire without writing",
    )

    approvals_approve_all = approvals_sub.add_parser(
        "approve-all",
        help="Bulk-approve PENDING actions matching filters",
    )
    approvals_approve_all.add_argument(
        "--engine", default=None,
        help="Restrict to one engine (omit = all engines)",
    )
    approvals_approve_all.add_argument(
        "--min-confidence", type=float, default=None,
        help="Skip actions below this confidence (0.0-1.0)",
    )
    approvals_approve_all.add_argument(
        "--by", default="operator",
        help="Operator name attributed to each decision",
    )
    approvals_approve_all.add_argument(
        "--reason", default="bulk_approve",
        help="Decision reason attached to each approval",
    )
    approvals_approve_all.add_argument(
        "--execute", action="store_true",
        help="Immediately run the executor on each approval",
    )
    approvals_approve_all.add_argument(
        "--dry-run", action="store_true",
        help="Show what would approve without writing",
    )

    approvals_audit = approvals_sub.add_parser(
        "audit",
        help="Audit dispatcher coverage vs engine enqueue sites",
    )
    approvals_audit.add_argument(
        "--engines-root", default="engines",
        help="Path to engines directory (default: engines)",
    )

    approvals_history = approvals_sub.add_parser(
        "history",
        help=(
            "Append-only decision audit trail (per-action lifecycle "
            "or global ticker)"
        ),
    )
    approvals_history.add_argument(
        "action_id", nargs="?", default=None,
        help=(
            "Action ID to scope to. Omit for the global decision "
            "ticker (newest first)."
        ),
    )
    approvals_history.add_argument(
        "--by", default=None,
        help="Restrict to decisions made by this actor (use 'system' for executor)",
    )
    approvals_history.add_argument(
        "--limit", type=int, default=50,
        help="Page size (default: 50)",
    )
    approvals_history.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the table view",
    )

    approvals_revenue = approvals_sub.add_parser(
        "revenue-by-engine",
        help=(
            "Per-engine revenue attribution from matched "
            "outcomes (gross/refunded/net + per-positive)"
        ),
    )
    approvals_revenue.add_argument(
        "--top", type=int, default=20, metavar="N",
        help="How many top engines to render (default 20)",
    )
    approvals_revenue.add_argument(
        "--sort", default="net",
        choices=["net", "gross", "per-positive"],
        help=(
            "Sort key. 'net' (default): net_revenue desc. "
            "'gross': gross_revenue desc (ignores refunds). "
            "'per-positive': revenue_per_positive_outcome desc "
            "(useful when comparing across volume)."
        ),
    )
    approvals_revenue.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the table view",
    )

    approvals_rejection_rates = approvals_sub.add_parser(
        "rejection-rates",
        help=(
            "Per-engine rejection rate — surfaces engines whose "
            "proposals operators consistently veto"
        ),
    )
    approvals_rejection_rates.add_argument(
        "--min-decisions", type=int, default=5,
        metavar="N",
        help=(
            "Minimum decided actions for an engine to surface "
            "(filters out engines with too little signal). "
            "Default: 5."
        ),
    )
    approvals_rejection_rates.add_argument(
        "--threshold", type=float, default=None,
        metavar="RATE",
        help=(
            "Filter to engines with rejection_rate >= RATE "
            "(e.g. 0.5 for majority-rejected). Alert mode."
        ),
    )
    approvals_rejection_rates.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the table view",
    )

    approvals_decision_latency = approvals_sub.add_parser(
        "decision-latency",
        help=(
            "Per-engine historical decision latency — how fast "
            "operators DECIDE on this engine's proposals"
        ),
    )
    approvals_decision_latency.add_argument(
        "--status", default="default",
        choices=[
            "default", "approved", "rejected", "executed",
            "failed", "expired", "all",
        ],
        help=(
            "Which decision statuses to aggregate. 'default' = "
            "approved+rejected+executed+failed (excludes EXPIRED "
            "since its decided_at is sweeper time, not operator "
            "time). 'all' includes EXPIRED."
        ),
    )
    approvals_decision_latency.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the table view",
    )

    approvals_pending_latency = approvals_sub.add_parser(
        "pending-latency",
        help=(
            "Per-engine PENDING-action age aggregator — surfaces "
            "engines producing un-actionable proposals"
        ),
    )
    approvals_pending_latency.add_argument(
        "--older-than", default=None, metavar="AGE",
        help=(
            "Filter to engines whose oldest PENDING exceeds AGE "
            "(e.g. 1h, 24h, 7d). Default: no filter."
        ),
    )
    approvals_pending_latency.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the table view",
    )

    approvals_release_candidates = approvals_sub.add_parser(
        "quarantine-release-candidates",
        help=(
            "Recommend quarantined engines whose recent outcomes "
            "have improved enough to safely release"
        ),
    )
    approvals_release_candidates.add_argument(
        "--since", default="7d", metavar="AGE",
        help=(
            "Recent-window size for recovery check "
            "(e.g. 1d, 3d, 7d). Default 7d."
        ),
    )
    approvals_release_candidates.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the table view",
    )

    approvals_auto_candidates = approvals_sub.add_parser(
        "auto-approve-candidates",
        help=(
            "Recommend engines NOT yet on the auto-approve "
            "allowlist that already pass the outcome guardrails"
        ),
    )
    approvals_auto_candidates.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the table view",
    )

    approvals_quarantine = approvals_sub.add_parser(
        "quarantine",
        help=(
            "Manage failed-engine quarantine "
            "(exemptions + operator releases)"
        ),
    )
    quarantine_action = (
        approvals_quarantine.add_mutually_exclusive_group()
    )
    quarantine_action.add_argument(
        "--release", metavar="ENGINE", default=None,
        help=(
            "Manually release a quarantined ENGINE — bypasses "
            "quarantine until the operator clears the release"
        ),
    )
    quarantine_action.add_argument(
        "--clear-release", metavar="ENGINE", default=None,
        help="Remove ENGINE from the released list",
    )
    quarantine_action.add_argument(
        "--exempt", metavar="ENGINE", default=None,
        help=(
            "Permanently exempt ENGINE from quarantine (legit "
            "high-negative-ratio engines)"
        ),
    )
    quarantine_action.add_argument(
        "--unexempt", metavar="ENGINE", default=None,
        help="Remove ENGINE from the exemption list",
    )
    quarantine_action.add_argument(
        "--list", action="store_true",
        help="Show current exemptions + released engines + thresholds",
    )
    approvals_quarantine.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    approvals_auto_config = approvals_sub.add_parser(
        "auto-config",
        help=(
            "Manage the auto-approve allowlist (per-engine "
            "opt-in for proven engines)"
        ),
    )
    auto_action = approvals_auto_config.add_mutually_exclusive_group()
    auto_action.add_argument(
        "--enable", metavar="ENGINE", default=None,
        help="Add ENGINE to the auto-approve allowlist",
    )
    auto_action.add_argument(
        "--disable", metavar="ENGINE", default=None,
        help="Remove ENGINE from the auto-approve allowlist",
    )
    auto_action.add_argument(
        "--list", action="store_true",
        help="Show current allowlist + threshold settings",
    )
    approvals_auto_config.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    approvals_recent = approvals_sub.add_parser(
        "recent",
        help="List recent actions filtered by status (operator triage)",
    )
    approvals_recent.add_argument(
        "status",
        choices=["pending", "approved", "rejected",
                 "executed", "failed", "expired"],
        help="Status to filter on",
    )
    approvals_recent.add_argument(
        "--engine", default=None,
        help="Restrict to one engine namespace",
    )
    approvals_recent.add_argument(
        "--limit", type=int, default=10,
        help="Page size (default: 10)",
    )

    # ── Pipeline commands ────────────────────────────────────
    pipeline = sub.add_parser("pipeline", help="Run a data pipeline")
    pipeline.add_argument("pipeline_name", choices=["product", "marketing", "analytics"])
    pipeline.add_argument("--input", type=str, required=True, help="Path to input JSON")

    # ── Workflow commands ────────────────────────────────────
    workflow = sub.add_parser("workflow", help="Run a workflow")
    workflow.add_argument("workflow_name", help="Workflow name")
    workflow.add_argument("--params", type=str, default="{}", help="JSON params")

    # ── Autonomous commands ─────────────────────────────────
    auto_p = sub.add_parser("auto", help="Run autonomous AI cycle")
    auto_p.add_argument("--store", default="", help="Store ID")
    auto_p.add_argument("--loop", action="store_true", help="Run continuously")
    auto_p.add_argument("--interval", type=int, default=600, help="Loop interval (seconds)")
    auto_p.add_argument("--auto-approve", action="store_true", help="Auto-approve actions (DANGEROUS)")
    auto_p.add_argument(
        "--use-recommender", action="store_true",
        help="Pick analysis engines via brain-stack recommender (vs legacy hardcoded list)",
    )

    learn_p = sub.add_parser("learn", help="Show learning status")
    learn_p.add_argument("--details", action="store_true", help="Show detailed learning data")

    feedback_p = sub.add_parser(
        "feedback",
        help="Inspect webhook feedback bridge (events → engine attribution)",
    )
    feedback_sub = feedback_p.add_subparsers(dest="feedback_action")
    feedback_stats = feedback_sub.add_parser(
        "stats", help="Show webhook bridge counters",
    )
    feedback_stats.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the table view",
    )

    # ── System commands ──────────────────────────────────────
    sub.add_parser("health", help="System health check")
    status_p = sub.add_parser("status", help="Full system status")
    status_p.add_argument(
        "--json", action="store_true",
        help="Emit raw status JSON instead of the table view",
    )

    loop_p = sub.add_parser(
        "loop",
        help="Single-screen autonomous-loop dashboard (queue + EMA + recommender + outcomes)",
    )
    loop_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the table view",
    )
    loop_p.add_argument(
        "--top", type=int, default=5,
        help="How many top-recommended engines to render (default 5)",
    )
    loop_p.add_argument(
        "--watch", type=int, default=0, metavar="SECONDS",
        help=(
            "Refresh the dashboard every N seconds (like top/htop). "
            "Default 0 = one-shot. Ctrl+C exits the watch loop."
        ),
    )

    outcomes_p = sub.add_parser(
        "outcomes",
        help=(
            "Chronological view of recent webhook outcomes "
            "(action → downstream event attribution)"
        ),
    )
    outcomes_p.add_argument(
        "--limit", type=int, default=20,
        help="How many recent outcomes to show (default 20)",
    )
    outcomes_p.add_argument(
        "--engine", default=None,
        help="Restrict to one engine namespace",
    )
    outcomes_p.add_argument(
        "--polarity",
        choices=["positive", "negative", "neutral"],
        default=None,
        help="Restrict to one polarity bucket",
    )
    outcomes_p.add_argument(
        "--since", default=None, metavar="AGE",
        help=(
            "Only outcomes within the last AGE (e.g. 1h, 30m, "
            "7d). Empty = no time filter."
        ),
    )
    outcomes_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the table view",
    )

    sub.add_parser("setup", help="Interactive setup wizard")
    sub.add_parser("start", help="Start the orchestrator")
    sub.add_parser("stop", help="Stop the orchestrator")

    server_p = sub.add_parser("server", help="Start API + webhook server")
    server_p.add_argument("--port", type=int, default=8080, help="Port (default 8080)")
    server_p.add_argument("--host", default="0.0.0.0", help="Host (default 0.0.0.0)")

    version_p = sub.add_parser(
        "version",
        help="Show ShopAI version + runtime fingerprint",
    )
    version_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    return parser


# ── Store Commands ───────────────────────────────────────────

def _get_store_manager():
    from data_pipeline.store.store_manager import StoreManager
    sm = StoreManager()
    # Auto-load from .env if no stores configured
    stores = sm.list_stores()
    if not stores:
        url = os.environ.get("SHOPAI_SHOPIFY_URL", "")
        key = os.environ.get("SHOPAI_SHOPIFY_KEY", "")
        if url and key:
            store_id = url.replace(".myshopify.com", "").replace("https://", "")
            sm.add_store(store_id, url, key, name="Default Store")
    return sm


def _cmd_store_add(args) -> None:
    sm = _get_store_manager()
    result = sm.add_store(
        args.store_id, args.shop_url,
        api_key=args.api_key,
        client_id=args.client_id,
        client_secret=args.client_secret,
        name=args.name, niche=args.niche, store_type=args.store_type,
    )
    print(f"✓ Store added: {args.store_id}")
    print(f"  URL: {args.shop_url}")
    print(f"  Auth: {'OAuth (auto-refresh)' if args.client_id else 'Legacy token' if args.api_key else 'No credentials'}")
    print(f"  Type: {args.store_type}")
    if args.niche:
        print(f"  Niche: {args.niche}")


def _cmd_store_list(args) -> None:
    sm = _get_store_manager()
    stores = sm.list_stores()
    if not stores:
        print("No stores configured. Add one with: shopai store add <id> <url> <key>")
        return
    print(f"Stores ({len(stores)}):\n")
    for s in stores:
        active = " [ACTIVE]" if s.get("is_active") else ""
        print(f"  {s['store_id']}{active}")
        print(f"    URL:  {s['shop_url']}")
        print(f"    Type: {s.get('store_type', 'unknown')}")
        print(f"    Niche: {s.get('niche', '-')}")
        print()


def _cmd_store_switch(args) -> None:
    sm = _get_store_manager()
    result = sm.set_active_store(args.store_id)
    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)
    print(f"✓ Active store: {args.store_id}")


def _cmd_store_status(args) -> None:
    sm = _get_store_manager()
    store_id = args.store_id or sm.active_store_id
    if not store_id:
        print("No store selected. Add one with: shopai store add")
        return
    stats = sm.get_stats(store_id)
    store = sm.get_store(store_id)
    print(f"Store: {store_id}")
    print(f"  URL: {store.get('shop_url', '-') if store else '-'}")
    print(f"  Products:  {stats['products']}")
    print(f"  Orders:    {stats['orders']}")
    print(f"  Customers: {stats['customers']}")
    print(f"  Revenue:   ${stats['total_revenue']:,.2f}")


def _cmd_store_connect(args) -> None:
    sm = _get_store_manager()
    store_id = args.store_id or sm.active_store_id
    if not store_id:
        print("No store selected.")
        return
    print(f"Testing connection to {store_id}...")
    result = sm.test_connection(store_id)
    if result.get("connected"):
        print(f"✓ Connected to Shopify: {result.get('shop', store_id)}")
    else:
        print(f"✗ Connection failed: {result.get('error', 'unknown')}")


def _cmd_store_remove(args) -> None:
    sm = _get_store_manager()
    result = sm.remove_store(args.store_id)
    print(f"✓ Store removed: {args.store_id}")


def _cmd_store_configure(args) -> None:
    """Run the auto-configurator against a registered store."""
    sm = _get_store_manager()
    store_id = args.store_id or sm.active_store_id
    if not store_id:
        print("No store specified and no active store set.")
        return

    creds = sm.get_credentials(store_id)
    if not creds or not creds.get("shop_url"):
        print(f"Store {store_id!r} not found or has no shop_url.")
        return
    token = creds.get("api_key") or ""
    if not token and creds.get("client_id") and creds.get("client_secret"):
        # Try to resolve via OAuth cache
        try:
            from core.auth.shopify_auth import ShopifyAuth
            token = ShopifyAuth(
                creds["shop_url"], creds["client_id"], creds["client_secret"],
            ).get_token()
        except Exception as exc:  # noqa: BLE001
            print(f"Could not resolve OAuth token: {exc}")
            return
    if not token:
        print(f"Store {store_id!r} has no usable credentials.")
        return

    store_info = sm.db.get_store(store_id) if hasattr(sm, "db") else {}
    niche = args.niche or (store_info or {}).get("niche") or "general"
    store_name = (store_info or {}).get("name") or store_id

    features = None
    if args.only:
        features = [f.strip() for f in args.only.split(",") if f.strip()]

    from execution.store_configurator import StoreConfigurator, ALL_FEATURES

    if args.dry_run:
        print(f"Dry-run: configuring {store_id} (niche={niche})")
    else:
        print(f"Configuring {store_id} (niche={niche})...")
    if features:
        print(f"  Features: {', '.join(features)}")
    else:
        print(f"  Features: all ({len(ALL_FEATURES)})")

    configurator = StoreConfigurator(dry_run=args.dry_run)
    result = configurator.configure(
        creds["shop_url"], token,
        niche=niche, store_name=store_name, features=features,
    )

    # Summary
    print()
    print(f"Status: {result['status']}")
    print(f"Niche:  {result['niche']}")
    print()
    print("Feature results:")
    for name in sorted(result.get("results", {}).keys()):
        data = result["results"][name]
        summary = _format_feature_summary(name, data)
        print(f"  {name:15s} {summary}")

    if args.dry_run and result.get("plan"):
        print()
        print(f"Planned writes ({len(result['plan'])}):")
        for step in result["plan"]:
            print(f"  {step['method']:6s} {step['path']:45s} {step['description']}")


def _format_feature_summary(name: str, data: dict) -> str:
    if not isinstance(data, dict):
        return str(data)
    if name == "collections":
        return f"created={data.get('created', 0)}, existing={data.get('existing', 0)}"
    if name == "discounts":
        codes = data.get("codes", [])
        return f"created={data.get('created', 0)} ({', '.join(codes[:5])}{'…' if len(codes) > 5 else ''})"
    if name == "shipping":
        cov = "fully covered" if data.get("fully_covered") else f"{len(data.get('gap_countries', []))} missing"
        return f"current={data.get('current_zones', 0)}, recommended={data.get('recommended_zones', 0)}, {cov}"
    if name == "content":
        return f"pages_created={data.get('pages_created', 0)}"
    if name == "product_tags":
        return f"tagged={data.get('tagged', 0)}"
    if name == "ai_config":
        return "saved" if data.get("saved") else "skip"
    if name == "gifts":
        prod = data.get("gift_product_id")
        return f"threshold=${data.get('threshold', 0):.0f}, gift_product={prod}, tagged={data.get('tagged')}"
    if name == "loyalty":
        return f"earn/$={data.get('earn_per_dollar', 0)}, welcome_bonus={data.get('welcome_bonus', 0)}, tiers={data.get('tiers', 0)}"
    if name == "referral":
        return f"code={data.get('discount_code', '-')}, code_created={data.get('code_created')}"
    if name == "emails":
        return f"templates={data.get('template_count', 0)} ({', '.join(data.get('templates', []))})"
    if name == "payments":
        return f"active={data.get('active_count', 0)}, missing={data.get('missing_count', 0)}"
    return str(data)[:60]


# ── Database Commands ────────────────────────────────────────

def _import_registered_dbs() -> None:
    """Import DB modules so they call register_schema() at import time.
    Construct default instances to populate the registry for `db status`."""
    constructors: list[tuple[str, str]] = [
        ("core.memory.intelligence", "MemoryIntelligence"),
        ("core.brain.memory", "IntelligentMemory"),
        ("data_pipeline.store.db", "ShopAIDatabase"),
        ("core.system.ab_testing", "ABTestingFramework"),
        ("core.ai.experience", "ExperienceAccumulator"),
        ("core.data.architecture", "DataArchitecture"),
        ("data_pipeline.tracking.event_collector", "EventCollector"),
        ("data_pipeline.tracking.price_history", "PriceHistory"),
        ("core.system.store_registry", "StoreRegistry"),
        ("models.rl.pricing_agent", "PricingAgent"),
    ]
    for module_name, class_name in constructors:
        try:
            module = __import__(module_name, fromlist=[class_name])
            getattr(module, class_name)()
        except Exception:  # noqa: BLE001
            pass


def _cmd_db_status() -> None:
    from core.db.migrations import get_all_schema_info
    _import_registered_dbs()
    infos = get_all_schema_info()
    if not infos:
        print("No databases registered.")
        return
    print(f"{'NAME':25s} {'VERSION':12s} {'STATUS':12s} PATH")
    print("-" * 80)
    for info in infos:
        ver = f"v{info['current_version']}/{info['target_version']}"
        print(f"{info['name']:25s} {ver:12s} {info['status']:12s} {info['path']}")


def _cmd_db_migrate() -> None:
    # Construction triggers Migrator.run() automatically — status shows result.
    print("Running pending migrations...")
    _import_registered_dbs()
    _cmd_db_status()


def _cmd_db_backup(out_path: str | None) -> None:
    """Snapshot the entire ``data/`` directory to a tar.gz.

    Default output filename: ``shopai-backup-YYYYMMDD-HHMMSS.tar.gz``
    (UTC). Refuses to overwrite an existing file — operators may
    mistype and clobber a prior snapshot.
    """
    import datetime
    import tarfile
    from pathlib import Path

    data_dir = Path("data")
    if not data_dir.exists():
        print(f"Error: no data directory at {data_dir.resolve()}")
        sys.exit(1)

    if out_path is None:
        ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        out_path = f"shopai-backup-{ts}.tar.gz"
    out_file = Path(out_path)
    if out_file.exists():
        print(
            f"Error: {out_file} already exists. "
            "Pick a different --out path or remove the existing file."
        )
        sys.exit(1)
    try:
        with tarfile.open(out_file, "w:gz") as tar:
            tar.add(data_dir, arcname="data")
    except OSError as exc:
        print(f"Error: backup failed: {exc}")
        sys.exit(1)

    size_bytes = out_file.stat().st_size
    size = (
        f"{size_bytes / 1024:.1f}KB"
        if size_bytes < 1024 * 1024
        else f"{size_bytes / (1024 * 1024):.1f}MB"
    )
    print(f"Backup written: {out_file} ({size})")
    print(f"Restore with: shopai db restore {out_file}")


def _cmd_db_restore(archive: str, yes: bool = False) -> None:
    """Restore data/ from a backup tarball.

    Current data/ moves to ``data.<UTC ts>.bak/`` before extract
    so a wrong-tarball recovery is still possible. Refuses
    without ``--yes``.
    """
    import datetime
    import shutil
    import tarfile
    from pathlib import Path

    archive_path = Path(archive)
    if not archive_path.exists():
        print(f"Error: archive not found: {archive_path}")
        sys.exit(1)
    if not yes:
        print(
            f"Restore will REPLACE the contents of data/ with the "
            f"tarball {archive_path.name}.\n"
            "Current data/ will be moved aside (not deleted) first.\n"
            "Re-run with --yes to confirm."
        )
        sys.exit(1)

    data_dir = Path("data")
    if data_dir.exists():
        ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        backup_dir = Path(f"data.{ts}.bak")
        if backup_dir.exists():
            print(f"Error: {backup_dir} already exists; aborting")
            sys.exit(1)
        try:
            shutil.move(str(data_dir), str(backup_dir))
        except OSError as exc:
            print(f"Error: could not move data/ aside: {exc}")
            sys.exit(1)
        print(f"Moved current data/ → {backup_dir}")

    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(".")
    except (tarfile.TarError, OSError) as exc:
        print(f"Error: extract failed: {exc}")
        sys.exit(1)

    if not data_dir.exists():
        print("Error: restore completed but data/ not present.")
        sys.exit(1)

    file_count = sum(1 for p in data_dir.rglob("*") if p.is_file())
    print(f"Restored data/ from {archive_path.name} ({file_count} files)")


def _cmd_goal(args) -> None:
    """Dispatcher for ``shopai goal {show, reset}``."""
    action = getattr(args, "goal_action", None)
    if action == "show":
        _cmd_goal_show()
        return
    if action == "reset":
        _cmd_goal_reset(args)
        return
    print(
        "Usage:\n"
        "  shopai goal show\n"
        "  shopai goal reset [--yes]"
    )
    sys.exit(1)


def _cmd_goal_show() -> None:
    """Current goal + per-goal effectiveness EMA snapshot."""
    try:
        from core.goals.goal_feedback import _default_manager
    except Exception as exc:
        print(f"Error: goal manager unavailable: {exc}")
        sys.exit(1)
    manager = _default_manager()
    if manager is None:
        print("Goal manager not configured.")
        sys.exit(1)
    current = manager.get_current_goal()
    stats = manager.get_effectiveness_stats()
    print(f"Current goal:   {current}\n")
    if not stats:
        print(
            "Per-goal EMA: (no recorded outcomes yet — all goals "
            "use the neutral default of 0.50)"
        )
        return
    print("Per-goal EMA (effectiveness × sample count):")
    col = 10
    print(f"  {'goal':<24}{'EMA':>{col}}{'samples':>{col}}")
    print(f"  {'-' * (24 + col * 2)}")
    rows = sorted(
        stats.items(),
        key=lambda kv: kv[1]["effectiveness"],
        reverse=True,
    )
    for goal, s in rows:
        print(
            f"  {goal:<24}{s['effectiveness']:>{col}.2f}"
            f"{s['n']:>{col}d}"
        )


def _cmd_goal_reset(args) -> None:
    """Clear the persisted per-goal EMA state."""
    if not getattr(args, "yes", False):
        print(
            "Reset will wipe per-goal EMA stats (the brain stack's "
            "learned signal). Re-run with --yes to confirm:\n"
            "  shopai goal reset --yes"
        )
        sys.exit(1)
    from pathlib import Path
    try:
        from core.goals.goal_manager import _DEFAULT_STATE_PATH
        from core.goals.goal_feedback import _default_manager
    except Exception as exc:
        print(f"Error: goal manager unavailable: {exc}")
        sys.exit(1)
    manager = _default_manager()
    if manager is not None:
        with manager._lock:
            manager._goal_stats.clear()
        manager._save_state()
    state_path = Path(_DEFAULT_STATE_PATH)
    if state_path.exists():
        try:
            state_path.unlink()
        except OSError as exc:
            print(f"Warning: could not remove {state_path}: {exc}")
    print("Per-goal EMA stats cleared.")


def _cmd_db_info() -> None:
    """Inventory every file under ``data/``.

    For each file:
      - size (human-friendly)
      - mtime (age in seconds → human-friendly)
      - row count for SQLite databases (sum across user tables)
      - top-level entry count for JSON files

    Useful for "what state does ShopAI persist?" + "is anything
    growing or stale?" questions an operator might ask without
    digging into individual modules.
    """
    import sqlite3
    from pathlib import Path

    data_dir = Path("data")
    if not data_dir.exists():
        print(f"No data directory at {data_dir.resolve()}")
        return

    files = sorted(data_dir.iterdir())
    files = [f for f in files if f.is_file()]
    if not files:
        print(f"No state files under {data_dir.resolve()}")
        return

    now = time.time()

    def _fmt_size(n: int) -> str:
        if n < 1024:
            return f"{n}B"
        if n < 1024 * 1024:
            return f"{n / 1024:.1f}KB"
        if n < 1024 * 1024 * 1024:
            return f"{n / (1024 * 1024):.1f}MB"
        return f"{n / (1024 ** 3):.1f}GB"

    def _fmt_age(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            return f"{int(seconds / 60)}m"
        if seconds < 86400:
            return f"{int(seconds / 3600)}h"
        return f"{int(seconds / 86400)}d"

    def _sqlite_row_count(p: Path) -> int | None:
        try:
            with sqlite3.connect(str(p)) as conn:
                cur = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                total = 0
                for (table,) in cur.fetchall():
                    try:
                        n = conn.execute(
                            f"SELECT COUNT(*) FROM {table}"
                        ).fetchone()[0]
                        total += int(n or 0)
                    except sqlite3.Error:
                        continue
                return total
        except sqlite3.Error:
            return None

    def _json_entries(p: Path) -> int | None:
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return len(data)
            if isinstance(data, list):
                return len(data)
            return None
        except (OSError, ValueError):
            return None

    print(f"ShopAI data files in {data_dir.resolve()}\n")
    print(
        f"  {'FILE':<28} {'SIZE':>8} {'AGE':>6}  ROWS / ENTRIES"
    )
    print(f"  {'-' * 28} {'-' * 8} {'-' * 6}  {'-' * 16}")
    total_size = 0
    for f in files:
        st = f.stat()
        total_size += st.st_size
        age_s = now - st.st_mtime
        rows: str = "-"
        if f.suffix == ".db":
            n = _sqlite_row_count(f)
            if n is not None:
                rows = f"{n:,} rows"
        elif f.suffix == ".json":
            n = _json_entries(f)
            if n is not None:
                rows = f"{n} entries"
        print(
            f"  {f.name:<28} {_fmt_size(st.st_size):>8} "
            f"{_fmt_age(age_s):>6}  {rows}"
        )
    print(f"\n  Total: {len(files)} files, {_fmt_size(total_size)}")


# ── Config Commands ──────────────────────────────────────────

def _cmd_config_check() -> int:
    """Validate config and print issues. Returns exit code (0 = ok)."""
    from infrastructure.config.schema import check_env_file, validate_config
    env_warning = check_env_file()
    if env_warning:
        print(f"WARNING: {env_warning}")
        print()

    result = validate_config()

    for err in result.errors:
        print(f"ERROR:   {err}")
    for warn in result.warnings:
        print(f"WARNING: {warn}")

    if result.ok() and not result.warnings and not env_warning:
        print("OK: configuration is valid")
    elif result.ok():
        print()
        print(f"OK: no errors ({len(result.warnings)} warning(s))")
    else:
        print()
        print(f"FAILED: {len(result.errors)} error(s), {len(result.warnings)} warning(s)")

    return 0 if result.ok() else 1


def _cmd_config_show() -> None:
    from infrastructure.config.schema import get_config_report
    rows = get_config_report()
    # Fit to terminal
    name_w = max(len(r["name"]) for r in rows) + 2
    print(f"{'NAME':{name_w}s} {'TYPE':7s} {'SET':5s} {'VALUE':30s} DESCRIPTION")
    print("-" * min(120, name_w + 55 + 40))
    for r in rows:
        set_marker = "yes" if r["set"] else "no"
        value = r["value"]
        if len(value) > 30:
            value = value[:27] + "..."
        print(f"{r['name']:{name_w}s} {r['type']:7s} {set_marker:5s} {value:30s} {r['description']}")


# ── Cognitive Mind Commands ─────────────────────────────────

def _get_mind():
    """Lazily build the singleton Mind for CLI calls."""
    from core.cognitive.mind import get_mind
    return get_mind()


def _cmd_mind_status(args=None) -> None:
    """Print the AI's self-narrative + active goals + recent reflection."""
    mind = _get_mind()
    print()
    print("─" * 70)
    print("  COGNITIVE MIND — STATUS")
    print("─" * 70)
    if mind.self_model is not None:
        print()
        print("Self-narrative:")
        print(f"  {mind.self_model.narrative()}")
        strengths = mind.self_model.strengths(top_n=3)
        if strengths:
            print()
            print("Top strengths:")
            for s in strengths:
                print(f"  - {s['name']:30s} score={s['score']:.2f}  conf={s['confidence']:.2f}")
        weaknesses = mind.self_model.weaknesses(top_n=3)
        if weaknesses:
            print()
            print("Top weaknesses:")
            for w in weaknesses:
                print(f"  - {w['name']:30s} score={w['score']:.2f}  conf={w['confidence']:.2f}")
        gaps = mind.self_model.knowledge_gaps(top_n=3)
        if gaps:
            print()
            print("Knowledge gaps:")
            for g in gaps:
                print(f"  - {g['name']:30s} only {g['evidence_count']} obs")
    if mind.goal_manager is not None:
        active = mind.goal_manager.active(limit=10)
        print()
        print(f"Active goals ({len(active)}):")
        for g in active[:10]:
            print(f"  [{g['state']:11s}] priority={g['priority']:.2f}  {g['what']}")
    print()
    print(f"Total cycles run: {mind.cycle_count()}")
    _print_mind_calibration_summary(mind)
    _print_mind_llm_summary()
    print()


def _print_mind_calibration_summary(mind) -> None:
    """Render the latest self-calibration scores so the operator
    can see at a glance whether the Mind's predictions match
    reality."""
    try:
        snap = mind.calibration_snapshot()
    except Exception:
        return

    img = snap.get("last_imagination_calibration")
    pred = snap.get("last_prediction_calibration")
    history_size = snap.get("history_size", 0)

    if img is None and pred is None and history_size == 0:
        return

    print()
    print("Calibration:")
    print(f"  cycle journal size: {history_size}")
    if img is None:
        print("  imagination: (not yet calibrated)")
    else:
        print(f"  imagination: {img:.2f}  ({_calibration_label(img)})")
    if pred is None:
        print("  prediction:  (not yet calibrated)")
    else:
        print(f"  prediction:  {pred:.2f}  ({_calibration_label(pred)})")


def _calibration_label(score: float) -> str:
    if score >= 0.8:
        return "well-calibrated"
    if score >= 0.6:
        return "acceptable"
    if score >= 0.4:
        return "drift"
    return "miscalibrated"


def _print_mind_llm_summary() -> None:
    """Render a compact LLM stats block (provider + cache) for `mind status`."""
    try:
        from core.system.llm_adapter import get_llm
        llm = get_llm()
        stats = llm.get_stats()
    except Exception as exc:
        print()
        print(f"LLM: unavailable ({exc})")
        return

    configured = stats.get("configured", []) or []
    available = stats.get("available_local", []) or []
    models = stats.get("models", {}) or {}
    fallback = stats.get("fallback_chain", []) or []

    total_calls = sum(int(s.get("calls", 0)) for s in models.values())
    total_errors = sum(int(s.get("errors", 0)) for s in models.values())
    total_tokens = sum(int(s.get("tokens", 0)) for s in models.values())
    total_fallbacks = sum(int(s.get("fallbacks", 0)) for s in models.values())

    print()
    print("LLM:")
    if not configured:
        print("  no providers configured")
    else:
        print(f"  providers={len(configured)}  local={len(available)}"
              f"  fallback_chain={' → '.join(fallback) if fallback else '(none)'}")
        print(f"  calls={total_calls}  errors={total_errors}"
              f"  tokens={total_tokens}  fallbacks_used={total_fallbacks}")

    try:
        from core.system.llm_cache import get_llm_cache
        cache = get_llm_cache()
        c = cache.stats().to_dict()
        hit_pct = c.get("hit_rate", 0.0) * 100.0
        print(
            f"  cache: size={c.get('size', 0)}/{c.get('max_entries', 0)}"
            f"  hits={c.get('hits', 0)}  misses={c.get('misses', 0)}"
            f"  hit_rate={hit_pct:.1f}%"
        )
    except Exception:
        pass


def _cmd_mind_cycle(args=None) -> None:
    """Run one cognitive cycle and print the report."""
    mind = _get_mind()
    print("Running cognitive cycle...")
    report = mind.run_cycle()

    print()
    print("─" * 70)
    print(f"  CYCLE {report.cycle_number} — {report.duration_s():.3f}s")
    print("─" * 70)
    if report.error:
        print(f"  ERROR: {report.error}")
        return

    if report.reflection:
        print()
        print("Reflection:")
        print(f"  episodes reviewed: {report.reflection.episodes_reviewed}")
        print(f"  lessons:           {len(report.reflection.lessons)}")
        for lesson in report.reflection.lessons[:5]:
            print(f"    [{lesson.type}] {lesson.evidence[:80]}")

    if report.goals_proposed:
        print()
        print(f"Goals proposed this cycle: {len(report.goals_proposed)}")
        for gid in report.goals_proposed:
            g = mind.goal_manager.get(gid) if mind.goal_manager else None
            if g:
                print(f"  {gid[:14]} priority={g['priority']:.2f}  {g['what']}")

    if report.selected_goal_id:
        g = mind.goal_manager.get(report.selected_goal_id) if mind.goal_manager else None
        if g:
            print()
            print(f"Selected goal: {g['what']}")

    if report.plan:
        print()
        print(f"Plan ({report.plan.backend}, {report.plan.step_count()} steps):")
        for i, step in enumerate(report.plan.steps[:10], 1):
            print(f"  {i}. {step.description}")

    if report.imagined_plan:
        print()
        print(
            f"Imagined: expected_score={report.imagined_plan.expected_score:.2f}, "
            f"cost={report.imagined_plan.expected_cost:.2f}, "
            f"confidence={report.imagined_plan.overall_confidence:.2f}"
        )

    if report.predictions:
        print()
        print(f"Agent predictions ({len(report.predictions)}):")
        for p in report.predictions[:5]:
            print(
                f"  [{p.agent_id}] for '{p.action_proposed[:40]}' → "
                f"{p.predicted_response} (conf {p.confidence:.2f})"
            )

    if report.actions_taken:
        print()
        print(f"Actions ({len(report.actions_taken)}):")
        for a in report.actions_taken:
            kind = a.get("kind", "?")
            if kind == "skill":
                print(f"  skill: {a.get('skill', '?')}")
            else:
                print(f"  recommendation: {a.get('description', '')[:60]}")

    if report.consolidation_ran:
        print()
        print("Memory consolidation: ran this cycle")

    if report.notes:
        print()
        print("Notes:")
        for n in report.notes:
            print(f"  - {n}")
    print()


def _cmd_mind_reflect(args=None) -> None:
    """Force a reflection pass without running a full cycle."""
    mind = _get_mind()
    if mind.reflection is None:
        print("No reflection module wired into the Mind.")
        return
    report = mind.reflection.reflect(apply=True)
    print()
    print("Reflection report:")
    print(f"  episodes reviewed:    {report.episodes_reviewed}")
    print(f"  lessons:              {len(report.lessons)}")
    print(f"  self_model updates:   {report.self_model_updates}")
    print(f"  goal revisions:       {report.goal_revisions}")
    print()
    if report.lessons:
        print("Lessons:")
        for lesson in report.lessons:
            print(f"  [{lesson.type}] {lesson.evidence}")
            if lesson.recommended_action:
                print(f"    → {lesson.recommended_action}")
    print()
    print(f"NARRATIVE: {report.narrative}")
    print()


def _cmd_mind_goals(args=None) -> None:
    """List active goals (proposed + active + in_progress)."""
    mind = _get_mind()
    if mind.goal_manager is None:
        print("No goal manager wired into the Mind.")
        return
    goals = mind.goal_manager.active(limit=50)
    if not goals:
        print("No active goals.")
        return
    print()
    print(f"{'ID':14s} {'STATE':12s} {'PRIORITY':9s} WHAT")
    print("-" * 80)
    for g in goals:
        print(
            f"{g['id'][:14]:14s} {g['state']:12s} "
            f"{g['priority']:9.2f} {g['what'][:50]}"
        )
    print()
    print(f"Total: {len(goals)}")
    print()


def _cmd_mind_skills(args=None) -> None:
    """List registered skills."""
    mind = _get_mind()
    if mind.skill_registry is None:
        print("No skill registry wired into the Mind.")
        return
    skills = mind.skill_registry.list_skills()
    if not skills:
        print("No skills registered.")
        return
    print()
    print(f"{'NAME':25s} {'STATE':14s} {'ACCURACY':10s} USES")
    print("-" * 70)
    for s in skills:
        print(
            f"{s.name[:25]:25s} {s.state:14s} "
            f"{s.accuracy:10.2f} {s.use_count}"
        )
    print()
    stats = mind.skill_registry.stats()
    print(f"Total: {stats['total']}, validated: {stats['validated']}, "
          f"avg accuracy: {stats['avg_accuracy']:.2f}")
    print()


def _cmd_mind_explain(args) -> None:
    """Explain a goal: show its plan + imagined outcome."""
    mind = _get_mind()
    if mind.goal_manager is None:
        print("No goal manager wired into the Mind.")
        return
    goal = mind.goal_manager.get(args.goal_id)
    if goal is None:
        print(f"Goal {args.goal_id!r} not found.")
        return

    print()
    print("─" * 70)
    print(f"  GOAL: {goal['what']}")
    print("─" * 70)
    print(f"  id:         {goal['id']}")
    print(f"  state:      {goal['state']}")
    print(f"  source:     {goal.get('source') or '(manual)'}")
    print(f"  priority:   {goal['priority']:.2f}")
    print(f"  impact:     {goal['impact']:.2f}")
    print(f"  urgency:    {goal['urgency']:.2f}")
    print(f"  confidence: {goal['confidence']:.2f}")
    print(f"  cost:       {goal['cost']:.2f}")
    print(f"  progress:   {goal['progress']:.0%}")
    if goal.get("why"):
        print(f"  why:        {goal['why']}")

    if mind.planner is not None:
        plan = mind.planner.plan(goal)
        print()
        print(f"Plan ({plan.backend}, {plan.step_count()} steps):")
        for i, step in enumerate(plan.steps, 1):
            print(f"  {i}. {step.description}")
            if step.rationale:
                print(f"      ↳ {step.rationale[:60]}")

        if mind.imagination is not None:
            imagined = mind.imagination.imagine_plan(plan)
            print()
            print(
                f"Imagined: score={imagined.expected_score:.2f}, "
                f"cost={imagined.expected_cost:.2f}, "
                f"confidence={imagined.overall_confidence:.2f}"
            )

    children = mind.goal_manager.children(goal["id"])
    if children:
        print()
        print(f"Sub-goals ({len(children)}):")
        for c in children:
            print(f"  [{c['state']}] {c['what']}")

    events = mind.goal_manager.events(goal["id"], limit=10)
    if events:
        print()
        print(f"Recent events ({len(events)}):")
        for e in events[:5]:
            print(f"  {e['event_type']:14s} {e['old_value']} → {e['new_value']}")
    print()


def _cmd_mind_think(args) -> None:
    """Ad-hoc free-form question through the cognitive context.

    Builds a `self_context` block from the SelfModel narrative +
    top goals, renders the `mind.think` prompt template, and asks
    the LLM via the requested role.
    """
    question = " ".join(args.question).strip()
    if not question:
        print("Empty question; nothing to think about.")
        return

    mind = _get_mind()

    # Build the context block
    context_parts: list[str] = []
    if not args.no_context:
        if mind.self_model is not None:
            try:
                narrative = mind.self_model.narrative()
                if narrative and "no data" not in narrative.lower():
                    context_parts.append(f"Who I am: {narrative}")
            except Exception:  # noqa: BLE001
                pass
        if mind.goal_manager is not None:
            try:
                active = mind.goal_manager.active(limit=5)
                if active:
                    goal_lines = "\n".join(
                        f"  - {g['what']} (priority {g['priority']:.2f})"
                        for g in active[:5]
                    )
                    context_parts.append(f"Current goals:\n{goal_lines}")
            except Exception:  # noqa: BLE001
                pass

    self_context = "\n\n".join(context_parts)
    if self_context:
        self_context = self_context + "\n\n"

    # Render via the prompt library
    try:
        from core.system.prompt_library import render_prompt
    except Exception:
        print("PromptLibrary not available.")
        return

    rendered = render_prompt(
        "mind.think",
        self_context=self_context,
        question=question,
    )
    if rendered is None:
        print("mind.think prompt template missing.")
        return

    # Resolve the LLM
    try:
        from core.system.llm_adapter import get_llm
        llm = get_llm()
    except Exception:
        print("LLM adapter not available.")
        return

    if not llm.is_available():
        print(
            "No LLM providers configured. Set SHOPAI_OLLAMA_URL or "
            "OPENAI_API_KEY or ANTHROPIC_API_KEY to enable thinking."
        )
        return

    print()
    print(f"Q: {question}")
    print()
    print("...thinking...")

    response = llm.ask(
        role=args.role,
        prompt=rendered.user,
        system_prompt=rendered.system,
    )

    print()
    if not response.success:
        print(f"LLM error: {response.error}")
        return
    print(response.text.strip())
    print()
    print(
        f"  ({response.provider}/{response.model}, "
        f"{response.tokens_used} tokens, {response.duration_s:.2f}s"
        f"{', via fallback' if response.fallback_used else ''})"
    )


def _cmd_mind_llm_status(args=None) -> None:
    """Show LLM provider availability and stats."""
    try:
        from core.system.llm_adapter import get_llm
        llm = get_llm()
    except Exception as exc:
        print(f"LLM adapter unavailable: {exc}")
        return

    info = llm.auto_configure() if not llm._checked else None
    stats = llm.get_stats()

    print()
    print("─" * 70)
    print("  LLM PROVIDER STATUS")
    print("─" * 70)
    print()
    print(f"Configured providers ({len(stats['configured'])}):")
    for name in stats["configured"]:
        cfg = llm._configs.get(name)
        if cfg:
            print(f"  - {name:25s} {cfg.provider}/{cfg.model}")
    print()
    print(f"Local Ollama models: {', '.join(stats['available_local']) or '(none)'}")
    print()
    print("Role mapping:")
    for role, model in sorted(stats["role_map"].items()):
        print(f"  {role:12s} → {model}")
    print()
    print(f"Fallback chain: {' → '.join(stats['fallback_chain'])}")
    print()
    if stats["models"]:
        print("Per-model stats:")
        for model, s in sorted(stats["models"].items()):
            avg_lat = s["total_time"] / s["calls"] if s["calls"] else 0
            print(
                f"  {model:25s} calls={s['calls']:4d} "
                f"errors={s['errors']:3d} "
                f"tokens={s['tokens']:6d} "
                f"avg={avg_lat:.2f}s"
            )
    else:
        print("Per-model stats: (no calls yet)")
    print()


# ── Sync Commands ────────────────────────────────────────────

def _cmd_sync(args) -> None:
    sm = _get_store_manager()
    from data_pipeline.store.sync_service import SyncService
    sync = SyncService(sm)

    if args.auto:
        print(f"Starting auto-sync (every {args.interval}s)...")
        print("Press Ctrl+C to stop.\n")
        sync.start_auto_sync(args.interval)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sync.stop_auto_sync()
            print("\nAuto-sync stopped.")
        return

    store_id = args.store_id or sm.active_store_id
    if not store_id:
        print("No store selected.")
        return

    print(f"Syncing {store_id}...")
    result = sync.sync_store(store_id)
    if result.get("status") == "success":
        synced = result.get("synced", {})
        print(f"✓ Sync complete ({result.get('duration_s', 0):.1f}s)")
        for dtype, info in synced.items():
            count = info.get("count", 0)
            errors = info.get("errors", []) or info.get("error", "")
            status = f"{count} records" if not errors else f"{count} records (errors: {errors})"
            print(f"  {dtype}: {status}")
    else:
        print(f"✗ Sync failed: {result.get('error', 'unknown')}")


# ── Engine Commands ──────────────────────────────────────────

def _cmd_engines(*, by_goal: bool = False, unmapped: bool = False) -> None:
    from engines.registry import engine_count, list_engines

    engines = list_engines()

    if unmapped:
        # Show only engines absent from ENGINE_GOAL_MAP.
        from core.goals.engine_goal_map import ENGINE_GOAL_MAP
        without_goal = [
            name for name in engines if name not in ENGINE_GOAL_MAP
        ]
        if not without_goal:
            print("All registered engines have a primary-goal mapping.")
            return
        print(
            f"Unmapped engines ({len(without_goal)} of "
            f"{len(engines)} registered):"
        )
        for i, name in enumerate(without_goal, 1):
            print(f"  {i:3d}. {name}")
        return

    if by_goal:
        # Group by primary goal. Engines not in ENGINE_GOAL_MAP land
        # under "unmapped" so the operator can see what's not yet
        # attributable to brain-stack EMA.
        from core.goals.engine_goal_map import ENGINE_GOAL_MAP

        by: dict[str, list[str]] = {}
        for name in engines:
            goal = ENGINE_GOAL_MAP.get(name, "unmapped")
            by.setdefault(goal, []).append(name)

        # Stable order: known goals alphabetical, "unmapped" last.
        ordered_goals = sorted(g for g in by if g != "unmapped")
        if "unmapped" in by:
            ordered_goals.append("unmapped")

        print(f"Registered engines: {engine_count()} (grouped by goal)\n")
        for goal in ordered_goals:
            engines_for = by[goal]
            print(f"{goal} ({len(engines_for)}):")
            for name in sorted(engines_for):
                print(f"  {name}")
            print()
        return

    print(f"Registered engines: {engine_count()}\n")
    for i, name in enumerate(engines, 1):
        print(f"  {i:3d}. {name}")


def _cmd_engine_info(engine_name: str, as_json: bool = False) -> None:
    from engines.registry import get_engine
    try:
        engine = get_engine(engine_name)
    except KeyError:
        if as_json:
            print(json.dumps({
                "error": f"Unknown engine: {engine_name}"
            }))
        else:
            print(f"Unknown engine: {engine_name}")
        sys.exit(1)
    if engine is None:
        if as_json:
            print(json.dumps({
                "error": f"Unknown engine: {engine_name}"
            }))
        else:
            print(f"Unknown engine: {engine_name}")
        sys.exit(1)

    name = getattr(
        engine, "ENGINE_NAME",
        getattr(engine, "engine_name", engine_name),
    )
    payload = {
        "name": name,
        "class": engine.__class__.__name__,
        "inputs": getattr(engine, "required_input_fields", []),
        "outputs": getattr(engine, "required_output_fields", []),
    }

    if as_json:
        print(json.dumps(payload, indent=2, default=str))
        return

    print(f"Engine: {payload['name']}")
    print(f"Class:  {payload['class']}")
    if payload["inputs"]:
        print(f"Inputs: {payload['inputs']}")
    if payload["outputs"]:
        print(f"Outputs: {payload['outputs']}")

    _print_engine_brain_stack(engine_name)


def _cmd_engine_calibration(args) -> None:
    """Render an engine's confidence-bucket calibration.

    A well-calibrated engine produces high outcome_score in
    high-confidence buckets and low outcome_score in low-
    confidence buckets — i.e. confidence actually means something.
    A miscalibrated engine (inverted or flat shape) is a signal
    operators need to act on:
      - Inverted: high-confidence actions worse than mid → the
        engine's internal scoring is broken or systematically
        overconfident on a specific failure mode.
      - Flat: confidence carries no information about outcome —
        the MIN_CONFIDENCE floor in auto-approve does nothing
        useful.

    The summary line ("Calibration: well-calibrated / inverted /
    insufficient data") gives operators an at-a-glance verdict
    backed by the bucketed numbers.
    """
    from core.approval import get_approval_queue

    try:
        queue = get_approval_queue()
        result = queue.engine_confidence_calibration(
            args.engine_name,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engine calibration lookup raised: %s", exc,
        )
        if getattr(args, "json", False):
            print(json.dumps({
                "engine": args.engine_name,
                "buckets": [],
                "monotonic_increasing": None,
                "error": str(exc),
            }, indent=2))
        else:
            print(f"Calibration unavailable for {args.engine_name}")
        return

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, default=str))
        return

    buckets = result["buckets"]
    monotonic = result["monotonic_increasing"]
    rendered_buckets = [b for b in buckets if b["action_count"]]

    print(f"Confidence calibration for engine: {args.engine_name}")
    print()

    if not rendered_buckets:
        print(
            "  (no actions with recorded confidence yet — "
            "engine has not enqueued actions or the queue is "
            "empty)"
        )
        return

    print(
        "  bucket       actions  positive  negative  score"
    )
    for b in rendered_buckets:
        score_display = (
            f"{b['outcome_score']:.2f}"
            if b['outcome_score'] is not None
            else "  -- "
        )
        print(
            f"  {b['label']:<11}  "
            f"{b['action_count']:>7}  "
            f"{b['positive_outcomes']:>8}  "
            f"{b['negative_outcomes']:>8}  "
            f"{score_display}"
        )

    print()
    if monotonic is True:
        print(
            "Calibration: well-calibrated "
            "(outcome score rises with confidence)"
        )
    elif monotonic is False:
        print(
            "Calibration: INVERTED — outcome score does not "
            "monotonically rise with confidence. The engine's "
            "self-assessment is unreliable; treat its "
            "confidence floor (e.g. auto-approve) with caution."
        )
    else:
        print(
            "Calibration: insufficient data "
            "(< 2 buckets with outcomes — need more history)"
        )


def _cmd_engines_calibration(args) -> None:
    """Calibration sweep across every engine.

    The companion to ``shopai engine-calibration <name>`` —
    where that's a deep-dive on one engine, this is a triage
    view across all of them. The highest-priority alert is an
    engine that's BOTH on the auto-approve allowlist AND
    miscalibrated: the operator has trusted it to auto-approve
    on confidence, but the calibration says that confidence
    floor isn't doing what it should.

    ``--miscalibrated-only`` filters to engines with inverted
    calibration — useful for "show me what needs attention."
    """
    from core.approval import get_approval_queue
    from core.approval.auto_approve import load_config as _aa_cfg

    try:
        queue = get_approval_queue()
        results = queue.all_engines_calibration()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engines calibration sweep raised: %s", exc,
        )
        results = {}

    try:
        allowlist = _aa_cfg().allowlist
    except Exception as exc:  # noqa: BLE001
        logger.debug("auto-approve allowlist probe failed: %s", exc)
        allowlist = frozenset()

    miscal_only = getattr(args, "miscalibrated_only", False)

    # Build row data with allowlist + verdict
    rows: list[dict[str, Any]] = []
    for engine, r in results.items():
        monotonic = r["monotonic_increasing"]
        if monotonic is True:
            verdict = "well-calibrated"
        elif monotonic is False:
            verdict = "INVERTED"
        else:
            verdict = "insufficient"

        action_count = sum(
            int(b.get("action_count", 0) or 0)
            for b in r.get("buckets", [])
        )
        rows.append({
            "engine": engine,
            "verdict": verdict,
            "monotonic_increasing": monotonic,
            "allowlisted": engine in allowlist,
            "action_count": action_count,
            # Surface a high-priority alert flag: an engine the
            # operator has trusted to auto-approve whose
            # confidence has stopped meaning anything.
            "miscalibrated_and_allowlisted": (
                monotonic is False and engine in allowlist
            ),
        })

    if miscal_only:
        rows = [r for r in rows if r["monotonic_increasing"] is False]

    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2, default=str))
        return

    if not rows:
        if miscal_only:
            print(
                "No miscalibrated engines — every engine with "
                "enough history has a monotonic calibration shape."
            )
        else:
            print(
                "No engines with confidence-tagged actions yet."
            )
        return

    # Sort: highest-priority alerts first
    #   1. miscalibrated AND allowlisted (RED)
    #   2. miscalibrated NOT allowlisted (YELLOW)
    #   3. insufficient data
    #   4. well-calibrated
    priority_rank = {
        "INVERTED": 0,
        "insufficient": 1,
        "well-calibrated": 2,
    }
    rows.sort(key=lambda r: (
        not r["miscalibrated_and_allowlisted"],
        priority_rank[r["verdict"]],
        r["engine"],
    ))

    print(f"Engine calibration sweep ({len(rows)} engines):")
    print()
    print(
        "  engine                          verdict           "
        "allowlist  actions"
    )
    for r in rows:
        # Visual prefix: '!' for the highest-priority alert,
        # space otherwise. Keeps the table grep-able while
        # surfacing the alert at the start of the line.
        prefix = "!" if r["miscalibrated_and_allowlisted"] else " "
        engine_label = r["engine"][:30]
        allow_label = "yes" if r["allowlisted"] else "no"
        print(
            f"{prefix} {engine_label:<30}  {r['verdict']:<16}  "
            f"{allow_label:<9}  {r['action_count']:>7}"
        )

    alerts = [r for r in rows if r["miscalibrated_and_allowlisted"]]
    if alerts:
        print()
        print(
            f"ALERT: {len(alerts)} engine(s) are auto-approved AND "
            "have inverted calibration. Consider disabling them "
            "via: shopai approvals auto-config --disable <engine>"
        )


def _cmd_engine_scorecard(args) -> None:
    """Render the unified engine scorecard.

    The capstone view: every per-engine signal in one screen.
    Eliminates the operator's need to bounce between
    ``approvals stats``, ``engine-calibration``,
    ``approvals pending-latency``, ``approvals decision-latency``,
    ``approvals rejection-rates``, ``approvals revenue-by-engine``,
    plus the governance config files. The scorecard pulls every
    signal from the queue + the auto-approve/quarantine state in
    a single render.
    """
    from core.approval import get_approval_queue

    try:
        queue = get_approval_queue()
        sc = queue.engine_scorecard(args.engine_name)
    except Exception as exc:  # noqa: BLE001
        logger.debug("engine_scorecard lookup raised: %s", exc)
        if getattr(args, "json", False):
            print(json.dumps({
                "engine": args.engine_name,
                "error": str(exc),
            }, indent=2))
        else:
            print(f"Scorecard unavailable for {args.engine_name}")
        return

    # Governance from the live config + state files (PR #161 /
    # #162) — these live outside the queue so we layer them on
    # top of the scorecard.
    try:
        from core.approval.auto_approve import load_config as _aa_cfg
        allowlist = _aa_cfg().allowlist
    except Exception as exc:  # noqa: BLE001
        logger.debug("auto-approve allowlist probe failed: %s", exc)
        allowlist = frozenset()
    try:
        from core.approval.quarantine import load_state as _q_state
        q_state = _q_state()
    except Exception as exc:  # noqa: BLE001
        logger.debug("quarantine state probe failed: %s", exc)
        q_state = None

    sc["governance"] = {
        "auto_approved": args.engine_name in allowlist,
        "quarantine_exempt": (
            q_state.is_exempt(args.engine_name)
            if q_state is not None else False
        ),
        "quarantine_released": (
            q_state.is_released(args.engine_name)
            if q_state is not None else False
        ),
    }

    if getattr(args, "json", False):
        print(json.dumps(sc, indent=2, default=str))
        return

    # ── Text render ──────────────────────────────────────
    print(f"Scorecard: {sc['engine']}")
    print()

    # Volume
    v = sc["volume"]
    decided = (
        v["approved"] + v["rejected"]
        + v["executed"] + v["failed"]
    )
    print("Volume:")
    print(
        f"  pending: {v['pending']:<4}  "
        f"approved: {v['approved']:<4}  "
        f"executed: {v['executed']:<4}"
    )
    print(
        f"  rejected: {v['rejected']:<3}  "
        f"failed:   {v['failed']:<4}  "
        f"expired:  {v['expired']:<3}  "
        f"(decided: {decided})"
    )

    # Outcomes
    o = sc["outcomes"]
    print()
    print("Outcomes:")
    if o.get("total_outcomes", 0) == 0:
        print("  (no matched outcomes yet)")
    else:
        score = o.get("outcome_score")
        score_display = f"{score:.2f}" if score is not None else "--"
        print(
            f"  positive: {o['positive_count']:<3}  "
            f"negative: {o['negative_count']:<3}  "
            f"neutral: {o['neutral_count']:<3}  "
            f"score: {score_display}"
        )

    # Calibration
    monotonic = sc["calibration"].get("monotonic_increasing")
    if monotonic is True:
        cal_verdict = "well-calibrated"
    elif monotonic is False:
        cal_verdict = "INVERTED"
    else:
        cal_verdict = "insufficient data"
    print()
    print(f"Calibration: {cal_verdict}")

    # Workflow
    pending = sc["workflow"]["pending"]
    decision = sc["workflow"]["decision"]
    print()
    print("Workflow:")
    if pending.get("pending_count", 0) > 0:
        print(
            f"  pending: {pending['pending_count']} action(s); "
            f"oldest {_format_age(pending['oldest_age_seconds'])}, "
            f"median {_format_age(pending['median_age_seconds'])}"
        )
    else:
        print("  pending: (none)")
    if decision.get("decided_count", 0) > 0:
        print(
            f"  decision latency: {decision['decided_count']} "
            f"decisions; "
            f"median {_format_age(decision['median_seconds'])}, "
            f"slowest {_format_age(decision['slowest_seconds'])}"
        )
    else:
        print("  decision latency: (no decisions yet)")

    # Veto
    veto = sc["veto"]
    print()
    if veto["decided_count"] > 0:
        print(
            f"Veto: rejection_rate={veto['rejection_rate']:.2f} "
            f"({veto['rejected_count']}/{veto['decided_count']})"
        )
    else:
        print("Veto: (no decisions yet)")

    # Revenue
    r = sc["revenue"]
    per_pos = r.get("revenue_per_positive_outcome")
    per_pos_display = f"{per_pos:.2f}" if per_pos is not None else "--"
    print()
    print("Revenue:")
    print(
        f"  gross={r['gross_revenue']:.2f}  "
        f"refunded={r['refunded_revenue']:.2f}  "
        f"net={r['net_revenue']:.2f}  "
        f"per-positive={per_pos_display}"
    )

    # Governance
    g = sc["governance"]
    print()
    print("Governance:")
    auto_label = "yes" if g["auto_approved"] else "no"
    exempt_label = "yes" if g["quarantine_exempt"] else "no"
    released_label = "yes" if g["quarantine_released"] else "no"
    print(
        f"  auto-approve: {auto_label}  "
        f"quarantine-exempt: {exempt_label}  "
        f"manually-released: {released_label}"
    )

    # Headline summary line — turns the full table into a
    # one-line verdict an operator can grep
    miscalibrated_and_auto = (
        monotonic is False and g["auto_approved"]
    )
    if miscalibrated_and_auto:
        print()
        print(
            "ALERT: engine is auto-approved AND has inverted "
            "calibration. Consider disabling via "
            "`shopai approvals auto-config --disable "
            f"{sc['engine']}`."
        )


def _print_engine_brain_stack(engine_name: str) -> None:
    """Render brain-stack attribution + effectiveness for an engine.

    Best-effort: any failure (goal map missing, manager unavailable)
    skips its line rather than crashing engine-info.
    """
    try:
        from core.goals.engine_goal_map import ENGINE_GOAL_MAP
    except Exception as exc:
        logger.debug("engine_goal_map import failed: %s", exc)
        return

    goal = ENGINE_GOAL_MAP.get(engine_name)
    print()
    print("Brain stack:")
    if goal is None:
        print(
            "  Goal:           (unmapped — actions don't attribute "
            "to any goal)"
        )
        return
    print(f"  Goal:           {goal}")

    try:
        from core.goals.goal_manager import GoalManager
    except Exception as exc:
        logger.debug("GoalManager import failed: %s", exc)
        return
    try:
        stats = GoalManager().get_effectiveness_stats()
    except Exception as exc:
        logger.debug("effectiveness stats lookup failed: %s", exc)
        return

    goal_stats = stats.get(goal, {})
    ema = goal_stats.get("effectiveness")
    samples = goal_stats.get("n", 0)
    if ema is None:
        print(
            "  Effectiveness:  0.50 (default — no recorded outcomes yet)"
        )
    else:
        print(
            f"  Effectiveness:  {ema:.2f} (over {samples} recorded outcomes)"
        )

    # Per-engine outcome score — the recommender's tiebreaker
    # signal added in the per-engine aggregator PR. Direct
    # measurement of this engine's track record on real Shopify
    # outcomes (orders/refunds tied back via discount code or
    # product id).
    try:
        from core.approval import get_approval_queue
        outcome_stats = (
            get_approval_queue().engine_outcome_stats(engine_name)
        )
    except Exception as exc:
        logger.debug("engine outcome stats lookup failed: %s", exc)
        return

    score = outcome_stats.get("outcome_score")
    pos = outcome_stats.get("positive_count", 0)
    neg = outcome_stats.get("negative_count", 0)
    revenue = outcome_stats.get("total_revenue", 0.0)
    if score is None and pos == 0 and neg == 0:
        # No outcome data — show the line as "not measured" so the
        # operator distinguishes "untested" from "measured at neutral".
        print(
            "  Outcome score:  (no matched outcomes yet)"
        )
    else:
        score_str = (
            f"{score:.2f}" if score is not None else "neutral"
        )
        print(
            f"  Outcome score:  {score_str} "
            f"({pos}+ / {neg}-, net ${revenue:,.2f})"
        )


def _cmd_run(args) -> None:
    sm = _get_store_manager()
    store_id = args.store or sm.active_store_id

    # Get data for engine
    from data_pipeline.store.data_provider import DataProvider
    provider = DataProvider(sm)
    data = provider.get_data_for_engine(args.task_type, store_id)

    # Merge user params
    user_params = json.loads(args.params)
    data.update(user_params)

    # Run engine
    from engines.registry import get_engine
    try:
        engine = get_engine(args.task_type)
    except KeyError:
        engine = None
    if engine is None:
        # Pre-PR: ``engine.run(data)`` crashed with
        # AttributeError on NoneType. Now: clean error + exit 1.
        print(
            f"Error: unknown engine: {args.task_type}\n"
            f"(see ``shopai engines`` for the registered list)"
        )
        sys.exit(1)

    print(f"Running {args.task_type} (data source: {data.get('source', 'unknown')})...\n")

    result = engine.run(data)
    print(json.dumps(result, indent=2, default=str))


def _cmd_suggest(args) -> None:
    """Goal × effectiveness → ranked engine recommendations.

    Two output formats:
      * Table (default) — human-readable rendering of the primary
        recommendations + optional alternatives.
      * JSON (``--json``) — raw ``RecommendationResult.to_dict()``
        for piping into other tools.
    """
    from core.brain.engine_recommender import recommend_engines

    result = recommend_engines(
        goal=args.goal,
        limit=args.limit,
        include_alternatives=not args.no_alternatives,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
        return

    print(f"Active goal: {result.active_goal}")
    if result.explanation:
        print(f"  {result.explanation}")
    print()

    if result.primary:
        print(f"Top picks (goal={result.active_goal}):")
        print(f"  {'rank':<4}  {'engine':<28} {'priority':<10} {'effectiveness':<14}")
        for i, r in enumerate(result.primary, 1):
            print(
                f"  {i:<4}  {r.engine:<28} "
                f"{r.priority:<10.2f} {r.effectiveness:<14.2f}"
            )
    else:
        print(f"No engines mapped to goal {result.active_goal!r}.")

    if result.alternatives and not args.no_alternatives:
        print()
        print("Alternatives (other goals — manual override):")
        print(f"  {'engine':<28} {'goal':<22} {'effectiveness':<14}")
        for r in result.alternatives:
            print(
                f"  {r.engine:<28} {r.goal:<22} "
                f"{r.effectiveness:<14.2f}"
            )


def _cmd_knowledge(args) -> None:
    """Knowledge-vault subcommand router.

    Verbs:
      * ``export`` — dump ShopAI state to an Obsidian-compatible
        Markdown vault.
      * ``digest`` — render a one-page insight briefing.
      * ``import`` — read operator notes back from the vault.
      * ``notes`` — inspect the persisted operator-notes store.
    """
    if args.knowledge_action == "export":
        _cmd_knowledge_export(args)
        return
    if args.knowledge_action == "digest":
        _cmd_knowledge_digest(args)
        return
    if args.knowledge_action == "import":
        _cmd_knowledge_import(args)
        return
    if args.knowledge_action == "notes":
        _cmd_knowledge_notes(args)
        return
    if args.knowledge_action == "set-notes":
        _cmd_knowledge_set_notes(args)
        return
    print(
        "Usage:\n"
        "  shopai knowledge export    <path> [--decision-limit N]\n"
        "  shopai knowledge digest    [--since N] [--limit M] "
        "[--out PATH]\n"
        "  shopai knowledge import    <path>\n"
        "  shopai knowledge notes     [engine|goal] [name]\n"
        "  shopai knowledge set-notes <engine|goal> <name> "
        "(--text TEXT | --from-file PATH)"
    )
    sys.exit(1)


def _cmd_knowledge_set_notes(args) -> None:
    """Add / update an operator note for an engine or goal.

    Two body sources:
      * ``--text "..."`` inline
      * ``--text -`` reads body from stdin
      * ``--from-file path`` reads body from a file

    Notes persist to ``data/operator_notes.json`` via NotesStore.
    Downstream consumers (digest, knowledge export, action review
    enrichment) read the same file — operator commentary surfaces
    without re-running the import flow.
    """
    kind = args.kind  # "engine" or "goal" (argparse-validated)
    name = (args.name or "").strip()
    if not name:
        print("Error: name is required")
        sys.exit(1)

    body = ""
    if args.text is not None:
        if args.text == "-":
            body = sys.stdin.read()
        else:
            body = args.text
    elif args.from_file:
        try:
            with open(args.from_file, encoding="utf-8") as f:
                body = f.read()
        except OSError as exc:
            print(f"Error: could not read {args.from_file}: {exc}")
            sys.exit(1)

    body = body.strip()
    if not body:
        print("Error: note body is empty")
        sys.exit(1)

    from core.knowledge import get_default_store

    store = get_default_store()
    if kind == "engine":
        store.set_engine_notes(name, body, source_path="cli")
    else:
        store.set_goal_notes(name, body, source_path="cli")

    preview = body.splitlines()[0][:60] if body.splitlines() else ""
    print(f"Saved {kind} note for {name!r}: {preview}{'...' if len(body) > 60 else ''}")


def _cmd_knowledge_export(args) -> None:
    from core.knowledge import ObsidianExporter

    exporter = ObsidianExporter(
        target_dir=args.target,
        decision_limit=args.decision_limit,
    )
    summary = exporter.export()
    print(f"Vault exported to: {exporter.target_dir}")
    print(f"  engines:   {summary.engines}")
    print(f"  goals:     {summary.goals}")
    print(f"  decisions: {summary.decisions}")
    if summary.skipped:
        print("  skipped:")
        for s in summary.skipped:
            print(f"    - {s}")
    if not summary.overview_written:
        print("  overview.md: NOT written (see skipped)")


def _cmd_knowledge_digest(args) -> None:
    from core.knowledge import InsightDigest

    digest = InsightDigest(
        since_days=args.since_days,
        decision_limit=args.decision_limit,
    )
    if args.out:
        stats = digest.write_to(args.out)
        print(f"Digest written to: {args.out}")
        print(
            f"  active_goal:    {stats.active_goal}\n"
            f"  decisions in window: {stats.decisions_window}\n"
            f"  cumulative executed/failed: "
            f"{stats.decisions_total_executed}/"
            f"{stats.decisions_total_failed}"
        )
        if stats.top_engine:
            print(f"  top engine in window: {stats.top_engine}")
    else:
        markdown, _stats = digest.render()
        print(markdown)


def _cmd_knowledge_import(args) -> None:
    """Walk the supplied vault and persist operator notes."""
    from core.knowledge import ObsidianImporter

    importer = ObsidianImporter()
    summary = importer.import_vault(args.source)
    print(f"Vault scanned: {args.source}")
    print(f"  files scanned:    {summary.files_scanned}")
    print(f"  files skipped:    {summary.files_skipped}")
    print(f"  engines imported: {summary.engines_imported}")
    print(f"  goals imported:   {summary.goals_imported}")
    if summary.skipped:
        print("  diagnostics:")
        for s in summary.skipped[:10]:
            print(f"    - {s}")
        if len(summary.skipped) > 10:
            print(f"    ...and {len(summary.skipped) - 10} more")
    print(f"  notes file: {importer.store.path}")


def _cmd_knowledge_notes(args) -> None:
    """Inspect the persisted operator-notes store.

    No args: list every (kind, name) with a one-line preview.
    ``engine``/``goal`` only: filter to that kind.
    ``engine cart_recovery``: print the full body for that entry.
    """
    from core.knowledge import get_default_store

    store = get_default_store()
    engines = store.all_engine_notes()
    goals = store.all_goal_notes()

    kind = getattr(args, "kind", None)
    name = getattr(args, "name", None)

    if kind == "engine" and name:
        text = store.get_engine_notes(name)
        if not text:
            print(f"No notes for engine {name!r}.")
            return
        print(f"# engine: {name}\n")
        print(text)
        return
    if kind == "goal" and name:
        text = store.get_goal_notes(name)
        if not text:
            print(f"No notes for goal {name!r}.")
            return
        print(f"# goal: {name}\n")
        print(text)
        return

    show_engines = kind in (None, "engine")
    show_goals = kind in (None, "goal")
    meta = store.meta()
    if meta:
        last = meta.get("last_import_at")
        src = meta.get("last_import_source", "")
        print(f"Notes file: {store.path}")
        print(
            f"  last import: {last} from {src}  "
            f"({meta.get('imported_count', 0)} entries)"
        )
        print()

    def _preview(text: str) -> str:
        first = (text or "").strip().splitlines()
        return first[0][:80] if first else ""

    if show_engines:
        print(f"Engines ({len(engines)}):")
        if not engines:
            print("  _(none — run 'shopai knowledge import <vault>')_")
        for engine, entry in sorted(engines.items()):
            print(f"  - {engine:30s}  {_preview(entry.get('notes', ''))}")
        print()
    if show_goals:
        print(f"Goals ({len(goals)}):")
        if not goals:
            print("  _(none)_")
        for goal, entry in sorted(goals.items()):
            print(f"  - {goal:30s}  {_preview(entry.get('notes', ''))}")


# ── Action Commands ──────────────────────────────────────────

def _cmd_actions(args) -> None:
    from execution.action_executor import ActionExecutor
    executor = ActionExecutor(_get_store_manager())

    if args.action_cmd == "pending":
        pending = executor.get_pending()
        if not pending:
            print("No pending actions.")
            return
        print(f"Pending actions ({len(pending)}):\n")
        for a in pending:
            print(f"  [{a['id']}] {a['type']} — {a.get('reason', '')[:60]}")
            print(f"    Store: {a['store_id']} | Confidence: {a.get('confidence', 0)}")
            print()

    elif args.action_cmd == "approve":
        result = executor.approve_action(args.action_id)
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print(f"✓ Action {args.action_id} executed: {result.get('status')}")

    elif args.action_cmd == "approve-all":
        results = executor.approve_all()
        print(f"✓ Approved {len(results)} actions")

    elif args.action_cmd == "reject":
        result = executor.reject_action(args.action_id, args.reason)
        print(f"✓ Action {args.action_id} rejected")

    elif args.action_cmd == "log":
        log = executor.get_action_log()
        if not log:
            print("No actions executed yet.")
            return
        for a in log[-20:]:
            status = a.get("status", "?")
            icon = "✓" if status == "executed" else "✗" if status == "failed" else "⊘"
            print(f"  {icon} [{a.get('id', '?')}] {a['type']} — {status}")

    elif args.action_cmd == "stats":
        stats = executor.get_stats()
        print("Action Stats:")
        print(f"  Pending:   {stats['pending']}")
        print(f"  Executed:  {stats['executed']}")
        print(f"  Failed:    {stats['failed']}")
        print(f"  Rejected:  {stats['rejected']}")
        print(f"  Auto-approve: {stats['auto_approve']}")

    else:
        print("Usage: shopai actions {pending|approve|approve-all|reject|log|stats}")


# ── Autonomous Commands ──────────────────────────────────────

def _cmd_auto(args) -> None:
    sm = _get_store_manager()
    from core.autonomous.controller import AutonomousController

    controller = AutonomousController(
        sm,
        auto_approve=args.auto_approve,
        use_engine_recommender=getattr(args, "use_recommender", False),
    )
    controller.initialize()

    if args.auto_approve:
        print("WARNING: Auto-approve enabled — AI will execute actions without confirmation!\n")

    if args.loop:
        print(f"Starting autonomous loop (every {args.interval}s). Press Ctrl+C to stop.\n")
        controller.start(args.interval)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            controller.stop()
            status = controller.get_status()
            print(f"\nStopped after {status['cycles_completed']} cycles.")
        return

    # Single cycle
    store_id = args.store or sm.active_store_id
    print(f"Running autonomous cycle for {store_id}...\n")
    result = controller.run_cycle(store_id)

    if result.get("status") == "error":
        print(f"Error: {result.get('error', 'unknown')}")
        return

    print(f"Cycle: {result['cycle_id']}")
    print(f"Duration: {result['duration_s']}s")
    print()

    phases = result.get("phases", {})
    data = phases.get("data", {})
    print(f"  Data: {data.get('products', 0)} products, {data.get('orders', 0)} orders, {data.get('customers', 0)} customers ({data.get('source', '?')})")

    analysis = phases.get("analysis", {})
    print(f"  Analysis: {analysis.get('engines_run', 0)} engines, {analysis.get('insights', 0)} insights")

    decisions = phases.get("decisions", {})
    print(f"  Decisions: {decisions.get('proposed', 0)} proposed")

    execution = phases.get("execution", {})
    print(f"  Execution: {execution.get('executed', 0)} executed, {execution.get('pending', 0)} pending")

    learning = phases.get("learning", {})
    print(f"  Learning: {learning.get('patterns_found', 0)} patterns, {learning.get('weight_updates', 0)} weight updates")


def _cmd_feedback(args) -> None:
    """Dispatcher for ``shopai feedback {stats}``."""
    action = getattr(args, "feedback_action", None)
    if action == "stats":
        _cmd_feedback_stats(args)
        return
    print(
        "Usage:\n"
        "  shopai feedback stats [--json]"
    )
    sys.exit(1)


def _cmd_feedback_stats(args) -> None:
    """Webhook bridge counters — diagnoses whether webhook events
    are reaching the bridge and getting attributed to engines.
    """
    try:
        from core.feedback import get_webhook_feedback_bridge
    except Exception as exc:
        print(f"Error: webhook bridge unavailable: {exc}")
        sys.exit(1)

    try:
        bridge = get_webhook_feedback_bridge()
        stats = bridge.get_stats()
    except Exception as exc:
        print(f"Error: bridge stats lookup failed: {exc}")
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps(stats, indent=2, default=str))
        return

    print("Webhook bridge stats:")
    rows = [
        ("Events seen",       stats.get("events_seen", 0)),
        ("Matched actions",   stats.get("matched_actions", 0)),
        ("Orphan events",     stats.get("orphan_events", 0)),
        ("Feedback recorded", stats.get("feedback_recorded", 0)),
        ("Errors",            stats.get("errors", 0)),
    ]
    for label, value in rows:
        print(f"  {label:<20} {value}")

    # Quick diagnostic hints
    events = stats.get("events_seen", 0)
    matched = stats.get("matched_actions", 0)
    if events == 0:
        print(
            "\n  Hint: 0 events seen — is the Shopify webhook "
            "subscription pointing at this server?"
        )
    elif matched == 0:
        print(
            "\n  Hint: events arriving but no engine attribution. "
            "Engines may not be minting matchable codes/product_ids."
        )


def _cmd_learn(args) -> None:
    from core.autonomous.controller import LearningPipeline
    sm = _get_store_manager()
    pipeline = LearningPipeline(sm)
    summary = pipeline.get_learning_summary()

    print("ShopAI Learning Status\n")

    weights = summary.get("weights", {})
    if weights:
        print("  Learned Weights:")
        for factor, weight in sorted(weights.items()):
            direction = "+" if weight > 0 else ""
            bar = "█" * int(abs(weight) * 20) if weight != 0 else "·"
            print(f"    {factor:12s}: {direction}{weight:.4f}  {bar}")
    else:
        print("  No learned weights yet (needs more cycles)")

    system = summary.get("system", {})
    if system and system.get("status") != "no_data":
        print(f"\n  Engines analyzed: {system.get('engines_analyzed', 0)}")
        recs = system.get("recommendations", [])
        if recs:
            print(f"  System recommendations ({len(recs)}):")
            for r in recs[:5]:
                print(f"    - {r}")

    if args.details:
        print(f"\n  Full summary: {json.dumps(summary, indent=2, default=str)}")


# ── System Commands ──────────────────────────────────────────

def _build_version_dict() -> dict:
    """Gather a runtime fingerprint for support / debug.

    Includes the static ShopAI version, the running Python
    interpreter, the platform string, and a best-effort git SHA
    (so operators can pin "they're running commit X" even when
    they're on a non-tagged dev branch).
    """
    import platform
    import subprocess

    payload: dict = {
        "shopai": SHOPAI_VERSION,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2, check=False,
        )
        if sha.returncode == 0 and sha.stdout.strip():
            payload["git_sha"] = sha.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        # No git in PATH or repo unavailable — skip silently.
        pass
    return payload


def _cmd_version(args) -> None:
    """Render the version + runtime fingerprint."""
    payload = _build_version_dict()
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, default=str))
        return
    print(f"ShopAI  {payload['shopai']}")
    print(f"Python  {payload['python']}")
    print(f"Platform {payload['platform']}")
    if "git_sha" in payload:
        print(f"Git SHA {payload['git_sha']}")


def _cmd_health() -> None:
    import importlib
    from engines.registry import engine_count

    modules = [
        ("engines", "engines.registry"),
        ("data_pipeline", "data_pipeline"),
        ("data_store", "data_pipeline.store"),
        ("execution", "execution"),
        ("action_executor", "execution.action_executor"),
        ("agents", "agents"),
        ("knowledge", "knowledge"),
        ("memory", "memory"),
        ("testing", "testing"),
        ("monitoring", "monitoring"),
        ("infrastructure", "infrastructure"),
        ("workflows", "workflows"),
        ("models", "models.routing.model_router"),
        ("core", "core.orchestrator"),
    ]
    print("ShopAI Health Check\n")
    all_ok = True
    for name, path in modules:
        try:
            importlib.import_module(path)
            print(f"  [OK]   {name}")
        except Exception as exc:
            print(f"  [FAIL] {name}: {exc}")
            all_ok = False

    print(f"\nEngines: {engine_count()}")
    print(f"Status:  {'ALL OK' if all_ok else 'SOME FAILURES'}")


def _build_status_dict() -> dict:
    """Gather the status payload as a structured dict.

    Shared between ``_cmd_status`` (renders the table) and any
    caller that wants the raw JSON (--json flag, monitoring
    pipes, future API endpoints).
    """
    from engines.registry import engine_count
    from data_pipeline.store.sync_service import SyncService

    sm = _get_store_manager()
    stores = sm.list_stores()
    sync = SyncService(sm)
    sync_status = sync.get_status()

    store_payload = []
    for s in stores:
        stats = sm.get_stats(s["store_id"])
        store_payload.append({
            "store_id": s["store_id"],
            "active": bool(s.get("is_active")),
            "products": stats.get("products", 0),
            "orders": stats.get("orders", 0),
            "customers": stats.get("customers", 0),
            "total_revenue": stats.get("total_revenue", 0.0),
        })

    now = time.time()
    sync_stores = []
    for si in sync_status.get("stores", []):
        last = si.get("last_sync")
        sync_stores.append({
            "store_id": si.get("store_id"),
            "last_sync": last,
            "last_sync_age_seconds": (now - last) if last else None,
            "last_status": si.get("last_status"),
        })

    return {
        "engines": engine_count(),
        "stores_count": len(stores),
        "active_store": sm.active_store_id or None,
        "stores": store_payload,
        "auto_sync_running": bool(
            sync_status.get("auto_sync_running"),
        ),
        "sync_stores": sync_stores,
    }


def _cmd_status(args=None) -> None:
    if args is not None and getattr(args, "json", False):
        payload = _build_status_dict()
        print(json.dumps(payload, indent=2, default=str))
        return

    payload = _build_status_dict()

    print("ShopAI System Status\n")
    print(f"  Engines:  {payload['engines']}")
    print(f"  Stores:   {payload['stores_count']}")
    print(f"  Active:   {payload['active_store'] or 'none'}")
    print()

    if payload["stores"]:
        print("Store Data:")
        for s in payload["stores"]:
            active = " *" if s["active"] else ""
            print(
                f"  {s['store_id']}{active}: {s['products']}p / "
                f"{s['orders']}o / {s['customers']}c / "
                f"${s['total_revenue']:,.0f}"
            )
    print()

    print(
        f"  Auto-sync: "
        f"{'running' if payload['auto_sync_running'] else 'stopped'}"
    )
    for si in payload["sync_stores"]:
        age = si.get("last_sync_age_seconds")
        if age is not None:
            ago = (
                f"{int(age)}s ago" if age < 60
                else f"{int(age/60)}m ago" if age < 3600
                else f"{int(age/3600)}h ago"
            )
            print(
                f"    {si['store_id']}: last sync {ago} "
                f"({si['last_status']})"
            )
        else:
            print(f"    {si['store_id']}: never synced")
    print()

    _print_approval_status()
    _print_goal_status()


def _build_loop_dict(top_n: int = 5) -> dict:
    """Aggregate the autonomous loop's live state in one pass.

    Pulls from five subsystems, each best-effort (a missing
    module leaves its slice empty rather than blowing up the
    whole render):

      * Approval queue stats by status (PR #110)
      * Recent EXECUTED actions (PR #111)
      * Active brain-stack goal + per-goal EMA (PR #119)
      * Top-N recommended engines (PR #91)
      * Webhook bridge counters (PR #128)
      * Engine→goal mapping coverage (PR #116)
    """
    import time as _time

    payload: dict[str, Any] = {
        "approval_queue": {},
        "recent_executed": [],
        "goal": {"current": None, "stats": {}},
        "recommendations": [],
        "webhook_stats": {},
        "engine_coverage": {},
        "governance": {
            "auto_approve_allowlist": [],
            "quarantine_exemptions": [],
            "quarantine_released": [],
            "recent_auto_approved": 0,
            "recent_auto_quarantined": 0,
        },
    }

    # Approval queue: per-status counts + recent EXECUTED
    try:
        from core.approval import get_approval_queue
        q = get_approval_queue()
        payload["approval_queue"] = q.stats()
        now = _time.time()
        for a in q.list_executed(limit=top_n):
            decided = a.decided_at or a.proposed_at
            payload["recent_executed"].append({
                "id": a.id,
                "engine": a.engine,
                "action_type": a.action_type,
                "status": a.status.value,
                "age_seconds": (
                    int(now - decided) if decided else None
                ),
            })
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue probe failed: %s", exc)

    # Brain stack: current goal + per-goal EMA
    try:
        from core.goals.goal_feedback import _default_manager
        mgr = _default_manager()
        if mgr is not None:
            payload["goal"]["current"] = mgr.get_current_goal()
            payload["goal"]["stats"] = mgr.get_effectiveness_stats()
    except Exception as exc:  # noqa: BLE001
        logger.debug("goal manager probe failed: %s", exc)

    # Recommender: top-N engines (best-effort, doesn't 500 if
    # the brain stack is mid-init)
    try:
        from core.brain.engine_recommender import recommend_engines
        result = recommend_engines(
            limit=max(1, int(top_n)),
            include_alternatives=False,
        )
        for r in result.primary:
            payload["recommendations"].append({
                "engine": r.engine,
                "goal": r.goal,
                "priority": round(r.priority, 4),
                "effectiveness": round(r.effectiveness, 4),
            })
    except Exception as exc:  # noqa: BLE001
        logger.debug("recommender probe failed: %s", exc)

    # Webhook bridge: counters
    try:
        from core.feedback import get_webhook_feedback_bridge
        payload["webhook_stats"] = (
            get_webhook_feedback_bridge().get_stats()
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("webhook bridge probe failed: %s", exc)

    # Engine→goal mapping coverage
    try:
        from core.goals.engine_goal_map import ENGINE_GOAL_MAP
        from engines.registry import list_engines
        engines = list_engines()
        mapped = sum(1 for e in engines if e in ENGINE_GOAL_MAP)
        payload["engine_coverage"] = {
            "total": len(engines),
            "mapped": mapped,
            "unmapped": len(engines) - mapped,
            "ratio": (
                round(mapped / len(engines), 3) if engines else 0.0
            ),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("engine coverage probe failed: %s", exc)

    # Governance: auto-approve allowlist + quarantine state +
    # last-24h counters for auto-decisions (PR #161 + #162). The
    # counters answer "is the self-regulating loop actually firing?"
    # so an operator can spot a regression (e.g. quarantine
    # suddenly thrashing) at a glance.
    try:
        from core.approval.auto_approve import load_config as _aa_cfg
        payload["governance"]["auto_approve_allowlist"] = (
            sorted(_aa_cfg().allowlist)
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("auto_approve probe failed: %s", exc)

    try:
        from core.approval.quarantine import load_state as _q_state
        s = _q_state()
        payload["governance"]["quarantine_exemptions"] = (
            sorted(s.exemptions)
        )
        payload["governance"]["quarantine_released"] = (
            sorted(s.released)
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("quarantine probe failed: %s", exc)

    try:
        from core.approval import get_approval_queue
        q = get_approval_queue()
        # Last 24h window — same lens as `shopai outcomes --since 24h`
        recent = q.list_decisions(limit=500)
        cutoff = _time.time() - 86400
        for r in recent:
            if r.get("occurred_at", 0) < cutoff:
                continue
            actor = r.get("decided_by")
            if actor == "auto_threshold":
                payload["governance"]["recent_auto_approved"] += 1
            elif actor == "auto_quarantine":
                payload["governance"]["recent_auto_quarantined"] += 1
    except Exception as exc:  # noqa: BLE001
        logger.debug("governance counters probe failed: %s", exc)

    return payload


def _cmd_loop(args=None) -> None:
    """Single-screen autonomous-loop dashboard.

    Pulls the live state of every moving part — queue depth,
    recent decisions, goal EMA, recommender picks, webhook
    counters, mapping coverage — into one operator-friendly
    view. The text mode is for humans; ``--json`` is for
    monitoring tools.

    Five panels stacked top-to-bottom in text mode:
      1. Approval Queue (per-status counts)
      2. Recent Decisions (last N EXECUTED)
      3. Active Goal + per-goal EMA
      4. Top Picks (from recommender)
      5. Webhook Bridge + Engine Coverage

    ``--watch N`` repeats the render every N seconds (like
    ``top`` / ``htop``). Ctrl+C exits cleanly.
    """
    top_n = getattr(args, "top", 5) if args is not None else 5
    watch_interval = (
        getattr(args, "watch", 0) if args is not None else 0
    )

    # --watch loop: clear + redraw every N seconds. Json mode
    # ignores --watch because watching a json stream isn't useful;
    # callers wanting a live JSON feed should script their own
    # polling loop.
    if (
        watch_interval > 0
        and not (args is not None and getattr(args, "json", False))
    ):
        try:
            while True:
                _clear_screen()
                _render_loop_text(_build_loop_dict(top_n=top_n))
                print()
                print(
                    f"(refreshing every {watch_interval}s — "
                    "press Ctrl+C to exit)"
                )
                time.sleep(watch_interval)
        except KeyboardInterrupt:
            print()  # flush a final newline so the prompt is clean
            return

    payload = _build_loop_dict(top_n=top_n)

    if args is not None and getattr(args, "json", False):
        print(json.dumps(payload, indent=2, default=str))
        return

    _render_loop_text(payload)


def _clear_screen() -> None:
    """Cross-platform clear. ANSI escape sequence works on
    modern Windows terminals (Win10+ console-host upgrade), most
    UNIX terminals, and falls through harmlessly on legacy
    consoles (extra junk in the scrollback, no actual harm).
    """
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def _render_loop_text(payload: dict) -> None:
    """Render the dashboard as text. Extracted so ``--watch``
    can call it repeatedly without re-doing the build."""

    print("ShopAI Autonomous Loop\n")

    # ── 1. Approval Queue ─────────────────────────────────
    q = payload["approval_queue"]
    if q:
        print("Approval Queue:")
        print(
            f"  pending: {q.get('pending', 0):<3}  "
            f"approved: {q.get('approved', 0):<3}  "
            f"executed: {q.get('executed', 0):<3}"
        )
        print(
            f"  rejected: {q.get('rejected', 0):<2}  "
            f"failed:   {q.get('failed', 0):<3}  "
            f"expired:  {q.get('expired', 0):<3}"
        )
    else:
        print("Approval Queue: (unavailable)")
    print()

    # ── 2. Recent Decisions ───────────────────────────────
    recent = payload["recent_executed"]
    if recent:
        print(f"Recent Decisions (last {len(recent)}):")
        for a in recent:
            age_str = (
                _format_age(a["age_seconds"])
                if a["age_seconds"] is not None else "?"
            )
            label = f"{a['engine']}/{a['action_type']}"
            if len(label) > 36:
                label = label[:33] + "..."
            print(
                f"  {a['id'][:18]:<18} {label:<36} "
                f"{a['status'].upper():<9} {age_str}"
            )
    else:
        print("Recent Decisions: (none yet)")
    print()

    # ── 3. Active Goal + EMA ──────────────────────────────
    goal = payload["goal"]
    print(f"Active Goal: {goal['current'] or '(unknown)'}")
    stats = goal["stats"]
    if stats:
        print("  Per-goal EMA:")
        sorted_goals = sorted(
            stats.items(),
            key=lambda kv: kv[1].get("effectiveness", 0.5),
            reverse=True,
        )
        for g, s in sorted_goals:
            ema = s.get("effectiveness", 0.5)
            n = s.get("n", 0)
            print(f"    {g:<22} {ema:.2f}  (over {n} outcomes)")
    else:
        print("  Per-goal EMA: (no recorded outcomes yet)")
    print()

    # ── 4. Top Picks ──────────────────────────────────────
    recs = payload["recommendations"]
    if recs:
        print(f"Top Picks (recommender, n={len(recs)}):")
        for i, r in enumerate(recs, 1):
            print(
                f"  {i}. {r['engine']:<24} "
                f"priority {r['priority']:.2f}  "
                f"(goal={r['goal']}, eff={r['effectiveness']:.2f})"
            )
    else:
        print("Top Picks: (recommender unavailable)")
    print()

    # ── 5. Webhook Bridge + Coverage ──────────────────────
    wh = payload["webhook_stats"]
    cov = payload["engine_coverage"]
    print("Webhook bridge:")
    if wh:
        print(
            f"  events_seen={wh.get('events_seen', 0)}  "
            f"matched={wh.get('matched_actions', 0)}  "
            f"orphan={wh.get('orphan_events', 0)}  "
            f"errors={wh.get('errors', 0)}"
        )
    else:
        print("  (bridge unavailable)")
    if cov:
        print(
            f"Engine coverage: {cov.get('mapped', 0)}/"
            f"{cov.get('total', 0)} mapped "
            f"({cov.get('ratio', 0.0):.0%})"
        )

    # ── 6. Governance (PR #161 / #162) ────────────────────
    gov = payload.get("governance", {})
    if gov:
        print()
        print("Governance:")
        allowlist = gov.get("auto_approve_allowlist") or []
        print(
            f"  Auto-approve allowlist ({len(allowlist)}): "
            f"{', '.join(allowlist) or '(empty)'}"
        )
        exemptions = gov.get("quarantine_exemptions") or []
        released = gov.get("quarantine_released") or []
        print(
            f"  Quarantine exemptions ({len(exemptions)}): "
            f"{', '.join(exemptions) or '(none)'}"
        )
        if released:
            print(
                f"  Quarantine released ({len(released)}): "
                f"{', '.join(released)}"
            )
        print(
            f"  Last 24h:  "
            f"auto-approved={gov.get('recent_auto_approved', 0)}  "
            f"auto-quarantined={gov.get('recent_auto_quarantined', 0)}"
        )


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds / 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds / 3600)}h ago"
    return f"{int(seconds / 86400)}d ago"


def _cmd_outcomes(args) -> None:
    """Chronological view of recent webhook outcomes.

    The companion to ``loop`` (snapshot of the moving parts) and
    ``approvals show`` (everything about ONE action). ``outcomes``
    is the across-engine ticker: "what's happening downstream right
    now?". Operators triaging a quiet day or chasing a sudden
    negative-polarity spike start here.

    Filters compose: ``--engine cart_recovery --polarity positive
    --since 1h`` answers "did our recovery codes drive any orders in
    the last hour?".
    """
    from core.approval import get_approval_queue

    since_seconds: float | None = None
    if getattr(args, "since", None):
        since_seconds = _parse_age_spec(args.since)
        if since_seconds is None:
            print(
                f"Invalid --since value: {args.since!r} "
                "(expected e.g. 60s, 30m, 24h, 7d)"
            )
            sys.exit(1)

    try:
        queue = get_approval_queue()
        outcomes = queue.list_recent_outcomes(
            limit=args.limit,
            engine=args.engine,
            polarity=args.polarity,
            since_seconds=since_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("outcomes lookup failed: %s", exc)
        outcomes = []

    if getattr(args, "json", False):
        print(json.dumps(outcomes, indent=2, default=str))
        return

    if not outcomes:
        filt_bits = []
        if args.engine:
            filt_bits.append(f"engine={args.engine}")
        if args.polarity:
            filt_bits.append(f"polarity={args.polarity}")
        if args.since:
            filt_bits.append(f"since={args.since}")
        suffix = f" ({', '.join(filt_bits)})" if filt_bits else ""
        print(f"No recent outcomes{suffix}.")
        return

    print(f"Recent outcomes ({len(outcomes)}):")
    now = time.time()
    for o in outcomes:
        ago = (
            _format_age(now - o["recorded_at"])
            if o.get("recorded_at") else "?"
        )
        label = f"{o['engine']}/{o['action_type']}"
        if len(label) > 30:
            label = label[:27] + "..."
        polarity_tag = (o.get("polarity") or "?")[:8]
        topic = o.get("topic") or "?"
        if len(topic) > 22:
            topic = topic[:19] + "..."
        line = (
            f"  {o['action_id'][:18]:<18} "
            f"{label:<30} "
            f"{polarity_tag:<8} "
            f"{topic:<22} "
            f"{ago}"
        )
        # Surface revenue / refund metrics inline when present —
        # they're the headline number for most outcomes
        m = o.get("metrics") or {}
        if isinstance(m, dict):
            rev = m.get("revenue")
            if isinstance(rev, (int, float)) and rev:
                line += f"  rev={rev:.2f}"
        print(line)


def _print_approval_status() -> None:
    """Approval-queue depth + last few decisions.

    The autonomous loop's middle layer: engines enqueue here, operators
    decide, executor replays. Empty / all-resolved is the steady state;
    a growing pending bucket means the loop is starved.
    """
    try:
        from core.approval.queue import get_approval_queue
        queue = get_approval_queue()
        stats = queue.stats()
        recent = queue.list_executed(limit=3)
    except Exception as exc:
        logger.debug("approval queue unavailable for status: %s", exc)
        return

    print("Approval Queue:")
    print(
        f"  pending: {stats.get('pending', 0):<4} "
        f"approved: {stats.get('approved', 0):<4} "
        f"executed: {stats.get('executed', 0):<4}"
    )
    print(
        f"  rejected: {stats.get('rejected', 0):<3} "
        f"failed:   {stats.get('failed', 0):<4} "
        f"expired:  {stats.get('expired', 0):<4}"
    )

    # Recent decisions — most-recent EXECUTED actions
    if recent:
        print("\n  Recent decisions:")
        now = time.time()
        for a in recent:
            decided = a.decided_at or a.created_at
            ago = _format_age(now - decided) if decided else "?"
            label = f"{a.engine}/{a.action_type}"
            if len(label) > 36:
                label = label[:33] + "..."
            print(
                f"    {a.id[:18]:<18} {label:<36} "
                f"{a.status.value.upper():<9} {ago}"
            )
    print()


def _print_goal_status() -> None:
    """Active business goal + top-priority engines.

    Wired through the brain stack (PR #90/#91/#92): the goal manager's
    per-engine EMA shifts as actions execute → goal_feedback hook
    runs → effectiveness moves → recommender reprioritizes. Showing
    the top picks here surfaces what the autonomous loop *thinks* the
    next-best work is.
    """
    try:
        from core.brain.engine_recommender import recommend_engines
    except Exception as exc:
        logger.debug("engine recommender unavailable: %s", exc)
        return

    try:
        result = recommend_engines(
            goal=None, limit=5, include_alternatives=False,
        )
    except Exception as exc:
        logger.debug("engine recommendation failed: %s", exc)
        return

    print(f"Active Goal: {result.active_goal}")
    if not result.primary:
        print("  (no engines mapped — set a goal via shopai mind)")
        print()
        return
    print("  Top picks:")
    for i, rec in enumerate(result.primary, 1):
        print(
            f"    {i}. {rec.engine:<22} priority {rec.priority:.2f} "
            f"(effectiveness {rec.effectiveness:.2f})"
        )
    print()


def _cmd_setup() -> None:
    """Interactive setup wizard."""
    print("=" * 50)
    print("  ShopAI Setup Wizard")
    print("=" * 50)
    print()

    # Check for .env file
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        print("Found existing .env file.")
        from infrastructure.config.env_manager import EnvManager
        env = EnvManager()
        env.load_env_file(env_path)
        url = os.environ.get("SHOPAI_SHOPIFY_URL", "")
        key = os.environ.get("SHOPAI_SHOPIFY_KEY", "")
        if url and key:
            print(f"  Store URL: {url}")
            print(f"  API Key:   {key[:10]}...")
            print()

            # Test connection
            sm = _get_store_manager()
            store_id = url.replace(".myshopify.com", "").replace("https://", "")
            print("Testing Shopify connection...")
            result = sm.test_connection(store_id)
            if result.get("connected"):
                print(f"✓ Connected!")
                # Do initial sync
                print("\nRunning initial data sync...")
                from data_pipeline.store.sync_service import SyncService
                sync = SyncService(sm)
                sync_result = sync.sync_store(store_id)
                if sync_result.get("status") == "success":
                    synced = sync_result.get("synced", {})
                    for dtype, info in synced.items():
                        print(f"  {dtype}: {info.get('count', 0)} records")
                    print(f"\n✓ Setup complete! Your store is ready.")
                else:
                    print(f"  Sync issue: {sync_result.get('error', 'check credentials')}")
            else:
                print(f"✗ Connection failed: {result.get('error', '')}")
                print("\nCheck your .env file credentials.")
            return

    # No .env — create one
    print("No .env file found. Let's set up your first store.\n")
    print("You need:")
    print("  1. Your Shopify store URL (e.g. mystore.myshopify.com)")
    print("  2. Your Shopify Admin API access token (starts with shpat_)")
    print()
    print("To get an API token:")
    print("  1. Go to your Shopify Admin > Settings > Apps and sales channels")
    print("  2. Click 'Develop apps' > 'Create an app'")
    print("  3. Configure API scopes (read/write products, orders, customers)")
    print("  4. Install the app and copy the Admin API access token")
    print()
    print("Then create a .env file with:")
    print()
    print("  SHOPAI_SHOPIFY_URL=your-store.myshopify.com")
    print("  SHOPAI_SHOPIFY_KEY=shpat_your_token_here")
    print()
    print("And run: python cli.py setup")


# ── Approval queue (modern path: ApprovalQueue + executor) ──


def _cmd_approvals(args) -> None:
    """Dispatch ``shopai approvals <verb>`` subcommands.

    Wraps the same SQLite-backed ApprovalQueue + executor the
    API endpoints use, so CLI and HTTP surfaces share decisions
    automatically (no separate state).
    """
    verb = getattr(args, "approvals_cmd", None)
    if verb == "pending":
        _cmd_approvals_pending(args)
        return
    if verb == "stats":
        _cmd_approvals_stats(args)
        return
    if verb == "show":
        _cmd_approvals_show(args)
        return
    if verb == "approve":
        _cmd_approvals_approve(args)
        return
    if verb == "reject":
        _cmd_approvals_reject(args)
        return
    if verb == "execute":
        _cmd_approvals_execute(args)
        return
    if verb == "sweep":
        _cmd_approvals_sweep(args)
        return
    if verb == "approve-all":
        _cmd_approvals_approve_all(args)
        return
    if verb == "audit":
        _cmd_approvals_audit(args)
        return
    if verb == "recent":
        _cmd_approvals_recent(args)
        return
    if verb == "history":
        _cmd_approvals_history(args)
        return
    if verb == "auto-config":
        _cmd_approvals_auto_config(args)
        return
    if verb == "quarantine":
        _cmd_approvals_quarantine(args)
        return
    if verb == "auto-approve-candidates":
        _cmd_approvals_auto_candidates(args)
        return
    if verb == "quarantine-release-candidates":
        _cmd_approvals_release_candidates(args)
        return
    if verb == "pending-latency":
        _cmd_approvals_pending_latency(args)
        return
    if verb == "decision-latency":
        _cmd_approvals_decision_latency(args)
        return
    if verb == "rejection-rates":
        _cmd_approvals_rejection_rates(args)
        return
    if verb == "revenue-by-engine":
        _cmd_approvals_revenue_by_engine(args)
        return
    print(
        "Usage:\n"
        "  shopai approvals pending     [--engine NAME] [--limit N]\n"
        "  shopai approvals stats       [--by-engine]\n"
        "  shopai approvals show        <action_id>\n"
        "  shopai approvals approve     <action_id> [--reason ...] [--by ...] [--execute]\n"
        "  shopai approvals reject      <action_id> [--reason ...] [--by ...]\n"
        "  shopai approvals execute     <action_id>\n"
        "  shopai approvals sweep       [--older-than 7d] [--dry-run]\n"
        "  shopai approvals approve-all [--engine NAME] [--min-confidence 0.X] [--execute] [--dry-run]\n"
        "  shopai approvals audit       [--engines-root PATH]\n"
        "  shopai approvals recent      <status> [--engine NAME] [--limit N]\n"
        "  shopai approvals history     [<action_id>] [--by ACTOR] [--limit N] [--json]\n"
        "  shopai approvals auto-config [--enable ENGINE | --disable ENGINE | --list] [--json]\n"
        "  shopai approvals auto-approve-candidates [--json]\n"
        "  shopai approvals quarantine  [--release | --clear-release | --exempt | --unexempt ENGINE | --list] [--json]\n"
        "  shopai approvals quarantine-release-candidates [--since 7d] [--json]\n"
        "  shopai approvals pending-latency [--older-than 24h] [--json]\n"
        "  shopai approvals decision-latency [--status approved|rejected|executed|failed|expired|all] [--json]\n"
        "  shopai approvals rejection-rates [--min-decisions N] [--threshold 0.5] [--json]\n"
        "  shopai approvals revenue-by-engine [--top N] [--sort net|gross|per-positive] [--json]"
    )
    sys.exit(1)


def _cmd_approvals_auto_config(args) -> None:
    """Manage the auto-approve allowlist.

    No mutation flag → defaults to list mode. ``--enable`` /
    ``--disable`` mutate the persisted JSON allowlist; ``--list``
    explicitly shows current state. The current thresholds (min
    history / ratio / confidence) are always included so an
    operator inspecting the config sees the full evaluator
    contract, not just the allowlist.
    """
    from core.approval import auto_approve as aa

    if args.enable:
        cfg = aa.enable_engine(args.enable)
        if getattr(args, "json", False):
            print(json.dumps({
                "enabled": args.enable,
                "allowlist": sorted(cfg.allowlist),
            }, indent=2))
            return
        print(
            f"Enabled auto-approve for engine '{args.enable}'. "
            f"Allowlist now: {sorted(cfg.allowlist)}"
        )
        return

    if args.disable:
        cfg = aa.disable_engine(args.disable)
        if getattr(args, "json", False):
            print(json.dumps({
                "disabled": args.disable,
                "allowlist": sorted(cfg.allowlist),
            }, indent=2))
            return
        print(
            f"Disabled auto-approve for engine '{args.disable}'. "
            f"Allowlist now: {sorted(cfg.allowlist)}"
        )
        return

    cfg = aa.load_config()
    payload = {
        "allowlist": sorted(cfg.allowlist),
        "thresholds": {
            "min_outcomes_observed": aa.MIN_OUTCOMES_OBSERVED,
            "min_outcome_ratio": aa.MIN_OUTCOME_RATIO,
            "min_confidence": aa.MIN_CONFIDENCE,
        },
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return

    print("Auto-approve configuration:")
    print(
        f"  Allowlist ({len(cfg.allowlist)}): "
        f"{', '.join(sorted(cfg.allowlist)) or '(empty — safe default)'}"
    )
    print("  Thresholds:")
    print(f"    min outcomes observed: {aa.MIN_OUTCOMES_OBSERVED}")
    print(f"    min outcome ratio:     {aa.MIN_OUTCOME_RATIO:.2f}")
    print(f"    min confidence:        {aa.MIN_CONFIDENCE:.2f}")


def _cmd_approvals_quarantine(args) -> None:
    """Manage failed-engine quarantine state.

    Five mutually exclusive actions (all optional → default is
    list mode):
      - ``--release ENGINE`` clears an active quarantine for ENGINE
      - ``--clear-release ENGINE`` removes ENGINE from the released
        list (lets quarantine re-engage on next bad ratio)
      - ``--exempt ENGINE`` permanently exempts ENGINE from
        quarantine (for engines where negative polarity is normal
        e.g. returns workflows)
      - ``--unexempt ENGINE`` removes the exemption
      - ``--list`` (default) shows current state + thresholds
    """
    from core.approval import quarantine as qm

    if args.release:
        s = qm.release_engine(args.release)
        if getattr(args, "json", False):
            print(json.dumps({
                "released": args.release,
                "released_list": sorted(s.released),
            }, indent=2))
            return
        print(
            f"Released '{args.release}' from quarantine. "
            f"Released list: {sorted(s.released)}"
        )
        return

    if args.clear_release:
        s = qm.clear_release(args.clear_release)
        if getattr(args, "json", False):
            print(json.dumps({
                "cleared_release": args.clear_release,
                "released_list": sorted(s.released),
            }, indent=2))
            return
        print(
            f"Cleared release of '{args.clear_release}'. "
            f"Released list: {sorted(s.released)}"
        )
        return

    if args.exempt:
        s = qm.exempt_engine(args.exempt)
        if getattr(args, "json", False):
            print(json.dumps({
                "exempted": args.exempt,
                "exemptions": sorted(s.exemptions),
            }, indent=2))
            return
        print(
            f"Exempted '{args.exempt}' from quarantine. "
            f"Exemptions: {sorted(s.exemptions)}"
        )
        return

    if args.unexempt:
        s = qm.unexempt_engine(args.unexempt)
        if getattr(args, "json", False):
            print(json.dumps({
                "unexempted": args.unexempt,
                "exemptions": sorted(s.exemptions),
            }, indent=2))
            return
        print(
            f"Removed '{args.unexempt}' from exemptions. "
            f"Exemptions: {sorted(s.exemptions)}"
        )
        return

    s = qm.load_state()
    payload = {
        "exemptions": sorted(s.exemptions),
        "released": sorted(s.released),
        "thresholds": {
            "min_outcomes_observed": qm.MIN_OUTCOMES_OBSERVED,
            "max_negative_ratio": qm.MAX_NEGATIVE_RATIO,
        },
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return

    print("Quarantine state:")
    print(
        f"  Exemptions ({len(s.exemptions)}): "
        f"{', '.join(sorted(s.exemptions)) or '(none)'}"
    )
    print(
        f"  Released ({len(s.released)}): "
        f"{', '.join(sorted(s.released)) or '(none)'}"
    )
    print("  Thresholds:")
    print(f"    min outcomes observed: {qm.MIN_OUTCOMES_OBSERVED}")
    print(f"    max negative ratio:    {qm.MAX_NEGATIVE_RATIO:.2f}")


def _cmd_approvals_auto_candidates(args) -> None:
    """List engines that would pass auto-approve guardrails if
    allowlisted — the adoption recommendation surface.

    Operators inspecting the output decide whether to opt each
    one in via ``shopai approvals auto-config --enable ENGINE``.
    The numbers (history count + outcome ratio) are shown so the
    operator can sanity-check the recommendation against their
    own intuition about the engine.
    """
    from core.approval import get_approval_queue
    from core.approval.auto_approve import find_candidates

    try:
        queue = get_approval_queue()
        candidates = find_candidates(queue)
    except Exception as exc:  # noqa: BLE001
        logger.debug("auto-approve candidate scan failed: %s", exc)
        candidates = []

    if getattr(args, "json", False):
        print(json.dumps(
            [
                {
                    "engine": c.engine,
                    "outcome_ratio": c.outcome_ratio,
                    "positive": c.positive,
                    "negative": c.negative,
                    "total_polarised": c.total_polarised,
                }
                for c in candidates
            ],
            indent=2,
        ))
        return

    if not candidates:
        print(
            "No auto-approve candidates "
            "(no engines outside the allowlist meet the outcome "
            "guardrails yet)."
        )
        return

    print(
        f"Auto-approve candidates ({len(candidates)} engines could "
        "be safely opted in):"
    )
    print(
        "  engine                          ratio  positive negative  history"
    )
    for c in candidates:
        engine_label = c.engine[:30]
        print(
            f"  {engine_label:<30}  {c.outcome_ratio:>5.2f}  "
            f"{c.positive:>8}  {c.negative:>8}  {c.total_polarised:>7}"
        )
    print()
    print(
        "Enable with: shopai approvals auto-config --enable <engine>"
    )


def _cmd_approvals_release_candidates(args) -> None:
    """List quarantined engines whose recent window has recovered.

    Symmetric to ``auto-approve-candidates`` (PR #164). Where
    that one says "these engines could safely speed up", this
    one says "these engines could safely come off the brake".

    The recent window defaults to 7d but is operator-tunable via
    ``--since`` — shrink it to catch recoveries faster, widen it
    to avoid false-positives on a lucky week.
    """
    from core.approval import get_approval_queue
    from core.approval.quarantine import find_release_candidates

    raw_since = getattr(args, "since", "7d") or "7d"
    recent_seconds = _parse_age_spec(raw_since)
    if recent_seconds is None:
        print(
            f"Invalid --since value: {raw_since!r} "
            "(expected e.g. 60s, 30m, 24h, 7d)"
        )
        sys.exit(1)

    try:
        queue = get_approval_queue()
        candidates = find_release_candidates(
            queue, recent_seconds=int(recent_seconds),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "quarantine release candidate scan failed: %s", exc,
        )
        candidates = []

    if getattr(args, "json", False):
        print(json.dumps(
            [
                {
                    "engine": c.engine,
                    "all_time_negative_ratio": (
                        c.all_time_negative_ratio
                    ),
                    "all_time_polarised": c.all_time_polarised,
                    "recent_negative_ratio": (
                        c.recent_negative_ratio
                    ),
                    "recent_polarised": c.recent_polarised,
                }
                for c in candidates
            ],
            indent=2,
        ))
        return

    if not candidates:
        print(
            f"No quarantine-release candidates in the last "
            f"{raw_since} window."
        )
        return

    print(
        f"Quarantine-release candidates ({len(candidates)}) — "
        f"recovered in last {raw_since}:"
    )
    print(
        "  engine                          alltime  recent  "
        "recent_total"
    )
    for c in candidates:
        engine_label = c.engine[:30]
        print(
            f"  {engine_label:<30}  "
            f"{c.all_time_negative_ratio:>5.2f}    "
            f"{c.recent_negative_ratio:>5.2f}  "
            f"{c.recent_polarised:>11}"
        )
    print()
    print(
        "Release with: shopai approvals quarantine --release <engine>"
    )


def _cmd_approvals_pending_latency(args) -> None:
    """Per-engine PENDING-action age aggregator.

    Surfaces engines producing un-actionable proposals — either
    the engine is spammy (too many proposals to triage) or its
    proposals aren't useful enough to warrant the click.
    Operators see "engine X has 30 pending, oldest 4 days old"
    and either tune the engine or sweep its backlog.

    ``--older-than`` filters to engines with at least one PENDING
    older than the cutoff — triage mode.
    """
    from core.approval import get_approval_queue

    cutoff_seconds: float | None = None
    raw_cutoff = getattr(args, "older_than", None)
    if raw_cutoff:
        cutoff_seconds = _parse_age_spec(raw_cutoff)
        if cutoff_seconds is None:
            print(
                f"Invalid --older-than value: {raw_cutoff!r} "
                "(expected e.g. 60s, 30m, 24h, 7d)"
            )
            sys.exit(1)

    try:
        queue = get_approval_queue()
        stats = queue.pending_latency_stats()
    except Exception as exc:  # noqa: BLE001
        logger.debug("pending_latency_stats raised: %s", exc)
        stats = {}

    # Build row data
    rows: list[dict[str, Any]] = []
    for engine, s in stats.items():
        if cutoff_seconds is not None and (
            s["oldest_age_seconds"] < cutoff_seconds
        ):
            continue
        rows.append({"engine": engine, **s})

    # Sort: oldest oldest_age first (most-stale engines surface
    # at the top), tiebreak on pending_count desc, then engine
    # alphabetical
    rows.sort(key=lambda r: (
        -r["oldest_age_seconds"],
        -r["pending_count"],
        r["engine"],
    ))

    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2, default=str))
        return

    if not rows:
        if cutoff_seconds is not None:
            print(
                f"No engines have PENDING actions older than "
                f"{raw_cutoff}."
            )
        else:
            print("No engines have PENDING actions.")
        return

    print(
        f"Pending-action latency ({len(rows)} engines with "
        "PENDING actions):"
    )
    print()
    print(
        "  engine                          pending  oldest    "
        "median    mean"
    )
    for r in rows:
        engine_label = r["engine"][:30]
        print(
            f"  {engine_label:<30}  {r['pending_count']:>7}  "
            f"{_format_age(r['oldest_age_seconds']):>8}  "
            f"{_format_age(r['median_age_seconds']):>8}  "
            f"{_format_age(r['mean_age_seconds']):>6}"
        )


def _cmd_approvals_decision_latency(args) -> None:
    """Per-engine historical decision latency.

    Complement to ``pending-latency``: that surface answers
    "what's stale RIGHT NOW?"; this one answers "across all
    historical decisions, how fast did operators DECIDE on this
    engine's proposals?"

    The two together let operators distinguish four
    engine-relationship patterns (see
    :meth:`ApprovalQueue.decision_latency_stats` for the table).

    ``--status`` chooses which decision states to include:
      - ``default`` (no flag): approved + rejected + executed +
        failed (excludes EXPIRED since its decided_at is sweeper
        time, not operator time)
      - ``approved`` / ``rejected`` / ``executed`` / ``failed``
        / ``expired``: single-status view
      - ``all``: every decided status including EXPIRED
    """
    from core.approval import get_approval_queue
    from core.approval.queue import ApprovalStatus

    raw_status = getattr(args, "status", "default") or "default"
    if raw_status == "default":
        statuses = None
    elif raw_status == "all":
        statuses = [
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.EXECUTED,
            ApprovalStatus.FAILED,
            ApprovalStatus.EXPIRED,
        ]
    else:
        try:
            statuses = [ApprovalStatus(raw_status)]
        except ValueError:
            print(f"Unknown status: {raw_status}")
            sys.exit(1)

    try:
        queue = get_approval_queue()
        stats = queue.decision_latency_stats(statuses=statuses)
    except Exception as exc:  # noqa: BLE001
        logger.debug("decision_latency_stats raised: %s", exc)
        stats = {}

    rows = [{"engine": e, **s} for e, s in stats.items()]

    # Sort: slowest median first (engines operators struggle
    # with most surface at the top — matches the triage UX of
    # PRs #164 / #165 / #167 / #168).
    rows.sort(key=lambda r: (
        -r["median_seconds"],
        -r["decided_count"],
        r["engine"],
    ))

    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2, default=str))
        return

    if not rows:
        print(
            "No decided actions yet for the selected status set."
        )
        return

    print(
        f"Decision latency ({len(rows)} engines, status="
        f"{raw_status}):"
    )
    print()
    print(
        "  engine                          decisions  slowest   "
        "median   mean"
    )
    for r in rows:
        engine_label = r["engine"][:30]
        print(
            f"  {engine_label:<30}  {r['decided_count']:>9}  "
            f"{_format_age(r['slowest_seconds']):>8}  "
            f"{_format_age(r['median_seconds']):>7}  "
            f"{_format_age(r['mean_seconds']):>6}"
        )


def _cmd_approvals_rejection_rates(args) -> None:
    """Per-engine rejection rate — engine misbehaviour signal.

    Different signal from the latency surfaces:
      - pending-latency #168: engines whose proposals SIT
      - decision-latency #169: engines where decisions are SLOW
      - this: engines where the operator explicitly says NO

    High rejection rate at proposal time = the engine's
    proposals are bad (operator vetoes them BEFORE execute).
    Different from quarantine (PR #162) which fires on
    negative OUTCOMES post-execute.

    ``--min-decisions`` filters out engines with too little
    signal (default 5). ``--threshold 0.5`` filters to
    majority-rejected engines for alert-mode triage.
    """
    from core.approval import get_approval_queue

    try:
        queue = get_approval_queue()
        stats = queue.rejection_rate_stats()
    except Exception as exc:  # noqa: BLE001
        logger.debug("rejection_rate_stats raised: %s", exc)
        stats = {}

    min_decisions = max(1, int(getattr(args, "min_decisions", 5)))
    threshold = getattr(args, "threshold", None)

    rows: list[dict[str, Any]] = []
    for engine, s in stats.items():
        if s["decided_count"] < min_decisions:
            continue
        if (
            threshold is not None
            and s["rejection_rate"] < threshold
        ):
            continue
        rows.append({"engine": engine, **s})

    # Sort: highest rejection rate first (worst offenders surface
    # at the top — matches the triage UX of PRs #164/#165/#167/
    # #168/#169). Tiebreak on decided_count desc (more-evidence
    # engines first).
    rows.sort(key=lambda r: (
        -r["rejection_rate"],
        -r["decided_count"],
        r["engine"],
    ))

    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2, default=str))
        return

    if not rows:
        if threshold is not None:
            print(
                f"No engines with rejection_rate >= {threshold} "
                f"(min decisions: {min_decisions})."
            )
        else:
            print(
                f"No engines with at least {min_decisions} "
                "decided actions yet."
            )
        return

    print(
        f"Rejection rates ({len(rows)} engines, "
        f"min decisions: {min_decisions}):"
    )
    print()
    print(
        "  engine                          decided  approved  "
        "rejected   rate"
    )
    for r in rows:
        prefix = "!" if r["rejection_rate"] >= 0.5 else " "
        engine_label = r["engine"][:30]
        print(
            f"{prefix} {engine_label:<30}  "
            f"{r['decided_count']:>7}  "
            f"{r['approved_count']:>8}  "
            f"{r['rejected_count']:>8}  "
            f"{r['rejection_rate']:>5.2f}"
        )

    alerts = [r for r in rows if r["rejection_rate"] >= 0.5]
    if alerts:
        print()
        print(
            f"ALERT: {len(alerts)} engine(s) have majority-"
            "rejected proposals. Inspect via "
            "`shopai approvals recent rejected --engine <name>` "
            "and consider disabling at the engine level."
        )


def _cmd_approvals_revenue_by_engine(args) -> None:
    """Per-engine revenue attribution.

    The complement to ``shopai approvals rejection-rates``:
    that surfaces the engines operators veto; this surfaces
    the engines that DRIVE revenue. Both are useful triage
    inputs — an engine producing $50k net but with a 70%
    rejection rate is BOTH valuable (when operators approve)
    AND noisy (operators are spending time vetoing).

    Three sort modes:
      - ``net`` (default): net_revenue desc — what each engine
        actually contributed after refunds. Most operator-useful.
      - ``gross``: gross_revenue desc — ignores refunds, useful
        when investigating an engine's headline numbers before
        the refund picture.
      - ``per-positive``: revenue_per_positive_outcome desc —
        the engine's "average impact when something good
        happens". Cross-engine comparison independent of volume.
    """
    from core.approval import get_approval_queue

    try:
        queue = get_approval_queue()
        stats = queue.revenue_attribution_stats()
    except Exception as exc:  # noqa: BLE001
        logger.debug("revenue_attribution_stats raised: %s", exc)
        stats = {}

    sort_key = getattr(args, "sort", "net") or "net"
    top_n = max(1, int(getattr(args, "top", 20)))

    rows = [{"engine": e, **s} for e, s in stats.items()]

    if sort_key == "net":
        rows.sort(key=lambda r: (
            -r["net_revenue"], r["engine"],
        ))
    elif sort_key == "gross":
        rows.sort(key=lambda r: (
            -r["gross_revenue"], r["engine"],
        ))
    else:  # per-positive
        # Engines without a per-positive (zero positive outcomes)
        # sort to the bottom.
        rows.sort(key=lambda r: (
            -(r["revenue_per_positive_outcome"] or -1.0),
            r["engine"],
        ))

    rows = rows[:top_n]

    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2, default=str))
        return

    if not rows:
        print(
            "No engines have matched outcomes with revenue yet."
        )
        return

    print(
        f"Revenue by engine ({len(rows)} engines, sort={sort_key}):"
    )
    print()
    print(
        "  engine                          gross     refunded     "
        "net   pos  per-positive"
    )
    for r in rows:
        engine_label = r["engine"][:30]
        per_pos = r["revenue_per_positive_outcome"]
        per_pos_display = (
            f"{per_pos:>9.2f}" if per_pos is not None else "       --"
        )
        print(
            f"  {engine_label:<30}  "
            f"{r['gross_revenue']:>9.2f}  "
            f"{r['refunded_revenue']:>9.2f}  "
            f"{r['net_revenue']:>9.2f}  "
            f"{r['positive_outcomes']:>4}  "
            f"{per_pos_display}"
        )


def _cmd_approvals_history(args) -> None:
    """Append-only decision audit trail.

    Two reading modes share the same verb:
      - ``shopai approvals history <action_id>`` — chronological
        lifecycle of ONE action (oldest first; reads top-to-bottom
        as the operator/system made each call).
      - ``shopai approvals history`` — global ticker (newest first)
        for cross-action audit sweeps.

    Filters compose: ``--by alice`` shows just alice's calls,
    ``--by system`` shows just the executor / TTL-sweep
    transitions.
    """
    from core.approval import get_approval_queue

    try:
        queue = get_approval_queue()
        rows = queue.list_decisions(
            action_id=args.action_id,
            decided_by=args.by,
            limit=args.limit,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("decision history lookup failed: %s", exc)
        rows = []

    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2, default=str))
        return

    if not rows:
        scope = (
            f"for {args.action_id}" if args.action_id else "globally"
        )
        by = f" by={args.by!r}" if args.by else ""
        print(f"No decisions recorded {scope}{by}.")
        return

    title = (
        f"Decision history for {args.action_id} "
        f"({len(rows)} transitions):"
        if args.action_id
        else f"Recent decisions ({len(rows)}):"
    )
    print(title)
    now = time.time()
    for r in rows:
        ago = (
            _format_age(now - r["occurred_at"])
            if r.get("occurred_at") else "?"
        )
        actor = (r.get("decided_by") or "?")[:14]
        decision = (r.get("decision") or "?")[:9]
        reason = r.get("reason") or ""
        # Global feed shows action_id; per-action feed omits it
        # since every row shares the same id
        if args.action_id:
            line = (
                f"  {decision:<9} by {actor:<14} {ago}"
            )
        else:
            line = (
                f"  {r['action_id'][:18]:<18} "
                f"{decision:<9} by {actor:<14} {ago}"
            )
        if reason:
            if len(reason) > 60:
                reason = reason[:57] + "..."
            line += f"  reason={reason}"
        print(line)


def _cmd_approvals_pending(args) -> None:
    from core.approval import get_approval_queue
    queue = get_approval_queue()
    actions = queue.list_pending(engine=args.engine, limit=args.limit)
    if not actions:
        if args.engine:
            print(f"No pending actions for engine {args.engine!r}.")
        else:
            print("No pending actions.")
        return
    print(f"Pending actions ({len(actions)}):")
    for a in actions:
        narrative = (a.narrative or "")[:80]
        conf = (
            f" conf={a.confidence:.2f}"
            if isinstance(a.confidence, (int, float))
            else ""
        )
        print(f"  [{a.id}] {a.engine}/{a.action_type}{conf}")
        if narrative:
            print(f"      {narrative}")


def _cmd_approvals_stats(args) -> None:
    from core.approval import get_approval_queue
    queue = get_approval_queue()

    if getattr(args, "by_engine", False):
        by_engine = queue.stats_by_engine()
        if not by_engine:
            print("Approval queue is empty.")
            return
        statuses = ["pending", "approved", "executed",
                    "failed", "rejected", "expired"]
        col = 10
        header = (
            f"{'engine':<24}"
            + "".join(f"{s:>{col}}" for s in statuses)
        )
        print("Approval queue by engine:")
        print(f"  {header}")
        print(f"  {'-' * len(header)}")
        for engine in sorted(by_engine):
            counts = by_engine[engine]
            row = (
                f"{engine:<24}"
                + "".join(
                    f"{counts.get(s, 0):>{col}}" for s in statuses
                )
            )
            print(f"  {row}")
        return

    stats = queue.stats()
    print("Approval queue stats:")
    for status, count in sorted(stats.items()):
        print(f"  {status:<10} {count}")


def _cmd_approvals_show(args) -> None:
    from core.approval import get_approval_queue
    queue = get_approval_queue()
    action = queue.get(args.action_id)
    if action is None:
        print(f"Unknown action id: {args.action_id}")
        sys.exit(1)
    payload = action.to_dict()
    try:
        from core.knowledge import enrich_action_dict
        payload = enrich_action_dict(payload)
    except Exception:  # noqa: BLE001
        # Knowledge layer optional — degrade silently
        pass

    # Embed outcomes by default for EXECUTED actions — the
    # whole point of ``show`` is "give me everything about this
    # action", and the downstream webhook attribution IS part of
    # "everything". Operators opt out via ``--no-outcomes`` when
    # the action's outcome history is large or irrelevant
    # (PENDING / REJECTED actions never have outcomes).
    include_outcomes = (
        not getattr(args, "no_outcomes", False)
        and action.status.value == "executed"
    )
    if include_outcomes:
        try:
            payload["outcomes"] = queue.get_outcomes(args.action_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("outcome lookup failed: %s", exc)
            payload["outcomes"] = []

    print(json.dumps(payload, indent=2, default=str))


def _cmd_approvals_approve(args) -> None:
    from core.approval import get_approval_queue
    queue = get_approval_queue()
    action = queue.approve(
        args.action_id,
        decided_by=args.by,
        reason=args.reason,
    )
    if action is None:
        print(
            f"Cannot approve {args.action_id} "
            "(unknown or already resolved)."
        )
        sys.exit(1)
    print(f"Approved: {action.id} ({action.engine}/{action.action_type})")
    if args.execute:
        _run_execute(args.action_id)


def _cmd_approvals_reject(args) -> None:
    from core.approval import get_approval_queue
    action = get_approval_queue().reject(
        args.action_id,
        decided_by=args.by,
        reason=args.reason,
    )
    if action is None:
        print(
            f"Cannot reject {args.action_id} "
            "(unknown or already resolved)."
        )
        sys.exit(1)
    print(f"Rejected: {action.id} ({action.engine}/{action.action_type})")


def _cmd_approvals_execute(args) -> None:
    _run_execute(args.action_id)


def _cmd_approvals_sweep(args) -> None:
    max_age = _parse_age_spec(args.older_than)
    if max_age is None:
        print(
            f"Invalid --older-than value: {args.older_than!r} "
            "(expected e.g. 60s, 30m, 24h, 7d)"
        )
        sys.exit(1)

    from core.approval.queue import (
        ApprovalStatus, get_approval_queue,
    )
    queue = get_approval_queue()

    if args.dry_run:
        # Inspect without writing — list PENDING actions older than cutoff
        cutoff = time.time() - max_age
        candidates = [
            a for a in queue.list_pending(limit=10_000)
            if a.proposed_at < cutoff
        ]
        if not candidates:
            print(
                f"Dry run: no PENDING actions older than {args.older_than}."
            )
            return
        print(
            f"Dry run: {len(candidates)} action(s) would expire "
            f"(older than {args.older_than}):"
        )
        for a in candidates:
            age = int(time.time() - a.proposed_at)
            print(
                f"  {a.id} {a.engine}/{a.action_type} "
                f"(age {_format_age(age)})"
            )
        return

    expired = queue.expire_stale(max_age_seconds=max_age)
    if not expired:
        print(
            f"Sweep complete: no PENDING actions older than "
            f"{args.older_than}."
        )
        return
    print(f"Sweep complete: {len(expired)} action(s) expired.")
    for a in expired:
        print(f"  {a.id} {a.engine}/{a.action_type}")


def _cmd_approvals_approve_all(args) -> None:
    """Bulk-approve PENDING actions matching engine + confidence filters.

    Saves the operator from clicking through dozens of high-confidence
    proposals one at a time. Pairs naturally with ``--execute`` so a
    triage round can land 20 dispatches in a single command.
    """
    from core.approval.queue import get_approval_queue

    queue = get_approval_queue()
    candidates = queue.list_pending(engine=args.engine, limit=10_000)
    if args.min_confidence is not None:
        candidates = [
            a for a in candidates
            if (a.confidence or 0.0) >= args.min_confidence
        ]

    if not candidates:
        filt = []
        if args.engine:
            filt.append(f"engine={args.engine}")
        if args.min_confidence is not None:
            filt.append(f"min_confidence={args.min_confidence}")
        suffix = f" ({', '.join(filt)})" if filt else ""
        print(f"No PENDING actions matched{suffix}.")
        return

    if args.dry_run:
        print(
            f"Dry run: {len(candidates)} action(s) would be approved:"
        )
        for a in candidates:
            conf = (
                f"conf={a.confidence:.2f}"
                if a.confidence is not None else "conf=-"
            )
            print(
                f"  {a.id} {a.engine}/{a.action_type} {conf}"
            )
        return

    approved_count = 0
    executed_count = 0
    failed_ids: list[str] = []

    for a in candidates:
        decision = queue.approve(
            a.id, decided_by=args.by, reason=args.reason,
        )
        if decision is None:
            # Race: approved/rejected/expired between list and approve.
            failed_ids.append(a.id)
            continue
        approved_count += 1
        if args.execute:
            from core.approval.executor import execute_action
            from core.approval.queue import ApprovalStatus
            result = execute_action(a.id)
            if (
                result is not None
                and result.status == ApprovalStatus.EXECUTED
            ):
                executed_count += 1

    print(
        f"Approved {approved_count} action(s)"
        + (f", executed {executed_count}" if args.execute else "")
        + "."
    )
    if failed_ids:
        print(f"  Skipped (state changed): {len(failed_ids)}")


def _cmd_approvals_recent(args) -> None:
    """List recent actions by status — operator triage feed.

    PENDING is shown oldest-first (review queue order); everything
    else is shown newest-first (recent activity).
    """
    import time as _time

    from core.approval.queue import ApprovalStatus, get_approval_queue

    try:
        status = ApprovalStatus(args.status)
    except ValueError:
        print(f"Unknown status: {args.status}")
        sys.exit(1)

    queue = get_approval_queue()
    actions = queue.list_by_status(
        status, engine=args.engine, limit=args.limit,
    )
    if not actions:
        suffix = f" for engine '{args.engine}'" if args.engine else ""
        print(f"No {status.value.upper()} actions{suffix}.")
        return

    print(f"Recent {status.value.upper()} actions ({len(actions)}):")
    now = _time.time()
    for a in actions:
        timestamp = a.decided_at if status != ApprovalStatus.PENDING else (
            a.proposed_at
        )
        ago = _format_age(now - timestamp) if timestamp else "?"
        label = f"{a.engine}/{a.action_type}"
        if len(label) > 40:
            label = label[:37] + "..."
        line = f"  {a.id[:18]:<18} {label:<40} {ago}"
        # For FAILED/REJECTED, also surface the reason or error
        if status == ApprovalStatus.FAILED and a.result:
            err = a.result.get("error") or a.result.get("status", "?")
            line += f"  err={err}"
        elif status == ApprovalStatus.REJECTED and a.decision_reason:
            line += f"  reason={a.decision_reason}"
        elif status == ApprovalStatus.EXPIRED and a.decision_reason:
            line += f"  ({a.decision_reason})"
        print(line)


def _cmd_approvals_audit(args) -> None:
    """Dispatcher coverage audit — flags Pattern K gaps.

    Cross-references action_types enqueued in engines/ against the
    registered dispatcher table. Exits 1 if any missing — useful as
    a CI guard so a new engine writeback without a matching
    dispatcher fails the build instead of failing silently at
    execute time.
    """
    from pathlib import Path

    from core.approval.coverage_audit import EnqueueCall, audit_coverage

    report = audit_coverage(Path(args.engines_root))

    print(
        f"Dispatcher coverage audit ({args.engines_root})"
    )
    print(
        f"  Engine enqueue sites:  {len(report.enqueued)}"
    )
    print(
        f"  Registered dispatchers: {len(report.registered)}"
    )
    print(
        f"  Missing: {len(report.missing)}    "
        f"Orphaned: {len(report.orphaned)}"
    )

    if report.missing:
        print()
        print("Missing dispatchers (Pattern K — silent execute failures):")
        # Group by action_type so each gap lists its call sites
        by_type: dict[str, list[EnqueueCall]] = {}
        for site in report.enqueued:
            if site.action_type in report.missing:
                by_type.setdefault(site.action_type, []).append(site)
        for action_type in sorted(by_type):
            print(f"  {action_type}")
            for s in by_type[action_type]:
                print(f"    {s.file_path}:{s.line}")

    if report.orphaned:
        print()
        print("Orphaned dispatchers (no engine enqueues these):")
        for o in report.orphaned:
            print(f"  {o}")

    if report.has_gaps:
        print()
        print(
            "Audit failed: register dispatchers for the missing action_types "
            "in core/approval/dispatchers.py."
        )
        sys.exit(1)

    print()
    print("Coverage OK — all enqueued action_types have dispatchers.")


def _parse_age_spec(spec: str) -> float | None:
    """Thin shim delegating to ``core.approval.queue.parse_age_spec``.

    Kept for backward compat with existing tests that import this
    by name; new callers should use the public function directly.
    """
    from core.approval.queue import parse_age_spec
    return parse_age_spec(spec)


def _run_execute(action_id: str) -> None:
    from core.approval.executor import execute_action
    result = execute_action(action_id)
    if result is None:
        print(
            f"Execute no-op: {action_id} "
            "(unknown, not approved, or already resolved)."
        )
        sys.exit(1)
    print(f"Executed: {action_id} -> {result.status.value}")
    if result.result:
        print(json.dumps(result.result, indent=2, default=str))


def _cmd_pipeline(pipeline_name: str, input_path: str) -> None:
    with open(input_path) as f:
        data = json.load(f)

    if pipeline_name == "product":
        from data_pipeline.pipelines.product_pipeline import ProductPipeline
        result = ProductPipeline().run(data)
    elif pipeline_name == "marketing":
        from data_pipeline.pipelines.marketing_pipeline import MarketingPipeline
        result = MarketingPipeline().run(data)
    elif pipeline_name == "analytics":
        from data_pipeline.pipelines.analytics_pipeline import AnalyticsPipeline
        result = AnalyticsPipeline().run(data)
    else:
        print(f"Unknown pipeline: {pipeline_name}")
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))


# ── Main ─────────────────────────────────────────────────────

def _validate_startup_config(command: str | None) -> None:
    """Run config validation at startup and fail fast on hard errors.

    - Skipped for the `config` subcommand itself so users can inspect bad
      configs via `shopai config check` without being blocked.
    - Skipped when no command is given (argparse will print help).
    - Type / range errors are printed to stderr and exit(2).
    - Cross-field warnings are printed to stderr but do not block.
    - An env var `SHOPAI_SKIP_CONFIG_CHECK=1` bypasses this entirely for
      emergency recovery.
    """
    if command in (None, "config"):
        return
    if os.environ.get("SHOPAI_SKIP_CONFIG_CHECK") == "1":
        return
    try:
        from infrastructure.config.schema import validate_config
    except Exception:  # noqa: BLE001
        return  # schema module broken — don't block the app

    result = validate_config()
    if result.warnings:
        for w in result.warnings:
            print(f"config warning: {w}", file=sys.stderr)
    if not result.ok():
        for err in result.errors:
            print(f"config error: {err}", file=sys.stderr)
        print(
            "\nFix the errors above or run `shopai config check` for "
            "details. Set SHOPAI_SKIP_CONFIG_CHECK=1 to bypass.",
            file=sys.stderr,
        )
        sys.exit(2)


def main(argv: list[str] | None = None) -> None:
    # Load .env if it exists
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        try:
            from infrastructure.config.env_manager import EnvManager
            EnvManager().load_env_file(env_path)
        except Exception:
            pass

    parser = build_parser()
    args = parser.parse_args(argv)

    _validate_startup_config(getattr(args, "command", None))

    if args.command == "store":
        dispatch = {
            "add": _cmd_store_add,
            "list": _cmd_store_list,
            "switch": _cmd_store_switch,
            "status": _cmd_store_status,
            "connect": _cmd_store_connect,
            "remove": _cmd_store_remove,
            "configure": _cmd_store_configure,
        }
        handler = dispatch.get(args.store_action)
        if handler:
            handler(args)
        else:
            print("Usage: shopai store {add|list|switch|status|connect|remove|configure}")
        return

    if args.command == "db":
        if args.db_action == "status":
            _cmd_db_status()
        elif args.db_action == "migrate":
            _cmd_db_migrate()
        elif args.db_action == "info":
            _cmd_db_info()
        elif args.db_action == "backup":
            _cmd_db_backup(getattr(args, "out", None))
        elif args.db_action == "restore":
            _cmd_db_restore(
                args.archive, yes=getattr(args, "yes", False),
            )
        else:
            print("Usage: shopai db {status|migrate|info|backup|restore}")
        return

    if args.command == "goal":
        _cmd_goal(args)
        return

    if args.command == "config":
        if args.config_action == "check":
            _cmd_config_check()
        elif args.config_action == "show":
            _cmd_config_show()
        else:
            print("Usage: shopai config {check|show}")
        return

    if args.command == "mind":
        dispatch = {
            "status": _cmd_mind_status,
            "cycle": _cmd_mind_cycle,
            "reflect": _cmd_mind_reflect,
            "goals": _cmd_mind_goals,
            "skills": _cmd_mind_skills,
            "explain": _cmd_mind_explain,
            "think": _cmd_mind_think,
            "llm-status": _cmd_mind_llm_status,
        }
        handler = dispatch.get(args.mind_action)
        if handler:
            handler(args)
        else:
            print("Usage: shopai mind {status|cycle|reflect|goals|skills|explain}")
        return

    if args.command == "sync":
        _cmd_sync(args)
        return

    if args.command == "engines":
        _cmd_engines(
            by_goal=getattr(args, "by_goal", False),
            unmapped=getattr(args, "unmapped", False),
        )
        return

    if args.command == "engine-info":
        _cmd_engine_info(
            args.engine_name,
            as_json=getattr(args, "json", False),
        )
        return

    if args.command == "engine-calibration":
        _cmd_engine_calibration(args)
        return

    if args.command == "engines-calibration":
        _cmd_engines_calibration(args)
        return

    if args.command == "engine-scorecard":
        _cmd_engine_scorecard(args)
        return

    if args.command == "run":
        _cmd_run(args)
        return

    if args.command == "suggest":
        _cmd_suggest(args)
        return

    if args.command == "knowledge":
        _cmd_knowledge(args)
        return

    if args.command == "actions":
        _cmd_actions(args)
        return

    if args.command == "approvals":
        _cmd_approvals(args)
        return

    if args.command == "auto":
        _cmd_auto(args)
        return

    if args.command == "learn":
        _cmd_learn(args)
        return

    if args.command == "feedback":
        _cmd_feedback(args)
        return

    if args.command == "pipeline":
        _cmd_pipeline(args.pipeline_name, getattr(args, "input"))
        return

    if args.command == "health":
        _cmd_health()
        return

    if args.command == "status":
        _cmd_status(args)
        return

    if args.command == "loop":
        _cmd_loop(args)
        return

    if args.command == "outcomes":
        _cmd_outcomes(args)
        return

    if args.command == "setup":
        _cmd_setup()
        return

    if args.command == "start":
        from core.orchestrator import MainOrchestrator
        from engines.registry import engine_count
        orchestrator = MainOrchestrator()
        orchestrator.initialize()
        print(f"ShopAI orchestrator started. ({engine_count()} engines)")
        return

    if args.command == "stop":
        from core.orchestrator import MainOrchestrator
        orchestrator = MainOrchestrator()
        orchestrator.shutdown()
        print("ShopAI orchestrator stopped.")
        return

    if args.command == "workflow":
        from core.orchestrator import MainOrchestrator
        orchestrator = MainOrchestrator()
        orchestrator.initialize()
        params = json.loads(args.params)
        result = orchestrator.run_workflow(args.workflow_name, params)
        print(json.dumps(result, indent=2, default=str))
        orchestrator.shutdown()
        return

    if args.command == "version":
        _cmd_version(args)
        return

    if args.command == "server":
        from api.server import ShopAIServer
        print(f"Starting ShopAI API server on {args.host}:{args.port}")
        print(f"Webhook URL: http://{args.host}:{args.port}/api/webhook/shopify")
        print("Press Ctrl+C to stop.\n")
        server = ShopAIServer(args.host, args.port)
        server.start()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
