#!/usr/bin/env python3
"""ShopAI Daemon — runs autonomous cycles continuously.

Usage:
    python scripts/run_daemon.py                  # 10 min interval
    python scripts/run_daemon.py --interval 300   # 5 min interval
    python scripts/run_daemon.py --cycles 5       # run 5 then stop

Runs 24/7 until stopped. Every cycle:
  1. Sync Shopify data
  2. Run 39-phase AI cycle
  3. Log results (structured JSON)
  4. Send notifications (alerts)
  5. Auto-fix store issues
  6. Sleep until next cycle
"""
import os, sys, time, argparse, signal

# Setup path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load env
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k] = v


# Graceful shutdown
_running = True
def _signal_handler(sig, frame):
    global _running
    print("\n[ShopAI] Shutting down gracefully...")
    _running = False

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def run_daemon(store_id="ts0efe-ih", interval=600, max_cycles=0):
    global _running

    print()
    print("=" * 55)
    print("  SHOPAI DAEMON — Autonomous Operation")
    print("=" * 55)
    print()
    print("  Store:    {}".format(store_id))
    print("  Interval: {}s ({}min)".format(interval, interval // 60))
    print("  Cycles:   {}".format(max_cycles if max_cycles else "unlimited"))
    print()

    # Load runtime settings (auto_approve / live execution come from
    # config/settings.json so operators don't have to thread CLI flags
    # through every layer)
    import json
    settings_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "settings.json",
    )
    settings = {}
    try:
        with open(settings_path) as f:
            settings = json.load(f)
    except Exception:
        pass
    auto_approve = bool(settings.get("auto_approve", False))
    live = bool(settings.get("enable_live_execution", False))
    print("  Mode:     auto_approve={} live={}".format(auto_approve, live))

    # Initialize once
    from core.autonomous.controller import AutonomousController
    ac = AutonomousController(auto_approve=auto_approve)
    ac.initialize()

    # Start dashboard
    try:
        from api.dashboard_api import start_api
        start_api(port=8080)
        print("  API:      http://localhost:8080/api/status")
    except Exception:
        pass

    try:
        from api.dashboard_ui import start_dashboard
        start_dashboard(port=8082)
        print("  Dashboard: http://localhost:8082")
    except Exception:
        pass

    print()
    print("  Running... (Ctrl+C to stop)")
    print("=" * 55)
    print()

    cycle_num = 0
    total_insights = 0
    total_actions = 0

    while _running:
        cycle_num += 1

        if max_cycles and cycle_num > max_cycles:
            print("[ShopAI] Reached {} cycles. Stopping.".format(max_cycles))
            break

        # Run cycle
        start = time.monotonic()
        try:
            result = ac.run_cycle(store_id)
            elapsed = time.monotonic() - start

            phases = len(result.get("phases", {}))
            layers = result.get("phases", {}).get("layers", {}).get("layers_run", 0)
            insights = result.get("phases", {}).get("layers", {}).get("total_insights", 0)
            smart = result.get("phases", {}).get("smart_execution", {}).get("total", 0)
            score = result.get("phases", {}).get("learning", {}).get("brain_learning", {}).get("score", 0)

            total_insights += insights
            total_actions += smart

            # Log
            from core.system.structured_logger import get_structured_logger
            sl = get_structured_logger()
            sl.log_cycle(result)
            sl.flush()

            # Notify
            try:
                from core.system.notifications import get_notifications
                notif = get_notifications()
                notif.send_cycle_summary(result)
            except Exception:
                pass

            # Print summary
            ts = time.strftime("%H:%M:%S")
            print("[{}] Cycle {:3d} | {:.1f}s | {}/12 layers | {} insights | {} actions | score {}".format(
                ts, cycle_num, elapsed, layers, insights, smart, score))

            # Print alerts
            alerts = result.get("phases", {}).get("alerts", {})
            if alerts.get("critical", 0) > 0:
                for msg in alerts.get("messages", []):
                    print("  ALERT: {}".format(msg))

        except Exception as exc:
            print("[{}] Cycle {} ERROR: {}".format(
                time.strftime("%H:%M:%S"), cycle_num, str(exc)[:80]))

            # Record error
            try:
                from core.system.structured_logger import get_structured_logger
                sl = get_structured_logger()
                sl.log("error", "daemon", str(exc)[:200])
                sl.flush()
            except Exception:
                pass

        # Wait for next cycle
        for _ in range(interval):
            if not _running:
                break
            time.sleep(1)

    # Shutdown summary
    print()
    print("=" * 55)
    print("  SHOPAI DAEMON STOPPED")
    print("=" * 55)
    print("  Cycles run:    {}".format(cycle_num))
    print("  Total insights: {}".format(total_insights))
    print("  Total actions:  {}".format(total_actions))

    # Final memory stats
    try:
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        s = mi.get_stats()
        print("  Memories:      {} (R={} S={})".format(
            s["total_memories"], s["by_level"].get("rule", 0),
            s["by_level"].get("strategy", 0)))
    except Exception:
        pass
    print("=" * 55)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ShopAI Autonomous Daemon")
    parser.add_argument("--store", default="ts0efe-ih", help="Store ID")
    parser.add_argument("--interval", type=int, default=600, help="Seconds between cycles")
    parser.add_argument("--cycles", type=int, default=0, help="Max cycles (0=unlimited)")
    args = parser.parse_args()

    run_daemon(store_id=args.store, interval=args.interval, max_cycles=args.cycles)
