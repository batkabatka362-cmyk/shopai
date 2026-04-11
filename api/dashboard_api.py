"""Dashboard API — HTTP endpoints for monitoring and control.

Endpoints:
  GET  /api/status             — system status (+ adapter SLA summary)
  GET  /api/dashboard          — full dashboard data
  GET  /api/cycle              — run a cycle and return results
  GET  /api/alerts             — recent alerts
  GET  /api/report             — human-readable report
  GET  /api/memory             — memory intelligence stats
  GET  /api/metrics/adapters   — per-adapter SLA rollup (Wave 4 #3)
  GET  /api/cognitive          — Mind cognitive dispatcher stats (Wave 5 #B)
  GET  /api/memory/satellites  — SatelliteRouter layer stats (Wave 5 #B)
  GET  /api/policy/audit       — recent policy audit entries (Wave 5 #B)
  POST /api/webhook            — Shopify webhook receiver
"""
from __future__ import annotations
import json
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any
from utils.logger import get_logger
logger = get_logger("api.dashboard")


class DashboardAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for dashboard API."""

    def do_GET(self):
        path = self.path.split("?")[0]

        # Record every API request in data architecture
        try:
            from core.data.architecture import get_data_architecture
            get_data_architecture().capture("system", {
                "event_type": "api_request",
                "component": "dashboard_api",
                "severity": "info",
                "endpoint": path,
            }, source="api", score=3.0)
        except Exception:
            pass

        if path == "/api/status":
            self._json_response(self._get_status())
        elif path == "/api/stores":
            self._json_response(self._get_stores())
        elif path == "/api/dashboard":
            self._json_response(self._get_dashboard())
        elif path == "/api/cycle":
            self._json_response(self._run_cycle())
        elif path == "/api/alerts":
            self._json_response(self._get_alerts())
        elif path == "/api/report":
            self._text_response(self._get_report())
        elif path == "/api/memory":
            self._json_response(self._get_memory())
        elif path == "/api/metrics/adapters":
            self._json_response(self._get_adapter_metrics())
        elif path == "/api/cognitive":
            self._json_response(self._get_cognitive_report())
        elif path == "/api/memory/satellites":
            self._json_response(self._get_satellite_stats())
        elif path == "/api/policy/audit":
            limit_raw = self.path.split("?", 1)[1] if "?" in self.path else ""
            limit = self._parse_limit(limit_raw, default=20, maximum=500)
            self._json_response(self._get_policy_audit(limit=limit))
        else:
            self._json_response({"error": "not_found", "endpoints": [
                "/api/status", "/api/dashboard", "/api/cycle",
                "/api/alerts", "/api/report", "/api/memory",
                "/api/metrics/adapters", "/api/cognitive",
                "/api/memory/satellites", "/api/policy/audit",
            ]}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/webhook":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            topic = self.headers.get("X-Shopify-Topic", "unknown")
            hmac_header = self.headers.get("X-Shopify-Hmac-Sha256", "")
            try:
                payload = json.loads(body)
                from core.system.webhook_handler import get_webhook_handler
                wh = get_webhook_handler()
                result = wh.process(topic, payload, hmac_header)
                self._json_response(result)
            except Exception as exc:
                self._json_response({"error": str(exc)[:100]}, 500)
        elif path == "/api/stores":
            # POST /api/stores — register new store
            try:
                payload = json.loads(body) if body else {}
                from core.system.store_registry import get_store_registry
                reg = get_store_registry()
                result = reg.register(
                    shop_url=payload.get("url", ""),
                    token=payload.get("token", ""),
                    name=payload.get("name", ""),
                    niche=payload.get("niche", ""),
                )
                self._json_response(result)
            except Exception as exc:
                self._json_response({"error": str(exc)[:100]}, 500)
        else:
            self._json_response({"error": "not_found"}, 404)

    def _json_response(self, data: dict, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def _text_response(self, text: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(text.encode())

    @staticmethod
    def _get_stores() -> dict:
        try:
            from core.system.store_registry import get_store_registry
            reg = get_store_registry()
            return {"stores": reg.list_stores(), "stats": reg.get_stats()}
        except Exception as exc:
            return {"error": str(exc)[:100]}

    @staticmethod
    def _get_status() -> dict:
        result = {"status": "running", "timestamp": time.time()}
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            result["memory"] = mi.get_stats()
        except Exception:
            pass
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
            result["data"] = da.get_stats()
        except Exception:
            pass
        # Wave 4 #3: surface an adapter SLA rollup so operators hitting
        # /api/status can see which adapters are breaching their SLO
        # without a separate call to /api/metrics/adapters.
        try:
            from core.adapters.metrics import get_metrics
            sla = get_metrics().get_sla_report()
            result["adapters_sla"] = DashboardAPIHandler._summarise_sla(sla)
        except Exception:
            pass
        return result

    @staticmethod
    def _summarise_sla(sla: dict) -> dict:
        """Compact an SLA report into a lightweight status summary.

        Keeps the per-adapter detail out of /api/status (that's what
        /api/metrics/adapters is for) and surfaces only the count
        of breached / degraded / ok adapters plus the list of any
        that are currently breaching.
        """
        if not isinstance(sla, dict):
            return {"total": 0, "ok": 0, "degraded": 0, "breached": 0, "breaching": []}
        subs = sla.get("subsystems", {}) if "subsystems" in sla else sla
        if not isinstance(subs, dict):
            return {"total": 0, "ok": 0, "degraded": 0, "breached": 0, "breaching": []}
        ok = deg = brk = 0
        breaching: list[str] = []
        for name, row in subs.items():
            status = (row or {}).get("status", "ok") if isinstance(row, dict) else "ok"
            if status == "breached":
                brk += 1
                breaching.append(name)
            elif status == "degraded":
                deg += 1
            else:
                ok += 1
        return {
            "total":     ok + deg + brk,
            "ok":        ok,
            "degraded":  deg,
            "breached":  brk,
            "breaching": breaching,
        }

    @staticmethod
    def _parse_limit(query: str, *, default: int, maximum: int) -> int:
        """Extract ``limit=<n>`` from a raw querystring, clamped to
        [1, maximum]. Returns *default* on any parse failure so the
        endpoint never 500s on bad input.
        """
        if not query:
            return default
        try:
            for part in query.split("&"):
                if "=" not in part:
                    continue
                key, val = part.split("=", 1)
                if key == "limit":
                    n = int(val)
                    return max(1, min(maximum, n))
        except Exception:
            pass
        return default

    @staticmethod
    def _get_cognitive_report() -> dict:
        """Return the Mind cognitive dispatcher observability snapshot.

        Wave 5 #B: exposes Wave 4 #4's in-memory counters (call counts,
        error counts, recent ring buffer, cycles_run) over HTTP so
        operators can watch MBTI function activity without attaching
        a debugger. Fails soft — a missing Mind singleton returns an
        error envelope, never a 500.
        """
        try:
            from core.cognitive.mind import get_mind
            mind = get_mind()
            report = mind.cognitive_report()
            report["timestamp"] = time.time()
            return report
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:200]}

    @staticmethod
    def _get_satellite_stats() -> dict:
        """Return SatelliteRouter layer stats (vector / graph / signal).

        Wave 5 #B: the satellite layers (Wave 2 #4, integrated Wave 3
        #3, reads exposed Wave 4 #2) track per-layer totals; this
        endpoint surfaces them so operators can see the memory
        augmentation is alive without opening a REPL.
        """
        try:
            from core.memory.unified_memory import get_unified_memory
            mem = get_unified_memory()
            router = mem.get_satellites()
            return {
                "layers":    router.stats(),
                "timestamp": time.time(),
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:200]}

    @staticmethod
    def _get_policy_audit(limit: int = 20) -> dict:
        """Return recent policy audit entries (newest first).

        Wave 5 #B: the policy store writes every HARD / MEDIUM /
        SOFT decision to JSONL (Wave 2 #1); without an HTTP surface
        operators had to tail the file by hand. This endpoint
        bridges the gap. Querystring ``?limit=N`` caps the response
        size (default 20, max 500).
        """
        try:
            from engines.meta_governance.policy_store import get_default_store
            store = get_default_store()
            entries = store.read_audit(limit=limit)
            return {
                "entries":   entries,
                "count":     len(entries),
                "timestamp": time.time(),
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:200]}

    @staticmethod
    def _get_adapter_metrics() -> dict:
        """Return the full per-adapter SLA report.

        Wave 4 #3: operator endpoint for the Wave 2 #6 SLATracker
        feed that was fully wired through the metrics layer in
        Wave 3 #4. Always returns a dict — any failure inside the
        telemetry module degrades to ``{"error": "..."}`` so the
        endpoint never crashes the dashboard server.
        """
        try:
            from core.adapters.metrics import get_metrics
            report = get_metrics().get_sla_report()
            return {
                "report":    report,
                "summary":   DashboardAPIHandler._summarise_sla(report),
                "timestamp": time.time(),
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:200]}

    @staticmethod
    def _get_dashboard() -> dict:
        try:
            from core.system.dashboard import get_dashboard
            return get_dashboard().generate()
        except Exception as exc:
            return {"error": str(exc)[:100]}

    @staticmethod
    def _run_cycle() -> dict:
        try:
            from core.system.auto_scheduler import get_scheduler
            return get_scheduler().run_once()
        except Exception as exc:
            return {"error": str(exc)[:100]}

    @staticmethod
    def _get_alerts() -> dict:
        try:
            from core.system.alerts import get_alert_system
            alerts = get_alert_system()
            return {"alerts": alerts.get_recent(20), "stats": alerts.get_stats()}
        except Exception:
            return {"alerts": []}

    @staticmethod
    def _get_report() -> str:
        try:
            from core.system.auto_scheduler import get_scheduler
            sc = get_scheduler()
            if sc._last_result:
                from core.system.cycle_reporter import get_cycle_reporter
                return get_cycle_reporter().report(sc._last_result)
            return "No cycle run yet. GET /api/cycle first."
        except Exception as exc:
            return "Error: {}".format(exc)

    @staticmethod
    def _get_memory() -> dict:
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            return {
                "stats": mi.get_stats(),
                "rules": [{"category": r.get("category",""), "action": r.get("action",""),
                           "uses": r.get("use_count",0), "success": r.get("success_count",0)}
                          for r in mi.get_rules()],
                "strategies": [{"category": s.get("category",""),
                               "content": s.get("content",{})}
                              for s in mi.get_strategies()],
                "meta": mi.get_meta_stats(),
            }
        except Exception as exc:
            return {"error": str(exc)[:100]}

    def log_message(self, format, *args):
        pass  # Suppress default logging


def start_api(host: str = "0.0.0.0", port: int = 8080) -> dict:
    """Start the dashboard API server in a background thread."""
    server = HTTPServer((host, port), DashboardAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True,
                              name="shopai-api")
    thread.start()
    logger.info("Dashboard API started on %s:%d", host, port)
    return {"status": "started", "host": host, "port": port}
