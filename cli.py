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
    add_p.add_argument("api_key", help="Shopify Admin API access token")
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

    # ── System commands ──────────────────────────────────────
    sub.add_parser("health", help="System health check")
    sub.add_parser("status", help="Full system status")
    sub.add_parser("setup", help="Interactive setup wizard")
    sub.add_parser("start", help="Start the orchestrator")
    sub.add_parser("stop", help="Stop the orchestrator")

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
        args.store_id, args.shop_url, args.api_key,
        name=args.name, niche=args.niche, store_type=args.store_type,
    )
    print(f"✓ Store added: {args.store_id}")
    print(f"  URL: {args.shop_url}")
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

    parser.print_help()


if __name__ == "__main__":
    main()
