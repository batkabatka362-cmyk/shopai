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

Module map (intended decomposition, not yet physical split)
─────────────────────────────────────────────────────────────
At 5000+ lines this file is too long for a single module.
A future refactor should extract each command group into
``cli_commands/<group>.py`` with a ``register(subparsers)`` +
``dispatch(args)`` pair. The mapping below is the plan; the
physical split is deferred because every command group has
inter-module helper usage that needs untangling first.

  Group           → Future home
  ──────────────── ─────────────────────────────────────────
  store, sync,    → cli_commands/store.py
  db, config
  mind, engines,  → cli_commands/brain.py
  run, explain,
  explains, plan-*
  actions,        → cli_commands/ops.py
  health, setup,
  status
  simulate,       → cli_commands/evaluate.py
  predict
  brain-learned,  → cli_commands/learning.py
  memory, trust
  vault-sweep,    → cli_commands/vault.py
  niches
  ask-support,    → cli_commands/support.py
  notify,
  owner-poll
  federation      → cli_commands/federation.py
  risk, crisis    → cli_commands/safety.py
  agentic,        → cli_commands/channels.py
  landed-cost

Rule: until the split happens, new commands follow the
same ``sub.add_parser(...) + def handle_<cmd>(args)``
pattern used by existing commands in this file.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("cli")


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
    sub.add_parser("engines", help="List all registered engines")

    eng_info = sub.add_parser("engine-info", help="Show engine details")
    eng_info.add_argument("engine_name", help="Engine name")

    run_p = sub.add_parser("run", help="Run an engine")
    run_p.add_argument("task_type", help="Engine name")
    run_p.add_argument("--store", default="", help="Store ID")
    run_p.add_argument("--params", type=str, default="{}", help="JSON params")

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

    learn_p = sub.add_parser("learn", help="Show learning status")
    learn_p.add_argument("--details", action="store_true", help="Show detailed learning data")

    # ── Launch commands (Goal-Driven Executor) ──────────────
    launch_p = sub.add_parser("launch", help="Launch a new product end-to-end")
    launch_p.add_argument("--alibaba-url", default="", help="Alibaba product URL")
    launch_p.add_argument("--title", default="", help="Product title (manual mode)")
    launch_p.add_argument("--price", type=float, default=0.0,
                          help="Source price (manual mode only)")
    launch_p.add_argument("--gallery", default="",
                          help="Comma-separated image URLs (manual mode only)")
    launch_p.add_argument("--target-price", type=float, default=None,
                          help="Retail price (default: AI computes from cost + margin)")
    launch_p.add_argument("--ad-budget", type=float, default=20.0,
                          help="Daily Meta Ads budget in USD (default 20)")
    launch_p.add_argument("--niche", default="", help="Niche / product category")
    launch_p.add_argument("--tone",
                          choices=["urgent", "friendly", "luxury", "informative"],
                          default="friendly")
    launch_p.add_argument("--dry-run", action="store_true",
                          help="Print the goal without running the pipeline")
    launch_p.add_argument("--min-win-prob", type=float, default=0.0,
                          help="Abort launch if predictor win_probability "
                               "is below this (0.0-1.0, default 0.0)")
    launch_p.add_argument("--predict-only", action="store_true",
                          help="Run the pre-launch predictor and exit")

    launches_p = sub.add_parser("launches", help="List active launches + verdicts")
    launches_p.add_argument("--json", action="store_true",
                            help="Emit raw JSON instead of a table")

    kill_p = sub.add_parser("kill",
                            help="Force-kill a launch regardless of ROAS")
    kill_p.add_argument("launch_id", help="launch_<id> to kill")

    # ── Reasoning ───────────────────────────────────────────
    reason_p = sub.add_parser("reason",
                              help="Multi-step reasoning chain over memory")
    reason_p.add_argument("question", help="Free-text question")
    reason_p.add_argument("--k", type=int, default=6,
                          help="Number of memories to pull (default 6)")
    reason_p.add_argument("--json", action="store_true",
                          help="Emit raw JSON instead of a narrative")

    # ── Ask the oracle ─────────────────────────────────────
    ask_p = sub.add_parser("ask",
                            help="Ask the brain a question (one-shot Q&A)")
    ask_p.add_argument("question", help="Free-text question")
    ask_p.add_argument("--k", type=int, default=8,
                       help="Memory rows to consider (default 8)")
    ask_p.add_argument("--json", action="store_true",
                       help="Emit raw JSON instead of human text")

    # ── Plan synthesis ──────────────────────────────────────
    plan_p = sub.add_parser("plan",
                            help="Turn a free-text goal into an action DAG")
    plan_p.add_argument("goal", help="Free-text goal (e.g. 'scale winners')")
    plan_p.add_argument("--json", action="store_true")

    # ── Skills ──────────────────────────────────────────────
    skills_p = sub.add_parser("skills",
                              help="View the brain's skill tree")
    skills_p.add_argument("--category", default=None,
                          help="Filter by category")
    skills_p.add_argument("--min-conf", type=float, default=None,
                          dest="min_conf",
                          help="Filter by minimum confidence")
    skills_p.add_argument("--json", action="store_true")

    # ── Human feedback ──────────────────────────────────────
    feedback_p = sub.add_parser("feedback",
                                help="Up/down vote a memory to steer the brain")
    feedback_p.add_argument("memory_id", type=int,
                            help="ID of the memory to rate")
    feedback_p.add_argument("sign", type=str,
                            help="+1 / up / +, or -1 / down / -")
    feedback_p.add_argument("note", nargs="?", default="",
                            help="Optional note explaining your rating")

    # ── Daily opportunity scout ─────────────────────────────
    digest_p = sub.add_parser("digest",
                              help="Run the proactive opportunity scout")
    digest_p.add_argument("--narrative", action="store_true",
                          help="Also generate an LLM narrative")
    digest_p.add_argument("--json", action="store_true")

    # ── Causal inference ────────────────────────────────────
    why_p = sub.add_parser("why",
                           help="Investigate likely causes for a launch outcome")
    why_p.add_argument("launch_id", help="launch_<id> to investigate")
    why_p.add_argument("--window", type=int, default=7,
                       help="Days of memory context around the anchor (default 7)")
    why_p.add_argument("--json", action="store_true")

    # ── Multi-turn chat ─────────────────────────────────────
    chat_p = sub.add_parser("chat",
                            help="Multi-turn conversation with the brain")
    chat_sub = chat_p.add_subparsers(dest="chat_action")
    say_p = chat_sub.add_parser("say", help="Send one turn to a session")
    say_p.add_argument("question", help="Free-text message")
    say_p.add_argument("--session", default="", help="Session id (new if empty)")
    say_p.add_argument("--json", action="store_true")
    chat_sub.add_parser("list", help="List recent sessions")
    show_p = chat_sub.add_parser("show", help="Show a session transcript")
    show_p.add_argument("session_id")

    # ── Semantic memory ─────────────────────────────────────
    similar_p = sub.add_parser("similar",
                               help="Find memories semantically close to a query")
    similar_p.add_argument("query", help="Free-text query")
    similar_p.add_argument("--k", type=int, default=5, help="Top K (default 5)")
    similar_p.add_argument("--level", type=int, default=0,
                           help="Min level (0=event, 1=pattern, 2=rule, 3=strategy)")
    similar_p.add_argument("--category", default=None,
                           help="Filter by memory category")

    # ── Competitor monitoring ───────────────────────────────
    comp_p = sub.add_parser("competitor",
                            help="Track a competitor product URL")
    comp_sub = comp_p.add_subparsers(dest="comp_action")
    comp_add = comp_sub.add_parser("add", help="Add URL to tracker")
    comp_add.add_argument("url")
    comp_rm = comp_sub.add_parser("remove", help="Stop tracking URL")
    comp_rm.add_argument("url")
    comp_sub.add_parser("list", help="Show tracked URLs + last snapshot")
    comp_sub.add_parser("check", help="Probe every tracked URL now")

    # ── Publisher bundle (v38+) ──────────────────────────────
    # ``publish`` goes through execution.launch.publisher_bundle
    # which is the v38-era transactional launch pipeline.
    # The older ``launch`` command uses the Goal-Driven Executor
    # (Alibaba URL / manual fields); both coexist.
    publish_p = sub.add_parser(
        "publish",
        help=(
            "Publish a winner end-to-end via publisher_bundle "
            "(Shopify product + PAUSED Meta campaign)"
        ),
    )
    publish_p.add_argument(
        "winner_json",
        help=(
            "Path to JSON with winner fields "
            "(title/price/image_url/...) or '-' for stdin"
        ),
    )
    publish_p.add_argument(
        "--budget", type=float, default=20.0,
        help="Daily ad budget USD (default $20)",
    )
    publish_p.add_argument(
        "--platform", default="facebook",
        choices=["facebook", "instagram", "tiktok", "google"],
    )
    publish_p.add_argument(
        "--live", action="store_true",
        help=(
            "Live writes (also needs "
            "SHOPAI_ENABLE_LIVE_EXECUTION=1)"
        ),
    )
    publish_p.add_argument(
        "--json", action="store_true",
    )

    activate_p = sub.add_parser(
        "activate",
        help=(
            "Flip a PAUSED Meta campaign to ACTIVE after "
            "readiness + constraints pass"
        ),
    )
    activate_p.add_argument("campaign_id")
    activate_p.add_argument(
        "--budget", type=float, default=0.0,
        help=(
            "Daily budget for pre-flight sanity "
            "(optional)"
        ),
    )
    activate_p.add_argument(
        "--auto-approve", action="store_true",
        help=(
            "Skip owner confirmation gate — required "
            "when not dry_run"
        ),
    )
    activate_p.add_argument(
        "--live", action="store_true",
    )
    activate_p.add_argument(
        "--json", action="store_true",
    )

    autopilot_p = sub.add_parser(
        "autopilot",
        help=(
            "Full-autonomy: winner sources → publish → "
            "activate. Per CLAUDE.md §4c, dry-run by default."
        ),
    )
    autopilot_p.add_argument(
        "--seeds",
        default="data/winner_seeds.json",
        help=(
            "ManualSeedSource JSON file "
            "(default data/winner_seeds.json)"
        ),
    )
    autopilot_p.add_argument(
        "--peers",
        default="",
        help=(
            "Comma-separated peer Shopify store URLs "
            "for PeerStoreObserverSource "
            "(e.g. a.myshopify.com,b.com)"
        ),
    )
    autopilot_p.add_argument(
        "--max-launches", type=int, default=1,
        help="Max winners to launch in one run (default 1)",
    )
    autopilot_p.add_argument(
        "--top-n", type=int, default=5,
        help="Top-N winners to rank before cap (default 5)",
    )
    autopilot_p.add_argument(
        "--budget", type=float, default=20.0,
        help="Daily ad budget USD (default $20)",
    )
    autopilot_p.add_argument(
        "--platform", default="facebook",
        choices=["facebook", "instagram", "tiktok", "google"],
    )
    autopilot_p.add_argument(
        "--no-activate", action="store_true",
        help=(
            "Publish only; skip campaign activation"
        ),
    )
    autopilot_p.add_argument(
        "--live", action="store_true",
        help=(
            "Live writes (also needs "
            "SHOPAI_ENABLE_LIVE_EXECUTION=1)"
        ),
    )
    autopilot_p.add_argument(
        "--json", action="store_true",
    )

    publications_p = sub.add_parser(
        "publications",
        help="Recent publisher_bundle publications",
    )
    publications_p.add_argument(
        "--limit", type=int, default=10,
    )
    publications_p.add_argument(
        "--json", action="store_true",
    )

    activations_p = sub.add_parser(
        "activations",
        help="Recent campaign_activator runs",
    )
    activations_p.add_argument(
        "--limit", type=int, default=10,
    )
    activations_p.add_argument(
        "--json", action="store_true",
    )

    # ── Self-revision journal (Sprint 2 #6) ──────────────────
    pending_p = sub.add_parser(
        "pending",
        help=(
            "Show proposals in self_revision_journal "
            "awaiting owner approval"
        ),
    )
    pending_p.add_argument(
        "--limit", type=int, default=20,
    )
    pending_p.add_argument(
        "--json", action="store_true",
    )

    approve_p = sub.add_parser(
        "approve",
        help=(
            "Approve a pending revision by id "
            "(launches the rule into applied state)"
        ),
    )
    approve_p.add_argument("revision_id")
    approve_p.add_argument(
        "--apply", action="store_true",
        help=(
            "Also mark as applied (default: just accepted)"
        ),
    )

    reject_p = sub.add_parser(
        "reject",
        help="Reject a pending revision by id",
    )
    reject_p.add_argument("revision_id")

    # ── Launch learning (Sprint 2 #2) ────────────────────────
    distill_p = sub.add_parser(
        "distill",
        help=(
            "Run launch_learner over recent episodes — "
            "promotes patterns to pending proposals"
        ),
    )
    distill_p.add_argument(
        "--window", type=int, default=200,
        help="Episode window (default 200)",
    )
    distill_p.add_argument(
        "--json", action="store_true",
    )

    # `digest` is taken by the older opportunity scout; use
    # `report` for the v38-era launch digest.
    report_p = sub.add_parser(
        "report",
        help=(
            "Launch digest — launches, learnings, "
            "journal, spend, insights (v38+)"
        ),
    )
    report_p.add_argument(
        "--hours", type=float, default=24.0 * 7,
        help="Window in hours (default 168 / 7d)",
    )
    report_p.add_argument(
        "--json", action="store_true",
    )

    # ── L8 simulator ─────────────────────────────────────────
    sim_p = sub.add_parser(
        "simulate",
        help=(
            "Monte Carlo pre-launch profit projection "
            "(L8 — see docs/AGI_STACK.md)"
        ),
    )
    sim_p.add_argument(
        "--cost", type=float, required=True,
        help="Unit cost (COGS + fulfilment)",
    )
    sim_p.add_argument(
        "--price", type=float, required=True,
        help="Retail price",
    )
    sim_p.add_argument(
        "--budget", type=float, required=True,
        help="Daily ad budget USD",
    )
    sim_p.add_argument("--days", type=int, default=3)
    sim_p.add_argument(
        "--cvr-mean", type=float, default=0.02,
    )
    sim_p.add_argument(
        "--cvr-stddev", type=float, default=0.01,
    )
    sim_p.add_argument(
        "--cpc-mean", type=float, default=1.20,
    )
    sim_p.add_argument(
        "--cpc-stddev", type=float, default=0.40,
    )
    sim_p.add_argument(
        "--refund-rate", type=float, default=0.05,
    )
    sim_p.add_argument(
        "--trials", type=int, default=1000,
    )
    sim_p.add_argument(
        "--seed", type=int, default=1337,
    )
    sim_p.add_argument(
        "--json", action="store_true",
    )

    # ── L7 legal templates ───────────────────────────────────
    legal_p = sub.add_parser(
        "legal",
        help=(
            "Render region-aware legal pages (privacy / terms "
            "/ returns / shipping / cookies)"
        ),
    )
    legal_p.add_argument(
        "--region", default="US",
        choices=("US", "EU", "UK"),
    )
    legal_p.add_argument(
        "--store", default="",
        help=(
            "Store name (defaults to SHOPAI_SHOPIFY_URL "
            "subdomain)"
        ),
    )
    legal_p.add_argument(
        "--email", default="",
        help=(
            "Contact email (defaults to SHOPAI_CONTACT_EMAIL)"
        ),
    )
    legal_p.add_argument(
        "--kind",
        choices=(
            "privacy", "terms", "returns",
            "shipping", "cookies",
        ),
        default=None,
        help="Render just one page (default: all five)",
    )
    legal_p.add_argument(
        "--json", action="store_true",
    )

    # ── LX.6 owner dialog ────────────────────────────────────
    poll_p = sub.add_parser(
        "owner-poll",
        help=(
            "Poll Telegram for owner commands and dispatch "
            "to brain handlers (approve/reject/status/etc.)"
        ),
    )
    poll_p.add_argument(
        "--limit", type=int, default=20,
    )
    poll_p.add_argument(
        "--dry-run", action="store_true",
        help=(
            "Process commands without sending replies back"
        ),
    )
    poll_p.add_argument(
        "--json", action="store_true",
    )

    notify_p = sub.add_parser(
        "notify",
        help=(
            "Send launch digest to the owner via Telegram "
            "(LX.6 owner dialog)"
        ),
    )
    notify_p.add_argument(
        "--hours", type=float, default=24.0 * 7,
        help="Window in hours (default 168 / 7d)",
    )
    notify_p.add_argument(
        "--dry-run", action="store_true",
        help="Compose the message without actually sending",
    )
    notify_p.add_argument(
        "--chat-id", type=str, default=None,
        help="Override TELEGRAM_CHAT_ID for this message",
    )
    notify_p.add_argument(
        "--json", action="store_true",
    )

    # ── World model what-if prediction ───────────────────────
    predict_p = sub.add_parser(
        "predict",
        help=(
            "Calibrated what-if prediction for an action "
            "(L4 reasoning — Track 10)"
        ),
    )
    predict_p.add_argument(
        "action",
        help=(
            "Action vocabulary: launch | scale | kill | "
            "hold | add_cross_sell | wait"
        ),
    )
    predict_p.add_argument(
        "--kpi", default="roas",
        choices=("roas", "cvr", "revenue", "aov"),
    )
    predict_p.add_argument(
        "--niche", default="unknown",
    )
    predict_p.add_argument(
        "--price-band",
        choices=("low", "mid", "high"), default="mid",
    )
    predict_p.add_argument(
        "--margin-band",
        choices=("low", "mid", "high"), default="mid",
    )
    predict_p.add_argument(
        "--tone", default="friendly",
    )
    predict_p.add_argument(
        "--json", action="store_true",
    )

    # ── Landed cost calculator (Wave F-1) ────────────────────
    landed_p = sub.add_parser(
        "landed-cost",
        help=(
            "Landed cost + de-minimis aware routing "
            "(FOB + duty + VAT + shipping + processing)"
        ),
    )
    landed_p.add_argument(
        "--fob", type=float, required=True,
        help="Supplier cost USD",
    )
    landed_p.add_argument(
        "--destination",
        choices=("US", "EU", "UK"),
        required=True,
    )
    landed_p.add_argument(
        "--origin", default="CN",
        help="Origin country code (default CN)",
    )
    landed_p.add_argument(
        "--hts", default="",
        help="HTS code (optional; drives duty category)",
    )
    landed_p.add_argument(
        "--shipping", type=float, default=0.0,
    )
    landed_p.add_argument(
        "--fulfillment", type=float, default=0.0,
    )
    landed_p.add_argument(
        "--target-margin", type=float, default=0.30,
        help="Target retail margin (default 0.30)",
    )
    landed_p.add_argument(
        "--de-minimis",
        choices=(
            "active", "suspended_cn", "suspended_all",
        ),
        default=None,
        help=(
            "Override US de-minimis status (default reads "
            "SHOPAI_US_DE_MINIMIS_STATUS env)"
        ),
    )
    landed_p.add_argument(
        "--json", action="store_true",
    )

    # ── Agentic Storefront channels (Wave B-1) ───────────────
    agentic_p = sub.add_parser(
        "agentic",
        help=(
            "Agentic Storefront channels — ChatGPT, Perplexity, "
            "Copilot, Gemini enrollment + attribution"
        ),
    )
    agentic_sub = agentic_p.add_subparsers(
        dest="agentic_action",
    )
    agentic_status = agentic_sub.add_parser(
        "status",
        help="Per-channel enrollment + order counts",
    )
    agentic_status.add_argument(
        "--force", action="store_true",
        help="Bypass 5-minute status cache",
    )
    agentic_status.add_argument(
        "--json", action="store_true",
    )
    agentic_metrics = agentic_sub.add_parser(
        "metrics",
        help=(
            "Roll up orders by agentic channel over window"
        ),
    )
    agentic_metrics.add_argument(
        "--days", type=int, default=7,
    )
    agentic_metrics.add_argument(
        "--json", action="store_true",
    )

    # ── Brain state synthesizer ──────────────────────────────
    brain_p = sub.add_parser(
        "brain",
        help=(
            "Holistic brain state snapshot — crisis + risk + "
            "memory + learning + trust + rationale + "
            "derived priorities (Track 9)"
        ),
    )
    brain_p.add_argument(
        "--json", action="store_true",
    )

    # ── Decision rationale replay ────────────────────────────
    explain_p = sub.add_parser(
        "explain",
        help=(
            "Replay a decision's rationale tree from the "
            "persistent ledger"
        ),
    )
    explain_p.add_argument(
        "decision_id",
        help="Decision id returned by activator/publisher",
    )
    explain_p.add_argument(
        "--json", action="store_true",
    )
    explain_recent_p = sub.add_parser(
        "explains",
        help="Recent decisions with rationale records",
    )
    explain_recent_p.add_argument(
        "--limit", type=int, default=20,
    )
    explain_recent_p.add_argument(
        "--json", action="store_true",
    )

    # ── Obsidian vault read-back ─────────────────────────────
    vault_p = sub.add_parser(
        "vault-sweep",
        help=(
            "Scan OBSIDIAN_VAULT_PATH for frontmatter-tagged "
            "constraint notes and apply them"
        ),
    )
    vault_p.add_argument(
        "--vault", default="",
        help=(
            "Vault path (default OBSIDIAN_VAULT_PATH env)"
        ),
    )
    vault_p.add_argument(
        "--dry-run", action="store_true",
        help=(
            "Parse notes but skip sink.register (preview)"
        ),
    )
    vault_p.add_argument(
        "--json", action="store_true",
    )

    # ── L2 source trust ──────────────────────────────────────
    trust_p = sub.add_parser(
        "trust",
        help=(
            "Source trust calibrator — per-source hit-rate "
            "× freshness"
        ),
    )
    trust_sub = trust_p.add_subparsers(
        dest="trust_action",
    )
    trust_sub.add_parser(
        "status",
        help="Ranked list of all registered sources",
    )
    trust_set = trust_sub.add_parser(
        "baseline",
        help="Set baseline trust for a source",
    )
    trust_set.add_argument("--source", required=True)
    trust_set.add_argument(
        "--trust", type=float, required=True,
    )

    # ── L3 memory consolidator ───────────────────────────────
    mem_p = sub.add_parser(
        "memory",
        help=(
            "Memory consolidator — episode → concept → "
            "procedure ladder"
        ),
    )
    mem_sub = mem_p.add_subparsers(dest="mem_action")
    mem_sub.add_parser(
        "status",
        help="Counts by layer + active thresholds",
    )
    mem_run = mem_sub.add_parser(
        "consolidate",
        help="Run one ladder sweep (promote + decay + archive)",
    )
    mem_run.add_argument(
        "--json", action="store_true",
    )
    mem_concepts = mem_sub.add_parser(
        "concepts",
        help="List top concepts by priority × evidence",
    )
    mem_concepts.add_argument(
        "--limit", type=int, default=20,
    )
    mem_concepts.add_argument(
        "--json", action="store_true",
    )
    mem_procs = mem_sub.add_parser(
        "procedures",
        help="List promoted procedures",
    )
    mem_procs.add_argument(
        "--limit", type=int, default=20,
    )
    mem_procs.add_argument(
        "--json", action="store_true",
    )

    # ── L9 learning / rulebook ───────────────────────────────
    learned_p = sub.add_parser(
        "brain-learned",
        help=(
            "Show the RuleBook — what the brain has learned "
            "from episodes + outcomes"
        ),
    )
    learned_sub = learned_p.add_subparsers(
        dest="learned_action",
    )
    learned_sub.add_parser(
        "status",
        help=(
            "Rule counts by status + active thresholds"
        ),
    )
    learned_top = learned_sub.add_parser(
        "top",
        help=(
            "Highest-confidence rules (ranked by "
            "confidence = wins × coverage)"
        ),
    )
    learned_top.add_argument(
        "--limit", type=int, default=10,
    )
    learned_top.add_argument(
        "--json", action="store_true",
    )
    learned_ls = learned_sub.add_parser(
        "list",
        help="List rules by status",
    )
    learned_ls.add_argument(
        "--status",
        choices=(
            "proposed", "active",
            "deprecated", "killed",
        ),
        default="proposed",
    )
    learned_ls.add_argument(
        "--limit", type=int, default=20,
    )
    learned_ls.add_argument(
        "--json", action="store_true",
    )

    # ── L2 niche discovery ───────────────────────────────────
    niches_p = sub.add_parser(
        "niches",
        help=(
            "Discover + rank niches from the winner pool "
            "(trend-enriched by Google Trends)"
        ),
    )
    niches_p.add_argument(
        "--candidates", type=int, default=50,
        help="Max candidates to pull from sources",
    )
    niches_p.add_argument(
        "--limit", type=int, default=10,
        help="Top niches to show",
    )
    niches_p.add_argument(
        "--no-trends", action="store_true",
        help=(
            "Skip Google Trends scoring (pure rollup ranking)"
        ),
    )
    niches_p.add_argument(
        "--json", action="store_true",
    )

    # ── L4 long-horizon planning ─────────────────────────────
    plan_p = sub.add_parser(
        "plan-quarter",
        help=(
            "Build a weekly-milestone plan from a quarterly "
            "revenue goal (L4)"
        ),
    )
    plan_p.add_argument(
        "--monthly-target", type=float, required=True,
        help="Revenue target in USD/month at deadline",
    )
    plan_p.add_argument(
        "--weeks", type=int, default=13,
        help="Plan duration in weeks (default 13 = 1 quarter)",
    )
    plan_p.add_argument(
        "--sku-target", type=int, default=20,
    )
    plan_p.add_argument(
        "--roas-target", type=float, default=1.8,
    )
    plan_p.add_argument(
        "--ramp",
        choices=("linear", "front_loaded", "back_loaded"),
        default="linear",
    )
    plan_p.add_argument(
        "--niche", default="",
    )
    plan_p.add_argument(
        "--json", action="store_true",
    )

    checkin_p = sub.add_parser(
        "plan-checkin",
        help=(
            "Check current revenue against a quarterly plan "
            "(verdict: ahead / on_track / behind / at_risk)"
        ),
    )
    checkin_p.add_argument(
        "--monthly-target", type=float, required=True,
    )
    checkin_p.add_argument(
        "--weeks", type=int, default=13,
    )
    checkin_p.add_argument(
        "--week-elapsed", type=int, required=True,
        help=(
            "Weeks since plan started (1-based; use week 0 "
            "for pre-kickoff)"
        ),
    )
    checkin_p.add_argument(
        "--revenue", type=float, required=True,
        help="Cumulative revenue so far, USD",
    )
    checkin_p.add_argument(
        "--skus-live", type=int, default=0,
    )
    checkin_p.add_argument(
        "--current-roas", type=float, default=0.0,
    )
    checkin_p.add_argument(
        "--ramp",
        choices=("linear", "front_loaded", "back_loaded"),
        default="linear",
    )
    checkin_p.add_argument(
        "--sku-target", type=int, default=20,
    )
    checkin_p.add_argument(
        "--json", action="store_true",
    )

    # ── LX.5 multi-store federation ──────────────────────────
    fed_p = sub.add_parser(
        "federation",
        help=(
            "Multi-store federation — pool rules across "
            "stores by similarity (LX.5)"
        ),
    )
    fed_sub = fed_p.add_subparsers(dest="fed_action")
    fed_sub.add_parser(
        "status",
        help="List registered stores + rule counts",
    )
    fed_register = fed_sub.add_parser(
        "register",
        help="Register a store (idempotent — re-register updates traits)",
    )
    fed_register.add_argument(
        "--store", required=True,
        help="Store id (unique)",
    )
    fed_register.add_argument(
        "--trait", action="append", default=[],
        help=(
            "key=value; repeatable. "
            "Example: --trait niche=pet --trait currency=USD"
        ),
    )
    fed_register.add_argument(
        "--weight", type=float, default=1.0,
    )
    fed_observe = fed_sub.add_parser(
        "observe",
        help=(
            "Record a rule observation. Observations accumulate."
        ),
    )
    fed_observe.add_argument(
        "--store", required=True,
    )
    fed_observe.add_argument(
        "--rule", required=True,
    )
    fed_observe.add_argument(
        "--wins", type=int, required=True,
    )
    fed_observe.add_argument(
        "--uses", type=int, required=True,
    )
    fed_score = fed_sub.add_parser(
        "score",
        help=(
            "Federated score for a rule at a target store "
            "(weighted by trait similarity)"
        ),
    )
    fed_score.add_argument(
        "--target", required=True,
        help="Target store_id",
    )
    fed_score.add_argument(
        "--rule", required=True,
    )
    fed_score.add_argument(
        "--json", action="store_true",
    )
    fed_best = fed_sub.add_parser(
        "best",
        help="Top federated rules for a target store",
    )
    fed_best.add_argument(
        "--target", required=True,
    )
    fed_best.add_argument(
        "--limit", type=int, default=10,
    )
    fed_best.add_argument(
        "--json", action="store_true",
    )

    # ── LX.1 customer support ────────────────────────────────
    ask_support_p = sub.add_parser(
        "ask-support",
        help=(
            "Preview how the LX.1 support chatbot would "
            "answer a customer question (rule-based, LLM-free)"
        ),
    )
    ask_support_p.add_argument("question", type=str)
    ask_support_p.add_argument(
        "--json", action="store_true",
    )

    # ── LX.4 crisis response ─────────────────────────────────
    crisis_p = sub.add_parser(
        "crisis",
        help=(
            "Crisis responder — kill switch + event-driven "
            "escalation"
        ),
    )
    crisis_sub = crisis_p.add_subparsers(
        dest="crisis_action",
    )
    crisis_status = crisis_sub.add_parser(
        "status", help="Show current crisis level + events",
    )
    crisis_status.add_argument(
        "--json", action="store_true",
    )
    crisis_halt = crisis_sub.add_parser(
        "halt",
        help="Trip the emergency halt (blocks all live writes)",
    )
    crisis_halt.add_argument(
        "--reason", default="",
        help="Reason recorded alongside the halt",
    )
    crisis_sub.add_parser(
        "resume", help="Clear a manual halt",
    )
    crisis_events = crisis_sub.add_parser(
        "events",
        help="Recent crisis events (limit = 20 by default)",
    )
    crisis_events.add_argument(
        "--limit", type=int, default=20,
    )
    crisis_events.add_argument(
        "--json", action="store_true",
    )

    # ── L7 risk / tripwire ───────────────────────────────────
    risk_p = sub.add_parser(
        "risk",
        help="Risk tripwire — $ caps and current spend",
    )
    risk_sub = risk_p.add_subparsers(dest="risk_action")
    risk_status_p = risk_sub.add_parser(
        "status",
        help="Today's ad spend vs caps + chargeback rate",
    )
    risk_status_p.add_argument(
        "--json", action="store_true",
    )
    risk_limits_p = risk_sub.add_parser(
        "limits",
        help="Show active tripwire limits and their env overrides",
    )
    risk_limits_p.add_argument(
        "--json", action="store_true",
    )
    risk_recent_p = risk_sub.add_parser(
        "recent",
        help="Recent spend events booked by the tripwire",
    )
    risk_recent_p.add_argument(
        "--limit", type=int, default=20,
    )
    risk_recent_p.add_argument(
        "--json", action="store_true",
    )

    # ── System commands ──────────────────────────────────────
    sub.add_parser("health", help="System health check (module imports)")
    doctor_p = sub.add_parser(
        "doctor",
        help=(
            "End-to-end readiness check — tells you exactly what "
            "to fix"
        ),
    )
    doctor_p.add_argument(
        "--json", action="store_true",
        help="Machine-readable output",
    )
    doctor_p.add_argument(
        "--network", action="store_true",
        help=(
            "Also run network-dependent checks (webhook "
            "registered, credentials validate via live call)"
        ),
    )
    doctor_p.add_argument(
        "--snippet", action="store_true",
        help=(
            "Print the Shopify attribution Liquid snippet for "
            "pasting into theme.liquid"
        ),
    )
    sub.add_parser("status", help="Full system status")
    sub.add_parser("setup", help="Interactive setup wizard")
    sub.add_parser("start", help="Start the orchestrator")
    sub.add_parser("stop", help="Stop the orchestrator")

    server_p = sub.add_parser("server", help="Start API + webhook server")
    server_p.add_argument("--port", type=int, default=8080, help="Port (default 8080)")
    server_p.add_argument("--host", default="0.0.0.0", help="Host (default 0.0.0.0)")

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

    # When the owner types an explicit store_id it must exist in
    # the registry. Otherwise get_credentials() would happily
    # return env-var fallback credentials for a *different*
    # store — a cross-store write that's easy to miss.
    if args.store_id and hasattr(sm, "db"):
        store_row = sm.db.get_store(args.store_id)
        if not store_row:
            print(
                f"Store {args.store_id!r} not found "
                "in registry.",
            )
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

def _cmd_engines() -> None:
    from engines.registry import engine_count, list_engines
    engines = list_engines()
    print(f"Registered engines: {engine_count()}\n")
    for i, name in enumerate(engines, 1):
        print(f"  {i:3d}. {name}")


def _cmd_engine_info(engine_name: str) -> None:
    from engines.registry import get_engine
    try:
        engine = get_engine(engine_name)
        name = getattr(engine, "ENGINE_NAME", getattr(engine, "engine_name", engine_name))
        print(f"Engine: {name}")
        print(f"Class:  {engine.__class__.__name__}")
        if hasattr(engine, "required_input_fields"):
            print(f"Inputs: {engine.required_input_fields}")
        if hasattr(engine, "required_output_fields"):
            print(f"Outputs: {engine.required_output_fields}")
    except KeyError:
        print(f"Unknown engine: {engine_name}")
        sys.exit(1)


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
    engine = get_engine(args.task_type)
    print(f"Running {args.task_type} (data source: {data.get('source', 'unknown')})...\n")

    result = engine.run(data)
    print(json.dumps(result, indent=2, default=str))


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

    controller = AutonomousController(sm, auto_approve=args.auto_approve)
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

def _cmd_launch(args) -> None:
    """Run the Goal-Driven launch pipeline end-to-end."""
    from workflows.launch import LaunchPipeline, LaunchGoal
    from core.adapters.llm.bootstrap import register_all as _register_llms
    _register_llms()  # idempotent; enables ContentStep's LLM call

    manual_payload = None
    if args.title:
        gallery = [u.strip() for u in (args.gallery or "").split(",") if u.strip()]
        manual_payload = {
            "title": args.title,
            "price_usd": args.price or 0.0,
            "gallery_urls": gallery,
        }

    goal = LaunchGoal(
        alibaba_url=args.alibaba_url or None,
        manual_payload=manual_payload,
        target_price=args.target_price,
        ad_budget_day=args.ad_budget,
        niche=args.niche,
        copy_tone=args.tone,
    )

    if args.dry_run:
        import dataclasses
        print(json.dumps(dataclasses.asdict(goal), indent=2, default=str))
        return

    if goal.source_kind() == "manual" and not goal.manual_payload:
        print("ERR: supply --alibaba-url OR --title (and --price / --gallery)",
              file=sys.stderr)
        sys.exit(2)

    # Pre-launch prediction — honours --predict-only + --min-win-prob
    if getattr(args, "predict_only", False) or getattr(args, "min_win_prob", 0) > 0:
        from core.autonomous.launch_predictor import predict as _predict
        pred = _predict(goal).as_dict()
        print(f"\nPREDICTION  grade={pred['grade']}  "
              f"win_probability={pred['win_probability']:.2f}")
        for r in pred.get("rationale", []):
            print(f"  • {r}")
        if args.predict_only:
            return
        if pred["win_probability"] < args.min_win_prob:
            print(f"\n  ABORTED — below --min-win-prob {args.min_win_prob}")
            sys.exit(4)

    result = LaunchPipeline().run(goal)
    print(f"\n[{result.status.upper()}] {result.launch_id}  "
          f"({result.duration_s:.1f}s)")
    if result.shopify_product_id:
        print(f"  Shopify: https://admin.shopify.com/store/"
              f"{os.environ.get('SHOPAI_SHOPIFY_URL', '').split('.')[0]}"
              f"/products/{result.shopify_product_id}")
    if result.shopify_handle:
        print(f"  Storefront: https://"
              f"{os.environ.get('SHOPAI_SHOPIFY_URL', '')}"
              f"/products/{result.shopify_handle}")
    print()
    for s in result.steps:
        marker = {"ok": "✓", "skipped": "·", "failed": "✗"}.get(s.status, " ")
        line = f"  {marker} {s.name:18s} {s.duration_s:5.2f}s"
        if s.error:
            line += f"  {s.error[:60]}"
        print(line)
    if result.failed_step:
        print(f"\n  aborted at {result.failed_step}: {result.failure_reason}")
        sys.exit(3)


def _cmd_launches(args) -> None:
    """Print per-launch KPIs + verdicts from the ROAS bucketer."""
    from core.autonomous.launch_evaluator import evaluate
    report = evaluate()
    data = report.as_dict()
    if args.json:
        print(json.dumps(data, indent=2))
        return
    print(f"Tracked: {data['launches_tracked']}  "
          f"Evaluated: {data['launches_evaluated']}  "
          f"Kills: {len(data['kills'])}  "
          f"Scales: {len(data['scales'])}  "
          f"Monitors: {len(data['monitors'])}\n")
    rows = data["kills"] + data["scales"] + data["monitors"]
    if not rows:
        print("  (no launches — run `shopai launch` first)")
        return
    print(f"  {'VERDICT':10s}  {'LAUNCH_ID':22s}  {'ROAS':6s}  "
          f"{'REV':>7s}  {'ORD':>4s}  {'DAYS':>5s}  REASON")
    for r in rows:
        print(f"  {r['verdict']:10s}  {r['launch_id']:22s}  "
              f"{r.get('estimated_roas', 0):6.2f}  "
              f"{r.get('revenue_usd', 0):>7.2f}  "
              f"{r.get('order_count', 0):>4d}  "
              f"{r.get('days_live', 0):>5.1f}  "
              f"{r.get('reason', '')[:60]}")


def _cmd_kill(launch_id: str) -> None:
    """Record a manual kill decision as a memory event + return."""
    try:
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        mi.create(
            category="launch",
            content={"launch_id": launch_id, "verdict": "manual_kill",
                     "reason": "owner-issued kill via CLI"},
            action="kill_launch",
            score=3.0,
            tags=["launch", "manual_kill", f"launch:{launch_id}"],
        )
        print(f"kill recorded for {launch_id}")
    except Exception as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        sys.exit(1)


def _cmd_reason(args) -> None:
    """Run the 4-phase reasoning chain."""
    from core.adapters.llm.bootstrap import register_all as _reg
    _reg()
    from core.brain.reasoner import reason
    result = reason(args.question, k_memories=args.k)
    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
        return
    print(f"\nQUESTION: {result.question}")
    print(f"  duration: {result.duration_s:.1f}s  "
          f"memories: {len(result.memory_ids)}")
    print(f"\n-- Research summary --")
    print(result.summary or "(empty)")
    print(f"\n-- Hypotheses ({len(result.hypotheses)}) --")
    for h in result.hypotheses:
        print(f"  [{h.get('impact', '?'):>4s}] {h['id']}: {h['claim']}")
        if h.get("test"):
            print(f"         test: {h['test']}  "
                  f"(signal: {h.get('signal', '?')}, "
                  f"cost ${h.get('cost_usd', 0):.0f})")
    print(f"\n-- Ranked plan --")
    for h in result.ranked:
        print(f"  #{h.get('rank', 99)}  {h['claim']}")
        if h.get("rationale"):
            print(f"       → {h['rationale']}")


def _cmd_ask(args) -> None:
    """One-shot Q&A over the memory + LLM chain."""
    from core.adapters.llm.bootstrap import register_all as _reg
    _reg()
    from core.brain.oracle import ask
    a = ask(args.question, k_memories=args.k)
    if args.json:
        print(json.dumps(a.as_dict(), indent=2))
        return
    print(f"\n{a.text}\n")
    print(f"  — cited {len(a.cited_ids)} memories, "
          f"confidence {a.confidence:.0%}, "
          f"{a.duration_s:.1f}s via {a.adapter}/{a.model}")


def _cmd_plan(args) -> None:
    """Synthesize an action DAG from a free-text goal."""
    from core.brain.planner import synthesize
    plan = synthesize(args.goal)
    if args.json:
        print(json.dumps(plan.as_dict(), indent=2))
        return
    print(f"\nPLAN {plan.id}  goal={plan.goal!r}")
    print(f"  total cost ${plan.total_cost:.2f}  "
          f"aggregate win_prob {plan.aggregate_win_prob:.0%}  "
          f"expected value ${plan.expected_value:.2f}")
    print()
    if not plan.nodes:
        print("  (no actions — empty goal?)")
        return
    for n in plan.nodes:
        deps = ("→ " + ",".join(n.depends_on)) if n.depends_on else ""
        print(f"  {n.id:20s}  {n.kind:16s}  w_p={n.win_prob:.0%}  "
              f"${n.cost_usd:6.2f}  {deps}")
        if n.rationale:
            print(f"    └─ {n.rationale[:100]}")


def _cmd_skills(args) -> None:
    """List the skill tree with confidence + use counts."""
    from core.brain.skills import registry
    skills = registry().list_all(
        category=args.category,
        min_confidence=args.min_conf,
    )
    if args.json:
        print(json.dumps([s.as_dict() for s in skills], indent=2))
        return
    if not skills:
        print("(no skills registered — run the launch pipeline once)")
        return
    print(f"  {'CONF':>6s}  {'±':>5s}  {'USES':>5s}  {'WINS':>5s}  "
          f"{'CATEGORY':12s}  NAME")
    for s in sorted(skills, key=lambda x: (-x.confidence, -x.uses)):
        print(f"  {s.confidence:>6.2f}  {s.uncertainty:>5.2f}  "
              f"{s.uses:>5d}  {s.wins:>5d}  {s.category:12s}  {s.name}")


def _cmd_feedback(args) -> None:
    """Up/down-vote a memory id and record the reason as a
    ``category=feedback`` event."""
    raw = args.sign.strip().lower()
    if raw in ("+1", "up", "+", "1"):
        sign = 1
    elif raw in ("-1", "down", "-"):
        sign = -1
    else:
        print(f"ERR: sign must be +1/-1/up/down (got {args.sign!r})",
              file=sys.stderr)
        sys.exit(2)
    from core.brain.feedback import record
    result = record(args.memory_id, sign, args.note)
    if result.feedback_memory_id is None and result.new_score == 0.0:
        print(f"ERR: memory {args.memory_id} not found", file=sys.stderr)
        sys.exit(3)
    arrow = "↑" if sign > 0 else "↓"
    print(f"Feedback recorded {arrow}  memory #{result.memory_id} "
          f"{result.prior_score:.2f} → {result.new_score:.2f}  "
          f"(feedback id #{result.feedback_memory_id})")


def _cmd_digest(args) -> None:
    """Run the proactive opportunity scout."""
    if args.narrative:
        from core.adapters.llm.bootstrap import register_all as _reg
        _reg()
    from core.autonomous.opportunity_scout import scout
    report = scout(include_narrative=args.narrative)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
        return
    print(f"\nDIGEST {report.date}  ({len(report.opportunities)} opportunities)")
    if not report.opportunities:
        print("  (brain is quiet — no proactive signals this pass)")
        return
    by_kind: dict[str, int] = {}
    for o in report.opportunities:
        by_kind[o.kind] = by_kind.get(o.kind, 0) + 1
    print("  counts: " + ", ".join(f"{k}={v}" for k, v in by_kind.items()))
    print()
    for o in report.opportunities[:12]:
        print(f"  [{o.kind:12s}] score={o.score:5.2f}  {o.headline}")
        if o.detail:
            print(f"               {o.detail[:100]}")
    if report.narrative:
        print("\n-- Morning brief --\n")
        print(report.narrative)


def _cmd_why(args) -> None:
    """Run the causal-inference engine on a launch and print the
    ranked list of candidate root causes."""
    from core.brain.causal_inference import investigate_launch
    report = investigate_launch(args.launch_id)
    if args.window:
        report.window_days = args.window
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
        return
    if not report.anchor_ts:
        print(f"ERR: no launch memory for {args.launch_id}", file=sys.stderr)
        sys.exit(2)
    print(f"Causal investigation for {report.target_id}  "
          f"(±{report.window_days} days around anchor)")
    if not report.candidates:
        print("  (no correlated events found in window)")
        return
    print(f"\n  {'STRENGTH':>8s}  {'CATEGORY':16s}  {'EVIDENCE':>8s}  SUMMARY")
    for c in report.candidates[:8]:
        print(f"  {c.strength:>8.2f}  {c.category:16s}  {c.evidence_count:>8d}  {c.summary[:80]}")


def _cmd_chat(args) -> None:
    """Multi-turn chat backed by ChatSession persistence."""
    from core.adapters.llm.bootstrap import register_all as _reg
    _reg()
    from core.brain.chat_session import send, ChatStore

    action = getattr(args, "chat_action", None)
    if action == "list":
        rows = ChatStore.list_ids(limit=20)
        if not rows:
            print("(no chat sessions — start one with `shopai chat say`)")
            return
        print(f"  {'SESSION':24s}  {'TURNS':>5s}  TITLE")
        for r in rows:
            print(f"  {r['id']:24s}  {r['turn_count']:>5d}  {r['title'][:80]}")
        return
    if action == "show":
        session = ChatStore.get(args.session_id)
        if session is None:
            print(f"ERR: unknown session {args.session_id}", file=sys.stderr)
            sys.exit(2)
        print(f"Session {session.id}  ({len(session.turns)} turns)")
        for t in session.turns:
            prefix = "USER" if t.role == "user" else "ORACLE"
            print(f"\n[{prefix}] {t.text}")
            if t.cited_ids:
                print(f"       cites: {t.cited_ids}")
        return
    if action == "say":
        out = send(args.session or None, args.question)
        if args.json:
            print(json.dumps(out, indent=2))
            return
        if "error" in out:
            print(f"ERR: {out['error']}", file=sys.stderr)
            sys.exit(3)
        print(f"\n{out['answer']}\n")
        print(f"  — session {out['session_id']} (turn {out['turn_count']}), "
              f"cites {out['cited_ids']}, "
              f"{out['memories_used']} memories, "
              f"via {out['adapter']}/{out['model']}")
        return
    print("ERR: use `shopai chat say|list|show`", file=sys.stderr)
    sys.exit(2)


def _cmd_similar(args) -> None:
    """Semantic search over the memory store."""
    from core.memory.semantic_index import retrieve_similar, stats
    idx = stats()
    if not idx.get("configured"):
        print("ERR: embedding client unconfigured "
              "(set GEMINI_API_KEY or GOOGLE_API_KEY)", file=sys.stderr)
        sys.exit(2)
    if idx["indexed"] == 0:
        print("WARN: memory index is empty — run the daemon for a cycle "
              "or call core.memory.semantic_index.index_pending()")
    hits = retrieve_similar(args.query, k=args.k, level_min=args.level,
                            category=args.category)
    if not hits:
        print("(no matches)")
        return
    print(f"Top {len(hits)} matches for: {args.query!r}")
    print(f"  {'SIM':>6s}  LVL  {'CATEGORY':18s}  {'ACTION':16s}  ID")
    for h in hits:
        m = h["memory"]
        print(f"  {h['score']:>6.3f}   {m['level']}   "
              f"{m['category']:18s}  {m['action']:16s}  {m['id']}")


def _cmd_competitor(args) -> None:
    """Manage the competitor price tracker."""
    from core.autonomous import competitor_monitor as cm
    action = getattr(args, "comp_action", None)
    if action == "add":
        ok = cm.add_url(args.url)
        print("added" if ok else "already tracked or invalid URL")
    elif action == "remove":
        ok = cm.remove_url(args.url)
        print("removed" if ok else "not tracked")
    elif action == "list":
        rows = cm.list_tracked()
        if not rows:
            print("(no tracked URLs — `shopai competitor add <url>` to add one)")
            return
        print(f"  {'PRICE':>8s}  {'CHECKED':>10s}  URL")
        for r in rows:
            price = r.get("last_price")
            ts = r.get("last_checked", 0)
            age = f"{int((time.time() - ts) / 60)}m" if ts else "never"
            pricestr = f"${price:.2f}" if isinstance(price, (int, float)) else "-"
            print(f"  {pricestr:>8s}  {age:>10s}  {r['url'][:80]}")
    elif action == "check":
        result = cm.check_all()
        print(f"checked {result['checked']} URLs — "
              f"{len(result['changes'])} significant price changes")
        for c in result.get("changes", [])[:10]:
            print(f"  {c['delta_pct']:+.1f}%  {c['old_price']} → "
                  f"{c['new_price']}  {c['url'][:80]}")
    else:
        print("ERR: use `competitor add|remove|list|check`", file=sys.stderr)
        sys.exit(2)


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


def _cmd_doctor(
    *,
    as_json: bool = False,
    network: bool = False,
    snippet: bool = False,
) -> None:
    """End-to-end readiness diagnostic. Tells the owner exactly
    what env / wiring / webhook fixes are needed for real work."""
    if snippet:
        from execution.launch.shopify_attribution import (
            build_liquid_snippet, install_instructions,
        )
        shop = os.environ.get(
            "SHOPAI_SHOPIFY_URL", "your-store.myshopify.com",
        )
        print(install_instructions(shop))
        print()
        print("─" * 60)
        print("SNIPPET (paste into layout/theme.liquid):")
        print("─" * 60)
        print(build_liquid_snippet())
        return
    from core.readiness.health_check import run_all
    report = run_all(network=network)
    if as_json:
        print(json.dumps(report.as_dict(), indent=2))
        return
    print(report.as_text())
    # Non-zero exit when blocked so shell scripts / CI can branch
    if report.verdict == "blocked":
        sys.exit(2)
    if report.verdict == "degraded":
        sys.exit(1)


# ── Launch pipeline handlers ───────────────────────────────

def _read_winner(source: str) -> dict:
    """Read winner JSON from file path or stdin ('-')."""
    if source == "-":
        data = sys.stdin.read()
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(
                f"winner file not found: {source}",
            )
        data = path.read_text()
    try:
        winner = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"winner_json is not valid JSON: {exc}",
        ) from exc
    if not isinstance(winner, dict):
        raise ValueError(
            "winner_json must decode to an object",
        )
    return winner


def _cmd_publish(
    *,
    winner_json: str,
    budget: float,
    platform: str,
    live: bool,
    as_json: bool,
) -> None:
    """Run publisher_bundle for one winner."""
    from execution.launch.publisher_bundle import (
        LaunchRequest, PublisherBundle,
    )
    try:
        winner = _read_winner(winner_json)
    except Exception as exc:
        if as_json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"[launch] error: {exc}")
        sys.exit(2)
    shop_url = os.environ.get(
        "SHOPAI_SHOPIFY_URL", "",
    )
    api_key = os.environ.get(
        "SHOPAI_SHOPIFY_KEY",
        os.environ.get(
            "SHOPAI_SHOPIFY_CLIENT_SECRET", "",
        ),
    )
    meta_account = os.environ.get(
        "META_ADS_ACCOUNT_ID",
        os.environ.get("meta_ads_account_id", ""),
    )
    try:
        req = LaunchRequest(
            winner=winner,
            shop_url=shop_url,
            api_key=api_key,
            ad_budget_daily=budget,
            platform=platform,
            meta_account_id=meta_account,
            live=live,
        )
    except ValueError as exc:
        if as_json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"[launch] request invalid: {exc}")
            print(
                "(hint: ensure SHOPAI_SHOPIFY_URL is set; "
                "use --live only with real Shopify token)"
            )
        sys.exit(2)
    bundle = PublisherBundle()
    result = bundle.launch(req)
    if as_json:
        print(json.dumps(result.as_dict(), indent=2))
        return
    status = "✓" if result.ok else "✗"
    mode = "DRY-RUN" if result.dry_run else "LIVE"
    print(
        f"[publish {status} {mode}] decision={result.decision_id}"
    )
    print(f"  product_id     : {result.product_id}")
    print(f"  product_handle : {result.product_handle}")
    print(f"  campaign_id    : {result.campaign_id}")
    print(f"  tracking_url   : {result.tracking_url}")
    if not result.ok:
        print(f"  note           : {result.note}")
    print("  steps:")
    for s in result.steps:
        icon = {
            "success": "✓", "dry_run": "·",
            "error": "✗",
        }.get(s.status, "?")
        print(f"    {icon} {s.name}: {s.status}")
        if s.error:
            print(f"        error: {s.error}")
    if not result.ok:
        sys.exit(1)


def _cmd_activate(
    *,
    campaign_id: str,
    budget: float,
    auto_approve: bool,
    live: bool,
    as_json: bool,
) -> None:
    """Run campaign_activator to flip PAUSED→ACTIVE."""
    from execution.launch.campaign_activator import (
        ActivateRequest, CampaignActivator,
    )
    try:
        req = ActivateRequest(
            campaign_id=campaign_id,
            daily_budget_usd=budget,
            auto_approve=auto_approve,
            live=live,
        )
    except ValueError as exc:
        if as_json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"[activate] request invalid: {exc}")
        sys.exit(2)
    activator = CampaignActivator()
    result = activator.activate(req)
    if as_json:
        print(json.dumps(result.as_dict(), indent=2))
        return
    verdict_icon = {
        "activated": "✓",
        "dry_run": "·",
        "pending": "?",
        "blocked": "✗",
    }.get(result.verdict, "?")
    print(
        f"[activate {verdict_icon} {result.verdict.upper()}] "
        f"campaign={result.campaign_id}"
    )
    print(f"  decision_id : {result.decision_id}")
    if result.block_reason:
        print(f"  blocked     : {result.block_reason}")
    if result.pending_reason:
        print(f"  pending     : {result.pending_reason}")
    print("  steps:")
    for s in result.steps:
        icon = {
            "ok": "✓", "dry_run": "·",
            "blocked": "✗", "pending": "?",
            "error": "✗",
        }.get(s.status, "?")
        print(
            f"    {icon} {s.name}: {s.status} "
            f"— {s.note}"
        )
    if result.verdict == "blocked":
        sys.exit(1)
    if result.verdict == "pending":
        sys.exit(2)


def _cmd_autopilot(
    *,
    seeds: str,
    peers: str,
    max_launches: int,
    top_n: int,
    budget: float,
    platform: str,
    auto_activate: bool,
    live: bool,
    as_json: bool,
) -> None:
    """Full-autonomy chain: discovery → publish → activate."""
    from execution.launch.autopilot import (
        Autopilot, AutopilotRequest,
    )
    from agents.research.sources.manual_seed import (
        ManualSeedSource,
    )
    from agents.research.sources.peer_store_observer import (
        PeerStoreObserverSource,
    )
    from agents.research.sources.cj_dropshipping import (
        CJDropshippingSource,
    )
    from agents.research.sources.aliexpress_scraper import (
        AliExpressScraperSource,
    )
    # Build sources from CLI flags + env
    sources = []
    seed_path = Path(seeds) if seeds else None
    if seed_path and seed_path.exists():
        sources.append(ManualSeedSource(seed_path))
    peer_list = [
        p.strip() for p in peers.split(",") if p.strip()
    ]
    if peer_list:
        sources.append(
            PeerStoreObserverSource(peer_list),
        )
    # CJ auto-enables on CJ_EMAIL + CJ_API_KEY
    cj = CJDropshippingSource()
    if cj.is_available():
        sources.append(cj)
    # AliExpress opt-in via env gate
    ali = AliExpressScraperSource()
    if ali.is_available():
        sources.append(ali)
    if not sources:
        msg = (
            "No winner sources available. "
            "Either create --seeds file or pass --peers. "
            "See 'shopai doctor --snippet' for template."
        )
        if as_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"[autopilot] {msg}")
        sys.exit(2)
    shop_url = os.environ.get(
        "SHOPAI_SHOPIFY_URL", "",
    )
    api_key = os.environ.get(
        "SHOPAI_SHOPIFY_KEY",
        os.environ.get(
            "SHOPAI_SHOPIFY_CLIENT_SECRET", "",
        ),
    )
    meta_account = os.environ.get(
        "META_ADS_ACCOUNT_ID",
        os.environ.get("meta_ads_account_id", ""),
    )
    try:
        req = AutopilotRequest(
            shop_url=shop_url,
            api_key=api_key,
            winner_sources=sources,
            max_launches=max_launches,
            top_n=top_n,
            ad_budget_daily=budget,
            platform=platform,
            meta_account_id=meta_account,
            auto_activate=auto_activate,
            live=live,
        )
    except ValueError as exc:
        if as_json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"[autopilot] request invalid: {exc}")
        sys.exit(2)
    pilot = Autopilot()
    run = pilot.run(req)
    if as_json:
        print(json.dumps(run.as_dict(), indent=2))
        return
    mode = "DRY-RUN" if run.dry_run else "LIVE"
    print(
        f"[autopilot {mode}] run={run.id} "
        f"examined={run.winners_examined} "
        f"ranked={run.winners_ranked} "
        f"launches={len(run.launches)} "
        f"successful={run.successful_launches}"
    )
    for l in run.launches:
        pub_icon = {
            "ok": "✓", "dry_run": "·", "error": "✗",
        }.get(l.publish_verdict, "?")
        act_icon = {
            "activated": "✓", "dry_run": "·",
            "pending": "?", "blocked": "✗",
            "skipped": "-", "error": "✗",
        }.get(l.activate_verdict, "?")
        print(
            f"  [{pub_icon}/{act_icon}] {l.winner_title[:40]}"
        )
        print(
            f"      decision : {l.decision_id}"
        )
        if l.product_handle:
            print(
                f"      handle   : {l.product_handle}"
            )
        if l.campaign_id:
            print(
                f"      campaign : {l.campaign_id}"
            )
        if l.block_reason:
            print(
                f"      blocked  : {l.block_reason}"
            )
    if run.successful_launches == 0 and run.launches:
        sys.exit(1)


# ── Self-revision journal (Sprint 2) ────────────────────────

def _cmd_pending(
    *, limit: int, as_json: bool,
) -> None:
    """Show revision_journal proposals awaiting owner approval."""
    from core.brain.brain_facade import _revision_journal
    journal = _revision_journal()
    pending = journal.by_status("proposed")
    pending = pending[:limit]
    if as_json:
        print(json.dumps(
            [p.as_dict() for p in pending], indent=2,
        ))
        return
    if not pending:
        print("No pending proposals.")
        return
    print(f"Pending proposals ({len(pending)}):")
    for p in pending:
        print(
            f"  [{p.id[:10]}] kind={p.kind} "
            f"target={p.target} "
            f"evidence={p.evidence_score:.2f}"
        )
        print(f"      new: {p.new_value}")
        print(f"      why: {p.reason}")


def _cmd_approve(
    *, revision_id: str, apply_too: bool,
) -> None:
    """Approve a pending revision → accepted (or applied)."""
    from core.brain.brain_facade import _revision_journal
    journal = _revision_journal()
    try:
        rev = journal.accept(revision_id)
    except ValueError as exc:
        print(f"[approve] {exc}")
        sys.exit(2)
    print(
        f"[approve ✓] {rev.id[:10]} → accepted "
        f"(target={rev.target})"
    )
    if apply_too:
        try:
            applied = journal.mark_applied(rev.id)
            print(
                f"[apply ✓] {applied.id[:10]} → applied"
            )
        except ValueError as exc:
            print(f"[apply] {exc}")
            sys.exit(2)


def _cmd_reject(*, revision_id: str) -> None:
    """Reject a pending revision."""
    from core.brain.brain_facade import _revision_journal
    journal = _revision_journal()
    try:
        rev = journal.reject(revision_id)
    except ValueError as exc:
        print(f"[reject] {exc}")
        sys.exit(2)
    print(
        f"[reject ✗] {rev.id[:10]} → rejected "
        f"(target={rev.target})"
    )


def _cmd_distill(
    *, window: int, as_json: bool,
) -> None:
    """Run launch_learner — episodes → rules → journal."""
    from agents.learning.launch_learner import LaunchLearner
    learner = LaunchLearner()
    report = learner.distill(window_limit=window)
    if as_json:
        print(json.dumps(report.as_dict(), indent=2))
        return
    print(
        f"[distill] examined={report.episodes_examined} "
        f"clusters={report.clusters_formed} "
        f"proposals={len(report.proposals)} "
        f"accepted={report.accepted}"
    )
    for p in report.proposals:
        icon = {
            "accept": "✓", "defer": "?", "skip": "-",
            "reject_all": "✗",
        }.get(p.arbitration_verdict, "?")
        print(
            f"  [{icon}] {p.statement[:80]}"
        )
        if p.journal_revision_id:
            print(
                f"      → journal rev "
                f"{p.journal_revision_id[:10]}"
            )
        elif p.note:
            print(f"      note: {p.note[:70]}")


def _cmd_report(
    *, hours: float, as_json: bool,
) -> None:
    """Compose + render the launch digest (v38+)."""
    from agents.learning.launch_digest import (
        compose_digest,
    )
    digest = compose_digest(period_hours=hours)
    if as_json:
        print(json.dumps(digest.as_dict(), indent=2))
        return
    print(digest.as_text())


def _cmd_publications(
    *, limit: int, as_json: bool,
) -> None:
    """Show recent publisher_bundle.recent() entries."""
    from execution.launch.publisher_bundle import (
        PublisherBundle,
    )
    bundle = PublisherBundle()
    recent = bundle.recent(limit=limit)
    if as_json:
        print(json.dumps(
            [r.as_dict() for r in recent],
            indent=2,
        ))
        return
    if not recent:
        print(
            "No publications yet (in-process history; "
            "run under a daemon for persistent history)."
        )
        return
    print(f"Recent publications ({len(recent)}):")
    for r in recent:
        icon = "✓" if r.ok else "✗"
        mode = "dry" if r.dry_run else "live"
        print(
            f"  {icon} [{mode}] {r.decision_id} "
            f"handle={r.product_handle} "
            f"campaign={r.campaign_id}"
        )


def _cmd_activations(
    *, limit: int, as_json: bool,
) -> None:
    """Show recent campaign_activator.recent() entries."""
    from execution.launch.campaign_activator import (
        CampaignActivator,
    )
    activator = CampaignActivator()
    recent = activator.recent(limit=limit)
    if as_json:
        print(json.dumps(
            [r.as_dict() for r in recent],
            indent=2,
        ))
        return
    if not recent:
        print("No activations yet.")
        return
    print(f"Recent activations ({len(recent)}):")
    for r in recent:
        icon = {
            "activated": "✓", "dry_run": "·",
            "pending": "?", "blocked": "✗",
        }.get(r.verdict, "?")
        print(
            f"  {icon} {r.verdict:10s} campaign={r.campaign_id} "
            f"decision={r.decision_id}"
        )


def _cmd_predict(args) -> None:
    from core.brain.world_model_calibration import (
        get_world_model_calibration,
    )
    calib = get_world_model_calibration()
    pred = calib.predict(
        action=args.action,
        kpi=args.kpi,
        context={
            "niche": args.niche,
            "price_band": args.price_band,
            "margin_band": args.margin_band,
            "copy_tone": args.tone,
        },
    )
    if args.json:
        print(json.dumps(pred.as_dict(), indent=2))
        return
    band_mark = {
        "tight": "✓", "moderate": "·",
        "loose": "!", "uninformed": "?",
    }.get(pred.band, "?")
    print(
        f"{band_mark} Prediction — action={args.action} "
        f"kpi={args.kpi}"
    )
    print()
    print(
        f"  Base mean:              {pred.mean:.3f}"
    )
    print(
        f"  Base stdev:             {pred.stdev:.3f}"
    )
    print(
        f"  Calibrated stdev:       "
        f"{pred.calibrated_stdev:.3f}"
    )
    print(
        f"  Bias-adjusted mean:     "
        f"{pred.bias_adjusted_mean:.3f}"
    )
    print(
        f"  Band:                   {pred.band}"
    )
    print(
        f"  World-model samples:    {pred.samples}"
    )
    print(
        f"  Calibration samples:    "
        f"{pred.calibration_sample_count}"
    )
    print()
    print(f"  {pred.explanation}")


def _cmd_landed_cost(args) -> None:
    from execution.fulfillment.landed_cost import (
        LandedCostInput,
        calculate_landed_cost,
        minimum_retail_for_margin,
    )
    inp = LandedCostInput(
        fob_usd=float(args.fob),
        destination=args.destination,
        origin=args.origin or "CN",
        hts_code=args.hts or "",
        shipping_usd=float(args.shipping),
        fulfillment_fee_usd=float(args.fulfillment),
    )
    breakdown = calculate_landed_cost(
        inp, de_minimis_override=args.de_minimis,
    )
    min_retail = minimum_retail_for_margin(
        inp,
        target_margin=float(args.target_margin),
        de_minimis_override=args.de_minimis,
    )
    if args.json:
        out = breakdown.as_dict()
        out["minimum_retail_for_target_margin"] = round(
            min_retail, 2,
        )
        out["target_margin"] = float(args.target_margin)
        print(json.dumps(out, indent=2))
        return
    print(
        f"Landed cost — {args.origin}→{args.destination} "
        f"FOB ${args.fob:.2f}"
    )
    print()
    print(
        f"  FOB:                ${breakdown.fob_usd:>8.2f}"
    )
    print(
        f"  Shipping:           ${breakdown.shipping_usd:>8.2f}"
    )
    print(
        f"  Duty ({breakdown.duty_rate:.0%}):        "
        f"${breakdown.duty_usd:>8.2f}"
    )
    print(
        f"  VAT ({breakdown.vat_rate:.0%}):         "
        f"${breakdown.vat_usd:>8.2f}"
    )
    print(
        f"  Payment processing: "
        f"${breakdown.payment_processing_usd:>8.2f}"
    )
    print(
        f"  Fulfillment fee:    "
        f"${breakdown.fulfillment_fee_usd:>8.2f}"
    )
    print(f"  {'':─>40}")
    print(
        f"  TOTAL:              ${breakdown.total_usd:>8.2f}"
    )
    print()
    print(
        f"  De-minimis: "
        + (
            "APPLIED ✓" if breakdown.de_minimis_applied
            else "NOT applied"
        )
    )
    if breakdown.notes:
        for n in breakdown.notes:
            print(f"    · {n}")
    print()
    print(
        f"  Min retail for {float(args.target_margin):.0%} "
        f"margin: ${min_retail:.2f}"
    )


def _cmd_agentic_status(
    *, force: bool, as_json: bool,
) -> None:
    from core.bridge.agentic_storefront import (
        get_agentic_bridge,
    )
    bridge = get_agentic_bridge()
    statuses = bridge.status(force=force)
    if as_json:
        print(json.dumps(
            [s.as_dict() for s in statuses], indent=2,
        ))
        return
    print("Agentic storefront channels:")
    print()
    print(
        f"  {'Channel':<12} {'Enabled':>8}  "
        f"{'Orders':>8}  Note"
    )
    for s in statuses:
        mark = "✓" if s.enabled else "·"
        print(
            f"  {s.channel:<12} {mark:>8}  "
            f"{s.total_orders:>8}  {s.note}"
        )
    print()
    print(
        "Shopify admin > Online Store > Sales channels > "
        "Agentic Storefronts to toggle."
    )


def _cmd_agentic_metrics(
    *, days: int, as_json: bool,
) -> None:
    from core.bridge.agentic_storefront import (
        get_agentic_bridge,
    )
    try:
        from core.memory.memory_intelligence import (
            MemoryIntelligence,
        )
        mem = MemoryIntelligence()
        orders = mem.recent_orders(
            window_days=int(days),
        ) if hasattr(
            mem, "recent_orders",
        ) else []
    except Exception:  # noqa: BLE001
        orders = []
    bridge = get_agentic_bridge()
    metrics = bridge.aggregate(
        orders, window_days=int(days),
    )
    if as_json:
        print(json.dumps(
            [m.as_dict() for m in metrics], indent=2,
        ))
        return
    if not metrics:
        print(
            f"No agentic orders in last {days}d.\n"
            "Either channels not enabled, or no AI-"
            "referred orders yet. Check `shopai agentic "
            "status`."
        )
        return
    print(f"Agentic channel GMV — last {days}d:")
    print(
        f"  {'Channel':<12} {'Orders':>7}  "
        f"{'GMV':>10}  {'AOV':>8}"
    )
    for m in metrics:
        print(
            f"  {m.channel:<12} {m.orders:>7}  "
            f"${m.gmv_usd:>9.2f}  ${m.aov_usd:>7.2f}"
        )


def _cmd_brain_snapshot(*, as_json: bool) -> None:
    from core.brain.brain_state_synthesizer import (
        get_brain_state_synthesizer,
    )
    synth = get_brain_state_synthesizer()
    state = synth.snapshot()
    if as_json:
        print(json.dumps(state.as_dict(), indent=2))
        return
    icon = {
        "green": "✓", "yellow": "?",
        "red": "✗",
    }.get(state.crisis_level, "?")
    print(
        f"{icon} Brain snapshot — "
        f"crisis={state.crisis_level.upper()}  "
        + ("(HALTED)" if state.halted else "")
    )
    print()
    print(
        f"  Ad spend today:   "
        f"{state.tripwire_utilisation:.0%} of cap  "
        f"(${state.tripwire_remaining_usd:.2f} remaining)"
    )
    if state.rule_counts:
        inline = "  ".join(
            f"{k}={v}"
            for k, v in sorted(state.rule_counts.items())
        )
        print(f"  Learned rules:    {inline}")
    if state.memory_counts:
        inline = "  ".join(
            f"{k}={v}"
            for k, v in state.memory_counts.items()
        )
        print(f"  Memory:           {inline}")
    if state.trust_top:
        names = ", ".join(
            f"{s}({t:.0%})"
            for s, t in state.trust_top[:3]
        )
        print(f"  Top sources:      {names}")
    print(
        f"  Decisions logged: {state.rationale_total}"
    )
    print()
    if state.priorities:
        print("Priorities:")
        for p in state.priorities:
            mark = {
                "critical": "✗",
                "warning": "!",
                "info": "·",
            }.get(p.level, "·")
            print(f"  {mark} [{p.level}] {p.message}")
            if p.detail:
                print(f"      {p.detail}")
    else:
        print("Priorities: (none — system idle)")
    if state.notes:
        print()
        print("Notes:")
        for n in state.notes:
            print(f"  • {n}")


def _cmd_vault_sweep(
    *, vault: str, dry_run: bool, as_json: bool,
) -> None:
    from core.adapters.obsidian.read_back import (
        ObsidianReadBack,
    )
    path = vault or os.environ.get(
        "OBSIDIAN_VAULT_PATH", "",
    )
    if not path:
        print(
            "Vault path missing — pass --vault or set "
            "OBSIDIAN_VAULT_PATH."
        )
        return
    rb = ObsidianReadBack(vault_path=path)
    if not rb.is_available():
        print(f"Vault path not a directory: {path}")
        return
    sink = None if dry_run else _default_constraint_sink()
    report = rb.sweep(constraint_sink=sink)
    if as_json:
        print(json.dumps(report.as_dict(), indent=2))
        return
    print(f"Vault sweep: {path}")
    print(f"  Scanned:           {report.scanned}")
    print(f"  Applied:           {report.applied}")
    print(
        f"  Skipped inactive:  {report.skipped_inactive}"
    )
    print(
        f"  Skipped expired:   {report.skipped_expired}"
    )
    print(
        f"  Skipped invalid:   {report.skipped_invalid}"
    )
    if report.errors:
        print()
        print("  Errors:")
        for e in report.errors:
            print(f"    • {e}")


def _default_constraint_sink():
    """Wrap behavioral_constraint_registry in a register()
    shim that matches the ObsidianReadBack contract. Returns
    None silently when the registry isn't reachable."""
    try:
        from core.brain.behavioral_constraint_registry import (
            BehavioralConstraintRegistry,
        )
    except Exception:  # noqa: BLE001
        return None

    class _Sink:
        def __init__(self):
            self._reg = BehavioralConstraintRegistry()

        def register(
            self, *, constraint_id, kind, scope,
            priority, note, source,
        ):
            # Behavioral constraints in ShopAI use a different
            # shape; we store a light-weight record in the
            # registry's note store so owner vault rules surface
            # in 'shopai brain' reports without requiring a
            # schema migration.
            try:
                self._reg.register_note(
                    note_id=constraint_id,
                    kind=kind,
                    scope=scope,
                    priority=priority,
                    note=note,
                    source=source,
                )
            except AttributeError:
                # Older registries don't expose register_note;
                # fall through silently so the sweep still
                # reports the applied_id.
                pass
    return _Sink()


def _cmd_explain_decision(
    *, decision_id: str, as_json: bool,
) -> None:
    from core.decision.rationale_ledger import (
        get_rationale_ledger,
    )
    ledger = get_rationale_ledger()
    if as_json:
        rec = ledger.get(decision_id)
        if rec is None:
            print(json.dumps(
                {"error": "not found"}, indent=2,
            ))
            return
        print(json.dumps(rec.as_dict(), indent=2))
        return
    print(ledger.explain(decision_id))


def _cmd_explain_recent(
    *, limit: int, as_json: bool,
) -> None:
    from core.decision.rationale_ledger import (
        get_rationale_ledger,
    )
    ledger = get_rationale_ledger()
    records = ledger.recent(limit=limit)
    if as_json:
        print(json.dumps(
            [r.as_dict() for r in records], indent=2,
        ))
        return
    if not records:
        print(
            "No rationales recorded yet. Run a launch via "
            "`shopai autopilot` to populate."
        )
        return
    print(f"Recent decisions ({len(records)}):")
    for r in records:
        ts = time.strftime(
            "%Y-%m-%d %H:%M:%SZ",
            time.gmtime(r.ts),
        )
        print(
            f"  {ts}  {r.decision_id:24s}  "
            f"nodes={r.node_count:>3}  "
            f"{r.summary[:40]}"
        )


def _cmd_trust_status() -> None:
    from core.data.source_trust_calibrator import (
        get_calibrator,
    )
    c = get_calibrator()
    ranked = c.ranked()
    if not ranked:
        print(
            "No sources registered yet. Use 'shopai trust "
            "baseline --source NAME --trust 0.5' to add one."
        )
        return
    print("Source trust (ranked):")
    print(
        f"  {'Source':<22} {'Trust':>6}  "
        f"{'Samples':>8}  {'Win EMA':>8}  "
        f"{'Err EMA':>8}"
    )
    for name, trust in ranked:
        stats = c.get(name)
        print(
            f"  {name:<22} {trust:>6.2f}  "
            f"{stats.samples:>8d}  "
            f"{stats.win_ema:>8.2%}  "
            f"{stats.error_rate_ema:>8.2%}"
        )


def _cmd_trust_set_baseline(
    *, source: str, trust_value: float,
) -> None:
    from core.data.source_trust_calibrator import (
        get_calibrator,
    )
    c = get_calibrator()
    c.register(source, baseline_trust=trust_value)
    print(
        f"✓ {source} baseline trust set to "
        f"{trust_value:.2f}"
    )


def _cmd_memory_status() -> None:
    from core.memory.consolidator import get_consolidator
    c = get_consolidator()
    s = c.stats()
    print("Memory consolidator — episode → concept → procedure")
    print(f"  Episodes:         {s['episodes']}")
    print(f"  Concepts:         {s['concepts']}")
    print(f"  Procedures:       {s['procedures']}")
    print(f"  Cold archive:     {s['cold_archive']}")
    print()
    print(
        f"  min_episodes→concept:           "
        f"{s['min_episodes_for_concept']}"
    )
    print(
        f"  min_concept_refs→procedure:     "
        f"{s['min_concept_refs_for_procedure']}"
    )
    print(
        f"  min_success_rate:               "
        f"{s['min_success_rate']:.0%}"
    )
    print(
        f"  stale_after:                    "
        f"{int(s['stale_after_s'] / 86400)}d"
    )


def _cmd_memory_consolidate(*, as_json: bool) -> None:
    from core.memory.consolidator import get_consolidator
    c = get_consolidator()
    report = c.consolidate()
    if as_json:
        print(json.dumps(report.as_dict(), indent=2))
        return
    print("✓ Consolidation sweep complete")
    print(
        f"  Episodes seen:       {report.episodes_seen}"
    )
    print(
        f"  Concepts promoted:   "
        f"{report.concepts_promoted}"
    )
    print(
        f"  Procedures promoted: "
        f"{report.procedures_promoted}"
    )
    print(f"  Stale decayed:       {report.stale_decayed}")
    print(f"  Cold archived:       {report.cold_archived}")


def _cmd_memory_concepts(
    *, limit: int, as_json: bool,
) -> None:
    from core.memory.consolidator import get_consolidator
    c = get_consolidator()
    concepts = c.concepts(limit=limit)
    if as_json:
        print(json.dumps(
            [c.as_dict() for c in concepts], indent=2,
        ))
        return
    if not concepts:
        print("No concepts yet.")
        return
    print(f"Top {len(concepts)} concepts:")
    for cc in concepts:
        procedure_mark = " →P" if cc.promoted_to_procedure else ""
        print(
            f"  [{cc.concept_id[:8]}] "
            f"{cc.signature:18s}  "
            f"ev={cc.evidence_count:>3} "
            f"refs={cc.refs:>3} "
            f"succ={cc.success_rate:.0%} "
            f"prio={cc.priority:.2f}"
            f"{procedure_mark}"
        )


def _cmd_memory_procedures(
    *, limit: int, as_json: bool,
) -> None:
    from core.memory.consolidator import get_consolidator
    c = get_consolidator()
    procs = c.procedures(limit=limit)
    if as_json:
        print(json.dumps(
            [p.as_dict() for p in procs], indent=2,
        ))
        return
    if not procs:
        print("No procedures promoted yet.")
        return
    print(f"Promoted procedures ({len(procs)}):")
    for p in procs:
        print(
            f"  [{p.procedure_id[:8]}] "
            f"{p.signature:22s}  "
            f"refs={p.refs:>3} "
            f"success={p.success_rate:.0%}"
        )


def _cmd_brain_learned_status() -> None:
    from core.learning.rulebook import get_rulebook
    book = get_rulebook()
    s = book.stats()
    print("RuleBook — what the brain has learned")
    print(f"  Total rules:      {s['total_rules']}")
    for status, count in (
        s.get("by_status") or {}
    ).items():
        print(f"    {status:12s}  {count}")
    print()
    print(
        f"  Auto-activate:    {s['min_evidence_for_active']}"
        f" evidence @ "
        f"{s['min_win_rate_for_active']:.0%} win-rate"
    )
    print(
        f"  Auto-kill:        "
        f"{s['kill_after_applied']} applied @ "
        f"< {s['kill_win_rate_floor']:.0%} win-rate"
    )


def _cmd_brain_learned_top(
    *, limit: int, as_json: bool,
) -> None:
    from core.learning.rulebook import get_rulebook
    book = get_rulebook()
    rules = book.top_by_confidence(limit=limit)
    if as_json:
        print(json.dumps(
            [r.as_dict() for r in rules], indent=2,
        ))
        return
    if not rules:
        print("No learned rules yet.")
        return
    print(
        f"Top {len(rules)} rules by confidence:"
    )
    print(
        f"  {'Status':>10}  {'Conf':>5}  "
        f"{'Win%':>5}  {'N':>3}  Pattern → Action"
    )
    for r in rules:
        print(
            f"  {r.status:>10}  "
            f"{r.confidence:>5.2f}  "
            f"{r.win_rate_ema:>5.0%}  "
            f"{r.applied_count:>3}  "
            f"{r.pattern[:40]:40s} → {r.action}"
        )


def _cmd_brain_learned_list(
    *, status: str, limit: int, as_json: bool,
) -> None:
    from core.learning.rulebook import get_rulebook
    book = get_rulebook()
    rules = book.by_status(status, limit=limit)
    if as_json:
        print(json.dumps(
            [r.as_dict() for r in rules], indent=2,
        ))
        return
    if not rules:
        print(f"No {status} rules.")
        return
    print(f"{status.upper()} rules ({len(rules)}):")
    for r in rules:
        print(
            f"  [{r.rule_id[:10]}] "
            f"{r.origin:18s}  "
            f"evidence={r.evidence_count:>3}  "
            f"applied={r.applied_count:>3}  "
            f"win_ema={r.win_rate_ema:.0%}"
        )
        print(
            f"      {r.pattern}  →  {r.action}"
        )
        if r.note:
            print(f"      note: {r.note}")


def _cmd_niches(
    *,
    candidate_limit: int,
    show_limit: int,
    skip_trends: bool,
    as_json: bool,
) -> None:
    """Discover + rank niches from winner sources. Trend-enriched
    by default unless --no-trends."""
    from agents.research.niche_discoverer import (
        build_default_niche_discoverer,
    )
    # Pull candidates from the autopilot's shared winner searcher
    try:
        from agents.research.winner_searcher import (
            WinnerSearcher,
        )
        from agents.research.sources.manual_seed import (
            ManualSeedSource,
        )
        searcher = WinnerSearcher(
            sources=[ManualSeedSource()],
        )
        search_result = searcher.search(
            per_source_limit=candidate_limit,
            top_n=max(candidate_limit, show_limit),
            publish=False,
        )
        pool = [s.candidate for s in search_result.ranked]
    except Exception as exc:
        print(f"Winner search failed: {exc}")
        return
    discoverer = build_default_niche_discoverer(
        attach_trend_scorer=not skip_trends,
    )
    reports = discoverer.discover(pool, persist=True)[:show_limit]
    if as_json:
        print(json.dumps(
            [r.as_dict() for r in reports], indent=2,
        ))
        return
    if not reports:
        print(
            "No niches discovered. Seed winners with "
            "winner_seeds.json or configure CJ/AliExpress."
        )
        return
    print(
        f"Top {len(reports)} niches "
        + ("(trend-enriched)" if not skip_trends else "(rollup only)")
    )
    print()
    print(
        f"  {'Niche':<12} {'Cnt':>4} {'Mgn':>6} "
        f"{'Dmd':>6} {'Sat':>5} {'Trend':>6} "
        f"{'Rank':>7}  Dir"
    )
    for r in reports:
        arrow = {
            "rising": "↑",
            "falling": "↓",
            "stable": "·",
        }.get(r.trend_direction, "?")
        print(
            f"  {r.label:<12} {r.candidate_count:>4} "
            f"{r.avg_margin:>6.0%} "
            f"{r.avg_demand:>6.1f} "
            f"{r.saturation_score:>5.2f} "
            f"{r.trend_signal_score:>6.2f} "
            f"{r.ranked_score:>7.3f}  {arrow}"
        )


def _cmd_plan_quarter(args) -> None:
    from core.planning.quarterly_planner import (
        QuarterlyGoal,
        build_quarterly_plan,
    )
    now = time.time()
    weeks = max(1, int(args.weeks))
    goal = QuarterlyGoal(
        revenue_target_monthly_usd=float(
            args.monthly_target,
        ),
        start_ts=now,
        deadline_ts=now + weeks * 7 * 24 * 3600.0,
        sku_target=int(args.sku_target),
        roas_target=float(args.roas_target),
        ramp_curve=args.ramp,
        niche=args.niche or "",
    )
    plan = build_quarterly_plan(goal)
    if args.json:
        print(json.dumps(plan.as_dict(), indent=2))
        return
    print(
        f"Quarterly plan — {weeks} weeks, "
        f"${goal.revenue_target_monthly_usd:,.0f}/mo target"
    )
    print(
        f"  Ramp: {goal.ramp_curve}  "
        f"SKU target: {goal.sku_target}  "
        f"ROAS floor: {goal.roas_target:.2f}"
    )
    print()
    print(
        f"  {'Week':>4}  {'Date':>10}  "
        f"{'Cum rev':>10}  {'SKUs':>4}  {'ROAS':>5}"
    )
    for m in plan.milestones:
        date_str = time.strftime(
            "%Y-%m-%d", time.gmtime(m.target_ts),
        )
        print(
            f"  {m.week_index:>4}  {date_str}  "
            f"${m.cumulative_revenue_usd:>9,.0f}  "
            f"{m.skus_live_target:>4}  "
            f"{m.roas_target:>5.2f}"
        )


def _cmd_plan_checkin(args) -> None:
    from core.planning.quarterly_planner import (
        QuarterlyGoal,
        build_quarterly_plan,
        check_in,
    )
    week_s = 7 * 24 * 3600.0
    weeks = max(1, int(args.weeks))
    elapsed = max(0, int(args.week_elapsed))
    # Plan started `elapsed` weeks ago; deadline at weeks * week_s
    # from start
    now = time.time()
    start_ts = now - elapsed * week_s
    deadline_ts = start_ts + weeks * week_s
    goal = QuarterlyGoal(
        revenue_target_monthly_usd=float(
            args.monthly_target,
        ),
        start_ts=start_ts,
        deadline_ts=deadline_ts,
        sku_target=int(args.sku_target),
        ramp_curve=args.ramp,
    )
    plan = build_quarterly_plan(goal)
    report = check_in(
        plan,
        current_revenue_usd=float(args.revenue),
        current_skus_live=int(args.skus_live),
        current_roas=float(args.current_roas),
        now_ts=now,
    )
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
        return
    icon = {
        "ahead": "⇧", "on_track": "✓",
        "behind": "⇩", "at_risk": "✗",
    }.get(report.verdict, "?")
    print(
        f"{icon} {report.verdict.upper()} "
        f"(ratio {report.ratio:.0%}, "
        f"missed {report.missed_milestones})"
    )
    print()
    print(f"  Reason:         {report.reason}")
    if report.current_milestone is not None:
        m = report.current_milestone
        print(
            f"  Active mile:    week {m.week_index}  "
            f"target ${m.cumulative_revenue_usd:,.0f}"
        )
    if report.next_milestone is not None:
        m = report.next_milestone
        print(
            f"  Next mile:      week {m.week_index}  "
            f"target ${m.cumulative_revenue_usd:,.0f}"
        )
    print()
    print(f"  Recommend: {report.recommendation}")


def _parse_trait_pairs(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in pairs or []:
        if "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k:
            out[k] = v
    return out


def _cmd_federation_status() -> None:
    from core.federation import get_federator
    fed = get_federator()
    stores = fed.stores()
    s = fed.stats()
    print("Multi-store federation")
    print(f"  Stores:       {len(stores)}")
    print(f"  Observations: {s.get('observations', 0)}")
    print(f"  Unique rules: {s.get('rules', 0)}")
    if stores:
        print()
        print("  Registered stores:")
        for spec in stores:
            traits = ", ".join(
                f"{k}={v}" for k, v in spec.traits.items()
            ) or "(no traits)"
            print(
                f"    • {spec.store_id} "
                f"[weight={spec.weight:.2f}]  "
                f"{traits}"
            )


def _cmd_federation_register(
    *, store: str, trait_pairs: list[str], weight: float,
) -> None:
    from core.federation import get_federator
    fed = get_federator()
    traits = _parse_trait_pairs(trait_pairs)
    fed.register_store(
        store, traits=traits, weight=weight,
    )
    print(
        f"✓ Registered {store} "
        f"[weight={weight:.2f}]  "
        + (
            ", ".join(
                f"{k}={v}" for k, v in traits.items()
            ) or "(no traits)"
        )
    )


def _cmd_federation_observe(
    *, store: str, rule: str, wins: int, uses: int,
) -> None:
    from core.federation import get_federator
    fed = get_federator()
    obs = fed.observe(
        store, rule, wins=wins, uses=uses,
    )
    print(
        f"✓ Observed {rule} @ {store}: "
        f"wins={obs.wins}, uses={obs.uses}, "
        f"rate={obs.win_rate:.2%}"
    )


def _cmd_federation_score(
    *, target: str, rule: str, as_json: bool,
) -> None:
    from core.federation import get_federator
    fed = get_federator()
    report = fed.federated_score(
        target_store=target, rule_id=rule,
    )
    if as_json:
        print(json.dumps(report.as_dict(), indent=2))
        return
    print(
        f"Federated score for rule={rule} "
        f"target={target}:"
    )
    print(
        f"  score: {report.federated_score:.4f}"
    )
    if report.contributors:
        print()
        print("  Contributors:")
        for c in report.contributors:
            print(
                f"    • {c.get('store_id')}  "
                f"weight={c.get('weight', 0):.3f}  "
                f"win_rate={c.get('win_rate', 0):.2%}  "
                f"uses={c.get('uses', 0)}"
            )
    else:
        print("  (no observations yet)")


def _cmd_federation_best(
    *, target: str, limit: int, as_json: bool,
) -> None:
    from core.federation import get_federator
    fed = get_federator()
    best = fed.best_rules_for(
        target_store=target, top_n=limit,
    )
    if as_json:
        print(json.dumps(
            [r.as_dict() for r in best], indent=2,
        ))
        return
    if not best:
        print(f"No federated rules yet for {target}.")
        return
    print(
        f"Top federated rules for {target}:"
    )
    for r in best:
        print(
            f"  • {r.rule_id:30s}  "
            f"score={r.federated_score:.4f}"
        )


def _cmd_ask_support(
    *, question: str, as_json: bool,
) -> None:
    """Preview the LX.1 first-line support answer for a question."""
    from agents.customer.support_chatbot import SupportChatbot
    bot = SupportChatbot()
    answer = bot.answer(question)
    if as_json:
        print(json.dumps(answer.as_dict(), indent=2))
        return
    icon = "✓" if answer.verdict == "answered" else "→"
    print(
        f"{icon} {answer.verdict.upper()} "
        f"(kind={answer.kind}, "
        f"confidence={answer.confidence:.2f})"
    )
    if answer.matched_rules:
        print(
            "  matched: "
            + ", ".join(answer.matched_rules)
        )
    if answer.text:
        print()
        print(answer.text)
    if answer.verdict == "escalate":
        print()
        print(
            f"  Escalate because: {answer.escalate_reason}"
        )


def _cmd_crisis_status(*, as_json: bool) -> None:
    from core.crisis.response import get_crisis_responder
    cr = get_crisis_responder()
    s = cr.stats()
    if as_json:
        print(json.dumps(s, indent=2))
        return
    state = s["state"]
    icon = {"green": "✓", "yellow": "?", "red": "✗"}.get(
        state["level"], "?",
    )
    print(
        f"{icon} Crisis level: {state['level'].upper()}"
    )
    print(f"  Halted:            {state['halted']}")
    print(f"  Reason:            {state['reason']}")
    print(
        f"  Events in window:  {state['recent_event_count']}"
    )
    if state["triggered_kinds"]:
        print(
            "  Triggered kinds:   "
            + ", ".join(state["triggered_kinds"])
        )
    print(
        f"  Window:            {int(s['window_s']/60)} min"
    )
    print(
        f"  Red threshold:     {s['red_threshold']} events"
    )
    print(
        f"  Env kill switch:   "
        f"{'set' if s['env_halt_set'] else 'not set'}"
    )


def _cmd_crisis_halt(*, reason: str) -> None:
    from core.crisis.response import get_crisis_responder
    cr = get_crisis_responder()
    cr.halt(reason=reason or "")
    print(
        "✗ Emergency halt engaged"
        + (f" ({reason})" if reason else "")
    )
    print("  Clear with: shopai crisis resume")


def _cmd_crisis_resume() -> None:
    from core.crisis.response import get_crisis_responder
    cr = get_crisis_responder()
    cr.resume()
    print("✓ Manual halt cleared")
    state = cr.detect_state()
    if state.halted:
        print(
            f"  Still halted by: {state.reason}",
        )


def _cmd_crisis_events(*, limit: int, as_json: bool) -> None:
    from core.crisis.response import get_crisis_responder
    cr = get_crisis_responder()
    events = cr.recent_events(limit=limit)
    if as_json:
        print(json.dumps(
            [e.as_dict() for e in events], indent=2,
        ))
        return
    if not events:
        print("No crisis events recorded.")
        return
    print(f"Recent crisis events ({len(events)}):")
    for ev in events:
        ts = time.strftime(
            "%Y-%m-%d %H:%M:%SZ",
            time.gmtime(ev.ts),
        )
        sev = ev.severity.upper()
        print(
            f"  {ts}  [{sev:8s}] {ev.kind:22s} "
            f"{ev.note}"
        )


def _cmd_simulate(args) -> None:
    """Pre-launch Monte Carlo projection."""
    from simulation.launch_simulator import (
        LaunchCandidate,
        simulate_launch,
    )
    c = LaunchCandidate(
        cost=float(args.cost),
        price=float(args.price),
        daily_budget_usd=float(args.budget),
        days=int(args.days),
        est_cvr_mean=float(args.cvr_mean),
        est_cvr_stddev=float(args.cvr_stddev),
        est_cpc_mean=float(args.cpc_mean),
        est_cpc_stddev=float(args.cpc_stddev),
        refund_rate=float(args.refund_rate),
    )
    proj = simulate_launch(
        c,
        n_trials=int(args.trials),
        seed=int(args.seed),
    )
    if args.json:
        print(json.dumps(proj.as_dict(), indent=2))
        return
    verdict_icon = {
        "go": "✓", "caution": "?", "stand_down": "✗",
    }.get(proj.verdict, "?")
    print(
        f"{verdict_icon} {proj.verdict.upper()}: "
        f"{proj.reason}"
    )
    print()
    print(f"  Margin:      {c.margin_ratio():.1%}")
    print(f"  Spend:       ${c.daily_budget_usd * c.days:.2f}")
    print(
        f"  Break-even:  {proj.break_even_prob:.0%}"
    )
    print(
        f"  Expected ROAS: {proj.expected_roas:.2f}x"
    )
    print(f"  Expected orders: {proj.expected_orders:.1f}")
    print()
    print("  Profit distribution:")
    print(
        f"    p25: ${proj.profit_p25:>8.2f}"
    )
    print(
        f"    p50: ${proj.profit_p50:>8.2f}"
    )
    print(
        f"    p75: ${proj.profit_p75:>8.2f}"
    )
    print(
        f"    mean ${proj.profit_mean:>7.2f} "
        f"± ${proj.profit_stddev:.2f}"
    )


def _cmd_legal(
    *,
    region: str,
    store: str,
    email: str,
    kind: str | None,
    as_json: bool,
) -> None:
    """Render L7 legal pages for a region."""
    from core.legal.compliance import render_legal_pages

    store_name = store or _infer_store_name()
    contact = email or os.environ.get(
        "SHOPAI_CONTACT_EMAIL", "",
    )
    if not contact:
        print(
            "Missing contact email — pass --email or set "
            "SHOPAI_CONTACT_EMAIL.",
        )
        return
    try:
        pageset = render_legal_pages(
            store_name=store_name,
            contact_email=contact,
            region=region,
            include=(kind,) if kind else None,
        )
    except ValueError as exc:
        print(f"Invalid input: {exc}")
        return
    if as_json:
        print(json.dumps(pageset.as_dict(), indent=2))
        return
    for page in pageset.pages:
        print(f"# ── {page.title} ({page.region}) ──")
        print()
        print(page.markdown)
        print()
        print()


def _infer_store_name() -> str:
    raw = os.environ.get("SHOPAI_SHOPIFY_URL", "")
    if not raw:
        return "Your Store"
    domain = (
        raw.replace("https://", "")
        .replace("http://", "")
        .replace(".myshopify.com", "")
        .strip("/")
    )
    return domain.replace("-", " ").title() or "Your Store"


def _cmd_owner_poll(
    *, limit: int, dry_run: bool, as_json: bool,
) -> None:
    """One-shot poll Telegram → dispatch to brain handlers."""
    from agents.owner_dialog.dispatcher import (
        OwnerDialogDispatcher,
        build_default_handlers,
    )
    from core.adapters.telegram_bot import (
        TelegramBotAdapter,
    )
    bot = TelegramBotAdapter()
    if not bot.is_available():
        print(
            "Telegram not configured — set "
            "TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID."
        )
        return
    dispatcher = OwnerDialogDispatcher(
        bot=bot,
        handlers=build_default_handlers(),
    )
    results = dispatcher.poll_and_dispatch(
        limit=limit, reply=not dry_run,
    )
    if as_json:
        print(json.dumps(
            [r.as_dict() for r in results], indent=2,
        ))
        return
    if not results:
        print("No new owner commands.")
        return
    print(f"Dispatched {len(results)} command(s):")
    for r in results:
        icon = "✓" if r.ok else "✗"
        print(
            f"  {icon} [{r.update_id}] "
            f"{r.verb or '(unknown)':10s}  "
            + (
                f"→ replied (id={r.sent_message_id})"
                if r.sent_message_id
                else "no reply sent"
            )
        )
        if r.error:
            print(f"      error: {r.error}")


def _cmd_notify(
    *, hours: float, dry_run: bool,
    chat_id: str | None, as_json: bool,
) -> None:
    """Compose launch digest and push to Telegram."""
    from agents.owner_dialog.notify import notify_owner
    result = notify_owner(
        period_hours=hours,
        dry_run=dry_run,
        chat_id=chat_id,
    )
    if as_json:
        print(json.dumps(result.as_dict(), indent=2))
        return
    if result.sent:
        print(
            f"✓ Sent digest to Telegram "
            f"(message_id={result.message_id})"
        )
        return
    if result.reason == "dry_run":
        print("— dry run — composed digest below —")
        print()
        print(result.text)
        return
    print(f"✗ Not sent: {result.reason}")
    if result.text:
        print()
        print("Preview:")
        print(result.text)


def _cmd_risk_status(*, as_json: bool) -> None:
    """Show today's ad spend rollup vs caps."""
    from core.risk.tripwire import get_risk_tripwire
    tw = get_risk_tripwire()
    s = tw.status()
    if as_json:
        print(json.dumps(s, indent=2))
        return
    lim = s["limits"]
    today = s["today"]
    cb = s["chargebacks"]
    print("Risk tripwire — today")
    print(
        f"  Ad spend:       ${today['ad_spend_usd']:.2f} / "
        f"${lim['daily_ad_spend_usd']:.2f} "
        f"({today['utilisation']:.0%})"
    )
    print(
        f"  Remaining:      ${today['remaining_usd']:.2f}"
    )
    print(
        f"  Per-campaign:   ${lim['per_campaign_cap_usd']:.2f} cap"
    )
    print(
        f"  Margin floor:   {lim['min_margin_ratio']:.2%}"
    )
    print(
        f"  Escalate at:    {lim['escalate_pct']:.0%} of daily"
    )
    print()
    print(
        f"Chargebacks (last {cb['window_days']}d): "
        f"{cb['bad']}/{cb['total']} = {cb['rate']:.2%} "
        f"(cap {lim['max_chargeback_rate']:.2%})"
    )


def _cmd_risk_limits(*, as_json: bool) -> None:
    """Show tripwire limits plus their env-var overrides."""
    from core.risk.tripwire import get_risk_tripwire
    tw = get_risk_tripwire()
    lim = tw.limits().as_dict()
    env_map = {
        "daily_ad_spend_usd": "SHOPAI_RISK_DAILY_CAP_USD",
        "per_campaign_cap_usd": "SHOPAI_RISK_PER_CAMPAIGN_CAP_USD",
        "min_margin_ratio": "SHOPAI_RISK_MIN_MARGIN",
        "max_chargeback_rate": "SHOPAI_RISK_MAX_CHARGEBACK",
        "escalate_pct": "SHOPAI_RISK_ESCALATE_PCT",
    }
    if as_json:
        out = {
            k: {
                "value": v,
                "env_var": env_map[k],
                "env_set": os.environ.get(env_map[k], ""),
            }
            for k, v in lim.items()
        }
        print(json.dumps(out, indent=2))
        return
    print("Risk tripwire — limits")
    for key, val in lim.items():
        env_name = env_map[key]
        env_val = os.environ.get(env_name, "")
        marker = f"  (env={env_val})" if env_val else ""
        print(f"  {key:22s} = {val}{marker}")
    print()
    print("Override with env vars, e.g.:")
    print("  export SHOPAI_RISK_DAILY_CAP_USD=100")


def _cmd_risk_recent(*, limit: int, as_json: bool) -> None:
    """Recent spend events booked by the tripwire."""
    from core.risk.tripwire import get_risk_tripwire
    tw = get_risk_tripwire()
    recent = tw.recent_spend(limit=limit)
    if as_json:
        print(json.dumps(recent, indent=2))
        return
    if not recent:
        print("No spend events recorded.")
        return
    print(f"Recent spend ({len(recent)}):")
    for ev in recent:
        ts = time.strftime(
            "%Y-%m-%d %H:%M:%SZ",
            time.gmtime(ev["ts"]),
        )
        camp = ev["campaign_id"] or "-"
        print(
            f"  {ts}  ${ev['amount_usd']:>7.2f}  "
            f"{ev['category']:10s}  campaign={camp}"
        )


def _cmd_status() -> None:
    from engines.registry import engine_count
    sm = _get_store_manager()
    stores = sm.list_stores()

    print("ShopAI System Status\n")
    print(f"  Engines:  {engine_count()}")
    print(f"  Stores:   {len(stores)}")
    print(f"  Active:   {sm.active_store_id or 'none'}")
    print()

    if stores:
        print("Store Data:")
        for s in stores:
            stats = sm.get_stats(s["store_id"])
            active = " *" if s.get("is_active") else ""
            print(f"  {s['store_id']}{active}: {stats['products']}p / {stats['orders']}o / {stats['customers']}c / ${stats['total_revenue']:,.0f}")
    print()

    # Sync status
    from data_pipeline.store.sync_service import SyncService
    sync = SyncService(sm)
    sync_status = sync.get_status()
    print(f"  Auto-sync: {'running' if sync_status['auto_sync_running'] else 'stopped'}")
    for si in sync_status["stores"]:
        last = si.get("last_sync")
        if last:
            age = time.time() - last
            ago = f"{int(age)}s ago" if age < 60 else f"{int(age/60)}m ago" if age < 3600 else f"{int(age/3600)}h ago"
            print(f"    {si['store_id']}: last sync {ago} ({si['last_status']})")
        else:
            print(f"    {si['store_id']}: never synced")


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
        else:
            print("Usage: shopai db {status|migrate}")
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
        _cmd_engines()
        return

    if args.command == "engine-info":
        _cmd_engine_info(args.engine_name)
        return

    if args.command == "run":
        _cmd_run(args)
        return

    if args.command == "actions":
        _cmd_actions(args)
        return

    if args.command == "auto":
        _cmd_auto(args)
        return

    if args.command == "learn":
        _cmd_learn(args)
        return

    if args.command == "pipeline":
        _cmd_pipeline(args.pipeline_name, getattr(args, "input"))
        return

    if args.command == "launch":
        _cmd_launch(args)
        return

    if args.command == "launches":
        _cmd_launches(args)
        return

    if args.command == "kill":
        _cmd_kill(args.launch_id)
        return

    if args.command == "reason":
        _cmd_reason(args)
        return

    if args.command == "ask":
        _cmd_ask(args)
        return

    if args.command == "chat":
        _cmd_chat(args)
        return

    if args.command == "why":
        _cmd_why(args)
        return

    if args.command == "digest":
        _cmd_digest(args)
        return

    if args.command == "feedback":
        _cmd_feedback(args)
        return

    if args.command == "skills":
        _cmd_skills(args)
        return

    if args.command == "plan":
        _cmd_plan(args)
        return

    if args.command == "similar":
        _cmd_similar(args)
        return

    if args.command == "competitor":
        _cmd_competitor(args)
        return

    if args.command == "health":
        _cmd_health()
        return

    if args.command == "doctor":
        _cmd_doctor(
            as_json=bool(getattr(args, "json", False)),
            network=bool(getattr(args, "network", False)),
            snippet=bool(getattr(args, "snippet", False)),
        )
        return

    if args.command == "publish":
        _cmd_publish(
            winner_json=args.winner_json,
            budget=float(args.budget),
            platform=args.platform,
            live=bool(args.live),
            as_json=bool(args.json),
        )
        return

    if args.command == "activate":
        _cmd_activate(
            campaign_id=args.campaign_id,
            budget=float(args.budget),
            auto_approve=bool(args.auto_approve),
            live=bool(args.live),
            as_json=bool(args.json),
        )
        return

    if args.command == "autopilot":
        _cmd_autopilot(
            seeds=args.seeds,
            peers=args.peers,
            max_launches=int(args.max_launches),
            top_n=int(args.top_n),
            budget=float(args.budget),
            platform=args.platform,
            auto_activate=not args.no_activate,
            live=bool(args.live),
            as_json=bool(args.json),
        )
        return

    if args.command == "pending":
        _cmd_pending(
            limit=int(args.limit),
            as_json=bool(args.json),
        )
        return

    if args.command == "approve":
        _cmd_approve(
            revision_id=args.revision_id,
            apply_too=bool(args.apply),
        )
        return

    if args.command == "reject":
        _cmd_reject(revision_id=args.revision_id)
        return

    if args.command == "distill":
        _cmd_distill(
            window=int(args.window),
            as_json=bool(args.json),
        )
        return

    if args.command == "report":
        _cmd_report(
            hours=float(args.hours),
            as_json=bool(args.json),
        )
        return

    if args.command == "publications":
        _cmd_publications(
            limit=int(args.limit),
            as_json=bool(args.json),
        )
        return

    if args.command == "activations":
        _cmd_activations(
            limit=int(args.limit),
            as_json=bool(args.json),
        )
        return

    if args.command == "predict":
        _cmd_predict(args)
        return

    if args.command == "landed-cost":
        _cmd_landed_cost(args)
        return

    if args.command == "agentic":
        action = (
            getattr(args, "agentic_action", None)
            or "status"
        )
        if action == "status":
            _cmd_agentic_status(
                force=bool(args.force),
                as_json=bool(args.json),
            )
        elif action == "metrics":
            _cmd_agentic_metrics(
                days=int(args.days),
                as_json=bool(args.json),
            )
        return

    if args.command == "brain":
        _cmd_brain_snapshot(as_json=bool(args.json))
        return

    if args.command == "vault-sweep":
        _cmd_vault_sweep(
            vault=args.vault or "",
            dry_run=bool(args.dry_run),
            as_json=bool(args.json),
        )
        return

    if args.command == "explain":
        _cmd_explain_decision(
            decision_id=args.decision_id,
            as_json=bool(args.json),
        )
        return

    if args.command == "explains":
        _cmd_explain_recent(
            limit=int(args.limit),
            as_json=bool(args.json),
        )
        return

    if args.command == "trust":
        action = (
            getattr(args, "trust_action", None) or "status"
        )
        if action == "status":
            _cmd_trust_status()
        elif action == "baseline":
            _cmd_trust_set_baseline(
                source=args.source,
                trust_value=float(args.trust),
            )
        return

    if args.command == "memory":
        action = (
            getattr(args, "mem_action", None) or "status"
        )
        if action == "status":
            _cmd_memory_status()
        elif action == "consolidate":
            _cmd_memory_consolidate(
                as_json=bool(args.json),
            )
        elif action == "concepts":
            _cmd_memory_concepts(
                limit=int(args.limit),
                as_json=bool(args.json),
            )
        elif action == "procedures":
            _cmd_memory_procedures(
                limit=int(args.limit),
                as_json=bool(args.json),
            )
        return

    if args.command == "brain-learned":
        action = (
            getattr(args, "learned_action", None)
            or "status"
        )
        if action == "status":
            _cmd_brain_learned_status()
        elif action == "top":
            _cmd_brain_learned_top(
                limit=int(args.limit),
                as_json=bool(args.json),
            )
        elif action == "list":
            _cmd_brain_learned_list(
                status=args.status,
                limit=int(args.limit),
                as_json=bool(args.json),
            )
        return

    if args.command == "niches":
        _cmd_niches(
            candidate_limit=int(args.candidates),
            show_limit=int(args.limit),
            skip_trends=bool(args.no_trends),
            as_json=bool(args.json),
        )
        return

    if args.command == "plan-quarter":
        _cmd_plan_quarter(args)
        return

    if args.command == "plan-checkin":
        _cmd_plan_checkin(args)
        return

    if args.command == "federation":
        action = (
            getattr(args, "fed_action", None) or "status"
        )
        if action == "status":
            _cmd_federation_status()
        elif action == "register":
            _cmd_federation_register(
                store=args.store,
                trait_pairs=args.trait,
                weight=float(args.weight),
            )
        elif action == "observe":
            _cmd_federation_observe(
                store=args.store,
                rule=args.rule,
                wins=int(args.wins),
                uses=int(args.uses),
            )
        elif action == "score":
            _cmd_federation_score(
                target=args.target,
                rule=args.rule,
                as_json=bool(args.json),
            )
        elif action == "best":
            _cmd_federation_best(
                target=args.target,
                limit=int(args.limit),
                as_json=bool(args.json),
            )
        return

    if args.command == "ask-support":
        _cmd_ask_support(
            question=args.question,
            as_json=bool(args.json),
        )
        return

    if args.command == "crisis":
        action = (
            getattr(args, "crisis_action", None) or "status"
        )
        if action == "status":
            _cmd_crisis_status(as_json=bool(args.json))
        elif action == "halt":
            _cmd_crisis_halt(reason=args.reason)
        elif action == "resume":
            _cmd_crisis_resume()
        elif action == "events":
            _cmd_crisis_events(
                limit=int(args.limit),
                as_json=bool(args.json),
            )
        return

    if args.command == "simulate":
        _cmd_simulate(args)
        return

    if args.command == "legal":
        _cmd_legal(
            region=args.region,
            store=args.store or "",
            email=args.email or "",
            kind=args.kind,
            as_json=bool(args.json),
        )
        return

    if args.command == "owner-poll":
        _cmd_owner_poll(
            limit=int(args.limit),
            dry_run=bool(args.dry_run),
            as_json=bool(args.json),
        )
        return

    if args.command == "notify":
        _cmd_notify(
            hours=float(args.hours),
            dry_run=bool(args.dry_run),
            chat_id=args.chat_id,
            as_json=bool(args.json),
        )
        return

    if args.command == "risk":
        action = getattr(args, "risk_action", None) or "status"
        if action == "status":
            _cmd_risk_status(as_json=bool(args.json))
        elif action == "limits":
            _cmd_risk_limits(as_json=bool(args.json))
        elif action == "recent":
            _cmd_risk_recent(
                limit=int(args.limit),
                as_json=bool(args.json),
            )
        return

    if args.command == "status":
        _cmd_status()
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
