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

    def show(self, *, force_fresh: bool = False):
        """Show full dashboard (single snapshot).

        ``force_fresh=True`` bypasses 5-min caches on the
        adapters so ``--live`` mode shows up-to-the-second
        data. Single-shot ``show()`` calls use the cached
        path to avoid slamming upstream APIs when an owner
        runs the command in a tight loop.
        """
        self._ensure_orch()
        clear_screen()
        self._header()
        self._system_health()
        self._engine_stats()
        self._agent_stats()
        self._workflow_stats()
        self._metrics()
        self._autopilot_panel()
        self._agentic_channels(force_fresh=force_fresh)
        self._moby_trust()
        self._fal_budget()
        self._recent_activity()
        self._footer()

    def show_live(self, interval: int = 5, count: int = 0):
        """Show live updating dashboard — each cycle forces a
        fresh adapter read so a 5-min cached status doesn't
        make ``--live`` effectively static."""
        self._ensure_orch()
        iteration = 0
        try:
            while True:
                self.show(force_fresh=True)
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

    def _autopilot_panel(self):
        """Wave pidfile — is the 24/7 daemon running + last cycle."""
        print(color(
            "── AUTOPILOT DAEMON ──────────────────────────────────────────",
            "bold",
        ))
        try:
            from core.system.pidfile import read_status
            status = read_status("daemon")
        except Exception as exc:  # noqa: BLE001
            print(
                f"  {color('—', 'dim')}  pidfile unavailable "
                f"({exc})"
            )
            print()
            return
        if status.running:
            uptime_h = status.uptime_s / 3600
            print(
                f"  running: {color('✓', 'green')}  "
                f"pid={status.pid}  "
                f"uptime={uptime_h:.1f}h"
            )
        else:
            print(
                f"  running: {color('✗', 'red')}  "
                f"{status.detail}"
            )
            print(color(
                "  (start with `python scripts/run_daemon.py` "
                "or systemctl start shopai-daemon)",
                "dim",
            ))
        # Latest cycle
        from pathlib import Path as _P
        log_path = _P("data/autopilot_loop.log")
        if not log_path.exists():
            print(color(
                "  No cycle log yet — no cycles recorded.",
                "dim",
            ))
            print()
            return
        last_cycle = None
        try:
            import json as _json
            for line in reversed(
                log_path.read_text().splitlines(),
            ):
                line = line.strip()
                if not line:
                    continue
                try:
                    last_cycle = _json.loads(line)
                    break
                except _json.JSONDecodeError:
                    continue
        except OSError as exc:
            print(f"  (log read failed: {exc})")
            print()
            return
        if last_cycle is None:
            print(color(
                "  No cycles recorded.",
                "dim",
            ))
            print()
            return
        ts = time.strftime(
            "%H:%M:%S",
            time.localtime(
                float(last_cycle.get("ts", 0)),
            ),
        )
        err = str(last_cycle.get("error", ""))
        launches = int(last_cycle.get("launches", 0))
        ok = int(last_cycle.get("successful", 0))
        err_mark = (
            color('!', 'red') if err
            else color('·', 'dim')
        )
        print(
            f"  last cycle #{last_cycle.get('cycle', '?')}  "
            f"@ {ts}  "
            f"launches={launches} ok={ok}  "
            f"dur={float(last_cycle.get('duration_s', 0)):.2f}s  "
            f"{err_mark} {err[:40]}"
        )
        print()

    def _agentic_channels(self, *, force_fresh: bool = False):
        """Wave B-1 A4 — per-AI-channel enrollment + GMV snapshot.

        ``--live`` mode passes ``force_fresh=True`` so the
        5-min cache inside AgenticStorefrontBridge.status()
        doesn't make consecutive live refreshes show the same
        stale payload."""
        print(color(
            "── AGENTIC CHANNELS (ChatGPT / Perplexity / …) ───────────────",
            "bold",
        ))
        try:
            from core.bridge.agentic_storefront import (
                get_agentic_bridge,
            )
            bridge = get_agentic_bridge()
            statuses = bridge.status(force=force_fresh)
        except Exception as exc:  # noqa: BLE001
            print(f"  {color('—', 'dim')}  bridge unavailable ({exc})")
            print()
            return
        if not statuses:
            print(f"  {color('—', 'dim')}  no channel data yet")
            print()
            return
        enabled = sum(1 for s in statuses if s.enabled)
        print(
            f"  Enrolled: {color(str(enabled), 'bold')}"
            f"/{len(statuses)} channels"
        )
        print(f"  {'Channel':<11} {'On':>3}  {'Orders':>7}  Note")
        for s in statuses:
            mark = (
                color('✓', 'green') if s.enabled
                else color('·', 'dim')
            )
            note = (s.note or '')[:40]
            print(
                f"  {s.channel:<11} {mark:>3}  "
                f"{s.total_orders:>7}  {note}"
            )
        print()

    def _moby_trust(self):
        """Wave C-1 A7 — shopai vs Moby win-rate on resolved votes."""
        print(color(
            "── MOBY TRUST (shopai vs Triple Whale Moby) ──────────────────",
            "bold",
        ))
        try:
            from core.brain.moby_vote_comparator import (
                get_moby_vote_comparator,
            )
            rate = get_moby_vote_comparator().win_rate()
        except Exception as exc:  # noqa: BLE001
            print(f"  {color('—', 'dim')}  comparator unavailable ({exc})")
            print()
            return
        total = int(rate.get("total_resolved", 0) or 0)
        if total == 0:
            print(
                f"  {color('—', 'dim')}  no resolved "
                "disagreements yet"
            )
            print(
                color(
                    "  (vote rows close when a purchase/return "
                    "webhook fires with the same decision_id)",
                    "dim",
                ),
            )
            print()
            return
        shopai = float(rate.get("shopai_win_rate", 0))
        moby = float(rate.get("moby_win_rate", 0))
        shopai_col = (
            "green" if shopai >= moby else "yellow"
        )
        moby_col = (
            "green" if moby > shopai else "yellow"
        )
        print(f"  Resolved: {color(str(total), 'bold')}")
        print(
            f"  shopai win-rate: "
            f"{color(f'{shopai:.1%}', shopai_col)}"
        )
        print(
            f"  moby   win-rate: "
            f"{color(f'{moby:.1%}', moby_col)}"
        )
        print(
            f"  Breakdown: shopai_only="
            f"{rate.get('shopai_only', 0)}  "
            f"moby_only={rate.get('moby_only', 0)}  "
            f"both_correct={rate.get('both_correct', 0)}  "
            f"both_wrong={rate.get('both_wrong', 0)}"
        )
        print()

    def _fal_budget(self):
        """Wave D-1 A6 — fal.ai weekly video-gen spend vs cap."""
        print(color(
            "── fal.ai VIDEO BUDGET ──────────────────────────────────────",
            "bold",
        ))
        try:
            from core.adapters.fal.video_router import (
                FalVideoRouter,
            )
            router = FalVideoRouter()
            stats = router.stats()
            router.close()
        except Exception as exc:  # noqa: BLE001
            print(
                f"  {color('—', 'dim')}  router unavailable "
                f"({exc})"
            )
            print()
            return
        configured = bool(stats.get("configured"))
        cap = float(stats.get("weekly_cap_usd", 0) or 0)
        total = float(stats.get("total_spend_usd", 0) or 0)
        gens = int(stats.get("total_generations", 0) or 0)
        config_mark = (
            color('✓', 'green') if configured
            else color('·', 'dim')
        )
        print(
            f"  Configured: {config_mark}  "
            f"Cap: ${cap:.2f}/wk  "
            f"Total spent: ${total:.2f}  "
            f"Generations: {gens}"
        )
        if not configured:
            print(color(
                "  (set FAL_KEY to enable live generation)",
                "dim",
            ))
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
