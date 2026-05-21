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
    status_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

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
    configure_p.add_argument(
        "--json", action="store_true",
        help=(
            "Emit the raw configurator result as JSON instead "
            "of the human-readable table. Useful for "
            "scripting / CI."
        ),
    )

    design_p = store_sub.add_parser(
        "design",
        help=(
            "Preview store-design recommendations: runs the "
            "store_design engine and renders its layout / "
            "color / navigation / mobile suggestions. Read-only "
            "-- doesn't modify the live store."
        ),
    )
    design_p.add_argument(
        "store_id", nargs="?",
        help="Store ID (default: active store)",
    )
    design_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )
    design_p.add_argument(
        "--section", default="all",
        choices=["all", "layout", "color", "navigation", "mobile"],
        help=(
            "Filter to one section. Default 'all' renders every "
            "recommendation block."
        ),
    )

    setup_p = store_sub.add_parser(
        "setup",
        help=(
            "End-to-end setup wizard: add credentials, test "
            "connection, plan the configurator, and optionally "
            "apply. Single command replaces add + connect + "
            "configure for first-time onboarding."
        ),
    )
    setup_p.add_argument(
        "store_id",
        help="Unique store identifier (e.g. my-store)",
    )
    setup_p.add_argument(
        "shop_url",
        help="Shopify store URL (e.g. mystore.myshopify.com)",
    )
    setup_p.add_argument(
        "--api-key", default="",
        help="Legacy API token (pre-2026)",
    )
    setup_p.add_argument(
        "--client-id", default="",
        help="OAuth Client ID (2026+)",
    )
    setup_p.add_argument(
        "--client-secret", default="",
        help="OAuth Client Secret (2026+)",
    )
    setup_p.add_argument(
        "--name", default="",
        help="Store display name",
    )
    setup_p.add_argument(
        "--niche", default="general",
        help=(
            "Store niche (drives the configurator templates). "
            "Default: general."
        ),
    )
    setup_p.add_argument(
        "--type", default="dropshipping", dest="store_type",
        choices=["dropshipping", "brand", "niche", "general"],
        help="Store type. Default: dropshipping.",
    )
    setup_p.add_argument(
        "--only", default="",
        help=(
            "Comma-separated features to plan/apply. Default: "
            "all 11 features."
        ),
    )
    setup_p.add_argument(
        "--apply", action="store_true",
        help=(
            "After planning, actually apply the configurator. "
            "Default: plan-only (safe)."
        ),
    )
    setup_p.add_argument(
        "--json", action="store_true",
        help="Emit a structured per-stage JSON envelope.",
    )

    report_p = store_sub.add_parser(
        "report",
        help=(
            "One-shot per-store report: stats + last sync + drift "
            "count + design lift + connection probe. The 'what's "
            "the state of this store?' command. Read-only."
        ),
    )
    report_p.add_argument(
        "store_id", nargs="?",
        help="Store ID (default: active store)",
    )
    report_p.add_argument(
        "--json", action="store_true",
        help="Emit a structured report envelope for automation.",
    )
    report_p.add_argument(
        "--skip-live", action="store_true",
        help=(
            "Skip live probes (verify + connection). Use when "
            "the store is offline or you only want cached state."
        ),
    )

    fleet_p = store_sub.add_parser(
        "fleet",
        help=(
            "Cross-store summary: aggregate stats + sync recency "
            "for every registered store in one view. The 'how is "
            "my whole empire doing?' command."
        ),
    )
    fleet_p.add_argument(
        "--json", action="store_true",
        help="Emit the raw fleet report as JSON.",
    )
    fleet_p.add_argument(
        "--sort-by", default="revenue",
        choices=["revenue", "products", "orders", "customers", "name"],
        help="Sort row order. Default: revenue (high to low).",
    )

    verify_p = store_sub.add_parser(
        "verify",
        help=(
            "Read-only audit: compares the live store against "
            "what the configurator would set up and reports the "
            "drift. Exits 1 when drift exists -- useful for CI / "
            "scheduled drift detection."
        ),
    )
    verify_p.add_argument(
        "store_id", nargs="?",
        help="Store ID (default: active store)",
    )
    verify_p.add_argument(
        "--only", default="",
        help=(
            "Comma-separated features to verify. Valid: "
            "collections, discounts, shipping, content, "
            "product_tags, ai_config, gifts, loyalty, referral, "
            "emails, payments. Default: all."
        ),
    )
    verify_p.add_argument(
        "--niche", default="",
        help="Override store niche (default: use stored niche)",
    )
    verify_p.add_argument(
        "--json", action="store_true",
        help="Emit the raw drift report as JSON.",
    )

    # ── World-model commands ─────────────────────────────────
    world_p = sub.add_parser(
        "world-model",
        help=(
            "Per-store world model: single dict that the AGI "
            "orchestrator reads before making decisions. "
            "Foundation for cross-store reasoning."
        ),
    )
    world_sub = world_p.add_subparsers(dest="world_action")

    world_show_p = world_sub.add_parser(
        "show",
        help="Render the world-model snapshot for one store",
    )
    world_show_p.add_argument(
        "store_id", nargs="?",
        help="Store ID (default: active store)",
    )
    world_show_p.add_argument(
        "--json", action="store_true",
        help="Emit the raw snapshot dict as JSON",
    )
    world_show_p.add_argument(
        "--skip-live", action="store_true",
        help=(
            "Skip live probes (connection + drift). Sync / "
            "design / approvals / decisions are local reads "
            "and always run."
        ),
    )

    world_fleet_p = world_sub.add_parser(
        "fleet",
        help=(
            "Cross-store world-model summary: render the "
            "snapshot for every registered store, side by side. "
            "The 'how does my whole fleet look right now?' "
            "command."
        ),
    )
    world_fleet_p.add_argument(
        "--json", action="store_true",
        help="Emit the raw fleet snapshot dict as JSON",
    )
    world_fleet_p.add_argument(
        "--skip-live", action="store_true",
        help=(
            "Skip live probes per store. Live probes can be "
            "slow at fleet scale (one connection test + "
            "configurator dry-run per store), so operators may "
            "want this flag for fast cron-able runs."
        ),
    )

    # ── Daily-brief command ──────────────────────────────────
    daily_p = sub.add_parser(
        "daily-brief",
        help=(
            "Empire-scale operator summary: per-store stats + "
            "engine activity + pending approvals + alerts, in "
            "one shot. The 'what happened across my fleet?' "
            "command."
        ),
    )
    daily_p.add_argument(
        "--window-hours", type=int, default=24,
        dest="window_hours",
        help="Activity window in hours (default: 24).",
    )
    daily_p.add_argument(
        "--json", action="store_true",
        help="Emit the raw brief as JSON.",
    )

    # ── Transfer (cross-store) commands ──────────────────────
    transfer_p = sub.add_parser(
        "transfer",
        help=(
            "Cross-store transfer learning: identify actions "
            "that worked on one store and suggest porting them "
            "to another. The empire-AGI payoff command."
        ),
    )
    transfer_sub = transfer_p.add_subparsers(dest="transfer_action")

    transfer_suggest_p = transfer_sub.add_parser(
        "suggest",
        help=(
            "Suggest action types that succeeded on the source "
            "store but haven't been tried on the target."
        ),
    )
    transfer_suggest_p.add_argument(
        "--from", required=True, dest="from_store",
        help="Source store ID (the one that has the success data)",
    )
    transfer_suggest_p.add_argument(
        "--to", required=True, dest="to_store",
        help="Target store ID (the one to suggest actions for)",
    )
    transfer_suggest_p.add_argument(
        "--engine", default="",
        help=(
            "Optional: filter to one engine. Default: scan all "
            "engines."
        ),
    )
    transfer_suggest_p.add_argument(
        "-k", "--k", type=int, default=5,
        help="Number of suggestions to return (default: 5).",
    )
    transfer_suggest_p.add_argument(
        "--json", action="store_true",
        help="Emit the raw suggestions as JSON.",
    )

    transfer_apply_p = transfer_sub.add_parser(
        "apply",
        help=(
            "Enqueue a transfer suggestion as a PENDING action "
            "on the target store. Operator reviews via "
            "``shopai approvals show`` and approves/rejects."
        ),
    )
    transfer_apply_p.add_argument(
        "--from", required=True, dest="from_store",
        help="Source store ID (the one with the success data)",
    )
    transfer_apply_p.add_argument(
        "--to", required=True, dest="to_store",
        help="Target store ID (where the action will be queued)",
    )
    transfer_apply_p.add_argument(
        "--engine", required=True,
        help="Engine to transfer from (e.g. loyalty)",
    )
    transfer_apply_p.add_argument(
        "--action-type", required=True, dest="action_type",
        help="Specific action_type to transfer (e.g. mint_loyalty_code)",
    )
    transfer_apply_p.add_argument(
        "--params-json", default="", dest="params_json",
        help=(
            "Optional JSON dict to override the source-store "
            "params. e.g. ``--params-json '{\"customer_id\": "
            "\"new-id\"}'``. Omit to use the source's most "
            "recent successful params verbatim."
        ),
    )
    transfer_apply_p.add_argument(
        "--narrative", default="",
        help=(
            "Optional operator note prepended to the auto-"
            "generated transfer narrative."
        ),
    )
    transfer_apply_p.add_argument(
        "--json", action="store_true",
        help="Emit the enqueued-action envelope as JSON.",
    )
    transfer_apply_p.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help=(
            "Preview the transfer without enqueueing. Shows the "
            "source template, merged params, and narrative that "
            "would be written. Same validation gates fire (source "
            "lookup, target duplicate-protection)."
        ),
    )

    transfer_sources_p = transfer_sub.add_parser(
        "sources",
        help=(
            "For a target store, rank OTHER stores in the "
            "fleet by transferable surface area: count of "
            "successful (engine, action_type) tuples on source "
            "that target hasn't tried. Tells operators which "
            "store to point ``transfer suggest --from`` at."
        ),
    )
    transfer_sources_p.add_argument(
        "--to", required=True, dest="to_store",
        help="Target store ID (the one to find sources for)",
    )
    transfer_sources_p.add_argument(
        "-k", "--k", type=int, default=5,
        help="Number of sources to return (default: 5).",
    )
    transfer_sources_p.add_argument(
        "--json", action="store_true",
        help="Emit the ranked sources as JSON.",
    )

    transfer_history_p = transfer_sub.add_parser(
        "history",
        help=(
            "List recent cross-store transfer apply events. "
            "Scans the approval queue for actions enqueued via "
            "``shopai transfer apply`` (narrative starts with "
            "``Transfer suggestion:``)."
        ),
    )
    transfer_history_p.add_argument(
        "--from", default="", dest="from_store",
        help="Filter to transfers originating from this store",
    )
    transfer_history_p.add_argument(
        "--to", default="", dest="to_store",
        help="Filter to transfers targeting this store",
    )
    transfer_history_p.add_argument(
        "--engine", default="",
        help="Filter to transfers of this engine",
    )
    transfer_history_p.add_argument(
        "--limit", type=int, default=20,
        help="Cap on history rows (default 20).",
    )
    transfer_history_p.add_argument(
        "--json", action="store_true",
        help="Emit the history rows as JSON.",
    )

    transfer_outcomes_p = transfer_sub.add_parser(
        "outcomes",
        help=(
            "For transferred actions that EXECUTED on the "
            "target store, show their measured outcomes "
            "(positive / negative / revenue) to see whether "
            "cross-store transfers are paying off."
        ),
    )
    transfer_outcomes_p.add_argument(
        "--from", default="", dest="from_store",
        help="Filter to transfers originating from this store",
    )
    transfer_outcomes_p.add_argument(
        "--to", default="", dest="to_store",
        help="Filter to transfers targeting this store",
    )
    transfer_outcomes_p.add_argument(
        "--engine", default="",
        help="Filter to transfers of this engine",
    )
    transfer_outcomes_p.add_argument(
        "--limit", type=int, default=20,
        help="Cap on executed-transfer rows scanned (default 20).",
    )
    transfer_outcomes_p.add_argument(
        "--json", action="store_true",
        help="Emit the outcomes rollup as JSON.",
    )

    transfer_credit_p = transfer_sub.add_parser(
        "credit",
        help=(
            "Attribute downstream transfer outcomes back to "
            "source actions. Answers 'which of my engine "
            "actions on store-A inspired successful transfers "
            "across the fleet?' Read-side analytics over the "
            "credit graph (PR #284)."
        ),
    )
    transfer_credit_p.add_argument(
        "--source-store", default="", dest="source_store",
        help=(
            "Optional: only credits for transfers originating "
            "from this store"
        ),
    )
    transfer_credit_p.add_argument(
        "--engine", default="",
        help="Optional: only credits for one engine",
    )
    transfer_credit_p.add_argument(
        "--limit", type=int, default=20,
        help=(
            "Cap on credit rows returned (default 20). The "
            "underlying scan covers up to 500 target actions."
        ),
    )
    transfer_credit_p.add_argument(
        "--json", action="store_true",
        help="Emit the credit graph as JSON.",
    )

    # ── Model-router commands ────────────────────────────────
    mr_p = sub.add_parser(
        "model-router",
        help=(
            "Cost-aware model router: classify prompts as local "
            "vs cloud and inspect daily budget. Layer 3 of the "
            "AGI orchestration stack."
        ),
    )
    mr_sub = mr_p.add_subparsers(dest="mr_action")

    mr_classify_p = mr_sub.add_parser(
        "classify",
        help="Classify a prompt (text on stdin or --prompt)",
    )
    mr_classify_p.add_argument(
        "--prompt", default="",
        help="Prompt text (omit to read from stdin)",
    )
    mr_classify_p.add_argument(
        "--hint", default="auto",
        choices=["auto", "local_only", "cloud_required"],
        help="Caller hint that overrides automatic classification",
    )
    mr_classify_p.add_argument(
        "--purpose", default="",
        help="Optional purpose label for the usage log",
    )
    mr_classify_p.add_argument(
        "--json", action="store_true",
        help="Emit the routing decision as JSON",
    )

    mr_budget_p = mr_sub.add_parser(
        "budget",
        help="Show recent usage + remaining cloud-budget estimate",
    )
    mr_budget_p.add_argument(
        "--window-hours", type=int, default=24,
        dest="window_hours",
        help="Rolling window in hours (default: 24)",
    )
    mr_budget_p.add_argument(
        "--json", action="store_true",
        help="Emit the budget report as JSON",
    )

    # ── Decision-retrieval (RAG) commands ────────────────────
    recall_p = sub.add_parser(
        "memory-recall",
        help=(
            "Decision-time RAG: retrieve past decisions similar "
            "to a query, joined with their outcomes. Layer 2 of "
            "the AGI orchestration stack."
        ),
    )
    recall_p.add_argument(
        "--engine", required=True,
        help="Engine to retrieve decisions from (required)",
    )
    recall_p.add_argument(
        "--action-type", default="", dest="action_type",
        help="Filter / boost by action_type (optional)",
    )
    recall_p.add_argument(
        "--capability", default="",
        help="Filter / boost by capability name (optional)",
    )
    recall_p.add_argument(
        "--params-json", default="", dest="params_json",
        help=(
            "JSON dict of params to compute overlap against "
            "(optional). e.g. --params-json '{\"discount_pct\": 10}'"
        ),
    )
    recall_p.add_argument(
        "-k", "--k", type=int, default=5,
        help="Number of results to return (default: 5)",
    )
    recall_p.add_argument(
        "--store", default="", dest="store_id",
        help=(
            "Optional: scope retrieval to one store. Default: "
            "fleet-wide (matches the cross-store transfer use "
            "case)."
        ),
    )
    recall_p.add_argument(
        "--since-hours", type=float, default=0,
        dest="since_hours",
        help=(
            "Optional: only retrieve decisions decided within "
            "the last N hours. Default 0 means no time filter "
            "(retrieval-layer recency decay still applies as a "
            "soft preference)."
        ),
    )
    recall_p.add_argument(
        "--json", action="store_true",
        help="Emit the raw retrieval list as JSON",
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

    engines_stats_p = sub.add_parser(
        "engines-stats",
        help=(
            "Aggregate engine activity: per-engine queue counts + "
            "wiring status + activity totals. The 'which engines "
            "are pulling weight?' command."
        ),
    )
    engines_stats_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the table view",
    )
    engines_stats_p.add_argument(
        "--top", type=int, default=10, metavar="N",
        help=(
            "How many top-activity engines to surface in the "
            "ranking. Default: 10."
        ),
    )
    engines_stats_p.add_argument(
        "--filter", default="all",
        choices=["all", "active", "idle"],
        help=(
            "Filter: 'all' (default) shows every engine, "
            "'active' restricts to engines with at least one "
            "queue action, 'idle' restricts to engines with "
            "no queue activity."
        ),
    )

    # Singular ``engine`` (vs plural ``engines``): drill into a
    # single engine's activity + outcomes. Sibling commands like
    # ``engine activity-window`` / ``engine outcomes`` can live
    # under this same parent.
    engine_p = sub.add_parser(
        "engine",
        help=(
            "Drill into a single engine: activity + outcomes + "
            "effectiveness over a recent window"
        ),
    )
    engine_sub = engine_p.add_subparsers(dest="engine_action")

    engine_pulse_p = engine_sub.add_parser(
        "pulse",
        help=(
            "Single-engine health pulse: composite 1-10 score + "
            "verdict (healthy/warning/unhealthy) over all signals. "
            "Use 'shopai engine pulse --fleet' for a fleet-wide "
            "leaderboard."
        ),
    )
    engine_pulse_p.add_argument(
        "engine_name", nargs="?", default=None,
        help=(
            "Engine to score (e.g. loyalty, cart_recovery). "
            "Omit when using --fleet."
        ),
    )
    engine_pulse_p.add_argument(
        "--fleet", action="store_true",
        help=(
            "Score every engine in ENGINE_GOAL_MAP and render a "
            "leaderboard ranked by score asc (sickest first). "
            "Exit code 1 if ANY engine is unhealthy."
        ),
    )
    engine_pulse_p.add_argument(
        "--verdict", choices=("healthy", "warning", "unhealthy"),
        default=None,
        help=(
            "When used with --fleet: only show engines with this "
            "verdict. No-op for single-engine mode."
        ),
    )
    engine_pulse_p.add_argument(
        "--history", action="store_true",
        help=(
            "Single-engine: also surface the recorded score "
            "trajectory from engine_health_history. Default "
            "30-day window. No-op when --fleet is set."
        ),
    )
    engine_pulse_p.add_argument(
        "--history-days", type=int, default=30,
        dest="history_days",
        help=(
            "Window (in days) for --history. Default 30. "
            "Capped at the data's natural retention."
        ),
    )
    engine_pulse_p.add_argument(
        "--json", action="store_true",
        help="Emit the raw health envelope(s) as JSON",
    )

    engine_summary_p = engine_sub.add_parser(
        "summary",
        help=(
            "Per-engine summary: queue counts by status, recent "
            "actions, outcome rollup + effectiveness score"
        ),
    )
    engine_summary_p.add_argument(
        "engine_name",
        help="Engine to drill into (e.g. loyalty, cart_recovery)",
    )
    engine_summary_p.add_argument(
        "--recent-n", type=int, default=5, dest="recent_n",
        help="How many recent actions to list. Default: 5.",
    )
    engine_summary_p.add_argument(
        "--json", action="store_true",
        help="Emit the raw summary envelope as JSON",
    )

    engine_guardrail_p = engine_sub.add_parser(
        "guardrail",
        help=(
            "Show AGI v2 guardrail state across all engines + "
            "recent-block counts. The 'is the AGI signal "
            "actually refusing actions?' command."
        ),
    )
    engine_guardrail_p.add_argument(
        "--window-hours", type=int, default=24,
        dest="window_hours",
        help="Block-count window in hours (default: 24).",
    )
    engine_guardrail_p.add_argument(
        "--recent", type=int, default=0, dest="recent_n",
        metavar="N",
        help=(
            "Additionally list the last N block events with "
            "their reason + age. Default 0 (counts only)."
        ),
    )
    engine_guardrail_p.add_argument(
        "--json", action="store_true",
        help="Emit the raw guardrail report as JSON",
    )

    engine_fleet_p = engine_sub.add_parser(
        "fleet",
        help=(
            "Show one engine's activity + outcomes across "
            "EVERY store in the fleet. Diagnoses 'where is "
            "this engine winning / losing?' -- inverse of "
            "transfer suggest."
        ),
    )
    engine_fleet_p.add_argument(
        "engine_name",
        help="Engine to inspect across stores",
    )
    engine_fleet_p.add_argument(
        "--window-hours", type=int, default=168,
        dest="window_hours",
        help=(
            "Activity window in hours (default: 168 = 7 days). "
            "Outcomes are pulled regardless of the window since "
            "the matching event can lag the action."
        ),
    )
    engine_fleet_p.add_argument(
        "--json", action="store_true",
        help="Emit the fleet report as JSON.",
    )

    engine_compare_p = engine_sub.add_parser(
        "compare",
        help=(
            "Head-to-head fleet comparison of two engines. "
            "Surfaces which one performs better (executed / "
            "outcome polarity / revenue) across the fleet "
            "for engine-selection decisions."
        ),
    )
    engine_compare_p.add_argument(
        "engine_a", help="First engine to compare",
    )
    engine_compare_p.add_argument(
        "engine_b", help="Second engine to compare",
    )
    engine_compare_p.add_argument(
        "--window-hours", type=int, default=168,
        dest="window_hours",
        help="Activity window in hours (default: 168 = 7 days).",
    )
    engine_compare_p.add_argument(
        "--json", action="store_true",
        help="Emit the compare report as JSON.",
    )

    engine_ranking_p = engine_sub.add_parser(
        "ranking",
        help=(
            "Rank ALL active engines fleet-wide by outcome "
            "score + executed count. The 'which engines are "
            "actually working?' command -- inverse of engine "
            "summary's per-engine drill."
        ),
    )
    engine_ranking_p.add_argument(
        "--window-hours", type=int, default=168,
        dest="window_hours",
        help="Activity window in hours (default: 168 = 7 days).",
    )
    engine_ranking_p.add_argument(
        "--limit", type=int, default=20,
        help="Cap on ranked engines (default 20).",
    )
    engine_ranking_p.add_argument(
        "--json", action="store_true",
        help="Emit the ranking as JSON.",
    )

    engine_alerts_p = engine_sub.add_parser(
        "alerts",
        help=(
            "Flag engines whose recent outcome score has "
            "degraded versus a longer baseline window. The "
            "'is anything quietly breaking?' command."
        ),
    )
    engine_alerts_p.add_argument(
        "--recent-hours", type=int, default=24,
        dest="recent_hours",
        help=(
            "Recent window in hours (default 24). The window "
            "scored against the baseline."
        ),
    )
    engine_alerts_p.add_argument(
        "--baseline-hours", type=int, default=168,
        dest="baseline_hours",
        help=(
            "Baseline window in hours (default 168 = 7 days). "
            "Engines whose recent score drops below baseline "
            "by --threshold get flagged."
        ),
    )
    engine_alerts_p.add_argument(
        "--threshold", type=float, default=0.2,
        help=(
            "Score-drop threshold (default 0.2 = 20 percentage "
            "points). Recent score must be below baseline by at "
            "least this to alert."
        ),
    )
    engine_alerts_p.add_argument(
        "--min-recent", type=int, default=3,
        dest="min_recent",
        help=(
            "Minimum recent polarised outcomes for an alert "
            "(default 3). Below this, the recent score is too "
            "noisy to trust."
        ),
    )
    engine_alerts_p.add_argument(
        "--per-store", action="store_true",
        help=(
            "Detect per-(engine, store_id) degradation "
            "instead of aggregating across stores. Catches "
            "'engine X dropped specifically on store_a' which "
            "fleet aggregation would hide. Empire-AGI pivot."
        ),
    )
    engine_alerts_p.add_argument(
        "--json", action="store_true",
        help="Emit the alerts as JSON.",
    )

    engines_writebacks_p = sub.add_parser(
        "engines-writebacks",
        help=(
            "Catalog Phase 6/7 writeback wireup state per "
            "engine (wired / advisory / partial)"
        ),
    )
    engines_writebacks_p.add_argument(
        "--filter", default="all",
        choices=["all", "wired", "advisory", "partial"],
        help=(
            "Filter the catalog to one status. Default 'all' "
            "shows every engine. 'wired' = full Phase 6/7 "
            "writeback. 'advisory' = engine only emits "
            "recommendations. 'partial' = half-wired (writer "
            "OR opt-in flag, not both)."
        ),
    )
    engines_writebacks_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the table view",
    )

    catalog_p = sub.add_parser(
        "catalog",
        help=(
            "Complete action surface: every registered dispatcher "
            "with its action_type, capability, claiming adapter, "
            "required scopes, and emitting engine -- in one shot"
        ),
    )
    catalog_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the table view",
    )
    catalog_p.add_argument(
        "--engine", default=None, metavar="NAME",
        help="Filter to entries emitted by a specific engine",
    )
    catalog_p.add_argument(
        "--action-type", default=None, metavar="TYPE",
        help="Filter to a specific action_type (exact match)",
    )
    catalog_p.add_argument(
        "--markdown", action="store_true",
        help=(
            "Emit a Markdown document instead of the text view. "
            "Suitable for committing to docs or pasting into a "
            "wiki/README. Mutually exclusive with --json."
        ),
    )
    catalog_p.add_argument(
        "--by-capability", action="store_true",
        help=(
            "Group entries by Shopify Capability enum value "
            "instead of listing per-action_type. Answers 'which "
            "action_types route through SHOPIFY_UPDATE_PRODUCT?'"
        ),
    )

    release_bundle_p = sub.add_parser(
        "release-bundle",
        help=(
            "Deploy-day capstone: generate every release "
            "artifact (snapshot + catalog.md + shopify.app.toml "
            "+ doctor.txt + README.md) into one folder. "
            "Refuses to write when the doctor flags failures."
        ),
    )
    release_bundle_p.add_argument(
        "--output", "-o", default="release",
        metavar="DIR",
        help=(
            "Target directory for the bundle. Default: "
            "``release/`` in the working directory."
        ),
    )
    release_bundle_p.add_argument(
        "--app-name", default="shopai",
        help="App name for shopify.app.toml. Default: shopai",
    )
    release_bundle_p.add_argument(
        "--app-host", default="https://YOUR_APP_HOST",
        help="Deployed app base URL. Default: placeholder.",
    )
    release_bundle_p.add_argument(
        "--api-version", default="2024-01",
        help="Shopify Admin API version. Default: 2024-01",
    )
    release_bundle_p.add_argument(
        "--force", action="store_true",
        help="Overwrite the output directory if it exists.",
    )
    release_bundle_p.add_argument(
        "--skip-live", action="store_true",
        help=(
            "Skip the live-API drift checks when collecting "
            "doctor verdicts."
        ),
    )
    release_bundle_p.add_argument(
        "--write-on-warning", action="store_true",
        help=(
            "Emit the bundle even if the doctor flagged failures "
            "(initial bring-up before a live app exists)."
        ),
    )

    learning_p = sub.add_parser(
        "learning",
        help=(
            "Inspect what the autonomous learning loop has "
            "recorded -- MemoryIntelligence rules + "
            "DataArchitecture attach rate + LearningLoop "
            "memory layers in one shot."
        ),
    )
    learning_sub = learning_p.add_subparsers(dest="learning_action")
    learning_stats = learning_sub.add_parser(
        "stats",
        help=(
            "Aggregate stats: total memories, failures, rules, "
            "attach rate, per-engine breakdown. The 'what is "
            "Phase 8 learning?' command."
        ),
    )
    learning_stats.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )
    learning_stats.add_argument(
        "--top", type=int, default=10, metavar="N",
        help=(
            "How many top categories to surface in the "
            "per-engine breakdown. Default: 10."
        ),
    )

    snapshot_p = sub.add_parser(
        "snapshot",
        help=(
            "Capture the entire system state -- catalog + engine "
            "counts + every audit + doctor verdicts -- into one "
            "committable JSON artifact. Operators commit "
            "snapshots and diff them across releases."
        ),
    )
    snapshot_p.add_argument(
        "--output", "-o", default=None, metavar="FILE",
        help=(
            "Write the snapshot JSON to FILE. Default: stdout. "
            "Refuses to overwrite an existing file unless "
            "--force is passed."
        ),
    )
    snapshot_p.add_argument(
        "--force", action="store_true",
        help="Overwrite the output file if it exists.",
    )
    snapshot_p.add_argument(
        "--skip-live", action="store_true",
        help=(
            "Skip the live drift checks (live scope + live "
            "webhook) when collecting doctor verdicts."
        ),
    )
    snapshot_p.add_argument(
        "--diff", default=None, metavar="BASELINE_FILE",
        help=(
            "Compare the current snapshot against BASELINE_FILE "
            "and emit only the differences. Operators commit a "
            "snapshot at release N and run --diff against it at "
            "release N+1 to surface drift."
        ),
    )

    eng_info = sub.add_parser("engine-info", help="Show engine details")
    eng_info.add_argument("engine_name", help="Engine name")
    eng_info.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    shopify_scopes_p = sub.add_parser(
        "shopify-scopes",
        help=(
            "OAuth scope manifest aggregated across every "
            "Shopify adapter (install-time install requirements)"
        ),
    )
    shopify_scopes_p.add_argument(
        "--per-adapter", action="store_true",
        help=(
            "Render scopes grouped per adapter (default: union "
            "list suitable for an install manifest)"
        ),
    )
    shopify_scopes_p.add_argument(
        "--show-gaps", action="store_true",
        help=(
            "Include the list of adapters that haven't wired "
            "required_scopes yet (rollout tracking)"
        ),
    )
    shopify_scopes_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    shopify_scopes_audit_p = sub.add_parser(
        "shopify-scopes-audit",
        help=(
            "CI gate: exit 1 if any Shopify adapter is missing "
            "a scope declaration (mirrors `approvals audit` for "
            "Pattern K)"
        ),
    )
    shopify_scopes_audit_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    capabilities_audit_p = sub.add_parser(
        "capabilities-audit",
        help=(
            "CI gate (Pattern Y): exit 1 if any Capability."
            "SHOPIFY_* enum value is unclaimed by every adapter "
            "(mirrors Pattern K dispatcher audit). 0 = clean, "
            "1 = at least one gap."
        ),
    )
    capabilities_audit_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )
    capabilities_audit_p.add_argument(
        "--show-multi-claimed", action="store_true",
        help=(
            "Also list capabilities claimed by 2+ adapters "
            "(warning -- usually legitimate, sometimes routing "
            "ambiguity)"
        ),
    )

    engines_cap_audit_p = sub.add_parser(
        "engines-capability-audit",
        help=(
            "CI gate (Pattern I): every `capability_name=` string "
            "in engines/ must reference a real Capability enum "
            "member claimed by 1+ adapter. 0 = clean, 1 = gap."
        ),
    )
    engines_cap_audit_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    audit_p = sub.add_parser(
        "audit",
        help=(
            "Run all five institutional audits in one shot "
            "(Pattern K + OAuth scope + Pattern Y + Pattern I + "
            "Pattern J). Exit 0 = all pass; 1 = at least one "
            "audit failed. The single-command companion to the "
            "individual `*-audit` surfaces."
        ),
    )
    audit_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )
    audit_p.add_argument(
        "--only", default=None,
        choices=[
            "pattern_k", "oauth", "pattern_y",
            "pattern_i", "pattern_j", "pattern_z",
            "pattern_q",
        ],
        metavar="NAME",
        help=(
            "Run a single named audit instead of all five. "
            "Useful for fast pre-commit checks targeting one "
            "concern."
        ),
    )

    pattern_j_audit_p = sub.add_parser(
        "pattern-j-audit",
        help=(
            "CI gate (Pattern J): writes to MemoryIntelligence / "
            "DataArchitecture / LearningLoop must come from the "
            "Phase 8 recorder or have a test-env guard. 0 = clean, "
            "1 = at least one unguarded write-site."
        ),
    )
    pattern_j_audit_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    pattern_q_audit_p = sub.add_parser(
        "pattern-q-audit",
        help=(
            "CI gate (Pattern Q): every registered engine's "
            "run() must return the canonical "
            "{status, data, meta, error} envelope. 0 = clean, "
            "1 = at least one engine violates the contract."
        ),
    )
    pattern_q_audit_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    pattern_z_audit_p = sub.add_parser(
        "pattern-z-audit",
        help=(
            "CI gate (Pattern Z): every writer module "
            "(*_applier.py / *_minter.py / *_payer.py) that "
            "calls a Shopify mutation MUST also call "
            "record_writeback. 0 = clean, 1 = at least one "
            "writer skipping Phase 8 feedback."
        ),
    )
    pattern_z_audit_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    shopify_scopes_live_p = sub.add_parser(
        "shopify-scopes-live-check",
        help=(
            "Compare declared OAuth scopes vs the live app's "
            "granted scopes (catches install-time misconfig)"
        ),
    )
    shopify_scopes_live_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    shopify_webhooks_live_p = sub.add_parser(
        "shopify-webhooks-live-check",
        help=(
            "Compare declared webhook subscriptions vs the live "
            "app's registered topics (catches outcome attribution "
            "drift + GDPR subscription gaps)"
        ),
    )
    shopify_webhooks_live_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    launch_p = sub.add_parser(
        "launch",
        help=(
            "Flagship: single-command store launch. Runs the "
            "autonomous setup pipeline (policies + pages "
            "today; brand / discount / collections / design "
            "as they land) and prints a checklist of what "
            "applied vs failed. Mission-critical wrapper "
            "around launch_orchestrator.launch_store."
        ),
    )
    launch_p.add_argument(
        "store_name",
        help=(
            "Display name for the store (required). Threads "
            "into policies, pages, and the founder/about flow."
        ),
    )
    launch_p.add_argument(
        "--niche", default="general",
        choices=[
            "general", "beauty", "fashion", "home",
            "tech", "food",
        ],
        help="Niche key (default: general)",
    )
    launch_p.add_argument(
        "--region", default="us",
        choices=["us", "eu", "uk"],
        help="Region code (default: us)",
    )
    launch_p.add_argument(
        "--founder-name", default=None,
        help="Optional founder name for the About page",
    )
    launch_p.add_argument(
        "--store-id", default=None,
        help=(
            "Optional store_id for Pattern Z scope on every "
            "fan-out write (falls back to active store "
            "thread-local)"
        ),
    )
    launch_p.add_argument(
        "--include-legal-notice", action="store_true",
        help="Forwarded to policy_generator",
    )
    launch_p.add_argument(
        "--include-subscription-policy", action="store_true",
        help="Forwarded to policy_generator",
    )
    launch_p.add_argument(
        "--logo-url", default=None,
        help=(
            "Public HTTPS URL for the brand logo. When set "
            "(alone or with the other brand-url flags), Step 5 "
            "uploads it via SHOPIFY_CREATE_FILES. Omit to skip "
            "the step entirely."
        ),
    )
    launch_p.add_argument(
        "--favicon-url", default=None,
        help="Public HTTPS URL for the brand favicon",
    )
    launch_p.add_argument(
        "--hero-url", default=None,
        help="Public HTTPS URL for the brand hero image",
    )
    launch_p.add_argument(
        "--og-image-url", default=None,
        help="Public HTTPS URL for the social-sharing image",
    )
    launch_p.add_argument(
        "--strict", action="store_true",
        help=(
            "Exit 1 when ready_to_launch is False. Default "
            "behaviour is exit 0 -- the checklist is the "
            "operator-visible result either way."
        ),
    )
    launch_p.add_argument(
        "--audit", action="store_true",
        help=(
            "After launch, automatically run "
            "``shopai launch-audit`` and print the readiness "
            "summary so the operator sees one combined result. "
            "Useful for sanity-checking that the orchestrator "
            "left the store in a launchable state per the "
            "audit's source of truth."
        ),
    )
    launch_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    launch_audit_p = sub.add_parser(
        "launch-audit",
        help=(
            "Read-only launch-readiness audit -- reports per-"
            "check pass/fail PLUS an operator-actionable "
            "fix_hint for each gap (legal, pages, discounts, "
            "collections, design, products, shipping, "
            "fulfillment). Records completion_pct via Pattern Z."
        ),
    )
    launch_audit_p.add_argument(
        "--store", default=None,
        help=(
            "Store ID for Pattern Z scope (falls back to active "
            "store thread-local)"
        ),
    )
    launch_audit_p.add_argument(
        "--expected-products", type=int, default=1,
        help=(
            "Minimum ACTIVE product count to pass the "
            "active_products check (default: 1)"
        ),
    )
    launch_audit_p.add_argument(
        "--expected-collections", type=int, default=1,
        help=(
            "Minimum collection count to pass the "
            "curated_collections check (default: 1)"
        ),
    )
    launch_audit_p.add_argument(
        "--expected-discounts", type=int, default=1,
        help=(
            "Minimum active discount count to pass the "
            "active_discounts check (default: 1)"
        ),
    )
    launch_audit_p.add_argument(
        "--strict", action="store_true",
        help=(
            "Exit 1 when ready_to_launch is False (default "
            "behaviour is informational exit 0 so the audit "
            "is safe to run on a cron alongside daily-brief)"
        ),
    )
    launch_audit_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    post_launch_p = sub.add_parser(
        "post-launch",
        help=(
            "Polish flow that runs AFTER ``shopai launch``: "
            "enrich-seo + enrich-descriptions in one shot. "
            "Default is read-only preview; pass --apply to "
            "actually write to Shopify."
        ),
    )
    post_launch_p.add_argument(
        "--store", default=None,
        help=(
            "Store ID for Pattern Z scope (falls back to active "
            "store thread-local)"
        ),
    )
    post_launch_p.add_argument(
        "--niche", default="general",
        choices=[
            "general", "beauty", "fashion", "home",
            "tech", "food",
        ],
        help="Niche key passed to both enrichers (default: general)",
    )
    post_launch_p.add_argument(
        "--store-name", default="",
        help="Optional brand suffix passed to enrich-seo.",
    )
    post_launch_p.add_argument(
        "--limit", type=int, default=100,
        help="Max products to fetch + enrich (default: 100)",
    )
    post_launch_p.add_argument(
        "--min-description-length", type=int, default=80,
        help=(
            "Skip description enrichment for products whose "
            "existing description is at least this many chars."
        ),
    )
    post_launch_p.add_argument(
        "--overwrite-seo", action="store_true",
        help=(
            "Replace existing SEO metadata even when non-empty"
        ),
    )
    post_launch_p.add_argument(
        "--apply", action="store_true",
        help=(
            "WRITE: push both enrichments via "
            "SHOPIFY_UPDATE_PRODUCT. Default is read-only "
            "preview."
        ),
    )
    post_launch_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    shopify_doctor_p = sub.add_parser(
        "shopify-doctor",
        help=(
            "Aggregate health check — runs every institutional "
            "protection audit (Pattern K dispatchers + OAuth "
            "scope coverage + Pattern Y capabilities + live "
            "scope drift) in one shot"
        ),
    )
    shopify_doctor_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )
    shopify_doctor_p.add_argument(
        "--skip-live", action="store_true",
        help=(
            "Skip the live scope drift check (don't call "
            "Shopify). Use in CI / dev environments without "
            "live credentials."
        ),
    )

    doctor_p = sub.add_parser(
        "doctor",
        help=(
            "Unified health check -- runs shopify-doctor + "
            "approvals doctor in one shot. The 'is everything "
            "OK?' command."
        ),
    )
    doctor_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )
    doctor_p.add_argument(
        "--skip-live", action="store_true",
        help=(
            "Skip the live drift checks (live scope + live "
            "webhook). Use in CI / dev environments without "
            "live credentials."
        ),
    )
    doctor_p.add_argument(
        "--stale-pending-hours", type=float, default=24.0,
        metavar="H",
        help=(
            "PENDING actions older than this many hours flag "
            "the approvals section. Default: 24h."
        ),
    )
    doctor_p.add_argument(
        "--failure-rate-warn", type=float, default=0.25,
        metavar="R",
        help=(
            "Recent dispatch failure-rate threshold for warn. "
            "Default: 0.25."
        ),
    )

    shopify_install_manifest_p = sub.add_parser(
        "shopify-install-manifest",
        help=(
            "Generate a Shopify app install manifest fragment "
            "(access_scopes for shopify.app.toml) from the "
            "registry"
        ),
    )
    shopify_install_manifest_p.add_argument(
        "--format", default="toml",
        choices=["toml", "json", "csv"],
        help=(
            "Output format. 'toml' = shopify.app.toml fragment "
            "(default). 'json' = raw list. 'csv' = comma-"
            "separated scope names (one-liner)."
        ),
    )
    shopify_install_manifest_p.add_argument(
        "--with-comments", action="store_true",
        help=(
            "Include per-scope adapter-usage comments above "
            "each scope (toml only — context for code review)"
        ),
    )

    shopify_webhooks_p = sub.add_parser(
        "shopify-webhooks",
        help=(
            "List the registered Shopify webhook subscriptions "
            "(declared topics + polarity + purpose)"
        ),
    )
    shopify_webhooks_p.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )
    shopify_webhooks_p.add_argument(
        "--gdpr-only", action="store_true",
        help=(
            "Filter to GDPR-mandatory topics (required by every "
            "public-distribution Shopify app)"
        ),
    )

    shopify_webhook_manifest_p = sub.add_parser(
        "shopify-webhook-manifest",
        help=(
            "Generate a Shopify app webhook subscription "
            "manifest fragment (for shopify.app.toml) from the "
            "registry"
        ),
    )
    shopify_webhook_manifest_p.add_argument(
        "--format", default="toml",
        choices=["toml", "json"],
        help=(
            "Output format. 'toml' = shopify.app.toml fragment "
            "(default). 'json' = structured topic list."
        ),
    )

    shopify_app_toml_p = sub.add_parser(
        "shopify-app-toml",
        help=(
            "Emit a complete shopify.app.toml — combines the "
            "install + webhook manifests into one deployable "
            "file"
        ),
    )
    shopify_app_toml_p.add_argument(
        "--app-name", default="shopai",
        help="App name (top-level `name = \"...\"`). Default: shopai",
    )
    shopify_app_toml_p.add_argument(
        "--app-host", default="https://YOUR_APP_HOST",
        help=(
            "Base URL where the app is deployed (used in webhook "
            "callback URLs + redirect URIs). Default: a "
            "placeholder operators substitute at deploy."
        ),
    )
    shopify_app_toml_p.add_argument(
        "--api-version", default="2024-01",
        help="Shopify Admin API version. Default: 2024-01",
    )
    shopify_app_toml_p.add_argument(
        "--write", default=None, metavar="FILE",
        help=(
            "Write the generated TOML to FILE instead of stdout. "
            "Refuses to overwrite an existing file unless "
            "--force is also passed."
        ),
    )
    shopify_app_toml_p.add_argument(
        "--force", action="store_true",
        help=(
            "When combined with --write, overwrite the target "
            "file if it already exists. Defaults off to protect "
            "against accidental overwrites of a hand-edited "
            "shopify.app.toml."
        ),
    )

    shopify_prepare_deploy_p = sub.add_parser(
        "shopify-prepare-deploy",
        help=(
            "Capstone: run shopify-doctor, then emit "
            "shopify.app.toml if every fatal check passes. "
            "Refuses to write when the doctor flags failures "
            "(override with --write-on-warning)."
        ),
    )
    shopify_prepare_deploy_p.add_argument(
        "--output", "-o", default="shopify.app.toml",
        metavar="FILE",
        help=(
            "Target file for the generated TOML. Default: "
            "shopify.app.toml in the working directory."
        ),
    )
    shopify_prepare_deploy_p.add_argument(
        "--app-name", default="shopai",
        help="App name. Default: shopai",
    )
    shopify_prepare_deploy_p.add_argument(
        "--app-host", default="https://YOUR_APP_HOST",
        help="Deployed app base URL. Default: placeholder.",
    )
    shopify_prepare_deploy_p.add_argument(
        "--api-version", default="2024-01",
        help="Shopify Admin API version. Default: 2024-01",
    )
    shopify_prepare_deploy_p.add_argument(
        "--force", action="store_true",
        help="Overwrite the output file if it exists.",
    )
    shopify_prepare_deploy_p.add_argument(
        "--skip-live", action="store_true",
        help=(
            "Skip the live-API drift checks (live scope + live "
            "webhook). Useful in CI where the dev store isn't "
            "reachable."
        ),
    )
    shopify_prepare_deploy_p.add_argument(
        "--write-on-warning", action="store_true",
        help=(
            "Emit the TOML even if the doctor flagged failures. "
            "Used during initial bring-up before a live Shopify "
            "app exists to compare against."
        ),
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
    approvals_show.add_argument(
        "--with-context", action="store_true", dest="with_context",
        help=(
            "Embed the AGI decision-retrieval context: top-k "
            "similar past decisions + their outcomes. Useful for "
            "operator triage of PENDING actions -- shows how "
            "similar past actions turned out."
        ),
    )
    approvals_show.add_argument(
        "--context-k", type=int, default=3, dest="context_k",
        help=(
            "How many similar past decisions to retrieve when "
            "--with-context is supplied. Default: 3."
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

    approvals_trace = approvals_sub.add_parser(
        "trace",
        help=(
            "Dry-run inspection: show what executing an action "
            "would do (dispatcher + adapter + scopes + params) "
            "without making any external calls"
        ),
    )
    approvals_trace.add_argument(
        "action_id",
        help="Approval action id (e.g. appr_1234567890123)",
    )
    approvals_trace.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    approvals_doctor = approvals_sub.add_parser(
        "doctor",
        help=(
            "Aggregate approval-queue health check (Pattern K + "
            "pending-age + recent failure rate + quarantine + "
            "auto-approve coverage in one shot)"
        ),
    )
    approvals_doctor.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )
    approvals_doctor.add_argument(
        "--stale-pending-hours", type=float, default=24.0,
        metavar="H",
        help=(
            "PENDING actions older than this many hours flag the "
            "section. Default: 24h."
        ),
    )
    approvals_doctor.add_argument(
        "--failure-rate-warn", type=float, default=0.25,
        metavar="R",
        help=(
            "Recent dispatch failure-rate above which the section "
            "warns (failed / (executed + failed)). Default: 0.25."
        ),
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

    approvals_alert_release_candidates = approvals_sub.add_parser(
        "alert-release-candidates",
        help=(
            "Recommend alert-paused engines whose degradation "
            "alerts have stopped firing (safe to release)"
        ),
    )
    approvals_alert_release_candidates.add_argument(
        "--quiet-days", type=float, default=None, metavar="N",
        help=(
            "Engines must be silent for at least N days. "
            "Default: matches the bridge's window-days "
            "(SHOPAI_AUTO_QUARANTINE_WINDOW_DAYS, default 7)."
        ),
    )
    approvals_alert_release_candidates.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the table view",
    )

    approvals_alert_pause_candidates = approvals_sub.add_parser(
        "alert-pause-candidates",
        help=(
            "Dry-run: show engines the alert-quarantine bridge "
            "would auto-pause if it ran right now"
        ),
    )
    approvals_alert_pause_candidates.add_argument(
        "--threshold", type=int, default=None, metavar="N",
        help=(
            "Override the streak threshold. Default: matches "
            "SHOPAI_AUTO_QUARANTINE_DAYS env var (default 3)."
        ),
    )
    approvals_alert_pause_candidates.add_argument(
        "--window-days", type=float, default=None, metavar="N",
        help=(
            "Override the detection window. Default: matches "
            "SHOPAI_AUTO_QUARANTINE_WINDOW_DAYS (default 7)."
        ),
    )
    approvals_alert_pause_candidates.add_argument(
        "--per-store", action="store_true",
        help=(
            "Break candidates down per (engine, store) pair. "
            "Useful for empire-AGI: an engine can degrade on "
            "one store but be healthy on others."
        ),
    )
    approvals_alert_pause_candidates.add_argument(
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
        "--release-alert", metavar="ENGINE", default=None,
        help=(
            "Clear ENGINE from the alert-paused set "
            "(auto-quarantined via consecutive degradation "
            "alerts). Pair with --release-alert-store STORE_ID "
            "to release just one store; pair with "
            "--release-alert-all to release ALL pauses for "
            "the engine."
        ),
    )
    quarantine_action.add_argument(
        "--apply-bridge", action="store_true",
        help=(
            "Manually trigger the alert-quarantine bridge "
            "(normally only runs inside daily-brief). Requires "
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS=1."
        ),
    )
    quarantine_action.add_argument(
        "--list", action="store_true",
        help=(
            "Show current exemptions + released + alert-paused "
            "engines + thresholds"
        ),
    )
    approvals_quarantine.add_argument(
        "--release-alert-store", metavar="STORE_ID", default=None,
        help=(
            "Scope --release-alert to a single store (release "
            "the per-store pause instead of the fleet-wide one)."
        ),
    )
    approvals_quarantine.add_argument(
        "--release-alert-all", action="store_true",
        help=(
            "With --release-alert, drop EVERY pause for the "
            "engine (fleet-wide + every per-store entry)."
        ),
    )
    approvals_quarantine.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    approvals_quarantine_simulate = approvals_sub.add_parser(
        "quarantine-simulate",
        help=(
            "Dry-run: 'what would happen if I enqueued an "
            "action for ENGINE on STORE_ID right now?'. "
            "Returns the would-be decision (paused / rejected "
            "/ approved) and explanation, without actually "
            "enqueueing anything."
        ),
    )
    approvals_quarantine_simulate.add_argument(
        "engine",
        help="Engine name to simulate (e.g. loyalty)",
    )
    approvals_quarantine_simulate.add_argument(
        "--store", default=None, metavar="STORE_ID",
        help=(
            "Per-store scope. When omitted, simulates a "
            "fleet-wide (no store_id) enqueue."
        ),
    )
    approvals_quarantine_simulate.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    approvals_health_regressions = approvals_sub.add_parser(
        "health-regressions",
        help=(
            "Find engines whose latest recorded health score "
            "has dropped sharply from their recent baseline"
        ),
    )
    approvals_health_regressions.add_argument(
        "--min-drop", type=float, default=3.0,
        help=(
            "Minimum score-drop in points (default 3.0; range 1-10)"
        ),
    )
    approvals_health_regressions.add_argument(
        "--baseline-days", type=float, default=7.0,
        help=(
            "Baseline look-back window in days (default 7)"
        ),
    )
    approvals_health_regressions.add_argument(
        "--latest-days", type=float, default=1.0,
        help=(
            "How recent the 'latest' event must be in days "
            "(default 1; matches daily-brief cadence)"
        ),
    )
    approvals_health_regressions.add_argument(
        "--min-baseline-samples", type=int, default=3,
        help=(
            "Skip engines with fewer baseline samples than "
            "this (default 3)"
        ),
    )
    approvals_health_regressions.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of the text view",
    )

    approvals_alert_history = approvals_sub.add_parser(
        "alert-history",
        help=(
            "Inspect engine-degradation alert firings "
            "(persistent log of daily-brief alerts)"
        ),
    )
    approvals_alert_history.add_argument(
        "--engine", default=None,
        help="Restrict to one engine (default: all)",
    )
    approvals_alert_history.add_argument(
        "--store", default=None, metavar="STORE_ID",
        help=(
            "Restrict to one store. Per-store events match "
            "exactly; fleet-wide events (store_id=None) are "
            "EXCLUDED. Pair with --include-fleet to see both."
        ),
    )
    approvals_alert_history.add_argument(
        "--include-fleet", action="store_true",
        help=(
            "When used with --store, also include fleet-wide "
            "(store_id=None) events alongside the store-scoped "
            "ones."
        ),
    )
    approvals_alert_history.add_argument(
        "--since-days", type=float, default=7.0,
        help="How far back to look (default: 7 days)",
    )
    approvals_alert_history.add_argument(
        "--clear", action="store_true",
        help=(
            "Wipe the alert history file. Operator escape "
            "hatch after fixing the root cause."
        ),
    )
    approvals_alert_history.add_argument(
        "--prune-older-than-days", type=float, default=None,
        metavar="N",
        help=(
            "Drop events older than N days. Finer scalpel than "
            "--clear: useful for ops hygiene (e.g. cron-prune "
            "the log to last 30 days)."
        ),
    )
    approvals_alert_history.add_argument(
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
    auto_action.add_argument(
        "--audit", action="store_true",
        help=(
            "Score every engine in the allowlist via "
            "engine_health and recommend removal for any that "
            "are currently 'unhealthy'. Cron-friendly: exit "
            "code 1 if any allowlist engine is unhealthy."
        ),
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

    approvals_outcome = approvals_sub.add_parser(
        "outcome",
        help=(
            "Manually record an outcome on an executed action. "
            "Use when Shopify webhooks miss an event or for "
            "retroactive corrections."
        ),
    )
    approvals_outcome.add_argument(
        "action_id",
        help="Action ID (e.g. ``appr_1779011988196_09728cbb``)",
    )
    approvals_outcome.add_argument(
        "--polarity", required=True,
        choices=["positive", "negative", "neutral"],
        help="Outcome polarity",
    )
    approvals_outcome.add_argument(
        "--revenue", type=float, default=0.0,
        help=(
            "Revenue impact in dollars (positive for gains, "
            "negative for refunds). Default 0."
        ),
    )
    approvals_outcome.add_argument(
        "--topic", default="manual",
        help=(
            "Outcome topic / event tag (default: ``manual``). "
            "Mirrors the Shopify webhook topic field "
            "(e.g. ``orders/create``, ``refunds/create``)."
        ),
    )
    approvals_outcome.add_argument(
        "--source", default="operator",
        dest="source_event",
        help=(
            "Source event tag (default: ``operator``). Helps "
            "downstream queries distinguish manual entries "
            "from webhook-attributed outcomes."
        ),
    )
    approvals_outcome.add_argument(
        "--json", action="store_true",
        help="Emit the recorded outcome as JSON.",
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
        help="Inspect webhook feedback bridge (events -> engine attribution)",
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
            "(action -> downstream event attribution)"
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
    version_p.add_argument(
        "--full", action="store_true",
        help=(
            "Include system identity fields (engine count, "
            "dispatcher count, scope-manifest hash) -- useful "
            "for support tickets to confirm 'I'm running build X'."
        ),
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


def _cmd_transfer(args) -> None:
    """Dispatcher for ``shopai transfer <verb>``."""
    verb = getattr(args, "transfer_action", None)
    if verb == "suggest":
        _cmd_transfer_suggest(args)
        return
    if verb == "apply":
        _cmd_transfer_apply(args)
        return
    if verb == "sources":
        _cmd_transfer_sources(args)
        return
    if verb == "history":
        _cmd_transfer_history(args)
        return
    if verb == "outcomes":
        _cmd_transfer_outcomes(args)
        return
    if verb == "credit":
        _cmd_transfer_credit(args)
        return
    print(
        "Usage: shopai transfer "
        "{suggest|apply|sources|history|outcomes|credit}"
    )


def _cmd_transfer_suggest(args) -> None:
    """Cross-store transfer recommender.

    For each (engine, action_type) tuple that succeeded on the
    ``--from`` store and was NOT tried on the ``--to`` store,
    surface it as a transfer candidate. Ranked by success count
    + measured revenue.

    Empire-AGI payoff command: "Store A had revenue lift from
    loyalty mints; suggest minting equivalents on Store B."
    """
    as_json = bool(getattr(args, "json", False))
    from_store = args.from_store
    to_store = args.to_store
    engine_filter = getattr(args, "engine", "") or None
    k = max(1, int(getattr(args, "k", 5) or 5))

    if from_store == to_store:
        msg = "--from and --to must be different stores"
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"Error: {msg}")
        sys.exit(1)
        return

    try:
        from core.approval.queue import (
            ApprovalStatus, get_approval_queue,
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"approval queue unavailable: {exc}"
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(msg)
        sys.exit(1)
        return

    queue = get_approval_queue()

    # ── Step 1: pull EXECUTED actions on the source store ───
    try:
        source_executed = queue.list_by_status(
            ApprovalStatus.EXECUTED,
            engine=engine_filter,
            store_id=from_store,
            limit=2000,
        )
    except TypeError:
        # Pre-#239 queue without store_id kwarg — bail with a
        # clear error rather than silently crossing stores.
        msg = (
            "approval queue does not support per-store filter "
            "(needs PR #239 or later)"
        )
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"Error: {msg}")
        sys.exit(1)
        return

    # ── Step 2: aggregate by (engine, action_type, capability) ─
    success_groups: dict[tuple, dict] = {}
    for a in source_executed:
        key = (a.engine, a.action_type, a.capability)
        bucket = success_groups.setdefault(key, {
            "engine": a.engine,
            "action_type": a.action_type,
            "capability": a.capability,
            "success_count": 0,
            "positive_outcomes": 0,
            "negative_outcomes": 0,
            "total_revenue": 0.0,
            "sample_params": a.params,
        })
        bucket["success_count"] += 1
        # Pull outcomes for revenue + polarity rollup.
        try:
            outcomes = queue.get_outcomes(a.id) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug("transfer-suggest outcomes raised: %s", exc)
            outcomes = []
        for o in outcomes:
            polarity = o.get("polarity", "neutral")
            if polarity == "positive":
                bucket["positive_outcomes"] += 1
            elif polarity == "negative":
                bucket["negative_outcomes"] += 1
            metrics = o.get("metrics") or {}
            rev = metrics.get("revenue")
            if rev is not None:
                try:
                    bucket["total_revenue"] += float(rev)
                except (TypeError, ValueError) as exc:
                    logger.debug(
                        "transfer-suggest revenue parse: %s", exc,
                    )

    # ── Step 3: filter out anything already tried on target ─
    # Pull every status on the target store and build the
    # already-tried set of (engine, action_type) pairs.
    already_tried: set[tuple] = set()
    for status in (
        ApprovalStatus.EXECUTED, ApprovalStatus.FAILED,
        ApprovalStatus.PENDING, ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
    ):
        try:
            target_actions = queue.list_by_status(
                status, engine=engine_filter,
                store_id=to_store, limit=2000,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "transfer-suggest target list_by_status raised: %s",
                exc,
            )
            continue
        for a in target_actions:
            already_tried.add((a.engine, a.action_type))

    # Filter + rank.
    candidates = [
        v for k_tuple, v in success_groups.items()
        if (v["engine"], v["action_type"]) not in already_tried
    ]
    candidates.sort(
        key=lambda v: (
            -(v["positive_outcomes"]),
            -v["total_revenue"],
            -v["success_count"],
        ),
    )
    suggestions = candidates[:k]

    # ── JSON envelope ─────────────────────────────────────
    if as_json:
        print(json.dumps({
            "from_store": from_store,
            "to_store": to_store,
            "engine_filter": engine_filter,
            "k": k,
            "source_executed_count": len(source_executed),
            "source_unique_actions": len(success_groups),
            "already_tried_count": len(already_tried),
            "suggestions": suggestions,
        }, indent=2, default=str))
        return

    # ── Text render ────────────────────────────────────────
    print(
        f"Transfer suggest: {from_store} -> {to_store}"
        + (f"  (engine={engine_filter})" if engine_filter else "")
    )
    print(
        f"  Source executed: {len(source_executed)}  "
        f"unique action types: {len(success_groups)}  "
        f"already tried on target: {len(already_tried)}"
    )
    print()
    if not suggestions:
        print(
            f"(no transfer candidates -- target store has tried "
            f"every action that succeeded on the source)"
        )
        return
    print(f"Top {len(suggestions)} suggestion(s):")
    for i, s in enumerate(suggestions, 1):
        rev_str = (
            f" revenue=${s['total_revenue']:,.2f}"
            if s["total_revenue"] else ""
        )
        outcome_str = (
            f" +{s['positive_outcomes']}/-{s['negative_outcomes']}"
        )
        print(
            f"  [{i}] {s['engine']}/{s['action_type']}"
        )
        print(
            f"      capability={s['capability']}  "
            f"runs={s['success_count']}{outcome_str}{rev_str}"
        )
        if s.get("sample_params"):
            keys = sorted(s["sample_params"].keys())[:5]
            print(f"      sample params: {', '.join(keys)}")


def _cmd_transfer_apply(args) -> None:
    """Enqueue a transfer suggestion as a PENDING action on the
    target store.

    Closes the suggest→action loop: ``transfer suggest`` shows
    recommendations, this command turns one of them into a real
    pending action that operators review via ``shopai approvals
    show`` and approve/reject.

    Reads the most recent successful execution of the matching
    (engine, action_type) on the source store to pull a params
    template, then enqueues a new PENDING action on the target
    store with those params (or operator-supplied overrides).
    No Shopify mutation runs -- this is a queue write only.
    """
    as_json = bool(getattr(args, "json", False))
    from_store = args.from_store
    to_store = args.to_store
    engine = args.engine
    action_type = args.action_type

    def _emit_error(msg: str) -> None:
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"Error: {msg}")
        sys.exit(1)

    if from_store == to_store:
        _emit_error("--from and --to must be different stores")
        return

    # Optional operator-supplied param overrides.
    override_params: dict | None = None
    raw = getattr(args, "params_json", "") or ""
    if raw:
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                _emit_error(
                    "--params-json must be a JSON object",
                )
                return
            override_params = parsed
        except json.JSONDecodeError as exc:
            _emit_error(f"--params-json is not valid JSON: {exc}")
            return

    try:
        from core.approval.queue import (
            ApprovalStatus, get_approval_queue,
        )
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"approval queue unavailable: {exc}")
        return

    queue = get_approval_queue()

    # Find the most recent EXECUTED action on the source store
    # matching the engine + action_type. That's our template.
    try:
        source_actions = queue.list_by_status(
            ApprovalStatus.EXECUTED,
            engine=engine,
            store_id=from_store,
            limit=200,
        )
    except TypeError:
        _emit_error(
            "approval queue does not support per-store filter "
            "(needs PR #239 or later)"
        )
        return

    matching = [
        a for a in source_actions
        if a.action_type == action_type
    ]
    if not matching:
        _emit_error(
            f"no successful {action_type!r} found on source store "
            f"{from_store!r} for engine {engine!r}"
        )
        return

    # Reject if the same (engine, action_type) is already on
    # target store in ANY status (operator may have already
    # tried this transfer or run the action organically).
    for status in (
        ApprovalStatus.EXECUTED, ApprovalStatus.FAILED,
        ApprovalStatus.PENDING, ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
    ):
        try:
            existing = queue.list_by_status(
                status, engine=engine, store_id=to_store,
                limit=200,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "transfer apply: target probe raised: %s", exc,
            )
            existing = []
        if any(a.action_type == action_type for a in existing):
            _emit_error(
                f"{engine}/{action_type} already exists on target "
                f"store {to_store!r} (status={status.value}); "
                "skipping to avoid duplicate enqueue"
            )
            return

    template = matching[0]  # most recent by decided_at desc
    capability = template.capability
    base_params = dict(template.params or {})
    if override_params:
        base_params.update(override_params)

    operator_note = (
        getattr(args, "narrative", "") or ""
    ).strip()
    narrative = (
        f"Transfer suggestion: {engine}/{action_type} "
        f"from {from_store} to {to_store}. "
        f"Source had {len(matching)} prior successful run(s)."
    )
    if operator_note:
        narrative = f"{operator_note}  ||  {narrative}"

    dry_run = bool(getattr(args, "dry_run", False))

    if dry_run:
        if as_json:
            print(json.dumps({
                "status": "dry_run",
                "would_enqueue": True,
                "engine": engine,
                "action_type": action_type,
                "capability": capability,
                "from_store": from_store,
                "to_store": to_store,
                "source_action_id": template.id,
                "source_run_count": len(matching),
                "params": base_params,
                "narrative": narrative,
            }, indent=2, default=str))
            return
        print(
            f"DRY RUN -- would transfer: "
            f"{engine}/{action_type}  "
            f"{from_store} -> {to_store}"
        )
        print(
            f"  source template id: {template.id}  "
            f"capability: {capability}"
        )
        print(f"  source runs: {len(matching)}")
        print(f"  params:    {base_params}")
        print(f"  narrative: {narrative}")
        print()
        print("  Re-run without --dry-run to enqueue.")
        return

    try:
        action = queue.enqueue(
            engine=engine,
            action_type=action_type,
            capability=capability,
            params=base_params,
            narrative=narrative,
            store_id=to_store,
        )
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"enqueue failed: {exc}")
        return

    if as_json:
        print(json.dumps({
            "status": "ok",
            "action_id": action.id,
            "engine": engine,
            "action_type": action_type,
            "capability": capability,
            "from_store": from_store,
            "to_store": to_store,
            "params": base_params,
            "narrative": narrative,
        }, indent=2, default=str))
        return

    print(
        f"Transfer applied: {engine}/{action_type}  "
        f"{from_store} -> {to_store}"
    )
    print(f"  action_id: {action.id}")
    print(
        f"  source runs: {len(matching)}  "
        f"capability: {capability}"
    )
    print(f"  narrative:  {narrative}")
    print()
    print(
        "  Review with:  "
        f"shopai approvals show {action.id} --with-context"
    )


def _cmd_transfer_sources(args) -> None:
    """Rank stores in the fleet by transferable surface area
    toward the target.

    Operators currently have to guess which source store to point
    ``transfer suggest --from`` at. This command tells them: 'these
    are the stores with the most successful actions that target
    hasn't tried yet'. Run before ``transfer suggest`` to pick a
    high-yield source.

    Scoring per candidate source store:
      - transferable_count = unique (engine, action_type) tuples
        that EXECUTED on source AND have NOT been tried on target
        in any status (mirrors the exclusion logic in
        ``transfer suggest``).
      - source_executed_total = total EXECUTED action count on
        source (raw activity signal).
    Ranking: transferable_count desc, then source_executed_total
    desc, then source_id asc.
    """
    as_json = bool(getattr(args, "json", False))
    to_store = (getattr(args, "to_store", "") or "").strip()
    k = max(1, int(getattr(args, "k", 5) or 5))

    def _emit_error(msg: str) -> None:
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"Error: {msg}")
        sys.exit(1)

    if not to_store:
        _emit_error("--to is required")
        return

    try:
        from core.approval.queue import (
            ApprovalStatus, get_approval_queue,
        )
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"approval queue unavailable: {exc}")
        return

    sm = _get_store_manager()
    fleet = sm.list_stores() or []
    candidate_ids = [
        s.get("store_id") for s in fleet
        if s.get("store_id") and s.get("store_id") != to_store
    ]

    queue = get_approval_queue()

    # Build the target's "already tried" set: every (engine,
    # action_type) tuple in ANY status on the target. Same
    # exclusion semantics as ``transfer suggest``.
    target_tried: set[tuple[str, str]] = set()
    for status in (
        ApprovalStatus.EXECUTED, ApprovalStatus.FAILED,
        ApprovalStatus.PENDING, ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED,
    ):
        try:
            rows = queue.list_by_status(
                status, store_id=to_store, limit=2000,
            )
        except TypeError:
            _emit_error(
                "approval queue does not support per-store filter "
                "(needs PR #239 or later)"
            )
            return
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "transfer sources target probe raised: %s", exc,
            )
            rows = []
        for a in rows:
            target_tried.add((a.engine, a.action_type))

    # For each candidate source, count transferable actions.
    sources: list[dict] = []
    for sid in candidate_ids:
        try:
            src_rows = queue.list_by_status(
                ApprovalStatus.EXECUTED,
                store_id=sid, limit=2000,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "transfer sources source probe raised: %s", exc,
            )
            src_rows = []

        unique_actions: set[tuple[str, str]] = set()
        transferable: set[tuple[str, str]] = set()
        for a in src_rows:
            key = (a.engine, a.action_type)
            unique_actions.add(key)
            if key not in target_tried:
                transferable.add(key)

        sources.append({
            "store_id": sid,
            "source_executed_total": len(src_rows),
            "source_unique_actions": len(unique_actions),
            "transferable_count": len(transferable),
            "sample_transferable": sorted(
                f"{e}/{at}" for e, at in transferable
            )[:5],
        })

    sources.sort(key=lambda s: (
        -s["transferable_count"],
        -s["source_executed_total"],
        s["store_id"],
    ))
    top = sources[:k]

    envelope = {
        "to_store": to_store,
        "k": k,
        "target_already_tried_count": len(target_tried),
        "candidate_count": len(candidate_ids),
        "sources": top,
    }

    if as_json:
        print(json.dumps(envelope, indent=2, default=str))
        return

    print(
        f"Transfer sources for target '{to_store}' "
        f"(top {len(top)} of {len(candidate_ids)} candidates):"
    )
    print()
    if not top:
        print("  No candidate stores in fleet.")
        return
    for i, s in enumerate(top, start=1):
        print(
            f"  [{i}] {s['store_id']}  "
            f"transferable={s['transferable_count']}  "
            f"(of {s['source_unique_actions']} unique actions, "
            f"{s['source_executed_total']} total executed)"
        )
        if s["sample_transferable"]:
            sample = ", ".join(s["sample_transferable"])
            print(f"      sample: {sample}")
    print()
    print(
        "  Next step:  "
        f"shopai transfer suggest --from {top[0]['store_id']} "
        f"--to {to_store}"
    )


def _cmd_transfer_history(args) -> None:
    """List recent cross-store transfer apply events.

    Scans ``pending_actions`` for rows whose ``narrative`` starts
    with ``Transfer suggestion:`` -- the marker that
    ``shopai transfer apply`` writes when it enqueues. Parses the
    narrative to extract from/to stores, then surfaces a chronological
    audit trail of cross-store transfers.

    Filters: ``--from``, ``--to``, ``--engine`` narrow the scan;
    ``--limit`` caps row count (default 20).
    """
    as_json = bool(getattr(args, "json", False))
    from_store = (getattr(args, "from_store", "") or "").strip()
    to_store = (getattr(args, "to_store", "") or "").strip()
    engine = (getattr(args, "engine", "") or "").strip()
    limit = max(1, int(getattr(args, "limit", 20) or 20))

    try:
        from core.approval.queue import get_approval_queue
    except Exception as exc:  # noqa: BLE001
        if as_json:
            print(json.dumps(
                {"status": "error", "error": str(exc)},
                indent=2, default=str,
            ))
        else:
            print(f"Error: approval queue unavailable: {exc}")
        sys.exit(1)
        return

    rows: list[dict] = []
    try:
        from core.transfer_narrative import SQL_LIKE_CLAUSE
        queue = get_approval_queue()
        clauses = [SQL_LIKE_CLAUSE]
        params: list = []
        if engine:
            clauses.append("engine = ?")
            params.append(engine)
        if to_store:
            # store_id on the row IS the target store (transfer
            # apply always enqueues with store_id=to_store).
            clauses.append("store_id = ?")
            params.append(to_store)
        params.append(limit)
        sql = (
            "SELECT id, engine, action_type, capability, "
            "store_id, status, narrative, proposed_at, "
            "decided_at FROM pending_actions WHERE "
            + " AND ".join(f"({c})" for c in clauses)
            + " ORDER BY proposed_at DESC LIMIT ?"
        )
        with queue._conn:
            raw_rows = queue._conn.execute(sql, params).fetchall()
        for r in raw_rows:
            parsed_from = _parse_from_store_from_narrative(
                r["narrative"] or "",
            )
            # --from filter is applied AFTER narrative parse since
            # the source store isn't in any indexed column.
            if from_store and parsed_from != from_store:
                continue
            rows.append({
                "action_id": r["id"],
                "engine": r["engine"],
                "action_type": r["action_type"],
                "capability": r["capability"],
                "from_store": parsed_from,
                "to_store": r["store_id"],
                "status": r["status"],
                "proposed_at": r["proposed_at"],
                "decided_at": r["decided_at"],
                "narrative": r["narrative"] or "",
            })
    except Exception as exc:  # noqa: BLE001
        if as_json:
            print(json.dumps(
                {"status": "error", "error": str(exc)},
                indent=2, default=str,
            ))
        else:
            print(f"Error: queue scan failed: {exc}")
        sys.exit(1)
        return

    envelope = {
        "filters": {
            "from_store": from_store,
            "to_store": to_store,
            "engine": engine,
            "limit": limit,
        },
        "count": len(rows),
        "rows": rows,
    }

    if as_json:
        print(json.dumps(envelope, indent=2, default=str))
        return

    if not rows:
        bits = []
        if from_store:
            bits.append(f"from={from_store}")
        if to_store:
            bits.append(f"to={to_store}")
        if engine:
            bits.append(f"engine={engine}")
        scope = f" ({', '.join(bits)})" if bits else ""
        print(f"No transfer history{scope}.")
        return

    print(f"Transfer history ({len(rows)} row(s)):")
    print()
    now = time.time()
    for r in rows:
        ts = r["proposed_at"] or 0.0
        try:
            age_h = max(0.0, (now - float(ts)) / 3600.0)
            age_str = (
                f"{age_h:.1f}h ago" if age_h < 48
                else f"{age_h / 24:.1f}d ago"
            )
        except (TypeError, ValueError):
            age_str = "?"
        print(
            f"  {r['engine']}/{r['action_type']}  "
            f"{r['from_store'] or '?'} -> {r['to_store'] or '?'}  "
            f"[{r['status']}]  {age_str}"
        )
        print(f"      action_id: {r['action_id']}")


def _parse_from_store_from_narrative(narrative: str) -> str:
    """Extract the source store from a transfer apply narrative.

    Thin wrapper around
    :func:`core.transfer_narrative.parse_source_store` so the
    callers (transfer history, transfer outcomes) don't have to
    do their own imports. The shared module owns the format
    contract; this file consumes it.
    """
    from core.transfer_narrative import parse_source_store
    return parse_source_store(narrative)



def _cmd_transfer_outcomes(args) -> None:
    """Close the empire-AGI loop: for transferred actions that
    EXECUTED on the target store, surface their measured outcomes
    so operators can see whether cross-store learning is paying off.

    Workflow:
      1. Scan ``pending_actions`` for EXECUTED rows whose narrative
         marks them as transfer-applied (same parser as ``transfer
         history``).
      2. For each, fetch outcomes via ``queue.get_outcomes()``.
      3. Aggregate counts (positive / negative / neutral) and
         revenue. Per-row + overall rollup.

    Filters mirror ``transfer history``: ``--from``, ``--to``,
    ``--engine``, ``--limit``.
    """
    as_json = bool(getattr(args, "json", False))
    from_store = (getattr(args, "from_store", "") or "").strip()
    to_store = (getattr(args, "to_store", "") or "").strip()
    engine = (getattr(args, "engine", "") or "").strip()
    limit = max(1, int(getattr(args, "limit", 20) or 20))

    def _emit_error(msg: str) -> None:
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"Error: {msg}")
        sys.exit(1)

    try:
        from core.approval.queue import get_approval_queue
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"approval queue unavailable: {exc}")
        return

    try:
        from core.transfer_narrative import SQL_LIKE_CLAUSE
        queue = get_approval_queue()
        clauses = [
            "status = 'executed'",
            SQL_LIKE_CLAUSE,
        ]
        params: list = []
        if engine:
            clauses.append("engine = ?")
            params.append(engine)
        if to_store:
            clauses.append("store_id = ?")
            params.append(to_store)
        params.append(limit)
        sql = (
            "SELECT id, engine, action_type, capability, "
            "store_id, narrative, decided_at "
            "FROM pending_actions WHERE "
            + " AND ".join(clauses)
            + " ORDER BY decided_at DESC LIMIT ?"
        )
        with queue._conn:
            raw_rows = queue._conn.execute(sql, params).fetchall()
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"queue scan failed: {exc}")
        return

    rows: list[dict] = []
    rollup = {
        "actions_with_outcomes": 0,
        "actions_without_outcomes": 0,
        "positive_total": 0,
        "negative_total": 0,
        "neutral_total": 0,
        "revenue_total": 0.0,
    }

    for r in raw_rows:
        parsed_from = _parse_from_store_from_narrative(
            r["narrative"] or "",
        )
        if from_store and parsed_from != from_store:
            continue

        try:
            outcomes = queue.get_outcomes(r["id"]) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "transfer outcomes: get_outcomes(%s) raised: %s",
                r["id"], exc,
            )
            outcomes = []

        from core.approval.outcome_aggregator import (
            aggregate_outcomes,
        )
        per_row = aggregate_outcomes(outcomes)

        if outcomes:
            rollup["actions_with_outcomes"] += 1
        else:
            rollup["actions_without_outcomes"] += 1
        rollup["positive_total"] += per_row.positive
        rollup["negative_total"] += per_row.negative
        rollup["neutral_total"] += per_row.neutral
        rollup["revenue_total"] += per_row.revenue

        rows.append({
            "action_id": r["id"],
            "engine": r["engine"],
            "action_type": r["action_type"],
            "capability": r["capability"],
            "from_store": parsed_from,
            "to_store": r["store_id"],
            "decided_at": r["decided_at"],
            "outcome_count": len(outcomes),
            "positive_outcomes": per_row.positive,
            "negative_outcomes": per_row.negative,
            "neutral_outcomes": per_row.neutral,
            "revenue": per_row.revenue,
        })

    envelope = {
        "filters": {
            "from_store": from_store,
            "to_store": to_store,
            "engine": engine,
            "limit": limit,
        },
        "count": len(rows),
        "rollup": rollup,
        "rows": rows,
    }

    if as_json:
        print(json.dumps(envelope, indent=2, default=str))
        return

    if not rows:
        bits = []
        if from_store:
            bits.append(f"from={from_store}")
        if to_store:
            bits.append(f"to={to_store}")
        if engine:
            bits.append(f"engine={engine}")
        scope = f" ({', '.join(bits)})" if bits else ""
        print(f"No executed transfers{scope}.")
        return

    print(
        f"Transfer outcomes ({len(rows)} executed transfer(s)):"
    )
    print()
    for r in rows:
        if r["outcome_count"] == 0:
            polarity = "no outcomes yet"
        else:
            parts = []
            if r["positive_outcomes"]:
                parts.append(f"+{r['positive_outcomes']}")
            if r["negative_outcomes"]:
                parts.append(f"-{r['negative_outcomes']}")
            if r["neutral_outcomes"]:
                parts.append(f"~{r['neutral_outcomes']}")
            polarity = " ".join(parts) or "0"
        rev_str = (
            f"  rev=${r['revenue']:.2f}"
            if r["revenue"] else ""
        )
        print(
            f"  {r['engine']}/{r['action_type']}  "
            f"{r['from_store'] or '?'} -> {r['to_store'] or '?'}  "
            f"[{polarity}]{rev_str}"
        )
        print(f"      action_id: {r['action_id']}")
    print()
    print(
        f"Rollup: {rollup['actions_with_outcomes']} with outcomes, "
        f"{rollup['actions_without_outcomes']} without.  "
        f"+{rollup['positive_total']} / "
        f"-{rollup['negative_total']} / "
        f"~{rollup['neutral_total']}  "
        f"rev=${rollup['revenue_total']:.2f}"
    )


def _cmd_transfer_credit(args) -> None:
    """Attribute downstream transfer outcomes back to source
    actions.

    Walks the chain backward via ``core.transfer_credit``: for
    every target-side transfer-applied action, parses the
    narrative to find the source (engine, action_type, store)
    and aggregates the action's outcomes back to that source
    tuple. Operators see "loyalty/mint on store-A inspired 5
    successful transfers with $250 attributed revenue."
    """
    as_json = bool(getattr(args, "json", False))
    source_store = (
        getattr(args, "source_store", "") or ""
    ).strip()
    engine = (getattr(args, "engine", "") or "").strip()
    limit = max(1, int(getattr(args, "limit", 20) or 20))

    def _emit_error(msg: str) -> None:
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"Error: {msg}")
        sys.exit(1)

    try:
        from core.approval.queue import get_approval_queue
        from core.transfer_credit import compute_transfer_credits
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"approval queue unavailable: {exc}")
        return

    queue = get_approval_queue()

    try:
        credits = compute_transfer_credits(
            queue,
            source_store=source_store or None,
            engine=engine or None,
        )
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"credit graph computation failed: {exc}")
        return

    top = credits[:limit]
    rows = [
        {
            "source_store": c.source_store,
            "engine": c.engine,
            "action_type": c.action_type,
            "transfer_count": c.transfer_count,
            "executed_count": c.executed_count,
            "positive_outcomes": c.positive_outcomes,
            "negative_outcomes": c.negative_outcomes,
            "revenue": c.revenue,
            "score": c.score,
        }
        for c in top
    ]

    envelope = {
        "filters": {
            "source_store": source_store,
            "engine": engine,
            "limit": limit,
        },
        "total_returned": len(rows),
        "total_keys": len(credits),
        "rows": rows,
    }

    if as_json:
        print(json.dumps(envelope, indent=2, default=str))
        return

    if not rows:
        bits = []
        if source_store:
            bits.append(f"source={source_store}")
        if engine:
            bits.append(f"engine={engine}")
        scope = f" ({', '.join(bits)})" if bits else ""
        print(f"No transfer credit attributable{scope}.")
        return

    label = (
        f"Transfer credit ({len(rows)} of "
        f"{len(credits)} source action(s) ranked):"
    )
    print(label)
    print()
    for i, r in enumerate(rows, start=1):
        score_str = (
            "n/a" if r["score"] is None
            else f"{r['score']:.0%}"
        )
        rev_str = (
            f"  rev=${r['revenue']:,.2f}"
            if r["revenue"]
            else ""
        )
        print(
            f"  [{i}] {r['source_store']}/{r['engine']}/"
            f"{r['action_type']}"
        )
        print(
            f"      transfers={r['transfer_count']}  "
            f"executed={r['executed_count']}  "
            f"+{r['positive_outcomes']} / "
            f"-{r['negative_outcomes']}  "
            f"score={score_str}{rev_str}"
        )


def _cmd_daily_brief(args) -> None:
    """Empire-scale operator summary: per-store + per-engine
    rollup over a recent window.

    Three sections:
      1. Per-store rows: stats + sync recency + connection (cheap,
         from cached state).
      2. Engine activity in the window: executed / failed counts
         across the fleet.
      3. Alerts: sync stale (>24h) / pending overflow (>5) /
         recent failures (>3 in window).

    Pure consumer of StoreManager + SyncService + ApprovalQueue.
    No live Shopify probe -- this is the "fast morning scan"
    command, designed to be cron-able.
    """
    as_json = bool(getattr(args, "json", False))
    window_hours = max(1, int(getattr(args, "window_hours", 24) or 24))
    cutoff = time.time() - window_hours * 3600.0

    sm = _get_store_manager()
    stores = sm.list_stores() or []

    # ── Per-store rows ─────────────────────────────────────
    sync_by_store: dict[str, dict] = {}
    try:
        from data_pipeline.store.sync_service import SyncService
        sync_status = SyncService(sm).get_status() or {}
        for si in sync_status.get("stores", []):
            sid = si.get("store_id")
            if sid:
                sync_by_store[sid] = {
                    "last_sync": si.get("last_sync"),
                    "last_status": si.get("last_status"),
                }
    except Exception as exc:  # noqa: BLE001
        logger.debug("daily-brief sync probe raised: %s", exc)

    store_rows: list[dict] = []
    for s in stores:
        sid = s.get("store_id", "")
        stats = sm.get_stats(sid) or {}
        sync = sync_by_store.get(sid) or {}
        last_sync = sync.get("last_sync")
        age = time.time() - float(last_sync) if last_sync else None
        store_rows.append({
            "store_id": sid,
            "shop_url": s.get("shop_url", ""),
            "niche": s.get("niche") or None,
            "is_active": bool(s.get("is_active")),
            "products": int(stats.get("products", 0)),
            "orders": int(stats.get("orders", 0)),
            "revenue": float(stats.get("total_revenue", 0.0)),
            "last_sync_age_seconds": age,
            "last_sync_status": sync.get("last_status"),
        })

    # ── Engine activity in the window ──────────────────────
    activity_by_engine: dict[str, dict[str, int]] = {}
    pending_by_engine: dict[str, int] = {}
    try:
        from core.approval.queue import (
            ApprovalStatus, get_approval_queue,
        )
        queue = get_approval_queue()
        for status in (
            ApprovalStatus.EXECUTED, ApprovalStatus.FAILED,
        ):
            try:
                rows = queue.list_by_status(status, limit=2000)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "daily-brief list_by_status raised: %s", exc,
                )
                continue
            for a in rows:
                ts = a.decided_at or a.proposed_at or 0
                if ts < cutoff:
                    continue
                bucket = activity_by_engine.setdefault(
                    a.engine, {"executed": 0, "failed": 0},
                )
                bucket[status.value] = bucket.get(status.value, 0) + 1
        per_engine_stats = queue.stats_by_engine() or {}
        for engine, counts in per_engine_stats.items():
            pending = int(counts.get("pending", 0))
            if pending:
                pending_by_engine[engine] = pending
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "daily-brief approval queue probe raised: %s", exc,
        )

    # ── Transfer activity ──────────────────────────────────
    # Scan for cross-store transfer apply events in the window.
    # The empire-AGI loop's morning view: how many transfers were
    # applied, how many have executed, did any pay off?
    transfer_activity: dict = {
        "applied_in_window": 0,
        "pending": 0,
        "executed": 0,
        "failed": 0,
        "rejected_or_expired": 0,
        "positive_outcomes": 0,
        "negative_outcomes": 0,
    }
    try:
        from core.approval.queue import get_approval_queue
        from core.transfer_narrative import SQL_LIKE_CLAUSE
        queue = get_approval_queue()
        with queue._conn:
            t_rows = queue._conn.execute(
                f"""SELECT id, status, proposed_at
                   FROM pending_actions
                   WHERE proposed_at >= ?
                     AND {SQL_LIKE_CLAUSE}""",
                (cutoff,),
            ).fetchall()
        for tr in t_rows:
            transfer_activity["applied_in_window"] += 1
            status = (tr["status"] or "").lower()
            if status == "executed":
                transfer_activity["executed"] += 1
                # Roll polarity for executed transfers only --
                # pending / failed have no outcomes. Uses the
                # shared aggregator so future polarity-schema
                # changes land in one place.
                try:
                    outcomes = queue.get_outcomes(tr["id"]) or []
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "daily-brief transfer outcomes raised: %s",
                        exc,
                    )
                    outcomes = []
                from core.approval.outcome_aggregator import (
                    aggregate_outcomes,
                )
                rollup = aggregate_outcomes(outcomes)
                transfer_activity["positive_outcomes"] += (
                    rollup.positive
                )
                transfer_activity["negative_outcomes"] += (
                    rollup.negative
                )
            elif status == "failed":
                transfer_activity["failed"] += 1
            elif status in {"pending", "approved"}:
                transfer_activity["pending"] += 1
            else:
                transfer_activity["rejected_or_expired"] += 1
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "daily-brief transfer probe raised: %s", exc,
        )

    # ── Alerts ─────────────────────────────────────────────
    alerts: list[dict] = []
    for r in store_rows:
        age = r["last_sync_age_seconds"]
        if age and age > 86400.0:
            alerts.append({
                "kind": "sync_stale",
                "store_id": r["store_id"],
                "detail": f"sync {int(age/3600)}h ago",
            })
        if age is None:
            alerts.append({
                "kind": "never_synced",
                "store_id": r["store_id"],
                "detail": "no sync recorded",
            })
    total_pending = sum(pending_by_engine.values())
    if total_pending > 5:
        alerts.append({
            "kind": "pending_overflow",
            "store_id": None,
            "detail": f"{total_pending} pending approvals across fleet",
        })
    for engine, counts in activity_by_engine.items():
        failed = counts.get("failed", 0)
        if failed >= 3:
            alerts.append({
                "kind": "recent_failures",
                "store_id": None,
                "engine": engine,
                "detail": f"{failed} failures in {window_hours}h",
            })

    # ── Engine-degradation alerts ──────────────────────────
    # Surface the outcome-score drops the dedicated
    # ``shopai engine alerts`` command finds, so cron-driven
    # morning briefs catch quietly-degrading engines without
    # an operator remembering to run it separately.
    # Uses default thresholds (recent=24h, baseline=168h,
    # threshold=0.2, min_recent=3) -- conservative + matches
    # the standalone command.
    try:
        from core.approval.outcome_trends import (
            compute_engine_alerts,
        )
        from core.approval.queue import get_approval_queue
        from core.approval import alert_history
        engine_alerts = compute_engine_alerts(
            get_approval_queue(),
            recent_hours=24.0,
            baseline_hours=168.0,
            threshold=0.2,
            min_recent=3,
        )
        # Persist this run's firings BEFORE reading the
        # consecutive-day count so today's bucket is included.
        # Pattern J guard inside record_alerts short-circuits
        # under pytest.
        try:
            alert_history.record_alerts(engine_alerts)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "daily-brief alert_history.record_alerts "
                "raised: %s", exc,
            )
        try:
            consecutive = (
                alert_history.consecutive_runs_per_engine()
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "daily-brief consecutive_runs_per_engine "
                "raised: %s", exc,
            )
            consecutive = {}
        for a in engine_alerts:
            entry = {
                "kind": "engine_score_degraded",
                "store_id": None,
                "engine": a.engine,
                "detail": a.detail,
            }
            days = consecutive.get(a.engine)
            if days and days >= 2:
                entry["consecutive_days"] = days
                entry["detail"] = (
                    f"{a.detail} (flagged {days} day(s) running)"
                )
            alerts.append(entry)

        # Auto-quarantine bridge: when the consecutive-day
        # count crosses the configured threshold AND the
        # SHOPAI_AUTO_QUARANTINE_FROM_ALERTS env var is set,
        # add the engine to the quarantine state's
        # alert_paused set so future enqueues get rejected.
        # Pattern J guard short-circuits under pytest.
        try:
            from core.approval import alert_quarantine
            newly_paused = (
                alert_quarantine.maybe_auto_quarantine_from_alerts()
            )
            for engine in newly_paused:
                alerts.append({
                    "kind": "auto_alert_quarantined",
                    "store_id": None,
                    "engine": engine,
                    "detail": (
                        f"engine {engine} auto-paused after "
                        f"{alert_quarantine.threshold_days()} "
                        f"consecutive day(s) of degradation "
                        f"alerts; release via "
                        f"'shopai approvals quarantine "
                        f"--release-alert {engine}'"
                    ),
                })
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "daily-brief alert_quarantine bridge raised: %s",
                exc,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "daily-brief engine alerts probe raised: %s", exc,
        )

    # ── Quarantine summary ─────────────────────────────────
    # Fleet-wide rollup of the quarantine state so the morning
    # brief surfaces ALL paused engines, not just today's
    # fresh bridge-fires. Independent of compute_engine_alerts
    # block above so a failure there doesn't suppress this.
    quarantine_summary: dict = {
        "exempt": [],
        "released": [],
        "alert_paused": [],
        "alert_release_candidates": [],
        "alert_pause_candidates": [],
    }
    try:
        from core.approval import quarantine as qm
        qstate = qm.load_state()
        quarantine_summary["exempt"] = sorted(qstate.exemptions)
        quarantine_summary["released"] = sorted(qstate.released)
        quarantine_summary["alert_paused"] = sorted(
            qstate.alert_paused,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "daily-brief quarantine summary load failed: %s", exc,
        )
    try:
        from core.approval import alert_quarantine as aq
        quarantine_summary["alert_release_candidates"] = [
            c["engine"] for c in aq.find_release_candidates()
        ]
        quarantine_summary["alert_pause_candidates"] = [
            c["engine"] for c in aq.find_pause_candidates()
            if c.get("blocked_by") is None
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "daily-brief alert_quarantine candidates raised: %s",
            exc,
        )

    # ── Fleet health rollup ────────────────────────────────
    # Use the composite engine_health scorer to surface the
    # fleet's directional verdict alongside the static
    # quarantine state above. Operators reading the morning
    # brief see "fleet has 3 unhealthy engines" without
    # having to run ``shopai engine pulse --fleet``.
    fleet_health: dict = {
        "checked": False,
        "verdict_counts": {
            "healthy": 0, "warning": 0, "unhealthy": 0,
        },
        "sickest": [],
        "average_score": None,
    }
    try:
        from core.approval.engine_health import score_engine
        from core.goals.engine_goal_map import ENGINE_GOAL_MAP
        scored: list[dict] = []
        for engine in sorted(ENGINE_GOAL_MAP):
            try:
                h = score_engine(engine)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "daily-brief fleet_health: score_engine "
                    "raised for %s: %s", engine, exc,
                )
                continue
            scored.append({
                "engine": h.engine,
                "score": h.score,
                "verdict": h.verdict,
            })
            fleet_health["verdict_counts"][h.verdict] = (
                fleet_health["verdict_counts"].get(h.verdict, 0)
                + 1
            )
        if scored:
            scored.sort(
                key=lambda r: (int(r["score"]), r["engine"]),
            )
            fleet_health["checked"] = True
            fleet_health["sickest"] = scored[:5]
            fleet_health["average_score"] = round(
                sum(int(r["score"]) for r in scored) / len(scored),
                2,
            )
            # Record each engine's current score to the
            # trajectory log so future ``shopai engine pulse
            # <engine> --history`` calls see the trend. Pattern J
            # guard in record_scores short-circuits under
            # pytest. Failure here is silent -- we already
            # surfaced the verdicts above.
            try:
                from core.approval.engine_health_history import (
                    record_scores,
                )
                record_scores(scored)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "daily-brief engine_health_history "
                    "record_scores raised: %s", exc,
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "daily-brief fleet_health rollup raised: %s", exc,
        )

    # ── Totals ─────────────────────────────────────────────
    totals = {
        "stores": len(store_rows),
        "revenue": sum(r["revenue"] for r in store_rows),
        "orders": sum(r["orders"] for r in store_rows),
        "products": sum(r["products"] for r in store_rows),
        "executed": sum(
            c.get("executed", 0) for c in activity_by_engine.values()
        ),
        "failed": sum(
            c.get("failed", 0) for c in activity_by_engine.values()
        ),
        "pending": total_pending,
        "alert_paused": len(quarantine_summary["alert_paused"]),
        "unhealthy_engines": (
            fleet_health["verdict_counts"]["unhealthy"]
        ),
    }

    # ── JSON envelope ──────────────────────────────────────
    if as_json:
        print(json.dumps({
            "window_hours": window_hours,
            "stores": store_rows,
            "engine_activity": activity_by_engine,
            "pending_by_engine": pending_by_engine,
            "transfer_activity": transfer_activity,
            "quarantine": quarantine_summary,
            "fleet_health": fleet_health,
            "totals": totals,
            "alerts": alerts,
        }, indent=2, default=str))
        return

    # ── Text render ────────────────────────────────────────
    print(
        f"Daily brief (last {window_hours}h) "
        f"-- {totals['stores']} store(s)"
    )
    print()
    print(
        f"  Totals: {totals['orders']} orders, "
        f"${totals['revenue']:,.2f} revenue, "
        f"{totals['products']} products"
    )
    print(
        f"  Activity: {totals['executed']} executed, "
        f"{totals['failed']} failed, "
        f"{totals['pending']} pending"
    )
    # Fleet health one-liner -- omitted when scorer probe
    # produced no scored engines (empty roster / all raises).
    if fleet_health["checked"]:
        vc = fleet_health["verdict_counts"]
        avg = fleet_health["average_score"]
        print(
            f"  Fleet health: avg={avg:.1f}/10  "
            f"healthy={vc['healthy']}  "
            f"warning={vc['warning']}  "
            f"unhealthy={vc['unhealthy']}"
        )
        # Surface the sickest engines when ANY are unhealthy --
        # cheap operator nudge to drill in via ``engine pulse``.
        if vc["unhealthy"] > 0:
            sickest = fleet_health["sickest"][:3]
            sickest_str = ", ".join(
                f"{r['engine']}({r['score']}/10)"
                for r in sickest
            )
            print(f"    Sickest: {sickest_str}")
    print()

    # Per-store table (compact)
    print("Stores:")
    print(
        f"  {'STORE':<22s} {'ORD':>5s} {'REVENUE':>11s} "
        f"{'SYNC':>9s}"
    )
    print("  " + "-" * 50)
    for r in sorted(store_rows, key=lambda x: -x["revenue"]):
        age = r["last_sync_age_seconds"]
        sync_str = (
            "never" if age is None
            else f"{int(age/3600)}h" if age < 86400
            else f"{int(age/86400)}d"
        )
        print(
            f"  {r['store_id']:<22s} {r['orders']:>5d} "
            f"${r['revenue']:>10,.2f} {sync_str:>9s}"
        )
    print()

    # Top-activity engines
    if activity_by_engine:
        print(f"Top engines (last {window_hours}h):")
        ranked = sorted(
            activity_by_engine.items(),
            key=lambda kv: -(kv[1].get("executed", 0)
                             + kv[1].get("failed", 0)),
        )
        for engine, counts in ranked[:5]:
            print(
                f"  {engine:25s} "
                f"executed={counts.get('executed', 0):>3d}  "
                f"failed={counts.get('failed', 0):>3d}"
            )
        print()

    # Transfer activity (empire-AGI loop signal)
    if transfer_activity["applied_in_window"]:
        print(
            f"Cross-store transfers (last {window_hours}h):"
        )
        print(
            f"  {transfer_activity['applied_in_window']} applied  "
            f"({transfer_activity['executed']} executed, "
            f"{transfer_activity['pending']} pending, "
            f"{transfer_activity['failed']} failed)"
        )
        if (
            transfer_activity["positive_outcomes"]
            or transfer_activity["negative_outcomes"]
        ):
            print(
                f"  Outcomes:  "
                f"+{transfer_activity['positive_outcomes']}  "
                f"-{transfer_activity['negative_outcomes']}"
            )
        print()

    # Quarantine summary — only render when there's something
    # actionable (paused engines or candidates). Keeps the
    # happy-path brief clean.
    q_paused = quarantine_summary.get("alert_paused") or []
    q_release_cands = quarantine_summary.get(
        "alert_release_candidates",
    ) or []
    q_pause_cands = quarantine_summary.get(
        "alert_pause_candidates",
    ) or []
    if q_paused or q_release_cands or q_pause_cands:
        print()
        print("Quarantine:")
        if q_paused:
            print(
                f"  Alert-paused ({len(q_paused)}): "
                f"{', '.join(q_paused[:5])}"
                f"{' ...' if len(q_paused) > 5 else ''}"
            )
        if q_release_cands:
            print(
                f"  Safe to release ({len(q_release_cands)}): "
                f"{', '.join(q_release_cands[:5])}"
                f"{' ...' if len(q_release_cands) > 5 else ''}"
            )
        if q_pause_cands:
            print(
                f"  Bridge would pause ({len(q_pause_cands)}): "
                f"{', '.join(q_pause_cands[:5])}"
                f"{' ...' if len(q_pause_cands) > 5 else ''}"
            )
        print()

    # Alerts
    if alerts:
        print(f"Alerts ({len(alerts)}):")
        for a in alerts:
            target = a.get("store_id") or a.get("engine") or "-"
            print(f"  [{a['kind']:<18s}] {target:<22s} {a['detail']}")
    else:
        print("Alerts: (none)")


def _cmd_store_fleet(args) -> None:
    """Cross-store summary: aggregate per-store metrics + sync
    recency across every registered store.

    Renders one row per store (text mode) with revenue, counts,
    last-sync age, and shop URL. Aggregate row at the bottom
    sums totals + flags the freshest / stalest sync. ``--json``
    emits the raw report dict for automation.

    Pure consumer of StoreManager + SyncService; no AGI-stack
    dependency. Useful even before per-store world-model lands.
    """
    as_json = bool(getattr(args, "json", False))
    sort_by = getattr(args, "sort_by", "revenue")

    sm = _get_store_manager()
    stores = sm.list_stores()
    if not stores:
        if as_json:
            print(json.dumps(
                {"status": "ok", "stores": [], "totals": {}},
                indent=2, default=str,
            ))
        else:
            print(
                "No stores configured. Add one with: "
                "shopai store add <id> <url> <key>"
            )
        return

    # ── Pull sync recency once ─────────────────────────────
    sync_by_store: dict[str, dict] = {}
    try:
        from data_pipeline.store.sync_service import SyncService
        sync_status = SyncService(sm).get_status() or {}
        for si in sync_status.get("stores", []):
            sid = si.get("store_id")
            if sid:
                sync_by_store[sid] = {
                    "last_sync": si.get("last_sync"),
                    "last_status": si.get("last_status"),
                }
    except Exception as exc:  # noqa: BLE001
        logger.debug("fleet sync probe raised: %s", exc)

    # ── Build per-store rows ───────────────────────────────
    rows: list[dict] = []
    for s in stores:
        sid = s.get("store_id", "")
        stats = sm.get_stats(sid) or {}
        sync = sync_by_store.get(sid) or {}
        last_sync = sync.get("last_sync")
        age = (
            time.time() - float(last_sync)
            if last_sync else None
        )
        rows.append({
            "store_id": sid,
            "shop_url": s.get("shop_url", ""),
            "niche": s.get("niche", "") or None,
            "store_type": s.get("store_type", "") or None,
            "is_active": bool(s.get("is_active")),
            "products": int(stats.get("products", 0)),
            "orders": int(stats.get("orders", 0)),
            "customers": int(stats.get("customers", 0)),
            "revenue": float(stats.get("total_revenue", 0.0)),
            "last_sync_at": last_sync,
            "last_sync_status": sync.get("last_status"),
            "last_sync_age_seconds": age,
        })

    # ── Sort ───────────────────────────────────────────────
    _sort_key_map = {
        "revenue": lambda r: -r["revenue"],
        "products": lambda r: -r["products"],
        "orders": lambda r: -r["orders"],
        "customers": lambda r: -r["customers"],
        "name": lambda r: r["store_id"],
    }
    rows.sort(key=_sort_key_map.get(sort_by, _sort_key_map["revenue"]))

    # ── Totals + spotlight ─────────────────────────────────
    totals = {
        "stores": len(rows),
        "products": sum(r["products"] for r in rows),
        "orders": sum(r["orders"] for r in rows),
        "customers": sum(r["customers"] for r in rows),
        "revenue": sum(r["revenue"] for r in rows),
    }
    fresh = min(
        (r for r in rows if r["last_sync_age_seconds"] is not None),
        key=lambda r: r["last_sync_age_seconds"],
        default=None,
    )
    stale = max(
        (r for r in rows if r["last_sync_age_seconds"] is not None),
        key=lambda r: r["last_sync_age_seconds"],
        default=None,
    )
    never_synced = [r for r in rows if r["last_sync_age_seconds"] is None]

    # ── JSON envelope ──────────────────────────────────────
    if as_json:
        print(json.dumps({
            "status": "ok",
            "sort_by": sort_by,
            "stores": rows,
            "totals": totals,
            "spotlight": {
                "freshest_sync": fresh["store_id"] if fresh else None,
                "stalest_sync": stale["store_id"] if stale else None,
                "never_synced": [r["store_id"] for r in never_synced],
            },
        }, indent=2, default=str))
        return

    # ── Text render ────────────────────────────────────────
    print(f"Fleet ({len(rows)} store(s); sorted by {sort_by})")
    print()
    # Header
    print(
        f"  {'STORE':<22s} {'NICHE':<10s} "
        f"{'PROD':>6s} {'ORD':>5s} {'CUST':>5s} "
        f"{'REVENUE':>11s} {'SYNC':>9s}"
    )
    print("  " + "-" * 75)
    for r in rows:
        age = r["last_sync_age_seconds"]
        sync_str = (
            "never" if age is None
            else f"{int(age)}s" if age < 60
            else f"{int(age/60)}m" if age < 3600
            else f"{int(age/3600)}h" if age < 86400
            else f"{int(age/86400)}d"
        )
        active_marker = "*" if r["is_active"] else " "
        print(
            f"  {active_marker}{r['store_id']:<21s} "
            f"{(r['niche'] or '-'):<10s} "
            f"{r['products']:>6d} {r['orders']:>5d} {r['customers']:>5d} "
            f"${r['revenue']:>10,.2f} "
            f"{sync_str:>9s}"
        )
    print("  " + "-" * 75)
    print(
        f"  {'TOTAL':<22s} {'':<10s} "
        f"{totals['products']:>6d} {totals['orders']:>5d} "
        f"{totals['customers']:>5d} ${totals['revenue']:>10,.2f}"
    )
    print()
    # Spotlight
    if fresh and stale and fresh["store_id"] != stale["store_id"]:
        print(
            f"  Freshest sync: {fresh['store_id']} "
            f"({int((fresh['last_sync_age_seconds'] or 0)/60)}m ago)"
        )
        print(
            f"  Stalest sync:  {stale['store_id']} "
            f"({int((stale['last_sync_age_seconds'] or 0)/3600)}h ago)"
        )
    if never_synced:
        ids = ", ".join(r["store_id"] for r in never_synced[:3])
        more = (
            f" + {len(never_synced) - 3} more"
            if len(never_synced) > 3 else ""
        )
        print(f"  Never synced:  {ids}{more}")


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
    """Per-store status: counts + last-sync recency + metadata.

    Default text view is operator-friendly. ``--json`` emits a
    structured envelope for automation (CI smoke tests,
    monitoring dashboards, etc.).
    """
    as_json = bool(getattr(args, "json", False))
    sm = _get_store_manager()
    store_id = args.store_id or sm.active_store_id
    if not store_id:
        if as_json:
            print(json.dumps(
                {
                    "status": "error",
                    "error": "no_store_selected",
                },
                indent=2, default=str,
            ))
            return
        print("No store selected. Add one with: shopai store add")
        return

    stats = sm.get_stats(store_id) or {}
    store = sm.get_store(store_id) or {}

    # Last-sync recency -- pull from the SyncService just like
    # the global ``shopai status`` does. Best-effort: a missing
    # sync service surfaces as ``null`` rather than crashing.
    last_sync_at: float | None = None
    last_sync_status: str | None = None
    last_sync_age_seconds: float | None = None
    try:
        from data_pipeline.store.sync_service import SyncService
        sync = SyncService(sm)
        sync_status = sync.get_status() or {}
        for si in sync_status.get("stores", []):
            if si.get("store_id") == store_id:
                last_sync_at = si.get("last_sync")
                last_sync_status = si.get("last_status")
                if last_sync_at:
                    last_sync_age_seconds = time.time() - last_sync_at
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("store status sync probe raised: %s", exc)

    if as_json:
        print(json.dumps({
            "store_id": store_id,
            "shop_url": store.get("shop_url", ""),
            "niche": store.get("niche", ""),
            "store_type": store.get("store_type", ""),
            "is_active": bool(store.get("is_active")),
            "stats": {
                "products": stats.get("products", 0),
                "orders": stats.get("orders", 0),
                "customers": stats.get("customers", 0),
                "total_revenue": float(stats.get("total_revenue", 0.0)),
            },
            "last_sync_at": last_sync_at,
            "last_sync_status": last_sync_status,
            "last_sync_age_seconds": last_sync_age_seconds,
        }, indent=2, default=str))
        return

    print(f"Store: {store_id}")
    print(f"  URL:       {store.get('shop_url', '-')}")
    niche = store.get("niche") or "-"
    store_type = store.get("store_type") or "-"
    print(f"  Niche:     {niche}")
    print(f"  Type:      {store_type}")
    if store.get("is_active"):
        print(f"  Active:    yes")
    print()
    print(f"  Products:  {stats.get('products', 0)}")
    print(f"  Orders:    {stats.get('orders', 0)}")
    print(f"  Customers: {stats.get('customers', 0)}")
    print(f"  Revenue:   ${stats.get('total_revenue', 0.0):,.2f}")
    print()
    if last_sync_at is None:
        print("  Last sync: never")
    else:
        age = last_sync_age_seconds or 0
        ago = (
            f"{int(age)}s ago" if age < 60
            else f"{int(age/60)}m ago" if age < 3600
            else f"{int(age/3600)}h ago" if age < 86400
            else f"{int(age/86400)}d ago"
        )
        status_str = last_sync_status or "unknown"
        print(f"  Last sync: {ago} ({status_str})")


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
    """Run the auto-configurator against a registered store.

    Text render (default) shows the human-readable per-feature
    table + planned writes. ``--json`` emits the raw
    configurator result for scripts and CI consumers.
    """
    as_json = bool(getattr(args, "json", False))

    def _emit_error(msg: str) -> None:
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(msg)

    sm = _get_store_manager()
    store_id = args.store_id or sm.active_store_id
    if not store_id:
        _emit_error("No store specified and no active store set.")
        return

    creds = sm.get_credentials(store_id)
    if not creds or not creds.get("shop_url"):
        _emit_error(
            f"Store {store_id!r} not found or has no shop_url.",
        )
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
            _emit_error(f"Could not resolve OAuth token: {exc}")
            return
    if not token:
        _emit_error(
            f"Store {store_id!r} has no usable credentials.",
        )
        return

    store_info = sm.db.get_store(store_id) if hasattr(sm, "db") else {}
    niche = args.niche or (store_info or {}).get("niche") or "general"
    store_name = (store_info or {}).get("name") or store_id

    features = None
    if args.only:
        features = [f.strip() for f in args.only.split(",") if f.strip()]

    from execution.store_configurator import StoreConfigurator, ALL_FEATURES

    if not as_json:
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

    # ── JSON envelope (early return) ────────────────────────
    if as_json:
        # Enrich the raw result with operator context fields so
        # scripts have everything in one envelope.
        envelope = {
            "store_id": store_id,
            "niche": niche,
            "dry_run": bool(args.dry_run),
            "feature_count": len(
                result.get("results", {}) or {},
            ),
            **result,
        }
        print(json.dumps(envelope, indent=2, default=str))
        return

    # ── Text render ─────────────────────────────────────────
    print()
    print(f"Status: {result['status']}")
    print(f"Niche:  {result['niche']}")
    print()
    print("Feature results:")
    results = result.get("results", {}) or {}
    for name in sorted(results.keys()):
        data = results[name]
        summary = _format_feature_summary(name, data)
        print(f"  {name:15s} {summary}")

    if args.dry_run and result.get("plan"):
        print()
        print(f"Planned writes ({len(result['plan'])}):")
        for step in result["plan"]:
            print(f"  {step['method']:6s} {step['path']:45s} {step['description']}")

    # Final one-line summary so operators see the verdict at a
    # glance. Counts feature outcomes (configurator may attach
    # 'created', 'skipped', 'failed' counters per feature).
    feature_count = len(results)
    plan_count = len(result.get("plan", []) or [])
    print()
    if args.dry_run:
        print(
            f"Summary: {feature_count} feature(s) planned, "
            f"{plan_count} write(s) staged"
            f"  -- pass --json for machine-readable output"
        )
    else:
        print(
            f"Summary: {feature_count} feature(s) applied "
            f"(status={result['status']})"
            f"  -- pass --json for machine-readable output"
        )


def _cmd_store_design(args) -> None:
    """Run the store_design engine and surface its recommendations.

    Read-only preview: layout / color / navigation / mobile
    suggestions. Doesn't modify the live store.

    When a store_id is supplied (or an active store is set), the
    engine reads brand + products + analytics from the store's
    sync data. Otherwise it falls back to the engine's default
    profile so operators can preview what the engine produces
    without first connecting a store.
    """
    sm = _get_store_manager()
    store_id = (
        getattr(args, "store_id", None) or sm.active_store_id
    )

    # Build the engine input. Best-effort: if store data isn't
    # available, fall back to empty input -- the engine handles
    # missing data gracefully (Pattern Q compliant).
    payload: dict = {
        "status": "success",
        "data": {},
        "meta": {},
        "error": None,
    }
    if store_id:
        try:
            stats = sm.get_stats(store_id) if hasattr(
                sm, "get_stats",
            ) else {}
            # Pull whatever brand/products/analytics we can find;
            # the engine tolerates partial input.
            payload["data"] = {
                "brand": {
                    "colors": [],
                    "fonts": [],
                    "voice": "professional",
                },
                "products": [],
                "analytics": {
                    "bounce_rate": 0.0,
                    "device_split": {},
                },
            }
            # If we have product / order counts, expose them so
            # the engine can shape its recommendations.
            if isinstance(stats, dict):
                _product_count = stats.get("products", 0)
                # Engine doesn't currently take a product count
                # but exposing the field here documents the
                # integration point for future enhancement.
                payload["data"]["_store_stats"] = {
                    "products": _product_count,
                    "orders": stats.get("orders", 0),
                    "customers": stats.get("customers", 0),
                }
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "store_design store-data probe raised: %s", exc,
            )

    try:
        from engines.store_design.flow import StoreDesignEngine
        out = StoreDesignEngine().run(payload)
    except Exception as exc:  # noqa: BLE001
        logger.debug("store_design engine raised: %s", exc)
        print(f"store_design unavailable: {exc}")
        sys.exit(1)

    if out.get("status") != "success" or not out.get("data"):
        msg = out.get("error") or "engine returned no data"
        if getattr(args, "json", False):
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"store_design produced no recommendations: {msg}")
        sys.exit(1)

    data = out["data"]
    section = getattr(args, "section", "all") or "all"

    if getattr(args, "json", False):
        payload_out = {
            "store_id": store_id,
            "section": section,
            "estimated_conversion_lift": data.get(
                "estimated_conversion_lift", 0.0,
            ),
        }
        if section in ("all", "layout"):
            payload_out["layout_recommendations"] = data.get(
                "layout_recommendations", [],
            )
        if section in ("all", "color"):
            payload_out["color_palette"] = data.get(
                "color_palette", {},
            )
        if section in ("all", "navigation"):
            payload_out["navigation"] = data.get(
                "navigation", {},
            )
        if section in ("all", "mobile"):
            payload_out["mobile_optimizations"] = data.get(
                "mobile_optimizations", [],
            )
        print(json.dumps(payload_out, indent=2, default=str))
        return

    # Text render
    print("ShopAI Store Design Preview")
    if store_id:
        print(f"  Store: {store_id}")
    else:
        print("  Store: (no active store -- using default profile)")
    lift = data.get("estimated_conversion_lift", 0.0)
    if lift:
        print(f"  Estimated conversion lift: {lift:.1%}")
    print()

    if section in ("all", "layout"):
        layout = data.get("layout_recommendations", []) or []
        print(f"== Layout ({len(layout)} recommendation(s)) ==")
        if not layout:
            print("  (no layout recommendations)")
        for rec in layout:
            print(
                f"  [{rec.get('priority', '?'):<6}] "
                f"{rec.get('page', '?')}: "
                f"{rec.get('recommendation', '')}"
            )
            impact = rec.get("expected_impact")
            if impact:
                print(f"           impact: {impact}")
        print()

    if section in ("all", "color"):
        palette = data.get("color_palette", {}) or {}
        print("== Color palette ==")
        if not palette:
            print("  (no color palette)")
        else:
            for key in (
                "primary", "secondary", "accent",
                "background", "text", "cta",
            ):
                value = palette.get(key)
                if value:
                    print(f"  {key:<12} {value}")
            rationale = palette.get("rationale")
            if rationale:
                print(f"  rationale:   {rationale}")
        print()

    if section in ("all", "navigation"):
        nav = data.get("navigation", {}) or {}
        items = nav.get("menu_items", []) or []
        print(f"== Navigation ({len(items)} menu item(s)) ==")
        if not items:
            print("  (no navigation suggestions)")
        for item in sorted(
            items, key=lambda x: x.get("priority", 99),
        ):
            print(
                f"  {item.get('priority', 0):>2}. "
                f"{item.get('label', '?'):<14} "
                f"-> {item.get('url', '?')}"
            )
        print()

    if section in ("all", "mobile"):
        mob = data.get("mobile_optimizations", []) or []
        print(f"== Mobile ({len(mob)} optimization(s)) ==")
        if not mob:
            print("  (no mobile optimizations)")
        for m in mob:
            print(
                f"  {m.get('area', '?'):<14} "
                f"{m.get('recommendation', '')}"
            )
            impact = m.get("impact")
            if impact:
                print(f"                 impact: {impact}")
        print()

    print(
        "Read-only preview. To apply suggestions, manually edit "
        "your Shopify theme/menu/settings (no Phase 7 writeback "
        "yet for store_design)."
    )


def _cmd_store_setup(args) -> None:
    """End-to-end setup wizard.

    Five stages: add → connect → plan → (optionally) apply →
    status. Stops on the first failing stage and exits 1.
    By default the configurator runs in dry_run mode so this
    command is safe to invoke without ``--apply``.

    JSON mode (``--json``) emits a structured per-stage envelope
    instead of the human-readable progress lines.
    """
    as_json = bool(getattr(args, "json", False))
    stages: list[dict] = []

    def _stage(name: str, **fields) -> dict:
        entry = {"stage": name, **fields}
        stages.append(entry)
        if not as_json:
            verdict = "ok" if fields.get("ok", True) else "fail"
            label = fields.get("label") or name
            extra = fields.get("detail", "")
            print(f"  [{verdict:4s}] {label}" + (f"  {extra}" if extra else ""))
        return entry

    def _emit(success: bool, error: str | None = None) -> None:
        if as_json:
            envelope = {
                "store_id": args.store_id,
                "shop_url": args.shop_url,
                "niche": args.niche,
                "applied": bool(args.apply) and success,
                "success": success,
                "error": error,
                "stages": stages,
            }
            print(json.dumps(envelope, indent=2, default=str))
        else:
            print()
            if success:
                if args.apply:
                    print(f"Setup complete for {args.store_id}.")
                else:
                    print(
                        f"Setup planned for {args.store_id}. Re-run "
                        f"with --apply to actually configure."
                    )
            else:
                print(f"Setup failed: {error or 'unknown error'}")
        sys.exit(0 if success else 1)

    # ── Pre-flight credential validation ────────────────────
    if not args.api_key and not (args.client_id and args.client_secret):
        _emit(
            False,
            error=(
                "Must supply --api-key OR both --client-id and "
                "--client-secret."
            ),
        )
        return

    if not as_json:
        print(f"Setting up {args.store_id} ({args.shop_url})")
        print(f"  Niche: {args.niche}  Type: {args.store_type}")
        print()

    sm = _get_store_manager()

    # ── Stage 1: add ───────────────────────────────────────
    try:
        sm.add_store(
            args.store_id, args.shop_url,
            api_key=args.api_key,
            client_id=args.client_id,
            client_secret=args.client_secret,
            name=args.name, niche=args.niche,
            store_type=args.store_type,
        )
        _stage(
            "add", ok=True, label="Store added",
            detail=f"id={args.store_id}",
        )
    except Exception as exc:  # noqa: BLE001
        _stage("add", ok=False, label="Store add failed",
               detail=str(exc))
        _emit(False, error=f"add: {exc}")
        return

    # ── Stage 2: connect ───────────────────────────────────
    try:
        conn = sm.test_connection(args.store_id) or {}
    except Exception as exc:  # noqa: BLE001
        _stage("connect", ok=False, label="Connection probe raised",
               detail=str(exc))
        _emit(False, error=f"connect: {exc}")
        return
    if not conn.get("connected"):
        err = conn.get("error", "unknown")
        _stage("connect", ok=False,
               label="Connection failed", detail=str(err))
        _emit(False, error=f"connect: {err}")
        return
    _stage(
        "connect", ok=True, label="Connection verified",
        detail=f"shop={conn.get('shop', args.store_id)}",
    )

    # ── Stage 3: plan ──────────────────────────────────────
    features = None
    if args.only:
        features = [f.strip() for f in args.only.split(",") if f.strip()]

    creds = sm.get_credentials(args.store_id) or {}
    token = creds.get("api_key") or ""
    if not token and creds.get("client_id") and creds.get("client_secret"):
        try:
            from core.auth.shopify_auth import ShopifyAuth
            token = ShopifyAuth(
                creds["shop_url"], creds["client_id"], creds["client_secret"],
            ).get_token()
        except Exception as exc:  # noqa: BLE001
            _stage(
                "plan", ok=False, label="OAuth token resolution failed",
                detail=str(exc),
            )
            _emit(False, error=f"plan: oauth: {exc}")
            return
    if not token:
        _stage("plan", ok=False, label="No usable credentials")
        _emit(False, error="plan: no usable credentials")
        return

    from execution.store_configurator import StoreConfigurator, ALL_FEATURES
    try:
        configurator = StoreConfigurator(dry_run=True)
        plan_result = configurator.configure(
            args.shop_url, token,
            niche=args.niche, store_name=args.name or args.store_id,
            features=features,
        )
    except Exception as exc:  # noqa: BLE001
        _stage("plan", ok=False, label="Configurator dry-run raised",
               detail=str(exc))
        _emit(False, error=f"plan: {exc}")
        return
    plan_count = len(plan_result.get("plan") or [])
    feature_count = len(plan_result.get("results") or {})
    _stage(
        "plan", ok=True, label="Configurator planned",
        detail=f"{feature_count} feature(s), {plan_count} write(s) staged",
        plan_count=plan_count,
        feature_count=feature_count,
    )

    # ── Stage 4: apply (only when --apply) ─────────────────
    if not args.apply:
        _stage(
            "apply", ok=True, label="Apply skipped",
            detail="(re-run with --apply to write)",
            skipped=True,
        )
        _emit(True)
        return

    try:
        configurator = StoreConfigurator(dry_run=False)
        apply_result = configurator.configure(
            args.shop_url, token,
            niche=args.niche, store_name=args.name or args.store_id,
            features=features,
        )
    except Exception as exc:  # noqa: BLE001
        _stage("apply", ok=False, label="Configurator apply raised",
               detail=str(exc))
        _emit(False, error=f"apply: {exc}")
        return
    status = apply_result.get("status")
    _stage(
        "apply", ok=(status == "configured"),
        label=f"Configurator status={status}",
        detail=f"{len(apply_result.get('results') or {})} feature(s) applied",
    )
    _emit(status == "configured", error=None if status == "configured" else f"apply: status={status}")


def _cmd_store_report(args) -> None:
    """One-shot per-store report.

    Bundles stats + sync recency + drift count + design lift +
    connection probe into a single text or JSON envelope. Read-
    only. Built as the foundation for the per-store world-model
    layer (each section maps directly to a slice of state the
    AGI orchestrator needs at decision time).
    """
    as_json = bool(getattr(args, "json", False))
    skip_live = bool(getattr(args, "skip_live", False))

    sm = _get_store_manager()
    store_id = args.store_id or sm.active_store_id
    if not store_id:
        if as_json:
            print(json.dumps(
                {"status": "error", "error": "no_store_selected"},
                indent=2, default=str,
            ))
        else:
            print("No store selected. Add one with: shopai store add")
        sys.exit(1)
        return

    # ── Section 1: stats + sync recency ────────────────────
    stats = sm.get_stats(store_id) or {}
    store = sm.get_store(store_id) or {}

    last_sync_at: float | None = None
    last_sync_status: str | None = None
    last_sync_age_seconds: float | None = None
    try:
        from data_pipeline.store.sync_service import SyncService
        sync = SyncService(sm)
        sync_status = sync.get_status() or {}
        for si in sync_status.get("stores", []):
            if si.get("store_id") == store_id:
                last_sync_at = si.get("last_sync")
                last_sync_status = si.get("last_status")
                if last_sync_at:
                    last_sync_age_seconds = time.time() - last_sync_at
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("store report sync probe raised: %s", exc)

    # ── Section 2: connection probe (live) ─────────────────
    connection: dict = {"checked": False}
    if not skip_live:
        try:
            conn_result = sm.test_connection(store_id) or {}
            connection = {
                "checked": True,
                "connected": bool(conn_result.get("connected")),
                "shop": conn_result.get("shop", ""),
                "error": conn_result.get("error", "") or None,
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("store report connect probe raised: %s", exc)
            connection = {
                "checked": True,
                "connected": False,
                "shop": "",
                "error": str(exc),
            }

    # ── Section 3: drift count (live) ──────────────────────
    drift: dict = {"checked": False}
    if not skip_live and connection.get("connected"):
        creds = sm.get_credentials(store_id) or {}
        token = creds.get("api_key") or ""
        if not token and creds.get("client_id") and creds.get("client_secret"):
            try:
                from core.auth.shopify_auth import ShopifyAuth
                token = ShopifyAuth(
                    creds["shop_url"], creds["client_id"], creds["client_secret"],
                ).get_token()
            except Exception as exc:  # noqa: BLE001
                logger.debug("store report token resolution raised: %s", exc)
                token = ""
        if token and creds.get("shop_url"):
            try:
                from execution.store_configurator import StoreConfigurator
                configurator = StoreConfigurator(dry_run=True)
                plan_result = configurator.configure(
                    creds["shop_url"], token,
                    niche=store.get("niche") or "general",
                    store_name=store.get("name") or store_id,
                )
                plan = plan_result.get("plan") or []
                drift = {
                    "checked": True,
                    "planned_writes": len(plan),
                    "has_drift": bool(plan),
                    "features_in_drift": _drift_feature_count(plan),
                }
            except Exception as exc:  # noqa: BLE001
                logger.debug("store report drift probe raised: %s", exc)
                drift = {"checked": True, "error": str(exc)}

    # ── Section 4: design conversion lift (cheap) ──────────
    design: dict = {"checked": False}
    try:
        from engines.store_design.flow import StoreDesignEngine
        engine_input = {
            "status": "success",
            "data": {},
            "meta": {},
            "error": None,
        }
        out = StoreDesignEngine().run(engine_input)
        if out.get("status") == "success" and out.get("data"):
            data = out["data"]
            design = {
                "checked": True,
                "estimated_conversion_lift": data.get(
                    "estimated_conversion_lift", 0.0,
                ),
                "layout_recommendations_count": len(
                    data.get("layout_recommendations", []) or [],
                ),
                "mobile_optimizations_count": len(
                    data.get("mobile_optimizations", []) or [],
                ),
            }
    except Exception as exc:  # noqa: BLE001
        logger.debug("store report design probe raised: %s", exc)

    # ── JSON envelope (early return) ───────────────────────
    if as_json:
        envelope = {
            "store_id": store_id,
            "shop_url": store.get("shop_url", ""),
            "niche": store.get("niche", "") or None,
            "store_type": store.get("store_type", "") or None,
            "is_active": bool(store.get("is_active")),
            "stats": {
                "products": stats.get("products", 0),
                "orders": stats.get("orders", 0),
                "customers": stats.get("customers", 0),
                "total_revenue": float(stats.get("total_revenue", 0.0)),
            },
            "last_sync_at": last_sync_at,
            "last_sync_status": last_sync_status,
            "last_sync_age_seconds": last_sync_age_seconds,
            "connection": connection,
            "drift": drift,
            "design": design,
        }
        print(json.dumps(envelope, indent=2, default=str))
        return

    # ── Text render ────────────────────────────────────────
    print(f"Store report: {store_id}")
    print(f"  URL:    {store.get('shop_url', '-')}")
    print(f"  Niche:  {store.get('niche') or '-'}")
    print(f"  Type:   {store.get('store_type') or '-'}")
    print()
    print("Stats:")
    print(f"  Products:  {stats.get('products', 0)}")
    print(f"  Orders:    {stats.get('orders', 0)}")
    print(f"  Customers: {stats.get('customers', 0)}")
    print(f"  Revenue:   ${stats.get('total_revenue', 0.0):,.2f}")
    print()
    if last_sync_at is None:
        print("Sync:")
        print("  Last sync: never")
    else:
        age = last_sync_age_seconds or 0
        ago = (
            f"{int(age)}s ago" if age < 60
            else f"{int(age/60)}m ago" if age < 3600
            else f"{int(age/3600)}h ago" if age < 86400
            else f"{int(age/86400)}d ago"
        )
        print("Sync:")
        print(
            f"  Last sync: {ago} ({last_sync_status or 'unknown'})"
        )
    print()
    print("Live probes:")
    if connection.get("checked"):
        verdict = "ok" if connection.get("connected") else "fail"
        line = f"  [{verdict:4s}] connection"
        shop = connection.get("shop") or ""
        err = connection.get("error") or ""
        if shop:
            line += f"  (shop={shop})"
        elif err:
            line += f"  ({err})"
        print(line)
    else:
        print("  [skip] connection")
    if drift.get("checked"):
        if "error" in drift:
            print(f"  [skip] drift  ({drift['error']})")
        else:
            writes = drift.get("planned_writes", 0)
            verdict = "drift" if drift.get("has_drift") else "ok"
            print(f"  [{verdict:4s}] drift  ({writes} planned write(s))")
    else:
        print("  [skip] drift")
    if design.get("checked"):
        lift = design.get("estimated_conversion_lift", 0.0) or 0.0
        print(
            f"  [ok  ] design  (estimated lift: {lift:.1%}, "
            f"{design.get('layout_recommendations_count', 0)} layout, "
            f"{design.get('mobile_optimizations_count', 0)} mobile)"
        )
    print()

    # Verdict line
    issues = []
    if connection.get("checked") and not connection.get("connected"):
        issues.append("connection")
    if drift.get("checked") and drift.get("has_drift"):
        issues.append(f"{drift.get('planned_writes', 0)} drift")
    if last_sync_age_seconds and last_sync_age_seconds > 86400:
        issues.append("sync stale")
    if issues:
        print(f"Verdict: attention needed -- {', '.join(issues)}")
    else:
        print("Verdict: healthy.")


def _drift_feature_count(plan: list[dict]) -> int:
    """Count distinct features represented in a configurator plan."""
    seen = set()
    for entry in plan:
        bucket = _classify_plan_entry(entry.get("path", ""))
        seen.add(bucket)
    return len(seen)


def _cmd_world_model_fleet(args) -> None:
    """Cross-store world-model snapshot.

    Runs ``WorldModel().snapshot()`` for every registered store
    and renders a compact comparison table. The empire-scale
    equivalent of ``world-model show``: instead of one store's
    full snapshot, one row per store with the key signals.

    Each row carries: stats counts, sync recency, drift count
    (when live probes are on), design lift, pending approvals,
    recent decisions.
    """
    as_json = bool(getattr(args, "json", False))
    skip_live = bool(getattr(args, "skip_live", False))

    sm = _get_store_manager()
    stores = sm.list_stores() or []

    if not stores:
        if as_json:
            print(json.dumps(
                {"status": "ok", "stores": []},
                indent=2, default=str,
            ))
        else:
            print(
                "No stores configured. Add one with: "
                "shopai store add <id> <url> <key>"
            )
        return

    from core.world_model import WorldModel

    wm = WorldModel(sm=sm)
    rows: list[dict] = []
    for s in stores:
        sid = s.get("store_id", "")
        try:
            snap = wm.snapshot(sid, skip_live=skip_live)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "world-model fleet: snapshot raised for %s: %s",
                sid, exc,
            )
            snap = {
                "store_id": sid,
                "error": str(exc),
            }
        rows.append(snap)

    if as_json:
        print(json.dumps({
            "skip_live": skip_live,
            "stores": rows,
        }, indent=2, default=str))
        return

    # ── Text render ────────────────────────────────────────
    print(
        f"World model fleet ({len(rows)} store(s)"
        + ("; live probes on" if not skip_live else "; live probes skipped")
        + ")"
    )
    print()
    print(
        f"  {'STORE':<22s} {'NICHE':<10s} {'PROD':>5s} "
        f"{'ORD':>4s} {'REVENUE':>11s} {'SYNC':>6s} "
        f"{'DRIFT':>6s} {'APPRV':>5s} {'DESIGN':>8s}"
    )
    print("  " + "-" * 87)
    for snap in rows:
        if "error" in snap:
            print(
                f"  {snap['store_id']:<22s} (snapshot error: "
                f"{snap['error']})"
            )
            continue
        store = snap.get("store", {})
        stats = snap.get("stats", {})
        sync = snap.get("sync", {})
        config = snap.get("config", {})
        design = snap.get("design", {})
        approvals = snap.get("approvals", {})

        age = sync.get("age_seconds")
        sync_str = (
            "never" if age is None
            else f"{int(age/3600)}h" if age < 86400
            else f"{int(age/86400)}d"
        )
        drift_str = (
            f"{config.get('planned_writes', 0)}"
            if config.get("checked") and "error" not in config
            else "-"
        )
        pending_str = (
            f"{approvals.get('pending_total', 0)}"
            if approvals.get("checked") else "-"
        )
        lift = design.get("estimated_conversion_lift")
        design_str = (
            f"{lift:.1%}" if isinstance(lift, (int, float))
            else "-"
        )
        print(
            f"  {snap['store_id']:<22s} "
            f"{(store.get('niche') or '-'):<10s} "
            f"{stats.get('products', 0):>5d} "
            f"{stats.get('orders', 0):>4d} "
            f"${stats.get('total_revenue', 0.0):>10,.2f} "
            f"{sync_str:>6s} {drift_str:>6s} "
            f"{pending_str:>5s} {design_str:>8s}"
        )
    print()
    # Quick aggregates
    total_revenue = sum(
        r.get("stats", {}).get("total_revenue", 0.0)
        for r in rows if "error" not in r
    )
    total_pending = sum(
        r.get("approvals", {}).get("pending_total", 0)
        for r in rows if "error" not in r
    )
    print(
        f"  Total: ${total_revenue:,.2f} revenue, "
        f"{total_pending} pending approval(s) across fleet"
    )
    # Fleet engine-health rollup -- ``fleet_health`` is GLOBAL
    # (same content in every per-store snapshot) so we pull it
    # from the first store that scored successfully. Omitted
    # when no store snapshotted cleanly or the rollup is empty.
    fh = None
    for r in rows:
        candidate = r.get("fleet_health")
        if (
            isinstance(candidate, dict)
            and candidate.get("checked")
        ):
            fh = candidate
            break
    if fh:
        vc = fh.get("verdict_counts") or {}
        avg = fh.get("average_score")
        avg_str = (
            f"{avg:.1f}/10"
            if isinstance(avg, (int, float))
            else "n/a"
        )
        print(
            f"  Engine health: avg={avg_str}  "
            f"healthy={vc.get('healthy', 0)}  "
            f"warning={vc.get('warning', 0)}  "
            f"unhealthy={vc.get('unhealthy', 0)}"
        )
        sickest = fh.get("sickest") or []
        if vc.get("unhealthy", 0) > 0 and sickest:
            top = ", ".join(
                f"{s.get('engine', '?')}"
                f"({s.get('score', 0)}/10)"
                for s in sickest[:3]
            )
            print(f"    Sickest: {top}")


def _cmd_world_model_show(args) -> None:
    """Render the per-store world-model snapshot.

    Read-only. Default text view summarises each section in one
    line; ``--json`` emits the full snapshot dict for automation
    or AI orchestration.
    """
    as_json = bool(getattr(args, "json", False))
    skip_live = bool(getattr(args, "skip_live", False))

    sm = _get_store_manager()
    store_id = args.store_id or sm.active_store_id
    if not store_id:
        if as_json:
            print(json.dumps(
                {"status": "error", "error": "no_store_selected"},
                indent=2, default=str,
            ))
        else:
            print("No store selected. Add one with: shopai store add")
        sys.exit(1)
        return

    from core.world_model import WorldModel

    snap = WorldModel(sm=sm).snapshot(store_id, skip_live=skip_live)

    if as_json:
        print(json.dumps(snap, indent=2, default=str))
        return

    # ── Text render ────────────────────────────────────────
    store = snap["store"]
    stats = snap["stats"]
    sync = snap["sync"]
    conn = snap["connection"]
    config = snap["config"]
    design = snap["design"]
    approvals = snap["approvals"]
    decisions = snap["decisions"]

    print(f"World model: {store_id}")
    print(f"  URL:    {store.get('shop_url', '-')}")
    print(f"  Niche:  {store.get('niche') or '-'}")
    print(f"  Type:   {store.get('store_type') or '-'}")
    print()
    print("Stats:")
    print(f"  Products:  {stats['products']}")
    print(f"  Orders:    {stats['orders']}")
    print(f"  Customers: {stats['customers']}")
    print(f"  Revenue:   ${stats['total_revenue']:,.2f}")
    print()
    if sync["last_sync_at"] is None:
        print("Sync:        never")
    else:
        age = sync["age_seconds"] or 0
        ago = (
            f"{int(age)}s ago" if age < 60
            else f"{int(age/60)}m ago" if age < 3600
            else f"{int(age/3600)}h ago" if age < 86400
            else f"{int(age/86400)}d ago"
        )
        print(
            f"Sync:        {ago} ({sync['last_sync_status'] or 'unknown'})"
        )
    print()
    print("Live probes:")
    if conn.get("checked"):
        verdict = "ok" if conn.get("connected") else "fail"
        shop = conn.get("shop") or ""
        err = conn.get("error") or ""
        detail = f"  shop={shop}" if shop else (f"  ({err})" if err else "")
        print(f"  [{verdict:4s}] connection{detail}")
    else:
        print("  [skip] connection")
    if config.get("checked") and "error" not in config:
        verdict = "drift" if config.get("has_drift") else "ok"
        print(
            f"  [{verdict:4s}] config  "
            f"({config.get('planned_writes', 0)} planned write(s))"
        )
    else:
        why = config.get("error", "skipped")
        print(f"  [skip] config  ({why})")
    if design.get("checked") and "error" not in design:
        lift = design.get("estimated_conversion_lift", 0.0)
        print(
            f"  [ok  ] design  (estimated lift: {lift:.1%}, "
            f"{design.get('layout_count', 0)} layout, "
            f"{design.get('mobile_count', 0)} mobile)"
        )
    print()
    print("Approvals (global):")
    if approvals.get("checked"):
        total = approvals.get("pending_total", 0)
        print(f"  Pending total: {total}")
        for engine, n in sorted(
            (approvals.get("pending_by_engine") or {}).items(),
            key=lambda kv: -kv[1],
        )[:5]:
            print(f"    {engine:25s} {n}")
    else:
        print(f"  (unavailable: {approvals.get('error', 'unknown')})")
    print()
    print("Decisions (global):")
    if decisions.get("checked"):
        n = decisions.get("recent_count", 0)
        last = decisions.get("last_occurred_at")
        if last is None:
            print(f"  Recent: {n}  (no recent activity)")
        else:
            age = time.time() - float(last)
            ago = (
                f"{int(age)}s ago" if age < 60
                else f"{int(age/60)}m ago" if age < 3600
                else f"{int(age/3600)}h ago" if age < 86400
                else f"{int(age/86400)}d ago"
            )
            print(f"  Recent: {n}  Last: {ago}")
    else:
        print(f"  (unavailable: {decisions.get('error', 'unknown')})")

    # Quarantine section (fleet-wide; affects this store too).
    quarantine = snap.get("quarantine") or {}
    if quarantine.get("checked"):
        exempt = quarantine.get("exemptions") or []
        released = quarantine.get("released") or []
        paused = quarantine.get("alert_paused") or []
        bridge = quarantine.get("bridge") or {}
        # Only print the section if there's something to show
        # OR if the bridge is enabled (operators need to know).
        release_cands = (
            quarantine.get("alert_release_candidates") or []
        )
        pause_cands = (
            quarantine.get("alert_pause_candidates") or []
        )
        if (exempt or released or paused or release_cands or
                pause_cands or bridge.get("enabled")):
            print()
            print("Quarantine (fleet-wide):")
            print(
                f"  Exempt ({len(exempt)}): "
                f"{', '.join(exempt) or '(none)'}"
            )
            print(
                f"  Released ({len(released)}): "
                f"{', '.join(released) or '(none)'}"
            )
            print(
                f"  Alert-paused ({len(paused)}): "
                f"{', '.join(paused) or '(none)'}"
            )
            if release_cands:
                print(
                    f"  Release candidates "
                    f"({len(release_cands)}): "
                    f"{', '.join(release_cands[:5])}"
                    f"{' ...' if len(release_cands) > 5 else ''}"
                )
            if pause_cands:
                print(
                    f"  Pause candidates "
                    f"({len(pause_cands)}): "
                    f"{', '.join(pause_cands[:5])}"
                    f"{' ...' if len(pause_cands) > 5 else ''}"
                )
            if bridge:
                state = "on" if bridge.get("enabled") else "off"
                print(
                    f"  Auto-pause bridge: {state} "
                    f"(threshold={bridge.get('threshold_days', '?')}d, "
                    f"window={bridge.get('window_days', '?')}d)"
                )

            # Per-store roll-up: which fleet entries actually
            # affect THIS store?
            for_this = quarantine.get("for_this_store") or {}
            this_paused = for_this.get("alert_paused") or []
            this_exempt = for_this.get("exempt") or []
            this_released = for_this.get("released") or []
            if this_paused or this_exempt or this_released:
                print(
                    f"  For this store ({quarantine.get('store_id')}):"
                )
                if this_paused:
                    print(
                        f"    Blocked engines ({len(this_paused)}): "
                        f"{', '.join(this_paused)}"
                    )
                if this_exempt:
                    print(
                        f"    Exempt engines ({len(this_exempt)}): "
                        f"{', '.join(this_exempt)}"
                    )
                if this_released:
                    print(
                        f"    Released engines "
                        f"({len(this_released)}): "
                        f"{', '.join(this_released)}"
                    )


def _cmd_model_router(args) -> None:
    """Dispatcher for ``shopai model-router <verb>``."""
    verb = getattr(args, "mr_action", None)
    if verb == "classify":
        _cmd_model_router_classify(args)
        return
    if verb == "budget":
        _cmd_model_router_budget(args)
        return
    print("Usage: shopai model-router {classify|budget}")


def _cmd_model_router_classify(args) -> None:
    """Classify a prompt and print the routing decision."""
    as_json = bool(getattr(args, "json", False))

    prompt = getattr(args, "prompt", "") or ""
    if not prompt:
        try:
            prompt = sys.stdin.read()
        except Exception as exc:  # noqa: BLE001
            msg = f"could not read prompt from stdin: {exc}"
            if as_json:
                print(json.dumps(
                    {"status": "error", "error": msg},
                    indent=2, default=str,
                ))
            else:
                print(f"Error: {msg}")
            sys.exit(1)
            return
    if not prompt.strip():
        msg = "prompt is empty (use --prompt or pipe text on stdin)"
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"Error: {msg}")
        sys.exit(1)
        return

    from core.model_router import ModelRouter, ModelHint

    try:
        hint = ModelHint(args.hint)
    except ValueError:
        hint = ModelHint.AUTO

    router = ModelRouter()
    decision = router.classify(
        prompt, hint=hint,
        purpose=getattr(args, "purpose", "") or None,
    )

    if as_json:
        print(json.dumps(decision.to_dict(), indent=2, default=str))
        return

    print(f"Tier:              {decision.tier.value}")
    print(f"Reason:            {decision.reason}")
    print(f"Estimated tokens:  {decision.estimated_tokens}")
    print(f"Complexity score:  {decision.complexity_score:.2f}")
    if decision.downgraded:
        print("Downgraded:        YES (cloud budget hit cap)")
    print(f"Components:        {decision.components}")


def _cmd_model_router_budget(args) -> None:
    """Print the rolling-window usage rollup."""
    as_json = bool(getattr(args, "json", False))

    from core.model_router import ModelRouter

    router = ModelRouter()
    report = router.budget_report(
        window_hours=int(getattr(args, "window_hours", 24) or 24),
    )

    if as_json:
        print(json.dumps(report, indent=2, default=str))
        return

    window = report["window_hours"]
    print(f"Model-router budget (last {window}h):")
    for tier, stats in report["by_tier"].items():
        print(
            f"  {tier:6s} "
            f"calls={stats['calls']:>4d}  "
            f"est={stats['estimated_tokens']:>8d}tok  "
            f"actual={stats['actual_tokens']:>8d}tok  "
            f"downgrades={stats['downgrades']}"
        )
    cap = report["cloud_tokens_per_24h"]
    used = report["cloud_tokens_used"]
    pct = report["cloud_remaining_estimate_pct"]
    print()
    print(
        f"Cloud cap: {cap:,} tok / 24h  "
        f"used: {used:,}  "
        f"remaining: ~{pct:.1%}"
    )


def _cmd_memory_recall(args) -> None:
    """Decision-time RAG: retrieve top-k past decisions similar
    to a query, joined with their outcomes.

    Read-only. Engines call ``DecisionRetrieval().retrieve(...)``
    directly; this CLI is for operators to inspect what the
    retriever would surface for a given engine + action.
    """
    as_json = bool(getattr(args, "json", False))

    params: dict | None = None
    raw = getattr(args, "params_json", "") or ""
    if raw:
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                if as_json:
                    print(json.dumps(
                        {"status": "error",
                         "error": "--params-json must be a JSON object"},
                        indent=2, default=str,
                    ))
                else:
                    print("Error: --params-json must be a JSON object.")
                sys.exit(1)
                return
            params = parsed
        except json.JSONDecodeError as exc:
            msg = f"--params-json is not valid JSON: {exc}"
            if as_json:
                print(json.dumps(
                    {"status": "error", "error": msg},
                    indent=2, default=str,
                ))
            else:
                print(f"Error: {msg}")
            sys.exit(1)
            return

    from core.decision_retrieval import DecisionRetrieval

    store_id = (getattr(args, "store_id", "") or "").strip() or None
    since_hours_raw = float(getattr(args, "since_hours", 0) or 0)
    since_hours = since_hours_raw if since_hours_raw > 0 else None

    retriever = DecisionRetrieval()
    # Build kwargs incrementally so we can drop ``since_hours``
    # if the retriever doesn't accept it (pre-PR-#278). The
    # store_id fallback below also handles its own pre-#241 case.
    retrieve_kwargs: dict = {
        "engine": args.engine,
        "action_type": getattr(args, "action_type", "") or None,
        "capability": getattr(args, "capability", "") or None,
        "params": params,
        "k": int(getattr(args, "k", 5) or 5),
        "store_id": store_id,
    }
    if since_hours is not None:
        retrieve_kwargs["since_hours"] = since_hours

    try:
        results = retriever.retrieve(**retrieve_kwargs)
    except TypeError as exc:
        # Pre-#241 retriever doesn't accept store_id; pre-#278
        # doesn't accept since_hours. Strip the unsupported
        # kwargs and retry. Operator-facing warning so it's
        # clear which filter got dropped.
        msg = str(exc)
        dropped: list[str] = []
        if "since_hours" in msg:
            retrieve_kwargs.pop("since_hours", None)
            dropped.append("--since-hours")
        if "store_id" in msg:
            retrieve_kwargs.pop("store_id", None)
            dropped.append("--store")
        if not dropped:
            # Some other TypeError -- re-raise so it's not
            # silently swallowed.
            raise
        if not as_json:
            print(
                f"Warning: {', '.join(dropped)} ignored "
                "(DecisionRetrieval is on an older revision; "
                "upgrade to the latest core/decision_retrieval)."
            )
        results = retriever.retrieve(**retrieve_kwargs)

    if as_json:
        print(json.dumps({
            "engine": args.engine,
            "query": {
                "action_type": getattr(args, "action_type", "") or None,
                "capability": getattr(args, "capability", "") or None,
                "params": params,
                "store_id": store_id,
                "since_hours": since_hours,
            },
            "k": int(getattr(args, "k", 5) or 5),
            "results": results,
        }, indent=2, default=str))
        return

    print(f"Memory recall: engine={args.engine}  k={args.k}")
    filters = []
    if getattr(args, "action_type", ""):
        filters.append(f"action_type={args.action_type}")
    if getattr(args, "capability", ""):
        filters.append(f"capability={args.capability}")
    if store_id:
        filters.append(f"store={store_id}")
    if since_hours is not None:
        filters.append(f"since_hours={since_hours:g}")
    if params:
        filters.append(f"params={sorted(params.keys())}")
    if filters:
        print("  Query: " + ", ".join(filters))
    print()
    if not results:
        print("(no similar past decisions found)")
        return
    for i, entry in enumerate(results, 1):
        rel = entry.get("relevance", 0.0)
        action_type = entry.get("action_type", "?")
        capability = entry.get("capability", "?")
        status = entry.get("status", "?")
        decided_at = entry.get("decided_at") or 0
        age_str = "?"
        if decided_at:
            age = time.time() - float(decided_at)
            age_str = (
                f"{int(age)}s ago" if age < 60
                else f"{int(age/60)}m ago" if age < 3600
                else f"{int(age/3600)}h ago" if age < 86400
                else f"{int(age/86400)}d ago"
            )
        print(
            f"  [{i}] rel={rel:.2f}  {action_type}  "
            f"({capability})  status={status}  {age_str}"
        )
        summary = entry.get("outcome_summary") or {}
        oc = summary.get("count", 0)
        if oc:
            polarity = summary.get("polarity_counts", {})
            rev = summary.get("total_revenue", 0.0)
            print(
                f"      outcomes: {oc}  "
                f"+{polarity.get('positive', 0)} / "
                f"-{polarity.get('negative', 0)} / "
                f"={polarity.get('neutral', 0)}  "
                f"revenue=${rev:.2f}"
            )
        components = entry.get("score_components", {})
        if components:
            comp_line = "      breakdown: " + ", ".join(
                f"{k}={v:.2f}"
                for k, v in components.items()
            )
            print(comp_line)


def _cmd_store_verify(args) -> None:
    """Read-only drift audit.

    Runs the configurator in dry_run mode and reports what would
    be written. A non-empty plan = drift between live state and
    recommended config. Exits 1 on drift, 0 when clean -- useful
    for CI and scheduled health checks.
    """
    as_json = bool(getattr(args, "json", False))

    def _emit_error(msg: str, *, exit_code: int = 1) -> None:
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(msg)
        sys.exit(exit_code)

    sm = _get_store_manager()
    store_id = args.store_id or sm.active_store_id
    if not store_id:
        _emit_error("No store specified and no active store set.")
        return

    creds = sm.get_credentials(store_id)
    if not creds or not creds.get("shop_url"):
        _emit_error(
            f"Store {store_id!r} not found or has no shop_url.",
        )
        return
    token = creds.get("api_key") or ""
    if not token and creds.get("client_id") and creds.get("client_secret"):
        try:
            from core.auth.shopify_auth import ShopifyAuth
            token = ShopifyAuth(
                creds["shop_url"], creds["client_id"], creds["client_secret"],
            ).get_token()
        except Exception as exc:  # noqa: BLE001
            _emit_error(f"Could not resolve OAuth token: {exc}")
            return
    if not token:
        _emit_error(
            f"Store {store_id!r} has no usable credentials.",
        )
        return

    store_info = sm.db.get_store(store_id) if hasattr(sm, "db") else {}
    niche = args.niche or (store_info or {}).get("niche") or "general"
    store_name = (store_info or {}).get("name") or store_id

    features = None
    if args.only:
        features = [f.strip() for f in args.only.split(",") if f.strip()]

    from execution.store_configurator import StoreConfigurator, ALL_FEATURES

    configurator = StoreConfigurator(dry_run=True)
    result = configurator.configure(
        creds["shop_url"], token,
        niche=niche, store_name=store_name, features=features,
    )

    plan = result.get("plan") or []
    # Bucket the plan entries by which feature they belong to. The
    # configurator doesn't tag plan entries directly, so we derive
    # feature membership by inspecting the path: collections.json /
    # discount_codes / shipping_zones / etc.
    drift_by_feature: dict[str, list[dict]] = {
        name: [] for name in (features or ALL_FEATURES)
    }
    for entry in plan:
        path = (entry.get("path") or "").lower()
        bucket = _classify_plan_entry(path)
        drift_by_feature.setdefault(bucket, []).append(entry)

    clean_features = [
        name for name, entries in drift_by_feature.items()
        if not entries
    ]
    drift_features = [
        name for name, entries in drift_by_feature.items()
        if entries
    ]

    if as_json:
        envelope = {
            "store_id": store_id,
            "shop_url": creds["shop_url"],
            "niche": niche,
            "checked_features": sorted(drift_by_feature.keys()),
            "clean_features": sorted(clean_features),
            "drift_features": sorted(drift_features),
            "total_planned_writes": len(plan),
            "drift_by_feature": {
                name: {
                    "count": len(entries),
                    "writes": entries,
                }
                for name, entries in drift_by_feature.items()
            },
            "has_drift": bool(plan),
        }
        print(json.dumps(envelope, indent=2, default=str))
        sys.exit(1 if plan else 0)
        return

    # ── Text render ─────────────────────────────────────────
    print(f"Store: {store_id}  ({creds['shop_url']})")
    print(f"Niche: {niche}")
    print()
    print(
        f"Verified {len(drift_by_feature)} feature(s); "
        f"{len(plan)} planned write(s) total."
    )
    print()
    if clean_features:
        print(f"Clean ({len(clean_features)}):")
        for name in sorted(clean_features):
            print(f"  [ok] {name}")
        print()
    if drift_features:
        print(f"Drift ({len(drift_features)}):")
        for name in sorted(drift_features):
            entries = drift_by_feature[name]
            print(f"  [drift] {name:14s} {len(entries)} write(s) staged")
            for entry in entries[:3]:
                method = entry.get("method", "?")
                path = entry.get("path", "?")
                desc = entry.get("description", "")
                print(f"            {method:6s} {path:35s} {desc}")
            if len(entries) > 3:
                print(f"            ... and {len(entries) - 3} more")
        print()
        print(
            f"Verdict: drift detected. Run `shopai store configure "
            f"{store_id}` to apply (or `--dry-run` to preview)."
        )
        sys.exit(1)
    else:
        print("Verdict: store fully aligned with recommended config.")
        sys.exit(0)


def _classify_plan_entry(path: str) -> str:
    """Map a configurator plan entry's path to its feature bucket.

    The plan entries don't carry their feature name directly, so
    we derive it from the path heuristically. Falls back to
    'other' so unknown buckets still surface in the report.
    """
    path = path.lower()
    if "smart_collections" in path or "custom_collections" in path or "collections.json" in path:
        return "collections"
    if "discount" in path or "price_rules" in path:
        return "discounts"
    if "shipping" in path:
        return "shipping"
    if "pages" in path or "blogs" in path or "articles" in path:
        return "content"
    if "metafield" in path:
        # Most metafields the configurator writes are ai_config /
        # gifts / loyalty / referral / shipping / payments. Match
        # by metafield namespace.
        if "shopai.ai_config" in path or "ai_config" in path:
            return "ai_config"
        if "shopai.gifts" in path or "free_gift" in path:
            return "gifts"
        if "shopai.loyalty" in path or "loyalty" in path:
            return "loyalty"
        if "shopai.referral" in path or "referral" in path:
            return "referral"
        if "shopai.shipping" in path:
            return "shipping"
        if "shopai.payments" in path or "payments" in path:
            return "payments"
        if "shopai.emails" in path or "email" in path:
            return "emails"
        return "ai_config"
    if "products" in path and "tags" in path:
        return "product_tags"
    if "products/" in path:
        # tag writes go through products/{id}.json
        return "product_tags"
    if "email" in path:
        return "emails"
    if "payment" in path:
        return "payments"
    return "other"


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


def _engine_pulse_history_rows(
    engine: str, *, history_days: int,
) -> list[dict]:
    """Fetch + flatten engine_health_history events for the
    ``--history`` flag. Returns newest-first list of
    ``{recorded_at, recorded_at_iso, score, verdict}`` dicts.
    Source-failure isolated: a missing history module returns
    an empty list."""
    try:
        from core.approval.engine_health_history import recent_history
        days = max(1, int(history_days))
        events = recent_history(
            engine, since_seconds=86400.0 * days,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engine pulse history fetch raised: %s", exc,
        )
        return []
    out: list[dict] = []
    for e in events:
        ts = float(getattr(e, "recorded_at", 0.0) or 0.0)
        iso = (
            time.strftime(
                "%Y-%m-%d %H:%M:%S", time.gmtime(ts),
            )
            if ts > 0 else "-"
        )
        out.append({
            "recorded_at": ts,
            "recorded_at_iso": iso,
            "score": int(getattr(e, "score", 0) or 0),
            "verdict": str(getattr(e, "verdict", "") or ""),
        })
    return out


def _cmd_engine_pulse(args) -> None:
    """Composite engine-health verdict.

    Single-engine mode: calls
    ``core.approval.engine_health.score_engine`` and renders a
    short, opinionated, cron-friendly summary. Exit code 1 when
    the verdict is ``unhealthy``, 0 otherwise.

    Fleet mode (``--fleet``): scores every engine in
    ``ENGINE_GOAL_MAP``, renders a leaderboard ranked by score
    ascending (sickest first). Exit code 1 if ANY engine is
    unhealthy, so monitoring pipelines fail-fast on fleet
    degradation.
    """
    as_json = bool(getattr(args, "json", False))
    fleet = bool(getattr(args, "fleet", False))
    if fleet:
        _engine_pulse_fleet(args, as_json=as_json)
        return

    engine_name = getattr(args, "engine_name", None)
    if not engine_name:
        print(
            "Usage: shopai engine pulse <engine_name>  "
            "(or --fleet for the leaderboard)"
        )
        sys.exit(2)
        return

    from core.approval.engine_health import score_engine

    health = score_engine(engine_name)
    payload = health.to_dict()

    history_rows: list[dict] = []
    if getattr(args, "history", False):
        history_rows = _engine_pulse_history_rows(
            engine_name,
            history_days=int(
                getattr(args, "history_days", 30) or 30,
            ),
        )
        payload["history"] = history_rows

    if as_json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(
            f"Engine pulse: {health.engine}  "
            f"score={health.score}/10  "
            f"verdict={health.verdict}"
        )
        if health.concerns:
            print()
            print("Concerns:")
            for c in health.concerns:
                print(f"  - {c}")
        sig = health.signals
        print()
        print("Signals:")
        print(
            f"  executed={sig.get('executed', 0)}  "
            f"failed={sig.get('failed', 0)}  "
            f"pending={sig.get('pending', 0)}"
        )
        os_val = sig.get("outcome_score")
        os_str = f"{float(os_val):.0%}" if os_val is not None else "n/a"
        print(
            f"  outcome_score={os_str}  "
            f"alert_streak_7d={sig.get('alert_streak_7d', 0)}  "
            f"alert_paused={sig.get('alert_paused', False)}"
        )
        # History trail -- newest first. Render as a tight
        # date / score / verdict table so trends are scannable.
        if getattr(args, "history", False):
            print()
            if history_rows:
                hd = int(getattr(args, "history_days", 30) or 30)
                print(
                    f"History (last {hd}d, "
                    f"{len(history_rows)} event(s)):"
                )
                for r in history_rows:
                    ts_str = r["recorded_at_iso"]
                    print(
                        f"  {ts_str:<19s}  "
                        f"{r['score']:>2d}/10  "
                        f"{r['verdict']}"
                    )
            else:
                print(
                    "History: (no recorded events in window)"
                )

    if health.verdict == "unhealthy":
        sys.exit(1)


def _engine_pulse_fleet(args, *, as_json: bool) -> None:
    """Score every engine in ENGINE_GOAL_MAP, render leaderboard
    sorted by score asc (sickest first).
    """
    from core.approval.engine_health import score_engine
    from core.goals.engine_goal_map import ENGINE_GOAL_MAP

    verdict_filter = getattr(args, "verdict", None) or None

    results: list[dict] = []
    for engine in sorted(ENGINE_GOAL_MAP):
        try:
            health = score_engine(engine)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "engine pulse fleet: score_engine raised for %s: %s",
                engine, exc,
            )
            continue
        if verdict_filter and health.verdict != verdict_filter:
            continue
        results.append(health.to_dict())

    # Rank: score asc, then engine name asc as tiebreak so order
    # is deterministic.
    results.sort(key=lambda r: (int(r["score"]), r["engine"]))

    if as_json:
        print(json.dumps({
            "fleet": results,
            "verdict_counts": _verdict_rollup(results),
        }, indent=2, default=str))
    else:
        if not results:
            print("(no engines match)")
        else:
            rollup = _verdict_rollup(results)
            print(
                f"Fleet pulse ({len(results)} engine(s)):  "
                f"healthy={rollup['healthy']}  "
                f"warning={rollup['warning']}  "
                f"unhealthy={rollup['unhealthy']}"
            )
            print()
            for r in results:
                concerns = r.get("concerns") or []
                concerns_str = (
                    f"  [{'; '.join(concerns[:2])}]"
                    if concerns else ""
                )
                print(
                    f"  {r['score']:>2d}/10  "
                    f"{r['verdict']:<9s}  "
                    f"{r['engine']:<28s}"
                    f"{concerns_str}"
                )

    if any(r["verdict"] == "unhealthy" for r in results):
        sys.exit(1)


def _verdict_rollup(results: list[dict]) -> dict[str, int]:
    """Aggregate verdict counts; used by both text + JSON modes."""
    rollup = {"healthy": 0, "warning": 0, "unhealthy": 0}
    for r in results:
        v = r.get("verdict")
        if v in rollup:
            rollup[v] += 1
    return rollup


def _cmd_engine_summary(args) -> None:
    """Per-engine drilldown: queue counts + recent actions + outcomes.

    Combines three existing queue probes into one summary:
      - ``stats_by_engine()`` for per-status counts.
      - ``list_by_status(EXECUTED, engine=N, limit=recent_n)`` for
        the most recent activity.
      - ``engine_outcome_stats()`` for the effectiveness signal.

    Useful as the "is this engine pulling its weight?" verdict for
    operators triaging which engines deserve more / less autonomy.
    """
    as_json = bool(getattr(args, "json", False))
    engine_name = args.engine_name
    recent_n = max(1, int(getattr(args, "recent_n", 5) or 5))

    try:
        from core.approval.queue import (
            ApprovalStatus, get_approval_queue,
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"approval queue unavailable: {exc}"
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(msg)
        sys.exit(1)
        return

    queue = get_approval_queue()

    # Per-status counts for this engine.
    all_engine_stats = queue.stats_by_engine() or {}
    per_engine = all_engine_stats.get(engine_name, {})
    counts = {
        s.value: int(per_engine.get(s.value, 0))
        for s in ApprovalStatus
    }
    total_activity = sum(counts.values())

    # Outcome rollup (success / failure / revenue).
    outcomes = queue.engine_outcome_stats(engine_name) or {}

    # Quarantine + alert-history block (PR-#306-era addition).
    # Answers the operator question "is this engine paused, and
    # why?" without requiring a separate ``approvals quarantine
    # --list`` invocation.
    quarantine_info: dict = {}
    try:
        from core.approval import quarantine as qm
        qstate = qm.load_state()
        quarantine_info = {
            "exempt": qstate.is_exempt(engine_name),
            "released": qstate.is_released(engine_name),
            "alert_paused": qstate.is_alert_paused(engine_name),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engine summary quarantine probe raised: %s", exc,
        )

    alert_streak = 0
    last_alert_at: float | None = None
    recent_alerts: list[dict] = []
    try:
        from core.approval import alert_history
        consecutive = (
            alert_history.consecutive_runs_per_engine(
                window_seconds=86400.0 * 7.0,
            )
        )
        alert_streak = int(consecutive.get(engine_name, 0))
        events = alert_history.recent_history(
            since_seconds=86400.0 * 365.0,
        )
        for e in events:
            if e.engine != engine_name:
                continue
            if last_alert_at is None:
                last_alert_at = e.recorded_at
            # Cap at 5 most recent for this engine. The trajectory
            # tells operators if alerts are accelerating or dying
            # down, not just whether they fired.
            if len(recent_alerts) < 5:
                recent_alerts.append({
                    "recorded_at": float(
                        getattr(e, "recorded_at", 0.0) or 0.0,
                    ),
                    "drop": float(
                        getattr(e, "drop", 0.0) or 0.0,
                    ),
                    "recent_score": float(
                        getattr(e, "recent_score", 0.0) or 0.0,
                    ),
                    "baseline_score": float(
                        getattr(e, "baseline_score", 0.0) or 0.0,
                    ),
                    "store_id": getattr(e, "store_id", None),
                })
            if (
                last_alert_at is not None
                and len(recent_alerts) >= 5
            ):
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engine summary alert_history probe raised: %s", exc,
        )
    if quarantine_info:
        quarantine_info["alert_streak_7d"] = alert_streak
        quarantine_info["last_alert_at"] = last_alert_at
        quarantine_info["recent_alerts"] = recent_alerts

    # Recent actions across the two most informative statuses --
    # EXECUTED first (the "what's been shipped" feed) then FAILED
    # (the "what's been breaking" feed). Capped at recent_n total.
    recent: list[dict] = []
    for status in (ApprovalStatus.EXECUTED, ApprovalStatus.FAILED):
        try:
            actions = queue.list_by_status(
                status, engine=engine_name, limit=recent_n,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "engine summary list_by_status raised: %s", exc,
            )
            continue
        for a in actions:
            recent.append({
                "action_id": a.id,
                "action_type": a.action_type,
                "capability": a.capability,
                "status": a.status.value,
                "decided_at": a.decided_at,
                "decided_by": a.decided_by,
                "error": (a.result or {}).get("error")
                         if a.result else None,
            })
    # Sort newest-first by decided_at, then truncate.
    recent.sort(key=lambda r: -(r.get("decided_at") or 0))
    recent = recent[:recent_n]

    if as_json:
        print(json.dumps({
            "engine": engine_name,
            "counts_by_status": counts,
            "total_activity": total_activity,
            "outcomes": outcomes,
            "quarantine": quarantine_info,
            "recent": recent,
        }, indent=2, default=str))
        return

    # ── Text render ────────────────────────────────────────
    print(f"Engine: {engine_name}")
    print()
    if not total_activity:
        print(
            f"  (no recorded activity yet for {engine_name})"
        )
        return
    print("Queue counts:")
    for status_value, n in counts.items():
        if n:
            print(f"  {status_value:<10s} {n}")
    print(f"  TOTAL      {total_activity}")
    print()
    pos = outcomes.get("positive_count", 0)
    neg = outcomes.get("negative_count", 0)
    neu = outcomes.get("neutral_count", 0)
    total_oc = outcomes.get("total_outcomes", 0)
    revenue = outcomes.get("total_revenue", 0.0)
    score = outcomes.get("outcome_score")
    print("Outcomes:")
    print(
        f"  positive={pos}  negative={neg}  "
        f"neutral={neu}  total={total_oc}"
    )
    print(f"  revenue: ${revenue:,.2f}")
    if score is not None:
        print(f"  effectiveness score: {score:.1%}")
    else:
        print("  effectiveness score: n/a (no polarised outcomes)")
    print()
    if quarantine_info:
        # Compose a one-line status -- skip the section entirely
        # when there's nothing to say (healthy + no recent alerts).
        flags = []
        if quarantine_info.get("exempt"):
            flags.append("exempt")
        if quarantine_info.get("released"):
            flags.append("released")
        if quarantine_info.get("alert_paused"):
            flags.append("alert_paused")
        streak = quarantine_info.get("alert_streak_7d", 0)
        last = quarantine_info.get("last_alert_at")
        recent_alerts_list = (
            quarantine_info.get("recent_alerts") or []
        )
        if flags or streak > 0:
            print("Quarantine:")
            if flags:
                print(f"  Flags: {', '.join(flags)}")
            if streak > 0:
                print(f"  Alert streak (last 7d): {streak} day(s)")
            if last:
                age = time.time() - float(last)
                ago = (
                    f"{int(age)}s ago" if age < 60
                    else f"{int(age/60)}m ago" if age < 3600
                    else f"{int(age/3600)}h ago" if age < 86400
                    else f"{int(age/86400)}d ago"
                )
                print(f"  Last alert firing: {ago}")
            if recent_alerts_list:
                print(
                    f"  Recent alerts ({len(recent_alerts_list)}):"
                )
                now = time.time()
                for ev in recent_alerts_list:
                    ts = ev.get("recorded_at") or 0
                    age = now - float(ts) if ts else 0
                    ago_short = (
                        f"{int(age/3600)}h ago" if age < 86400
                        else f"{int(age/86400)}d ago"
                    )
                    drop = float(ev.get("drop", 0.0) or 0.0)
                    sid = ev.get("store_id")
                    scope = f"@{sid}" if sid else "(fleet)"
                    rs = float(ev.get("recent_score", 0.0))
                    bs = float(ev.get("baseline_score", 0.0))
                    print(
                        f"    {ago_short:<10s} {scope:<14s} "
                        f"drop={drop:.0%}  "
                        f"recent={rs:.2f} baseline={bs:.2f}"
                    )
            print()
    if recent:
        print(f"Recent activity ({len(recent)}):")
        now = time.time()
        for r in recent:
            ts = r.get("decided_at") or 0
            age = now - float(ts) if ts else 0
            ago = (
                f"{int(age)}s ago" if age < 60
                else f"{int(age/60)}m ago" if age < 3600
                else f"{int(age/3600)}h ago" if age < 86400
                else f"{int(age/86400)}d ago"
            )
            line = (
                f"  {r['status']:<9s} "
                f"{r['action_type']:<28s} {ago}"
            )
            if r.get("error"):
                line += f"  err={r['error']}"
            print(line)


def _cmd_engine_guardrail(args) -> None:
    """Show AGI v2 guardrail state + recent-block counts across
    all engines that have opted in.

    Default text view renders one row per engine: env-var state
    (ON/OFF) + count of guardrail-blocked actions in the recent
    window. ``--json`` emits the raw report.

    The block count reads ``pending_actions`` rows whose ``result_json``
    payload's error field starts with ``agi_guardrail_blocked:`` --
    that's the marker the v2 wiring records when it refuses to
    mint.
    """
    as_json = bool(getattr(args, "json", False))
    window_hours = max(1, int(getattr(args, "window_hours", 24) or 24))
    cutoff = time.time() - window_hours * 3600.0

    # Engines that have v2 guardrail wiring. Source of truth:
    # ``engines._agi_context.GUARDRAIL_ENGINES`` -- the roster
    # is owned by the AGI-context module so new engines wiring
    # in v2 don't need a parallel update here.
    try:
        from engines._agi_context import GUARDRAIL_ENGINES
        guardrail_engines = list(GUARDRAIL_ENGINES)
    except Exception as exc:  # noqa: BLE001
        # Pre-PR-#272 codebase doesn't have the roster. Fall
        # back to the hardcoded list so older deployments
        # still render their state.
        logger.debug(
            "engine guardrail roster import failed: %s", exc,
        )
        guardrail_engines = [
            "loyalty",
            "cart_recovery",
            "browse_recovery",
            "email_marketing",
            "wholesale_b2b",
            "discount_strategy",
        ]

    # Per-engine env-var state.
    try:
        from engines._agi_context import guardrail_enabled
    except Exception as exc:  # noqa: BLE001
        # Pre-PR-#247 codebase doesn't have the helper. Fall
        # back to manual env var read.
        logger.debug(
            "engine guardrail status: import failed: %s", exc,
        )

        def guardrail_enabled(name: str) -> bool:
            return os.environ.get(
                f"SHOPAI_{name.upper()}_AGI_GUARDRAIL", "",
            ) in {"1", "true", "yes", "on"}

    # Recent-block counts: scan pending_actions for failures
    # tagged with the agi_guardrail_blocked marker.
    blocks_by_engine: dict[str, int] = {e: 0 for e in guardrail_engines}
    try:
        from core.approval.queue import get_approval_queue
        queue = get_approval_queue()
        with queue._conn:
            rows = queue._conn.execute(
                """SELECT engine, COUNT(*) as n
                   FROM pending_actions
                   WHERE status = 'failed'
                     AND decided_at >= ?
                     AND decision_reason LIKE 'agi_guardrail_blocked:%'
                   GROUP BY engine""",
                (cutoff,),
            ).fetchall()
        for r in rows:
            if r["engine"] in blocks_by_engine:
                blocks_by_engine[r["engine"]] = int(r["n"])
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engine guardrail status: queue read raised: %s", exc,
        )

    # Quarantine flags per engine -- v2 guardrail and quarantine
    # are parallel pause mechanisms (one refuses at decision time,
    # the other rejects at enqueue). Operators should see both
    # in one view to understand "why isn't this engine acting?".
    qstate = None
    try:
        from core.approval import quarantine as qm
        qstate = qm.load_state()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engine guardrail quarantine probe raised: %s", exc,
        )

    def _engine_flags(name: str) -> list[str]:
        if qstate is None:
            return []
        out: list[str] = []
        if qstate.is_alert_paused(name):
            out.append("alert_paused")
        if qstate.is_exempt(name):
            out.append("exempt")
        if qstate.is_released(name):
            out.append("released")
        return out

    report = [
        {
            "engine": engine,
            "guardrail_enabled": guardrail_enabled(engine),
            "blocks_in_window": blocks_by_engine.get(engine, 0),
            "env_var": f"SHOPAI_{engine.upper()}_AGI_GUARDRAIL",
            "quarantine_flags": _engine_flags(engine),
        }
        for engine in guardrail_engines
    ]

    # Optional: recent block events with reason + age. Useful
    # operator triage when an engine spirals -- "why did the
    # guardrail block this mint?" with the exact action_type
    # and avg_relevance from the recorded reason string.
    recent_n = max(0, int(getattr(args, "recent_n", 0) or 0))
    recent_blocks: list[dict] = []
    if recent_n > 0:
        try:
            from core.approval.queue import get_approval_queue
            queue = get_approval_queue()
            with queue._conn:
                rows = queue._conn.execute(
                    """SELECT id, engine, action_type, decided_at,
                              decision_reason
                       FROM pending_actions
                       WHERE status = 'failed'
                         AND decided_at >= ?
                         AND decision_reason LIKE
                             'agi_guardrail_blocked:%'
                       ORDER BY decided_at DESC
                       LIMIT ?""",
                    (cutoff, recent_n),
                ).fetchall()
            recent_blocks = [
                {
                    "action_id": r["id"],
                    "engine": r["engine"],
                    "action_type": r["action_type"],
                    "decided_at": r["decided_at"],
                    "reason": r["decision_reason"],
                }
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "engine guardrail recent: queue read raised: %s",
                exc,
            )

    if as_json:
        envelope: dict = {
            "window_hours": window_hours,
            "engines": report,
        }
        if recent_n > 0:
            envelope["recent_blocks"] = recent_blocks
        print(json.dumps(envelope, indent=2, default=str))
        return

    enabled_count = sum(1 for e in report if e["guardrail_enabled"])
    total_blocks = sum(e["blocks_in_window"] for e in report)
    print(
        f"AGI v2 guardrail status (window: {window_hours}h)"
    )
    print(
        f"  {enabled_count}/{len(report)} engine(s) enabled; "
        f"{total_blocks} block(s) recorded"
    )
    print()
    print(
        f"  {'ENGINE':<22s} {'STATE':<6s} {'BLOCKS':>7s}  "
        f"{'QUARANTINE':<14s} ENV VAR"
    )
    print("  " + "-" * 85)
    for e in report:
        state = "ON" if e["guardrail_enabled"] else "off"
        marker = "*" if e["guardrail_enabled"] else " "
        qflags = ",".join(e.get("quarantine_flags") or [])[:14] or "-"
        print(
            f"  {marker}{e['engine']:<21s} {state:<6s} "
            f"{e['blocks_in_window']:>7d}  "
            f"{qflags:<14s} {e['env_var']}"
        )
    print()
    if recent_n > 0 and recent_blocks:
        print(f"Recent blocks (last {len(recent_blocks)}):")
        now = time.time()
        for b in recent_blocks:
            ts = b.get("decided_at") or 0
            age = now - float(ts) if ts else 0
            ago = (
                f"{int(age)}s ago" if age < 60
                else f"{int(age/60)}m ago" if age < 3600
                else f"{int(age/3600)}h ago" if age < 86400
                else f"{int(age/86400)}d ago"
            )
            # The reason string is the full audit line written
            # by explain_guardrail_block -- e.g.
            # "agi_guardrail_blocked: similar=4 negative=true
            #  positive=false avg_relevance=0.85"
            print(
                f"  {b['engine']:<22s} {b['action_type']:<28s} "
                f"{ago}"
            )
            print(f"      {b['reason']}")
        print()
    elif recent_n > 0:
        print(f"Recent blocks: (none in last {window_hours}h)")
        print()
    if enabled_count == 0:
        print(
            "  Enable any engine via env var, e.g.:\n"
            "    export SHOPAI_LOYALTY_AGI_GUARDRAIL=1"
        )


def _cmd_engine_fleet(args) -> None:
    """Show one engine's activity + outcomes across every store
    in the fleet -- the empire-AGI 'where is this engine winning
    or losing?' diagnostic.

    Inverse of ``transfer suggest``: that asks 'what should I
    copy?', this asks 'on which stores does this engine already
    perform?'. Surfaces per-store rows (executed / failed /
    polarity / revenue) plus a fleet rollup so operators can
    spot patterns: engine X is great everywhere except store B
    (investigate config), engine Y only works on store C
    (consider quarantining elsewhere).
    """
    as_json = bool(getattr(args, "json", False))
    engine_name = (
        getattr(args, "engine_name", "") or ""
    ).strip()
    window_hours = max(
        1, int(getattr(args, "window_hours", 168) or 168),
    )
    cutoff = time.time() - window_hours * 3600.0

    def _emit_error(msg: str) -> None:
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"Error: {msg}")
        sys.exit(1)

    if not engine_name:
        _emit_error("engine_name is required")
        return

    try:
        from core.approval.queue import get_approval_queue
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"approval queue unavailable: {exc}")
        return

    sm = _get_store_manager()
    fleet_stores = sm.list_stores() or []
    known_store_ids = {
        s.get("store_id") for s in fleet_stores if s.get("store_id")
    }

    by_store: dict[str, dict] = {}

    def _bucket(sid: str) -> dict:
        if sid not in by_store:
            by_store[sid] = {
                "store_id": sid,
                "executed": 0,
                "failed": 0,
                "pending": 0,
                "positive_outcomes": 0,
                "negative_outcomes": 0,
                "neutral_outcomes": 0,
                "revenue": 0.0,
            }
        return by_store[sid]

    try:
        queue = get_approval_queue()
        with queue._conn:
            rows = queue._conn.execute(
                """SELECT id, store_id, status, decided_at,
                          proposed_at
                   FROM pending_actions
                   WHERE engine = ?
                     AND (decided_at >= ? OR
                          (decided_at IS NULL
                           AND proposed_at >= ?))""",
                (engine_name, cutoff, cutoff),
            ).fetchall()
        from core.approval.outcome_aggregator import (
            aggregate_outcomes,
        )
        for r in rows:
            sid = r["store_id"] or "(unscoped)"
            bucket = _bucket(sid)
            status = (r["status"] or "").lower()
            if status == "executed":
                bucket["executed"] += 1
                try:
                    outcomes = queue.get_outcomes(r["id"]) or []
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "engine fleet outcomes raised: %s", exc,
                    )
                    outcomes = []
                rollup = aggregate_outcomes(outcomes)
                bucket["positive_outcomes"] += rollup.positive
                bucket["negative_outcomes"] += rollup.negative
                bucket["neutral_outcomes"] += rollup.neutral
                bucket["revenue"] += rollup.revenue
            elif status == "failed":
                bucket["failed"] += 1
            elif status in {"pending", "approved"}:
                bucket["pending"] += 1
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"queue scan failed: {exc}")
        return

    # Ensure every fleet store shows up, even with zero activity.
    for sid in known_store_ids:
        _bucket(sid)

    # Outcome score: positive / (positive + negative); None when
    # no polarised events. Computed AFTER the fleet-stores backfill
    # so every bucket carries the field.
    for b in by_store.values():
        pos = b["positive_outcomes"]
        neg = b["negative_outcomes"]
        b["outcome_score"] = (
            pos / (pos + neg) if (pos + neg) > 0 else None
        )

    # Rollup over the fleet.
    rollup = {
        "stores_with_activity": sum(
            1 for b in by_store.values()
            if (b["executed"] + b["failed"] + b["pending"]) > 0
        ),
        "total_executed": sum(
            b["executed"] for b in by_store.values()
        ),
        "total_failed": sum(
            b["failed"] for b in by_store.values()
        ),
        "total_pending": sum(
            b["pending"] for b in by_store.values()
        ),
        "total_positive": sum(
            b["positive_outcomes"] for b in by_store.values()
        ),
        "total_negative": sum(
            b["negative_outcomes"] for b in by_store.values()
        ),
        "total_revenue": sum(
            b["revenue"] for b in by_store.values()
        ),
    }

    # Sort: most-active first, with executed > failed > pending,
    # then revenue tiebreak.
    ranked = sorted(
        by_store.values(),
        key=lambda b: (
            -(b["executed"] + b["failed"] + b["pending"]),
            -b["executed"], -b["revenue"], b["store_id"],
        ),
    )

    # Quarantine banner: this engine's fleet-wide quarantine
    # state surfaces at the top so operators reading the
    # per-store table know upfront whether the engine is
    # acting at all (or just being rejected at enqueue).
    quarantine_flags: list[str] = []
    try:
        from core.approval import quarantine as qm
        qstate = qm.load_state()
        if qstate.is_exempt(engine_name):
            quarantine_flags.append("exempt")
        if qstate.is_released(engine_name):
            quarantine_flags.append("released")
        if qstate.is_alert_paused(engine_name):
            quarantine_flags.append("alert_paused")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engine fleet quarantine probe raised: %s", exc,
        )

    envelope = {
        "engine": engine_name,
        "window_hours": window_hours,
        "quarantine_flags": quarantine_flags,
        "rollup": rollup,
        "stores": ranked,
    }

    if as_json:
        print(json.dumps(envelope, indent=2, default=str))
        return

    print(
        f"Engine '{engine_name}' across fleet "
        f"(last {window_hours}h):"
    )
    if quarantine_flags:
        print(
            f"  ! Quarantine: {', '.join(quarantine_flags)}"
        )
    print()
    print(
        f"  {'STORE':<22s} {'EXEC':>5s} {'FAIL':>5s} "
        f"{'PEND':>5s} {'+':>4s} {'-':>4s} "
        f"{'SCORE':>6s} {'REVENUE':>11s}"
    )
    print("  " + "-" * 72)
    for b in ranked:
        score_str = (
            "n/a" if b["outcome_score"] is None
            else f"{b['outcome_score']:.0%}"
        )
        print(
            f"  {b['store_id']:<22s} "
            f"{b['executed']:>5d} "
            f"{b['failed']:>5d} "
            f"{b['pending']:>5d} "
            f"{b['positive_outcomes']:>4d} "
            f"{b['negative_outcomes']:>4d} "
            f"{score_str:>6s} "
            f"${b['revenue']:>10,.2f}"
        )
    print()
    score_str = (
        "n/a" if (rollup["total_positive"]
                  + rollup["total_negative"]) == 0
        else (
            f"{rollup['total_positive'] / (rollup['total_positive'] + rollup['total_negative']):.0%}"
        )
    )
    print(
        f"  Rollup:  "
        f"{rollup['stores_with_activity']} store(s) with activity, "
        f"{rollup['total_executed']} executed, "
        f"{rollup['total_failed']} failed, "
        f"score={score_str}, "
        f"rev=${rollup['total_revenue']:,.2f}"
    )


def _cmd_engine_compare(args) -> None:
    """Head-to-head fleet comparison of two engines.

    For each engine, compute fleet-wide totals over the window:
    executed / failed / pending counts + outcome polarity +
    revenue. Surface side-by-side with a winner per metric so
    operators see at a glance "engine A executes more but
    engine B has better outcome polarity -- maybe B's the
    right pick for new stores".
    """
    as_json = bool(getattr(args, "json", False))
    engine_a = (getattr(args, "engine_a", "") or "").strip()
    engine_b = (getattr(args, "engine_b", "") or "").strip()
    window_hours = max(
        1, int(getattr(args, "window_hours", 168) or 168),
    )
    cutoff = time.time() - window_hours * 3600.0

    def _emit_error(msg: str) -> None:
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"Error: {msg}")
        sys.exit(1)

    if not engine_a or not engine_b:
        _emit_error("both engine_a and engine_b are required")
        return
    if engine_a == engine_b:
        _emit_error("engine_a and engine_b must be different")
        return

    try:
        from core.approval.queue import get_approval_queue
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"approval queue unavailable: {exc}")
        return

    queue = get_approval_queue()

    def _profile(engine: str) -> dict:
        bucket = {
            "engine": engine,
            "executed": 0, "failed": 0, "pending": 0,
            "positive_outcomes": 0,
            "negative_outcomes": 0,
            "neutral_outcomes": 0,
            "revenue": 0.0,
        }
        try:
            with queue._conn:
                rows = queue._conn.execute(
                    """SELECT id, status FROM pending_actions
                       WHERE engine = ?
                         AND (decided_at >= ? OR
                              (decided_at IS NULL
                               AND proposed_at >= ?))""",
                    (engine, cutoff, cutoff),
                ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "engine compare scan raised: %s", exc,
            )
            rows = []
        from core.approval.outcome_aggregator import (
            aggregate_outcomes,
        )
        for r in rows:
            status = (r["status"] or "").lower()
            if status == "executed":
                bucket["executed"] += 1
                try:
                    outcomes = queue.get_outcomes(r["id"]) or []
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "engine compare outcomes raised: %s", exc,
                    )
                    outcomes = []
                rollup = aggregate_outcomes(outcomes)
                bucket["positive_outcomes"] += rollup.positive
                bucket["negative_outcomes"] += rollup.negative
                bucket["neutral_outcomes"] += rollup.neutral
                bucket["revenue"] += rollup.revenue
            elif status == "failed":
                bucket["failed"] += 1
            elif status in {"pending", "approved"}:
                bucket["pending"] += 1
        pos = bucket["positive_outcomes"]
        neg = bucket["negative_outcomes"]
        bucket["outcome_score"] = (
            pos / (pos + neg) if (pos + neg) > 0 else None
        )
        return bucket

    prof_a = _profile(engine_a)
    prof_b = _profile(engine_b)

    # Quarantine flags side-by-side: an engine winning on score
    # but currently alert_paused is worth flagging visibly so
    # operators don't pick the paused one.
    qstate = None
    try:
        from core.approval import quarantine as qm
        qstate = qm.load_state()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engine compare quarantine probe raised: %s", exc,
        )
    for prof in (prof_a, prof_b):
        engine = prof["engine"]
        flags: list[str] = []
        if qstate is not None:
            if qstate.is_exempt(engine):
                flags.append("exempt")
            if qstate.is_released(engine):
                flags.append("released")
            if qstate.is_alert_paused(engine):
                flags.append("alert_paused")
        prof["flags"] = flags

    def _winner(key: str, higher_is_better: bool = True) -> str:
        va = prof_a.get(key)
        vb = prof_b.get(key)
        # Treat None as "no data" -> not winner
        if va is None and vb is None:
            return "tie"
        if va is None:
            return engine_b
        if vb is None:
            return engine_a
        if va == vb:
            return "tie"
        if higher_is_better:
            return engine_a if va > vb else engine_b
        return engine_a if va < vb else engine_b

    winners = {
        "executed": _winner("executed"),
        "failed": _winner("failed", higher_is_better=False),
        "positive_outcomes": _winner("positive_outcomes"),
        "negative_outcomes": _winner(
            "negative_outcomes", higher_is_better=False,
        ),
        "outcome_score": _winner("outcome_score"),
        "revenue": _winner("revenue"),
    }

    envelope = {
        "engine_a": prof_a,
        "engine_b": prof_b,
        "window_hours": window_hours,
        "winners": winners,
    }

    if as_json:
        print(json.dumps(envelope, indent=2, default=str))
        return

    print(
        f"Engine compare (last {window_hours}h):  "
        f"{engine_a}  vs  {engine_b}"
    )
    print()

    def _score_str(s):
        return "n/a" if s is None else f"{s:.0%}"

    flags_a = ",".join(prof_a.get("flags") or []) or "-"
    flags_b = ",".join(prof_b.get("flags") or []) or "-"
    rows = [
        ("executed", prof_a["executed"], prof_b["executed"],
         winners["executed"], False),
        ("failed", prof_a["failed"], prof_b["failed"],
         winners["failed"], False),
        ("pending", prof_a["pending"], prof_b["pending"],
         "-", False),
        ("positive_outcomes",
         prof_a["positive_outcomes"],
         prof_b["positive_outcomes"],
         winners["positive_outcomes"], False),
        ("negative_outcomes",
         prof_a["negative_outcomes"],
         prof_b["negative_outcomes"],
         winners["negative_outcomes"], False),
        ("outcome_score",
         _score_str(prof_a["outcome_score"]),
         _score_str(prof_b["outcome_score"]),
         winners["outcome_score"], False),
        ("revenue",
         f"${prof_a['revenue']:,.2f}",
         f"${prof_b['revenue']:,.2f}",
         winners["revenue"], False),
        ("flags", flags_a, flags_b, "-", False),
    ]

    a_label = engine_a[:15]
    b_label = engine_b[:15]
    print(
        f"  {'METRIC':<20s} {a_label:>15s} {b_label:>15s} "
        f"{'WINNER':>20s}"
    )
    print("  " + "-" * 73)
    for metric, va, vb, w, _ in rows:
        print(
            f"  {metric:<20s} {str(va):>15s} {str(vb):>15s} "
            f"{w[:20]:>20s}"
        )



def _cmd_engine_ranking(args) -> None:
    """Rank every active engine fleet-wide by outcome score +
    executed count.

    Operators want a single-glance answer to 'which engines are
    actually working across my fleet?'. ``engine summary`` is
    per-engine drill; ``engine compare`` is two-engine head-
    to-head; this is the fleet-wide leaderboard.

    Per-engine bucket (over the window):
      - executed / failed / pending
      - positive_outcomes / negative_outcomes / neutral_outcomes
      - outcome_score = positive / (positive + negative); None
        on no polarised events
      - revenue summed across outcome metrics

    Ranking: engines with a non-None outcome_score first (sorted
    by score desc), then engines with no polarised events
    (sorted by executed desc). Ties broken by executed desc,
    then by engine name asc for determinism.
    """
    as_json = bool(getattr(args, "json", False))
    window_hours = max(
        1, int(getattr(args, "window_hours", 168) or 168),
    )
    limit = max(1, int(getattr(args, "limit", 20) or 20))
    cutoff = time.time() - window_hours * 3600.0

    def _emit_error(msg: str) -> None:
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"Error: {msg}")
        sys.exit(1)

    try:
        from core.approval.queue import get_approval_queue
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"approval queue unavailable: {exc}")
        return

    queue = get_approval_queue()
    by_engine: dict[str, dict] = {}

    def _bucket(name: str) -> dict:
        if name not in by_engine:
            by_engine[name] = {
                "engine": name,
                "executed": 0, "failed": 0, "pending": 0,
                "positive_outcomes": 0,
                "negative_outcomes": 0,
                "neutral_outcomes": 0,
                "revenue": 0.0,
            }
        return by_engine[name]

    try:
        with queue._conn:
            rows = queue._conn.execute(
                """SELECT id, engine, status FROM pending_actions
                   WHERE (decided_at >= ? OR
                          (decided_at IS NULL
                           AND proposed_at >= ?))""",
                (cutoff, cutoff),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"queue scan failed: {exc}")
        return

    from core.approval.outcome_aggregator import (
        aggregate_outcomes,
    )
    for r in rows:
        engine = r["engine"] or "(unknown)"
        bucket = _bucket(engine)
        status = (r["status"] or "").lower()
        if status == "executed":
            bucket["executed"] += 1
            try:
                outcomes = queue.get_outcomes(r["id"]) or []
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "engine ranking outcomes raised: %s", exc,
                )
                outcomes = []
            rollup = aggregate_outcomes(outcomes)
            bucket["positive_outcomes"] += rollup.positive
            bucket["negative_outcomes"] += rollup.negative
            bucket["neutral_outcomes"] += rollup.neutral
            bucket["revenue"] += rollup.revenue
        elif status == "failed":
            bucket["failed"] += 1
        elif status in {"pending", "approved"}:
            bucket["pending"] += 1

    for b in by_engine.values():
        pos = b["positive_outcomes"]
        neg = b["negative_outcomes"]
        b["outcome_score"] = (
            pos / (pos + neg) if (pos + neg) > 0 else None
        )

    # Quarantine flags: lazy probe so a corrupt state file
    # doesn't break the ranking. Each engine gets a ``flags``
    # list of any of {exempt, released, alert_paused} so the
    # leaderboard shows what's paused at a glance.
    qstate = None
    try:
        from core.approval import quarantine as qm
        qstate = qm.load_state()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engine ranking quarantine probe raised: %s", exc,
        )
    for b in by_engine.values():
        engine = b["engine"]
        flags: list[str] = []
        if qstate is not None:
            if qstate.is_exempt(engine):
                flags.append("exempt")
            if qstate.is_released(engine):
                flags.append("released")
            if qstate.is_alert_paused(engine):
                flags.append("alert_paused")
        b["flags"] = flags

    # Ranking: scored engines first (by score desc), then
    # unscored (by executed desc). Stable tiebreaks for
    # determinism.
    def _key(b):
        score = b["outcome_score"]
        return (
            0 if score is not None else 1,  # scored first
            -(score if score is not None else 0),  # higher score
            -b["executed"],
            b["engine"],
        )

    ranked = sorted(by_engine.values(), key=_key)
    top = ranked[:limit]

    envelope = {
        "window_hours": window_hours,
        "limit": limit,
        "engine_count": len(by_engine),
        "engines": top,
    }

    if as_json:
        print(json.dumps(envelope, indent=2, default=str))
        return

    if not top:
        print(f"No engine activity in last {window_hours}h.")
        return

    print(
        f"Engine ranking (last {window_hours}h, "
        f"{len(by_engine)} engine(s) active):"
    )
    print()
    print(
        f"  {'RANK':>4s}  {'ENGINE':<22s} {'EXEC':>5s} "
        f"{'FAIL':>5s} {'+':>4s} {'-':>4s} {'SCORE':>6s} "
        f"{'REVENUE':>11s}  FLAGS"
    )
    print("  " + "-" * 76)
    for i, b in enumerate(top, start=1):
        score_str = (
            "n/a" if b["outcome_score"] is None
            else f"{b['outcome_score']:.0%}"
        )
        flags_str = ",".join(b.get("flags") or []) or ""
        print(
            f"  [{i:>2d}]  {b['engine']:<22s} "
            f"{b['executed']:>5d} {b['failed']:>5d} "
            f"{b['positive_outcomes']:>4d} "
            f"{b['negative_outcomes']:>4d} "
            f"{score_str:>6s} "
            f"${b['revenue']:>10,.2f}  {flags_str}"
        )


def _cmd_engine_alerts(args) -> None:
    """Flag engines whose recent outcome score has degraded
    relative to a longer baseline window.

    For each engine with executed activity in the recent
    window, compute outcome_score over BOTH the recent window
    (default 24h) and a baseline window (default 168h = 7 days).
    Alert when:
      - recent has at least ``--min-recent`` polarised outcomes
        (signal isn't pure noise)
      - baseline also has at least ``--min-recent`` polarised
        outcomes (we have something to compare against)
      - baseline_score - recent_score >= ``--threshold``

    Pure read from ``pending_actions`` + ``action_outcomes``.
    Cheap to run; suitable for cron alongside ``daily-brief``.
    """
    as_json = bool(getattr(args, "json", False))
    recent_hours = max(
        1, int(getattr(args, "recent_hours", 24) or 24),
    )
    baseline_hours = max(
        1, int(getattr(args, "baseline_hours", 168) or 168),
    )
    threshold = max(
        0.0, float(getattr(args, "threshold", 0.2) or 0.2),
    )
    min_recent = max(
        1, int(getattr(args, "min_recent", 3) or 3),
    )

    def _emit_error(msg: str) -> None:
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"Error: {msg}")
        sys.exit(1)

    if baseline_hours <= recent_hours:
        _emit_error(
            "--baseline-hours must exceed --recent-hours "
            "(otherwise the baseline overlaps the recent window)"
        )
        return

    # Delegate the detection logic to the shared module
    # (PR #282). Module raises ValueError on baseline<=recent
    # which we already validated above. Other queue exceptions
    # propagate -- we catch them here for the CLI envelope.
    try:
        from core.approval.outcome_trends import (
            compute_engine_alerts,
            compute_engine_alerts_per_store,
        )
        from core.approval.queue import get_approval_queue
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"approval queue unavailable: {exc}")
        return

    queue = get_approval_queue()
    per_store = bool(getattr(args, "per_store", False))

    try:
        if per_store:
            engine_alerts = compute_engine_alerts_per_store(
                queue,
                recent_hours=float(recent_hours),
                baseline_hours=float(baseline_hours),
                threshold=threshold,
                min_recent=min_recent,
            )
        else:
            engine_alerts = compute_engine_alerts(
                queue,
                recent_hours=float(recent_hours),
                baseline_hours=float(baseline_hours),
                threshold=threshold,
                min_recent=min_recent,
            )
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"queue scan failed: {exc}")
        return

    # Count distinct engines surveyed (same baseline window).
    # The module doesn't expose this; one cheap COUNT keeps the
    # envelope's ``engine_count`` field stable for callers.
    # Defensive: ``row["n"]`` might come back as a non-number
    # under MagicMock-based test fakes, so we type-check before
    # coercing.
    baseline_cutoff = time.time() - baseline_hours * 3600.0
    engine_count = 0
    try:
        with queue._conn:
            row = queue._conn.execute(
                """SELECT COUNT(DISTINCT engine) AS n
                   FROM pending_actions
                   WHERE status = 'executed'
                     AND decided_at >= ?""",
                (baseline_cutoff,),
            ).fetchone()
        if row is not None:
            raw_n = (
                row["n"] if hasattr(row, "__getitem__") else None
            )
            if isinstance(raw_n, (int, float)):
                engine_count = int(raw_n)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engine alerts engine_count probe raised: %s", exc,
        )

    # Quarantine flags per alerted engine: an alert against an
    # already-paused engine is informational only (the bridge
    # has already acted). Surface the flag so operators can
    # de-prioritise those.
    qstate = None
    try:
        from core.approval import quarantine as qm
        qstate = qm.load_state()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engine alerts quarantine probe raised: %s", exc,
        )

    def _engine_flags(name: str) -> list[str]:
        if qstate is None:
            return []
        out: list[str] = []
        if qstate.is_exempt(name):
            out.append("exempt")
        if qstate.is_released(name):
            out.append("released")
        if qstate.is_alert_paused(name):
            out.append("alert_paused")
        return out

    alerts = [
        {
            "engine": a.engine,
            "store_id": getattr(a, "store_id", None),
            "recent_executed": a.recent_executed,
            "baseline_executed": a.baseline_executed,
            "recent_score": a.recent_score,
            "baseline_score": a.baseline_score,
            "recent_polarised": a.recent_polarised,
            "baseline_polarised": a.baseline_polarised,
            "drop": a.drop,
            "kind": a.kind,
            "detail": a.detail,
            "flags": _engine_flags(a.engine),
        }
        for a in engine_alerts
    ]

    envelope = {
        "recent_hours": recent_hours,
        "baseline_hours": baseline_hours,
        "threshold": threshold,
        "min_recent": min_recent,
        "per_store": per_store,
        "engine_count": engine_count,
        "alert_count": len(alerts),
        "alerts": alerts,
    }

    if as_json:
        print(json.dumps(envelope, indent=2, default=str))
        return

    print(
        f"Engine alerts (recent={recent_hours}h, "
        f"baseline={baseline_hours}h, threshold={threshold:.0%}):"
    )
    print()
    if not alerts:
        if engine_count == 0:
            print(f"No engine activity in last {baseline_hours}h.")
        else:
            print(
                f"No alerts. {engine_count} engine(s) surveyed; "
                "no recent score drops past threshold."
            )
        return

    suffix = " (per-store)" if per_store else ""
    print(f"  {len(alerts)} alert(s) flagged{suffix}:")
    for a in alerts:
        store_label = (
            f"@{a['store_id']}" if a.get("store_id")
            else ""
        )
        engine_label = f"{a['engine']}{store_label}"
        flags_str = (
            f"  [{','.join(a['flags'])}]"
            if a.get("flags") else ""
        )
        print(
            f"  [{a['drop']:.0%} drop] {engine_label:<32s}  "
            f"{a['detail']}{flags_str}"
        )
        print(
            f"      recent executed={a['recent_executed']} "
            f"({a['recent_polarised']} polarised)  "
            f"baseline executed={a['baseline_executed']} "
            f"({a['baseline_polarised']} polarised)"
        )


def _cmd_engines_writebacks(args) -> None:
    """Catalog Phase 6/7 writeback wireup state per engine.

    Operators want a one-glance answer to: "which engines act
    autonomously on Shopify, and which are advisory-only?".
    This surface gives them three buckets:

      * ``wired``: full Phase 6/7 — writer module exists AND
        flow.py has the opt-in flag. Engine acts on Shopify
        when the operator opts in.
      * ``advisory``: no writer module + no opt-in flag.
        Engine only emits recommendations; operator must
        action manually.
      * ``partial``: half-wired — writer OR opt-in flag, not
        both. Indicates incomplete rollout; the next thing to
        fix.

    Today's catalog (per scan): 22 wired / 113 advisory / 0
    partial. The wired set covers ~16% of engines; subsequent
    Phase 7 candidates (e.g. dropshipping, gift_card,
    subscription) will push that higher.
    """
    from engines._writeback_audit import audit_writeback_coverage

    try:
        report = audit_writeback_coverage("engines")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "writeback audit raised: %s", exc,
        )
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"Writeback audit unavailable: {exc}")
        return

    filter_mode = getattr(args, "filter", "all") or "all"
    if filter_mode == "all":
        engines_filtered = report.engines
    else:
        engines_filtered = [
            s for s in report.engines if s.status == filter_mode
        ]

    if getattr(args, "json", False):
        print(json.dumps({
            "summary": {
                "total_engines": report.total_engines,
                "wired": report.wired_count,
                "advisory": report.advisory_count,
                "partial": report.partial_count,
            },
            "filter": filter_mode,
            "engines": [
                {
                    "name": s.name,
                    "status": s.status,
                    "writer_files": s.writer_files,
                    "opt_in_flags": s.opt_in_flags,
                }
                for s in engines_filtered
            ],
        }, indent=2, default=str))
        return

    # Text render
    coverage_pct = (
        round(100 * report.wired_count / report.total_engines)
        if report.total_engines else 0
    )
    print(
        f"Engine writeback coverage: "
        f"{report.wired_count}/{report.total_engines} wired "
        f"({coverage_pct}%) — "
        f"{report.advisory_count} advisory, "
        f"{report.partial_count} partial"
    )

    if not engines_filtered:
        print()
        print(f"No engines match filter '{filter_mode}'.")
        return

    if filter_mode != "all":
        print(
            f"\nFiltered to status='{filter_mode}' "
            f"({len(engines_filtered)} engines):"
        )

    # Sort: wired first, then partial, then advisory; within
    # each bucket alphabetical
    status_rank = {"wired": 0, "partial": 1, "advisory": 2}
    sorted_engines = sorted(
        engines_filtered,
        key=lambda s: (status_rank.get(s.status, 9), s.name),
    )

    print()
    print("  engine                          status     writers  opt-ins")
    for s in sorted_engines:
        marker = (
            "!" if s.status == "partial"
            else " "
        )
        engine_label = s.name[:30]
        writers_count = len(s.writer_files)
        opt_ins_count = len(s.opt_in_flags)
        print(
            f"{marker} {engine_label:<30}  "
            f"{s.status:<9}  "
            f"{writers_count:>7}  "
            f"{opt_ins_count:>7}"
        )

    if filter_mode == "all" and report.partial_count > 0:
        print()
        print(
            f"NOTE: {report.partial_count} engine(s) are "
            "partially wired -- pass --filter partial to "
            "investigate."
        )


def _collect_engines_stats(top_n: int, filter_mode: str) -> dict:
    """Aggregate per-engine activity into a structured dict.

    Combines three signals per engine:
      - Wiring status (wired / advisory / partial) from
        engines._writeback_audit
      - Queue activity counts (pending / approved / rejected /
        executed / failed / expired) from ApprovalQueue.stats_by_engine
      - Total registered engine count

    The dict shape is stable: ``{summary, engines: [...]}``.
    Each engine entry has name + wiring + queue counts +
    derived "total_actions" + "successful_actions" fields.
    """
    out: dict = {
        "summary": {
            "total_engines": 0,
            "wired": 0,
            "advisory": 0,
            "partial": 0,
            "active": 0,
            "idle": 0,
        },
        "engines": [],
        "filter": filter_mode,
        "top_n": top_n,
    }

    # ── Registry ────────────────────────────────────────────
    try:
        from engines.registry import list_engines
        all_engine_names = sorted(list_engines())
        out["summary"]["total_engines"] = len(all_engine_names)
    except Exception as exc:  # noqa: BLE001
        logger.debug("engines registry probe raised: %s", exc)
        all_engine_names = []

    # ── Wiring (writeback audit) ────────────────────────────
    wiring_by_name: dict[str, str] = {}
    writers_by_name: dict[str, list[str]] = {}
    try:
        from engines._writeback_audit import audit_writeback_coverage
        wb = audit_writeback_coverage("engines")
        out["summary"]["wired"] = wb.wired_count
        out["summary"]["advisory"] = wb.advisory_count
        out["summary"]["partial"] = wb.partial_count
        for s in wb.engines:
            wiring_by_name[s.name] = s.status
            writers_by_name[s.name] = list(s.writer_files)
    except Exception as exc:  # noqa: BLE001
        logger.debug("writeback audit probe raised: %s", exc)

    # ── Queue activity ──────────────────────────────────────
    queue_stats: dict[str, dict] = {}
    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
        queue_stats = queue.stats_by_engine() or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("queue probe raised: %s", exc)

    # ── Build per-engine entries ────────────────────────────
    entries: list[dict] = []
    for name in all_engine_names:
        stats = queue_stats.get(name, {})
        total_actions = sum(stats.values()) if stats else 0
        successful = (
            stats.get("executed", 0) + stats.get("approved", 0)
        )
        entry = {
            "name": name,
            "wiring": wiring_by_name.get(name, "unknown"),
            "writers": writers_by_name.get(name, []),
            "pending": stats.get("pending", 0),
            "approved": stats.get("approved", 0),
            "rejected": stats.get("rejected", 0),
            "executed": stats.get("executed", 0),
            "failed": stats.get("failed", 0),
            "expired": stats.get("expired", 0),
            "total_actions": total_actions,
            "successful_actions": successful,
        }
        entries.append(entry)

    out["summary"]["active"] = sum(
        1 for e in entries if e["total_actions"] > 0
    )
    out["summary"]["idle"] = (
        out["summary"]["total_engines"]
        - out["summary"]["active"]
    )

    # Filter
    if filter_mode == "active":
        entries = [e for e in entries if e["total_actions"] > 0]
    elif filter_mode == "idle":
        entries = [e for e in entries if e["total_actions"] == 0]

    # Sort by total_actions descending, then alpha for ties
    entries.sort(key=lambda e: (-e["total_actions"], e["name"]))

    out["engines"] = entries[:top_n] if top_n > 0 else entries
    return out


def _cmd_engines_stats(args) -> None:
    """Aggregate engine activity: per-engine queue counts +
    wiring status + activity totals.

    The "which engines are pulling weight?" command. Operators
    daily-glance see which engines are queueing actions and
    which are idle, alongside their Phase 6/7 wiring status.
    """
    top_n = int(getattr(args, "top", 10) or 10)
    filter_mode = getattr(args, "filter", "all") or "all"

    stats = _collect_engines_stats(top_n, filter_mode)

    if getattr(args, "json", False):
        print(json.dumps(stats, indent=2, default=str))
        return

    s = stats["summary"]
    print("ShopAI Engine Activity Stats")
    print()
    print(
        f"  Total engines: {s['total_engines']}"
    )
    print(
        f"    wired:    {s['wired']}, "
        f"advisory: {s['advisory']}, "
        f"partial: {s['partial']}"
    )
    print(
        f"    active:   {s['active']} "
        f"(at least 1 queue action), "
        f"idle: {s['idle']}"
    )

    entries = stats["engines"]
    if not entries:
        print()
        print(f"No engines match filter '{filter_mode}'.")
        return

    if filter_mode != "all":
        print()
        print(
            f"Filtered to {filter_mode}: showing "
            f"{len(entries)} engine(s) "
            f"(top {top_n}):"
        )
    else:
        print()
        print(
            f"Top {len(entries)} engines by queue activity:"
        )
    print()
    # Compact table
    header = (
        f"  {'engine':<28} {'wiring':<10} "
        f"{'exec':>5} {'fail':>5} {'pend':>5} {'total':>6}"
    )
    print(header)
    print(f"  {'-' * (len(header) - 2)}")
    for e in entries:
        engine_label = e["name"][:28]
        wiring = e["wiring"]
        print(
            f"  {engine_label:<28} {wiring:<10} "
            f"{e['executed']:>5} {e['failed']:>5} "
            f"{e['pending']:>5} {e['total_actions']:>6}"
        )


def _render_catalog_markdown(report, entries) -> None:
    """Emit the catalog as a Markdown document.

    Renders a header summary + a table-of-contents anchor list +
    per-action sections with description, dispatcher, capability,
    claiming adapter(s), required scopes, and emitting engines.

    Deterministic ordering (entries already alphabetised by
    action_type from the builder) so the rendered doc is
    stable across runs -- a snapshot of the catalog can be
    committed and diffed.
    """
    print("# ShopAI Action Catalog")
    print()
    print(
        f"_{len(report.entries)} dispatcher(s) registered, "
        f"{len(entries)} shown after filters._"
    )
    if report.unknown_dispatchers:
        print()
        print(
            f"_{len(report.unknown_dispatchers)} dispatcher(s) "
            "could not be AST-resolved._"
        )
    print()
    print("## Index")
    print()
    for e in entries:
        # GitHub auto-slug: lowercase + non-alphanumerics -> '-'
        slug = e.action_type.lower().replace("_", "-")
        print(f"- [`{e.action_type}`](#{slug})")
    print()

    for e in entries:
        print(f"## `{e.action_type}`")
        print()
        if e.description:
            print(e.description)
            print()
        print(
            f"- **Dispatcher**: `{e.dispatcher_module}."
            f"{e.dispatcher_qualname}`"
        )
        caps = ", ".join(f"`{c}`" for c in e.capabilities) or "_(unresolved)_"
        print(f"- **Capability**: {caps}")
        if e.adapters:
            for a in e.adapters:
                scope_md = (
                    ", ".join(f"`{s}`" for s in a.required_scopes)
                    if a.required_scopes
                    else (
                        "_(scope-independent)_"
                        if a.scope_independent
                        else "_(no scopes declared)_"
                    )
                )
                print(
                    f"- **Adapter**: `{a.name}` "
                    f"(scopes: {scope_md})"
                )
        else:
            print(
                "- **Adapter**: _(no adapter claims this capability)_"
            )
        engines = (
            ", ".join(f"`{en}`" for en in e.emitting_engines)
            or "_(no engine emits this action)_"
        )
        print(f"- **Emitting engines**: {engines}")
        print()


def _render_catalog_by_capability(report, entries, args) -> None:
    """Group catalog entries by capability instead of action_type.

    Answers the operator question: 'which action_types route
    through SHOPIFY_UPDATE_PRODUCT?' Useful when reviewing a
    capability's footprint or planning scope-deprecation.

    Entries that route through multiple capabilities appear
    under each (rare today; only a few dispatchers like
    branchy mints have >1).

    Honors --json for machine consumption: emits
    ``{capability_name: [entries...]}``.
    """
    # cap_name -> [entries...]
    grouped: dict[str, list] = {}
    unrouted: list = []
    for e in entries:
        if not e.capabilities:
            unrouted.append(e)
            continue
        for cap in e.capabilities:
            grouped.setdefault(cap, []).append(e)

    if getattr(args, "json", False):
        payload = {
            "summary": {
                "total_dispatchers": len(report.entries),
                "distinct_capabilities": len(grouped),
                "unrouted_count": len(unrouted),
                "filtered_count": len(entries),
            },
            "by_capability": {
                cap: [
                    {
                        "action_type": e.action_type,
                        "description": e.description,
                        "adapters": [
                            a.name for a in e.adapters
                        ],
                        "aggregate_scopes": list(
                            e.aggregate_scopes,
                        ),
                        "emitting_engines": list(e.emitting_engines),
                    }
                    for e in sorted(
                        cap_entries,
                        key=lambda x: x.action_type,
                    )
                ]
                for cap, cap_entries in sorted(grouped.items())
            },
            "unrouted": [e.action_type for e in unrouted],
        }
        print(json.dumps(payload, indent=2, default=str))
        return

    print(
        f"ShopAI action catalog by capability -- "
        f"{len(grouped)} distinct capability(ies), "
        f"{len(entries)} action(s) total."
    )
    if unrouted:
        print(
            f"  ({len(unrouted)} dispatcher(s) unresolved -- "
            "no capability extracted)"
        )
    print()

    for cap_name in sorted(grouped.keys()):
        cap_entries = sorted(
            grouped[cap_name], key=lambda x: x.action_type,
        )
        # Pull adapter + scopes from the first entry (all entries
        # under one capability share the same adapter aggregation)
        first = cap_entries[0]
        adapter_names = sorted({a.name for a in first.adapters})
        scopes = (
            ", ".join(first.aggregate_scopes)
            if first.aggregate_scopes else "(none)"
        )
        adapters_str = (
            ", ".join(adapter_names) if adapter_names
            else "(no adapter)"
        )
        print(f"  {cap_name}")
        print(f"    adapter:    {adapters_str}")
        print(f"    scopes:     {scopes}")
        print(
            f"    actions ({len(cap_entries)}):"
        )
        for e in cap_entries:
            engines = (
                ", ".join(e.emitting_engines)
                or "(no engine)"
            )
            print(
                f"      {e.action_type:<28}  emitted by: {engines}"
            )
        print()

    if unrouted:
        print("  Unresolved dispatchers (no capability):")
        for e in unrouted:
            print(f"    {e.action_type}")


def _cmd_catalog(args) -> None:
    """Complete action surface in one operator readout.

    For every registered dispatcher, surfaces:
      - action_type + dispatcher fully-qualified name
      - the Capability enum value it routes through
      - claiming adapter(s) + their declared required_scopes
      - emitting engine(s) (which engines enqueue this action_type)

    Master-level visibility — the answer to 'what can ShopAI do?'
    Pure read-only; builds on top of every registry the doctor
    surfaces use (dispatcher registry, Capability enum, adapter
    classes, engines/ AST scan).

    Filters: --engine NAME (engines emitting), --action-type T
    (exact match).
    """
    try:
        from core.approval.catalog import build_catalog
        report = build_catalog()
    except Exception as exc:  # noqa: BLE001
        logger.debug("catalog build raised: %s", exc)
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"Catalog unavailable: {exc}")
        return

    engine_filter = getattr(args, "engine", None)
    action_type_filter = getattr(args, "action_type", None)
    entries = report.entries
    if engine_filter:
        entries = tuple(
            e for e in entries if engine_filter in e.emitting_engines
        )
    if action_type_filter:
        entries = tuple(
            e for e in entries if e.action_type == action_type_filter
        )

    if getattr(args, "markdown", False):
        _render_catalog_markdown(report, entries)
        return

    if getattr(args, "by_capability", False):
        _render_catalog_by_capability(report, entries, args)
        return

    if getattr(args, "json", False):
        payload = {
            "summary": {
                "total_dispatchers": len(report.entries),
                "unknown_dispatchers": list(
                    report.unknown_dispatchers,
                ),
                "filtered_count": len(entries),
            },
            "entries": [
                {
                    "action_type": e.action_type,
                    "description": e.description,
                    "dispatcher": (
                        f"{e.dispatcher_module}."
                        f"{e.dispatcher_qualname}"
                    ),
                    "capabilities": list(e.capabilities),
                    "adapters": [
                        {
                            "name": a.name,
                            "module": a.module,
                            "required_scopes": list(a.required_scopes),
                            "scope_independent": a.scope_independent,
                        }
                        for a in e.adapters
                    ],
                    "aggregate_scopes": list(e.aggregate_scopes),
                    "emitting_engines": list(e.emitting_engines),
                }
                for e in entries
            ],
        }
        print(json.dumps(payload, indent=2, default=str))
        return

    print(
        f"ShopAI action catalog -- "
        f"{len(report.entries)} dispatcher(s) registered"
    )
    if report.unknown_dispatchers:
        print(
            f"  ({len(report.unknown_dispatchers)} could not be "
            "AST-resolved; dispatcher source uses an unrecognised "
            "router-call pattern)"
        )
    if engine_filter or action_type_filter:
        filter_parts = []
        if engine_filter:
            filter_parts.append(f"engine={engine_filter}")
        if action_type_filter:
            filter_parts.append(f"action_type={action_type_filter}")
        print(
            f"  filtered to {' + '.join(filter_parts)}: "
            f"{len(entries)} entry(ies)"
        )
    print()

    if not entries:
        print("No catalog entries match the filter.")
        return

    for e in entries:
        cap_str = ", ".join(e.capabilities) or "(unresolved)"
        engines_str = (
            ", ".join(e.emitting_engines) or "(no engine emits)"
        )
        print(f"  {e.action_type}")
        if e.description:
            print(f"    description: {e.description}")
        print(f"    dispatcher:  {e.dispatcher_qualname}")
        print(f"    capability:  {cap_str}")
        if e.adapters:
            for a in e.adapters:
                scope_str = (
                    ", ".join(a.required_scopes)
                    if a.required_scopes
                    else (
                        "(scope-independent)"
                        if a.scope_independent
                        else "(no scopes declared)"
                    )
                )
                print(
                    f"    adapter:     {a.name}  ({scope_str})"
                )
        else:
            print("    adapter:     (no adapter claims this capability)")
        print(f"    engines:     {engines_str}")
        print()


def _collect_learning_stats(top_n: int) -> dict[str, Any]:
    """Aggregate the three Phase 8 learning sources into one
    structured dict.

    Each section is best-effort -- a missing or broken backend
    surfaces as ``{"error": "..."}`` for that section, leaves
    the others intact.
    """
    out: dict[str, Any] = {}

    # ── MemoryIntelligence ──────────────────────────────────
    try:
        from core.memory.intelligence import MemoryIntelligence
        mi = MemoryIntelligence()
        stats = mi.get_stats()
        meta = mi.get_meta_stats()
        # Top engines by total memory count
        by_cat = stats.get("by_category", {}) or {}
        top_cats = sorted(
            by_cat.items(), key=lambda kv: kv[1], reverse=True,
        )[:top_n]
        out["memory_intelligence"] = {
            "total_memories": stats.get("total_memories", 0),
            "by_level": stats.get("by_level", {}),
            "by_type": stats.get("by_type", {}),
            "promotions": stats.get("promotions", 0),
            "failures": stats.get("failures", 0),
            "avg_score": stats.get("avg_score", 0.0),
            "top_categories": [
                {"category": k, "count": v} for k, v in top_cats
            ],
            "most_used_count": len(meta.get("most_used", [])),
            "never_used_count": meta.get("never_used_count", 0),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("MI stats raised: %s", exc)
        out["memory_intelligence"] = {"error": str(exc)}

    # ── DataArchitecture ───────────────────────────────────
    try:
        from core.data.architecture import DataArchitecture
        da = DataArchitecture()
        da_stats = da.get_stats()
        domains = da_stats.get("domains", {}) or {}
        top_domains = sorted(
            domains.items(),
            key=lambda kv: kv[1].get("total", 0),
            reverse=True,
        )[:top_n]
        out["data_architecture"] = {
            "total_records": da_stats.get("total_records", 0),
            "actions_tracked": da_stats.get("actions_tracked", 0),
            "results_attached": da_stats.get("results_attached", 0),
            "result_rate_pct": da_stats.get("result_rate", 0),
            "top_domains": [
                {
                    "domain": k,
                    "total": v.get("total", 0),
                    "avg_score": v.get("avg_score", 0.0),
                }
                for k, v in top_domains
            ],
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("DA stats raised: %s", exc)
        out["data_architecture"] = {"error": str(exc)}

    # ── LearningLoop ───────────────────────────────────────
    try:
        from core.brain.learning_loop import LearningLoop
        ll = LearningLoop()
        ll_stats = ll.get_stats() or {}
        memory = ll_stats.get("memory", {}) or {}
        out["learning_loop"] = {
            "total_learnings": ll_stats.get("total_learnings", 0),
            "by_layer": memory.get("by_layer", {}),
            "patterns": memory.get("patterns", 0),
            "rules": memory.get("rules", 0),
            "bad_data": memory.get("bad_data", 0),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("LL stats raised: %s", exc)
        out["learning_loop"] = {"error": str(exc)}

    return out


def _cmd_learning(args) -> None:
    """Dispatch ``shopai learning <verb>`` subcommands."""
    verb = getattr(args, "learning_action", None)
    if verb == "stats":
        _cmd_learning_stats(args)
        return
    print(
        "Usage:\n"
        "  shopai learning stats [--top N] [--json]"
    )
    sys.exit(1)


def _cmd_learning_stats(args) -> None:
    """Surface what the Phase 8 autonomous learning loop has
    recorded across MemoryIntelligence + DataArchitecture +
    LearningLoop.

    The "what has the system learned?" command. Operators see
    the OUTPUT of the loop -- previously only the INPUT side
    (writebacks) was visible.
    """
    top_n = int(getattr(args, "top", 10) or 10)
    stats = _collect_learning_stats(top_n)

    if getattr(args, "json", False):
        print(json.dumps(stats, indent=2, default=str))
        return

    print("ShopAI Phase 8 Learning Stats")
    print()
    _render_learning_mi(stats.get("memory_intelligence", {}))
    print()
    _render_learning_da(stats.get("data_architecture", {}))
    print()
    _render_learning_ll(stats.get("learning_loop", {}))


def _render_learning_mi(section: dict) -> None:
    if "error" in section:
        print(
            f"[??] Memory Intelligence -- "
            f"{section['error']}"
        )
        return
    total = section.get("total_memories", 0)
    fails = section.get("failures", 0)
    avg = section.get("avg_score", 0.0)
    promotions = section.get("promotions", 0)
    by_level = section.get("by_level", {})
    by_type = section.get("by_type", {})
    print(
        f"Memory Intelligence -- {total} memories "
        f"(avg score {avg:.2f}, {fails} failures, "
        f"{promotions} promotions)"
    )
    if by_level:
        levels = ", ".join(
            f"{k}={v}" for k, v in sorted(by_level.items())
        )
        print(f"  by_level:  {levels}")
    if by_type:
        types = ", ".join(
            f"{k}={v}" for k, v in sorted(by_type.items())
        )
        print(f"  by_type:   {types}")
    cats = section.get("top_categories", [])
    if cats:
        print(f"  top engines by memory count:")
        for c in cats:
            print(f"    {c['category']:<28} {c['count']}")


def _render_learning_da(section: dict) -> None:
    if "error" in section:
        print(
            f"[??] Data Architecture -- "
            f"{section['error']}"
        )
        return
    total = section.get("total_records", 0)
    rate = section.get("result_rate_pct", 0)
    actions = section.get("actions_tracked", 0)
    attached = section.get("results_attached", 0)
    print(
        f"Data Architecture -- {total} records across 12 domains "
        f"({rate}% attach rate: {attached}/{actions} actions "
        "have results)"
    )
    domains = section.get("top_domains", [])
    if domains:
        print(f"  top domains:")
        for d in domains:
            print(
                f"    {d['domain']:<14} {d['total']:>6}  "
                f"avg_score {d['avg_score']:.2f}"
            )


def _render_learning_ll(section: dict) -> None:
    if "error" in section:
        print(
            f"[??] Learning Loop -- "
            f"{section['error']}"
        )
        return
    learnings = section.get("total_learnings", 0)
    patterns = section.get("patterns", 0)
    rules = section.get("rules", 0)
    bad = section.get("bad_data", 0)
    by_layer = section.get("by_layer", {})
    print(
        f"Learning Loop -- {learnings} learnings, "
        f"{patterns} patterns + {rules} rules detected"
        f" ({bad} bad-data entries flagged)"
    )
    if by_layer:
        layers = ", ".join(
            f"{k}={v}" for k, v in sorted(by_layer.items())
        )
        print(f"  memory layers: {layers}")


def _diff_snapshots(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    """Compute the operator-visible delta between two snapshots.

    Surfaces the seven changes operators actually care about:

      - ``overall_ok`` flipped
      - engine counts changed (total / wired / advisory /
        partial)
      - catalog entries added / removed / changed
      - per-audit ``ok`` flipped (each of pattern_k / oauth /
        pattern_y / pattern_i / pattern_j)

    Intentionally NOT a deep recursive diff: a release-to-release
    review focuses on the seven listed signals; the raw JSON is
    still available via the regular snapshot output for deep
    forensic inspection. The diff envelope's ``has_changes`` flag
    drives the CLI exit code (1 on diff, 0 on clean).
    """
    diff: dict[str, Any] = {
        "baseline_generated_at": baseline.get("generated_at"),
        "current_generated_at": current.get("generated_at"),
        "changes": {},
        "has_changes": False,
    }

    # overall_ok
    if baseline.get("overall_ok") != current.get("overall_ok"):
        diff["changes"]["overall_ok"] = {
            "baseline": baseline.get("overall_ok"),
            "current": current.get("overall_ok"),
        }
        diff["has_changes"] = True

    # engine counts
    b_counts = baseline.get("engine_counts") or {}
    c_counts = current.get("engine_counts") or {}
    count_changes: dict[str, Any] = {}
    for key in ("total", "wired", "advisory", "partial"):
        if b_counts.get(key) != c_counts.get(key):
            count_changes[key] = {
                "baseline": b_counts.get(key),
                "current": c_counts.get(key),
            }
    if count_changes:
        diff["changes"]["engine_counts"] = count_changes
        diff["has_changes"] = True

    # catalog entries (compare by action_type key)
    b_entries = {
        e["action_type"]: e
        for e in (baseline.get("catalog") or {}).get("entries", [])
    }
    c_entries = {
        e["action_type"]: e
        for e in (current.get("catalog") or {}).get("entries", [])
    }
    added = sorted(set(c_entries) - set(b_entries))
    removed = sorted(set(b_entries) - set(c_entries))
    changed: list[dict[str, Any]] = []
    for action_type in sorted(set(b_entries) & set(c_entries)):
        b = b_entries[action_type]
        c = c_entries[action_type]
        # Compare the fields that matter for operator review:
        # capability, adapter list, scopes, emitting engines.
        # Ignore dispatcher qualname changes (refactors).
        per_change: dict[str, Any] = {}
        for field in (
            "capabilities",
            "aggregate_scopes",
            "emitting_engines",
        ):
            if list(b.get(field, [])) != list(c.get(field, [])):
                per_change[field] = {
                    "baseline": b.get(field),
                    "current": c.get(field),
                }
        b_adapters = sorted(
            (a.get("name", "") for a in b.get("adapters", [])),
        )
        c_adapters = sorted(
            (a.get("name", "") for a in c.get("adapters", [])),
        )
        if b_adapters != c_adapters:
            per_change["adapters"] = {
                "baseline": b_adapters,
                "current": c_adapters,
            }
        if per_change:
            changed.append({
                "action_type": action_type,
                "changes": per_change,
            })
    if added or removed or changed:
        diff["changes"]["catalog"] = {
            "added": added,
            "removed": removed,
            "changed": changed,
        }
        diff["has_changes"] = True

    # audits (each ok flag)
    b_audits = baseline.get("audits") or {}
    c_audits = current.get("audits") or {}
    audit_flips: dict[str, Any] = {}
    for name in sorted(set(b_audits) | set(c_audits)):
        b_ok = (b_audits.get(name) or {}).get("ok")
        c_ok = (c_audits.get(name) or {}).get("ok")
        if b_ok != c_ok:
            audit_flips[name] = {
                "baseline": b_ok,
                "current": c_ok,
            }
    if audit_flips:
        diff["changes"]["audits"] = audit_flips
        diff["has_changes"] = True

    return diff


def _cmd_snapshot(args) -> None:
    """Capture the complete system state in one committable JSON
    artifact.

    The snapshot bundles every existing audit, doctor, and
    catalog into a single deterministic dict suitable for git
    archival. Operators commit the snapshot when they release
    and diff future captures against it to surface drift.

    Fields:
      - ``generated_at``: ISO 8601 UTC timestamp
      - ``engine_counts``: total / wired / advisory / partial
      - ``catalog``: full action surface (dispatcher -> capability
        -> adapter -> scopes -> engines)
      - ``audits``: pattern_k / oauth / pattern_y / pattern_i /
        pattern_j summaries
      - ``doctor_shopify``: doctor section dict (without live
        drift if --skip-live)
      - ``doctor_approvals``: approval-queue doctor sections

    With ``--output FILE`` the snapshot is written to disk;
    otherwise it's emitted to stdout. ``--force`` overwrites
    existing files (matches the shopify-app-toml --force
    semantics).
    """
    import time as _time
    from datetime import datetime, timezone

    snapshot: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
    }

    # ── Engine counts (Phase 6/7 writeback wiring) ──────────
    try:
        from engines._writeback_audit import audit_writeback_coverage
        wb = audit_writeback_coverage("engines")
        snapshot["engine_counts"] = {
            "total": wb.total_engines,
            "wired": wb.wired_count,
            "advisory": wb.advisory_count,
            "partial": wb.partial_count,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("engine count audit raised: %s", exc)
        snapshot["engine_counts"] = {"error": str(exc)}

    # ── Catalog ─────────────────────────────────────────────
    try:
        from core.approval.catalog import build_catalog
        catalog = build_catalog()
        snapshot["catalog"] = {
            "total_dispatchers": len(catalog.entries),
            "unknown_dispatchers": list(catalog.unknown_dispatchers),
            "entries": [
                {
                    "action_type": e.action_type,
                    "dispatcher": (
                        f"{e.dispatcher_module}."
                        f"{e.dispatcher_qualname}"
                    ),
                    "capabilities": list(e.capabilities),
                    "adapters": [
                        {
                            "name": a.name,
                            "required_scopes": list(a.required_scopes),
                            "scope_independent": a.scope_independent,
                        }
                        for a in e.adapters
                    ],
                    "aggregate_scopes": list(e.aggregate_scopes),
                    "emitting_engines": list(e.emitting_engines),
                }
                for e in catalog.entries
            ],
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("catalog raised: %s", exc)
        snapshot["catalog"] = {"error": str(exc)}

    # ── Audits summary ──────────────────────────────────────
    audits: dict[str, Any] = {}
    # Pattern K
    try:
        from core.approval.coverage_audit import audit_coverage
        from pathlib import Path as _P
        r = audit_coverage(_P("engines"))
        audits["pattern_k"] = {
            "ok": not r.has_gaps,
            "enqueue_sites": len(r.enqueued),
            "dispatchers_registered": len(r.registered),
            "missing": sorted(r.missing),
            "orphaned": sorted(r.orphaned),
        }
    except Exception as exc:  # noqa: BLE001
        audits["pattern_k"] = {"error": str(exc)}
    # OAuth scope coverage
    try:
        from core.adapters.shopify.scope_registry import collect_manifest
        m = collect_manifest()
        audits["oauth_scopes"] = {
            "ok": not m.undeclared_adapters,
            "total_adapters": m.total_adapters,
            "undeclared_adapters": m.undeclared_adapters,
            "scope_independent": list(
                m.scope_independent_adapters,
            ),
            "unique_scopes": sorted(m.all_scopes),
        }
    except Exception as exc:  # noqa: BLE001
        audits["oauth_scopes"] = {"error": str(exc)}
    # Pattern Y
    try:
        from core.adapters.coverage_audit import (
            audit_capability_coverage,
        )
        c = audit_capability_coverage()
        audits["pattern_y"] = {
            "ok": not c.has_gaps,
            "total_capabilities": c.total_shopify_capabilities,
            "claimed_count": c.claimed_count,
            "unclaimed": c.unclaimed,
            "orphan_claims": c.orphan_claims,
        }
    except Exception as exc:  # noqa: BLE001
        audits["pattern_y"] = {"error": str(exc)}
    # Pattern I
    try:
        from engines._engine_capability_audit import (
            audit_engine_capabilities,
        )
        i = audit_engine_capabilities()
        audits["pattern_i"] = {
            "ok": not i.has_gaps,
            "total_refs": i.total_refs,
            "distinct_capabilities": i.distinct_capabilities,
            "unknown_enum_member": [
                f"{r.capability_name} ({r.file}:{r.lineno})"
                for r in i.unknown_enum_member
            ],
            "unclaimed_by_adapter": [
                f"{r.capability_name} ({r.file}:{r.lineno})"
                for r in i.unclaimed_by_adapter
            ],
        }
    except Exception as exc:  # noqa: BLE001
        audits["pattern_i"] = {"error": str(exc)}
    # Pattern J
    try:
        from engines._pattern_j_audit import audit_pattern_j
        j = audit_pattern_j()
        audits["pattern_j"] = {
            "ok": not j.has_violations,
            "scanned_modules": j.scanned_modules,
            "recorder_sites": len(j.recorder_sites),
            "guarded_sites": len(j.guarded_sites),
            "unguarded_sites": [
                f"{s.file}:{s.lineno} {s.receiver_expr}.{s.method}()"
                for s in j.unguarded_sites
            ],
        }
    except Exception as exc:  # noqa: BLE001
        audits["pattern_j"] = {"error": str(exc)}
    snapshot["audits"] = audits

    # ── Doctor verdicts (re-use existing collectors) ───────
    try:
        shopify_ok, shopify_sections = _collect_doctor_sections(args)
        snapshot["doctor_shopify"] = {
            "ok": shopify_ok,
            "sections": shopify_sections,
        }
    except Exception as exc:  # noqa: BLE001
        snapshot["doctor_shopify"] = {"error": str(exc)}
    try:
        approvals_ok, approvals_sections = (
            _collect_approvals_doctor_sections(args)
        )
        snapshot["doctor_approvals"] = {
            "ok": approvals_ok,
            "sections": approvals_sections,
        }
    except Exception as exc:  # noqa: BLE001
        snapshot["doctor_approvals"] = {"error": str(exc)}

    snapshot["overall_ok"] = bool(
        snapshot.get("doctor_shopify", {}).get("ok", True)
        and snapshot.get("doctor_approvals", {}).get("ok", True)
    )

    # ── Diff mode: compare against a committed baseline ─────
    diff_path = getattr(args, "diff", None)
    if diff_path:
        from pathlib import Path as _DP
        baseline_path = _DP(diff_path)
        try:
            baseline = json.loads(
                baseline_path.read_text(encoding="utf-8"),
            )
        except FileNotFoundError:
            print(f"Baseline file not found: {baseline_path}")
            sys.exit(1)
        except json.JSONDecodeError as exc:
            print(f"Baseline is not valid JSON: {exc}")
            sys.exit(1)
        except OSError as exc:
            print(f"Failed to read {baseline_path}: {exc}")
            sys.exit(1)
        diff = _diff_snapshots(baseline, snapshot)
        diff_serialised = json.dumps(diff, indent=2, default=str) + "\n"
        target = getattr(args, "output", None)
        if not target:
            sys.stdout.write(diff_serialised)
        else:
            target_path = _DP(target)
            if (
                target_path.exists()
                and not getattr(args, "force", False)
            ):
                print(
                    f"Refusing to overwrite {target_path} -- "
                    "pass --force to overwrite, or pick a "
                    "different path."
                )
                sys.exit(1)
            try:
                target_path.parent.mkdir(
                    parents=True, exist_ok=True,
                )
                target_path.write_text(
                    diff_serialised, encoding="utf-8",
                )
            except OSError as exc:
                print(f"Failed to write {target_path}: {exc}")
                sys.exit(1)
            print(
                f"Wrote diff to {target_path} "
                f"({len(diff_serialised.splitlines())} lines)"
            )
        # Exit code reflects whether anything changed: 0 for
        # clean (no diff), 1 for diff present, 2 for hard errors
        # (which already exited above). Lets CI alert on drift.
        if diff.get("has_changes"):
            sys.exit(1)
        return

    serialised = json.dumps(snapshot, indent=2, default=str) + "\n"

    target = getattr(args, "output", None)
    if not target:
        sys.stdout.write(serialised)
        return

    from pathlib import Path as _P
    target_path = _P(target)
    if target_path.exists() and not getattr(args, "force", False):
        print(
            f"Refusing to overwrite {target_path} -- pass --force "
            "to overwrite, or pick a different path."
        )
        sys.exit(1)
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(serialised, encoding="utf-8")
    except OSError as exc:
        print(f"Failed to write {target_path}: {exc}")
        sys.exit(1)
    print(
        f"Wrote {target_path} "
        f"({len(serialised.splitlines())} lines)"
    )


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

    # ── Writeback status (Phase 6/7 wiring) ──────────────────
    try:
        from engines._writeback_audit import audit_writeback_coverage
        wb_report = audit_writeback_coverage("engines")
        engine_wb = next(
            (s for s in wb_report.engines if s.name == engine_name),
            None,
        )
        if engine_wb is not None:
            payload["writeback"] = {
                "status": engine_wb.status,
                "writer_files": engine_wb.writer_files,
                "opt_in_flags": engine_wb.opt_in_flags,
            }
    except Exception as exc:  # noqa: BLE001
        logger.debug("writeback audit raised: %s", exc)

    # ── Action chain (from catalog) ──────────────────────────
    try:
        from core.approval.catalog import build_catalog
        catalog = build_catalog()
        emitted = [
            e for e in catalog.entries
            if engine_name in e.emitting_engines
        ]
        if emitted:
            payload["actions"] = [
                {
                    "action_type": e.action_type,
                    "capability": (
                        list(e.capabilities)[0]
                        if e.capabilities else None
                    ),
                    "adapter": (
                        e.adapters[0].name if e.adapters else None
                    ),
                    "scopes": list(e.aggregate_scopes),
                }
                for e in emitted
            ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("catalog lookup raised: %s", exc)

    if as_json:
        print(json.dumps(payload, indent=2, default=str))
        return

    print(f"Engine: {payload['name']}")
    print(f"Class:  {payload['class']}")
    if payload["inputs"]:
        print(f"Inputs: {payload['inputs']}")
    if payload["outputs"]:
        print(f"Outputs: {payload['outputs']}")

    # Writeback wiring section
    wb = payload.get("writeback")
    if wb is not None:
        print()
        print(f"Writeback:  {wb['status']}")
        if wb["writer_files"]:
            print(f"  writers:  {', '.join(wb['writer_files'])}")
        if wb["opt_in_flags"]:
            print(f"  flags:    {', '.join(wb['opt_in_flags'])}")

    # Action chain section
    actions = payload.get("actions")
    if actions:
        print()
        print(f"Actions emitted ({len(actions)}):")
        for a in actions:
            cap = a.get("capability") or "(unresolved)"
            adapter = a.get("adapter") or "(no adapter)"
            scopes = (
                ", ".join(a["scopes"]) if a["scopes"]
                else "(none)"
            )
            print(f"  {a['action_type']}")
            print(f"    capability:  {cap}")
            print(f"    adapter:     {adapter}")
            print(f"    scopes:      {scopes}")

    _print_engine_brain_stack(engine_name)


def _cmd_shopify_scopes(args) -> None:
    """Render the aggregated Shopify OAuth scope manifest.

    Answers "which OAuth scopes does this app need at install
    time?" without reading every adapter file's docstring.

    Three modes:
      - default: union list of every scope any adapter needs
        (operator-friendly install manifest)
      - ``--per-adapter``: grouped breakdown showing exactly
        which adapter pulls in which scope (useful for shrinking
        the install footprint by removing adapters)
      - ``--show-gaps``: lists adapters that haven't declared
        ``required_scopes`` yet (rollout tracking — the wireup
        is incremental and the gap report drives follow-up PRs)

    Over-requesting scopes makes merchants nervous and Shopify's
    review team flag it; under-requesting causes the adapter to
    fail with ACCESS_DENIED at first live call. This surface
    keeps the manifest correct as adapters change.
    """
    try:
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest()
    except Exception as exc:  # noqa: BLE001
        logger.debug("scope manifest collection raised: %s", exc)
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print("Scope manifest unavailable")
        return

    if getattr(args, "json", False):
        payload = {
            "all_scopes": sorted(manifest.all_scopes),
            "by_scope": manifest.by_scope,
            "by_adapter": manifest.by_adapter,
            "undeclared_adapters": (
                manifest.undeclared_adapters
                if getattr(args, "show_gaps", False) else None
            ),
            "scope_independent_adapters": (
                manifest.scope_independent_adapters
            ),
            "total_adapters": manifest.total_adapters,
            "declared_adapter_count": (
                manifest.total_adapters
                - len(manifest.undeclared_adapters)
            ),
        }
        print(json.dumps(payload, indent=2, default=str))
        return

    declared_count = (
        manifest.total_adapters
        - len(manifest.undeclared_adapters)
    )
    independent_count = len(manifest.scope_independent_adapters)
    print(
        f"Shopify OAuth scope manifest "
        f"({declared_count}/{manifest.total_adapters} adapters "
        f"declared; {independent_count} scope-independent):"
    )
    print()

    if getattr(args, "per_adapter", False):
        # Grouped: adapter → its scopes
        declared = [
            (a, scopes)
            for a, scopes in manifest.by_adapter.items()
            if scopes
        ]
        declared.sort(key=lambda kv: kv[0])
        for adapter, scopes in declared:
            print(f"  {adapter}:")
            for s in scopes:
                print(f"    {s}")
    else:
        # Default: flat union, install-manifest-ready
        if not manifest.all_scopes:
            print("  (no scopes declared yet)")
        else:
            for s in sorted(manifest.all_scopes):
                # Show how many adapters pull this scope — helps
                # operators decide whether removing one adapter
                # could shrink the manifest.
                adapter_count = len(manifest.by_scope.get(s, []))
                print(f"  {s:<48} (used by {adapter_count})")

    if getattr(args, "show_gaps", False):
        gaps = manifest.undeclared_adapters
        print()
        print(
            f"Adapters without declared scopes ({len(gaps)}) — "
            "rollout gaps:"
        )
        if not gaps:
            print("  (none)")
        else:
            for a in gaps[:40]:
                print(f"  {a}")
            if len(gaps) > 40:
                print(f"  ... and {len(gaps) - 40} more")


def _cmd_shopify_scopes_audit(args) -> None:
    """CI gate: exit 1 if any Shopify adapter is missing a scope
    declaration.

    The companion to ``shopai approvals audit`` (PR #157 — the
    Pattern K dispatcher coverage gate). Every concrete Shopify
    adapter must declare one of:

      - ``required_scopes = frozenset({...})`` — the OAuth scopes
        it needs at install time
      - ``scope_independent = True`` — sentinel for app-level
        features (app billing, mobile platform) or context-
        dependent surfaces (bulk, generic_tags, shop) that
        legitimately need no extra OAuth scope

    Exit 0 = clean. Exit 1 = at least one adapter has neither
    set, which would silently become a "scope unknown" install
    risk. The audit prints the gap list so the failing CI run's
    output is actionable — operators can wire the missing
    declarations directly from the error message.
    """
    try:
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest()
    except Exception as exc:  # noqa: BLE001
        logger.debug("scope manifest collection raised: %s", exc)
        # Surface the failure but don't exit 1 — a broken
        # registry import is a different bug class from a
        # missing scope declaration. The test suite catches
        # the registry-broken case directly.
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"Scope audit unavailable: {exc}")
        return

    gaps = list(manifest.undeclared_adapters)
    if getattr(args, "json", False):
        print(json.dumps({
            "ok": not gaps,
            "undeclared_count": len(gaps),
            "undeclared_adapters": gaps,
            "total_adapters": manifest.total_adapters,
        }, indent=2))
        if gaps:
            sys.exit(1)
        return

    if not gaps:
        independent = len(manifest.scope_independent_adapters)
        print(
            f"Scope coverage OK — "
            f"{manifest.total_adapters}/{manifest.total_adapters} "
            f"adapters declared "
            f"({independent} scope-independent)."
        )
        return

    print(
        f"Scope coverage FAILED: {len(gaps)} adapter(s) missing "
        "scope declaration."
    )
    print()
    print("Undeclared adapters:")
    for a in gaps:
        print(f"  {a}")
    print()
    print(
        "Fix: add ``required_scopes = frozenset({\"...\"})`` "
        "(or ``scope_independent = True`` for app-level "
        "adapters) to each class. See PR #173 / #176 for "
        "examples."
    )
    sys.exit(1)


def _cmd_launch(args) -> None:
    """Flagship: single-command store launch.

    Calls ``launch_orchestrator.launch_store(...)`` with the
    operator-supplied args and renders the checklist. Each
    step in the orchestrator's output becomes one line in
    the text view so the operator sees what applied, what
    failed, and where to look next.

    Exits 0 by default (the checklist is the result regardless
    of pass/fail). ``--strict`` flips to exit 1 when
    ``ready_to_launch`` is False so CI / autonomous loops can
    gate on it.
    """
    as_json = bool(getattr(args, "json", False))
    strict = bool(getattr(args, "strict", False))
    sm = _get_store_manager()
    store_id = (
        getattr(args, "store_id", None)
        or sm.active_store_id
    )

    try:
        from engines.store_setup.launch_orchestrator import (
            launch_store,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("launch_orchestrator import failed: %s", exc)
        if as_json:
            print(json.dumps({
                "ok": None,
                "error": "launch_orchestrator_unavailable",
                "message": str(exc),
            }, indent=2))
        else:
            print(f"launch unavailable: {exc}")
        return

    try:
        result = launch_store(
            store_name=args.store_name,
            niche=getattr(args, "niche", "general"),
            region=getattr(args, "region", "us"),
            founder_name=getattr(args, "founder_name", None),
            store_id=store_id,
            include_legal_notice=bool(
                getattr(args, "include_legal_notice", False)
            ),
            include_subscription_policy=bool(
                getattr(args, "include_subscription_policy",
                        False)
            ),
            logo_url=getattr(args, "logo_url", None),
            favicon_url=getattr(args, "favicon_url", None),
            hero_url=getattr(args, "hero_url", None),
            og_image_url=getattr(args, "og_image_url", None),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("launch_store raised: %s", exc)
        if as_json:
            print(json.dumps({
                "ok": None,
                "error": "launch_failed",
                "message": str(exc),
            }, indent=2))
        else:
            print(f"launch failed: {exc}")
        return

    # Optionally run launch-audit after the orchestrator. The
    # result is attached to the launch output under
    # ``audit_after_launch`` so JSON callers see both in one
    # payload; text view prints the readiness summary below.
    audit_after: dict | None = None
    if getattr(args, "audit", False):
        try:
            from engines.store_setup.launch_audit import (
                audit_store,
            )
            audit_after = audit_store(store_id=store_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "launch --audit follow-up raised: %s", exc,
            )
            audit_after = {
                "error": "audit_unavailable",
                "message": str(exc),
            }

    if as_json:
        payload = dict(result)
        if audit_after is not None:
            payload["audit_after_launch"] = audit_after
        print(json.dumps(payload, indent=2))
        if strict and not result.get("ready_to_launch"):
            sys.exit(1)
        return

    # ── Text view ───────────────────────────────────────────
    if result.get("error") == "store_name_required":
        print(
            "launch failed: store_name is required (empty "
            "string was supplied)."
        )
        sys.exit(1)

    ready = bool(result.get("ready_to_launch"))
    header = "READY TO LAUNCH" if ready else "NOT READY"
    print(f"Store launch -- {header}")
    print()
    checklist = result.get("checklist") or []
    for entry in checklist:
        step = entry.get("step", "?")
        ok = entry.get("ok", False)
        applied = entry.get("applied", 0)
        skipped = entry.get("skipped", False)
        err = entry.get("error")
        # Skipped steps are "didn't attempt" -- they contribute
        # ok=True but aren't actual writes. Render distinctly
        # so operators don't confuse them with successful
        # applies.
        if skipped:
            mark = "SKIP"
        elif ok:
            mark = "OK  "
        else:
            mark = "FAIL"
        line = f"  [{mark}] {step:<16} applied={applied}"
        if skipped and err:
            line += f"  reason={err}"
        elif err:
            line += f"  error={err}"
        print(line)
    print()
    if ready:
        print(
            f"Store '{args.store_name}' is launchable. "
            "Next: shopai post-launch to enrich SEO + "
            "descriptions."
        )
    else:
        # Surface per-step errors compactly
        failed = [
            f"{c['step']}: {c.get('error') or 'no_writes'}"
            for c in checklist if not c.get("ok")
        ]
        if failed:
            print("Failed steps: " + "; ".join(failed))
        print(
            "Re-run after fixing, or run "
            "`shopai launch-audit` for the full readiness "
            "checklist + fix hints."
        )

    # Optional post-launch audit summary
    if audit_after is not None and not audit_after.get("error"):
        a_checks = audit_after.get("checks") or []
        a_passed = sum(1 for c in a_checks if c.get("ok"))
        a_pct = audit_after.get("completion_pct", 0)
        a_ready = audit_after.get("ready_to_launch", False)
        print()
        print(
            f"Launch-audit follow-up -- "
            f"{'READY' if a_ready else 'NOT READY'} "
            f"({a_passed}/{len(a_checks)} pass, {a_pct}%)"
        )
        for c in a_checks:
            if c.get("ok"):
                continue
            key = c.get("key", "?")
            missing = c.get("missing") or []
            hint = c.get("fix_hint") or ""
            line = f"  [MISS] {key}"
            if missing:
                line += f"  missing: {', '.join(missing)}"
            print(line)
            if hint:
                print(f"        fix: {hint}")
    elif audit_after is not None and audit_after.get("error"):
        print()
        print(
            f"Launch-audit follow-up: unavailable "
            f"({audit_after.get('message') or audit_after.get('error')})"
        )

    if strict and not ready:
        sys.exit(1)


def _cmd_launch_audit(args) -> None:
    """Read-only launch-readiness audit.

    Walks the 8 launchability checks (legal_policies,
    standard_pages, active_discounts, curated_collections,
    design_tokens, active_products, shipping_zones,
    fulfillable_locations) and reports per-check pass/fail
    plus an operator-actionable ``fix_hint`` on each gap.

    Exits 0 by default (informational; safe alongside the
    daily cron). Pass ``--strict`` to exit 1 when
    ready_to_launch is False so CI can gate on it.
    """
    as_json = bool(getattr(args, "json", False))
    strict = bool(getattr(args, "strict", False))
    sm = _get_store_manager()
    store_id = (
        getattr(args, "store", None) or sm.active_store_id
    )

    try:
        from engines.store_setup.launch_audit import audit_store
    except Exception as exc:  # noqa: BLE001
        logger.debug("launch_audit import failed: %s", exc)
        if as_json:
            print(json.dumps({
                "ok": None,
                "error": "launch_audit_unavailable",
                "message": str(exc),
            }, indent=2))
        else:
            print(f"launch-audit unavailable: {exc}")
        return

    try:
        result = audit_store(
            store_id=store_id,
            expected_products=int(
                getattr(args, "expected_products", 1) or 1
            ),
            expected_collections=int(
                getattr(args, "expected_collections", 1) or 1
            ),
            expected_discounts=int(
                getattr(args, "expected_discounts", 1) or 1
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("launch_audit raised: %s", exc)
        if as_json:
            print(json.dumps({
                "ok": None,
                "error": "launch_audit_failed",
                "message": str(exc),
            }, indent=2))
        else:
            print(f"launch-audit failed: {exc}")
        return

    if as_json:
        print(json.dumps(result, indent=2))
        if strict and not result.get("ready_to_launch"):
            sys.exit(1)
        return

    # ── Text view ───────────────────────────────────────────
    checks = result.get("checks") or []
    pct = result.get("completion_pct", 0)
    ready = result.get("ready_to_launch", False)
    passed = sum(1 for c in checks if c.get("ok"))
    header_status = "READY" if ready else "NOT READY"
    print(
        f"Launch-readiness audit -- {header_status} "
        f"({passed}/{len(checks)} checks pass, {pct}% complete)"
    )
    print()
    for check in checks:
        key = check.get("key", "?")
        ok = check.get("ok", False)
        applied = check.get("applied", 0)
        expected = check.get("expected", 0)
        mark = "OK " if ok else "MISS"
        print(f"  [{mark}] {key:<24} {applied}/{expected}")
        if not ok:
            missing = check.get("missing") or []
            if missing:
                print(f"        missing: {', '.join(missing)}")
            hint = check.get("fix_hint") or ""
            if hint:
                print(f"        fix: {hint}")
    print()
    if ready:
        print("All checks pass -- store is launchable.")
    else:
        print(
            f"Missing: {result.get('missing_summary', '')}"
        )
        next_action = _suggest_next_audit_action(checks)
        if next_action:
            print()
            print(f"Next action: {next_action}")
    if strict and not ready:
        sys.exit(1)


def _suggest_next_audit_action(
    checks: list[dict],
) -> str:
    """Pick the highest-leverage next command from a launch
    audit result.

    Groups failing checks by which command can fix them, then
    returns the command that closes the most gaps. The four
    mandatory orchestrator steps (legal_policies,
    standard_pages, active_discounts, curated_collections)
    are all closed by a single ``shopai launch`` run, so any
    failing combination of those collapses into one
    recommendation. Manual steps (shipping_zones,
    fulfillable_locations) get separate URLs.
    """
    if not checks:
        return ""
    # Group failing checks by remediation bucket
    launch_keys = {
        "legal_policies", "standard_pages",
        "active_discounts", "curated_collections",
        "design_tokens",
    }
    manual_admin_keys = {
        "shipping_zones", "fulfillable_locations",
    }
    seeder_keys = {"active_products"}

    failing = [c for c in checks if not c.get("ok")]
    if not failing:
        return ""
    failing_keys = {c.get("key", "") for c in failing}

    launchable_gaps = failing_keys & launch_keys
    manual_gaps = failing_keys & manual_admin_keys
    seeder_gaps = failing_keys & seeder_keys

    # Pick the bucket that closes the most gaps in one shot
    if (
        len(launchable_gaps) >= len(manual_gaps)
        and len(launchable_gaps) >= len(seeder_gaps)
        and launchable_gaps
    ):
        return (
            f"shopai launch --store-name <NAME> "
            f"--niche <NICHE>  "
            f"(closes {len(launchable_gaps)} of "
            f"{len(failing)} gaps)"
        )
    if (
        len(manual_gaps) >= len(seeder_gaps)
        and manual_gaps
    ):
        urls = {
            "shipping_zones":
                "admin.shopify.com/settings/shipping",
            "fulfillable_locations":
                "admin.shopify.com/settings/locations",
        }
        target = sorted(manual_gaps)[0]
        return (
            f"Visit {urls.get(target, 'Shopify admin')} "
            f"to close {target}"
        )
    if seeder_gaps:
        return (
            "Add ACTIVE products via Shopify admin (or a "
            "niche seeder) to close active_products"
        )
    return ""


def _cmd_post_launch(args) -> None:
    """Post-launch polish: run SEO + description enrichment
    over the store's products in one shot.

    Companion to ``shopai launch`` (the create-stuff flow).
    After launch the operator typically adds products; this
    command then walks every product and:
      1. Generates SEO title + meta_description.
      2. Generates body_html for products without one (or
         with a placeholder shorter than ``--min-description-
         length``).
      3. With ``--apply``, writes both via SHOPIFY_UPDATE_PRODUCT.

    Mirrors the safety pattern of the underlying CLIs
    (#471 enrich-seo, #472 enrich-descriptions): default is
    read-only preview; ``--apply`` opts in to writes.

    Exits 0 on preview / clean apply; exits 1 when ``--apply``
    is set AND at least one write failed. Probe failures
    (router down, no products) exit 0 with a friendly
    message.
    """
    as_json = bool(getattr(args, "json", False))
    apply_writes = bool(getattr(args, "apply", False))
    sm = _get_store_manager()
    store_id = (
        getattr(args, "store", None) or sm.active_store_id
    )

    # ── Fetch products via the router ────────────────────
    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
        router = get_router()
        list_result = router.execute(
            Capability.SHOPIFY_LIST_PRODUCTS,
            {"limit": int(getattr(args, "limit", 100) or 100)},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("post-launch router fetch raised: %s", exc)
        if as_json:
            print(json.dumps({
                "ok": None,
                "error": "products_fetch_unavailable",
                "message": str(exc),
            }, indent=2))
        else:
            print(f"Product fetch unavailable: {exc}")
        return

    if not getattr(list_result, "ok", False):
        err = getattr(list_result, "error", "unknown")
        if as_json:
            print(json.dumps({
                "ok": None,
                "error": "products_fetch_failed",
                "message": str(err),
            }, indent=2))
        else:
            print(f"Product fetch failed: {err}")
        return

    data = getattr(list_result, "data", None) or {}
    products = (
        data.get("products") if isinstance(data, dict) else []
    )
    if not isinstance(products, list):
        products = []

    if not products:
        if as_json:
            print(json.dumps({
                "ok": True,
                "applied": apply_writes,
                "products_total": 0,
                "seo": {"generated_count": 0, "skipped_count": 0},
                "descriptions": {
                    "generated_count": 0, "skipped_count": 0,
                },
            }, indent=2))
        else:
            print(
                "post-launch: no products to enrich -- add "
                "products via Shopify admin or `shopai store "
                "add-product` first."
            )
        return

    niche = getattr(args, "niche", "general")

    # ── Step 1: SEO enrichment ────────────────────────────
    try:
        from engines.store_setup.seo_meta_enricher import (
            enrich_seo,
        )
        seo_gen = enrich_seo(
            products,
            niche=niche,
            store_name=(getattr(args, "store_name", "") or ""),
            overwrite_existing=bool(
                getattr(args, "overwrite_seo", False),
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("enrich_seo raised: %s", exc)
        seo_gen = {"generated": [], "skipped": []}

    # ── Step 2: Description enrichment ────────────────────
    try:
        from engines.store_setup.product_description_enricher import (
            enrich_products,
        )
        desc_gen = enrich_products(
            products,
            niche=niche,
            min_existing_length=int(
                getattr(args, "min_description_length", 80)
                or 80,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("enrich_products raised: %s", exc)
        desc_gen = {"generated": [], "skipped": []}

    seo_generated = seo_gen.get("generated") or []
    seo_skipped = seo_gen.get("skipped") or []
    desc_generated = desc_gen.get("generated") or []
    desc_skipped = desc_gen.get("skipped") or []

    # ── Preview-only path ─────────────────────────────────
    if not apply_writes:
        if as_json:
            print(json.dumps({
                "ok": True,
                "applied": False,
                "products_total": len(products),
                "seo": {
                    "generated_count": len(seo_generated),
                    "skipped_count": len(seo_skipped),
                    "generated": seo_generated,
                },
                "descriptions": {
                    "generated_count": len(desc_generated),
                    "skipped_count": len(desc_skipped),
                    "generated": desc_generated,
                },
            }, indent=2))
            return
        print(
            f"post-launch PREVIEW -- {len(products)} product(s) "
            "scanned."
        )
        print(
            f"  SEO:          {len(seo_generated)} updates, "
            f"{len(seo_skipped)} skipped"
        )
        print(
            f"  Descriptions: {len(desc_generated)} updates, "
            f"{len(desc_skipped)} skipped"
        )
        print()
        print("Re-run with --apply to write to Shopify.")
        return

    # ── Apply path ────────────────────────────────────────
    seo_applied = 0
    seo_failures: list[dict] = []
    desc_applied = 0
    desc_failures: list[dict] = []

    try:
        from engines.store_setup.seo_meta_enricher import apply_seo
        seo_apply = apply_seo(
            seo_generated, store_id=store_id,
        )
        seo_applied = int(seo_apply.get("applied_count", 0))
        seo_failures = [
            r for r in (seo_apply.get("results") or [])
            if not r.get("ok")
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("apply_seo raised: %s", exc)
        seo_failures = [{
            "product_id": "?", "error": f"apply_raised: {exc}",
        }]

    try:
        from engines.store_setup.product_description_enricher import (
            apply_descriptions,
        )
        desc_apply = apply_descriptions(
            desc_generated, store_id=store_id,
        )
        desc_applied = int(desc_apply.get("applied_count", 0))
        desc_failures = [
            r for r in (desc_apply.get("results") or [])
            if not r.get("ok")
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("apply_descriptions raised: %s", exc)
        desc_failures = [{
            "product_id": "?", "error": f"apply_raised: {exc}",
        }]

    total_failures = len(seo_failures) + len(desc_failures)

    if as_json:
        print(json.dumps({
            "ok": total_failures == 0,
            "applied": True,
            "products_total": len(products),
            "seo": {
                "applied_count": seo_applied,
                "failure_count": len(seo_failures),
            },
            "descriptions": {
                "applied_count": desc_applied,
                "failure_count": len(desc_failures),
            },
        }, indent=2))
        if total_failures:
            sys.exit(1)
        return

    if total_failures == 0:
        print(
            f"post-launch APPLIED -- "
            f"{seo_applied} SEO updates + "
            f"{desc_applied} description updates "
            f"across {len(products)} product(s)."
        )
        return

    print(
        f"post-launch PARTIAL -- "
        f"{seo_applied + desc_applied} applied, "
        f"{total_failures} failed:"
    )
    if seo_failures:
        print(f"  SEO failures ({len(seo_failures)}):")
        for f in seo_failures[:3]:
            print(
                f"    {f.get('product_id', '?')}: "
                f"{f.get('error', 'unknown')}"
            )
        if len(seo_failures) > 3:
            print(f"    ... +{len(seo_failures) - 3} more")
    if desc_failures:
        print(f"  Description failures ({len(desc_failures)}):")
        for f in desc_failures[:3]:
            print(
                f"    {f.get('product_id', '?')}: "
                f"{f.get('error', 'unknown')}"
            )
        if len(desc_failures) > 3:
            print(f"    ... +{len(desc_failures) - 3} more")
    sys.exit(1)


def _cmd_shopify_scopes_live_check(args) -> None:
    """Compare the registry's declared scopes against the live
    app installation's granted scopes.

    Closes the runtime gap left by the registry + CI gate +
    install manifest: those tell us what we WANT, but the
    merchant's actual app install might have a different set.
    The first symptom of a stale install is adapters failing
    with ACCESS_DENIED — a slow debug path. This check
    surfaces it directly.

    Exits 1 when ``missing_from_app`` is non-empty (adapters
    WILL fail at runtime). Exits 0 with a warning when only
    ``extra_in_app`` is non-empty (over-requesting — Shopify
    review may flag, but functionality works).

    Returns 0 with a friendly "no live data" when the apps
    adapter isn't configured — local dev sees the message
    rather than an opaque crash.
    """
    try:
        from core.adapters.shopify.scope_health import compare_to_live
        report = compare_to_live()
    except Exception as exc:  # noqa: BLE001
        logger.debug("scope health check raised: %s", exc)
        report = None

    if report is None:
        if getattr(args, "json", False):
            print(json.dumps({
                "ok": None,
                "error": "live_data_unavailable",
                "message": (
                    "apps adapter not configured or live API "
                    "call failed; cannot compare scopes"
                ),
            }, indent=2))
        else:
            print(
                "Live scope check unavailable — the Shopify "
                "apps adapter is not configured (or the live "
                "call failed). Configure SHOPAI_SHOPIFY_URL + "
                "SHOPAI_SHOPIFY_KEY and re-run."
            )
        return

    if getattr(args, "json", False):
        print(json.dumps({
            "ok": report.is_healthy,
            "granted_scope_count": len(report.granted_scopes),
            "required_scope_count": len(report.required_scopes),
            "missing_from_app": report.missing_from_app,
            "extra_in_app": report.extra_in_app,
        }, indent=2))
        if report.missing_from_app:
            sys.exit(1)
        return

    if report.is_healthy and not report.extra_in_app:
        print(
            f"Live scope check OK — all "
            f"{len(report.required_scopes)} required scopes "
            "are granted on the live app installation."
        )
        return

    if report.missing_from_app:
        print(
            f"Live scope check FAILED: "
            f"{len(report.missing_from_app)} scope(s) declared "
            "but NOT granted on the live install. Adapters "
            "calling these surfaces WILL fail with ACCESS_DENIED."
        )
        print()
        print("Missing scopes:")
        for s in report.missing_from_app:
            print(f"  {s}")
        if report.extra_in_app:
            print()
            print(
                f"Also: {len(report.extra_in_app)} extra scope(s) "
                "granted that the registry doesn't declare."
            )
            for s in report.extra_in_app:
                print(f"  {s}")
        print()
        print(
            "Fix: regenerate the install manifest with "
            "`shopai shopify-install-manifest` and re-install "
            "the app on the merchant store."
        )
        sys.exit(1)

    # is_healthy True + extras exist → warning, not fatal
    print(
        f"Live scope check OK with warnings — all "
        f"{len(report.required_scopes)} required scopes are "
        f"granted, but {len(report.extra_in_app)} extra scope(s) "
        "are present that the registry doesn't declare."
    )
    print()
    print("Over-requested scopes:")
    for s in report.extra_in_app:
        print(f"  {s}")
    print()
    print(
        "Fix (optional but recommended): regenerate the install "
        "manifest with `shopai shopify-install-manifest` and "
        "re-submit so Shopify's app reviewers don't flag "
        "over-requesting."
    )


def _cmd_shopify_webhooks_live_check(args) -> None:
    """Compare the webhook registry's declared topics against
    the live app installation's registered subscriptions.

    Mirrors ``shopify-scopes-live-check`` (PR #179) for the
    webhook surface. The registry tells us what topics the
    app SHOULD subscribe to; this checks what it ACTUALLY does
    on Shopify's side. Drift surfaces:

      - ``missing_on_app``: declared but not registered. Bridge
        never receives these events; outcome attribution stalls.
      - ``extra_on_app``: registered but not declared. App
        receives events it doesn't handle (legacy install
        residue).
      - ``gdpr_missing``: GDPR-mandatory topics not registered
        — review-blocking failure for public-distribution apps.

    Exits 1 when ``missing_on_app`` is non-empty (operational
    alert). Exits 0 with a warning for extras only. Exits 0
    with a friendly message when the webhooks adapter isn't
    configured (dev environments without live creds).
    """
    try:
        from core.feedback.webhook_health import compare_to_live
        report = compare_to_live()
    except Exception as exc:  # noqa: BLE001
        logger.debug("webhook health check raised: %s", exc)
        report = None

    if report is None:
        if getattr(args, "json", False):
            print(json.dumps({
                "ok": None,
                "error": "live_data_unavailable",
                "message": (
                    "webhooks adapter not configured or live API "
                    "call failed; cannot compare subscriptions"
                ),
            }, indent=2))
        else:
            print(
                "Live webhook check unavailable — the Shopify "
                "webhooks adapter is not configured (or the "
                "live call failed). Configure "
                "SHOPAI_SHOPIFY_URL + SHOPAI_SHOPIFY_KEY and "
                "re-run."
            )
        return

    if getattr(args, "json", False):
        print(json.dumps({
            "ok": report.is_healthy,
            "registered_count": len(report.registered_topics),
            "declared_count": len(report.declared_topics),
            "missing_on_app": report.missing_on_app,
            "extra_on_app": report.extra_on_app,
            "gdpr_missing": report.gdpr_missing,
        }, indent=2))
        if report.missing_on_app:
            sys.exit(1)
        return

    if report.is_healthy and not report.extra_on_app:
        print(
            f"Live webhook check OK — all "
            f"{len(report.declared_topics)} declared topics "
            "are registered on the live app installation."
        )
        return

    if report.missing_on_app:
        print(
            f"Live webhook check FAILED: "
            f"{len(report.missing_on_app)} topic(s) declared "
            "but NOT registered on the live install. Outcome "
            "attribution will silently miss these events."
        )
        if report.gdpr_missing:
            print()
            print(
                f"GDPR ALERT: {len(report.gdpr_missing)} "
                "mandatory topic(s) NOT registered. Shopify "
                "will reject the install for public-distribution "
                "apps."
            )
            for s in report.gdpr_missing:
                print(f"  {s}")
        print()
        print("Missing topics:")
        for s in report.missing_on_app:
            tag = (
                " [GDPR-mandatory]"
                if s in report.gdpr_missing else ""
            )
            print(f"  {s}{tag}")
        if report.extra_on_app:
            print()
            print(
                f"Also: {len(report.extra_on_app)} extra "
                "subscription(s) registered that the registry "
                "doesn't declare."
            )
            for s in report.extra_on_app:
                print(f"  {s}")
        print()
        print(
            "Fix: regenerate the webhook manifest with "
            "`shopai shopify-webhook-manifest` and re-deploy "
            "the app's subscription config to Shopify."
        )
        sys.exit(1)

    # is_healthy True + extras exist → warning, not fatal
    print(
        f"Live webhook check OK with warnings — all "
        f"{len(report.declared_topics)} declared topics are "
        f"registered, but {len(report.extra_on_app)} extra "
        "subscription(s) are present that the registry doesn't "
        "declare."
    )
    print()
    print("Extra (un-declared) topics:")
    for s in report.extra_on_app:
        print(f"  {s}")
    print()
    print(
        "Fix (optional): if these are legacy subscriptions, "
        "remove them via the Shopify Partners dashboard or "
        "by re-applying a clean webhook manifest."
    )


def _cmd_capabilities_audit(args) -> None:
    """CI gate (Pattern Y): exit 1 if any ``Capability.SHOPIFY_*``
    enum value is unclaimed by every adapter.

    The companion to ``shopai approvals audit`` (Pattern K) and
    ``shopai shopify-scopes-audit``. Each enum value declares an
    abstract capability the router can resolve to an adapter.
    When a new ``SHOPIFY_X`` lands on the enum without a matching
    adapter, engines calling for ``Capability.SHOPIFY_X`` hit
    ``AdapterNotConfigured`` — silent at the system level, loud
    at the single engine. This audit makes that an explicit gate.

    Two failure modes caught:

      - **unclaimed**: enum has the capability, no adapter
        declares it. Engines route into a void.
      - **orphan_claims**: adapter declares a "capability" that
        isn't a real enum value (string typo, deleted enum).
        Module load would crash on the import; this gate would
        flag it before tests run.

    Exit 0 = clean. Exit 1 = at least one gap. ``--show-multi-
    claimed`` adds a warning section for capabilities claimed
    by 2+ adapters (legitimate in some cases — read vs write
    splits — but worth surfacing).
    """
    try:
        from core.adapters.coverage_audit import audit_capability_coverage
        report = audit_capability_coverage()
    except Exception as exc:  # noqa: BLE001
        logger.debug("capability coverage audit raised: %s", exc)
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"Capability audit unavailable: {exc}")
        return

    if getattr(args, "json", False):
        payload = {
            "ok": not report.has_gaps,
            "total_shopify_capabilities": (
                report.total_shopify_capabilities
            ),
            "claimed_count": report.claimed_count,
            "unclaimed": report.unclaimed,
            "orphan_claims": report.orphan_claims,
        }
        if getattr(args, "show_multi_claimed", False):
            payload["multi_claimed"] = report.multi_claimed
        print(json.dumps(payload, indent=2))
        if report.has_gaps:
            sys.exit(1)
        return

    if not report.has_gaps:
        print(
            f"Capability coverage OK — "
            f"{report.claimed_count}/"
            f"{report.total_shopify_capabilities} "
            "Shopify capabilities claimed by 1+ adapter."
        )
        if getattr(args, "show_multi_claimed", False):
            if report.multi_claimed:
                print()
                print(
                    f"Multi-claimed ({len(report.multi_claimed)}) — "
                    "usually legitimate, sometimes routing "
                    "ambiguity:"
                )
                for cap, adapters in sorted(
                    report.multi_claimed.items(),
                ):
                    print(f"  {cap}: {', '.join(adapters)}")
            else:
                print()
                print("No multi-claimed capabilities.")
        return

    print(
        f"Capability coverage FAILED: "
        f"{len(report.unclaimed)} unclaimed, "
        f"{len(report.orphan_claims)} orphan claim(s)."
    )
    print()
    if report.unclaimed:
        print(
            "Unclaimed capabilities (engines routing to these "
            "will hit AdapterNotConfigured):"
        )
        for cap in report.unclaimed:
            print(f"  {cap}")
        print()
    if report.orphan_claims:
        print(
            "Orphan claims (adapter declares a capability that "
            "doesn't exist on the enum):"
        )
        for cap in report.orphan_claims:
            print(f"  {cap}")
        print()
    print(
        "Fix: add the missing capabilities to the adapter's "
        "`capabilities` set in core/adapters/shopify/, OR drop "
        "the enum value if it's no longer needed."
    )
    sys.exit(1)


def _cmd_engines_capability_audit(args) -> None:
    """CI gate (Pattern I): every ``capability_name=...`` string
    literal in ``engines/**/*.py`` must reference a real Capability
    enum member claimed by 1+ adapter.

    Catches the exact failure class documented in CLAUDE.md Pattern
    I and fixed in PR #40: engine hydrators using a capability name
    that's silently unroutable. Mocked unit tests never catch this
    because they patch the router; only live production traffic
    hits the real registry. This audit makes it an explicit gate.

    Two failure modes:

      - **unknown_enum_member**: engine passes ``capability_name=
        "SHOPIFY_FETCH_ORDRES"`` — typo. The router would raise
        ``AttributeError`` on first call.
      - **unclaimed_by_adapter**: name exists on the enum but no
        adapter claims it. Hydrator returns ``[]``, engine falls
        through to its "X list is required" guard.

    Exit 0 = clean. Exit 1 = at least one ref is broken.
    """
    try:
        from engines._engine_capability_audit import (
            audit_engine_capabilities,
            format_refs,
        )
        report = audit_engine_capabilities()
    except Exception as exc:  # noqa: BLE001
        logger.debug("engine capability audit raised: %s", exc)
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"Engine capability audit unavailable: {exc}")
        return

    if getattr(args, "json", False):
        payload = {
            "ok": not report.has_gaps,
            "total_refs": report.total_refs,
            "distinct_capabilities": report.distinct_capabilities,
            "unknown_enum_member": [
                {
                    "engine": r.engine,
                    "file": r.file,
                    "lineno": r.lineno,
                    "capability_name": r.capability_name,
                }
                for r in report.unknown_enum_member
            ],
            "unclaimed_by_adapter": [
                {
                    "engine": r.engine,
                    "file": r.file,
                    "lineno": r.lineno,
                    "capability_name": r.capability_name,
                }
                for r in report.unclaimed_by_adapter
            ],
        }
        print(json.dumps(payload, indent=2))
        if report.has_gaps:
            sys.exit(1)
        return

    if not report.has_gaps:
        print(
            f"Engine capability parity OK -- "
            f"{report.total_refs} `capability_name=` refs across "
            f"{report.distinct_capabilities} distinct capabilities; "
            "every name resolves to an adapter-claimed enum value."
        )
        return

    print(
        f"Engine capability parity FAILED: "
        f"{len(report.unknown_enum_member)} unknown, "
        f"{len(report.unclaimed_by_adapter)} unclaimed."
    )
    print()
    if report.unknown_enum_member:
        print(
            "Unknown enum members (typos -- engine references a "
            "capability name that doesn't exist on Capability):"
        )
        print(format_refs(report.unknown_enum_member))
        print()
    if report.unclaimed_by_adapter:
        print(
            "Unclaimed by adapter (enum value exists but no "
            "Shopify adapter claims it):"
        )
        print(format_refs(report.unclaimed_by_adapter))
        print()
    print(
        "Fix: either correct the engine's `capability_name=` "
        "string, OR add an adapter under core/adapters/shopify/ "
        "claiming the capability."
    )
    sys.exit(1)


def _cmd_pattern_j_audit(args) -> None:
    """CI gate (Pattern J): every write to
    MemoryIntelligence / DataArchitecture / LearningLoop
    singletons must come from the canonical Phase 8 recorder
    (``engines/_writeback_recorder.py``) -- which gates on
    ``PYTEST_CURRENT_TEST`` -- or be in a module that defines its
    own ``_is_test_environment`` guard.

    Catches the bug class documented in CLAUDE.md Pattern J:
    test code that exercises an unguarded path silently pollutes
    the on-disk SQLite stores; the failure-intelligence pipeline
    then generates avoidance rules from test fixtures.

    Exit 0 = clean. Exit 1 = at least one unguarded write-site.
    """
    try:
        from engines._pattern_j_audit import audit_pattern_j
        report = audit_pattern_j()
    except Exception as exc:  # noqa: BLE001
        logger.debug("pattern J audit raised: %s", exc)
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"Pattern J audit unavailable: {exc}")
        return

    if getattr(args, "json", False):
        payload = {
            "ok": not report.has_violations,
            "scanned_modules": report.scanned_modules,
            "recorder_sites": [
                {
                    "file": s.file,
                    "lineno": s.lineno,
                    "method": s.method,
                    "receiver": s.receiver_expr,
                }
                for s in report.recorder_sites
            ],
            "guarded_sites": [
                {
                    "file": s.file,
                    "lineno": s.lineno,
                    "method": s.method,
                    "receiver": s.receiver_expr,
                }
                for s in report.guarded_sites
            ],
            "unguarded_sites": [
                {
                    "file": s.file,
                    "lineno": s.lineno,
                    "method": s.method,
                    "receiver": s.receiver_expr,
                }
                for s in report.unguarded_sites
            ],
        }
        print(json.dumps(payload, indent=2))
        if report.has_violations:
            sys.exit(1)
        return

    if not report.has_violations:
        print(
            f"Pattern J OK -- "
            f"{len(report.recorder_sites)} recorder site(s), "
            f"{len(report.guarded_sites)} guarded site(s); "
            f"no unguarded writes across "
            f"{report.scanned_modules} scanned modules."
        )
        return

    print(
        f"Pattern J FAILED: "
        f"{len(report.unguarded_sites)} unguarded write-site(s) "
        "to learning singletons."
    )
    print()
    print(
        "Unguarded sites (each could pollute the on-disk "
        "SQLite stores when a test exercises the path):"
    )
    for s in report.unguarded_sites:
        print(
            f"  {s.file}:{s.lineno}  "
            f"{s.receiver_expr}.{s.method}()"
        )
    print()
    print(
        "Fix: either delegate the write through "
        "`engines._writeback_recorder.record_writeback()` (the "
        "canonical Phase 8 bridge), OR add an "
        "`_is_test_environment()` guard to the calling module."
    )
    sys.exit(1)


def _cmd_pattern_z_audit(args) -> None:
    """CI gate (Pattern Z): every writer module that calls a
    Shopify mutation MUST also call ``record_writeback`` so the
    autonomous learning loop sees the outcome.

    Catches the bug class fixed in PR #205: four discount-code
    minters were minting real Shopify codes but skipping
    ``record_writeback``. The minted codes were live on Shopify,
    but Phase 8 (MemoryIntelligence / DataArchitecture /
    LearningLoop) never saw the mint event -- recommender + EMA
    silently undercounted those engines' impact.

    Writer modules in scope (filename suffix):
      * ``*_applier.py``
      * ``*_minter.py``
      * ``*_payer.py``

    A writer is flagged when it calls one of (``execute``,
    ``_router_call``, ``mint_recovery_code``, ``_mint``) but
    has NO ``record_writeback`` call in the same file. Writers
    that only enqueue (no direct mutation) skip cleanly --
    Phase 8 fan-out for the queue path is the executor's
    responsibility, not the applier's.

    Exit 0 = clean. Exit 1 = at least one writer skips
    record_writeback.
    """
    try:
        from engines._pattern_z_audit import audit_pattern_z
        report = audit_pattern_z()
    except Exception as exc:  # noqa: BLE001
        logger.debug("pattern Z audit raised: %s", exc)
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"Pattern Z audit unavailable: {exc}")
        return

    if getattr(args, "json", False):
        payload = {
            "ok": not report.has_violations,
            "scanned_writers": report.scanned_writers,
            "clean_writers": report.clean_writers,
            "skipped_no_mutation": report.skipped_no_mutation,
            "missing_recorder": [
                {
                    "file": s.file,
                    "mutation_calls": list(s.mutation_calls),
                    "has_recorder_import": s.has_recorder_import,
                }
                for s in report.missing_recorder
            ],
        }
        print(json.dumps(payload, indent=2))
        if report.has_violations:
            sys.exit(1)
        return

    if not report.has_violations:
        print(
            f"Pattern Z OK -- "
            f"{len(report.clean_writers)}/{report.scanned_writers} "
            "writer module(s) call record_writeback "
            f"({len(report.skipped_no_mutation)} skipped: no "
            "direct mutation)."
        )
        return

    print(
        f"Pattern Z FAILED: "
        f"{len(report.missing_recorder)} writer(s) call a Shopify "
        "mutation but skip record_writeback."
    )
    print()
    print(
        "Phase 8 (MemoryIntelligence / DataArchitecture / "
        "LearningLoop) won't see these writes -- the autonomous "
        "loop can't learn from them:"
    )
    for s in report.missing_recorder:
        hint = (
            " (recorder imported but not called)"
            if s.has_recorder_import else ""
        )
        print(
            f"  {s.file}  mutations={list(s.mutation_calls)}"
            f"{hint}"
        )
    print()
    print(
        "Fix: add `from engines._writeback_recorder import "
        "record_writeback` and call it adjacent to the mutation, "
        "passing engine + action_type + capability + params + "
        "success + error. See engines/loyalty/discount_minter.py "
        "for the canonical pattern."
    )
    sys.exit(1)


def _cmd_pattern_q_audit(args) -> None:
    """CI gate (Pattern Q): every registered engine's ``run()``
    must return the canonical ``{status, data, meta, error}``
    envelope.

    Catches a regression class the existing audits don't:
    a refactor drops one of the four envelope keys, downstream
    consumers (approval queue narrative, Phase 8 recorder,
    recommender) assume the missing key and silently break.

    The audit RUNS each engine with empty input -- it's a
    runtime check, not an AST walk, because engines compute
    their envelope dict dynamically. Engines that need real
    data return ``status="error"`` cleanly; they still emit
    the four-key envelope.

    Exit 0 = clean. Exit 1 = at least one engine violates.
    """
    try:
        from engines._output_schema_audit import (
            audit_engine_output_schema,
        )
        report = audit_engine_output_schema()
    except Exception as exc:  # noqa: BLE001
        logger.debug("pattern Q audit raised: %s", exc)
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"Pattern Q audit unavailable: {exc}")
        return

    if getattr(args, "json", False):
        payload = {
            "ok": not report.has_violations,
            "scanned_engines": report.scanned_engines,
            "clean_engines": report.clean_engines,
            "skipped_engines": report.skipped_engines,
            "violations": [
                {
                    "engine": v.engine,
                    "reason": v.reason,
                    "detail": v.detail,
                }
                for v in report.violations
            ],
        }
        print(json.dumps(payload, indent=2))
        if report.has_violations:
            sys.exit(1)
        return

    if not report.has_violations:
        print(
            f"Pattern Q OK -- "
            f"{len(report.clean_engines)}/{report.scanned_engines} "
            "engines return the canonical "
            "{status, data, meta, error} envelope"
            + (
                f" ({len(report.skipped_engines)} skipped: "
                "could not instantiate)"
                if report.skipped_engines else ""
            )
            + "."
        )
        return

    print(
        f"Pattern Q FAILED: "
        f"{len(report.violations)} engine(s) violate the "
        "envelope contract."
    )
    print()
    print("Each engine's run() must return a dict with keys "
          "{status, data, meta, error}, with status in "
          "{success, error, fail}.")
    print()
    for v in report.violations:
        print(f"  {v.engine}  [{v.reason}]  {v.detail}")
    print()
    print(
        "Fix: ensure the engine's run() returns the canonical "
        "envelope on every code path (including error paths). "
        "Look at engines/loyalty/flow.py for the standard "
        "pattern (status='success'/'error'/'fail', data=dict, "
        "meta=dict with engine name + timestamp, "
        "error=str | None)."
    )
    sys.exit(1)


def _run_one_audit(name: str) -> dict[str, Any]:
    """Run a single named audit and return ``{ok, details}``.

    Each branch matches the existing per-audit module's interface.
    Catches all module-level exceptions and surfaces them as
    ``{ok: False, error: ...}`` so a single broken audit doesn't
    block the others.
    """
    try:
        if name == "pattern_k":
            from core.approval.coverage_audit import audit_coverage
            from pathlib import Path
            r = audit_coverage(Path("engines"))
            return {
                "ok": not r.has_gaps,
                "enqueue_sites": len(r.enqueued),
                "dispatchers_registered": len(r.registered),
                "missing": sorted(r.missing),
                "orphaned": sorted(r.orphaned),
            }
        if name == "oauth":
            from core.adapters.shopify.scope_registry import collect_manifest
            m = collect_manifest()
            return {
                "ok": not m.undeclared_adapters,
                "total_adapters": m.total_adapters,
                "declared_count": (
                    m.total_adapters - len(m.undeclared_adapters)
                ),
                "scope_independent_count": (
                    len(m.scope_independent_adapters)
                ),
                "undeclared_adapters": m.undeclared_adapters,
                "unique_scopes": len(m.all_scopes),
            }
        if name == "pattern_y":
            from core.adapters.coverage_audit import (
                audit_capability_coverage,
            )
            c = audit_capability_coverage()
            return {
                "ok": not c.has_gaps,
                "total_capabilities": c.total_shopify_capabilities,
                "claimed_count": c.claimed_count,
                "unclaimed": c.unclaimed,
                "orphan_claims": c.orphan_claims,
            }
        if name == "pattern_i":
            from engines._engine_capability_audit import (
                audit_engine_capabilities,
            )
            i = audit_engine_capabilities()
            return {
                "ok": not i.has_gaps,
                "total_refs": i.total_refs,
                "distinct_capabilities": i.distinct_capabilities,
                "unknown_enum_member": [
                    f"{r.capability_name} ({r.file}:{r.lineno})"
                    for r in i.unknown_enum_member
                ],
                "unclaimed_by_adapter": [
                    f"{r.capability_name} ({r.file}:{r.lineno})"
                    for r in i.unclaimed_by_adapter
                ],
            }
        if name == "pattern_j":
            from engines._pattern_j_audit import audit_pattern_j
            j = audit_pattern_j()
            return {
                "ok": not j.has_violations,
                "scanned_modules": j.scanned_modules,
                "recorder_sites": len(j.recorder_sites),
                "guarded_sites": len(j.guarded_sites),
                "unguarded_sites": [
                    f"{s.file}:{s.lineno} {s.receiver_expr}.{s.method}()"
                    for s in j.unguarded_sites
                ],
            }
        if name == "pattern_z":
            from engines._pattern_z_audit import audit_pattern_z
            z = audit_pattern_z()
            return {
                "ok": not z.has_violations,
                "scanned_writers": z.scanned_writers,
                "clean_writers": len(z.clean_writers),
                "skipped_no_mutation": len(z.skipped_no_mutation),
                "missing_recorder": [
                    f"{s.file} {list(s.mutation_calls)}"
                    for s in z.missing_recorder
                ],
            }
        if name == "pattern_q":
            from engines._output_schema_audit import (
                audit_engine_output_schema,
            )
            q = audit_engine_output_schema()
            return {
                "ok": not q.has_violations,
                "scanned_engines": q.scanned_engines,
                "clean_engines": len(q.clean_engines),
                "skipped_engines": len(q.skipped_engines),
                "violations": [
                    f"{v.engine} [{v.reason}] {v.detail}"
                    for v in q.violations
                ],
            }
    except Exception as exc:  # noqa: BLE001
        logger.debug("audit %s raised: %s", name, exc)
        return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": f"unknown audit: {name}"}


_AUDIT_ORDER = (
    "pattern_k", "oauth", "pattern_y", "pattern_i", "pattern_j",
    "pattern_z", "pattern_q",
)
_AUDIT_LABELS = {
    "pattern_k": "Pattern K (dispatcher coverage)",
    "oauth": "OAuth scope coverage",
    "pattern_y": "Pattern Y (capability coverage)",
    "pattern_i": "Pattern I (engine capability parity)",
    "pattern_j": "Pattern J (test pollution)",
    "pattern_z": "Pattern Z (writer-recorder parity)",
    "pattern_q": "Pattern Q (engine envelope parity)",
}


def _cmd_audit_all(args) -> None:
    """Run every institutional audit in one shot and surface a
    unified verdict.

    A single-pass companion to the five individual ``*-audit``
    surfaces. Operators run ``shopai audit`` as a fast pre-commit
    check; CI can replace the five separate steps with one when
    granular per-audit failure surfacing isn't required.

    ``--only NAME`` restricts to one audit; useful for fast pre-
    commit checks targeting one concern.

    Exit 0 = all selected audits pass. Exit 1 = at least one
    failed.
    """
    only = getattr(args, "only", None)
    selected = (only,) if only else _AUDIT_ORDER

    results: dict[str, dict[str, Any]] = {}
    for name in selected:
        results[name] = _run_one_audit(name)
    all_ok = all(r.get("ok", False) for r in results.values())

    if getattr(args, "json", False):
        payload = {
            "ok": all_ok,
            "audits": results,
        }
        print(json.dumps(payload, indent=2, default=str))
        if not all_ok:
            sys.exit(1)
        return

    # Text mode
    if only:
        print(f"ShopAI audit: {_AUDIT_LABELS.get(only, only)}")
    else:
        print("ShopAI audit (all institutional gates)")
    print()

    for name in selected:
        r = results[name]
        label = _AUDIT_LABELS.get(name, name)
        if r.get("ok"):
            print(f"  [pass] {label}")
        else:
            if "error" in r:
                print(f"  [??]   {label} -- {r['error']}")
            else:
                # surface a short fail-detail per audit
                if name == "pattern_k":
                    missing = r.get("missing", [])
                    print(
                        f"  [FAIL] {label} -- "
                        f"{len(missing)} missing dispatcher(s)"
                    )
                elif name == "oauth":
                    gaps = r.get("undeclared_adapters", [])
                    print(
                        f"  [FAIL] {label} -- "
                        f"{len(gaps)} undeclared adapter(s)"
                    )
                elif name == "pattern_y":
                    print(
                        f"  [FAIL] {label} -- "
                        f"{len(r.get('unclaimed', []))} unclaimed, "
                        f"{len(r.get('orphan_claims', []))} orphan(s)"
                    )
                elif name == "pattern_i":
                    print(
                        f"  [FAIL] {label} -- "
                        f"{len(r.get('unknown_enum_member', []))} unknown, "
                        f"{len(r.get('unclaimed_by_adapter', []))} unclaimed"
                    )
                elif name == "pattern_j":
                    print(
                        f"  [FAIL] {label} -- "
                        f"{len(r.get('unguarded_sites', []))} unguarded site(s)"
                    )
                elif name == "pattern_z":
                    print(
                        f"  [FAIL] {label} -- "
                        f"{len(r.get('missing_recorder', []))} writer(s) missing recorder"
                    )
                elif name == "pattern_q":
                    print(
                        f"  [FAIL] {label} -- "
                        f"{len(r.get('violations', []))} engine(s) violate envelope"
                    )
                else:
                    print(f"  [FAIL] {label}")
    print()
    if all_ok:
        if only:
            print(f"Audit OK -- {only} passes.")
        else:
            print("Audit OK -- every institutional gate passes.")
    else:
        broken = [
            _AUDIT_LABELS.get(n, n)
            for n, r in results.items()
            if not r.get("ok", False)
        ]
        print(
            f"Audit FAILED -- {len(broken)} of "
            f"{len(results)} gate(s) flagged: "
            f"{'; '.join(broken)}"
        )
        sys.exit(1)


def _collect_doctor_sections(args) -> tuple[bool, dict[str, Any]]:
    """Collect every doctor-section's status without rendering.

    Extracted so the section-collection logic is reusable across
    ``_cmd_shopify_doctor`` (which renders text/json) and
    ``_cmd_shopify_prepare_deploy`` (which uses the
    ``overall_ok`` to gate the file write).

    Returns ``(overall_ok, sections_dict)``. ``overall_ok`` is
    True iff every fatal check passes; informational sections
    (engines_writebacks) never flip it to False.
    """
    sections: dict[str, Any] = {}
    overall_ok = True

    # ── Pattern K dispatcher coverage ────────────────────────
    try:
        from core.approval.coverage_audit import audit_coverage
        from pathlib import Path
        report = audit_coverage(Path("engines"))
        sections["pattern_k_dispatchers"] = {
            "status": "pass" if not report.has_gaps else "fail",
            "enqueue_sites": len(report.enqueued),
            "dispatchers_registered": len(report.registered),
            "missing": sorted(report.missing),
            "orphaned": sorted(report.orphaned),
        }
        if report.has_gaps:
            overall_ok = False
    except Exception as exc:  # noqa: BLE001
        logger.debug("pattern K probe raised: %s", exc)
        sections["pattern_k_dispatchers"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    # ── OAuth scope coverage ─────────────────────────────────
    try:
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest()
        gaps = manifest.undeclared_adapters
        sections["oauth_scope_coverage"] = {
            "status": "pass" if not gaps else "fail",
            "total_adapters": manifest.total_adapters,
            "declared_count": (
                manifest.total_adapters - len(gaps)
            ),
            "scope_independent_count": (
                len(manifest.scope_independent_adapters)
            ),
            "unique_scopes": len(manifest.all_scopes),
            "undeclared_adapters": gaps,
        }
        if gaps:
            overall_ok = False
    except Exception as exc:  # noqa: BLE001
        logger.debug("oauth scope probe raised: %s", exc)
        sections["oauth_scope_coverage"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    # ── Pattern Y capability coverage ────────────────────────
    try:
        from core.adapters.coverage_audit import (
            audit_capability_coverage,
        )
        cap_report = audit_capability_coverage()
        sections["pattern_y_capabilities"] = {
            "status": "pass" if not cap_report.has_gaps else "fail",
            "total_shopify_capabilities": (
                cap_report.total_shopify_capabilities
            ),
            "claimed_count": cap_report.claimed_count,
            "unclaimed": cap_report.unclaimed,
            "orphan_claims": cap_report.orphan_claims,
        }
        if cap_report.has_gaps:
            overall_ok = False
    except Exception as exc:  # noqa: BLE001
        logger.debug("pattern Y probe raised: %s", exc)
        sections["pattern_y_capabilities"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    # ── Pattern I engine capability parity ───────────────────
    try:
        from engines._engine_capability_audit import (
            audit_engine_capabilities,
        )
        eng_report = audit_engine_capabilities()
        sections["pattern_i_engine_capabilities"] = {
            "status": (
                "pass" if not eng_report.has_gaps else "fail"
            ),
            "total_refs": eng_report.total_refs,
            "distinct_capabilities": eng_report.distinct_capabilities,
            "unknown_enum_member": [
                f"{r.capability_name} ({r.file}:{r.lineno})"
                for r in eng_report.unknown_enum_member
            ],
            "unclaimed_by_adapter": [
                f"{r.capability_name} ({r.file}:{r.lineno})"
                for r in eng_report.unclaimed_by_adapter
            ],
        }
        if eng_report.has_gaps:
            overall_ok = False
    except Exception as exc:  # noqa: BLE001
        logger.debug("pattern I probe raised: %s", exc)
        sections["pattern_i_engine_capabilities"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    # ── Pattern J test pollution ─────────────────────────────
    try:
        from engines._pattern_j_audit import audit_pattern_j
        j_report = audit_pattern_j()
        sections["pattern_j_test_pollution"] = {
            "status": (
                "pass" if not j_report.has_violations else "fail"
            ),
            "scanned_modules": j_report.scanned_modules,
            "recorder_sites": len(j_report.recorder_sites),
            "guarded_sites": len(j_report.guarded_sites),
            "unguarded_sites": [
                f"{s.file}:{s.lineno} {s.receiver_expr}.{s.method}()"
                for s in j_report.unguarded_sites
            ],
        }
        if j_report.has_violations:
            overall_ok = False
    except Exception as exc:  # noqa: BLE001
        logger.debug("pattern J probe raised: %s", exc)
        sections["pattern_j_test_pollution"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    # ── Pattern Z writer-recorder parity ────────────────────
    try:
        from engines._pattern_z_audit import audit_pattern_z
        z_report = audit_pattern_z()
        sections["pattern_z_writer_recorder"] = {
            "status": (
                "pass" if not z_report.has_violations else "fail"
            ),
            "scanned_writers": z_report.scanned_writers,
            "clean_writers": len(z_report.clean_writers),
            "skipped_no_mutation": len(z_report.skipped_no_mutation),
            "missing_recorder": [
                f"{s.file} {list(s.mutation_calls)}"
                for s in z_report.missing_recorder
            ],
        }
        if z_report.has_violations:
            overall_ok = False
    except Exception as exc:  # noqa: BLE001
        logger.debug("pattern Z probe raised: %s", exc)
        sections["pattern_z_writer_recorder"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    # ── Live scope drift ─────────────────────────────────────
    if getattr(args, "skip_live", False):
        sections["live_scope_drift"] = {
            "status": "skipped",
            "reason": "--skip-live flag set",
        }
    else:
        try:
            from core.adapters.shopify.scope_health import compare_to_live
            health_report = compare_to_live()
            if health_report is None:
                sections["live_scope_drift"] = {
                    "status": "skipped",
                    "reason": (
                        "apps adapter not configured or live "
                        "API call failed"
                    ),
                }
            else:
                # Missing scopes are fatal; extras are a warning
                # (recorded but don't fail the doctor)
                sections["live_scope_drift"] = {
                    "status": (
                        "pass" if health_report.is_healthy
                        else "fail"
                    ),
                    "missing_from_app": (
                        health_report.missing_from_app
                    ),
                    "extra_in_app": health_report.extra_in_app,
                    "granted_count": (
                        len(health_report.granted_scopes)
                    ),
                    "required_count": (
                        len(health_report.required_scopes)
                    ),
                }
                if not health_report.is_healthy:
                    overall_ok = False
        except Exception as exc:  # noqa: BLE001
            logger.debug("live scope probe raised: %s", exc)
            sections["live_scope_drift"] = {
                "status": "unavailable",
                "error": str(exc),
            }

    # ── Live webhook drift ───────────────────────────────────
    if getattr(args, "skip_live", False):
        sections["live_webhook_drift"] = {
            "status": "skipped",
            "reason": "--skip-live flag set",
        }
    else:
        try:
            from core.feedback.webhook_health import (
                compare_to_live as webhook_compare_to_live,
            )
            wh_report = webhook_compare_to_live()
            if wh_report is None:
                sections["live_webhook_drift"] = {
                    "status": "skipped",
                    "reason": (
                        "webhooks adapter not configured or "
                        "live API call failed"
                    ),
                }
            else:
                sections["live_webhook_drift"] = {
                    "status": (
                        "pass" if wh_report.is_healthy
                        else "fail"
                    ),
                    "missing_on_app": wh_report.missing_on_app,
                    "extra_on_app": wh_report.extra_on_app,
                    "gdpr_missing": wh_report.gdpr_missing,
                    "registered_count": (
                        len(wh_report.registered_topics)
                    ),
                    "declared_count": (
                        len(wh_report.declared_topics)
                    ),
                }
                if not wh_report.is_healthy:
                    overall_ok = False
        except Exception as exc:  # noqa: BLE001
            logger.debug("live webhook probe raised: %s", exc)
            sections["live_webhook_drift"] = {
                "status": "unavailable",
                "error": str(exc),
            }

    # ── Engines-writebacks coverage (informational) ─────────
    # Not a pass/fail check — advisory engines are legitimate.
    # Surfaces the Phase 6/7 wireup state so operators know
    # which engines act autonomously today + what the Phase 7
    # candidate pool looks like. Counts as 'info' (never fails
    # the doctor) but does flag 'partial' wireups as a warning.
    try:
        from engines._writeback_audit import audit_writeback_coverage
        wb_report = audit_writeback_coverage("engines")
        # Status: 'info' when nothing is partial; 'warn' when
        # at least one engine is half-wired (real rollout gap).
        wb_status = "warn" if wb_report.partial_count > 0 else "info"
        sections["engines_writebacks"] = {
            "status": wb_status,
            "total_engines": wb_report.total_engines,
            "wired": wb_report.wired_count,
            "advisory": wb_report.advisory_count,
            "partial": wb_report.partial_count,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("writebacks audit raised: %s", exc)
        sections["engines_writebacks"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    return overall_ok, sections


def _cmd_shopify_doctor(args) -> None:
    """Aggregate health check across the institutional-protection
    surfaces. Renders either JSON or human text and exits non-zero
    when any fatal check fails."""
    overall_ok, sections = _collect_doctor_sections(args)

    if getattr(args, "json", False):
        print(json.dumps({
            "ok": overall_ok,
            "sections": sections,
        }, indent=2, default=str))
        if not overall_ok:
            sys.exit(1)
        return

    print("ShopAI Shopify Doctor")
    print()

    _doctor_render_pattern_k(sections.get("pattern_k_dispatchers", {}))
    _doctor_render_oauth(sections.get("oauth_scope_coverage", {}))
    _doctor_render_pattern_y(sections.get("pattern_y_capabilities", {}))
    _doctor_render_pattern_i(
        sections.get("pattern_i_engine_capabilities", {})
    )
    _doctor_render_pattern_j(
        sections.get("pattern_j_test_pollution", {})
    )
    _doctor_render_pattern_z(
        sections.get("pattern_z_writer_recorder", {})
    )
    _doctor_render_live(sections.get("live_scope_drift", {}))
    _doctor_render_webhook_live(sections.get("live_webhook_drift", {}))
    _doctor_render_writebacks(sections.get("engines_writebacks", {}))

    print()
    if overall_ok:
        print("Overall: OK — all institutional protection checks pass.")
    else:
        print(
            "Overall: FAILED — at least one check has gaps. "
            "Inspect sections above."
        )
        sys.exit(1)


def _cmd_unified_doctor(args) -> None:
    """Unified health check: shopify-doctor + approvals doctor in
    one run.

    The 'is everything OK?' command for operators. Combines the
    Shopify institutional-protection audit (7 sections) with the
    approval-queue health check (5 sections) into a single
    verdict. Fatal failures in either side flip the overall to
    FAILED and exit 1.

    Reuses the two existing collectors (`_collect_doctor_sections`
    and `_collect_approvals_doctor_sections`) so the underlying
    section logic stays single-sourced.
    """
    shopify_ok, shopify_sections = _collect_doctor_sections(args)
    approvals_ok, approvals_sections = (
        _collect_approvals_doctor_sections(args)
    )
    overall_ok = shopify_ok and approvals_ok

    if getattr(args, "json", False):
        print(json.dumps({
            "ok": overall_ok,
            "shopify": {
                "ok": shopify_ok,
                "sections": shopify_sections,
            },
            "approvals": {
                "ok": approvals_ok,
                "sections": approvals_sections,
            },
        }, indent=2, default=str))
        if not overall_ok:
            sys.exit(1)
        return

    print("ShopAI Doctor (unified)")
    print()
    print("== Shopify integration ==")
    _doctor_render_pattern_k(
        shopify_sections.get("pattern_k_dispatchers", {}),
    )
    _doctor_render_oauth(
        shopify_sections.get("oauth_scope_coverage", {}),
    )
    _doctor_render_pattern_y(
        shopify_sections.get("pattern_y_capabilities", {}),
    )
    _doctor_render_pattern_i(
        shopify_sections.get("pattern_i_engine_capabilities", {}),
    )
    _doctor_render_pattern_j(
        shopify_sections.get("pattern_j_test_pollution", {}),
    )
    _doctor_render_pattern_z(
        shopify_sections.get("pattern_z_writer_recorder", {}),
    )
    _doctor_render_live(
        shopify_sections.get("live_scope_drift", {}),
    )
    _doctor_render_webhook_live(
        shopify_sections.get("live_webhook_drift", {}),
    )
    _doctor_render_writebacks(
        shopify_sections.get("engines_writebacks", {}),
    )
    print()
    print("== Approval queue ==")
    _approvals_doctor_render_pattern_k(
        approvals_sections.get("pattern_k_dispatchers", {}),
    )
    _approvals_doctor_render_pending(
        approvals_sections.get("pending_queue", {}),
    )
    _approvals_doctor_render_dispatch(
        approvals_sections.get("recent_dispatch", {}),
    )
    _approvals_doctor_render_quarantine(
        approvals_sections.get("quarantine", {}),
    )
    _approvals_doctor_render_auto_approve(
        approvals_sections.get("auto_approve", {}),
    )
    _approvals_doctor_render_alert_history(
        approvals_sections.get("alert_history", {}),
    )

    print()
    if overall_ok:
        print("Overall: OK -- both Shopify and approval-queue "
              "checks pass.")
    else:
        broken = []
        if not shopify_ok:
            broken.append("Shopify")
        if not approvals_ok:
            broken.append("Approval queue")
        print(
            f"Overall: FAILED -- {' + '.join(broken)} has gaps. "
            "Inspect sections above."
        )
        sys.exit(1)


def _doctor_render_pattern_k(section: dict) -> None:
    status = section.get("status", "unavailable")
    if status == "pass":
        print(
            f"[pass] Pattern K dispatchers — "
            f"{section.get('enqueue_sites', 0)} enqueue sites, "
            f"{section.get('dispatchers_registered', 0)} dispatchers"
        )
    elif status == "fail":
        missing = section.get("missing", [])
        print(
            f"[FAIL] Pattern K dispatchers — "
            f"{len(missing)} missing: "
            f"{', '.join(missing[:3])}"
            f"{'...' if len(missing) > 3 else ''}"
        )
        print(
            "       fix: register a dispatcher for each missing "
            "action_type in core/approval/dispatchers.py "
            "(see `shopai approvals audit` for the full list)"
        )
    else:
        print(
            f"[??] Pattern K dispatchers — "
            f"{section.get('error', 'unavailable')}"
        )


def _doctor_render_oauth(section: dict) -> None:
    status = section.get("status", "unavailable")
    if status == "pass":
        print(
            f"[pass] OAuth scope coverage — "
            f"{section.get('declared_count', 0)}/"
            f"{section.get('total_adapters', 0)} adapters, "
            f"{section.get('unique_scopes', 0)} unique scopes"
        )
    elif status == "fail":
        gaps = section.get("undeclared_adapters", [])
        sample = ", ".join(gaps[:3]) + ("..." if len(gaps) > 3 else "")
        print(
            f"[FAIL] OAuth scope coverage — "
            f"{len(gaps)} undeclared adapter(s): {sample}"
        )
        print(
            "       fix: add `required_scopes = frozenset({...})` "
            "or `scope_independent = True` to each adapter under "
            "core/adapters/shopify/ (see `shopai shopify-scopes-audit`)"
        )
    else:
        print(
            f"[??] OAuth scope coverage — "
            f"{section.get('error', 'unavailable')}"
        )


def _doctor_render_pattern_y(section: dict) -> None:
    status = section.get("status", "unavailable")
    if status == "pass":
        print(
            f"[pass] Pattern Y capabilities — "
            f"{section.get('claimed_count', 0)}/"
            f"{section.get('total_shopify_capabilities', 0)} "
            "enum values claimed"
        )
    elif status == "fail":
        unclaimed = section.get("unclaimed", [])
        orphan = section.get("orphan_claims", [])
        print(
            f"[FAIL] Pattern Y capabilities — "
            f"{len(unclaimed)} unclaimed, "
            f"{len(orphan)} orphan claim(s)"
        )
        print(
            "       fix: add an adapter under core/adapters/shopify/ "
            "for each unclaimed Capability enum value, OR drop the "
            "enum value (see `shopai capabilities-audit`)"
        )
    else:
        print(
            f"[??] Pattern Y capabilities — "
            f"{section.get('error', 'unavailable')}"
        )


def _doctor_render_pattern_i(section: dict) -> None:
    status = section.get("status", "unavailable")
    if status == "pass":
        print(
            f"[pass] Pattern I engine capabilities -- "
            f"{section.get('total_refs', 0)} `capability_name=` "
            f"refs across "
            f"{section.get('distinct_capabilities', 0)} capabilities; "
            "all routable"
        )
    elif status == "fail":
        unknown = section.get("unknown_enum_member", [])
        unclaimed = section.get("unclaimed_by_adapter", [])
        print(
            f"[FAIL] Pattern I engine capabilities -- "
            f"{len(unknown)} unknown, "
            f"{len(unclaimed)} unclaimed"
        )
        # Surface up to 3 of each so operators see the first hit
        for ref in unknown[:3]:
            print(f"       unknown: {ref}")
        for ref in unclaimed[:3]:
            print(f"       unclaimed: {ref}")
        print(
            "       fix: correct the engine's `capability_name=` "
            "string, OR add an adapter under core/adapters/shopify/ "
            "claiming the capability (see "
            "`shopai engines-capability-audit`)"
        )
    else:
        print(
            f"[??] Pattern I engine capabilities -- "
            f"{section.get('error', 'unavailable')}"
        )


def _doctor_render_pattern_j(section: dict) -> None:
    status = section.get("status", "unavailable")
    if status == "pass":
        print(
            f"[pass] Pattern J test pollution -- "
            f"{section.get('recorder_sites', 0)} recorder + "
            f"{section.get('guarded_sites', 0)} guarded site(s); "
            "no unguarded writes"
        )
    elif status == "fail":
        unguarded = section.get("unguarded_sites", [])
        print(
            f"[FAIL] Pattern J test pollution -- "
            f"{len(unguarded)} unguarded write-site(s)"
        )
        for site in unguarded[:3]:
            print(f"       {site}")
        print(
            "       fix: delegate through "
            "`engines._writeback_recorder.record_writeback()` "
            "or add an `_is_test_environment()` guard "
            "(see `shopai pattern-j-audit`)"
        )
    else:
        print(
            f"[??] Pattern J test pollution -- "
            f"{section.get('error', 'unavailable')}"
        )


def _doctor_render_pattern_z(section: dict) -> None:
    status = section.get("status", "unavailable")
    if status == "pass":
        print(
            f"[pass] Pattern Z writer-recorder -- "
            f"{section.get('clean_writers', 0)}/"
            f"{section.get('scanned_writers', 0)} "
            "writer module(s) call record_writeback"
        )
    elif status == "fail":
        missing = section.get("missing_recorder", [])
        print(
            f"[FAIL] Pattern Z writer-recorder -- "
            f"{len(missing)} writer(s) missing recorder"
        )
        for site in missing[:3]:
            print(f"       {site}")
        print(
            "       fix: add `record_writeback(...)` adjacent to "
            "the mutation in each flagged writer "
            "(see `shopai pattern-z-audit`)"
        )
    else:
        print(
            f"[??] Pattern Z writer-recorder -- "
            f"{section.get('error', 'unavailable')}"
        )


def _doctor_render_live(section: dict) -> None:
    status = section.get("status", "unavailable")
    if status == "pass":
        print(
            f"[pass] Live scope drift — "
            f"{section.get('granted_count', 0)}/"
            f"{section.get('required_count', 0)} "
            "scopes granted; no drift"
        )
        extras = section.get("extra_in_app", [])
        if extras:
            print(
                f"       (warning: {len(extras)} extra scope(s) "
                "granted but not declared — over-requesting)"
            )
    elif status == "fail":
        missing = section.get("missing_from_app", [])
        sample = ", ".join(missing[:3]) + ("..." if len(missing) > 3 else "")
        print(
            f"[FAIL] Live scope drift — "
            f"{len(missing)} scope(s) declared but NOT granted: "
            f"{sample}"
        )
        print(
            "       fix: re-install the app on the merchant so the "
            "OAuth consent re-runs with the current scope set "
            "(or re-grant via the Shopify Admin -> Apps panel)"
        )
    elif status == "skipped":
        print(
            f"[skip] Live scope drift — "
            f"{section.get('reason', 'unknown')}"
        )
    else:
        print(
            f"[??] Live scope drift — "
            f"{section.get('error', 'unavailable')}"
        )


def _doctor_render_webhook_live(section: dict) -> None:
    status = section.get("status", "unavailable")
    if status == "pass":
        print(
            f"[pass] Live webhook drift — "
            f"{section.get('declared_count', 0)}/"
            f"{section.get('declared_count', 0)} "
            "topics registered; no drift"
        )
        extras = section.get("extra_on_app", [])
        if extras:
            print(
                f"       (warning: {len(extras)} extra "
                "subscription(s) registered but not declared)"
            )
    elif status == "fail":
        missing = section.get("missing_on_app", [])
        gdpr_missing = section.get("gdpr_missing", [])
        suffix = (
            f" (incl. {len(gdpr_missing)} GDPR-mandatory)"
            if gdpr_missing else ""
        )
        print(
            f"[FAIL] Live webhook drift — "
            f"{len(missing)} topic(s) declared but NOT "
            f"registered{suffix}"
        )
        if gdpr_missing:
            print(
                "       *** GDPR topics missing — public-distribution "
                "Shopify review WILL REJECT until these are "
                f"registered: {', '.join(gdpr_missing)}"
            )
        print(
            "       fix: deploy the latest shopify.app.toml "
            "(`shopai shopify-prepare-deploy`) and re-deploy the "
            "app so Shopify picks up the new webhook subscriptions"
        )
    elif status == "skipped":
        print(
            f"[skip] Live webhook drift — "
            f"{section.get('reason', 'unknown')}"
        )
    else:
        print(
            f"[??] Live webhook drift — "
            f"{section.get('error', 'unavailable')}"
        )


def _doctor_render_writebacks(section: dict) -> None:
    """Render the engines-writebacks Phase 6/7 coverage line.

    Informational (never fails the doctor): advisory engines
    are legitimate. ``partial`` engines surface as a warning
    because they're a real rollout gap — writer or opt-in but
    not both.
    """
    status = section.get("status", "unavailable")
    if status == "info":
        total = section.get("total_engines", 0)
        wired = section.get("wired", 0)
        advisory = section.get("advisory", 0)
        pct = round(100 * wired / total) if total else 0
        print(
            f"[info] Engine writebacks — "
            f"{wired}/{total} wired ({pct}%), "
            f"{advisory} advisory"
        )
    elif status == "warn":
        total = section.get("total_engines", 0)
        wired = section.get("wired", 0)
        partial = section.get("partial", 0)
        print(
            f"[WARN] Engine writebacks — "
            f"{wired}/{total} wired; "
            f"{partial} engine(s) half-wired (run "
            "`shopai engines-writebacks --filter partial`)"
        )
    else:
        print(
            f"[??] Engine writebacks — "
            f"{section.get('error', 'unavailable')}"
        )


def _cmd_shopify_webhooks(args) -> None:
    """List the registered Shopify webhook subscriptions.

    Mirrors ``shopai shopify-scopes`` for the webhook surface.
    The registry (PR #182) is the single source of truth — the
    webhook bridge derives its polarity buckets from it, and the
    manifest generator emits the deployable TOML fragment.

    ``--gdpr-only`` filters to the three GDPR-mandatory topics
    (every public-distribution Shopify app MUST subscribe).
    """
    try:
        from core.feedback.webhook_registry import WEBHOOK_REGISTRY
    except Exception as exc:  # noqa: BLE001
        logger.debug("webhook registry import failed: %s", exc)
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print("Webhook registry unavailable")
        return

    subs = list(WEBHOOK_REGISTRY)
    if getattr(args, "gdpr_only", False):
        subs = [s for s in subs if s.gdpr_mandatory]

    if getattr(args, "json", False):
        print(json.dumps([
            {
                "topic": s.topic,
                "polarity": s.polarity,
                "purpose": s.purpose,
                "gdpr_mandatory": s.gdpr_mandatory,
            }
            for s in subs
        ], indent=2))
        return

    if not subs:
        print("(no webhook subscriptions match the filter)")
        return

    label = (
        "GDPR-mandatory webhook subscriptions"
        if getattr(args, "gdpr_only", False)
        else "Webhook subscriptions"
    )
    print(f"{label} ({len(subs)}):")
    print()
    for s in subs:
        gdpr_tag = " [GDPR]" if s.gdpr_mandatory else ""
        print(f"  {s.topic:<28}  ({s.polarity}){gdpr_tag}")
        print(f"    {s.purpose}")


def _cmd_shopify_webhook_manifest(args) -> None:
    """Generate a Shopify app webhook subscription manifest.

    Companion to ``shopify-install-manifest`` (PR #178). Together
    they emit the two deployable config blocks the Shopify CLI
    needs: ``[access_scopes]`` for OAuth scopes, ``[webhooks]``
    for subscriptions. Re-run both after adding/removing
    subscribed topics; commit the resulting diffs.
    """
    try:
        from core.feedback.webhook_registry import WEBHOOK_REGISTRY
    except Exception as exc:  # noqa: BLE001
        logger.debug("webhook registry import failed: %s", exc)
        if getattr(args, "format", "toml") == "json":
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"# Manifest unavailable: {exc}")
        return

    fmt = getattr(args, "format", "toml")
    subs = sorted(WEBHOOK_REGISTRY, key=lambda s: s.topic)

    if fmt == "json":
        print(json.dumps([
            {
                "topic": s.topic,
                "polarity": s.polarity,
                "purpose": s.purpose,
                "gdpr_mandatory": s.gdpr_mandatory,
            }
            for s in subs
        ], indent=2))
        return

    # toml
    gdpr_count = sum(1 for s in subs if s.gdpr_mandatory)
    print("# Generated by `shopai shopify-webhook-manifest`")
    print(
        f"# Subscriptions: {len(subs)} "
        f"({gdpr_count} GDPR-mandatory)"
    )
    print("#")
    print("# Paste this fragment into your shopify.app.toml under")
    print("# [[webhooks.subscriptions]]. Re-run after editing the")
    print("# webhook_registry.py to refresh.")
    print()
    print("[webhooks]")
    print('api_version = "2024-01"')
    print()
    for s in subs:
        print(f"# {s.purpose}")
        print("[[webhooks.subscriptions]]")
        print(f'topics = ["{s.topic}"]')
        # Operators wire their own callback URL — the manifest
        # leaves a placeholder so the deploy step substitutes it.
        print('uri = "https://YOUR_APP_HOST/api/webhook/shopify"')
        print()


def _cmd_shopify_app_toml(args) -> None:
    """Emit a complete ``shopify.app.toml`` combining the
    install manifest (PR #178) + webhook manifest (PR #182)
    into one deployable file.

    Operators previously ran two commands and pasted both
    outputs into ``shopify.app.toml`` separately. This wraps
    them into a single canonical emit + adds the surrounding
    structural fields (``name``, ``application_url``,
    ``redirect_urls``, ``api_version``) so the result is a
    ready-to-deploy file rather than just fragments.

    ``--app-host`` substitutes the placeholder URL across every
    webhook subscription's callback. Operators redirect by
    setting their actual host (e.g. ``https://shopai.io``).

    Output is always TOML; ``shopai shopify-install-manifest``
    + ``shopai shopify-webhook-manifest`` still emit the
    fragments independently for cases where operators want to
    re-paste only one block.
    """
    from core.adapters.shopify.scope_registry import collect_manifest
    from core.feedback.webhook_registry import WEBHOOK_REGISTRY

    app_name = getattr(args, "app_name", "shopai") or "shopai"
    app_host = (
        getattr(args, "app_host", "https://YOUR_APP_HOST")
        or "https://YOUR_APP_HOST"
    ).rstrip("/")
    api_version = (
        getattr(args, "api_version", "2024-01") or "2024-01"
    )

    # ── Scope manifest ────────────────────────────────────
    try:
        manifest = collect_manifest()
        scopes = sorted(manifest.all_scopes)
    except Exception as exc:  # noqa: BLE001
        logger.debug("scope manifest unavailable: %s", exc)
        scopes = []

    # ── Webhook manifest ──────────────────────────────────
    webhook_subs = sorted(
        WEBHOOK_REGISTRY, key=lambda s: s.topic,
    )

    # ── Build the TOML string ─────────────────────────────
    lines: list[str] = []
    lines.append("# Generated by `shopai shopify-app-toml`")
    lines.append(
        f"# {len(scopes)} OAuth scope(s), "
        f"{len(webhook_subs)} webhook subscription(s)"
    )
    lines.append(
        "# Re-run after any registry edit (scope or webhook) "
        "to refresh."
    )
    lines.append("")
    lines.append(f'name = "{app_name}"')
    lines.append(f'application_url = "{app_host}/"')
    lines.append("")
    lines.append("[auth]")
    lines.append(
        f'redirect_urls = ['
        f'"{app_host}/auth/callback", '
        f'"{app_host}/auth/shopify/callback"'
        f']'
    )
    lines.append("")

    if scopes:
        scopes_csv = ",".join(scopes)
        lines.append("[access_scopes]")
        lines.append(f'scopes = "{scopes_csv}"')
        lines.append("")

    lines.append("[webhooks]")
    lines.append(f'api_version = "{api_version}"')
    lines.append("")
    for s in webhook_subs:
        lines.append(f"# {s.purpose}")
        lines.append("[[webhooks.subscriptions]]")
        lines.append(f'topics = ["{s.topic}"]')
        lines.append(f'uri = "{app_host}/api/webhook/shopify"')
        lines.append("")

    toml_body = "\n".join(lines) + "\n"

    # ── Output: write to file OR stdout ───────────────────
    target = getattr(args, "write", None)
    if target:
        from pathlib import Path
        target_path = Path(target)
        force = bool(getattr(args, "force", False))
        if target_path.exists() and not force:
            print(
                f"Refusing to overwrite {target_path} — pass "
                "--force to overwrite, or pick a different path."
            )
            sys.exit(1)
        # Ensure parent directory exists so operators pointing
        # at e.g. ``deploy/shopify.app.toml`` don't fail on a
        # missing dir
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(toml_body, encoding="utf-8")
        except OSError as exc:
            print(f"Failed to write {target_path}: {exc}")
            sys.exit(1)
        print(
            f"Wrote {target_path} "
            f"({len(toml_body.splitlines())} lines, "
            f"{len(scopes)} scopes, "
            f"{len(webhook_subs)} webhooks)"
        )
        return

    # Default: stdout
    sys.stdout.write(toml_body)


def _cmd_shopify_prepare_deploy(args) -> None:
    """Capstone: doctor health check + ``shopify.app.toml`` emit.

    The fail-safe deploy gate. Operators run ONE command to:

      1. Run every doctor section (Pattern K, OAuth scopes,
         Pattern Y, live drift, webhook drift, writebacks audit).
      2. Refuse to emit the deploy file if any fatal check
         failed — unless ``--write-on-warning`` is set.
      3. When safe (or forced), invoke the same logic as
         ``shopai shopify-app-toml`` to write the deployable
         TOML.

    Default destination is ``shopify.app.toml`` in the working
    directory; override with ``--output``. Use ``--force`` to
    overwrite an existing file (mirrors the app-toml command).

    Exits 0 on successful write; 1 when doctor flags a fatal
    issue and ``--write-on-warning`` is unset, or when writing
    fails.
    """
    overall_ok, sections = _collect_doctor_sections(args)

    print("ShopAI prepare-deploy")
    print()
    _doctor_render_pattern_k(sections.get("pattern_k_dispatchers", {}))
    _doctor_render_oauth(sections.get("oauth_scope_coverage", {}))
    _doctor_render_pattern_y(sections.get("pattern_y_capabilities", {}))
    _doctor_render_pattern_i(
        sections.get("pattern_i_engine_capabilities", {})
    )
    _doctor_render_pattern_j(
        sections.get("pattern_j_test_pollution", {})
    )
    _doctor_render_pattern_z(
        sections.get("pattern_z_writer_recorder", {})
    )
    _doctor_render_live(sections.get("live_scope_drift", {}))
    _doctor_render_webhook_live(sections.get("live_webhook_drift", {}))
    _doctor_render_writebacks(sections.get("engines_writebacks", {}))
    print()

    if not overall_ok and not getattr(args, "write_on_warning", False):
        print(
            "Refusing to write — doctor flagged failures. Fix the "
            "above sections, or pass --write-on-warning to emit "
            "the TOML anyway (e.g. during initial bring-up before "
            "the live app exists)."
        )
        sys.exit(1)

    if not overall_ok:
        print(
            "Doctor flagged failures, but --write-on-warning was "
            "passed — emitting TOML anyway."
        )

    # Re-use the app-toml command's emission logic. Build a small
    # namespace with the fields it reads so we don't duplicate.
    import argparse as _argparse
    output = getattr(args, "output", None) or "shopify.app.toml"
    toml_args = _argparse.Namespace(
        app_name=getattr(args, "app_name", None) or "shopai",
        app_host=(
            getattr(args, "app_host", None) or "https://YOUR_APP_HOST"
        ),
        api_version=getattr(args, "api_version", None) or "2024-01",
        write=output,
        force=bool(getattr(args, "force", False)),
    )
    _cmd_shopify_app_toml(toml_args)


def _cmd_release_bundle(args) -> None:
    """Deploy-day capstone: generate every release artifact into
    one folder.

    Files written:
      - snapshot.json -- full system state via shopai snapshot
      - catalog.md    -- catalog Markdown via catalog --markdown
      - shopify.app.toml -- deployable config via shopify-app-toml
      - doctor.txt    -- text doctor output (point-in-time
        verdict for audit history)
      - README.md     -- index linking the above + summary

    Refuses to write when the doctor flags failures unless
    ``--write-on-warning`` is set (matches prepare-deploy's
    contract).

    Operators commit this folder per release; the diff between
    release/ at v1 vs v2 is the operator-visible delta for
    review.
    """
    from io import StringIO
    from pathlib import Path

    output_dir = Path(getattr(args, "output", None) or "release")
    force = bool(getattr(args, "force", False))
    write_on_warning = bool(getattr(args, "write_on_warning", False))

    # ── Doctor gate ─────────────────────────────────────────
    overall_ok, sections = _collect_doctor_sections(args)
    print("ShopAI release-bundle")
    print()
    print("== Doctor verdict ==")
    _doctor_render_pattern_k(sections.get("pattern_k_dispatchers", {}))
    _doctor_render_oauth(sections.get("oauth_scope_coverage", {}))
    _doctor_render_pattern_y(sections.get("pattern_y_capabilities", {}))
    _doctor_render_pattern_i(
        sections.get("pattern_i_engine_capabilities", {})
    )
    _doctor_render_pattern_j(
        sections.get("pattern_j_test_pollution", {})
    )
    _doctor_render_pattern_z(
        sections.get("pattern_z_writer_recorder", {})
    )
    _doctor_render_live(sections.get("live_scope_drift", {}))
    _doctor_render_webhook_live(sections.get("live_webhook_drift", {}))
    _doctor_render_writebacks(sections.get("engines_writebacks", {}))
    print()

    if not overall_ok and not write_on_warning:
        print(
            "Refusing to write -- doctor flagged failures. "
            "Fix the above sections, or pass --write-on-warning."
        )
        sys.exit(1)
    if not overall_ok:
        print(
            "Doctor flagged failures, but --write-on-warning "
            "was passed -- emitting bundle anyway."
        )

    # ── Output dir guard ────────────────────────────────────
    if output_dir.exists() and not force:
        # Allow if empty (mkdir, no overwrites)
        try:
            empty = not any(output_dir.iterdir())
        except OSError as exc:
            print(f"Cannot inspect {output_dir}: {exc}")
            sys.exit(1)
        if not empty:
            print(
                f"Refusing to overwrite non-empty {output_dir} "
                "-- pass --force to overwrite."
            )
            sys.exit(1)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Failed to create {output_dir}: {exc}")
        sys.exit(1)

    # ── snapshot.json ───────────────────────────────────────
    import argparse as _argparse
    snap_args = _argparse.Namespace(
        output=str(output_dir / "snapshot.json"),
        force=True,
        skip_live=getattr(args, "skip_live", False),
        diff=None,
        json=False,
        stale_pending_hours=24.0,
        failure_rate_warn=0.25,
    )
    # Re-use the existing snapshot command so the same code path
    # produces the same artifact shape that operators get from
    # `shopai snapshot --output FILE`.
    _capture_silent(_cmd_snapshot, snap_args)
    print(f"  wrote {output_dir / 'snapshot.json'}")

    # ── catalog.md ──────────────────────────────────────────
    md_buf = StringIO()
    md_args = _argparse.Namespace(
        json=False, markdown=True,
        engine=None, action_type=None,
    )
    with _redirect_stdout(md_buf):
        _cmd_catalog(md_args)
    (output_dir / "catalog.md").write_text(
        md_buf.getvalue(), encoding="utf-8",
    )
    print(f"  wrote {output_dir / 'catalog.md'}")

    # ── shopify.app.toml ────────────────────────────────────
    toml_args = _argparse.Namespace(
        app_name=getattr(args, "app_name", None) or "shopai",
        app_host=(
            getattr(args, "app_host", None) or "https://YOUR_APP_HOST"
        ),
        api_version=getattr(args, "api_version", None) or "2024-01",
        write=str(output_dir / "shopify.app.toml"),
        force=True,
    )
    _capture_silent(_cmd_shopify_app_toml, toml_args)
    print(f"  wrote {output_dir / 'shopify.app.toml'}")

    # ── doctor.txt ──────────────────────────────────────────
    # Re-render the doctor to a file for audit history. Uses
    # _cmd_shopify_doctor's existing text path.
    doc_buf = StringIO()
    doc_args = _argparse.Namespace(
        json=False, skip_live=getattr(args, "skip_live", False),
    )
    with _redirect_stdout(doc_buf):
        try:
            _cmd_shopify_doctor(doc_args)
        except SystemExit:
            # Doctor exits 1 on failure; we already chose to
            # write (via write_on_warning), so swallow the exit.
            pass
    (output_dir / "doctor.txt").write_text(
        doc_buf.getvalue(), encoding="utf-8",
    )
    print(f"  wrote {output_dir / 'doctor.txt'}")

    # ── README.md ───────────────────────────────────────────
    from datetime import datetime, timezone
    generated_at = datetime.now(timezone.utc).isoformat()
    readme = "\n".join([
        "# ShopAI Release Bundle",
        "",
        f"_Generated: {generated_at}_",
        "",
        f"Doctor verdict: **{'OK' if overall_ok else 'FAILED'}**",
        "",
        "## Contents",
        "",
        "- [`snapshot.json`](snapshot.json) -- full system state "
        "(engine counts, catalog, every audit, both doctor verdicts)",
        "- [`catalog.md`](catalog.md) -- action catalog for "
        "ops + non-CLI stakeholders",
        "- [`shopify.app.toml`](shopify.app.toml) -- deployable "
        "Shopify config (scopes + webhook subscriptions)",
        "- [`doctor.txt`](doctor.txt) -- doctor render at the "
        "time of bundle generation",
        "",
        "## How to use",
        "",
        "Commit this folder per release. The diff between "
        "`release/` at v1 vs v2 is the operator-visible delta "
        "for review. Compare `snapshot.json` across releases "
        "with `shopai snapshot --diff <prev>/snapshot.json`.",
        "",
    ])
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    print(f"  wrote {output_dir / 'README.md'}")

    print()
    print(
        f"Release bundle written to {output_dir}/ "
        f"(5 files; doctor: "
        f"{'OK' if overall_ok else 'FAILED'})"
    )


def _capture_silent(fn, args) -> None:
    """Helper to call a CLI command and discard its stdout. Used
    by release-bundle when re-using existing commands that print
    progress to stdout but write the actual artifact to disk."""
    from io import StringIO
    buf = StringIO()
    with _redirect_stdout(buf):
        try:
            fn(args)
        except SystemExit:
            # Inner commands may exit non-zero on overwrite
            # refusal etc.; the bundle controls force-overwrite
            # so any inner exit is unexpected -- swallow to keep
            # the bundle's outer flow intact. The inner output is
            # available in `buf` for debugging.
            pass


from contextlib import contextmanager as _contextmanager


@_contextmanager
def _redirect_stdout(buf):
    """Local stdout redirect (the std lib's contextlib.redirect_stdout
    works too but its presence in cli.py was inconsistent; this
    keeps the import surface minimal)."""
    old = sys.stdout
    sys.stdout = buf
    try:
        yield buf
    finally:
        sys.stdout = old


def _cmd_shopify_install_manifest(args) -> None:
    """Generate a Shopify app install manifest fragment.

    Closes the loop on the scope registry: registry → install
    manifest → ``shopify.app.toml``. Operators no longer have to
    hand-transcribe the scope union when registering the app on
    a new merchant.

    Three formats:
      - ``toml`` (default): ready to paste into
        ``[access_scopes]`` of ``shopify.app.toml``. The TOML
        format Shopify's CLI expects is ``scopes = "a,b,c"`` so
        the manifest emits that single string.
      - ``json``: raw list of scope names — useful for
        programmatic consumption (CI scripts that compare
        live-app scopes against the manifest, for example).
      - ``csv``: one-line comma-separated, no quotes — useful
        for ``shopify app config`` or similar tooling.

    ``--with-comments`` (toml only) adds per-scope adapter-usage
    comments so the generated file's reader can trace exactly
    which adapter brought in which scope.
    """
    from core.adapters.shopify.scope_registry import collect_manifest

    try:
        manifest = collect_manifest()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "scope manifest collection raised: %s", exc,
        )
        if getattr(args, "format", "toml") == "json":
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"# Manifest unavailable: {exc}")
        return

    scopes = sorted(manifest.all_scopes)
    fmt = getattr(args, "format", "toml")

    if fmt == "json":
        print(json.dumps(scopes, indent=2))
        return

    if fmt == "csv":
        # One-line comma-separated list — matches the value
        # operators paste into ``scopes = "..."``
        print(",".join(scopes))
        return

    # toml (default)
    print("# Generated by `shopai shopify-install-manifest`")
    print(f"# Scopes: {len(scopes)} (across "
          f"{manifest.total_adapters - len(manifest.scope_independent_adapters)} "
          f"adapters; {len(manifest.scope_independent_adapters)} "
          f"scope-independent)")
    print("#")
    print("# Paste this fragment into your shopify.app.toml under")
    print("# [access_scopes]. Re-run after wiring new adapters")
    print("# to refresh.")
    print()

    if getattr(args, "with_comments", False):
        print("[access_scopes]")
        for scope in scopes:
            adapters_using = manifest.by_scope.get(scope, [])
            # Truncate the adapter list comment to keep the line
            # readable when many adapters share a scope (e.g.
            # read_orders has 12 users)
            if len(adapters_using) > 4:
                head = ", ".join(adapters_using[:3])
                comment = (
                    f"# used by {head}, "
                    f"... +{len(adapters_using) - 3} more"
                )
            else:
                comment = f"# used by {', '.join(adapters_using)}"
            print(f"  {comment}")
            print(f"  # {scope}")
        # Final canonical line for the Shopify CLI
        scopes_csv = ",".join(scopes)
        print(f'scopes = "{scopes_csv}"')
    else:
        # Plain form — single line, ready to paste
        scopes_csv = ",".join(scopes)
        print("[access_scopes]")
        print(f'scopes = "{scopes_csv}"')


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

def _build_version_dict(full: bool = False) -> dict:
    """Gather a runtime fingerprint for support / debug.

    Includes the static ShopAI version, the running Python
    interpreter, the platform string, and a best-effort git SHA
    (so operators can pin "they're running commit X" even when
    they're on a non-tagged dev branch).

    With ``full=True``, adds system-identity fields that change
    when the codebase changes: engine count, dispatcher count,
    and a stable hash of the scope manifest. Operators paste the
    full fingerprint into support tickets to confirm "I'm
    running build X with N dispatchers and scope-hash Y."

    Each ``full`` field is best-effort -- a broken collector
    surfaces as ``None`` for that field, doesn't block the rest.
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

    if not full:
        return payload

    # ── System identity (full mode) ──────────────────────────
    # Each is wrapped in try/except so a single collector
    # failure doesn't break the whole fingerprint.
    try:
        from engines.registry import engine_count
        payload["engine_count"] = engine_count()
    except Exception as exc:  # noqa: BLE001
        logger.debug("engine_count probe raised: %s", exc)
        payload["engine_count"] = None

    try:
        from core.approval.executor import (
            list_registered_action_types,
            _ensure_dispatchers_loaded,
        )
        _ensure_dispatchers_loaded()
        payload["dispatcher_count"] = len(
            list_registered_action_types(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("dispatcher probe raised: %s", exc)
        payload["dispatcher_count"] = None

    try:
        import hashlib
        from core.adapters.shopify.scope_registry import collect_manifest
        manifest = collect_manifest()
        scope_blob = ",".join(sorted(manifest.all_scopes))
        payload["scope_count"] = len(manifest.all_scopes)
        payload["scope_hash"] = hashlib.sha256(
            scope_blob.encode("utf-8"),
        ).hexdigest()[:12]
    except Exception as exc:  # noqa: BLE001
        logger.debug("scope manifest probe raised: %s", exc)
        payload["scope_count"] = None
        payload["scope_hash"] = None

    try:
        # Wired engine count -- captures Phase 6/7 wiring state.
        from engines._writeback_audit import audit_writeback_coverage
        wb = audit_writeback_coverage("engines")
        payload["engines_wired"] = wb.wired_count
        payload["engines_advisory"] = wb.advisory_count
    except Exception as exc:  # noqa: BLE001
        logger.debug("writeback audit probe raised: %s", exc)
        payload["engines_wired"] = None
        payload["engines_advisory"] = None

    return payload


def _cmd_version(args) -> None:
    """Render the version + runtime fingerprint."""
    full = bool(getattr(args, "full", False))
    payload = _build_version_dict(full=full)
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, default=str))
        return
    print(f"ShopAI  {payload['shopai']}")
    print(f"Python  {payload['python']}")
    print(f"Platform {payload['platform']}")
    if "git_sha" in payload:
        print(f"Git SHA {payload['git_sha']}")
    if full:
        # System identity block (only present in full mode)
        ec = payload.get("engine_count")
        dc = payload.get("dispatcher_count")
        sc = payload.get("scope_count")
        sh = payload.get("scope_hash")
        ew = payload.get("engines_wired")
        ea = payload.get("engines_advisory")
        print()
        print("System identity:")
        if ec is not None:
            print(f"  Engines:        {ec}")
        if ew is not None and ea is not None:
            print(f"    wired:        {ew}")
            print(f"    advisory:     {ea}")
        if dc is not None:
            print(f"  Dispatchers:    {dc}")
        if sc is not None and sh is not None:
            print(f"  Scopes:         {sc}  (hash {sh})")


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

    # ── Phase 6/7 wiring snapshot (best-effort) ───────────
    # Surfaces wired-engine progress in the daily-glance view
    # so operators see the autonomous-loop coverage without
    # running engines-writebacks separately.
    engines_wired: int | None = None
    engines_advisory: int | None = None
    try:
        from engines._writeback_audit import (
            audit_writeback_coverage,
        )
        wb = audit_writeback_coverage("engines")
        engines_wired = wb.wired_count
        engines_advisory = wb.advisory_count
    except Exception as exc:  # noqa: BLE001
        logger.debug("status writeback probe raised: %s", exc)

    dispatchers: int | None = None
    try:
        from core.approval.executor import (
            _ensure_dispatchers_loaded,
            list_registered_action_types,
        )
        _ensure_dispatchers_loaded()
        dispatchers = len(list_registered_action_types())
    except Exception as exc:  # noqa: BLE001
        logger.debug("status dispatcher probe raised: %s", exc)

    return {
        "engines": engine_count(),
        "engines_wired": engines_wired,
        "engines_advisory": engines_advisory,
        "dispatchers": dispatchers,
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
    # Phase 6/7 wiring breakdown (best-effort -- present iff
    # the writeback audit succeeded at status-build time)
    wired = payload.get("engines_wired")
    advisory = payload.get("engines_advisory")
    if wired is not None and advisory is not None:
        total = payload["engines"]
        pct = round(100 * wired / total) if total else 0
        print(
            f"    wired:  {wired}/{total} ({pct}%), "
            f"advisory: {advisory}"
        )
    dispatchers = payload.get("dispatchers")
    if dispatchers is not None:
        print(f"  Dispatchers: {dispatchers}")
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
    if verb == "quarantine-simulate":
        _cmd_approvals_quarantine_simulate(args)
        return
    if verb == "alert-history":
        _cmd_approvals_alert_history(args)
        return
    if verb == "health-history":
        _cmd_approvals_health_history(args)
        return
    if verb == "health-regressions":
        _cmd_approvals_health_regressions(args)
        return
    if verb == "auto-approve-candidates":
        _cmd_approvals_auto_candidates(args)
        return
    if verb == "quarantine-release-candidates":
        _cmd_approvals_release_candidates(args)
        return
    if verb == "alert-release-candidates":
        _cmd_approvals_alert_release_candidates(args)
        return
    if verb == "alert-pause-candidates":
        _cmd_approvals_alert_pause_candidates(args)
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
    if verb == "doctor":
        _cmd_approvals_doctor(args)
        return
    if verb == "trace":
        _cmd_approvals_trace(args)
        return
    if verb == "outcome":
        _cmd_approvals_outcome(args)
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
        "  shopai approvals revenue-by-engine [--top N] [--sort net|gross|per-positive] [--json]\n"
        "  shopai approvals doctor             [--stale-pending-hours H] [--failure-rate-warn R] [--json]\n"
        "  shopai approvals trace              <action_id> [--json]"
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

    ``--audit`` scores every allowlist engine via engine_health
    and recommends removal for any whose verdict is currently
    ``unhealthy``. Cron-friendly: exit code 1 if any allowlist
    engine is unhealthy.
    """
    from core.approval import auto_approve as aa

    if getattr(args, "audit", False):
        _audit_auto_approve_allowlist(args)
        return

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


def _audit_auto_approve_allowlist(args) -> None:
    """Score every engine in the auto-approve allowlist and flag
    those whose current ``engine_health`` verdict is unhealthy.

    Output: a per-engine row with score / verdict / first concern,
    plus a summary block. Exit code 1 when ANY allowlist engine
    is unhealthy so monitoring pipelines can fail-fast.
    """
    from core.approval import auto_approve as aa
    from core.approval.engine_health import score_engine

    as_json = bool(getattr(args, "json", False))
    cfg = aa.load_config()
    allowlist = sorted(cfg.allowlist)

    audit_rows: list[dict] = []
    for engine in allowlist:
        try:
            health = score_engine(engine)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "auto-config audit: score_engine raised for %s: "
                "%s", engine, exc,
            )
            continue
        audit_rows.append({
            "engine": engine,
            "score": health.score,
            "verdict": health.verdict,
            "concerns": list(health.concerns),
        })

    unhealthy = [
        r for r in audit_rows if r["verdict"] == "unhealthy"
    ]

    if as_json:
        print(json.dumps({
            "allowlist_size": len(allowlist),
            "audit_rows": audit_rows,
            "unhealthy_engines": [r["engine"] for r in unhealthy],
            "recommendation": (
                "remove unhealthy engines from allowlist via "
                "'shopai approvals auto-config --disable <engine>'"
                if unhealthy else "all engines healthy"
            ),
        }, indent=2, default=str))
    else:
        if not allowlist:
            print("Auto-approve allowlist is empty.")
            print("Nothing to audit.")
            return
        print(
            f"Auto-approve allowlist audit "
            f"({len(allowlist)} engine(s)):"
        )
        print()
        for r in audit_rows:
            concerns = r["concerns"]
            first_concern = concerns[0] if concerns else "-"
            print(
                f"  {r['score']:>2d}/10  "
                f"{r['verdict']:<9s}  "
                f"{r['engine']:<28s}  "
                f"{first_concern}"
            )
        print()
        if unhealthy:
            print(
                f"  {len(unhealthy)} unhealthy engine(s) -- "
                "consider removal:"
            )
            for r in unhealthy:
                print(
                    f"    shopai approvals auto-config "
                    f"--disable {r['engine']}"
                )
        else:
            print("  All allowlist engines healthy.")

    if unhealthy:
        sys.exit(1)


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

    if getattr(args, "release_alert", None):
        engine = args.release_alert
        store_arg = getattr(args, "release_alert_store", None)
        release_all = bool(
            getattr(args, "release_alert_all", False),
        )
        if release_all:
            s = qm.clear_all_alert_pauses_for_engine(engine)
        else:
            s = qm.clear_alert_pause(
                engine, store_id=store_arg,
            )
        # Serialize alert_paused tuples as [engine, store] pairs.
        # Sort by (engine, store_or_empty) since None can't be
        # compared with str in Python 3.
        paused_serialised = [
            [eng, store]
            for (eng, store) in sorted(
                s.alert_paused,
                key=lambda p: (p[0], p[1] or ""),
            )
        ]
        if getattr(args, "json", False):
            print(json.dumps({
                "released_from_alert_pause": engine,
                "released_store": store_arg,
                "released_all": release_all,
                "alert_paused": paused_serialised,
            }, indent=2))
            return
        scope_str = (
            "(all stores)" if release_all
            else f"@{store_arg}" if store_arg else "(fleet)"
        )
        print(
            f"Cleared alert-pause on '{engine}' {scope_str}. "
            f"Alert-paused: {paused_serialised or '(none)'}"
        )
        return

    if getattr(args, "apply_bridge", False):
        # Manually trigger the alert-quarantine bridge. Normally
        # daily-brief is the only caller; this gives operators
        # a way to force the bridge without waiting for the
        # next daily-brief run. Honors the env-var gate just
        # like the daily-brief path.
        from core.approval import alert_quarantine
        as_json = bool(getattr(args, "json", False))
        if not alert_quarantine.is_enabled():
            msg = (
                "bridge disabled "
                "(SHOPAI_AUTO_QUARANTINE_FROM_ALERTS != 1); "
                "no engines paused"
            )
            if as_json:
                print(json.dumps({
                    "status": "skipped",
                    "reason": "bridge_disabled",
                    "paused": [],
                }, indent=2))
            else:
                print(f"Skipped: {msg}")
            return
        try:
            paused = (
                alert_quarantine.maybe_auto_quarantine_from_alerts()
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"bridge run failed: {exc}"
            logger.debug(msg)
            if as_json:
                print(json.dumps({
                    "status": "error", "error": msg,
                }, indent=2, default=str))
            else:
                print(f"Error: {msg}")
            sys.exit(1)
            return
        if as_json:
            print(json.dumps({
                "status": "success",
                "newly_paused": paused,
                "count": len(paused),
            }, indent=2))
            return
        if paused:
            print(
                f"Bridge run: paused {len(paused)} engine(s): "
                f"{', '.join(paused)}"
            )
        else:
            print(
                "Bridge run: no engines crossed the streak "
                "threshold."
            )
        return

    s = qm.load_state()
    payload = {
        "exemptions": sorted(s.exemptions),
        "released": sorted(s.released),
        # Serialise tuples as [engine, store_id] pairs
        "alert_paused": [
            [eng, store]
            for (eng, store) in sorted(
                s.alert_paused,
                key=lambda p: (p[0], p[1] or ""),
            )
        ],
        "thresholds": {
            "min_outcomes_observed": qm.MIN_OUTCOMES_OBSERVED,
            "max_negative_ratio": qm.MAX_NEGATIVE_RATIO,
        },
    }

    # Surface the alert-bridge config too -- operators inspecting
    # quarantine state need to know whether auto-pause is even
    # enabled before they reason about the alert_paused list.
    try:
        from core.approval import alert_quarantine as aq
        payload["alert_quarantine"] = {
            "enabled": aq.is_enabled(),
            "threshold_days": aq.threshold_days(),
            "window_days": aq.window_days(),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "alert_quarantine config readout failed: %s", exc,
        )

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
    # alert_paused is now a set of (engine, store_id) tuples.
    # Format each as ``engine`` (fleet-wide) or
    # ``engine@store_id`` (per-store).
    paused_labels = sorted(
        (
            f"{engine}@{store}" if store else engine
            for (engine, store) in s.alert_paused
        ),
    )
    print(
        f"  Alert-paused ({len(s.alert_paused)}): "
        f"{', '.join(paused_labels) or '(none)'}"
    )
    print("  Thresholds:")
    print(f"    min outcomes observed: {qm.MIN_OUTCOMES_OBSERVED}")
    print(f"    max negative ratio:    {qm.MAX_NEGATIVE_RATIO:.2f}")
    aq_block = payload.get("alert_quarantine")
    if aq_block:
        print("  Alert-quarantine bridge:")
        print(
            f"    enabled:               "
            f"{'yes' if aq_block['enabled'] else 'no'}"
        )
        print(
            f"    threshold days:        "
            f"{aq_block['threshold_days']}"
        )
        print(
            f"    window days:           "
            f"{aq_block['window_days']}"
        )


def _cmd_approvals_quarantine_simulate(args) -> None:
    """Dry-run the quarantine evaluator for a given (engine,
    store_id) pair.

    Answers "if I enqueue an action for ENGINE on STORE_ID
    right now, would it be quarantined, and why?" -- without
    actually creating an action.

    Calls ``quarantine.evaluate()`` directly. The Pattern J
    pytest gate inside ``maybe_quarantine`` is bypassed since
    we don't go through the enqueue path; this is read-only.
    """
    from core.approval import quarantine as qm
    from core.approval.queue import get_approval_queue

    as_json = bool(getattr(args, "json", False))
    engine = (getattr(args, "engine", "") or "").strip()
    store_id = getattr(args, "store", None) or None

    if not engine:
        msg = "engine name is required"
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"Error: {msg}")
        sys.exit(1)
        return

    try:
        queue = get_approval_queue()
        decision = qm.evaluate(
            engine=engine, queue=queue, store_id=store_id,
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"simulate failed: {exc}"
        logger.debug(msg)
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"Error: {msg}")
        sys.exit(1)
        return

    # Read the persisted state too, so the operator sees the
    # full picture without a follow-up command.
    try:
        state = qm.load_state()
        exempt = state.is_exempt(engine)
        released = state.is_released(engine)
        alert_paused = state.is_alert_paused(
            engine, store_id=store_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("simulate state probe raised: %s", exc)
        exempt = released = alert_paused = False

    verdict = (
        "would_be_quarantined"
        if decision.should_quarantine
        else "would_proceed"
    )

    if as_json:
        print(json.dumps({
            "engine": engine,
            "store_id": store_id,
            "verdict": verdict,
            "should_quarantine": decision.should_quarantine,
            "reason": decision.reason,
            "negative_ratio": decision.negative_ratio,
            "total_polarised": decision.total_polarised,
            "state": {
                "exempt": exempt,
                "released": released,
                "alert_paused": alert_paused,
            },
        }, indent=2, default=str))
        return

    scope = f" on store '{store_id}'" if store_id else " (fleet-wide)"
    print(f"Simulate: engine '{engine}'{scope}")
    print()
    if decision.should_quarantine:
        print(f"  Verdict: WOULD BE QUARANTINED (REJECTED)")
    else:
        print(f"  Verdict: would proceed (PENDING)")
    print(f"  Reason: {decision.reason}")
    if decision.negative_ratio is not None:
        print(
            f"  Negative ratio: {decision.negative_ratio:.2%} "
            f"({decision.total_polarised} polarised outcomes)"
        )
    print()
    print("State for this engine:")
    print(f"  exempt:       {exempt}")
    print(f"  released:     {released}")
    print(f"  alert_paused: {alert_paused}")


def _cmd_approvals_health_history(args) -> None:
    """Inspect the persistent engine_health score log.

    Each ``daily-brief`` run that successfully scored the fleet
    appends one event per engine to
    ``data/engine_health_history.json`` (or
    ``$SHOPAI_DATA_DIR/engine_health_history.json``). This
    command summarises + manages it.

    Default text view: newest-first table of recorded
    ``{engine, recorded_at, score, verdict}`` events with a
    one-line header naming the window + count. Operator
    actions: ``--clear`` nukes the log, ``--prune-older-than-days N``
    drops events older than N days.
    """
    as_json = bool(getattr(args, "json", False))

    try:
        from core.approval.engine_health_history import (
            clear, prune, recent_history,
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"engine_health_history unavailable: {exc}"
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(msg)
        sys.exit(1)
        return

    if getattr(args, "clear", False):
        try:
            clear()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "approvals health-history clear raised: %s",
                exc,
            )
        if as_json:
            print(json.dumps(
                {"status": "ok", "cleared": True},
                indent=2, default=str,
            ))
        else:
            print("Health history cleared.")
        return

    prune_days = getattr(args, "prune_older_than_days", None)
    if prune_days is not None:
        dropped = 0
        try:
            dropped = prune(
                older_than_seconds=86400.0 * float(prune_days),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "approvals health-history prune raised: %s",
                exc,
            )
        if as_json:
            print(json.dumps(
                {
                    "status": "ok",
                    "dropped": dropped,
                    "prune_older_than_days": float(prune_days),
                },
                indent=2, default=str,
            ))
        else:
            print(
                f"Pruned {dropped} event(s) older than "
                f"{prune_days} day(s)."
            )
        return

    engine = (getattr(args, "engine", None) or "").strip() or None
    since_days = float(getattr(args, "since_days", 30.0) or 30.0)
    limit = max(1, int(getattr(args, "limit", 20) or 20))

    try:
        events = recent_history(
            engine, since_seconds=86400.0 * since_days,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "approvals health-history recent_history raised: %s",
            exc,
        )
        events = []

    capped = list(events)[:limit]
    rows = [
        {
            "engine": e.engine,
            "recorded_at": float(e.recorded_at),
            "score": int(e.score),
            "verdict": e.verdict,
        }
        for e in capped
    ]

    if as_json:
        print(json.dumps({
            "engine": engine,
            "since_days": since_days,
            "limit": limit,
            "total_in_window": len(events),
            "events": rows,
        }, indent=2, default=str))
        return

    suffix = f" for {engine}" if engine else ""
    print(
        f"Engine health history{suffix} "
        f"(last {since_days:g}d, {len(events)} event(s)):"
    )
    if not rows:
        print("  (no events)")
        return
    print()
    print(
        f"  {'WHEN':<19s}  {'ENGINE':<22s}  "
        f"{'SCORE':>7s}  VERDICT"
    )
    for r in rows:
        ts = float(r["recorded_at"])
        when = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts))
            if ts > 0 else "-"
        )
        print(
            f"  {when:<19s}  {r['engine']:<22s}  "
            f"{r['score']:>2d}/10   {r['verdict']}"
        )


def _cmd_approvals_health_regressions(args) -> None:
    """Surface engines whose latest recorded health score has
    dropped sharply from their recent baseline.

    Reads ``engine_health_history.find_regressions`` with the
    operator-supplied window + threshold. Cron-friendly: exit
    code 1 when any regression is flagged so monitoring
    pipelines fail-fast.
    """
    as_json = bool(getattr(args, "json", False))
    min_drop = float(getattr(args, "min_drop", 3.0) or 3.0)
    baseline_days = float(getattr(args, "baseline_days", 7.0) or 7.0)
    latest_days = float(getattr(args, "latest_days", 1.0) or 1.0)
    min_samples = int(
        getattr(args, "min_baseline_samples", 3) or 3,
    )

    try:
        from core.approval.engine_health_history import (
            find_regressions,
        )
        regressions = find_regressions(
            min_drop=min_drop,
            baseline_window_seconds=86400.0 * baseline_days,
            latest_window_seconds=86400.0 * latest_days,
            min_baseline_samples=min_samples,
        )
    except Exception as exc:  # noqa: BLE001
        msg = (
            f"engine_health_history unavailable: {exc}"
        )
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(msg)
        sys.exit(1)
        return

    rows = [
        {
            "engine": r.engine,
            "latest_score": r.latest_score,
            "latest_verdict": r.latest_verdict,
            "baseline_score": r.baseline_score,
            "drop": r.drop,
            "samples_in_baseline": r.samples_in_baseline,
        }
        for r in regressions
    ]

    if as_json:
        print(json.dumps({
            "min_drop": min_drop,
            "baseline_days": baseline_days,
            "latest_days": latest_days,
            "min_baseline_samples": min_samples,
            "regressions": rows,
        }, indent=2, default=str))
    else:
        if not rows:
            print("No regressions flagged.")
            print(
                f"  (min_drop={min_drop} baseline={baseline_days}d "
                f"latest={latest_days}d min_samples={min_samples})"
            )
            return
        print(
            f"Health regressions ({len(rows)} engine(s)):"
        )
        print()
        for r in rows:
            print(
                f"  {r['engine']:<28s}  "
                f"baseline={r['baseline_score']:.1f}/10  "
                f"latest={r['latest_score']:>2d}/10  "
                f"drop={r['drop']:>4.1f}pts  "
                f"({r['latest_verdict']}, "
                f"n={r['samples_in_baseline']})"
            )

    if rows:
        sys.exit(1)


def _cmd_approvals_alert_history(args) -> None:
    """Inspect the persistent engine-alert firing log.

    Each ``daily-brief`` run that produces an EngineAlert
    appends an event to ``data/alert_history.json`` (or
    ``$SHOPAI_DATA_DIR/alert_history.json``). This command
    summarises it: per-engine bucket-day counts plus the
    individual firings.

    ``--clear`` is the operator escape hatch -- wipes the
    file after root-cause fix so the consecutive-day count
    resets to zero (otherwise the bridge keeps re-pausing
    the engine on the next daily-brief run).
    """
    from core.approval import alert_history

    as_json = bool(getattr(args, "json", False))

    if getattr(args, "clear", False):
        try:
            alert_history.clear()
        except Exception as exc:  # noqa: BLE001
            msg = f"clear failed: {exc}"
            if as_json:
                print(json.dumps(
                    {"status": "error", "error": msg},
                    indent=2, default=str,
                ))
            else:
                print(f"Error: {msg}")
            sys.exit(1)
            return
        if as_json:
            print(json.dumps({"status": "success", "cleared": True}))
        else:
            print("Alert history wiped.")
        return

    prune_days = getattr(args, "prune_older_than_days", None)
    if prune_days is not None:
        if prune_days <= 0:
            msg = "--prune-older-than-days must be positive"
            if as_json:
                print(json.dumps(
                    {"status": "error", "error": msg},
                    indent=2, default=str,
                ))
            else:
                print(f"Error: {msg}")
            sys.exit(1)
            return
        try:
            removed = alert_history.prune(
                older_than_seconds=prune_days * 86400.0,
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"prune failed: {exc}"
            if as_json:
                print(json.dumps(
                    {"status": "error", "error": msg},
                    indent=2, default=str,
                ))
            else:
                print(f"Error: {msg}")
            sys.exit(1)
            return
        if as_json:
            print(json.dumps({
                "status": "success",
                "removed_count": removed,
                "older_than_days": prune_days,
            }))
        else:
            print(
                f"Pruned {removed} event(s) older than "
                f"{prune_days:.1f} day(s)."
            )
        return

    since_days = max(0.0, float(getattr(args, "since_days", 7.0)))
    engine_filter = getattr(args, "engine", None)
    store_filter = getattr(args, "store", None)
    include_fleet = bool(getattr(args, "include_fleet", False))

    try:
        if store_filter is not None and include_fleet:
            # Two queries: store-scoped + fleet (None). Merge.
            scoped = alert_history.recent_history(
                since_seconds=since_days * 86400.0,
                store_id=store_filter,
            )
            fleet = [
                e for e in alert_history.recent_history(
                    since_seconds=since_days * 86400.0,
                )
                if e.store_id is None
            ]
            events = sorted(
                scoped + fleet,
                key=lambda e: -e.recorded_at,
            )
            consecutive_scoped = (
                alert_history.consecutive_runs_per_engine(
                    window_seconds=since_days * 86400.0,
                    store_id=store_filter,
                )
            )
            # Fleet None bucket: pass store_id=None won't work
            # (the filter is strict). Approximate via the
            # per-pair table.
            per_pair = (
                alert_history
                .consecutive_runs_per_engine_store(
                    window_seconds=since_days * 86400.0,
                )
            )
            consecutive = dict(consecutive_scoped)
            for (engine, sid), days in per_pair.items():
                if sid is None:
                    # Combine fleet days into the per-store
                    # number for this engine.
                    consecutive[engine] = max(
                        consecutive.get(engine, 0), days,
                    )
        elif store_filter is not None:
            events = alert_history.recent_history(
                since_seconds=since_days * 86400.0,
                store_id=store_filter,
            )
            consecutive = (
                alert_history.consecutive_runs_per_engine(
                    window_seconds=since_days * 86400.0,
                    store_id=store_filter,
                )
            )
        else:
            events = alert_history.recent_history(
                since_seconds=since_days * 86400.0,
            )
            consecutive = (
                alert_history.consecutive_runs_per_engine(
                    window_seconds=since_days * 86400.0,
                )
            )
    except Exception as exc:  # noqa: BLE001
        msg = f"read failed: {exc}"
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"Error: {msg}")
        sys.exit(1)
        return

    if engine_filter:
        events = [e for e in events if e.engine == engine_filter]
        consecutive = {
            k: v for k, v in consecutive.items()
            if k == engine_filter
        }

    if as_json:
        payload = {
            "since_days": since_days,
            "engine": engine_filter,
            "store": store_filter,
            "include_fleet": include_fleet,
            "event_count": len(events),
            "consecutive_days_by_engine": consecutive,
            "events": [
                {
                    "engine": e.engine,
                    "store_id": e.store_id,
                    "recorded_at": e.recorded_at,
                    "drop": e.drop,
                    "recent_score": e.recent_score,
                    "baseline_score": e.baseline_score,
                }
                for e in events
            ],
        }
        print(json.dumps(payload, indent=2, default=str))
        return

    if not events:
        scope = (
            f" (store={store_filter})" if store_filter else ""
        )
        print(
            f"No alert firings in the last "
            f"{since_days:.1f} day(s){scope}"
            + (f" for engine '{engine_filter}'." if engine_filter
               else ".")
        )
        return

    scope_str = (
        f", store={store_filter}"
        + (" + fleet" if include_fleet else "")
        if store_filter else ""
    )
    print(
        f"Alert history (last {since_days:.1f} day(s)"
        f"{scope_str}, {len(events)} event(s))"
    )
    print()
    if consecutive:
        print("Per-engine bucket-day count:")
        for engine, days in sorted(
            consecutive.items(), key=lambda kv: -kv[1],
        ):
            print(f"  {engine:25s} {days:3d} day(s)")
        print()
    print("Recent events (newest first):")
    for e in events[:50]:
        age = time.time() - e.recorded_at
        ago = (
            f"{int(age)}s ago" if age < 60
            else f"{int(age/60)}m ago" if age < 3600
            else f"{int(age/3600)}h ago" if age < 86400
            else f"{int(age/86400)}d ago"
        )
        store_label = (
            f" @{e.store_id}" if e.store_id else " (fleet)"
        )
        print(
            f"  [{ago:>8s}] {e.engine:22s}{store_label:12s} "
            f"drop={e.drop:.2f} recent={e.recent_score:.2f} "
            f"baseline={e.baseline_score:.2f}"
        )


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


def _cmd_approvals_alert_release_candidates(args) -> None:
    """List alert-paused engines whose alerts have gone quiet.

    Sister to ``quarantine-release-candidates`` (which is
    outcome-based). This one is alert-based: an operator
    looking at the alert_paused set wants to know which
    engines haven't fired any new degradation alerts recently
    and are safe to release.

    ``--quiet-days`` controls the silence window; defaults to
    the bridge's window-days (so an engine that hasn't fired
    in the entire detection window is a candidate).
    """
    from core.approval import alert_quarantine

    quiet_days = getattr(args, "quiet_days", None)
    try:
        candidates = alert_quarantine.find_release_candidates(
            quiet_days=quiet_days,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "alert release candidate scan failed: %s", exc,
        )
        candidates = []

    if getattr(args, "json", False):
        print(json.dumps(candidates, indent=2, default=str))
        return

    if not candidates:
        print(
            "No alert-release candidates "
            "(every alert-paused engine has fired recently, "
            "or none are paused)."
        )
        return

    effective_quiet = (
        quiet_days if quiet_days is not None
        else alert_quarantine.window_days()
    )
    print(
        f"Alert-release candidates ({len(candidates)}) "
        f"-- quiet for >= {effective_quiet} day(s):"
    )
    print(
        "  engine                          days_quiet"
    )
    for c in candidates:
        engine = c["engine"][:30]
        days = c["days_since_last_alert"]
        days_str = (
            f"{days:>10.1f}" if days is not None
            else "       n/a"
        )
        print(f"  {engine:<30}  {days_str}")
    print()
    print(
        "Release with: shopai approvals quarantine "
        "--release-alert <engine>"
    )


def _cmd_approvals_alert_pause_candidates(args) -> None:
    """Dry-run preview of the alert-quarantine bridge.

    The bridge (``core.approval.alert_quarantine``) auto-adds
    engines to ``alert_paused`` when they've fired degradation
    alerts on N consecutive days. This command shows what WOULD
    happen if the bridge ran right now -- regardless of whether
    the ``SHOPAI_AUTO_QUARANTINE_FROM_ALERTS`` env var is set.

    Operators use this to:
      - Preview the bridge's effect before enabling it
      - Audit "why hasn't engine X been paused?" -- the
        ``blocked_by`` field shows exempt / already_paused
    """
    from core.approval import alert_quarantine

    threshold = getattr(args, "threshold", None)
    window_days = getattr(args, "window_days", None)
    per_store = bool(getattr(args, "per_store", False))
    window_seconds = (
        window_days * 86400.0 if window_days is not None else None
    )

    try:
        if per_store:
            candidates = (
                alert_quarantine.find_pause_candidates_per_store(
                    threshold=threshold,
                    window_seconds=window_seconds,
                )
            )
        else:
            candidates = alert_quarantine.find_pause_candidates(
                threshold=threshold,
                window_seconds=window_seconds,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "alert pause candidate scan failed: %s", exc,
        )
        candidates = []

    effective_threshold = (
        threshold if threshold is not None
        else alert_quarantine.threshold_days()
    )
    effective_window = (
        window_days if window_days is not None
        else alert_quarantine.window_days()
    )
    enabled = alert_quarantine.is_enabled()

    if getattr(args, "json", False):
        payload = {
            "bridge_enabled": enabled,
            "threshold_days": effective_threshold,
            "window_days": effective_window,
            "per_store": per_store,
            "candidates": candidates,
        }
        print(json.dumps(payload, indent=2, default=str))
        return

    suffix = " (per-store)" if per_store else ""
    print(
        f"Alert-pause candidates{suffix} "
        f"(threshold={effective_threshold}d, "
        f"window={effective_window}d, "
        f"bridge={'on' if enabled else 'off'}):"
    )
    if not candidates:
        print(
            "  (no engines at or above the streak threshold)"
        )
        return
    if per_store:
        print(
            "  engine                  store_id              "
            "days  blocked_by"
        )
        for c in candidates:
            engine = c["engine"][:22]
            store = (c.get("store_id") or "(fleet)")[:20]
            days = c["consecutive_days"]
            blocked = c.get("blocked_by") or "-"
            print(
                f"  {engine:<22}  {store:<20}  "
                f"{days:>3}d  {blocked}"
            )
    else:
        print(
            "  engine                          days  blocked_by"
        )
        for c in candidates:
            engine = c["engine"][:30]
            days = c["consecutive_days"]
            blocked = c.get("blocked_by") or "-"
            print(f"  {engine:<30}  {days:>3}d  {blocked}")
    print()
    if not enabled:
        print(
            "Bridge is OFF. Set "
            "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS=1 to enable "
            "auto-pause on the next daily-brief run."
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

    # Append a quarantine-state summary so this one-glance
    # command also tells the operator how many engines are
    # paused / exempt / released. Only print the line when
    # there's something non-zero to report.
    try:
        from core.approval import quarantine as qm
        qstate = qm.load_state()
        ex = len(qstate.exemptions)
        rel = len(qstate.released)
        paused = len(qstate.alert_paused)
        if ex or rel or paused:
            print()
            print(
                f"Quarantine: exempt={ex} released={rel} "
                f"alert_paused={paused}"
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "approvals stats quarantine probe raised: %s", exc,
        )


def _collect_approvals_doctor_sections(args) -> tuple[bool, dict[str, Any]]:
    """Collect every approvals-doctor section without rendering.

    Returns ``(overall_ok, sections_dict)``. ``overall_ok`` flips
    False when any FATAL section fails (dispatcher coverage gap,
    stale-pending overage, high failure rate). Informational
    sections (auto-approve coverage, quarantine list) never flip
    it to False.
    """
    import time
    sections: dict[str, Any] = {}
    overall_ok = True

    stale_hours = float(getattr(args, "stale_pending_hours", 24.0))
    fail_rate_warn = float(getattr(args, "failure_rate_warn", 0.25))

    # ── Pattern K dispatcher coverage (reuse existing audit) ─
    try:
        from core.approval.coverage_audit import audit_coverage
        from pathlib import Path
        report = audit_coverage(Path("engines"))
        sections["pattern_k_dispatchers"] = {
            "status": "pass" if not report.has_gaps else "fail",
            "enqueue_sites": len(report.enqueued),
            "dispatchers_registered": len(report.registered),
            "missing": sorted(report.missing),
            "orphaned": sorted(report.orphaned),
        }
        if report.has_gaps:
            overall_ok = False
    except Exception as exc:  # noqa: BLE001
        logger.debug("pattern K probe raised: %s", exc)
        sections["pattern_k_dispatchers"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    # ── Pending queue depth + stale pending ──────────────────
    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
        pending = queue.list_pending(limit=1000)
        now = time.time()
        ages_s = [
            now - p.proposed_at
            for p in pending
            if p.proposed_at is not None
        ]
        stale_threshold_s = stale_hours * 3600.0
        stale = [a for a in ages_s if a >= stale_threshold_s]
        oldest_s = max(ages_s) if ages_s else 0.0
        status = "pass"
        if stale:
            status = "fail"
            overall_ok = False
        sections["pending_queue"] = {
            "status": status,
            "pending_count": len(pending),
            "stale_threshold_hours": stale_hours,
            "stale_count": len(stale),
            "oldest_age_hours": round(oldest_s / 3600.0, 2),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("pending queue probe raised: %s", exc)
        sections["pending_queue"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    # ── Recent dispatch failure rate ─────────────────────────
    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
        stats = queue.stats()
        executed = int(stats.get("executed", 0))
        failed = int(stats.get("failed", 0))
        decided = executed + failed
        rate = (failed / decided) if decided > 0 else 0.0
        status = "pass"
        if decided >= 5 and rate >= fail_rate_warn:
            status = "warn"
            # Informational/warning — does NOT flip overall_ok
            # (failures can be from upstream Shopify issues, not
            # a queue health bug — operators decide the action).
        sections["recent_dispatch"] = {
            "status": status,
            "executed_count": executed,
            "failed_count": failed,
            "decided_count": decided,
            "failure_rate": round(rate, 3),
            "warn_threshold": fail_rate_warn,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("dispatch stats probe raised: %s", exc)
        sections["recent_dispatch"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    # ── Quarantine state ─────────────────────────────────────
    # The quarantine module stores operator state (exemptions +
    # manual releases); the "currently quarantined" set is computed
    # dynamically from outcome stats. The doctor surfaces the
    # operator-managed state so it's a 1-line readout.
    try:
        from core.approval.quarantine import load_state
        qstate = load_state()
        sections["quarantine"] = {
            "status": "info",
            "exemptions_count": len(qstate.exemptions),
            "exemptions": sorted(qstate.exemptions),
            "released_count": len(qstate.released),
            "released": sorted(qstate.released),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("quarantine probe raised: %s", exc)
        sections["quarantine"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    # ── Auto-approve coverage (informational) ────────────────
    try:
        from core.approval.auto_approve import load_config
        cfg = load_config()
        allowed = list(cfg.allowlist)
        sections["auto_approve"] = {
            "status": "info",
            "allowlist_count": len(allowed),
            "allowlist": sorted(allowed),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("auto-approve probe raised: %s", exc)
        sections["auto_approve"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    # ── Alert history (informational + warn on long streaks) ─
    # Counts engine-degradation alert firings persisted by
    # ``alert_history`` over the last 7 days, plus per-engine
    # consecutive-day counts. Warns when an engine has fired
    # on 3+ distinct days -- that's the threshold the future
    # alert_quarantine bridge would auto-pause at.
    try:
        from core.approval import alert_history
        events = alert_history.recent_history(
            since_seconds=86400.0 * 7.0,
        )
        consecutive = alert_history.consecutive_runs_per_engine(
            window_seconds=86400.0 * 7.0,
        )
        long_streak = {
            e: d for e, d in consecutive.items() if d >= 3
        }
        status = "warn" if long_streak else "info"
        sections["alert_history"] = {
            "status": status,
            "event_count_7d": len(events),
            "engines_with_alerts": sorted(consecutive),
            "consecutive_days_by_engine": consecutive,
            "long_streak_engines": long_streak,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("alert_history probe raised: %s", exc)
        sections["alert_history"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    return overall_ok, sections


def _cmd_approvals_doctor(args) -> None:
    """Aggregate approval-queue health check.

    Combines five existing audits into one shot:

      1. Pattern K dispatcher coverage (reuses `approvals audit`)
      2. Pending queue depth + stale-pending detection
      3. Recent dispatch failure rate (executed vs failed)
      4. Quarantine list (failed engines auto-paused)
      5. Auto-approve allowlist coverage (informational)

    Fatal sections fail the doctor (exit 1): Pattern K gap,
    stale pending. Warning sections don't fail it: high failure
    rate, non-empty quarantine. Informational sections never
    fail.
    """
    overall_ok, sections = _collect_approvals_doctor_sections(args)

    if getattr(args, "json", False):
        print(json.dumps({
            "ok": overall_ok,
            "sections": sections,
        }, indent=2, default=str))
        if not overall_ok:
            sys.exit(1)
        return

    print("ShopAI Approvals Doctor")
    print()

    _approvals_doctor_render_pattern_k(
        sections.get("pattern_k_dispatchers", {}),
    )
    _approvals_doctor_render_pending(
        sections.get("pending_queue", {}),
    )
    _approvals_doctor_render_dispatch(
        sections.get("recent_dispatch", {}),
    )
    _approvals_doctor_render_quarantine(
        sections.get("quarantine", {}),
    )
    _approvals_doctor_render_auto_approve(
        sections.get("auto_approve", {}),
    )
    _approvals_doctor_render_alert_history(
        sections.get("alert_history", {}),
    )

    print()
    if overall_ok:
        print(
            "Overall: OK -- approval queue health checks pass."
        )
    else:
        print(
            "Overall: FAILED -- at least one fatal check has gaps. "
            "Inspect sections above."
        )
        sys.exit(1)


def _approvals_doctor_render_pattern_k(section: dict) -> None:
    status = section.get("status", "unavailable")
    if status == "pass":
        print(
            f"[pass] Pattern K dispatchers -- "
            f"{section.get('enqueue_sites', 0)} enqueue sites, "
            f"{section.get('dispatchers_registered', 0)} dispatchers"
        )
    elif status == "fail":
        missing = section.get("missing", [])
        print(
            f"[FAIL] Pattern K dispatchers -- "
            f"{len(missing)} missing: "
            f"{', '.join(missing[:3])}"
            f"{'...' if len(missing) > 3 else ''}"
        )
        print(
            "       fix: register a dispatcher for each missing "
            "action_type in core/approval/dispatchers.py"
        )
    else:
        print(
            f"[??] Pattern K dispatchers -- "
            f"{section.get('error', 'unavailable')}"
        )


def _approvals_doctor_render_pending(section: dict) -> None:
    status = section.get("status", "unavailable")
    if status == "pass":
        print(
            f"[pass] Pending queue -- "
            f"{section.get('pending_count', 0)} pending, "
            f"oldest {section.get('oldest_age_hours', 0)}h "
            f"(threshold {section.get('stale_threshold_hours', 24)}h)"
        )
    elif status == "fail":
        print(
            f"[FAIL] Pending queue -- "
            f"{section.get('stale_count', 0)} action(s) older than "
            f"{section.get('stale_threshold_hours', 24)}h, "
            f"oldest {section.get('oldest_age_hours', 0)}h"
        )
        print(
            "       fix: triage stale actions via `shopai approvals "
            "pending`, decide / sweep / expire; long pending ages "
            "stall the autonomous loop"
        )
    else:
        print(
            f"[??] Pending queue -- "
            f"{section.get('error', 'unavailable')}"
        )


def _approvals_doctor_render_dispatch(section: dict) -> None:
    status = section.get("status", "unavailable")
    if status == "pass":
        decided = section.get("decided_count", 0)
        rate = section.get("failure_rate", 0.0)
        if decided == 0:
            print(
                "[pass] Recent dispatch -- no decided actions yet"
            )
        else:
            print(
                f"[pass] Recent dispatch -- "
                f"{section.get('executed_count', 0)}/"
                f"{decided} executed "
                f"(failure rate {rate * 100:.1f}%)"
            )
    elif status == "warn":
        rate = section.get("failure_rate", 0.0)
        warn = section.get("warn_threshold", 0.25)
        print(
            f"[WARN] Recent dispatch -- "
            f"{section.get('failed_count', 0)}/"
            f"{section.get('decided_count', 0)} failed "
            f"(rate {rate * 100:.1f}% >= warn {warn * 100:.0f}%)"
        )
        print(
            "       investigate: `shopai approvals recent failed`"
            " -- common causes are adapter scope drift or upstream"
            " Shopify errors, not a queue bug"
        )
    else:
        print(
            f"[??] Recent dispatch -- "
            f"{section.get('error', 'unavailable')}"
        )


def _approvals_doctor_render_quarantine(section: dict) -> None:
    status = section.get("status", "unavailable")
    if status == "info":
        ex = section.get("exemptions_count", 0)
        rel = section.get("released_count", 0)
        if ex == 0 and rel == 0:
            print(
                "[info] Quarantine -- no exemptions, "
                "no manual releases"
            )
        else:
            print(
                f"[info] Quarantine -- "
                f"{ex} exemption(s), "
                f"{rel} manual release(s)"
            )
    else:
        print(
            f"[??] Quarantine -- "
            f"{section.get('error', 'unavailable')}"
        )


def _approvals_doctor_render_auto_approve(section: dict) -> None:
    status = section.get("status", "unavailable")
    if status == "info":
        count = section.get("allowlist_count", 0)
        if count == 0:
            print(
                "[info] Auto-approve -- empty allowlist "
                "(every action requires human review)"
            )
        else:
            allowed = section.get("allowlist", [])
            print(
                f"[info] Auto-approve -- "
                f"{count} engine(s) on allowlist: "
                f"{', '.join(allowed[:3])}"
                f"{'...' if len(allowed) > 3 else ''}"
            )
    else:
        print(
            f"[??] Auto-approve -- "
            f"{section.get('error', 'unavailable')}"
        )


def _approvals_doctor_render_alert_history(section: dict) -> None:
    status = section.get("status", "unavailable")
    if status == "info":
        count = section.get("event_count_7d", 0)
        engines = section.get("engines_with_alerts", [])
        if count == 0:
            print(
                "[info] Alert history -- no engine degradation "
                "alerts in the last 7 days"
            )
        else:
            print(
                f"[info] Alert history -- {count} firing(s) "
                f"across {len(engines)} engine(s) in last 7 days"
            )
        return
    if status == "warn":
        long_streak = section.get("long_streak_engines", {})
        if long_streak:
            top = sorted(
                long_streak.items(), key=lambda kv: -kv[1],
            )[:3]
            descr = ", ".join(
                f"{e}={d}d" for e, d in top
            )
            print(
                f"[warn] Alert history -- "
                f"{len(long_streak)} engine(s) on 3+ day streak: "
                f"{descr}"
            )
        return
    print(
        f"[??] Alert history -- "
        f"{section.get('error', 'unavailable')}"
    )


def _trace_action(action_id: str) -> dict[str, Any]:
    """Build a dry-run trace of what executing ``action_id`` would
    do, WITHOUT making any side-effecting call.

    Returns a structured dict with:
      - action: id + engine + action_type + capability + status
        + narrative + confidence
      - dispatcher: whether one is registered + its module/name
      - adapter: which Shopify adapter would claim the capability
        + its declared required_scopes
      - params: the parked friendly-form params dict
      - issues: any problems detected (not approved, no
        dispatcher, no adapter, missing required keys)

    The CLI render and the JSON envelope share this builder so
    they stay consistent.
    """
    out: dict[str, Any] = {
        "ok": True,
        "issues": [],
    }
    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["issues"].append(f"queue_unavailable: {exc}")
        return out

    action = queue.get(action_id)
    if action is None:
        out["ok"] = False
        out["issues"].append("unknown_action_id")
        return out

    out["action"] = {
        "id": action.id,
        "engine": action.engine,
        "action_type": action.action_type,
        "capability": action.capability,
        "status": action.status.value,
        "narrative": action.narrative,
        "confidence": action.confidence,
    }
    out["params"] = action.params

    if action.status.value not in {"pending", "approved"}:
        out["issues"].append(
            f"already_resolved: status={action.status.value} "
            "(trace shows what would have happened)"
        )

    # ── Dispatcher lookup ────────────────────────────────────
    try:
        # Trigger lazy load so the registry is populated
        from core.approval.executor import (
            _DISPATCHERS,
            _ensure_dispatchers_loaded,
        )
        _ensure_dispatchers_loaded()
        fn = _DISPATCHERS.get(action.action_type)
        if fn is None:
            out["issues"].append(
                f"no_dispatcher_registered: action_type="
                f"{action.action_type}"
            )
            out["dispatcher"] = None
        else:
            out["dispatcher"] = {
                "registered": True,
                "module": getattr(fn, "__module__", "?"),
                "qualname": getattr(fn, "__qualname__", "?"),
            }
    except Exception as exc:  # noqa: BLE001
        out["issues"].append(f"dispatcher_lookup_failed: {exc}")
        out["dispatcher"] = None

    # ── Adapter / scope lookup ───────────────────────────────
    cap_name = action.capability
    try:
        from core.adapters.shopify import bootstrap
        adapters_claiming = []
        all_scopes: set[str] = set()
        for cls in bootstrap._SHOPIFY_ADAPTER_CLASSES:
            for cap in getattr(cls, "capabilities", set()):
                name = getattr(cap, "name", None) or str(cap)
                if name == cap_name:
                    scopes = sorted(
                        getattr(cls, "required_scopes", frozenset()),
                    )
                    adapters_claiming.append({
                        "name": getattr(cls, "name", cls.__name__),
                        "module": cls.__module__,
                        "required_scopes": scopes,
                        "scope_independent": bool(
                            getattr(cls, "scope_independent", False),
                        ),
                    })
                    all_scopes.update(scopes)
                    break
        out["adapters"] = adapters_claiming
        out["aggregate_required_scopes"] = sorted(all_scopes)
        if not adapters_claiming:
            out["issues"].append(
                f"no_adapter_claims: capability={cap_name}"
            )
    except Exception as exc:  # noqa: BLE001
        out["issues"].append(f"adapter_lookup_failed: {exc}")
        out["adapters"] = []
        out["aggregate_required_scopes"] = []

    if out["issues"]:
        # Anything in issues warrants attention; ok stays True
        # unless the trace itself couldn't render at all.
        pass

    return out


def _cmd_approvals_trace(args) -> None:
    """Dry-run inspection of an approval action.

    Shows what executing ``action_id`` would do — dispatcher,
    adapter, scopes, params — WITHOUT making any external call.
    Useful before pushing the button on a high-stakes action
    (price changes, product archives, gift-card mints).
    """
    trace = _trace_action(args.action_id)

    if getattr(args, "json", False):
        print(json.dumps(trace, indent=2, default=str))
        if not trace.get("ok", False) or trace.get("issues"):
            # Issues are advisory but useful as a non-zero
            # exit so scripts can detect "would-fail" cases.
            sys.exit(1 if not trace.get("ok", False) else 0)
        return

    if not trace.get("ok", True) or "action" not in trace:
        for issue in trace.get("issues", []):
            print(f"[error] {issue}")
        sys.exit(1)

    a = trace["action"]
    print(f"Action {a['id']}")
    print(f"  engine:        {a['engine']}")
    print(f"  action_type:   {a['action_type']}")
    print(f"  capability:    {a['capability']}")
    print(f"  status:        {a['status']}")
    if a.get("narrative"):
        print(f"  narrative:     {a['narrative']}")
    if a.get("confidence") is not None:
        print(f"  confidence:    {a['confidence']:.2f}")
    print()

    disp = trace.get("dispatcher")
    if disp:
        print(
            f"  dispatcher:    registered "
            f"({disp.get('module', '?')}.{disp.get('qualname', '?')})"
        )
    else:
        print("  dispatcher:    NOT REGISTERED")

    adapters = trace.get("adapters", [])
    if adapters:
        print(f"  routes to:")
        for ad in adapters:
            scope_str = (
                ", ".join(ad["required_scopes"])
                if ad["required_scopes"]
                else (
                    "(scope-independent)" if ad["scope_independent"]
                    else "(no scopes declared)"
                )
            )
            print(
                f"    {ad['name']} ({ad['module']})"
            )
            print(f"      scopes:   {scope_str}")
        agg = trace.get("aggregate_required_scopes", [])
        if agg:
            print(f"  aggregate scopes: {', '.join(agg)}")
    else:
        print(f"  routes to:     NO ADAPTER CLAIMS {a['capability']}")

    params = trace.get("params", {})
    if params:
        print()
        print("  params:")
        for k, v in params.items():
            # Compact rendering — pull strings out
            v_str = repr(v) if isinstance(v, (list, dict)) else v
            print(f"    {k:<24} {v_str}")

    issues = trace.get("issues", [])
    if issues:
        print()
        print("  Issues:")
        for i in issues:
            print(f"    - {i}")

    print()
    print(
        "  No side effects executed. "
        f"Run `shopai approvals execute {a['id']}` to apply."
    )

    # Exit 1 if any issues were detected so scripts can gate on
    # a clean trace.
    if issues:
        sys.exit(1)


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

    # Engine quarantine state -- attaches flags so an operator
    # triaging this action sees if the engine is currently
    # paused/exempt/released. Cheap state-file read.
    try:
        from core.approval import quarantine as qm
        qstate = qm.load_state()
        engine = action.engine
        flags: list[str] = []
        if qstate.is_exempt(engine):
            flags.append("exempt")
        if qstate.is_released(engine):
            flags.append("released")
        if qstate.is_alert_paused(engine):
            flags.append("alert_paused")
        payload["engine_quarantine_flags"] = flags
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "approvals show quarantine probe raised: %s", exc,
        )
        payload["engine_quarantine_flags"] = []

    # Recent alerts for THIS engine -- mirrors the field added
    # to ``engine summary`` so operators get the same trajectory
    # signal regardless of which command they came in through.
    # Newest-first within the 7-day window, capped at 5.
    try:
        from core.approval import alert_history
        recent_alerts: list[dict] = []
        for e in alert_history.recent_history(
            since_seconds=86400.0 * 7.0,
        ):
            if e.engine != action.engine:
                continue
            recent_alerts.append({
                "recorded_at": float(
                    getattr(e, "recorded_at", 0.0) or 0.0,
                ),
                "drop": float(getattr(e, "drop", 0.0) or 0.0),
                "recent_score": float(
                    getattr(e, "recent_score", 0.0) or 0.0,
                ),
                "baseline_score": float(
                    getattr(e, "baseline_score", 0.0) or 0.0,
                ),
                "store_id": getattr(e, "store_id", None),
            })
            if len(recent_alerts) >= 5:
                break
        payload["engine_recent_alerts"] = recent_alerts
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "approvals show alert_history probe raised: %s", exc,
        )
        payload["engine_recent_alerts"] = []

    # AGI decision-retrieval context (opt-in via --with-context).
    # When operator is triaging a PENDING action, the top-k
    # similar past decisions + their outcome rollup answers
    # "how did similar past actions turn out?" -- the cheapest
    # decision-support signal we can surface.
    if getattr(args, "with_context", False):
        try:
            from core.decision_retrieval import DecisionRetrieval
            k = int(getattr(args, "context_k", 3) or 3)
            similar = DecisionRetrieval().retrieve(
                engine=action.engine,
                action_type=action.action_type,
                capability=action.capability,
                params=action.params,
                k=k,
            )
            payload["agi_context"] = {
                "k": k,
                "similar": similar,
                "summary": _summarize_context(similar),
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("agi_context lookup failed: %s", exc)
            payload["agi_context"] = {"error": str(exc)}

    print(json.dumps(payload, indent=2, default=str))


def _summarize_context(similar: list[dict]) -> dict:
    """Flat-summary rollup of a decision-retrieval result list.

    Mirrors the shape ``engines._agi_context._summarize_similar``
    produces, but kept here as a thin wrapper so this handler
    doesn't introduce a CLI -> engines/* dependency.
    """
    if not similar:
        return {
            "similar_count": 0,
            "recent_positive": False,
            "recent_negative": False,
            "avg_relevance": 0.0,
            "total_revenue": 0.0,
        }
    total_relevance = 0.0
    has_pos = has_neg = False
    total_revenue = 0.0
    for entry in similar:
        total_relevance += float(entry.get("relevance", 0.0) or 0.0)
        summary = entry.get("outcome_summary") or {}
        if summary.get("has_positive"):
            has_pos = True
        if summary.get("has_negative"):
            has_neg = True
        total_revenue += float(summary.get("total_revenue", 0.0) or 0.0)
    return {
        "similar_count": len(similar),
        "recent_positive": has_pos,
        "recent_negative": has_neg,
        "avg_relevance": round(total_relevance / len(similar), 4),
        "total_revenue": round(total_revenue, 2),
    }


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

    # Warn the operator if the engine is currently quarantined.
    # Approving doesn't bypass the rejection -- it transitions
    # the action to APPROVED, but subsequent enqueues would
    # still be rejected. More importantly, an operator manually
    # approving an action whose engine they themselves
    # quarantined recently may not realise the state is
    # inconsistent.
    try:
        from core.approval import quarantine as qm
        qstate = qm.load_state()
        flags: list[str] = []
        if qstate.is_alert_paused(action.engine):
            flags.append("alert_paused")
        if qstate.is_exempt(action.engine):
            flags.append("exempt")
        if qstate.is_released(action.engine):
            flags.append("released")
        if flags:
            print(
                f"  Warning: engine '{action.engine}' is "
                f"currently in quarantine state "
                f"[{','.join(flags)}]. New enqueues for this "
                f"engine will be auto-rejected; manage via "
                f"'shopai approvals quarantine'."
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "approvals approve quarantine probe raised: %s", exc,
        )

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

    # Quarantine state probe once -- shared across the row loop.
    qstate = None
    try:
        from core.approval import quarantine as qm
        qstate = qm.load_state()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "approvals recent quarantine probe raised: %s", exc,
        )

    def _engine_quarantine_marker(engine: str) -> str:
        if qstate is None:
            return ""
        flags: list[str] = []
        if qstate.is_alert_paused(engine):
            flags.append("alert_paused")
        if qstate.is_exempt(engine):
            flags.append("exempt")
        if qstate.is_released(engine):
            flags.append("released")
        return f"  [{','.join(flags)}]" if flags else ""

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
        line += _engine_quarantine_marker(a.engine)
        print(line)


def _cmd_approvals_outcome(args) -> None:
    """Manually record an outcome on an executed action.

    Use cases:
      - Shopify webhooks missed an event and the action's
        learning signal is incomplete.
      - Retroactive correction (operator marks an action as
        positive/negative after observing real-world impact).
      - Manual override during operator-driven testing.

    Writes a row to ``action_outcomes`` via the canonical
    ``queue.record_outcome(...)`` API -- same path as the
    webhook-driven recorder, so the AGI signal flows through
    ``DecisionRetrieval`` + ``MemoryIntelligence`` identically.
    """
    as_json = bool(getattr(args, "json", False))
    action_id = args.action_id
    polarity = args.polarity
    revenue = float(getattr(args, "revenue", 0.0) or 0.0)
    topic = (getattr(args, "topic", "manual") or "manual").strip()
    source_event = (
        getattr(args, "source_event", "operator") or "operator"
    ).strip()

    def _emit_error(msg: str) -> None:
        if as_json:
            print(json.dumps(
                {"status": "error", "error": msg},
                indent=2, default=str,
            ))
        else:
            print(f"Error: {msg}")
        sys.exit(1)

    try:
        from core.approval.queue import get_approval_queue
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"approval queue unavailable: {exc}")
        return

    queue = get_approval_queue()

    # Verify the action exists before recording the outcome --
    # ``record_outcome`` silently no-ops on unknown ids, which
    # makes operator typos invisible. The CLI surface should
    # surface them.
    try:
        action = queue.get(action_id)
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"action lookup failed: {exc}")
        return

    if action is None:
        _emit_error(f"action {action_id!r} not found")
        return

    metrics = {}
    if revenue != 0.0:
        metrics["revenue"] = revenue
    metrics["manually_recorded"] = True

    try:
        recorded = queue.record_outcome(
            action_id,
            topic=topic,
            polarity=polarity,
            metrics=metrics,
            source_event=source_event,
        )
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"record_outcome failed: {exc}")
        return

    if not recorded:
        _emit_error(
            f"queue.record_outcome returned falsy for {action_id!r} "
            "(action may not be executed yet)"
        )
        return

    envelope = {
        "status": "ok",
        "action_id": action_id,
        "engine": getattr(action, "engine", None),
        "action_type": getattr(action, "action_type", None),
        "polarity": polarity,
        "topic": topic,
        "source_event": source_event,
        "metrics": metrics,
    }

    if as_json:
        print(json.dumps(envelope, indent=2, default=str))
        return

    print(f"Outcome recorded on {action_id}")
    print(
        f"  {action.engine}/{action.action_type}  "
        f"polarity={polarity}  topic={topic}"
    )
    if revenue:
        print(f"  revenue=${revenue:.2f}")
    print(f"  source_event={source_event}")


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
            "design": _cmd_store_design,
            "verify": _cmd_store_verify,
            "setup": _cmd_store_setup,
            "report": _cmd_store_report,
            "fleet": _cmd_store_fleet,
        }
        handler = dispatch.get(args.store_action)
        if handler:
            handler(args)
        else:
            print(
                "Usage: shopai store "
                "{add|list|switch|status|connect|remove|configure|design|verify|setup|report|fleet}"
            )
        return

    if args.command == "daily-brief":
        _cmd_daily_brief(args)
        return

    if args.command == "transfer":
        _cmd_transfer(args)
        return

    if args.command == "world-model":
        action = getattr(args, "world_action", None)
        if action == "show":
            _cmd_world_model_show(args)
            return
        if action == "fleet":
            _cmd_world_model_fleet(args)
            return
        print("Usage: shopai world-model {show|fleet}")
        return

    if args.command == "memory-recall":
        _cmd_memory_recall(args)
        return

    if args.command == "model-router":
        _cmd_model_router(args)
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

    if args.command == "engine":
        action = getattr(args, "engine_action", None)
        if action == "summary":
            _cmd_engine_summary(args)
            return
        if action == "guardrail":
            _cmd_engine_guardrail(args)
            return
        if action == "fleet":
            _cmd_engine_fleet(args)
            return
        if action == "compare":
            _cmd_engine_compare(args)
            return
        if action == "ranking":
            _cmd_engine_ranking(args)
            return
        if action == "alerts":
            _cmd_engine_alerts(args)
            return
        if action == "pulse":
            _cmd_engine_pulse(args)
            return
        print(
            "Usage: shopai engine "
            "{summary|guardrail|fleet|compare|ranking|alerts|pulse}"
        )
        return

    if args.command == "engines-writebacks":
        _cmd_engines_writebacks(args)
        return

    if args.command == "engines-stats":
        _cmd_engines_stats(args)
        return

    if args.command == "catalog":
        _cmd_catalog(args)
        return

    if args.command == "learning":
        _cmd_learning(args)
        return

    if args.command == "release-bundle":
        _cmd_release_bundle(args)
        return

    if args.command == "snapshot":
        _cmd_snapshot(args)
        return

    if args.command == "engine-info":
        _cmd_engine_info(
            args.engine_name,
            as_json=getattr(args, "json", False),
        )
        return

    if args.command == "shopify-scopes":
        _cmd_shopify_scopes(args)
        return

    if args.command == "shopify-scopes-audit":
        _cmd_shopify_scopes_audit(args)
        return

    if args.command == "capabilities-audit":
        _cmd_capabilities_audit(args)
        return

    if args.command == "engines-capability-audit":
        _cmd_engines_capability_audit(args)
        return

    if args.command == "pattern-j-audit":
        _cmd_pattern_j_audit(args)
        return

    if args.command == "pattern-z-audit":
        _cmd_pattern_z_audit(args)
        return

    if args.command == "pattern-q-audit":
        _cmd_pattern_q_audit(args)
        return

    if args.command == "audit":
        _cmd_audit_all(args)
        return

    if args.command == "shopify-doctor":
        _cmd_shopify_doctor(args)
        return

    if args.command == "doctor":
        _cmd_unified_doctor(args)
        return

    if args.command == "shopify-webhooks":
        _cmd_shopify_webhooks(args)
        return

    if args.command == "shopify-webhook-manifest":
        _cmd_shopify_webhook_manifest(args)
        return

    if args.command == "shopify-app-toml":
        _cmd_shopify_app_toml(args)
        return

    if args.command == "shopify-prepare-deploy":
        _cmd_shopify_prepare_deploy(args)
        return

    if args.command == "shopify-scopes-live-check":
        _cmd_shopify_scopes_live_check(args)
        return

    if args.command == "shopify-webhooks-live-check":
        _cmd_shopify_webhooks_live_check(args)
        return

    if args.command == "launch":
        _cmd_launch(args)
        return

    if args.command == "launch-audit":
        _cmd_launch_audit(args)
        return

    if args.command == "post-launch":
        _cmd_post_launch(args)
        return

    if args.command == "shopify-install-manifest":
        _cmd_shopify_install_manifest(args)
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
