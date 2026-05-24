"""Shared cluster event bus -- horizontal collaboration.

User's framing: cluster-uud uuriin specialty-tei, gehdee
neg goaltay. They should SHARE INFORMATION horizontally
across the bus while still respecting vertical authority.

This module provides:
  - ClusterEvent dataclass: a single emitted signal
  - emit_event(): record an event from a captain plan
  - subscribe_events(): pull events for a specific cluster
                        / topic / time window
  - cross_cluster_signals(): convert recent events into
                              signals_by_cluster dict for
                              the NEXT cycle

The bus is a JSON-on-disk persistence (data/cluster_events.json
or in the Pattern Z DB). Cheap, append-only, indexed by
emitter cluster + topic + timestamp.

## Example flow

  Cycle 1 (T=0):
    meta_ads captain fires
    -> ad_analyzer detects product X has 5x ROAS
    -> emit_event(emitter="meta_ads", topic="high_roas_product",
                  payload={"product_id": "X", "roas": 5.0})

  Cycle 2 (T=1h):
    shopify captain plans
    -> Tier 1 calls cross_cluster_signals() to build signals
       dict from recent bus events
    -> signals["merchandising"]["high_roas_product_count"] = 1
    -> merchandising captain fires product_ranking, sees
       product X with 5x ROAS signal, ranks it higher

## Substrate-first

Bus is OBSERVATIONAL + ADVISORY. No captain MUST consume
events; cluster rules opt-in to event-derived signals.
Same pluggable principle as the rest.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ClusterEvent:
    emitter_cluster: str
    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    emitted_at: float = field(default_factory=time.time)
    store_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "emitter_cluster": self.emitter_cluster,
            "topic": self.topic,
            "payload": self.payload,
            "emitted_at": self.emitted_at,
            "store_id": self.store_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClusterEvent":
        return cls(
            emitter_cluster=str(d.get("emitter_cluster", "")),
            topic=str(d.get("topic", "")),
            payload=d.get("payload") or {},
            emitted_at=float(d.get("emitted_at", 0.0) or 0.0),
            store_id=d.get("store_id"),
        )


def _bus_path() -> Path:
    """Default path for the JSON-backed event bus."""
    data_dir = Path(
        os.environ.get("SHOPAI_DATA_DIR", "data")
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "cluster_events.json"


def _load_events() -> list[ClusterEvent]:
    path = _bus_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        return [ClusterEvent.from_dict(d) for d in raw if isinstance(d, dict)]
    except (json.JSONDecodeError, OSError):
        return []


def _save_events(events: list[ClusterEvent]) -> bool:
    path = _bus_path()
    try:
        path.write_text(
            json.dumps(
                [e.to_dict() for e in events],
                indent=2, default=str,
            ),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def emit_event(
    emitter_cluster: str,
    topic: str,
    *,
    payload: dict[str, Any] | None = None,
    store_id: str | None = None,
) -> ClusterEvent:
    """Emit one event to the bus. Append-only persistence."""
    event = ClusterEvent(
        emitter_cluster=emitter_cluster,
        topic=topic,
        payload=payload or {},
        store_id=store_id,
    )
    events = _load_events()
    events.append(event)
    # Keep only the most recent 5000 events to bound disk
    if len(events) > 5000:
        events = events[-5000:]
    _save_events(events)
    return event


def subscribe_events(
    *,
    topic: str | None = None,
    emitter_cluster: str | None = None,
    store_id: str | None = None,
    window_hours: float = 24.0,
) -> list[ClusterEvent]:
    """Pull events matching optional filters within the window."""
    cutoff = time.time() - (window_hours * 3600.0)
    events = _load_events()
    out: list[ClusterEvent] = []
    for e in events:
        if e.emitted_at < cutoff:
            continue
        if topic is not None and e.topic != topic:
            continue
        if (
            emitter_cluster is not None
            and e.emitter_cluster != emitter_cluster
        ):
            continue
        if store_id is not None and e.store_id != store_id:
            continue
        out.append(e)
    return out


def cross_cluster_signals(
    *,
    store_id: str | None = None,
    window_hours: float = 24.0,
) -> dict[str, dict[str, Any]]:
    """Convert recent bus events into a signals_by_cluster
    dict the next cycle's captains can read.

    Topic conventions (consumer cluster -> signal name):

      high_roas_product   -> merchandising:high_roas_product_count
      churn_risk_detected -> retention:at_risk_count
      thin_margin_flagged -> pricing:thin_margin_count
      stockout_warning    -> fulfillment:stockout_imminent_count
      negative_review     -> quality:negative_review_count
      undercut_detected   -> pricing:undercut_count

    Each consumer cluster sees a COUNT of relevant signals
    fired by ANY emitter in the window.
    """
    _TOPIC_TO_SIGNAL = {
        "high_roas_product":
            ("merchandising", "high_roas_product_count"),
        "churn_risk_detected":
            ("retention", "at_risk_count"),
        "thin_margin_flagged":
            ("pricing", "thin_margin_count"),
        "stockout_warning":
            ("fulfillment", "stockout_imminent_count"),
        "negative_review":
            ("quality", "negative_review_count"),
        "undercut_detected":
            ("pricing", "undercut_count"),
        "wishlist_high_demand":
            ("merchandising", "wishlist_high_demand_count"),
    }

    events = subscribe_events(
        store_id=store_id, window_hours=window_hours,
    )
    out: dict[str, dict[str, Any]] = {}
    for e in events:
        target = _TOPIC_TO_SIGNAL.get(e.topic)
        if target is None:
            continue
        cluster, signal_name = target
        out.setdefault(cluster, {})
        out[cluster][signal_name] = (
            out[cluster].get(signal_name, 0) + 1
        )
    return out


def clear_bus() -> bool:
    """Wipe the bus -- useful for tests / operator reset."""
    return _save_events([])


def bus_stats(
    *, window_hours: float = 24.0,
) -> dict[str, Any]:
    """Aggregate view of the bus over a window."""
    cutoff = time.time() - (window_hours * 3600.0)
    events = [
        e for e in _load_events()
        if e.emitted_at >= cutoff
    ]
    by_topic: dict[str, int] = {}
    by_emitter: dict[str, int] = {}
    by_store: dict[str, int] = {}
    for e in events:
        by_topic[e.topic] = by_topic.get(e.topic, 0) + 1
        by_emitter[e.emitter_cluster] = (
            by_emitter.get(e.emitter_cluster, 0) + 1
        )
        sid = e.store_id or "(none)"
        by_store[sid] = by_store.get(sid, 0) + 1

    now = time.time()
    if events:
        oldest_age = now - min(e.emitted_at for e in events)
        newest_age = now - max(e.emitted_at for e in events)
    else:
        oldest_age = None
        newest_age = None

    return {
        "total_events": len(events),
        "window_hours": window_hours,
        "by_topic": dict(sorted(
            by_topic.items(), key=lambda kv: -kv[1],
        )),
        "by_emitter": dict(sorted(
            by_emitter.items(), key=lambda kv: -kv[1],
        )),
        "by_store": dict(sorted(
            by_store.items(), key=lambda kv: -kv[1],
        )),
        "oldest_age_seconds": oldest_age,
        "newest_age_seconds": newest_age,
    }
