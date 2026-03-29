"""ShopAIServer — lightweight HTTP API server using stdlib only.

Provides REST endpoints for external systems to interact with ShopAI.
No flask/fastapi dependency — pure stdlib http.server.
"""
from __future__ import annotations

import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlparse, parse_qs

from utils.logger import get_logger
from core.orchestrator import MainOrchestrator

logger = get_logger("api.server")


class ShopAIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for ShopAI API."""

    orchestrator: MainOrchestrator | None = None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        routes = {
            "/api/health": self._health,
            "/api/status": self._status,
            "/api/engines": self._list_engines,
            "/api/chains": self._list_chains,
        }

        if path.startswith("/api/engine/") and path.count("/") == 3:
            engine_name = path.split("/")[-1]
            self._engine_info(engine_name)
            return

        handler = routes.get(path)
        if handler:
            handler()
        else:
            self._json_response(404, {"error": f"Not found: {path}"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        body = self._read_body()
        if body is None:
            return

        routes = {
            "/api/task": self._submit_task,
            "/api/chain": self._run_chain,
            "/api/batch": self._batch_process,
            "/api/analyze": self._analyze_engine,
        }

        handler = routes.get(path)
        if handler:
            handler(body)
        else:
            self._json_response(404, {"error": f"Not found: {path}"})

    # --- GET handlers ---

    def _health(self) -> None:
        from core.self_monitor import HealthChecker
        health = HealthChecker().check_all()
        self._json_response(200, health)

    def _status(self) -> None:
        if not self.orchestrator:
            self._json_response(503, {"error": "Orchestrator not initialized"})
            return
        status = self.orchestrator.get_status()
        self._json_response(200, status)

    def _list_engines(self) -> None:
        from engines.registry import list_engines, engine_count
        self._json_response(200, {"count": engine_count(), "engines": list_engines()})

    def _list_chains(self) -> None:
        from core.chaining import ChainRegistry
        registry = ChainRegistry()
        self._json_response(200, {"chains": registry.list_chains()})

    def _engine_info(self, engine_name: str) -> None:
        from engines.registry import get_engine, is_registered
        if not is_registered(engine_name):
            self._json_response(404, {"error": f"Unknown engine: {engine_name}"})
            return
        try:
            engine = get_engine(engine_name)
            self._json_response(200, {
                "name": engine.engine_name,
                "class": engine.__class__.__name__,
                "inputs": engine.required_input_fields,
                "outputs": engine.required_output_fields,
            })
        except Exception as exc:
            self._json_response(500, {"error": str(exc)})

    # --- POST handlers ---

    def _submit_task(self, body: dict) -> None:
        if not self.orchestrator:
            self._json_response(503, {"error": "Orchestrator not initialized"})
            return

        task_type = body.get("task_type", body.get("engine"))
        params = body.get("params", body.get("data", {}))

        if not task_type:
            self._json_response(400, {"error": "Missing task_type"})
            return

        result = self.orchestrator.submit_task(task_type, params)
        self._json_response(200, result)

    def _run_chain(self, body: dict) -> None:
        chain_name = body.get("chain")
        data = body.get("data", {})

        if not chain_name:
            self._json_response(400, {"error": "Missing chain name"})
            return

        from core.chaining import ChainRegistry
        try:
            registry = ChainRegistry()
            result = registry.run(chain_name, data)
            self._json_response(200, result)
        except KeyError as exc:
            self._json_response(404, {"error": str(exc)})

    def _batch_process(self, body: dict) -> None:
        engine = body.get("engine")
        items = body.get("items", [])

        if not engine or not items:
            self._json_response(400, {"error": "Missing engine or items"})
            return

        from core.performance import BatchProcessor
        bp = BatchProcessor()
        result = bp.process(engine, items, body.get("shared_params"))
        self._json_response(200, result)

    def _analyze_engine(self, body: dict) -> None:
        if not self.orchestrator:
            self._json_response(503, {"error": "Orchestrator not initialized"})
            return

        engine_name = body.get("engine")
        if engine_name:
            result = self.orchestrator.analyze_engine(engine_name)
        else:
            result = self.orchestrator.analyze_system()
        self._json_response(200, result)

    # --- Helpers ---

    def _read_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            return json.loads(raw) if raw else {}
        except (json.JSONDecodeError, ValueError) as exc:
            self._json_response(400, {"error": f"Invalid JSON: {exc}"})
            return None

    def _json_response(self, status: int, data: Any) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        body = json.dumps(data, default=str)
        self.wfile.write(body.encode())

    def log_message(self, format: str, *args: Any) -> None:
        logger.info(format, *args)


class ShopAIServer:
    """HTTP server for ShopAI API."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        self._host = host
        self._port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._orchestrator = MainOrchestrator()

    def start(self) -> None:
        """Start API server (blocking)."""
        self._orchestrator.initialize()
        ShopAIHandler.orchestrator = self._orchestrator

        self._server = HTTPServer((self._host, self._port), ShopAIHandler)
        logger.info("ShopAI API server starting on %s:%d", self._host, self._port)
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            self.stop()

    def start_background(self) -> None:
        """Start API server in background thread."""
        self._orchestrator.initialize()
        ShopAIHandler.orchestrator = self._orchestrator

        self._server = HTTPServer((self._host, self._port), ShopAIHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("ShopAI API server started on %s:%d (background)", self._host, self._port)

    def stop(self) -> None:
        """Stop API server."""
        if self._server:
            self._server.shutdown()
        self._orchestrator.shutdown()
        logger.info("ShopAI API server stopped")
