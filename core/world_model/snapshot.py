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

    def _section_approvals(self, *, store_id: str | None = None) -> dict:
        """Pending action counts. PER-STORE when ``store_id`` is
        supplied (rows with that store_id only); GLOBAL otherwise.

        Rows enqueued before the store_id column existed have
        ``store_id=NULL`` and are excluded from filtered results.
        """
        try:
            queue = self._approval_queue()
            if store_id is not None:
                # Per-store: count pending for this store directly
                # via list_pending(store_id=...). The fleet-wide
                # stats_by_engine() can't filter per-store, so we
                # roll up from the listed actions.
                try:
                    pending_actions = queue.list_pending(
                        store_id=store_id, limit=10_000,
                    )
                except TypeError:
                    # Legacy fake queues without store_id kwarg
                    # → fall back to global; better than crash.
                    return self._section_approvals(store_id=None)
                per_engine: dict[str, int] = {}
                for a in pending_actions:
                    eng = (
                        a.engine if hasattr(a, "engine")
                        else a.get("engine", "?")
                    )
                    per_engine[eng] = per_engine.get(eng, 0) + 1
                return {
                    "checked": True,
                    "scope": "per_store",
                    "store_id": store_id,
                    "pending_total": len(pending_actions),
                    "pending_by_engine": per_engine,
                }
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

    def _section_decisions(
        self, *, limit: int = 25, store_id: str | None = None,
    ) -> dict:
        """Recent decision-log entries. PER-STORE when ``store_id``
        is supplied (executed/failed actions tagged with this
        store_id); GLOBAL otherwise.

        For per-store mode, we derive recent activity from
        ``list_by_status(EXECUTED + FAILED)`` filtered by store_id
        rather than the global ``list_decisions`` (which has no
        store_id link). For global mode, behavior is unchanged.
        """
        try:
            queue = self._approval_queue()
            if store_id is not None:
                # Per-store: derive from list_by_status.
                try:
                    from core.approval.queue import ApprovalStatus
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "world_model decisions per-store import "
                        "failed: %s", exc,
                    )
                    return {"checked": False, "error": str(exc)}
                actions: list = []
                for st in (
                    ApprovalStatus.EXECUTED, ApprovalStatus.FAILED,
                ):
                    try:
                        actions.extend(queue.list_by_status(
                            st, store_id=store_id, limit=limit,
                        ))
                    except TypeError:
                        # Legacy fake queue without store_id kwarg
                        # → fall back to global.
                        return self._section_decisions(
                            limit=limit, store_id=None,
                        )
                # Most recent first
                actions.sort(
                    key=lambda a: -(getattr(a, "decided_at", 0) or 0),
                )
                actions = actions[:limit]
                last = (
                    actions[0].decided_at
                    if actions and hasattr(actions[0], "decided_at")
                    else None
                )
                return {
                    "checked": True,
                    "scope": "per_store",
                    "store_id": store_id,
                    "recent_count": len(actions),
                    "last_occurred_at": last,
                }
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

    def _section_transfers(
        self, *, store_id: str, limit: int = 50,
    ) -> dict:
        """Cross-store transfer activity touching this store.

        Scans ``pending_actions`` for rows whose narrative was
        written by ``shopai transfer apply`` (starts with
        ``Transfer suggestion:`` or has the operator-note
        prefix variant). Splits results into two buckets:

          - ``incoming``: this store is the TARGET of a transfer.
            The row's ``store_id`` column matches.
          - ``outgoing``: this store is the SOURCE of a transfer.
            Detected from narrative text ``from <store_id> to``.

        Counts by status (executed / pending / failed / other) so
        callers can see "we applied 3 transfers to this store
        last week, 2 executed, 1 still pending".

        Returns ``{"checked": True, "incoming": {...},
        "outgoing": {...}}`` on success; ``{"checked": False,
        "error": ...}`` on queue failure.
        """
        try:
            queue = self._approval_queue()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "world_model transfers queue raised: %s", exc,
            )
            return {"checked": False, "error": str(exc)}

        from core.transfer_narrative import SQL_LIKE_CLAUSE
        like_clause = SQL_LIKE_CLAUSE

        def _bucketise(rows: list) -> dict:
            bucket = {
                "total": 0, "executed": 0, "pending": 0,
                "failed": 0, "other": 0,
            }
            for r in rows:
                bucket["total"] += 1
                st = (r["status"] or "").lower()
                if st == "executed":
                    bucket["executed"] += 1
                elif st in {"pending", "approved"}:
                    bucket["pending"] += 1
                elif st == "failed":
                    bucket["failed"] += 1
                else:
                    bucket["other"] += 1
            return bucket

        # ── Incoming: store_id column matches ───────────────
        try:
            with queue._conn:
                in_rows = queue._conn.execute(
                    f"""SELECT status FROM pending_actions
                       WHERE store_id = ?
                         AND {like_clause}
                       ORDER BY proposed_at DESC LIMIT ?""",
                    (store_id, limit),
                ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "world_model transfers incoming raised: %s", exc,
            )
            in_rows = []

        # ── Outgoing: narrative contains "from <store_id> to" ─
        # This is the same SQL LIKE approach the CLI's
        # ``transfer history`` uses (no source-store column to
        # filter on yet). Match for either ``from <id> to`` (the
        # canonical narrative tail) or ``from <id>.`` (rare edge
        # case).
        try:
            needle = f"%from {store_id} to %"
            with queue._conn:
                out_rows = queue._conn.execute(
                    f"""SELECT status FROM pending_actions
                       WHERE {like_clause}
                         AND narrative LIKE ?
                       ORDER BY proposed_at DESC LIMIT ?""",
                    (needle, limit),
                ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "world_model transfers outgoing raised: %s", exc,
            )
            out_rows = []

        return {
            "checked": True,
            "incoming": _bucketise(in_rows),
            "outgoing": _bucketise(out_rows),
        }

    def _section_recent_outcomes(
        self, *, store_id: str, limit: int = 10,
        since_hours: float = 168.0,
    ) -> dict:
        """Recent outcome events for actions tagged with this store.

        Surfaces the polarity + revenue stream operators want to
        see at a glance: "what's been working / failing on this
        store in the last week?" Uses
        ``queue.list_recent_outcomes(store_id=...)`` so the JOIN
        + filter happens in SQL.

        Returns ``{"checked": True, "count": N, "summary":
        {positive, negative, neutral, revenue}, "recent": [...]}``
        on success. ``recent`` is capped at ``limit`` rows
        (newest first); ``count`` is the same length (this is
        not a paginator -- callers wanting more should hit the
        queue directly).

        Per-store filter requires PR #280's queue extension.
        Pre-#280 queues raise TypeError on the kwarg; the
        section falls back to ``{"checked": False, "error":
        ...}`` rather than crashing the snapshot.
        """
        try:
            queue = self._approval_queue()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "world_model recent_outcomes queue raised: %s",
                exc,
            )
            return {"checked": False, "error": str(exc)}

        since_seconds = max(0.0, float(since_hours)) * 3600.0
        try:
            rows = queue.list_recent_outcomes(
                limit=limit,
                store_id=store_id,
                since_seconds=since_seconds,
            )
        except TypeError as exc:
            # Pre-PR-#280 queue without store_id kwarg.
            logger.debug(
                "world_model recent_outcomes pre-#280 queue: %s",
                exc,
            )
            return {
                "checked": False,
                "error": "list_recent_outcomes lacks store_id "
                         "support (needs PR #280 or later)",
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "world_model recent_outcomes raised: %s", exc,
            )
            return {"checked": False, "error": str(exc)}

        # Aggregate via shared rollup. Outcomes come back as
        # ``{polarity, metrics, ...}`` dicts -- exactly what
        # ``aggregate_outcomes`` expects.
        try:
            from core.approval.outcome_aggregator import (
                aggregate_outcomes,
            )
            stats = aggregate_outcomes(rows)
            summary = {
                "positive": stats.positive,
                "negative": stats.negative,
                "neutral": stats.neutral,
                "revenue": stats.revenue,
            }
        except Exception as exc:  # noqa: BLE001
            # Aggregator failure shouldn't drop the section.
            logger.debug(
                "world_model recent_outcomes aggregate raised: %s",
                exc,
            )
            summary = {
                "positive": 0, "negative": 0, "neutral": 0,
                "revenue": 0.0,
            }

        return {
            "checked": True,
            "count": len(rows),
            "summary": summary,
            "recent": rows,
        }

    def _section_quarantine(
        self, store_id: str | None = None,
    ) -> dict:
        """Quarantine state, optionally filtered to a specific
        store.

        The underlying quarantine state file is GLOBAL, but the
        ``alert_paused`` set is now ``(engine, store_id)``
        tuples (per-store granularity, from PR #320). When the
        snapshot is being built for a specific store, this
        section returns:

          - The full fleet-wide listing (exemptions, released,
            all alert_paused pairs across the fleet) -- so
            operators see the global picture.
          - A ``for_this_store`` sub-block surfacing ONLY the
            entries affecting ``store_id``: fleet-wide pauses
            (which affect every store) plus the per-store
            pauses specifically for ``store_id``.

        When called without ``store_id`` (e.g. from a fleet
        view), ``for_this_store`` stays empty.

        Bridge config is gated behind PR #294's
        ``core.approval.alert_quarantine`` module. Missing
        module falls back to ``bridge: None``.
        """
        try:
            from core.approval import quarantine
            s = quarantine.load_state()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "world_model quarantine load raised: %s", exc,
            )
            return {"checked": False, "error": str(exc)}

        bridge: dict | None = None
        try:
            from core.approval import alert_quarantine as aq
            bridge = {
                "enabled": aq.is_enabled(),
                "threshold_days": aq.threshold_days(),
                "window_days": aq.window_days(),
            }
        except ImportError as exc:
            # Pre-PR-#294 deployments don't have the bridge.
            logger.debug(
                "world_model quarantine bridge import failed: %s",
                exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "world_model quarantine bridge readout raised: %s",
                exc,
            )

        # ``alert_paused`` is now ``frozenset[(engine, store_id)]``.
        # Surface engine names (deduplicated) for backward
        # compatibility with callers that just want the list of
        # paused engines. The per-store breakdown is exposed
        # separately via ``alert_paused_pairs`` so empire-AGI
        # consumers can drill into "which stores".
        raw_paused = getattr(s, "alert_paused", frozenset())
        alert_paused: list[str] = []
        alert_paused_pairs: list[list] = []
        for entry in raw_paused:
            if isinstance(entry, tuple) and len(entry) == 2:
                engine, store = entry
                alert_paused_pairs.append([engine, store])
                if engine not in alert_paused:
                    alert_paused.append(engine)
            else:
                # Legacy string entry (pre-per-store schema)
                alert_paused.append(str(entry))
                alert_paused_pairs.append([str(entry), None])
        alert_paused.sort()
        alert_paused_pairs.sort(
            key=lambda p: (p[0], p[1] or ""),
        )

        # Candidate engines for release/pause -- the bridge's
        # forward + reverse views. Empty when the bridge module
        # isn't installed or the alert_history is empty.
        release_candidates: list[str] = []
        pause_candidates: list[str] = []
        try:
            from core.approval import alert_quarantine as aq
            release_candidates = [
                c["engine"]
                for c in aq.find_release_candidates()
            ]
            pause_candidates = [
                c["engine"]
                for c in aq.find_pause_candidates()
                if c.get("blocked_by") is None
            ]
        except ImportError as exc:
            logger.debug(
                "world_model quarantine candidates import "
                "failed: %s", exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "world_model quarantine candidates raised: %s",
                exc,
            )

        # Per-store filter: which fleet-level entries actually
        # block THIS store? Fleet-wide pauses ((engine, None))
        # affect every store. Per-store pauses match only on
        # exact store_id. Exempt + released are engine-only and
        # apply fleet-wide -- so they affect this store too if
        # present.
        for_this_store: dict[str, list[str]] = {
            "exempt": [],
            "released": [],
            "alert_paused": [],
        }
        if store_id is not None:
            for_this_store["exempt"] = sorted(s.exemptions)
            for_this_store["released"] = sorted(s.released)
            engines_blocked: set[str] = set()
            for entry in raw_paused:
                if isinstance(entry, tuple) and len(entry) == 2:
                    engine, pause_store = entry
                    if (
                        pause_store is None
                        or pause_store == store_id
                    ):
                        engines_blocked.add(engine)
                else:
                    # Legacy string entry = fleet-wide
                    engines_blocked.add(str(entry))
            for_this_store["alert_paused"] = sorted(
                engines_blocked,
            )

        # Recent alert events -- gives the snapshot a directional
        # signal (is this engine getting worse, better, stable?)
        # beyond the static "currently paused" flag. Capped at 10
        # so the snapshot stays inspectable in a terminal.
        recent_alerts: list[dict] = []
        try:
            from core.approval.alert_history import recent_history
            for event in recent_history(since_seconds=86400.0 * 7.0)[:10]:
                recent_alerts.append({
                    "engine": getattr(event, "engine", "") or "",
                    "recorded_at": float(
                        getattr(event, "recorded_at", 0.0) or 0.0,
                    ),
                    "drop": float(
                        getattr(event, "drop", 0.0) or 0.0,
                    ),
                    "recent_score": float(
                        getattr(event, "recent_score", 0.0) or 0.0,
                    ),
                    "baseline_score": float(
                        getattr(event, "baseline_score", 0.0) or 0.0,
                    ),
                    "store_id": getattr(event, "store_id", None),
                })
        except ImportError as exc:
            logger.debug(
                "world_model alert_history import failed: %s", exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "world_model alert_history readout raised: %s",
                exc,
            )

        return {
            "checked": True,
            # Scope changed: when a store filter is active the
            # data has both fleet-wide AND per-store views.
            "scope": (
                "per_store" if store_id is not None else "fleet"
            ),
            "store_id": store_id,
            "exemptions": sorted(s.exemptions),
            "released": sorted(s.released),
            "alert_paused": alert_paused,
            "alert_paused_pairs": alert_paused_pairs,
            "alert_release_candidates": release_candidates,
            "alert_pause_candidates": pause_candidates,
            "for_this_store": for_this_store,
            "recent_alerts": recent_alerts,
            "bridge": bridge,
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
        # Per-store scope for approvals + decisions when the
        # store_id maps to actual tagged rows. Sections fall back
        # to global if the queue layer or actions don't carry
        # store_id (pre-migration data).
        approvals = self._section_approvals(store_id=store_id)
        decisions = self._section_decisions(store_id=store_id)
        transfers = self._section_transfers(store_id=store_id)
        recent_outcomes = self._section_recent_outcomes(
            store_id=store_id,
        )
        quarantine = self._section_quarantine(store_id=store_id)

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
            "transfers": transfers,
            "recent_outcomes": recent_outcomes,
            "quarantine": quarantine,
        }


def snapshot(store_id: str, *, skip_live: bool = False) -> dict[str, Any]:
    """Module-level convenience: equivalent to
    ``WorldModel().snapshot(store_id, skip_live=skip_live)``.

    The class form exists so tests + callers can inject fake
    store managers / approval queues; this is the right entry
    point for everyone else.
    """
    return WorldModel().snapshot(store_id, skip_live=skip_live)
