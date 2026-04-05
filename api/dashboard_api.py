"""Dashboard API — HTTP endpoints for monitoring and control.

Endpoints:
  GET  /api/status     — system status
  GET  /api/dashboard  — full dashboard data
  GET  /api/cycle      — run a cycle and return results
  GET  /api/alerts     — recent alerts
  GET  /api/report     — human-readable report
  POST /api/webhook    — Shopify webhook receiver
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
        else:
            self._json_response({"error": "not_found", "endpoints": [
                "/api/status", "/api/dashboard", "/api/cycle",
                "/api/alerts", "/api/report", "/api/memory",
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
        return result

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
