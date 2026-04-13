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
        body = self._read_body()

        if path == "/api/chat":
            self._handle_chat(body or {})
        else:
            self._json(404, {"error": "not found"})

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

    def _handle_chat(self, body: dict) -> None:
        message = body.get("message", "")
        if not message:
            self._json(400, {"error": "message required"})
            return

        # AI chat response — uses available LLM adapter
        response = self._process_chat(message)
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

    def _process_chat(self, message: str) -> str:
        """Process a chat message through available LLM or local logic."""
        msg_lower = message.lower()

        # Built-in commands (no LLM needed)
        if "adapter" in msg_lower and ("status" in msg_lower or "list" in msg_lower):
            return self._chat_adapter_status()
        if "health" in msg_lower:
            return self._chat_health()
        if "help" in msg_lower:
            return self._chat_help()

        # Try LLM for complex queries
        try:
            from core.adapters import get_router
            from core.adapters.base import Capability
            router = get_router()
            result = router.execute(
                Capability.CHAT_COMPLETE,
                {
                    "system": (
                        "You are ShopAI Assistant, an AI managing e-commerce stores. "
                        "Answer concisely about store operations, adapters, and analytics. "
                        "Be direct and helpful."
                    ),
                    "prompt": message,
                    "max_tokens": 500,
                },
            )
            if result.ok:
                return result.data.get("text", "I processed your request.")
        except Exception:
            pass

        return (
            "I understand your question. Currently, I can help with:\n\n"
            "- **adapter status** — check which tools are connected\n"
            "- **health check** — system health overview\n"
            "- **help** — see all available commands\n\n"
            "For complex queries, configure an LLM adapter (Groq, OpenAI, or Claude)."
        )

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

    def _chat_help(self) -> str:
        return (
            "**ShopAI Assistant Commands:**\n\n"
            "- **adapter status** — show all adapter connections\n"
            "- **health** — system health check\n"
            "- **help** — this help message\n\n"
            "You can also ask natural language questions about your store, "
            "and I'll answer using the connected LLM."
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
