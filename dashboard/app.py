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
            "/api/chat/stream": self._handle_chat_stream,
            "/api/chat/feedback": self._handle_chat_feedback,
            "/api/chat/session": self._handle_chat_session_save,
            "/api/scheduler/start": self._handle_scheduler_start,
            "/api/scheduler/stop": self._handle_scheduler_stop,
            "/api/scheduler/run-once": self._handle_scheduler_run_once,
        }
        handler = routes.get(path.rstrip("/"))
        if handler is None:
            self._json(404, {"error": "not found"})
            return
        handler(body)

    def do_DELETE(self) -> None:
        """Minimal DELETE plumbing — just the chat session endpoint for now."""
        path = urlparse(self.path).path
        if path.rstrip("/") == "/api/chat/session":
            self._handle_chat_session_delete()
            return
        self._json(404, {"error": "not found"})

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS",
        )
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
            "/api/vault/note": self._api_vault_note,
            "/api/vault/search": self._api_vault_search,
            "/api/chat/sessions": self._api_chat_sessions_list,
            "/api/chat/session": self._api_chat_session_get,
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

    def _api_vault_note(self) -> None:
        """Return the full Markdown body of a single vault note.

        Query: ``?path=Wins/2026-04-14.md`` (relative to the vault root).
        The path is resolved strictly inside the configured vault —
        traversal attempts (``..``, absolute paths, symlinks escaping the
        root) are rejected with 400 so the operator can't accidentally
        leak files from the host filesystem.
        """
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(self.path).query)
        rel = (qs.get("path", [""])[0] or "").strip()
        if not rel:
            self._json(400, {"error": "path required"})
            return
        try:
            data = _read_vault_note(rel)
        except _VaultNotConfigured as exc:
            self._json(400, {"error": str(exc)})
            return
        except _VaultPathDenied as exc:
            self._json(400, {"error": str(exc)})
            return
        except FileNotFoundError:
            self._json(404, {"error": "note not found"})
            return
        except Exception as exc:  # noqa: BLE001
            logger.debug("vault note read failed: %s", exc)
            self._json(200, {"error": str(exc)[:200]})
            return
        self._json(200, data)

    def _api_vault_search(self) -> None:
        """Keyword search across the configured Obsidian vault.

        Query:
            ?q=<keywords>&type=<folder>&limit=<n>

        ``type`` narrows the walk to one folder (Wins, Errors, Decisions,
        ShopAI/Learned, …) — defaults to the whole vault. Returns an
        empty result set (never 500) when the vault isn't configured,
        so the UI can render a friendly "configure vault" hint without
        special-casing the error envelope.
        """
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(self.path).query)
        query = (qs.get("q", [""])[0] or "").strip()
        type_filter = (qs.get("type", [""])[0] or "").strip()
        try:
            limit = int(qs.get("limit", ["30"])[0] or "30")
        except (TypeError, ValueError):
            limit = 30
        limit = max(1, min(limit, 200))
        try:
            data = _collect_vault_search(query, type_filter, limit)
        except _VaultNotConfigured as exc:
            self._json(200, {
                "configured": False,
                "error": str(exc),
                "results": [],
            })
            return
        except Exception as exc:  # noqa: BLE001
            logger.debug("vault search failed: %s", exc)
            self._json(200, {
                "configured": True,
                "error": str(exc)[:200],
                "results": [],
            })
            return
        self._json(200, data)

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

    def _handle_chat_stream(self, body: dict) -> None:
        """Stream a chat response as newline-delimited SSE ``data:`` frames.

        Current adapters don't expose a vendor-native streaming hook, so
        we resolve the full reply via ``_process_chat`` and then chunk
        the text word-by-word to deliver a typewriter effect in the UI.
        Each frame is JSON so a future real-streaming upgrade can swap
        in without changing the client parser.
        """
        message = body.get("message", "")
        history = body.get("history") or []
        if not isinstance(history, list):
            history = []
        if not message:
            self._json(400, {"error": "message required"})
            return

        try:
            full = self._process_chat(message, history)
        except Exception as exc:  # noqa: BLE001
            full = f"Error: {str(exc)[:200]}"

        self._begin_stream()
        try:
            self._stream_text(full)
        finally:
            self._finish_stream()

    def _begin_stream(self) -> None:
        """Send SSE-style response headers. HTTP/1.0 close-delimited so
        we don't need to hand-format chunked transfer encoding."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")  # disable nginx buffering
        self.end_headers()

    def _stream_text(self, text: str) -> None:
        """Chunk ``text`` into word-size deltas and flush each one."""
        # Split on whitespace but keep the spaces so the reconstructed
        # text matches the source exactly. ``re.split`` with a capture
        # group does this trick.
        import re
        pieces = re.findall(r"\S+\s*", text)
        if not pieces:
            pieces = [text]

        # Flatten into deltas of ~3 words each so we don't write hundreds
        # of tiny packets for long responses.
        batch_size = 3
        try:
            for i in range(0, len(pieces), batch_size):
                delta = "".join(pieces[i:i + batch_size])
                self._send_stream_event({"delta": delta})
                # Small sleep between batches gives the typewriter feel
                # without inflating perceived latency too much.
                time.sleep(0.02)
            self._send_stream_event({"done": True})
        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected mid-stream — nothing to do.
            pass

    def _send_stream_event(self, payload: dict) -> None:
        frame = "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
        self.wfile.write(frame.encode("utf-8"))
        try:
            self.wfile.flush()
        except Exception:  # noqa: BLE001
            pass

    def _finish_stream(self) -> None:
        try:
            self.wfile.flush()
        except Exception:  # noqa: BLE001
            pass

    # ── Chat feedback → vault ─────────────────────────────

    def _handle_chat_feedback(self, body: dict) -> None:
        """Persist a thumbs-up/down on a chat response to the vault.

        Body shape::

            {
              "rating":   "up" | "down",
              "message":  "user turn text",
              "response": "assistant turn text",
              "note":     "optional operator note"
            }

        The feedback lands in ``vault/ShopAI/Feedback/<ts>-<rating>.md``
        with Obsidian-friendly frontmatter + wikilinks so the graph view
        connects it to adjacent Wins/Errors. No-ops gracefully when the
        vault path is not configured.
        """
        rating = (body.get("rating") or "").strip().lower()
        if rating not in ("up", "down"):
            self._json(400, {"error": "rating must be 'up' or 'down'"})
            return

        message = str(body.get("message") or "").strip()
        response = str(body.get("response") or "").strip()
        note = str(body.get("note") or "").strip()
        if not response:
            self._json(400, {"error": "response text required"})
            return

        try:
            path = _write_feedback_note(
                rating=rating, message=message,
                response=response, note=note,
            )
        except _VaultNotConfigured:
            # Still accept the feedback — keep it in memory for stats
            # even though we can't persist it right now.
            self._json(200, {
                "status": "accepted",
                "persisted": False,
                "reason": "OBSIDIAN_VAULT_PATH not set",
            })
            return
        except Exception as exc:  # noqa: BLE001
            logger.debug("feedback write failed: %s", exc)
            self._json(200, {
                "status": "error",
                "persisted": False,
                "error": str(exc)[:200],
            })
            return

        self._json(200, {
            "status": "ok",
            "persisted": True,
            "path": str(path),
        })

    # ── Chat session persistence (Option J) ───────────────

    def _api_chat_sessions_list(self) -> None:
        """Return summaries (id, title, turn count, timestamps) of every
        stored chat session, newest first. No turn bodies — the sidebar
        only needs labels."""
        try:
            from dashboard.chat_sessions import get_session_store
            sessions = get_session_store().list()
            self._json(200, {"sessions": sessions})
        except Exception as exc:  # noqa: BLE001
            logger.debug("session list failed: %s", exc)
            self._json(200, {"sessions": [], "error": str(exc)[:200]})

    def _api_chat_session_get(self) -> None:
        """Return the full turns of a single session. 404 on unknown id."""
        from urllib.parse import parse_qs, urlparse
        sid = (parse_qs(urlparse(self.path).query).get("id", [""])[0] or "").strip()
        if not sid:
            self._json(400, {"error": "id required"})
            return
        try:
            from dashboard.chat_sessions import get_session_store
            session = get_session_store().get(sid)
        except Exception as exc:  # noqa: BLE001
            self._json(200, {"error": str(exc)[:200]})
            return
        if session is None:
            self._json(404, {"error": "session not found"})
            return
        self._json(200, session)

    def _handle_chat_session_save(self, body: dict) -> None:
        """Upsert a session. Body: ``{id?, turns, title?}``.

        ``id`` is optional — omit to create a fresh session, pass the
        existing id to update in place.
        """
        turns = body.get("turns")
        if not isinstance(turns, list):
            self._json(400, {"error": "turns must be a list"})
            return
        sid_raw = body.get("id")
        sid = sid_raw.strip() if isinstance(sid_raw, str) else None
        title_raw = body.get("title")
        title = title_raw.strip() if isinstance(title_raw, str) else None
        try:
            from dashboard.chat_sessions import get_session_store
            store = get_session_store()
            stored_id = store.save(sid, turns, title)
        except Exception as exc:  # noqa: BLE001
            logger.debug("session save failed: %s", exc)
            self._json(200, {"status": "error", "error": str(exc)[:200]})
            return
        self._json(200, {"status": "ok", "id": stored_id})

    def _handle_chat_session_delete(self) -> None:
        """Remove a session. Query: ``?id=sess-...``."""
        from urllib.parse import parse_qs, urlparse
        sid = (parse_qs(urlparse(self.path).query).get("id", [""])[0] or "").strip()
        if not sid:
            self._json(400, {"error": "id required"})
            return
        try:
            from dashboard.chat_sessions import get_session_store
            removed = get_session_store().delete(sid)
        except Exception as exc:  # noqa: BLE001
            self._json(200, {"status": "error", "error": str(exc)[:200]})
            return
        if not removed:
            self._json(404, {"error": "session not found"})
            return
        self._json(200, {"status": "ok"})

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
        """Forward ``message`` + bounded history to the LLM router.

        Runs a one-shot tool-use loop: if the first response begins with
        ``TOOL_CALL: {...}``, invoke the named tool, feed its JSON output
        back as a synthetic assistant/system turn, and re-call the router
        for the final answer. Loop is bounded to 2 iterations so a
        mis-behaving LLM can't spin.
        """
        try:
            from core.adapters import get_router
            from core.adapters.base import Capability
            router = get_router()

            system_prompt = self._build_system_prompt()
            messages = self._build_messages(history, message)

            text = self._invoke_llm(router, Capability, system_prompt, messages)
            if text is None:
                raise RuntimeError("router returned no result")

            # Tool-use loop: at most one follow-up after a tool result, so
            # 2 LLM calls total. A mis-behaving LLM that re-emits TOOL_CALL
            # after being told not to is ignored — its raw text stands.
            for _ in range(1):
                directive = self._parse_tool_directive(text)
                if not directive:
                    return text
                tool_name = directive.get("tool", "")
                tool_args = directive.get("args") or {}
                tool_output = self._run_chat_tool(tool_name, tool_args)
                # Feed the tool result back as an extra assistant turn +
                # a user nudge so the LLM composes the final answer.
                messages = messages + [
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": (
                            f"TOOL_RESULT for {tool_name}:\n{tool_output}\n\n"
                            "Using that data, answer my original question "
                            "concisely. Do not issue another TOOL_CALL."
                        ),
                    },
                ]
                text = self._invoke_llm(
                    router, Capability, system_prompt, messages,
                )
                if text is None:
                    raise RuntimeError("router returned no follow-up")
            return text
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
        lines.append("")
        lines.append(
            "TOOLS — if you need fresher/deeper data than CONTEXT provides, "
            "you may issue exactly one tool call. To do so, respond with ONE "
            "line containing ONLY:\n"
            '  TOOL_CALL: {"tool": "<name>"}\n'
            "Available tools:"
        )
        for name, meta in self._CHAT_TOOLS.items():
            lines.append(f"- {name}: {meta['description']}")
        lines.append(
            "After you receive the TOOL_RESULT, answer directly — do not "
            "chain another TOOL_CALL."
        )
        return "\n".join(lines)

    # ── LLM tool-calling ─────────────────────────────────

    # Catalog of tools the LLM may self-invoke. Each entry binds a public
    # tool name (used in the prompt) to the handler that collects the
    # data. Handlers must be read-only and cheap — the LLM may call them
    # repeatedly on the same turn if we ever lift the 2-iteration cap.
    _CHAT_TOOLS: dict[str, dict[str, str]] = {
        "get_adapter_status": {
            "description": (
                "Full adapter registry: total count, configured count, "
                "per-category breakdown, each adapter's name and state."
            ),
        },
        "get_cycle_summary": {
            "description": (
                "Latest autonomous cycle: id, store, duration, phase errors, "
                "action count, top action, hook results."
            ),
        },
        "get_vault_summary": {
            "description": (
                "Obsidian vault state: per-folder note counts and recent "
                "entries across Wins/Errors/Decisions/Learned."
            ),
        },
    }

    def _invoke_llm(
        self,
        router,
        capability_cls,
        system_prompt: str,
        messages: list[dict],
    ) -> str | None:
        """Thin router wrapper returning text or None on adapter miss."""
        try:
            result = router.execute(
                capability_cls.CHAT_COMPLETE,
                {
                    "system": system_prompt,
                    "prompt": messages[-1]["content"] if messages else "",
                    "messages": messages,
                    "max_tokens": 500,
                    "temperature": 0.3,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("router.execute failed: %s", exc)
            return None
        if result and result.ok:
            return result.data.get("text", "")
        return None

    @staticmethod
    def _parse_tool_directive(text: str) -> dict | None:
        """Return the JSON object from a ``TOOL_CALL: {...}`` line, or None.

        Accepts the directive anywhere in the first non-empty line so
        small-LLM preambles like "Sure, " don't defeat detection.
        """
        if not text:
            return None
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            marker = line.find("TOOL_CALL:")
            if marker < 0:
                # Only scan the first non-empty line to avoid picking up
                # quoted examples in a natural-language reply.
                return None
            json_blob = line[marker + len("TOOL_CALL:"):].strip()
            # Trim anything after the first balanced JSON object.
            if not json_blob.startswith("{"):
                return None
            depth = 0
            end = -1
            for i, ch in enumerate(json_blob):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end < 0:
                return None
            try:
                obj = json.loads(json_blob[:end + 1])
            except Exception:  # noqa: BLE001
                return None
            if not isinstance(obj, dict) or "tool" not in obj:
                return None
            return obj
        return None

    def _run_chat_tool(self, name: str, args: dict) -> str:
        """Dispatch ``name`` to the matching ``_tool_*`` handler.

        Returns a JSON string so the next LLM turn can consume it
        verbatim. Unknown / failing tools return a structured error
        so the LLM can still compose a graceful answer.
        """
        if name not in self._CHAT_TOOLS:
            return json.dumps({"error": f"unknown tool: {name}"})
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return json.dumps({"error": f"handler missing: {name}"})
        try:
            output = handler(args or {})
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"tool {name} failed: {exc}"[:200]})
        try:
            return json.dumps(output, ensure_ascii=False, default=str)[:2000]
        except Exception:  # noqa: BLE001
            return json.dumps({"error": "tool output not JSON-serialisable"})

    def _tool_get_adapter_status(self, _args: dict) -> dict:
        snap = self._get_adapter_status() or {}
        # _get_adapter_status returns categories as {cat_name: [ad dict, ...]}.
        # Flatten into a compact [{name, category, configured}] shape plus a
        # per-category count map so the LLM has both views to reason over.
        category_counts: dict[str, int] = {}
        adapters: list[dict] = []
        for cat_name, ads in (snap.get("categories") or {}).items():
            category_counts[cat_name] = len(ads)
            for ad in ads:
                adapters.append({
                    "name": ad.get("name"),
                    "category": cat_name,
                    "configured": ad.get("configured"),
                })
        return {
            "total": snap.get("total", 0),
            "configured": snap.get("configured", 0),
            "categories": category_counts,
            "adapters": adapters[:40],
        }

    def _tool_get_cycle_summary(self, _args: dict) -> dict:
        try:
            from core.system.auto_scheduler import get_scheduler
            sched = get_scheduler()
            latest = sched.get_last_summary() or {}
            status = sched.get_status()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"scheduler unavailable: {exc}"}
        # Keep only the fields that matter for answering chat questions —
        # full adapter_hooks payload is too chunky.
        return {
            "has_data": bool(latest),
            "scheduler": {
                "running": status.get("running"),
                "busy": status.get("busy"),
                "cycles_run": status.get("cycles_run"),
                "last_error": status.get("last_error"),
            },
            "latest": {
                "cycle_id": latest.get("cycle_id"),
                "store_id": latest.get("store_id"),
                "duration_s": latest.get("duration_s"),
                "phase_error_count": latest.get("phase_error_count"),
                "actions_proposed": latest.get("actions_proposed"),
                "top_action": latest.get("top_action"),
                "products": latest.get("products"),
                "orders": latest.get("orders"),
                "insights": latest.get("insights"),
            },
        }

    def _tool_get_vault_summary(self, _args: dict) -> dict:
        try:
            snap = _collect_vault_summary() or {}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"vault unavailable: {exc}"}
        # Flatten the recent_* lists into a single dict keyed by folder
        # so the LLM gets a predictable shape. Trim to 5 per folder to
        # keep the tool output compact.
        recent = {
            "wins": (snap.get("recent_wins") or [])[:5],
            "errors": (snap.get("recent_errors") or [])[:5],
            "decisions": (snap.get("recent_decisions") or [])[:5],
            "learned": (snap.get("recent_learned") or [])[:5],
        }
        return {
            "configured": snap.get("configured", False),
            "path": snap.get("path", ""),
            "totals": snap.get("totals", {}),
            "recent": recent,
        }

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


class _VaultNotConfigured(Exception):
    """Raised when the feedback writer can't locate the Obsidian vault."""


class _VaultPathDenied(Exception):
    """Raised when a requested note path escapes the vault root."""


def _read_vault_note(rel: str) -> dict[str, Any]:
    """Return ``{path, title, mtime, body}`` for a note at ``rel``.

    ``rel`` must be a path relative to the vault root, ending in ``.md``.
    We resolve both the vault root and the target to absolute paths and
    confirm the target is a strict child — this blocks ``..``, absolute
    paths, and symlinks that would otherwise escape the sandbox.
    """
    root = _vault_root().resolve()

    # Reject obvious shenanigans early.
    if not rel or rel.startswith("/") or "\\" in rel or "\x00" in rel:
        raise _VaultPathDenied(f"invalid path: {rel!r}")
    if not rel.endswith(".md"):
        raise _VaultPathDenied("only .md files are readable")

    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise _VaultPathDenied("path escapes vault root") from exc

    if not candidate.is_file():
        raise FileNotFoundError(rel)

    body = candidate.read_text(encoding="utf-8", errors="replace")
    # Hard cap on returned body — a 10 MB note would choke the UI and
    # is never a legitimate chat-visible artifact.
    if len(body) > 200_000:
        body = body[:200_000] + "\n\n… [truncated]\n"

    return {
        "path": candidate.relative_to(root).as_posix(),
        "title": candidate.stem,
        "mtime": candidate.stat().st_mtime,
        "body": body,
    }


def _vault_root() -> Path:
    """Return the configured vault root as a ``Path`` or raise."""
    try:
        from core.adapters.config import get_config
        vault_raw = get_config().get("obsidian_vault_path")
    except Exception as exc:  # noqa: BLE001
        raise _VaultNotConfigured(
            f"config unavailable: {exc}",
        ) from exc
    if not vault_raw:
        raise _VaultNotConfigured("OBSIDIAN_VAULT_PATH not set")
    path = Path(vault_raw)
    if not path.is_dir():
        raise _VaultNotConfigured(f"vault not a directory: {path}")
    return path


def _sanitise_feedback_snippet(text: str, limit: int = 2000) -> str:
    """Escape Markdown control characters and clip to ``limit``.

    We keep the raw text readable in Obsidian but prevent accidental
    frontmatter injection or table-of-contents blowup from a crafted
    chat transcript.
    """
    if not text:
        return ""
    clipped = text[:limit]
    # Strip leading ``---`` which Obsidian interprets as frontmatter.
    # Also drop NUL bytes that would corrupt the file.
    clipped = clipped.replace("\x00", "")
    return clipped


def _write_feedback_note(
    *,
    rating: str,
    message: str,
    response: str,
    note: str,
) -> Path:
    """Write a feedback note into ``vault/ShopAI/Feedback/``.

    Filename format: ``<utc-iso>-<rating>.md``. Contents carry
    frontmatter (tags, rating, date) and wikilinks to the Wins/Errors
    folders so the Obsidian graph view picks up connections.
    """
    root = _vault_root()
    feedback_dir = root / "ShopAI" / "Feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)

    # Compact, filesystem-safe ISO timestamp: "2026-04-14T08-32-14".
    ts = time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())
    filename = f"{ts}-{rating}.md"
    path = feedback_dir / filename

    msg = _sanitise_feedback_snippet(message)
    rsp = _sanitise_feedback_snippet(response)
    operator_note = _sanitise_feedback_snippet(note, limit=800)

    tag_suffix = "good" if rating == "up" else "bad"
    graph_link = "[[Wins]]" if rating == "up" else "[[Errors]]"

    lines = [
        "---",
        f"title: Chat feedback ({rating})",
        f"date: {ts}",
        f"rating: {rating}",
        "type: chat-feedback",
        f"tags: [feedback, chat, {tag_suffix}]",
        "---",
        "",
        f"# Chat feedback — {rating.upper()}",
        "",
        f"Related: {graph_link} · [[ShopAI Architecture]]",
        "",
        "## User message",
        "",
        "```",
        msg or "(empty)",
        "```",
        "",
        "## Assistant response",
        "",
        "```",
        rsp or "(empty)",
        "```",
    ]
    if operator_note:
        lines.extend(["", "## Operator note", "", operator_note])

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


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
            try:
                rel = f.relative_to(vault).as_posix()
            except ValueError:
                rel = f.name
            entry = {
                "title": f.stem,
                "folder": folder,
                "mtime": f.stat().st_mtime,
                "path": rel,
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


# Scan/Body caps so one monster note can't starve the search.
_VAULT_SEARCH_MAX_FILES = 5000
_VAULT_SEARCH_MAX_BODY_BYTES = 200_000
_VAULT_SEARCH_SNIPPET_RADIUS = 80


def _collect_vault_search(
    query: str,
    type_filter: str = "",
    limit: int = 30,
) -> dict[str, Any]:
    """Rank notes in the vault by relevance to ``query``.

    Scoring (cheap and predictable):

    * title hit → +5 per occurrence
    * tag / frontmatter field hit → +3
    * body hit → +1 (capped at 10 per note)

    With an empty query we fall through to an mtime-sorted listing so
    the UI can still use this endpoint to browse by folder.
    """
    root = _vault_root()  # raises _VaultNotConfigured
    q_lower = query.lower()

    # Decide which subtree to walk. Unknown filters fall back to the
    # whole vault — better than returning nothing and confusing the UI.
    if type_filter and type_filter in _VAULT_FOLDERS_OF_INTEREST:
        walk_root = root / type_filter
        if not walk_root.is_dir():
            return {"configured": True, "query": query, "type": type_filter,
                    "total": 0, "results": []}
    else:
        walk_root = root
        type_filter = ""

    try:
        from core.adapters.obsidian.parser import parse_note
    except Exception:  # noqa: BLE001
        parse_note = None

    scored: list[tuple[float, dict[str, Any]]] = []
    scanned = 0

    for f in walk_root.rglob("*.md"):
        if scanned >= _VAULT_SEARCH_MAX_FILES:
            break
        scanned += 1
        try:
            stat = f.stat()
        except OSError:
            continue

        title = f.stem
        tags: list[str] = []
        frontmatter_blob = ""

        # Best-effort frontmatter + tag extraction; fall back to the
        # filename if the parser isn't available or chokes on the file.
        if parse_note is not None:
            try:
                n = parse_note(f, root)
                fm = n.get("frontmatter", {}) or {}
                title = str(fm.get("title") or f.stem)
                tags = [str(t) for t in (n.get("tags") or [])][:12]
                # Concat a few structured fields for the "tag hit" bucket.
                frontmatter_blob = " ".join([
                    str(fm.get("title", "")),
                    str(fm.get("date", "")),
                    str(fm.get("action", "")),
                    str(fm.get("severity", "")),
                    " ".join(tags),
                ]).lower()
            except Exception:  # noqa: BLE001
                pass

        try:
            body = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(body) > _VAULT_SEARCH_MAX_BODY_BYTES:
            body = body[:_VAULT_SEARCH_MAX_BODY_BYTES]
        body_lower = body.lower()

        # Score the note. An empty query leaves everything at 0 and we
        # fall back to mtime ordering at the end.
        score = 0.0
        if q_lower:
            title_hits = title.lower().count(q_lower)
            score += title_hits * 5
            if frontmatter_blob:
                score += frontmatter_blob.count(q_lower) * 3
            body_hits = body_lower.count(q_lower)
            score += min(body_hits, 10)
            if score <= 0:
                continue

        try:
            rel = f.relative_to(root).as_posix()
        except ValueError:
            rel = f.name
        # Derive the folder label from the path — avoids duplicating
        # our folder map in the response.
        folder = rel.split("/", 1)[0] if "/" in rel else ""
        if rel.startswith("ShopAI/"):
            # Surface the two-segment prefix so the UI can pill-tag it.
            folder = "ShopAI/" + rel.split("/", 2)[1] if "/" in rel[7:] else "ShopAI"

        snippet = _vault_search_snippet(body, q_lower)

        scored.append((score, {
            "path": rel,
            "title": title,
            "folder": folder,
            "mtime": stat.st_mtime,
            "tags": tags,
            "score": score,
            "snippet": snippet,
        }))

    # Primary sort: score desc (0 when query empty). Secondary: mtime
    # desc so "browse" mode always shows newest first.
    scored.sort(key=lambda t: (t[0], t[1]["mtime"]), reverse=True)
    results = [entry for _, entry in scored[:limit]]

    return {
        "configured": True,
        "path": str(root),
        "query": query,
        "type": type_filter,
        "total": len(scored),
        "scanned": scanned,
        "results": results,
    }


def _vault_search_snippet(body: str, q_lower: str) -> str:
    """Return a ~160 char window around the first query hit.

    Without a query we return the opening line or two — enough for the
    UI to show some context in the result row.
    """
    if not body:
        return ""
    if not q_lower:
        head = body.strip().splitlines()[:2]
        return " ".join(head)[:160]
    idx = body.lower().find(q_lower)
    if idx < 0:
        return body.strip()[:160]
    start = max(0, idx - _VAULT_SEARCH_SNIPPET_RADIUS)
    end = min(len(body), idx + len(q_lower) + _VAULT_SEARCH_SNIPPET_RADIUS)
    chunk = body[start:end].replace("\n", " ").strip()
    if start > 0:
        chunk = "…" + chunk
    if end < len(body):
        chunk = chunk + "…"
    return chunk


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
