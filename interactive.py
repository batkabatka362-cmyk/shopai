"""Interactive CLI — conversational interface for ShopAI.

Commands:
  help                     Show commands
  status                   System status
  health                   Health check
  engines                  List engine count
  search <query>           Search engines by name
  run <engine> [data]      Run engine with JSON data
  agent <name> <task>      Run via agent
  workflow <name>          Run workflow
  analyze [engine]         Analyze engine/system
  products                 Show Shopify products
  pricing                  Run pricing analysis
  customers                Run customer segmentation
  seo                      Run SEO audit
  forecast <values>        Forecast from comma-separated values
  subject <text>           Score email subject line
  quit                     Exit
"""
from __future__ import annotations

import json
import sys
from typing import Any


def main():
    from core.orchestrator import MainOrchestrator
    from core.bridge.shopify_bridge import ShopifyBridge

    print("ShopAI Interactive CLI")
    print("Type 'help' for commands.\n")

    orch = MainOrchestrator()
    orch.initialize()
    shopify = ShopifyBridge()

    while True:
        try:
            raw = input("shopai> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not raw:
            continue

        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        try:
            if cmd in ("quit", "exit", "q"):
                break
            elif cmd == "help":
                print(__doc__)
            elif cmd == "status":
                s = orch.get_status()
                print(f"Running: {s['running']}")
                m = s.get("metrics", {}).get("counters", {})
                print(f"Tasks: submitted={m.get('task.submitted',0)}, completed={m.get('task.completed',0)}")
            elif cmd == "health":
                h = orch.health_check()
                print(f"Status: {h['status']}")
            elif cmd == "engines":
                from engines.registry import engine_count
                print(f"Engines: {engine_count()}")
            elif cmd == "search":
                from engines.registry import list_engines
                matches = [e for e in list_engines() if arg.lower() in e]
                print(f"Found {len(matches)}: {matches[:20]}")
            elif cmd == "run":
                parts2 = arg.split(maxsplit=1)
                engine_name = parts2[0] if parts2 else ""
                data = json.loads(parts2[1]) if len(parts2) > 1 else {}
                result = orch.submit_task(engine_name, data)
                print(f"Status: {result['status']}")
                _print_result(result.get("result", {}))
            elif cmd == "agent":
                parts2 = arg.split(maxsplit=1)
                agent_name = parts2[0] if parts2 else ""
                task = parts2[1] if len(parts2) > 1 else ""
                result = orch.agent_run(agent_name, task, {})
                print(f"Status: {result.get('status')}")
            elif cmd == "workflow":
                products = shopify.fetch_products()
                result = orch.run_workflow(arg or "product_launch", {"products": products, "criteria": {}})
                print(f"Status: {result['status']} ({result['completed_steps']}/{result['total_steps']} steps, {result['elapsed_seconds']}s)")
            elif cmd == "analyze":
                if arg:
                    result = orch.analyze_engine(arg)
                else:
                    result = orch.analyze_system()
                print(json.dumps(result, indent=2, default=str)[:500])
            elif cmd == "products":
                products = shopify.fetch_products()
                for p in products:
                    print(f"  {p['name']}: ${p['price']} (cost=${p.get('cost',0)}, stock={p.get('inventory_quantity',0)})")
            elif cmd == "pricing":
                products = shopify.fetch_products()
                result = orch.submit_task("pricing", {"products": products})
                r = result.get("result", {})
                for rec in r.get("pricing_recommendations", [])[:5]:
                    print(f"  {rec.get('name')}: ${rec.get('current_price')} margin={rec.get('current_margin')}% → {rec.get('action')}")
            elif cmd == "customers":
                customers = shopify.fetch_customers()
                result = orch.submit_task("customer_segmentation", {"customer_data": customers, "segmentation_criteria": {}})
                r = result.get("result", {})
                for seg, info in r.get("rfm_segments", {}).items():
                    if info.get("count", 0) > 0:
                        print(f"  {seg}: {info['count']} customers")
            elif cmd == "seo":
                from core.intelligence import SEOIntelligence
                si = SEOIntelligence()
                products = shopify.fetch_products()
                for p in products[:3]:
                    audit = si.audit_page({"title": p["name"], "keyword": p.get("category", "product")})
                    print(f"  {p['name']}: SEO {audit['score']}/100 ({audit['grade']}) — {audit['issue_count']} issues")
            elif cmd == "forecast":
                from core.intelligence import Forecasting
                values = [float(v.strip()) for v in arg.split(",") if v.strip()]
                result = Forecasting().forecast(values, periods=7)
                print(f"  Method: {result.get('method')}")
                print(f"  Forecast: {result.get('forecast')}")
                print(f"  Trend: {result.get('trend', {}).get('direction')}")
            elif cmd == "subject":
                from core.intelligence import EmailIntelligence
                result = EmailIntelligence().score_subject_line(arg)
                print(f"  Score: {result['score']}/100 ({result['grade']})")
                for imp in result.get("improvements", []):
                    print(f"  → {imp}")
            else:
                print(f"Unknown command: {cmd}. Type 'help'.")
        except Exception as exc:
            print(f"Error: {exc}")

    orch.shutdown()
    print("Goodbye.")


def _print_result(result: dict, indent: int = 0):
    """Print result dict nicely."""
    for key, value in result.items():
        if key.startswith("_"):
            continue
        prefix = "  " * indent
        if isinstance(value, dict) and len(value) > 0:
            print(f"{prefix}{key}:")
            _print_result(value, indent + 1)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            print(f"{prefix}{key}: [{len(value)} items]")
            for item in value[:3]:
                print(f"{prefix}  {item}")
        elif isinstance(value, list):
            print(f"{prefix}{key}: {value[:5]}")
        else:
            print(f"{prefix}{key}: {value}")


if __name__ == "__main__":
    main()
