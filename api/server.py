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

# Approval action ids are minted by ``core.approval.queue.enqueue``
# as ``appr_<ms-epoch>_<8-hex>``. The allowed character set is
# ``[A-Za-z0-9_]`` and the length cap rejects path-injection
# attempts (no slashes, dots, or query bleed into the SQL lookup).
import re as _re
_ACTION_ID_RE = _re.compile(r"^[A-Za-z0-9_]{8,80}$")


def _is_valid_action_id(action_id: str) -> bool:
    return bool(action_id and _ACTION_ID_RE.match(action_id))


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
            "/api/pending-actions": self._list_pending_actions,
            "/api/pending-actions/stats": self._pending_actions_stats,
            "/api/approvals/audit": self._approvals_audit,
            "/api/recommendations": self._list_recommendations,
        }

        if path.startswith("/api/engine/") and path.count("/") == 3:
            engine_name, err = validate_safe_name(path.split("/")[-1], "engine")
            if err:
                self._json_response(400, {"error": err})
                return
            self._engine_info(engine_name)
            return

        if path.startswith("/api/pending-actions/") and path.count("/") == 3:
            action_id = path.split("/")[-1]
            self._get_pending_action(action_id, params)
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
            "/api/intent": self._classify_intent,
            "/api/approvals/sweep": self._approvals_sweep,
            "/api/approvals/approve-all": self._approvals_approve_all,
        }

        # /api/pending-actions/<id>/approve  /api/pending-actions/<id>/reject
        # /api/pending-actions/<id>/execute
        if path.startswith("/api/pending-actions/") and path.count("/") == 4:
            parts = path.split("/")
            action_id, verb = parts[3], parts[4]
            if verb == "approve":
                self._approve_pending_action(action_id, body)
                return
            if verb == "reject":
                self._reject_pending_action(action_id, body)
                return
            if verb == "execute":
                self._execute_pending_action(action_id, body)
                return
            self._json_response(404, {"error": f"Unknown action verb: {verb}"})
            return

        handler = routes.get(path)
        if handler:
            handler(body)
        else:
            self._json_response(404, {"error": f"Not found: {path}"})

    # --- GET handlers ---

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

    def _list_pending_actions(self) -> None:
        """GET /api/pending-actions — open queue for the merchant.

        Optional query params:
          ?engine=<name> — filter to a single engine namespace
          ?limit=<int>   — page size (default 100, max 500)
        """
        from urllib.parse import urlparse, parse_qs
        from core.approval import get_approval_queue

        params = parse_qs(urlparse(self.path).query)
        engine = params.get("engine", [None])[0]
        if engine:
            engine, err = validate_safe_name(engine, "engine")
            if err:
                self._json_response(400, {"error": err})
                return
        try:
            limit = int(params.get("limit", ["100"])[0])
        except ValueError:
            limit = 100
        limit = max(1, min(500, limit))

        try:
            queue = get_approval_queue()
            actions = queue.list_pending(engine=engine, limit=limit)
            try:
                from core.knowledge import enrich_action_dict
                enriched = [
                    enrich_action_dict(a.to_dict()) for a in actions
                ]
            except Exception as exc:  # noqa: BLE001
                # NotesStore is best-effort — never block the
                # action list on knowledge-layer issues.
                logger.debug(
                    "operator-context enrichment failed: %s", exc,
                )
                enriched = [a.to_dict() for a in actions]
            self._json_response(200, {
                "count": len(enriched),
                "actions": enriched,
            })
        except Exception as exc:
            logger.warning("list pending actions failed: %s", exc)
            self._json_response(500, {"error": str(exc)})

    def _pending_actions_stats(self) -> None:
        """GET /api/pending-actions/stats — counts per status."""
        from core.approval import get_approval_queue
        try:
            self._json_response(200, get_approval_queue().stats())
        except Exception as exc:
            logger.warning("approval queue stats failed: %s", exc)
            self._json_response(500, {"error": str(exc)})

    def _list_recommendations(self) -> None:
        """GET /api/recommendations — orchestration-brain v1 surface.

        Joins the active goal + per-goal effectiveness EMA with the
        engine→goal map to rank which engines the merchant should
        run next. Pure read; nothing persists.

        Query params (all optional):
          ?goal=<name>      — explicit goal override (defaults to
                              GoalManager.get_current_goal()).
          ?limit=<int>      — page size for primary list (default 10,
                              clamped to 1-50).
          ?alternatives=0   — drop the cross-goal alternatives bucket
                              from the response for a compact payload.

        Returns ``RecommendationResult.to_dict()``.
        """
        from urllib.parse import urlparse, parse_qs
        from core.brain.engine_recommender import recommend_engines

        params = parse_qs(urlparse(self.path).query)
        goal = params.get("goal", [None])[0]
        if goal:
            goal, err = validate_safe_name(goal, "goal")
            if err:
                self._json_response(400, {"error": err})
                return
        try:
            limit = int(params.get("limit", ["10"])[0])
        except ValueError:
            limit = 10
        limit = max(1, min(50, limit))

        # alternatives=0 / false disables the bucket
        alt_param = params.get("alternatives", ["1"])[0].lower()
        include_alternatives = alt_param not in {"0", "false", "no"}

        try:
            result = recommend_engines(
                goal=goal,
                limit=limit,
                include_alternatives=include_alternatives,
            )
            self._json_response(200, result.to_dict())
        except Exception as exc:
            logger.warning("recommendations failed: %s", exc)
            self._json_response(500, {"error": str(exc)})

    def _get_pending_action(self, action_id: str, _params: dict) -> None:
        """GET /api/pending-actions/<id> — fetch a single action."""
        if action_id in ("stats",):
            # Routed elsewhere; defensive guard if dispatch ever
            # changes shape.
            self._pending_actions_stats()
            return
        if not _is_valid_action_id(action_id):
            self._json_response(400, {"error": "Invalid action id"})
            return
        from core.approval import get_approval_queue
        action = get_approval_queue().get(action_id)
        if action is None:
            self._json_response(404, {"error": f"Unknown action id: {action_id}"})
            return
        payload = action.to_dict()
        try:
            from core.knowledge import enrich_action_dict
            payload = enrich_action_dict(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "operator-context enrichment failed: %s", exc,
            )
        self._json_response(200, payload)

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
        from core.brain.api_narrative import enrich_response
        self._json_response(
            200, enrich_response(result, task_type=task_type, params=params),
        )

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
        from core.brain.api_narrative import enrich_response
        try:
            registry = ChainRegistry()
            result = registry.run(chain_name, data)
            self._json_response(
                200,
                enrich_response(result, task_type=f"chain:{chain_name}", params=data),
            )
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
            from core.brain.api_narrative import enrich_response
            sm = StoreManager()
            controller = AutonomousController(sm, auto_approve=bool(body.get("auto_approve", False)))
            controller.initialize()
            result = controller.run_cycle(store_id)
            self._json_response(
                200,
                enrich_response(result, task_type="auto_cycle", params={"store_id": store_id}),
            )
        except Exception as exc:
            logger.warning("cycle run failed for %s: %s", store_id, exc)
            self._json_response(500, {
                "status": "error",
                "error": str(exc),
                "narrative": (
                    f"auto_cycle failed for store_id={store_id}: {exc}"
                ),
                "next_action": (
                    "verify the store is registered (POST /api/store/sync) "
                    "and Shopify credentials are valid"
                ),
            })

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

    def _approve_pending_action(self, action_id: str, body: dict) -> None:
        """POST /api/pending-actions/<id>/approve — sign off on a pending action.

        Body (optional): ``{"by": "<operator>", "reason": "<note>"}``.
        Idempotent: re-approving an already-resolved action returns
        the current state without error.
        """
        if not _is_valid_action_id(action_id):
            self._json_response(400, {"error": "Invalid action id"})
            return
        from core.approval import get_approval_queue
        queue = get_approval_queue()
        decided_by = str(body.get("by") or body.get("decided_by") or "")[:80]
        reason = str(body.get("reason") or "")[:500]

        action = queue.approve(
            action_id, decided_by=decided_by, reason=reason,
        )
        if action is None:
            existing = queue.get(action_id)
            if existing is None:
                self._json_response(404, {"error": f"Unknown action id: {action_id}"})
                return
            self._json_response(200, {
                "status": "noop",
                "reason": f"action already in '{existing.status.value}' state",
                "action": existing.to_dict(),
            })
            return
        self._json_response(200, {"status": "approved", "action": action.to_dict()})

    def _reject_pending_action(self, action_id: str, body: dict) -> None:
        """POST /api/pending-actions/<id>/reject — block a pending action."""
        if not _is_valid_action_id(action_id):
            self._json_response(400, {"error": "Invalid action id"})
            return
        from core.approval import get_approval_queue
        queue = get_approval_queue()
        decided_by = str(body.get("by") or body.get("decided_by") or "")[:80]
        reason = str(body.get("reason") or "")[:500]

        action = queue.reject(
            action_id, decided_by=decided_by, reason=reason,
        )
        if action is None:
            existing = queue.get(action_id)
            if existing is None:
                self._json_response(404, {"error": f"Unknown action id: {action_id}"})
                return
            self._json_response(200, {
                "status": "noop",
                "reason": f"action already in '{existing.status.value}' state",
                "action": existing.to_dict(),
            })
            return
        self._json_response(200, {"status": "rejected", "action": action.to_dict()})

    def _execute_pending_action(self, action_id: str, body: dict) -> None:
        """POST /api/pending-actions/<id>/execute — replay an APPROVED action.

        Loads the action, refuses anything not in APPROVED state
        (idempotent — re-executing returns the current snapshot),
        invokes the registered dispatcher, and flips the queue
        entry to EXECUTED or FAILED via attach_result.

        Body is currently ignored; future extensions (e.g.
        ``{"dry_run": true}``) will read from it.
        """
        if not _is_valid_action_id(action_id):
            self._json_response(400, {"error": "Invalid action id"})
            return
        from core.approval import execute_action, get_approval_queue
        queue = get_approval_queue()

        existing = queue.get(action_id)
        if existing is None:
            self._json_response(404, {"error": f"Unknown action id: {action_id}"})
            return
        if existing.status.value != "approved":
            self._json_response(200, {
                "status": "noop",
                "reason": (
                    f"action is in '{existing.status.value}' state "
                    "(execute requires 'approved')"
                ),
                "action": existing.to_dict(),
            })
            return

        result_action = execute_action(action_id)
        if result_action is None:
            self._json_response(500, {
                "error": "execute_action returned None unexpectedly",
                "action_id": action_id,
            })
            return
        self._json_response(200, {
            "status": result_action.status.value,
            "action": result_action.to_dict(),
        })

    def _approvals_sweep(self, body: dict) -> None:
        """POST /api/approvals/sweep — bulk-expire stale PENDING actions.

        Body (all optional):
          - ``older_than``: age spec (``"60s"``/``"30m"``/``"24h"``/``"7d"``)
            or bare integer seconds. Default ``"7d"``.
          - ``dry_run``: bool. If true, return the candidate list
            without writing. Default false.
        """
        from core.approval.queue import parse_age_spec
        spec = body.get("older_than") or "7d"
        max_age = parse_age_spec(str(spec))
        if max_age is None:
            self._json_response(400, {
                "error": f"Invalid 'older_than': {spec!r}",
                "hint": "Expected '60s', '30m', '24h', '7d', or integer seconds.",
            })
            return
        dry_run = bool(body.get("dry_run", False))

        from core.approval.queue import get_approval_queue
        queue = get_approval_queue()

        if dry_run:
            import time as _time
            cutoff = _time.time() - max_age
            candidates = [
                a for a in queue.list_pending(limit=10_000)
                if a.proposed_at < cutoff
            ]
            self._json_response(200, {
                "status": "dry_run",
                "max_age_seconds": int(max_age),
                "count": len(candidates),
                "candidates": [a.to_dict() for a in candidates],
            })
            return

        expired = queue.expire_stale(max_age_seconds=max_age)
        self._json_response(200, {
            "status": "swept",
            "max_age_seconds": int(max_age),
            "expired_count": len(expired),
            "expired": [a.to_dict() for a in expired],
        })

    def _approvals_approve_all(self, body: dict) -> None:
        """POST /api/approvals/approve-all — bulk-approve PENDING with filters.

        Body (all optional):
          - ``engine``: restrict to one engine name
          - ``min_confidence``: float floor (0.0-1.0); None confidence
            treated as 0.0 (gate cannot be bypassed by missing data)
          - ``by``: operator name (default "operator")
          - ``reason``: decision note (default "bulk_approve")
          - ``execute``: bool, also run executor on each (default false)
          - ``dry_run``: bool, preview without writing (default false)
        """
        engine = body.get("engine")
        if engine is not None and not isinstance(engine, str):
            self._json_response(400, {"error": "'engine' must be a string"})
            return
        try:
            mc_raw = body.get("min_confidence")
            min_confidence = float(mc_raw) if mc_raw is not None else None
        except (TypeError, ValueError):
            self._json_response(400, {
                "error": "'min_confidence' must be a number",
            })
            return
        decided_by = str(body.get("by") or "operator")[:80]
        reason = str(body.get("reason") or "bulk_approve")[:500]
        execute = bool(body.get("execute", False))
        dry_run = bool(body.get("dry_run", False))

        from core.approval.queue import get_approval_queue
        queue = get_approval_queue()

        candidates = queue.list_pending(engine=engine, limit=10_000)
        if min_confidence is not None:
            candidates = [
                a for a in candidates
                if (a.confidence or 0.0) >= min_confidence
            ]

        if dry_run:
            self._json_response(200, {
                "status": "dry_run",
                "count": len(candidates),
                "candidates": [a.to_dict() for a in candidates],
            })
            return

        approved_ids: list[str] = []
        executed_ids: list[str] = []
        skipped_ids: list[str] = []
        for a in candidates:
            decision = queue.approve(
                a.id, decided_by=decided_by, reason=reason,
            )
            if decision is None:
                skipped_ids.append(a.id)
                continue
            approved_ids.append(a.id)
            if execute:
                from core.approval.executor import execute_action
                from core.approval.queue import ApprovalStatus
                result = execute_action(a.id)
                if result is not None and result.status == (
                    ApprovalStatus.EXECUTED
                ):
                    executed_ids.append(a.id)

        self._json_response(200, {
            "status": "approved",
            "approved_count": len(approved_ids),
            "executed_count": len(executed_ids) if execute else None,
            "approved_ids": approved_ids,
            "executed_ids": executed_ids if execute else [],
            "skipped_ids": skipped_ids,
        })

    def _approvals_audit(self) -> None:
        """GET /api/approvals/audit — dispatcher coverage audit.

        Returns a JSON summary of which action_types engines enqueue
        vs which the executor can dispatch. Surfaces Pattern K gaps
        (silent execute failures).
        """
        from core.approval.coverage_audit import audit_coverage
        try:
            report = audit_coverage()
        except Exception as exc:
            self._json_response(500, {"error": f"Audit failed: {exc}"})
            return
        self._json_response(200, {
            "enqueue_site_count": len(report.enqueued),
            "registered_count": len(report.registered),
            "registered": report.registered,
            "missing": report.missing,
            "orphaned": report.orphaned,
            "has_gaps": report.has_gaps,
            "enqueue_sites": [
                {
                    "action_type": s.action_type,
                    "file_path": s.file_path,
                    "line": s.line,
                }
                for s in report.enqueued
            ],
        })

    def _classify_intent(self, body: dict) -> None:
        """POST /api/intent — classify free-text into an engine.

        Body: ``{"text": "increase my margins", "language": "auto"}``
        Returns the :class:`IntentResult` plus a suggested
        ``next_step`` string the caller can use to construct a
        follow-up ``/api/task`` request when the match is high
        enough.
        """
        from core.brain.intent_router import (
            classify_intent, list_supported_engines,
        )

        text = body.get("text") or body.get("query") or ""
        language = str(body.get("language") or "auto")[:8]
        if not isinstance(text, str) or not text.strip():
            self._json_response(400, {
                "error": "Missing 'text' field",
                "hint": "POST {\"text\": \"<your request>\"}",
                "supported_engines": list_supported_engines(),
            })
            return

        result = classify_intent(text, language=language)
        payload = result.to_dict()
        if result.engine is not None:
            # Any above-floor match earns a routing suggestion;
            # confidence in the payload tells the caller how
            # much to trust it.
            payload["next_step"] = (
                f"POST /api/task with task_type='{result.engine}' "
                f"and the relevant params"
            )
            if result.confidence < 0.4:
                payload["next_step"] += " (low confidence — verify before executing)"
        else:
            payload["next_step"] = (
                "rephrase the request with a specific verb + noun "
                "(e.g. 'create a 10% promo code', 'archive declining "
                "products') or pick from supported_engines"
            )
            payload["supported_engines"] = list_supported_engines()
        self._json_response(200, payload)

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
        from core.brain.api_narrative import enrich_response
        self._json_response(
            200,
            enrich_response(result, task_type=f"agent:{agent}:{task}", params=data),
        )

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
        from core.brain.api_narrative import enrich_response
        self._json_response(
            200,
            enrich_response(result, task_type=f"workflow:{workflow}", params=data),
        )

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
