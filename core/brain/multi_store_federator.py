"""Multi-store federator — pool wins across stores by similarity weight.

CLAUDE.md Z3: *"1 store-д сурсан rule бусдад автомат түгээнэ"*. The
federator implements that — it accepts per-store rule observations,
groups them by canonical rule_id, and emits a *federated* score that
weights each store by:

  • similarity to the target store (niche, currency, AOV band)
  • the local sample size for that rule
  • the local win-rate confidence

Pure stdlib. SQLite-persisted (optional). Federation is deterministic:
the output for a given target_store + rule depends only on what's
been registered.

API:

    fed = MultiStoreFederator()
    fed.register_store("audio_us", traits={"niche": "audio",
                                            "currency": "USD"})
    fed.register_store("audio_eu", traits={"niche": "audio",
                                            "currency": "EUR"})
    fed.observe("audio_us", rule_id="kill_at_roas_1.5",
                wins=8, uses=10)
    fed.observe("audio_eu", rule_id="kill_at_roas_1.5",
                wins=5, uses=8)
    score = fed.federated_score(
        target_store="audio_us", rule_id="kill_at_roas_1.5",
    )
    # → 0..1 weighted average across all stores, biased toward
    #   local + similar-traited siblings
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("brain.multi_store_federator")


@dataclass
class StoreSpec:
    store_id: str
    traits: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0           # owner-set baseline preference

    def as_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "traits": dict(self.traits),
            "weight": round(self.weight, 4),
        }


@dataclass
class RuleObservation:
    store_id: str
    rule_id: str
    wins: int
    uses: int
    last_ts: float = 0.0

    @property
    def win_rate(self) -> float:
        # Laplace smoothing: 1/2 prior of 0.5
        return (self.wins + 1.0) / (self.uses + 2.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "rule_id": self.rule_id,
            "wins": self.wins,
            "uses": self.uses,
            "win_rate": round(self.win_rate, 4),
            "last_ts": self.last_ts,
        }


@dataclass
class FederationReport:
    target_store: str
    rule_id: str
    federated_score: float
    contributors: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_store": self.target_store,
            "rule_id": self.rule_id,
            "federated_score": round(self.federated_score, 4),
            "contributors": list(self.contributors),
        }


# ── Similarity ───────────────────────────────────────────

def _trait_similarity(
    a: dict[str, Any], b: dict[str, Any],
) -> float:
    """Jaccard on shared key=value pairs. Empty intersections → 0."""
    if not a or not b:
        return 0.0
    a_pairs = {(k, str(v)) for k, v in a.items()}
    b_pairs = {(k, str(v)) for k, v in b.items()}
    if not a_pairs or not b_pairs:
        return 0.0
    intersect = a_pairs & b_pairs
    union = a_pairs | b_pairs
    return len(intersect) / len(union) if union else 0.0


_SCHEMA = """
CREATE TABLE IF NOT EXISTS stores (
    store_id  TEXT PRIMARY KEY,
    traits    TEXT NOT NULL DEFAULT '{}',
    weight    REAL NOT NULL DEFAULT 1.0
);
CREATE TABLE IF NOT EXISTS rule_observations (
    store_id  TEXT NOT NULL,
    rule_id   TEXT NOT NULL,
    wins      INTEGER NOT NULL DEFAULT 0,
    uses      INTEGER NOT NULL DEFAULT 0,
    last_ts   REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (store_id, rule_id)
);
"""


class MultiStoreFederator:
    def __init__(
        self,
        db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._stores: dict[str, StoreSpec] = {}
        self._observations: dict[
            tuple[str, str], RuleObservation
        ] = {}
        self._conn: sqlite3.Connection | None = None
        if db_path is not None:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(path), check_same_thread=False,
            )
            with self._lock:
                self._conn.execute("PRAGMA busy_timeout=5000")
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.executescript(_SCHEMA)
                self._conn.commit()
            self._load()

    # ── Registration ─────────────────────────────────────

    def register_store(
        self,
        store_id: str,
        *,
        traits: dict[str, Any] | None = None,
        weight: float = 1.0,
    ) -> StoreSpec:
        if not store_id:
            raise ValueError("store_id required")
        if weight <= 0:
            raise ValueError("weight must be positive")
        spec = StoreSpec(
            store_id=store_id,
            traits=dict(traits or {}),
            weight=float(weight),
        )
        with self._lock:
            self._stores[store_id] = spec
            if self._conn is not None:
                import json
                self._conn.execute(
                    "INSERT OR REPLACE INTO stores"
                    "(store_id, traits, weight) VALUES (?, ?, ?)",
                    (store_id, json.dumps(spec.traits), spec.weight),
                )
                self._conn.commit()
        return spec

    def stores(self) -> list[StoreSpec]:
        return list(self._stores.values())

    # ── Observe ──────────────────────────────────────────

    def observe(
        self,
        store_id: str,
        rule_id: str,
        *,
        wins: int = 0,
        uses: int = 0,
    ) -> RuleObservation:
        if not store_id or not rule_id:
            raise ValueError("store_id and rule_id required")
        if uses < 0 or wins < 0 or wins > uses + 0:
            # uses ≥ wins ≥ 0
            raise ValueError("uses ≥ wins ≥ 0")
        key = (store_id, rule_id)
        with self._lock:
            existing = self._observations.get(key)
            if existing is None:
                existing = RuleObservation(
                    store_id=store_id, rule_id=rule_id,
                    wins=int(wins), uses=int(uses),
                    last_ts=time.time(),
                )
                self._observations[key] = existing
            else:
                existing.wins += int(wins)
                existing.uses += int(uses)
                existing.last_ts = time.time()
            if self._conn is not None:
                self._conn.execute(
                    "INSERT INTO rule_observations"
                    "(store_id, rule_id, wins, uses, last_ts) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(store_id, rule_id) DO UPDATE SET "
                    "wins=excluded.wins, uses=excluded.uses, "
                    "last_ts=excluded.last_ts",
                    (
                        store_id, rule_id,
                        existing.wins, existing.uses,
                        existing.last_ts,
                    ),
                )
                self._conn.commit()
        return existing

    def _load(self) -> None:
        if self._conn is None:
            return
        import json
        with self._lock:
            for row in self._conn.execute(
                "SELECT store_id, traits, weight FROM stores",
            ):
                try:
                    traits = json.loads(row[1] or "{}")
                except (json.JSONDecodeError, ValueError):
                    traits = {}
                self._stores[row[0]] = StoreSpec(
                    store_id=row[0], traits=traits,
                    weight=float(row[2]),
                )
            for row in self._conn.execute(
                "SELECT store_id, rule_id, wins, uses, last_ts "
                "FROM rule_observations",
            ):
                key = (row[0], row[1])
                self._observations[key] = RuleObservation(
                    store_id=row[0], rule_id=row[1],
                    wins=int(row[2]), uses=int(row[3]),
                    last_ts=float(row[4]),
                )

    # ── Federate ─────────────────────────────────────────

    def federated_score(
        self,
        target_store: str,
        rule_id: str,
        *,
        local_boost: float = 2.0,
        similarity_floor: float = 0.0,
    ) -> FederationReport:
        target = self._stores.get(target_store)
        if target is None:
            raise ValueError(f"unknown store {target_store!r}")
        contributors: list[dict[str, Any]] = []
        weighted_sum = 0.0
        weight_sum = 0.0
        for (sid, rid), obs in self._observations.items():
            if rid != rule_id or obs.uses == 0:
                continue
            other = self._stores.get(sid)
            if other is None:
                continue
            if sid == target_store:
                sim = 1.0
            else:
                sim = _trait_similarity(target.traits, other.traits)
                if sim < similarity_floor:
                    continue
            confidence = 1.0 - (1.0 / math.sqrt(obs.uses + 1))
            store_w = other.weight
            local = local_boost if sid == target_store else 1.0
            weight = sim * confidence * store_w * local
            if weight <= 0:
                continue
            contribution = obs.win_rate * weight
            weighted_sum += contribution
            weight_sum += weight
            contributors.append({
                "store_id": sid,
                "win_rate": round(obs.win_rate, 4),
                "uses": obs.uses,
                "similarity": round(sim, 4),
                "weight": round(weight, 4),
            })
        score = weighted_sum / weight_sum if weight_sum > 0 else 0.0
        contributors.sort(key=lambda c: -c["weight"])
        return FederationReport(
            target_store=target_store,
            rule_id=rule_id,
            federated_score=score,
            contributors=contributors,
        )

    def best_rules_for(
        self,
        target_store: str,
        *,
        min_uses: int = 5,
        top_n: int = 10,
    ) -> list[FederationReport]:
        if target_store not in self._stores:
            raise ValueError(f"unknown store {target_store!r}")
        rule_ids: set[str] = set()
        with self._lock:
            for (_, rid), obs in self._observations.items():
                if obs.uses >= min_uses:
                    rule_ids.add(rid)
        reports = [
            self.federated_score(target_store, rid)
            for rid in sorted(rule_ids)
        ]
        reports.sort(key=lambda r: -r.federated_score)
        return reports[:top_n]

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "stores": len(self._stores),
            "observations": len(self._observations),
            "rules": len({rid for _, rid in self._observations}),
        }

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
