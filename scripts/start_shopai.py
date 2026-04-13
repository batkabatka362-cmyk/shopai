"""ShopAI Startup — single command to start the full AI system.

Usage:
    python scripts/start_shopai.py

Starts:
    1. AI system initialization
    2. Shopify store sync
    3. Full autonomous cycle
    4. Dashboard API (port 8080)
    5. Dashboard UI (port 8082)
    6. Health report
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k] = v


def main():
    print()
    print("=" * 55)
    print("  SHOPAI — Autonomous E-Commerce Intelligence")
    print("=" * 55)
    print()

    # 1. Initialize
    print("[1/6] Initializing AI system...")
    from core.autonomous.controller import AutonomousController
    ac = AutonomousController(auto_approve=False)
    ac.initialize()
    print("  OK: Controller initialized")

    # 2. Sync store
    print()
    print("[2/6] Syncing Shopify store...")
    try:
        from data_pipeline.store.sync_service import SyncService
        from data_pipeline.store.store_manager import StoreManager
        sm = StoreManager()
        sync = SyncService(sm)
        result = sync.sync_store('deguar')
        print("  OK: {} products, {} orders synced".format(
            result.get('synced', {}).get('products', {}).get('count', '?'),
            result.get('synced', {}).get('orders', {}).get('count', '?')))
    except Exception as e:
        print("  Skip: {}".format(str(e)[:50]))

    # 3. Run cycle
    print()
    print("[3/6] Running autonomous cycle...")
    start = time.monotonic()
    cycle = ac.run_cycle('deguar')
    elapsed = time.monotonic() - start
    phases = len(cycle.get('phases', {}))
    layers = cycle.get('phases', {}).get('layers', {}).get('layers_run', 0)
    insights = cycle.get('phases', {}).get('layers', {}).get('total_insights', 0)
    print("  OK: {} phases, {}/12 layers, {} insights in {:.1f}s".format(
        phases, layers, insights, elapsed))

    # 4. Start API
    print()
    print("[4/6] Starting Dashboard API...")
    try:
        from api.dashboard_api import start_api
        start_api(port=8080)
        print("  OK: http://localhost:8080/api/status")
    except Exception as e:
        print("  Skip: {}".format(str(e)[:50]))

    # 5. Start UI
    print()
    print("[5/6] Starting Dashboard UI...")
    try:
        from api.dashboard_ui import start_dashboard
        start_dashboard(port=8082)
        print("  OK: http://localhost:8082/dashboard")
    except Exception as e:
        print("  Skip: {}".format(str(e)[:50]))

    # 6. Health report
    print()
    print("[6/6] Generating health report...")
    from core.memory.intelligence import get_memory_intelligence
    from core.data.architecture import get_data_architecture
    mi = get_memory_intelligence()
    da = get_data_architecture()
    s = mi.get_stats()
    ds = da.get_stats()

    print()
    print("=" * 55)
    print("  SHOPAI RUNNING")
    print("=" * 55)
    print()
    print("  Store:      deguar (ts0efe-ih.myshopify.com)")
    print("  Phases:     {}".format(phases))
    print("  Layers:     {}/12".format(layers))
    print("  Insights:   {}".format(insights))
    print("  Memories:   {} (R={} S={})".format(
        s['total_memories'],
        s['by_level'].get('rule', 0),
        s['by_level'].get('strategy', 0)))
    print("  Data:       {} records ({}% result)".format(
        ds['total_records'], ds['result_rate']))
    print("  API:        http://localhost:8080/api/status")
    print("  Dashboard:  http://localhost:8082/dashboard")
    print()
    print("  Press Ctrl+C to stop")
    print("=" * 55)

    # Print cycle report
    report = cycle.get('_report', '')
    if report:
        print()
        print(report)

    # Keep running
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nShopAI stopped.")


if __name__ == "__main__":
    main()
