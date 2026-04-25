"""TikTokShopPoller — cycle-driven order ingestor.

Contract (one method owner or daemon cares about):

    summary = TikTokShopPoller.open().poll_once()

Steps the poll performs:

  1. Guard: is the TikTok Shop adapter configured? If not,
     return ``{"polled": 0, "new": 0, "reason": "not_configured"}``
     silently — this is the common case on stores that
     haven't opted into Z6 yet.
  2. Fetch orders via
     ``TikTokShopAdapter.fetch_orders(order_status="AWAITING_SHIPMENT")``
     — paid orders that haven't shipped are the most useful
     learning signal (order validated the conversion path;
     shipping-tail noise is irrelevant).
  3. For each order whose id is not already in the local
     ``seen`` table:
        a. Emit an ``EngineOutcome`` to the canonical
           ``engine_outcome_bus`` — kpi="revenue_usd",
           value=total_amount, engine="tiktok_shop",
           source="tiktok_shop_poller". Feeds the same
           pattern miner + feedback store that Shopify
           order webhooks feed.
        b. Mark the order id seen.
  4. Return a summary dict the cycle logs.

Why SQLite for the seen cache:
  * Survives daemon restart (env-var idempotency would be
    lost on every deploy).
  * Cheap — same WAL pattern as the social scheduler, no
    concurrency concerns.
"""
from __future__ import annotations

import dataclasses
import logging
import os
import sqlite3
import threading
import time
from typing import Any


_logger = logging.getLogger("shopai.tiktok_shop_poller")

_DEFAULT_DB_PATH = os.path.join(
    "data", "tiktok_shop_seen.db",
)


@dataclasses.dataclass(frozen=True)
class PollerSummary:
    polled: int
    new: int
    reason: str = ""
    emitted: int = 0
    emit_errors: int = 0

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tts_seen_orders (
            order_id  TEXT PRIMARY KEY,
            total_usd REAL NOT NULL DEFAULT 0.0,
            ts_seen   INTEGER NOT NULL
        )
        """,
    )
    conn.commit()
    return conn


class TikTokShopPoller:
    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._path = db_path
        self._conn = _connect(db_path)
        self._lock = threading.Lock()

    @classmethod
    def open(
        cls, db_path: str | None = None,
    ) -> "TikTokShopPoller":
        return cls(db_path or _DEFAULT_DB_PATH)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass

    # ── Public ────────────────────────────────────────

    def poll_once(
        self,
        *,
        adapter: Any = None,
        bus: Any = None,
        order_status: str = "AWAITING_SHIPMENT",
        max_orders: int = 50,
    ) -> PollerSummary:
        """One pass through the adapter. Accepts explicit
        ``adapter`` + ``bus`` for tests; defaults pull the
        module singletons.
        """
        if adapter is None:
            try:
                from core.adapters.tiktok_shop import (
                    TikTokShopAdapter,
                )
                adapter = TikTokShopAdapter()
            except Exception as exc:  # noqa: BLE001
                return PollerSummary(
                    polled=0, new=0,
                    reason=f"adapter_import_fail: {exc}",
                )
        if not adapter.is_available():
            return PollerSummary(
                polled=0, new=0, reason="not_configured",
            )
        try:
            rows = adapter.fetch_orders(
                order_status=order_status,
                page_size=max(1, min(int(max_orders), 100)),
            ) or []
        except Exception as exc:  # noqa: BLE001
            return PollerSummary(
                polled=0, new=0,
                reason=f"fetch_error: {type(exc).__name__}",
            )
        if not isinstance(rows, list):
            return PollerSummary(
                polled=0, new=0,
                reason="fetch_returned_non_list",
            )

        if bus is None:
            try:
                from core.integration import (
                    get_engine_outcome_bus,
                )
                bus = get_engine_outcome_bus()
            except Exception as exc:  # noqa: BLE001
                _logger.debug(
                    "bus lazy load: %s", exc,
                )
                bus = None

        new_count = 0
        emitted = 0
        emit_errors = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            order_id = str(row.get("order_id") or "")
            if not order_id:
                continue
            if self._already_seen(order_id):
                continue
            try:
                total = float(row.get("total_amount") or 0)
            except (TypeError, ValueError):
                total = 0.0
            self._mark_seen(order_id, total)
            new_count += 1
            if bus is None:
                continue
            try:
                self._emit(bus, row)
                emitted += 1
            except Exception as exc:  # noqa: BLE001
                emit_errors += 1
                _logger.debug(
                    "tts_poller emit failed %s: %s",
                    order_id, exc,
                )

        return PollerSummary(
            polled=len(rows),
            new=new_count,
            emitted=emitted,
            emit_errors=emit_errors,
        )

    # ── Internals ────────────────────────────────────

    def _already_seen(self, order_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM tts_seen_orders WHERE "
            "order_id = ? LIMIT 1",
            (order_id,),
        ).fetchone()
        return row is not None

    def _mark_seen(
        self, order_id: str, total_usd: float,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO tts_seen_orders "
                "(order_id, total_usd, ts_seen) VALUES "
                "(?, ?, ?)",
                (
                    order_id,
                    float(total_usd or 0.0),
                    int(time.time()),
                ),
            )
            self._conn.commit()

    def _emit(
        self, bus: Any, row: dict[str, Any],
    ) -> None:
        from core.integration.engine_outcome_bus import (
            EngineOutcome,
        )
        try:
            total = float(row.get("total_amount") or 0)
        except (TypeError, ValueError):
            total = 0.0
        order_id = str(row.get("order_id") or "")
        bus.report(EngineOutcome(
            engine="tiktok_shop",
            kpi="revenue_usd",
            value=total,
            ok=total > 0,
            source="tiktok_shop_poller",
            context={
                "order_id": order_id,
                "currency": str(
                    row.get("currency") or "USD",
                ),
                "line_item_count": len(
                    row.get("line_items") or (),
                ),
                "buyer_email_hash": _hash_if_set(
                    row.get("buyer_email"),
                ),
            },
            ts=time.time(),
        ))


def _hash_if_set(value: Any) -> str:
    """Hash the buyer email so the context carries an
    identity without leaking PII."""
    if not value:
        return ""
    import hashlib
    return hashlib.sha256(
        str(value).lower().encode("utf-8"),
    ).hexdigest()[:16]
