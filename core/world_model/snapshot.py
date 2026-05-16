"""Per-store world-model snapshot.

Aggregates store state from every read surface (store manager,
sync service, configurator dry-run, store_design engine,
approval queue, decision log) into one dict.

Designed to be cheap: skippable live probes, lazy imports so a
test that mocks one section doesn't have to mock all of them,
and per-section ``checked`` flags so callers can reason about
"why is this empty".
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class WorldModel:
    """Per-store world-model aggregator.

    Default construction uses the process-wide singletons (store
    manager + approval queue). Tests pass ``sm`` / ``queue`` to
    swap in fakes without touching the global state.
    """

    def __init__(
        self,
        *,
        sm: Any = None,
        queue: Any = None,
    ) -> None:
        self._sm_override = sm
        self._queue_override = queue

    # ── Section assemblers ──────────────────────────────────

    def _store_manager(self) -> Any:
        if self._sm_override is not None:
            return self._sm_override
        from data_pipeline.store.store_manager import StoreManager
        return StoreManager()

    def _approval_queue(self) -> Any:
        if self._queue_override is not None:
            return self._queue_override
        from core.approval.queue import get_approval_queue
        return get_approval_queue()

    def _section_store(self, sm: Any, store_id: str) -> dict:
        try:
            store = sm.get_store(store_id) or {}
        except Exception as exc:  # noqa: BLE001
            logger.debug("world_model store probe raised: %s", exc)
            store = {}
        return {
            "shop_url": store.get("shop_url", "") or "",
            "niche": store.get("niche") or None,
            "store_type": store.get("store_type") or None,
            "is_active": bool(store.get("is_active")),
            "name": store.get("name") or store_id,
        }

    def _section_stats(self, sm: Any, store_id: str) -> dict:
        try:
            stats = sm.get_stats(store_id) or {}
        except Exception as exc:  # noqa: BLE001
            logger.debug("world_model stats probe raised: %s", exc)
            stats = {}
        return {
            "products": int(stats.get("products", 0)),
            "orders": int(stats.get("orders", 0)),
            "customers": int(stats.get("customers", 0)),
            "total_revenue": float(stats.get("total_revenue", 0.0)),
        }

    def _section_sync(self, sm: Any, store_id: str) -> dict:
        out = {
            "last_sync_at": None,
            "last_sync_status": None,
            "age_seconds": None,
        }
        try:
            from data_pipeline.store.sync_service import SyncService
            sync = SyncService(sm)
            sync_status = sync.get_status() or {}
            for si in sync_status.get("stores", []):
                if si.get("store_id") == store_id:
                    last_sync = si.get("last_sync")
                    out["last_sync_at"] = last_sync
                    out["last_sync_status"] = si.get("last_status")
                    if last_sync:
                        out["age_seconds"] = time.time() - last_sync
                    break
        except Exception as exc:  # noqa: BLE001
            logger.debug("world_model sync probe raised: %s", exc)
        return out

    def _section_connection(self, sm: Any, store_id: str) -> dict:
        try:
            conn = sm.test_connection(store_id) or {}
        except Exception as exc:  # noqa: BLE001
            logger.debug("world_model connect probe raised: %s", exc)
            return {
                "checked": True,
                "connected": False,
                "shop": "",
                "error": str(exc),
            }
        return {
            "checked": True,
            "connected": bool(conn.get("connected")),
            "shop": conn.get("shop", "") or "",
            "error": (conn.get("error") or None),
        }

    def _section_config(
        self, sm: Any, store_id: str, *, niche: str | None,
        store_name: str,
    ) -> dict:
        """Drift count from a configurator dry_run. Skipped silently
        when credentials are missing or the configurator raises."""
        try:
            creds = sm.get_credentials(store_id) or {}
        except Exception as exc:  # noqa: BLE001
            logger.debug("world_model creds probe raised: %s", exc)
            return {"checked": True, "error": str(exc)}
        if not creds or not creds.get("shop_url"):
            return {"checked": True, "error": "no_credentials"}

        token = creds.get("api_key") or ""
        if not token and creds.get("client_id") and creds.get("client_secret"):
            try:
                from core.auth.shopify_auth import ShopifyAuth
                token = ShopifyAuth(
                    creds["shop_url"],
                    creds["client_id"],
                    creds["client_secret"],
                ).get_token()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "world_model oauth token resolution raised: %s",
                    exc,
                )
                return {"checked": True, "error": f"oauth: {exc}"}
        if not token:
            return {"checked": True, "error": "no_token"}

        try:
            from execution.store_configurator import StoreConfigurator
            configurator = StoreConfigurator(dry_run=True)
            result = configurator.configure(
                creds["shop_url"], token,
                niche=niche or "general",
                store_name=store_name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("world_model configurator dry-run raised: %s", exc)
            return {"checked": True, "error": str(exc)}
        plan = result.get("plan") or []
        return {
            "checked": True,
            "planned_writes": len(plan),
            "has_drift": bool(plan),
            "feature_count": len(result.get("results") or {}),
        }

    def _section_design(self) -> dict:
        """Cheap probe: runs the store_design engine with empty
        input. Engine is Pattern Q compliant so this never throws
        on missing data."""
        try:
            from engines.store_design.flow import StoreDesignEngine
            out = StoreDesignEngine().run({
                "status": "success",
                "data": {},
                "meta": {},
                "error": None,
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug("world_model design probe raised: %s", exc)
            return {"checked": False, "error": str(exc)}
        if out.get("status") != "success" or not out.get("data"):
            return {
                "checked": True,
                "error": out.get("error") or "no_data",
            }
        data = out["data"]
        return {
            "checked": True,
            "estimated_conversion_lift": float(
                data.get("estimated_conversion_lift", 0.0) or 0.0,
            ),
            "layout_count": len(
                data.get("layout_recommendations", []) or [],
            ),
            "mobile_count": len(
                data.get("mobile_optimizations", []) or [],
            ),
        }

    def _section_approvals(self) -> dict:
        """Pending action counts. GLOBAL (not per-store) -- the
        pending_actions schema has no store_id column yet, so we
        report engine-level rollups instead of per-store.
        """
        try:
            queue = self._approval_queue()
            stats = queue.stats() or {}
            by_engine = queue.stats_by_engine() or {}
        except Exception as exc:  # noqa: BLE001
            logger.debug("world_model approvals probe raised: %s", exc)
            return {"checked": False, "error": str(exc)}
        pending = int(stats.get("pending", 0))
        per_engine = {
            engine: int(counts.get("pending", 0))
            for engine, counts in by_engine.items()
            if counts.get("pending", 0)
        }
        return {
            "checked": True,
            "scope": "global",
            "pending_total": pending,
            "pending_by_engine": per_engine,
        }

    def _section_decisions(self, *, limit: int = 25) -> dict:
        """Recent decision-log entries. GLOBAL (same caveat as
        approvals).
        """
        try:
            queue = self._approval_queue()
            recent = queue.list_decisions(limit=limit) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug("world_model decisions probe raised: %s", exc)
            return {"checked": False, "error": str(exc)}
        return {
            "checked": True,
            "scope": "global",
            "recent_count": len(recent),
            "last_occurred_at": (
                recent[0].get("occurred_at") if recent else None
            ),
        }

    # ── Public API ──────────────────────────────────────────

    def snapshot(
        self,
        store_id: str,
        *,
        skip_live: bool = False,
    ) -> dict[str, Any]:
        """Build the per-store world-model snapshot.

        Args:
            store_id: Target store identifier.
            skip_live: When True, skips the connection + config
                probes (the two sections that call Shopify).
                Sync / design / approvals / decisions are local
                reads so they always run.

        Returns:
            Snapshot dict with the section structure documented
            in the module docstring. Missing sections never
            raise -- they surface as ``{"checked": False, ...}``
            or carry an ``error`` field.
        """
        sm = self._store_manager()
        store = self._section_store(sm, store_id)
        stats = self._section_stats(sm, store_id)
        sync = self._section_sync(sm, store_id)

        if skip_live:
            connection = {"checked": False}
            config = {"checked": False}
        else:
            connection = self._section_connection(sm, store_id)
            # Skip the configurator dry-run if connection failed --
            # would just waste a GraphQL hop.
            if connection.get("connected"):
                config = self._section_config(
                    sm, store_id,
                    niche=store.get("niche"),
                    store_name=store.get("name") or store_id,
                )
            else:
                config = {
                    "checked": False,
                    "error": "connection_failed",
                }

        design = self._section_design()
        approvals = self._section_approvals()
        decisions = self._section_decisions()

        return {
            "store_id": store_id,
            "fetched_at": time.time(),
            "store": store,
            "stats": stats,
            "sync": sync,
            "connection": connection,
            "config": config,
            "design": design,
            "approvals": approvals,
            "decisions": decisions,
        }


def snapshot(store_id: str, *, skip_live: bool = False) -> dict[str, Any]:
    """Module-level convenience: equivalent to
    ``WorldModel().snapshot(store_id, skip_live=skip_live)``.

    The class form exists so tests + callers can inject fake
    store managers / approval queues; this is the right entry
    point for everyone else.
    """
    return WorldModel().snapshot(store_id, skip_live=skip_live)
