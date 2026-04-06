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

    if args.command == "store":
        dispatch = {
            "add": _cmd_store_add,
            "list": _cmd_store_list,
            "switch": _cmd_store_switch,
            "status": _cmd_store_status,
            "connect": _cmd_store_connect,
            "remove": _cmd_store_remove,
        }
        handler = dispatch.get(args.store_action)
        if handler:
            handler(args)
        else:
            print("Usage: shopai store {add|list|switch|status|connect|remove}")
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
