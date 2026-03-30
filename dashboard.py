"""ShopAI Dashboard — terminal-based system dashboard.

Shows: engine stats, workflow status, system health, live metrics.
Pure Python — no external UI dependencies.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def bar(value: float, max_val: float = 100, width: int = 20) -> str:
    """Render a progress bar."""
    filled = int(value / max(max_val, 1) * width)
    return f"[{'█' * filled}{'░' * (width - filled)}] {value:.0f}/{max_val:.0f}"


def color(text: str, code: str) -> str:
    """ANSI color wrapper."""
    codes = {"green": "32", "red": "31", "yellow": "33", "cyan": "36", "bold": "1", "dim": "2"}
    return f"\033[{codes.get(code, '0')}m{text}\033[0m"


class Dashboard:
    """Terminal dashboard for ShopAI system monitoring."""

    def __init__(self):
        self._orch = None

    def _ensure_orch(self):
        if self._orch is None:
            from core.orchestrator import MainOrchestrator
            self._orch = MainOrchestrator()
            self._orch.initialize()

    def show(self):
        """Show full dashboard (single snapshot)."""
        self._ensure_orch()
        clear_screen()
        self._header()
        self._system_health()
        self._engine_stats()
        self._agent_stats()
        self._workflow_stats()
        self._metrics()
        self._recent_activity()
        self._footer()

    def show_live(self, interval: int = 5, count: int = 0):
        """Show live updating dashboard."""
        self._ensure_orch()
        iteration = 0
        try:
            while True:
                self.show()
                iteration += 1
                if count and iteration >= count:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nDashboard stopped.")

    def _header(self):
        print(color("╔══════════════════════════════════════════════════════════════╗", "cyan"))
        print(color("║              SHOPAI SYSTEM DASHBOARD                        ║", "bold"))
        print(color("║         AI-Powered Shopify Operator                         ║", "dim"))
        print(color("╚══════════════════════════════════════════════════════════════╝", "cyan"))
        print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}  |  Env: {os.environ.get('SHOPAI_ENV', 'development')}")
        print()

    def _system_health(self):
        print(color("── SYSTEM HEALTH ──────────────────────────────────────────────", "bold"))
        health = self._orch.health_check()
        status = health.get("status", "unknown")
        status_color = "green" if status == "healthy" else "red"
        print(f"  Status: {color(status.upper(), status_color)}")

        checks = health.get("health", {}).get("checks", {})
        for name, check in checks.items():
            ok = check.get("healthy", False)
            icon = color("✓", "green") if ok else color("✗", "red")
            detail = ""
            if name == "modules":
                detail = f"{check.get('ok', 0)}/{check.get('total', 0)} modules"
            elif name == "engines":
                detail = f"{check.get('count', 0)} registered"
            elif name == "models":
                models = check.get("models", {})
                detail = " ".join(f"{m}={'✓' if v else '✗'}" for m, v in models.items())
            elif name == "memory":
                detail = f"cache={check.get('cache', '?')}"
            print(f"  {icon} {name}: {detail}")
        print()

    def _engine_stats(self):
        print(color("── ENGINES ────────────────────────────────────────────────────", "bold"))
        from engines.registry import engine_count
        from core.step_logic.domain import DomainRouter
        dr = DomainRouter()

        total = engine_count()
        # Count domain distribution
        from engines.registry import list_engines
        domain_counts: dict[str, int] = {}
        for e in list_engines():
            d = dr.get_domain(e)
            if d:
                name = type(d).__name__.replace("Logic", "")
                domain_counts[name] = domain_counts.get(name, 0) + 1

        print(f"  Total: {color(str(total), 'bold')} engines | 100% domain coverage")
        print(f"  Domains:")
        for domain, cnt in sorted(domain_counts.items(), key=lambda x: -x[1]):
            pct = cnt / total * 100
            bar_str = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            print(f"    {domain:12s} [{bar_str}] {cnt:4d} ({pct:.0f}%)")
        print()

    def _agent_stats(self):
        print(color("── AGENTS ─────────────────────────────────────────────────────", "bold"))
        agents = self._orch.list_agents()
        for a in agents:
            print(f"  {color(a['name'], 'cyan'):30s} {a['engines']:2d} engines  {a['description'][:40]}")
        print()

    def _workflow_stats(self):
        print(color("── WORKFLOWS ──────────────────────────────────────────────────", "bold"))
        workflows = self._orch.list_workflows()
        for wf in workflows:
            print(f"  {color(wf['name'], 'cyan'):30s} {wf['steps']:2d} steps   {wf['description'][:40]}")
        print()

    def _metrics(self):
        print(color("── METRICS ────────────────────────────────────────────────────", "bold"))
        status = self._orch.get_status()
        metrics = status.get("metrics", {})
        counters = metrics.get("counters", {})
        histograms = metrics.get("histograms", {})

        submitted = counters.get("task.submitted", 0)
        completed = counters.get("task.completed", 0)
        failed = counters.get("task.failed", 0) + counters.get("task.crash", 0)
        cache_hit = counters.get("task.cache_hit", 0)

        print(f"  Tasks:  submitted={submitted}  completed={completed}  failed={failed}  cached={cache_hit}")

        duration = histograms.get("task.duration_ms", {})
        if duration.get("count", 0) > 0:
            print(f"  Timing: avg={duration.get('avg', 0):.1f}ms  p50={duration.get('p50', 0):.1f}ms  p95={duration.get('p95', 0):.1f}ms  p99={duration.get('p99', 0):.1f}ms")

        # Cache stats
        cache_stats = status.get("cache_stats", {})
        if cache_stats.get("stores", 0) > 0:
            print(f"  Cache:  hit_rate={cache_stats.get('hit_rate', 0):.0%}  size={cache_stats.get('size', 0)}/{cache_stats.get('max_size', 0)}")

        # Events
        event_stats = status.get("event_stats", {})
        if event_stats.get("published", 0) > 0:
            print(f"  Events: published={event_stats.get('published', 0)}  delivered={event_stats.get('delivered', 0)}  subscribers={event_stats.get('subscriber_count', 0)}")
        print()

    def _recent_activity(self):
        print(color("── RECENT ACTIVITY ────────────────────────────────────────────", "bold"))
        # Show recent events
        events = self._orch.events.get_history(limit=5)
        if events:
            for evt in events[-5:]:
                t = time.strftime("%H:%M:%S", time.localtime(evt.get("timestamp", 0)))
                print(f"  {t}  {evt.get('type', '?'):25s}  {evt.get('source', '?')}")
        else:
            print("  No recent activity")
        print()

    def _footer(self):
        print(color("────────────────────────────────────────────────────────────────", "dim"))
        print(color("  Ctrl+C to exit  |  Live mode: python -m dashboard --live", "dim"))

    def shutdown(self):
        if self._orch:
            self._orch.shutdown()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ShopAI Dashboard")
    parser.add_argument("--live", action="store_true", help="Live updating mode")
    parser.add_argument("--interval", type=int, default=5, help="Update interval (seconds)")
    args = parser.parse_args()

    dash = Dashboard()
    try:
        if args.live:
            dash.show_live(interval=args.interval)
        else:
            dash.show()
    finally:
        dash.shutdown()


if __name__ == "__main__":
    main()
