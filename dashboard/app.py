"""ShopAI Neural Command — Dashboard HTTP server.

Serves the dashboard static files and provides JSON API endpoints
for the frontend to consume. Runs standalone on port 3000.

Usage::

    python -m dashboard.app          # default port 3000
    python -m dashboard.app 8888     # custom port

The server reads live data from the adapter registry, controller,
and core systems. No external web framework — pure stdlib.
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from utils.logger import get_logger

logger = get_logger("dashboard")

STATIC_DIR = Path(__file__).parent / "static"


class DashboardAPIHandler(BaseHTTPRequestHandler):
    """Serves static files and dashboard API endpoints."""

    def do_GET(self) -> None:
        path = urlparse(self.path).path

        # API routes
        if path.startswith("/api/"):
            self._handle_api(path)
            return

        # Static file serving
        self._serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        body = self._read_body() or {}

        # NOTE: No authentication. The dashboard is intended for a
        # single operator on localhost; scheduler controls trigger real
        # side effects against the configured stores. Do not expose
        # this server on a public network.
        routes = {
            "/api/chat": self._handle_chat,
            "/api/scheduler/start": self._handle_scheduler_start,
            "/api/scheduler/stop": self._handle_scheduler_stop,
            "/api/scheduler/run-once": self._handle_scheduler_run_once,
        }
        handler = routes.get(path.rstrip("/"))
        if handler is None:
            self._json(404, {"error": "not found"})
            return
        handler(body)

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── Static file server ─────────────────────────────────

    def _serve_static(self, path: str) -> None:
        if path in ("", "/", "/index.html"):
            path = "/index.html"

        file_path = STATIC_DIR / path.lstrip("/")

        if not file_path.exists() or not file_path.is_file():
            self._json(404, {"error": "not found"})
            return

        # Security: ensure path doesn't escape static dir
        try:
            file_path.resolve().relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._json(403, {"error": "forbidden"})
            return

        content_type, _ = mimetypes.guess_type(str(file_path))
        content_type = content_type or "application/octet-stream"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    # ── API routes ─────────────────────────────────────────

    def _handle_api(self, path: str) -> None:
        routes = {
            "/api/overview": self._api_overview,
            "/api/adapters": self._api_adapters,
            "/api/graph": self._api_graph,
            "/api/analytics": self._api_analytics,
            "/api/stream": self._api_stream,
            "/api/health": self._api_health,
            "/api/cycle": self._api_cycle,
            "/api/vault": self._api_vault,
        }
        handler = routes.get(path.rstrip("/"))
        if handler:
            handler()
        else:
            self._json(404, {"error": f"unknown endpoint: {path}"})

    def _api_overview(self) -> None:
        data: dict[str, Any] = {
            "timestamp": time.time(),
            "adapters": self._get_adapter_status(),
            "system": self._get_system_health(),
            "metrics": self._get_metrics_summary(),
        }
        self._json(200, data)

    def _api_adapters(self) -> None:
        self._json(200, {"adapters": self._get_adapter_detail()})

    def _api_graph(self) -> None:
        self._json(200, self._get_graph_data())

    def _api_analytics(self) -> None:
        self._json(200, self._get_analytics_data())

    def _api_stream(self) -> None:
        self._json(200, {"events": self._get_recent_events()})

    def _api_health(self) -> None:
        try:
            from core.self_monitor import HealthChecker
            self._json(200, HealthChecker().check_all())
        except Exception:
            self._json(200, {"status": "unknown", "checks": {}})

    def _api_cycle(self) -> None:
        """Latest + recent cycle summaries from the AutoScheduler."""
        try:
            from core.system.auto_scheduler import get_scheduler
            sched = get_scheduler()
            latest = sched.get_last_summary()
            recent = sched.get_recent_summaries(limit=20)
            status = sched.get_status()
            self._json(200, {
                "has_data": latest is not None,
                "latest": latest,
                "recent": recent,
                "scheduler": {
                    "running": status.get("running", False),
                    "busy": status.get("busy", False),
                    "cycles_run": status.get("cycles_run", 0),
                    "interval": status.get("interval", 0),
                    "stores": status.get("stores", []),
                    "last_error": status.get("last_error", ""),
                },
            })
        except Exception as exc:  # noqa: BLE001
            self._json(200, {
                "has_data": False,
                "latest": None,
                "recent": [],
                "scheduler": {},
                "error": str(exc)[:120],
            })

    def _api_vault(self) -> None:
        """Vault summary: folder counts + recent wins/errors/decisions."""
        self._json(200, _collect_vault_summary())

    # ── Scheduler control (operator POSTs) ─────────────────

    def _handle_scheduler_start(self, body: dict) -> None:
        """Start the scheduler loop. Idempotent."""
        try:
            from core.system.auto_scheduler import get_scheduler
            sched = get_scheduler()

            stores = body.get("stores")
            if not isinstance(stores, list) or not all(
                isinstance(s, str) and s for s in stores
            ):
                stores = None  # fall back to scheduler default

            interval = body.get("interval")
            try:
                interval = int(interval) if interval is not None else 600
            except (TypeError, ValueError):
                interval = 600
            interval = max(60, min(interval, 24 * 3600))  # clamp 1m..24h

            out = sched.start(stores=stores, interval_seconds=interval)
            self._json(200, out)
        except Exception as exc:  # noqa: BLE001
            self._json(200, {"status": "error", "error": str(exc)[:200]})

    def _handle_scheduler_stop(self, _body: dict) -> None:
        try:
            from core.system.auto_scheduler import get_scheduler
            out = get_scheduler().stop()
            self._json(200, out)
        except Exception as exc:  # noqa: BLE001
            self._json(200, {"status": "error", "error": str(exc)[:200]})

    def _handle_scheduler_run_once(self, body: dict) -> None:
        """Fire a single cycle on a background thread. Non-blocking."""
        try:
            from core.system.auto_scheduler import get_scheduler
            store_id = body.get("store_id") or "deguar"
            if not isinstance(store_id, str) or not store_id.strip():
                self._json(400, {"status": "error",
                                 "error": "store_id must be a non-empty string"})
                return
            out = get_scheduler().run_once_async(store_id.strip())
            # 202 when queued, 200 when busy — both are informational.
            status_code = 202 if out.get("status") == "queued" else 200
            self._json(status_code, out)
        except Exception as exc:  # noqa: BLE001
            self._json(200, {"status": "error", "error": str(exc)[:200]})

    def _handle_chat(self, body: dict) -> None:
        message = body.get("message", "")
        if not message:
            self._json(400, {"error": "message required"})
            return

        # Conversation history: list of {"role": "user"|"assistant", "content": "..."}
        # The client persists this in localStorage and re-sends on each turn.
        # We clamp to a reasonable window so the prompt stays bounded.
        history = body.get("history") or []
        if not isinstance(history, list):
            history = []

        response = self._process_chat(message, history)
        self._json(200, {"response": response})

    # ── Data collectors ────────────────────────────────────

    @staticmethod
    def _iter_adapters():
        """Iterate all registered adapters via names() + get()."""
        from core.adapters import get_registry
        reg = get_registry()
        for name in reg.names():
            adapter = reg.get(name)
            if adapter is not None:
                yield adapter

    def _get_adapter_status(self) -> dict[str, Any]:
        try:
            categories: dict[str, list] = {}
            for adapter in self._iter_adapters():
                cat = getattr(adapter, "category", "other")
                cat_name = cat.value if hasattr(cat, "value") else str(cat)
                if cat_name not in categories:
                    categories[cat_name] = []
                categories[cat_name].append({
                    "name": adapter.name,
                    "configured": adapter.is_configured(),
                    "priority": getattr(adapter, "priority", 0),
                    "cost": getattr(adapter, "cost_per_call", 0),
                    "capabilities": [
                        c.value if hasattr(c, "value") else str(c)
                        for c in getattr(adapter, "capabilities", set())
                    ],
                })
            total = sum(len(v) for v in categories.values())
            configured = sum(
                1 for adapters in categories.values()
                for a in adapters if a["configured"]
            )
            return {
                "total": total,
                "configured": configured,
                "categories": categories,
            }
        except Exception as exc:
            _ = exc
            return {"total": 0, "configured": 0, "categories": {}}

    def _get_adapter_detail(self) -> list[dict]:
        try:
            result = []
            for adapter in self._iter_adapters():
                result.append({
                    "name": adapter.name,
                    "category": getattr(adapter, "category", "other"),
                    "configured": adapter.is_configured(),
                    "priority": getattr(adapter, "priority", 0),
                    "cost_per_call": getattr(adapter, "cost_per_call", 0),
                    "capabilities": [
                        c.value if hasattr(c, "value") else str(c)
                        for c in getattr(adapter, "capabilities", set())
                    ],
                })
            return result
        except Exception:
            return []

    def _get_system_health(self) -> dict:
        try:
            from core.self_monitor import HealthChecker
            return HealthChecker().check_all()
        except Exception:
            return {"status": "unknown", "checks": {}}

    def _get_metrics_summary(self) -> dict:
        try:
            from core.orchestrator import MainOrchestrator
            orch = MainOrchestrator()
            status = orch.get_status()
            return {
                "tasks": status.get("metrics", {}).get("counters", {}),
                "cache": status.get("cache_stats", {}),
                "events": status.get("event_stats", {}),
            }
        except Exception:
            return {"tasks": {}, "cache": {}, "events": {}}

    def _get_graph_data(self) -> dict:
        """Build nodes and edges for the neural map visualization."""
        nodes = []
        edges = []

        try:
            # Central brain node
            nodes.append({
                "id": "brain",
                "label": "ShopAI Brain",
                "type": "core",
                "size": 40,
            })

            # Category hub nodes
            category_map: dict[str, list] = {}
            for adapter in self._iter_adapters():
                cat = getattr(adapter, "category", "other")
                cat_name = cat.value if hasattr(cat, "value") else str(cat)
                if cat_name not in category_map:
                    category_map[cat_name] = []
                category_map[cat_name].append(adapter)

            for cat_name, adapters in category_map.items():
                cat_id = f"cat_{cat_name}"
                nodes.append({
                    "id": cat_id,
                    "label": cat_name.replace("_", " ").title(),
                    "type": "category",
                    "size": 25,
                    "count": len(adapters),
                })
                edges.append({
                    "from": "brain",
                    "to": cat_id,
                    "type": "primary",
                })

                for adapter in adapters:
                    a_id = f"adapter_{adapter.name}"
                    nodes.append({
                        "id": a_id,
                        "label": adapter.name,
                        "type": "adapter",
                        "size": 15,
                        "configured": adapter.is_configured(),
                        "priority": getattr(adapter, "priority", 0),
                    })
                    edges.append({
                        "from": cat_id,
                        "to": a_id,
                        "type": "secondary",
                    })

            # Add memory/learning nodes
            for extra in ["Memory", "Learning", "Router", "Vault"]:
                eid = f"system_{extra.lower()}"
                nodes.append({
                    "id": eid,
                    "label": extra,
                    "type": "system",
                    "size": 20,
                })
                edges.append({"from": "brain", "to": eid, "type": "system"})

        except Exception:
            nodes.append({
                "id": "brain",
                "label": "ShopAI Brain",
                "type": "core",
                "size": 40,
            })

        return {"nodes": nodes, "edges": edges}

    def _get_analytics_data(self) -> dict:
        """Aggregate analytics data for charts."""
        try:
            # Adapter usage by category
            all_adapters = list(self._iter_adapters())
            categories: dict[str, int] = {}
            configured_count = 0
            for adapter in all_adapters:
                cat = getattr(adapter, "category", "other")
                cat_name = cat.value if hasattr(cat, "value") else str(cat)
                categories[cat_name] = categories.get(cat_name, 0) + 1
                if adapter.is_configured():
                    configured_count += 1

            # LLM provider costs
            llm_costs = []
            for adapter in all_adapters:
                cat = getattr(adapter, "category", "other")
                cat_name = cat.value if hasattr(cat, "value") else str(cat)
                if cat_name == "llm":
                    llm_costs.append({
                        "name": adapter.name,
                        "cost_per_call": getattr(adapter, "cost_per_call", 0),
                        "priority": getattr(adapter, "priority", 0),
                        "configured": adapter.is_configured(),
                    })

            return {
                "adapter_categories": categories,
                "llm_providers": llm_costs,
                "total_adapters": sum(categories.values()),
                "configured_adapters": configured_count,
            }
        except Exception:
            return {
                "adapter_categories": {},
                "llm_providers": [],
                "total_adapters": 0,
                "configured_adapters": 0,
            }

    def _get_recent_events(self) -> list[dict]:
        """Get recent system events for the live stream."""
        events = []
        try:
            for adapter in self._iter_adapters():
                events.append({
                    "timestamp": time.time(),
                    "type": "adapter_status",
                    "source": adapter.name,
                    "message": f"{adapter.name} {'online' if adapter.is_configured() else 'offline'}",
                    "level": "info" if adapter.is_configured() else "warning",
                })
        except Exception:
            pass
        return events[-50:]  # Last 50 events

    # Max turns of history kept in the LLM prompt. 6 = 3 user + 3 assistant,
    # enough for follow-ups without blowing the context window on free-tier LLMs.
    _CHAT_HISTORY_WINDOW = 6

    def _process_chat(self, message: str, history: list | None = None) -> str:
        """Process a chat message through available LLM or local logic."""
        history = history or []

        # Slash commands take precedence — they never touch the LLM.
        if message.startswith("/"):
            return self._handle_slash(message)

        msg_lower = message.lower()

        # Built-in keyword commands (backwards-compat with the old chat UX).
        if "adapter" in msg_lower and ("status" in msg_lower or "list" in msg_lower):
            return self._chat_adapter_status()
        if "health" in msg_lower:
            return self._chat_health()
        if "cycle" in msg_lower or "сүүлийн" in msg_lower or "суулийн" in msg_lower:
            return self._chat_cycle()
        if "vault" in msg_lower or "ноут" in msg_lower or "тэмдэглэл" in msg_lower:
            return self._chat_vault()
        if msg_lower.strip() in {"help", "?"}:
            return self._chat_help()

        # Fall through to the LLM router with enriched context + history.
        return self._chat_via_llm(message, history)

    def _chat_via_llm(self, message: str, history: list) -> str:
        """Forward ``message`` + bounded history to the LLM router."""
        try:
            from core.adapters import get_router
            from core.adapters.base import Capability
            router = get_router()

            system_prompt = self._build_system_prompt()
            messages = self._build_messages(history, message)

            result = router.execute(
                Capability.CHAT_COMPLETE,
                {
                    "system": system_prompt,
                    "prompt": message,   # kept for adapters that only read .prompt
                    "messages": messages,
                    "max_tokens": 500,
                    "temperature": 0.3,
                },
            )
            if result.ok:
                return result.data.get("text", "I processed your request.")
        except Exception as exc:  # noqa: BLE001
            logger.debug("LLM chat failed: %s", exc)

        return (
            "I don't have an LLM adapter configured right now, so I can only "
            "handle built-in commands:\n\n"
            "- `/status` — adapter status\n"
            "- `/cycle` — latest autonomous cycle\n"
            "- `/vault` — Obsidian vault summary\n"
            "- `/health` — system health\n"
            "- `/help` — full command list\n\n"
            "Configure a Groq, OpenAI, or Claude key to enable free-form chat."
        )

    def _build_messages(self, history: list, message: str) -> list[dict]:
        """Clamp history to the window and append the new user turn.

        Normalises role names, drops malformed entries, and guarantees a
        well-formed list even when the client sends garbage.
        """
        clean: list[dict] = []
        for entry in history[-self._CHAT_HISTORY_WINDOW:]:
            if not isinstance(entry, dict):
                continue
            role = entry.get("role")
            content = entry.get("content")
            if role not in ("user", "assistant") or not isinstance(content, str):
                continue
            clean.append({"role": role, "content": content[:2000]})
        clean.append({"role": "user", "content": message})
        return clean

    def _build_system_prompt(self) -> str:
        """Assemble a context-aware system prompt so the LLM knows the
        shape of the running ShopAI instance (adapter counts, latest
        cycle, vault state) without us round-tripping for every turn.
        """
        ctx = self._build_chat_context()
        lines = [
            "You are ShopAI Assistant, an AI managing autonomous e-commerce stores.",
            "Answer concisely and directly. Prefer bullet lists over paragraphs.",
            "When the user asks about live state, use the CONTEXT block below.",
            "If the CONTEXT lacks an answer, say so — do not invent numbers.",
            "",
            "CONTEXT:",
            f"- adapters: {ctx['adapters_configured']}/{ctx['adapters_total']} online"
            f" across {ctx['adapters_categories']} categories",
            f"- system health: {ctx['system_status']}",
        ]
        if ctx["cycle_summary"]:
            lines.append(f"- latest cycle: {ctx['cycle_summary']}")
        if ctx["vault_summary"]:
            lines.append(f"- vault: {ctx['vault_summary']}")
        lines.append(
            "\nThe user can also invoke slash commands (/status, /cycle, /vault, "
            "/health, /help); those are handled outside the LLM."
        )
        return "\n".join(lines)

    def _build_chat_context(self) -> dict[str, Any]:
        """Gather a compact snapshot of live ShopAI state for the prompt.

        Each sub-call is best-effort — a missing scheduler or vault must
        never prevent the chat from responding.
        """
        ctx: dict[str, Any] = {
            "adapters_total": 0,
            "adapters_configured": 0,
            "adapters_categories": 0,
            "system_status": "unknown",
            "cycle_summary": "",
            "vault_summary": "",
        }
        try:
            ad = self._get_adapter_status()
            ctx["adapters_total"] = ad.get("total", 0)
            ctx["adapters_configured"] = ad.get("configured", 0)
            ctx["adapters_categories"] = len(ad.get("categories", {}))
        except Exception:  # noqa: BLE001
            pass
        try:
            ctx["system_status"] = self._get_system_health().get("status", "unknown")
        except Exception:  # noqa: BLE001
            pass
        try:
            from core.system.auto_scheduler import get_scheduler
            latest = get_scheduler().get_last_summary()
            if latest:
                ctx["cycle_summary"] = (
                    f"{latest.get('cycle_id', '?')} store={latest.get('store_id', '?')} "
                    f"duration={latest.get('duration_s', 0):.1f}s "
                    f"errors={latest.get('phase_error_count', 0)} "
                    f"top_action={latest.get('top_action') or 'none'}"
                )
        except Exception:  # noqa: BLE001
            pass
        try:
            vault = _collect_vault_summary()
            if vault.get("configured"):
                totals = vault.get("totals", {})
                ctx["vault_summary"] = (
                    f"{totals.get('total', 0)} notes "
                    f"(wins={totals.get('Wins', 0)} errors={totals.get('Errors', 0)} "
                    f"decisions={totals.get('Decisions', 0)} "
                    f"learned={totals.get('ShopAI/Learned', 0)})"
                )
        except Exception:  # noqa: BLE001
            pass
        return ctx

    # ── Slash commands ────────────────────────────────────

    def _handle_slash(self, message: str) -> str:
        """Dispatch a ``/command [args]`` message to the matching handler."""
        parts = message.strip().split(None, 1)
        cmd = parts[0][1:].lower()  # strip leading '/'
        args = parts[1] if len(parts) > 1 else ""
        handlers = {
            "status": lambda _a: self._chat_adapter_status(),
            "adapters": lambda _a: self._chat_adapter_status(),
            "health": lambda _a: self._chat_health(),
            "cycle": lambda _a: self._chat_cycle(),
            "vault": lambda _a: self._chat_vault(),
            "help": lambda _a: self._chat_help(),
            "clear": lambda _a: (
                "Chat history cleared. "
                "(Your browser will remove local messages.)"
            ),
        }
        handler = handlers.get(cmd)
        if handler is None:
            return (
                f"Unknown command `/{cmd}`.\n\n"
                + self._chat_help()
            )
        return handler(args)

    def _chat_adapter_status(self) -> str:
        try:
            lines = ["**Adapter Status:**\n"]
            for adapter in self._iter_adapters():
                icon = "ON" if adapter.is_configured() else "OFF"
                lines.append(f"- {adapter.name}: {icon}")
            return "\n".join(lines)
        except Exception:
            return "Unable to check adapter status."

    def _chat_health(self) -> str:
        try:
            from core.self_monitor import HealthChecker
            h = HealthChecker().check_all()
            status = h.get("status", "unknown").upper()
            checks = h.get("checks", {})
            lines = [f"**System Health: {status}**\n"]
            for name, result in checks.items():
                lines.append(f"- {name}: {result}")
            return "\n".join(lines)
        except Exception:
            return "Unable to check system health."

    def _chat_cycle(self) -> str:
        try:
            from core.system.auto_scheduler import get_scheduler
            sched = get_scheduler()
            latest = sched.get_last_summary()
            status = sched.get_status()
            if not latest:
                return (
                    "**No cycle has run yet.**\n\n"
                    "Start the scheduler or run `get_scheduler().run_once(\"your-store\")`."
                )
            hooks = latest.get("adapter_hooks", {}) or {}
            fired = [k for k in ("analytics", "crm", "helpdesk", "automation")
                     if self._hook_fired(hooks.get(k))]
            lines = [
                f"**Latest cycle — {latest.get('cycle_id', '?')}**\n",
                f"- Store: {latest.get('store_id', '?')}",
                f"- Duration: {latest.get('duration_s', 0):.2f}s",
                f"- Phase errors: {latest.get('phase_error_count', 0)}",
                f"- Actions proposed: {latest.get('actions_proposed', 0)}",
                f"- Top action: {latest.get('top_action') or '—'}",
                f"- Hooks fired: {', '.join(fired) if fired else 'none'}",
                f"\nScheduler: {status.get('cycles_run', 0)} cycle(s) run, "
                f"{'running' if status.get('running') else 'idle'}.",
            ]
            return "\n".join(lines)
        except Exception as exc:  # noqa: BLE001
            return f"Unable to read cycle state: {exc}"

    @staticmethod
    def _hook_fired(h: dict | None) -> bool:
        if not h:
            return False
        ev = (h.get("cycle_event") or {}) if isinstance(h, dict) else {}
        return bool(
            (ev and ev.get("ok"))
            or h.get("synced", 0)
            or h.get("created")
            or h.get("triggered")
        )

    def _chat_vault(self) -> str:
        try:
            data = _collect_vault_summary()
            if not data.get("configured"):
                return (
                    "**Vault not configured.**\n\n"
                    "Set `OBSIDIAN_VAULT_PATH=./vault` in your environment."
                )
            totals = data.get("totals", {}) or {}
            lines = [
                f"**Vault at `{data.get('path', '?')}`**\n",
                f"- Total notes: {totals.get('total', 0)}",
                f"- Concepts: {totals.get('Concepts', 0)}",
                f"- Knowledge: {totals.get('Knowledge', 0)}",
                f"- Wins: {totals.get('Wins', 0)}",
                f"- Errors: {totals.get('Errors', 0)}",
                f"- Decisions: {totals.get('Decisions', 0)}",
                f"- Learned patterns: {totals.get('ShopAI/Learned', 0)}",
            ]
            recent = data.get("recent_learned", [])[:3]
            if recent:
                lines.append("\n**Recent learned:**")
                for r in recent:
                    lines.append(f"- {r.get('title', '?')}")
            return "\n".join(lines)
        except Exception as exc:  # noqa: BLE001
            return f"Unable to read vault: {exc}"

    def _chat_help(self) -> str:
        return (
            "**ShopAI Assistant Commands:**\n\n"
            "- `/status` — adapter connections\n"
            "- `/health` — system health check\n"
            "- `/cycle` — latest autonomous cycle summary\n"
            "- `/vault` — Obsidian vault summary\n"
            "- `/clear` — clear the chat history\n"
            "- `/help` — this help message\n\n"
            "You can also ask natural language questions (e.g. \"How many "
            "adapters are online?\") and I'll answer using the connected LLM "
            "with live ShopAI context."
        )

    # ── Helpers ────────────────────────────────────────────

    def _read_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            return json.loads(raw) if raw else {}
        except (json.JSONDecodeError, ValueError):
            return {}

    def _json(self, status: int, data: Any) -> None:
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # Suppress default request logging


# ── Vault summary helper ─────────────────────────────────────────
#
# Module-level (not a handler method) so tests can import and
# exercise it directly without spinning an HTTP server.


_VAULT_FOLDERS_OF_INTEREST = (
    "Concepts", "Knowledge", "Wins", "Errors",
    "Decisions", "Templates", "ShopAI/Learned",
)


def _collect_vault_summary() -> dict[str, Any]:
    """Inspect the configured Obsidian vault and return a compact
    summary suitable for the dashboard Vault tab.

    Returns ``{"configured": False}`` when ``OBSIDIAN_VAULT_PATH`` is
    unset or the directory is missing. Always safe to call — any
    internal error falls back to an empty-but-well-formed response.
    """
    try:
        from core.adapters.config import get_config
        vault_raw = get_config().get("obsidian_vault_path")
    except Exception:  # noqa: BLE001
        vault_raw = None

    if not vault_raw:
        return {"configured": False, "path": "", "totals": {},
                "recent_wins": [], "recent_errors": [],
                "recent_decisions": [], "recent_learned": []}

    vault = Path(vault_raw)
    if not vault.is_dir():
        return {"configured": False, "path": str(vault_raw),
                "totals": {}, "recent_wins": [], "recent_errors": [],
                "recent_decisions": [], "recent_learned": []}

    totals: dict[str, int] = {}
    for folder in _VAULT_FOLDERS_OF_INTEREST:
        sub = vault / folder
        totals[folder] = (
            sum(1 for _ in sub.rglob("*.md")) if sub.is_dir() else 0
        )
    totals["total"] = sum(1 for _ in vault.rglob("*.md"))

    try:
        from core.adapters.obsidian.parser import parse_note
    except Exception:  # noqa: BLE001
        parse_note = None

    def _recent(folder: str, limit: int = 10) -> list[dict]:
        sub = vault / folder
        if not sub.is_dir():
            return []
        # Sort by mtime desc; we don't trust frontmatter dates for
        # ordering (user-editable, optional).
        files = sorted(
            sub.rglob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]
        out: list[dict] = []
        for f in files:
            entry = {
                "title": f.stem,
                "folder": folder,
                "mtime": f.stat().st_mtime,
            }
            if parse_note is not None:
                try:
                    n = parse_note(f, vault)
                    fm = n.get("frontmatter", {}) or {}
                    entry["title"] = str(fm.get("title") or f.stem)
                    entry["date"] = str(fm.get("date") or "")
                    entry["tags"] = list(n.get("tags", []) or [])[:6]
                    if fm.get("cycle_id"):
                        entry["cycle_id"] = str(fm["cycle_id"])
                    if fm.get("action"):
                        entry["action"] = str(fm["action"])
                except Exception:  # noqa: BLE001
                    pass
            out.append(entry)
        return out

    return {
        "configured": True,
        "path": str(vault),
        "totals": totals,
        "recent_wins": _recent("Wins"),
        "recent_errors": _recent("Errors"),
        "recent_decisions": _recent("Decisions"),
        "recent_learned": _recent("ShopAI/Learned"),
    }


def start(port: int = 3000) -> None:
    """Start the dashboard server."""
    # Bootstrap adapters so the dashboard has data to show
    try:
        from core.adapters import reset_registry, reset_config
        reset_config()
        reset_registry()

        from core.adapters.llm.bootstrap import register_all as reg_llm
        from core.adapters.search.bootstrap import register_all as reg_search
        from core.adapters.email.bootstrap import register_all as reg_email
        from core.adapters.sms.bootstrap import register_all as reg_sms
        from core.adapters.payment.bootstrap import register_all as reg_pay
        from core.adapters.browser.bootstrap import register_all as reg_browser
        from core.adapters.vector.bootstrap import register_all as reg_vector
        from core.adapters.scraper.bootstrap import register_all as reg_scraper
        from core.adapters.reviews.bootstrap import register_all as reg_reviews

        reg_llm()
        reg_search()
        reg_email()
        reg_sms()
        reg_pay()
        reg_browser()
        reg_vector()
        reg_scraper()
        reg_reviews()

        try:
            from core.adapters.ads.bootstrap import register_all as reg_ads
            reg_ads()
        except Exception:
            pass
        try:
            from core.adapters.subscription.bootstrap import register_all as reg_sub
            reg_sub()
        except Exception:
            pass
        try:
            from core.adapters.voice.bootstrap import register_all as reg_voice
            reg_voice()
        except Exception:
            pass
        try:
            from core.adapters.automation.bootstrap import register_all as reg_auto
            reg_auto()
        except Exception:
            pass

        try:
            from core.adapters.shipping.bootstrap import register_all as reg_ship
            reg_ship()
        except Exception:
            pass
        try:
            from core.adapters.image.bootstrap import register_all as reg_img
            reg_img()
        except Exception:
            pass
        try:
            from core.adapters.obsidian.bootstrap import register_all as reg_obs
            reg_obs()
        except Exception:
            pass
        try:
            from core.adapters.helpdesk.bootstrap import register_all as reg_helpdesk
            reg_helpdesk()
        except Exception:
            pass
        try:
            from core.adapters.analytics.bootstrap import register_all as reg_analytics
            reg_analytics()
        except Exception:
            pass
        try:
            from core.adapters.crm.bootstrap import register_all as reg_crm
            reg_crm()
        except Exception:
            pass

        logger.info("Adapter bootstrap complete for dashboard")
    except Exception as exc:
        logger.warning("Adapter bootstrap partial: %s", exc)

    server = HTTPServer(("0.0.0.0", port), DashboardAPIHandler)
    print(f"\n  ShopAI Neural Command")
    print(f"  http://localhost:{port}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Dashboard stopped.")


if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    start(p)
