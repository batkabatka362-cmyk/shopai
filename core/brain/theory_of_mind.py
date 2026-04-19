"""Theory of mind — belief states for customers and competitors.

Everything we've built so far models the store's own state. Real
e-commerce is adversarial / interactive: competitors move in
response to us, customers form preferences across visits.
Autonomous AI that ignores those agents runs straight into ruinous
strategies (e.g. repeatedly cutting price against a competitor who
follows us down).

This module maintains two lightweight belief models:

  CustomerMindModel  — per-segment preferences inferred from order
                        history: preferred price_band, tone affinity,
                        repeat-buy propensity, basket-add bias.
  CompetitorMindModel — per-URL price + title trajectory from the
                        competitor monitor (v2-D6), plus inferred
                        "reactivity" (probability they cut when we
                        scale, or match our kill).

Both expose ``belief()`` returning a structured snapshot the
reasoner / planner / deliberation can consult. Updates are
lightweight aggregations over memory rows — no LLM, a few ms.

Belief persistence: the latest snapshot is written back as a
``category=belief score=3.0`` memory event each update so retrieval
can quote "per our model, competitor X is a follower" with an id.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DB_PATH = Path("data/memory_intelligence.db")


@dataclass
class CustomerSegmentBelief:
    segment_key: str             # e.g. "us_mobile_first_purchase"
    order_count: int
    mean_aov: float
    preferred_price_band: str
    likely_repeat: float         # 0-1
    basket_size: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "segment_key": self.segment_key,
            "order_count": self.order_count,
            "mean_aov": round(self.mean_aov, 2),
            "preferred_price_band": self.preferred_price_band,
            "likely_repeat": round(self.likely_repeat, 3),
            "basket_size": round(self.basket_size, 2),
        }


@dataclass
class CustomerBelief:
    total_orders: int
    total_customers: int
    segments: list[CustomerSegmentBelief]
    global_aov: float
    global_repeat_rate: float
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_orders": self.total_orders,
            "total_customers": self.total_customers,
            "segment_count": len(self.segments),
            "global_aov": round(self.global_aov, 2),
            "global_repeat_rate": round(self.global_repeat_rate, 3),
            "segments": [s.as_dict() for s in self.segments],
            "ts": self.ts,
        }


@dataclass
class CompetitorBelief:
    url: str
    title: str
    samples: int
    last_price: float
    mean_price: float
    price_stddev: float
    monotonic_cuts: int           # n times price dropped consecutively
    monotonic_raises: int
    reactivity: float             # 0-1 — prob they mirror our verdicts
    last_checked: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "samples": self.samples,
            "last_price": round(self.last_price, 2),
            "mean_price": round(self.mean_price, 2),
            "price_stddev": round(self.price_stddev, 2),
            "monotonic_cuts": self.monotonic_cuts,
            "monotonic_raises": self.monotonic_raises,
            "reactivity": round(self.reactivity, 3),
            "last_checked": self.last_checked,
        }


# ── Public API ──────────────────────────────────────────────

def customer_belief() -> CustomerBelief:
    """Aggregate order events into per-segment beliefs."""
    orders = _pull_orders()
    if not orders:
        return CustomerBelief(
            total_orders=0, total_customers=0,
            segments=[], global_aov=0.0, global_repeat_rate=0.0,
            ts=time.time(),
        )
    total_orders = len(orders)
    # Count per customer email so we can estimate repeat rate
    per_customer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for o in orders:
        email = o.get("customer_email") or "(guest)"
        per_customer[email].append(o)
    total_customers = len(per_customer)
    repeat_customers = sum(1 for v in per_customer.values() if len(v) >= 2)
    global_repeat = repeat_customers / total_customers if total_customers else 0.0
    global_aov = statistics.fmean(o.get("total_price", 0) for o in orders)

    # Group by segment: source_name (web/meta_ads) × price band
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for o in orders:
        source = o.get("source_name") or "unknown"
        price = float(o.get("total_price") or 0)
        band = _price_band(price)
        key = f"{source}_{band}"
        groups[key].append(o)

    segments: list[CustomerSegmentBelief] = []
    for key, seg_orders in groups.items():
        aov = statistics.fmean(o.get("total_price", 0) for o in seg_orders)
        prices = [float(o.get("total_price", 0)) for o in seg_orders]
        bands = [(_price_band(p)) for p in prices]
        preferred_band = Counter(bands).most_common(1)[0][0]
        basket = statistics.fmean(o.get("line_count", 1) for o in seg_orders)
        # repeat inside this segment
        emails = [o.get("customer_email") or "(guest)" for o in seg_orders]
        email_counts = Counter(emails)
        likely_repeat = sum(
            1 for e, n in email_counts.items() if n >= 2
        ) / max(1, len(email_counts))
        segments.append(CustomerSegmentBelief(
            segment_key=key,
            order_count=len(seg_orders),
            mean_aov=aov,
            preferred_price_band=preferred_band,
            likely_repeat=likely_repeat,
            basket_size=basket,
        ))
    segments.sort(key=lambda s: -s.order_count)

    belief = CustomerBelief(
        total_orders=total_orders,
        total_customers=total_customers,
        segments=segments,
        global_aov=global_aov,
        global_repeat_rate=global_repeat,
        ts=time.time(),
    )
    _persist(belief.as_dict(), kind="customer")
    return belief


def competitor_belief() -> list[CompetitorBelief]:
    """Build per-URL competitor beliefs from competitor monitor events."""
    events = _pull_events_by_category("competitor")
    by_url: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        content = e.get("content") or {}
        url = content.get("url") or "(unknown)"
        by_url[url].append({
            "ts": e.get("ts") or 0.0,
            "price": float(content.get("new_price") or 0),
            "delta_pct": float(content.get("delta_pct") or 0),
            "title": content.get("title") or "",
        })

    beliefs: list[CompetitorBelief] = []
    for url, rows in by_url.items():
        rows.sort(key=lambda r: r["ts"])
        prices = [r["price"] for r in rows if r["price"] > 0]
        if not prices:
            continue
        deltas = [r["delta_pct"] for r in rows]
        cuts = _monotonic_run(deltas, negative=True)
        raises = _monotonic_run(deltas, negative=False)
        reactivity = _compute_reactivity(rows)
        title = rows[-1]["title"]
        stddev = statistics.stdev(prices) if len(prices) > 1 else 0.0
        belief = CompetitorBelief(
            url=url, title=title,
            samples=len(rows),
            last_price=prices[-1],
            mean_price=statistics.fmean(prices),
            price_stddev=stddev,
            monotonic_cuts=cuts,
            monotonic_raises=raises,
            reactivity=reactivity,
            last_checked=rows[-1]["ts"],
        )
        beliefs.append(belief)
        _persist(belief.as_dict(), kind=f"competitor:{url[-32:]}")
    beliefs.sort(key=lambda b: -b.samples)
    return beliefs


# ── Helpers ─────────────────────────────────────────────────

def _price_band(p: float) -> str:
    if p >= 80:
        return "premium"
    if p >= 25:
        return "mid"
    if p >= 5:
        return "impulse"
    return "giveaway"


def _monotonic_run(deltas: list[float], negative: bool) -> int:
    max_run = run = 0
    for d in deltas:
        if (negative and d < 0) or ((not negative) and d > 0):
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    return max_run


def _compute_reactivity(rows: list[dict[str, Any]]) -> float:
    """Estimate how often the competitor moved inside 24h of our move.

    We don't have ShopAI's own verdict timeline here (would need
    another table join); we use a proxy: if the competitor moves
    often (> every 3 days on average) we treat reactivity as high.
    """
    if len(rows) < 2:
        return 0.0
    deltas = [rows[i + 1]["ts"] - rows[i]["ts"] for i in range(len(rows) - 1)]
    mean_gap_days = statistics.fmean(deltas) / 86_400
    if mean_gap_days < 3:
        return 0.9
    if mean_gap_days < 7:
        return 0.6
    if mean_gap_days < 14:
        return 0.3
    return 0.1


def _pull_orders() -> list[dict[str, Any]]:
    if not _DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM memories WHERE category='order' "
            "ORDER BY timestamp DESC LIMIT 2000"
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for (content_json,) in rows:
        try:
            c = json.loads(content_json or "{}")
        except (json.JSONDecodeError, ValueError):
            continue
        out.append(c)
    return out


def _pull_events_by_category(category: str) -> list[dict[str, Any]]:
    if not _DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT content, timestamp FROM memories "
            "WHERE category=? ORDER BY timestamp ASC LIMIT 2000",
            (category,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for (content_json, ts) in rows:
        try:
            c = json.loads(content_json or "{}")
        except (json.JSONDecodeError, ValueError):
            continue
        out.append({"content": c, "ts": float(ts or 0)})
    return out


def _persist(content: dict[str, Any], kind: str) -> None:
    try:
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        mi.create(
            category="belief",
            content={"kind": kind, **content},
            action="snapshot",
            score=3.0,
            tags=["belief", "theory_of_mind", kind],
        )
    except Exception:
        pass
