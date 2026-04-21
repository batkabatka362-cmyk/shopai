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
from api.validation import (
    validate_store_id, validate_safe_name, validate_batch_items,
    validate_params, validate_webhook_topic,
)

logger = get_logger("api.server")


def _lookup_launch_ids(shop: str, product_ids: list[int]) -> list[str]:
    """Return the ``shopai/launch_id`` metafield for each product that
    has one. Used by the order webhook to tag revenue events with the
    launch that produced them. Silently returns an empty list on any
    failure — revenue signal must still land in memory even when the
    correlation step fails.
    """
    import os
    import urllib.error
    import urllib.request

    if not shop or not product_ids:
        return []
    token = os.environ.get("SHOPAI_SHOPIFY_KEY", "")
    if not token:
        return []

    launch_ids: list[str] = []
    for pid in product_ids[:20]:  # cap for safety
        url = (
            f"https://{shop}/admin/api/2024-01/products/{pid}/metafields.json"
            "?namespace=shopai&key=launch_id"
        )
        req = urllib.request.Request(
            url,
            headers={
                "X-Shopify-Access-Token": token,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
            continue
        for mf in data.get("metafields", []):
            val = mf.get("value")
            if val:
                launch_ids.append(str(val))
                break
    return launch_ids


class ShopAIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for ShopAI API."""

    orchestrator: MainOrchestrator | None = None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        routes = {
            "/health": self._liveness,       # lightweight probe for load balancers
            "/api/health": self._health,
            "/api/status": self._status,
            "/api/engines": self._list_engines,
            "/api/chains": self._list_chains,
            "/api/experience": self._get_experience,
            "/api/webhooks": self._list_webhooks,
            "/api/stores": self._list_stores,
            "/api/launches": self._list_launches,
            # Wave E-1: llms.txt + llms-full.txt served from disk
            "/llms.txt": self._llms_txt,
            "/llms-full.txt": self._llms_full_txt,
        }

        if path.startswith("/llms-mirror/") and path.endswith(".md"):
            # Serve one product mirror as markdown
            slug = path[len("/llms-mirror/"):-len(".md")]
            self._llms_mirror(slug)
            return

        if path.startswith("/api/engine/") and path.count("/") == 3:
            engine_name, err = validate_safe_name(path.split("/")[-1], "engine")
            if err:
                self._json_response(400, {"error": err})
                return
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
            "/api/webhook/shopify": self._handle_webhook,
            "/api/agent": self._agent_run,
            "/api/workflow": self._run_workflow,
            "/api/auto/cycle": self._auto_cycle,
            "/api/store/sync": self._store_sync,
            "/api/launch": self._launch_product,
        }

        handler = routes.get(path)
        if handler:
            handler(body)
        else:
            self._json_response(404, {"error": f"Not found: {path}"})

    # --- GET handlers ---

    def _text_response(
        self,
        status: int,
        body: str,
        *,
        content_type: str = "text/plain; charset=utf-8",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header(
            "Access-Control-Allow-Origin", "*",
        )
        encoded = body.encode("utf-8")
        self.send_header(
            "Content-Length", str(len(encoded)),
        )
        self.end_headers()
        self.wfile.write(encoded)

    def _llms_txt(self) -> None:
        """Serve ``data/llms/llms.txt`` if it exists."""
        self._serve_llms_file(
            relative="llms.txt",
            content_type="text/plain; charset=utf-8",
        )

    def _llms_full_txt(self) -> None:
        self._serve_llms_file(
            relative="llms-full.txt",
            content_type="text/plain; charset=utf-8",
        )

    def _llms_mirror(self, slug: str) -> None:
        """Serve a product markdown mirror. Slug is
        untrusted input — guard against path traversal."""
        import re
        if not re.match(r"^[a-z0-9\-]{1,80}$", slug):
            self._text_response(
                400, "invalid slug",
            )
            return
        self._serve_llms_file(
            relative=f"products/{slug}.md",
            content_type="text/markdown; charset=utf-8",
        )

    def _serve_llms_file(
        self, *, relative: str, content_type: str,
    ) -> None:
        from pathlib import Path as _P
        root = _P("data/llms")
        target = (root / relative).resolve()
        # Path-traversal guard: must stay under the root.
        try:
            target.relative_to(root.resolve())
        except ValueError:
            self._text_response(400, "bad path")
            return
        if not target.is_file():
            self._text_response(
                404,
                "Not built yet. Run "
                "`shopai build-llms-txt` first.",
            )
            return
        try:
            body = target.read_text(encoding="utf-8")
        except OSError as exc:
            self._text_response(
                500, f"read error: {exc}",
            )
            return
        self._text_response(
            200, body, content_type=content_type,
        )

    def _liveness(self) -> None:
        """Lightweight liveness probe. Returns immediately without any
        deep checks — intended for load balancers / k8s probes.
        Returns 200 if the process is running and the HTTP loop is
        responsive."""
        import time
        self._json_response(200, {
            "status": "ok",
            "service": "shopai",
            "ts": time.time(),
        })

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
            logger.warning("engine info failed: %s", exc)
            self._json_response(500, {"error": str(exc)})

    def _get_experience(self) -> None:
        try:
            from core.ai.experience import get_experience
            exp = get_experience()
            self._json_response(200, exp.get_knowledge_summary())
        except Exception as exc:
            logger.warning("experience summary failed: %s", exc)
            self._json_response(500, {"error": str(exc)})

    def _list_webhooks(self) -> None:
        from core.webhooks import ShopifyWebhookHandler
        handler = ShopifyWebhookHandler()
        self._json_response(200, {
            "supported_events": handler.list_supported_events(),
            "stats": handler.get_stats(),
        })

    def _list_stores(self) -> None:
        try:
            from data_pipeline.store.store_manager import StoreManager
            sm = StoreManager()
            stores = sm.list_stores()
            stats = [sm.get_stats(s["store_id"]) for s in stores]
            self._json_response(200, {"stores": stores, "stats": stats})
        except Exception as exc:
            logger.warning("store listing failed: %s", exc)
            self._json_response(200, {"stores": [], "error": str(exc)})

    def _list_launches(self) -> None:
        """Dashboard endpoint — per-launch KPIs + kill/scale verdicts.

        Cheap call: pure aggregation over the memory store, no
        external API. Returns the evaluator report plus a compact
        summary counts block for the UI.
        """
        from core.autonomous.launch_evaluator import evaluate
        report = evaluate()
        self._json_response(200, {
            "summary": {
                "tracked": report.launches_tracked,
                "evaluated": report.launches_evaluated,
                "kill": len(report.kill_recommendations),
                "scale": len(report.scale_recommendations),
                "monitor": len(report.monitor_recommendations),
            },
            "report": report.as_dict(),
        })

    # --- POST handlers ---

    def _submit_task(self, body: dict) -> None:
        if not self.orchestrator:
            self._json_response(503, {"error": "Orchestrator not initialized"})
            return

        task_type, err = validate_safe_name(
            body.get("task_type", body.get("engine")), "task_type")
        if err:
            self._json_response(400, {"error": err})
            return

        params, err = validate_params(body.get("params", body.get("data", {})))
        if err:
            self._json_response(400, {"error": err})
            return

        result = self.orchestrator.submit_task(task_type, params)
        self._json_response(200, result)

    def _run_chain(self, body: dict) -> None:
        chain_name, err = validate_safe_name(body.get("chain"), "chain")
        if err:
            self._json_response(400, {"error": err})
            return

        data, err = validate_params(body.get("data", {}))
        if err:
            self._json_response(400, {"error": err})
            return

        from core.chaining import ChainRegistry
        try:
            registry = ChainRegistry()
            result = registry.run(chain_name, data)
            self._json_response(200, result)
        except KeyError as exc:
            self._json_response(404, {"error": str(exc)})

    def _batch_process(self, body: dict) -> None:
        engine, err = validate_safe_name(body.get("engine"), "engine")
        if err:
            self._json_response(400, {"error": err})
            return

        items, err = validate_batch_items(body.get("items", []))
        if err:
            self._json_response(400, {"error": err})
            return

        shared_params, err = validate_params(body.get("shared_params"))
        if err:
            self._json_response(400, {"error": err})
            return

        from core.performance import BatchProcessor
        bp = BatchProcessor()
        result = bp.process(engine, items, shared_params)
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

    def _handle_webhook(self, body: dict) -> None:
        """Handle Shopify webhook event — triggers engines + records experience."""
        topic, err = validate_webhook_topic(
            self.headers.get("X-Shopify-Topic", body.get("topic", "")))
        if err:
            self._json_response(400, {"error": err})
            return
        shop = self.headers.get("X-Shopify-Shop-Domain", body.get("shop", ""))
        hmac_val = self.headers.get("X-Shopify-Hmac-SHA256", "")

        from core.webhooks import ShopifyWebhookHandler
        handler = ShopifyWebhookHandler()
        # ``_read_body`` stashes the raw request bytes on
        # ``self._last_raw_body`` — the webhook handler needs
        # them for HMAC verification because Python's
        # ``json.dumps(body)`` doesn't round-trip to the bytes
        # Shopify actually signed. Audit pass 42 security fix.
        raw_body = getattr(self, "_last_raw_body", None)
        result = handler.handle(topic, body, hmac_val, shop, raw_body=raw_body)

        # Store in experience DB
        try:
            from core.ai.experience import get_experience
            exp = get_experience()
            store_id = shop.replace(".myshopify.com", "") if shop else ""
            if "orders/create" in topic:
                total = float(body.get("total_price", 0) or 0)
                exp.store_market_intel(
                    "order_event", f"New order ${total:.2f} from {shop}",
                    source="webhook", confidence=1.0, relevance=store_id,
                )
            # Cache webhook data to DB
            from data_pipeline.store.db import ShopAIDatabase
            db = ShopAIDatabase()
            if store_id and "order" in topic:
                db.upsert_orders(store_id, handler._normalize_order(body))
            elif store_id and "product" in topic:
                db.upsert_products(store_id, handler._normalize_product(body))
            elif store_id and "customer" in topic:
                db.upsert_customers(store_id, handler._normalize_customer(body))
        except Exception as exc:
            logger.debug("Webhook experience/cache: %s", exc)

        # Reward-signal bridge: orders are the closing leg of the
        # decision → action → outcome loop the learning pipeline
        # depends on. Record each order as a memory event tagged
        # with the originating launch_id so pattern promotion
        # aggregates rewards per-launch instead of globally.
        if "orders/create" in topic:
            try:
                from core.memory.intelligence import get_memory_intelligence
                line_items = body.get("line_items") or []
                product_ids = [
                    li.get("product_id") for li in line_items if li.get("product_id")
                ]
                # Look up launch_id metafield for each product so the
                # event is tagged with the launch that produced this
                # order. Launch_id comes from workflows/launch/ —
                # products created outside the launch pipeline stay
                # unlabeled, which is fine.
                launch_ids = _lookup_launch_ids(shop, product_ids)
                tags = ["revenue", "order"]
                if store_id:
                    tags.append(store_id)
                tags.extend(f"launch:{lid}" for lid in launch_ids)

                get_memory_intelligence().create(
                    category="order",
                    content={
                        "shop": shop,
                        "order_id": body.get("id"),
                        "total_price": float(body.get("total_price", 0) or 0),
                        "currency": body.get("currency"),
                        "product_ids": product_ids,
                        "launch_ids": launch_ids,
                        "line_count": len(line_items),
                        "customer_email": body.get("email"),
                        "source_name": body.get("source_name"),
                        "landing_site": body.get("landing_site"),
                    },
                    action="purchase",
                    score=5.0,  # orders = highest-fidelity reward signal
                    tags=tags,
                )
            except Exception as exc:
                logger.debug("memory create failed: %s", exc)

        self._json_response(200, result)

    def _auto_cycle(self, body: dict) -> None:
        """Run one autonomous AI cycle."""
        store_id, err = validate_store_id(body.get("store_id", ""))
        if err:
            self._json_response(400, {"error": err})
            return
        try:
            from data_pipeline.store.store_manager import StoreManager
            from core.autonomous.controller import AutonomousController
            sm = StoreManager()
            controller = AutonomousController(sm, auto_approve=bool(body.get("auto_approve", False)))
            controller.initialize()
            result = controller.run_cycle(store_id)
            self._json_response(200, result)
        except Exception as exc:
            logger.warning("cycle run failed for %s: %s", store_id, exc)
            self._json_response(500, {"error": str(exc)})

    def _store_sync(self, body: dict) -> None:
        """Sync store data from Shopify."""
        store_id, err = validate_store_id(body.get("store_id", ""))
        if err:
            self._json_response(400, {"error": err})
            return
        try:
            from data_pipeline.store.store_manager import StoreManager
            from data_pipeline.store.sync_service import SyncService
            sm = StoreManager()
            sync = SyncService(sm)
            result = sync.sync_store(store_id)
            self._json_response(200, result)
        except Exception as exc:
            logger.warning("store sync failed for %s: %s", store_id, exc)
            self._json_response(500, {"error": str(exc)})

    def _agent_run(self, body: dict) -> None:
        """Run a task through an agent."""
        if not self.orchestrator:
            self._json_response(503, {"error": "Orchestrator not initialized"})
            return

        agent, err = validate_safe_name(body.get("agent", ""), "agent")
        if err:
            self._json_response(400, {"error": err})
            return

        task, err = validate_safe_name(body.get("task", ""), "task")
        if err:
            self._json_response(400, {"error": err})
            return

        data, err = validate_params(body.get("data", {}))
        if err:
            self._json_response(400, {"error": err})
            return

        result = self.orchestrator.agent_run(agent, task, data)
        self._json_response(200, result)

    def _run_workflow(self, body: dict) -> None:
        """Run a named workflow."""
        if not self.orchestrator:
            self._json_response(503, {"error": "Orchestrator not initialized"})
            return

        workflow, err = validate_safe_name(body.get("workflow", ""), "workflow")
        if err:
            self._json_response(400, {"error": err})
            return

        data, err = validate_params(body.get("data", {}))
        if err:
            self._json_response(400, {"error": err})
            return

        result = self.orchestrator.run_workflow(workflow, data)
        self._json_response(200, result)

    def _launch_product(self, body: dict) -> None:
        """Owner-facing endpoint that runs the Goal-Driven launch
        pipeline. Body fields map 1:1 to LaunchGoal:

            POST /api/launch
            {
              "alibaba_url": "https://...",          # optional
              "spy_url": "https://minea.com/...",   # optional
              "supplier_sku": "CJ-12345",            # optional
              "manual_payload": {...},               # optional
              "target_price": 29.99,
              "ad_budget_day": 20.0,
              "ad_kill_roas": 1.5,
              "ad_kill_after_days": 3,
              "niche": "pets",
              "copy_tone": "urgent",
              "store_id": "ts0efe-ih"
            }
        """
        from workflows.launch import LaunchPipeline, LaunchGoal

        try:
            goal = LaunchGoal(
                alibaba_url=body.get("alibaba_url"),
                spy_url=body.get("spy_url"),
                supplier_sku=body.get("supplier_sku"),
                manual_payload=body.get("manual_payload"),
                target_price=body.get("target_price"),
                margin_floor=float(body.get("margin_floor", 0.30)),
                ad_budget_day=float(body.get("ad_budget_day", 20.0)),
                ad_kill_roas=float(body.get("ad_kill_roas", 1.5)),
                ad_kill_after_days=int(body.get("ad_kill_after_days", 3)),
                niche=body.get("niche", ""),
                copy_tone=body.get("copy_tone", "friendly"),
                store_id=body.get("store_id", ""),
            )
        except (TypeError, ValueError) as exc:
            self._json_response(400, {"error": f"invalid goal: {exc}"})
            return

        # Reject if no source pointer at all
        if goal.source_kind() == "manual" and not goal.manual_payload:
            self._json_response(400, {
                "error": "must supply one of: alibaba_url, spy_url, "
                         "supplier_sku, manual_payload",
            })
            return

        result = LaunchPipeline().run(goal)
        status_code = 200 if result.status == "complete" else (
            207 if result.status == "partial" else 422
        )
        self._json_response(status_code, result.as_dict())

    # --- Helpers ---

    def _read_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            # Stash the raw bytes so handlers that need them
            # (Shopify webhook HMAC verification) can read them
            # via ``self._last_raw_body`` without changing the
            # return shape of ``_read_body``. Audit pass 42.
            self._last_raw_body = raw
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
