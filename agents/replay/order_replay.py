"""Order replay — feed historical or synthetic Shopify
``order.paid`` payloads through the live webhook handler.

Why this exists (CLAUDE.md §4d quality principle, T1→T2 bridge):
ShopAI's learning loop (Deliberation back-fill, engine outcome
bus, PatternMiner, RuleBook promotion) only fires when real
orders arrive. Waiting for real traffic to calibrate pattern
thresholds is slow + unsafe. This module lets the owner feed
a curated JSONL file of historical orders (exported from a
real Shopify store) or synthetic fixtures through the exact
same webhook entry point the live daemon uses, producing
genuine learning signal without needing a paying customer.

Deterministic, no LLM. The ``OrderWebhookHandler`` does the
full fan-out (OutcomeRecorder + KPITracker + RevenueTracker +
brain hooks + agentic attribution + Deliberation back-fill +
engine outcome bus) — replay just pushes payloads at it.

Pure stdlib. Dependency-injected handler so tests run offline.

File format (one JSON object per line):

    {"id": "ord-1", "total_price": "29.99",
     "line_items": [...], "note_attributes": [
       {"name": "shopai_decision_id", "value": "dec_abc"}
     ], ...}

Invocations:

    # From file (owner workflow — export Shopify orders to JSONL
    # or hand-write synthetic ones for threshold tuning):
    $ shopai replay-orders data/replay/pet_store_q1.jsonl

    # Programmatic (tests):
    >>> from agents.replay import replay_orders
    >>> stats = replay_orders([{...}, {...}])
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


logger = logging.getLogger("agents.replay.order_replay")


@dataclass
class OrderReplayResult:
    """Per-order replay outcome."""

    order_id: str
    ok: bool
    handler_output: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "ok": self.ok,
            "handler_output": dict(self.handler_output),
            "error": self.error,
        }


@dataclass
class ReplayStats:
    """Aggregate counters across a replay run."""

    attempted: int = 0
    successful: int = 0
    failed: int = 0
    skipped_non_dict: int = 0
    total_revenue_usd: float = 0.0
    deliberations_observed: int = 0
    duration_s: float = 0.0
    results: list[OrderReplayResult] = field(
        default_factory=list,
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "successful": self.successful,
            "failed": self.failed,
            "skipped_non_dict": self.skipped_non_dict,
            "total_revenue_usd": round(
                self.total_revenue_usd, 2,
            ),
            "deliberations_observed": (
                self.deliberations_observed
            ),
            "duration_s": round(self.duration_s, 3),
            "results": [
                r.as_dict() for r in self.results[-50:]
            ],
        }


_PUBLIC_LOCK = threading.Lock()


def _default_handler() -> Any:
    from core.webhooks.order_handler import (
        OrderWebhookHandler,
    )
    return OrderWebhookHandler()


def replay_orders(
    orders: Iterable[dict[str, Any]],
    *,
    handler: Any = None,
    throttle_s: float = 0.0,
    now_fn: Any = None,
) -> ReplayStats:
    """Push each ``order_data`` dict through the live
    webhook handler's ``handle_order_paid`` path.

    Returns aggregate :class:`ReplayStats` with per-order
    results. Throttle between calls is optional so a burst
    of 1000 orders doesn't pin CPU.
    """
    now = now_fn or time.time
    h = handler if handler is not None else _default_handler()
    stats = ReplayStats()
    start = float(now())
    with _PUBLIC_LOCK:
        for raw in orders:
            if not isinstance(raw, dict):
                stats.skipped_non_dict += 1
                continue
            stats.attempted += 1
            oid = str(
                raw.get("id") or raw.get("order_id") or "",
            )
            try:
                output = h.handle_order_paid(raw)
                ok = True
                err_text = ""
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "replay order %s raised: %s",
                    oid, exc,
                )
                output = {}
                ok = False
                err_text = f"{type(exc).__name__}: {exc}"
            if ok:
                stats.successful += 1
                try:
                    stats.total_revenue_usd += float(
                        raw.get("total_price") or 0,
                    )
                except (TypeError, ValueError):
                    pass
                if output.get(
                    "deliberation_observed",
                ):
                    stats.deliberations_observed += 1
            else:
                stats.failed += 1
            stats.results.append(OrderReplayResult(
                order_id=oid,
                ok=ok,
                handler_output=(
                    dict(output)
                    if isinstance(output, dict) else {}
                ),
                error=err_text,
            ))
            if throttle_s > 0:
                time.sleep(throttle_s)
    stats.duration_s = float(now()) - start
    return stats


def replay_orders_from_file(
    path: str | Path,
    *,
    handler: Any = None,
    throttle_s: float = 0.0,
) -> ReplayStats:
    """Read a JSONL file of order dicts + replay them.
    Malformed lines log at debug + count as skipped."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    orders: list[dict[str, Any]] = []
    for i, line in enumerate(
        p.read_text().splitlines(), start=1,
    ):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.debug(
                "replay line %d bad json: %s", i, exc,
            )
            continue
        if isinstance(parsed, dict):
            orders.append(parsed)
    return replay_orders(
        orders,
        handler=handler,
        throttle_s=throttle_s,
    )
