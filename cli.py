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

    approvals_sub.add_parser(
        "stats", help="Per-status counts in the approval queue",
    )

    approvals_show = approvals_sub.add_parser(
        "show", help="Show full detail for one action",
    )
    approvals_show.add_argument("action_id", help="Action ID")

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

    # ── System commands ──────────────────────────────────────
    sub.add_parser("health", help="System health check")
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
    print(
        "Usage:\n"
        "  shopai knowledge export <path> [--decision-limit N]\n"
        "  shopai knowledge digest [--since N] [--limit M] "
        "[--out PATH]\n"
        "  shopai knowledge import <path>\n"
        "  shopai knowledge notes [engine|goal] [name]"
    )
    sys.exit(1)


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
    print(
        "Usage:\n"
        "  shopai approvals pending  [--engine NAME] [--limit N]\n"
        "  shopai approvals stats\n"
        "  shopai approvals show     <action_id>\n"
        "  shopai approvals approve  <action_id> [--reason ...] [--by ...] [--execute]\n"
        "  shopai approvals reject   <action_id> [--reason ...] [--by ...]\n"
        "  shopai approvals execute  <action_id>"
    )
    sys.exit(1)


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
    stats = get_approval_queue().stats()
    print("Approval queue stats:")
    for status, count in sorted(stats.items()):
        print(f"  {status:<10} {count}")


def _cmd_approvals_show(args) -> None:
    from core.approval import get_approval_queue
    action = get_approval_queue().get(args.action_id)
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

    if args.command == "pipeline":
        _cmd_pipeline(args.pipeline_name, getattr(args, "input"))
        return

    if args.command == "health":
        _cmd_health()
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
