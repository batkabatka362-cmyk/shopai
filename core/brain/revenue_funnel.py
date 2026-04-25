"""Revenue funnel — end-to-end drop-off analysis.

Every ecommerce business has the same funnel:

   impression → click → view_product → add_to_cart → checkout → purchase → (return)

Each stage has a conversion rate and a drop-off. Individual metrics
(CTR, CVR, cart-abandonment) live across dashboards but the *shape*
of the funnel — where the biggest leak is — is rarely explicit.

``RevenueFunnel`` ingests events keyed by stage, computes:

  • stage counts + conversion-to-next
  • the single biggest drop (stage with the worst survival rate)
  • contribution score per stage (closing the leak would add N%)
  • a diagnosis hint per leak ("low CTR → creative fatigue",
    "checkout drop → price or shipping friction")

Callers record events per stage; analyse() produces a snapshot.

Pure stdlib, deterministic. Persisted counts live in memory; if a
db_path is supplied, events are appended to SQLite so analysis can
span daemon restarts.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.revenue_funnel")


STAGES: tuple[str, ...] = (
    "impression", "click", "view_product",
    "add_to_cart", "checkout", "purchase", "return",
)

_DIAGNOSES: dict[tuple[str, str], str] = {
    ("impression", "click"): (
        "low CTR — creative fatigue or wrong audience"
    ),
    ("click", "view_product"): (
        "fast bounce — landing page mismatch"
    ),
    ("view_product", "add_to_cart"): (
        "price or product-page friction; check reviews & images"
    ),
    ("add_to_cart", "checkout"): (
        "cart abandon — shipping/tax surprise or unclear urgency"
    ),
    ("checkout", "purchase"): (
        "checkout abandon — payment friction or trust signals"
    ),
}


@dataclass
class StageMetric:
    stage: str
    count: int
    conversion_to_next: float   # 0..1, 1.0 if terminal
    drop_count: int              # count − next_count
    contribution_score: float    # drop_count / impression count

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "count": self.count,
            "conversion_to_next": round(
                self.conversion_to_next, 4,
            ),
            "drop_count": self.drop_count,
            "contribution_score": round(
                self.contribution_score, 4,
            ),
        }


@dataclass
class FunnelSnapshot:
    stages: list[StageMetric]
    biggest_leak: tuple[str, str] | None
    biggest_leak_diagnosis: str
    overall_conversion: float
    return_rate: float
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "stages": [s.as_dict() for s in self.stages],
            "biggest_leak": (
                list(self.biggest_leak)
                if self.biggest_leak else None
            ),
            "biggest_leak_diagnosis": self.biggest_leak_diagnosis,
            "overall_conversion": round(self.overall_conversion, 4),
            "return_rate": round(self.return_rate, 4),
            "ts": self.ts,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS funnel_events (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    stage TEXT NOT NULL,
    n     INTEGER NOT NULL,
    ts    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_funnel_stage ON funnel_events(stage);
CREATE INDEX IF NOT EXISTS idx_funnel_ts ON funnel_events(ts);
"""


class RevenueFunnel:
    def __init__(
        self, db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {s: 0 for s in STAGES}
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

    def _load(self) -> None:
        if self._conn is None:
            return
        with self._lock:
            for row in self._conn.execute(
                "SELECT stage, SUM(n) FROM funnel_events "
                "GROUP BY stage",
            ):
                if row[0] in self._counts:
                    self._counts[row[0]] = int(row[1] or 0)

    # ── Intake ───────────────────────────────────────────

    def record(
        self,
        stage: str,
        count: int = 1,
        *,
        ts: float | None = None,
    ) -> None:
        if stage not in self._counts:
            raise ValueError(
                f"unknown stage {stage!r}; must be one of {STAGES}",
            )
        if count <= 0:
            raise ValueError("count must be > 0")
        timestamp = float(ts if ts is not None else time.time())
        with self._lock:
            self._counts[stage] += int(count)
            if self._conn is not None:
                self._conn.execute(
                    "INSERT INTO funnel_events(stage, n, ts) "
                    "VALUES (?, ?, ?)",
                    (stage, int(count), timestamp),
                )
                self._conn.commit()

    def record_batch(
        self, counts: dict[str, int],
        *, ts: float | None = None,
    ) -> int:
        total = 0
        for stage, n in counts.items():
            if n <= 0:
                continue
            self.record(stage, n, ts=ts)
            total += n
        return total

    # ── Analyse ──────────────────────────────────────────

    def analyse(self) -> FunnelSnapshot:
        with self._lock:
            counts = dict(self._counts)
        main_stages = STAGES[:-1]   # exclude "return"
        impressions = counts.get("impression", 0)
        purchases = counts.get("purchase", 0)
        returns = counts.get("return", 0)
        stages_out: list[StageMetric] = []
        biggest_leak: tuple[str, str] | None = None
        biggest_leak_drop = -1
        for i, s in enumerate(main_stages):
            this_count = counts.get(s, 0)
            next_count = (
                counts.get(main_stages[i + 1], 0)
                if i + 1 < len(main_stages) else this_count
            )
            if i + 1 < len(main_stages) and this_count > 0:
                cvr = min(1.0, next_count / this_count)
            elif i + 1 >= len(main_stages):
                cvr = 1.0
            else:
                cvr = 0.0
            drop = max(0, this_count - next_count)
            contribution = (
                drop / impressions if impressions > 0 else 0.0
            )
            stages_out.append(StageMetric(
                stage=s,
                count=this_count,
                conversion_to_next=cvr,
                drop_count=drop,
                contribution_score=contribution,
            ))
            if (
                i + 1 < len(main_stages)
                and drop > biggest_leak_drop
            ):
                biggest_leak_drop = drop
                biggest_leak = (s, main_stages[i + 1])
        diagnosis = (
            _DIAGNOSES.get(biggest_leak, "leak identified")
            if biggest_leak else "no funnel data yet"
        )
        overall_conversion = (
            purchases / impressions if impressions > 0 else 0.0
        )
        return_rate = (
            returns / purchases if purchases > 0 else 0.0
        )
        return FunnelSnapshot(
            stages=stages_out,
            biggest_leak=biggest_leak,
            biggest_leak_diagnosis=diagnosis,
            overall_conversion=overall_conversion,
            return_rate=return_rate,
            ts=time.time(),
        )

    # ── Queries / maintenance ────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_events = sum(self._counts.values())
            return {
                "total_events": total_events,
                "counts": dict(self._counts),
            }

    def reset(self) -> int:
        with self._lock:
            n = sum(self._counts.values())
            for s in self._counts:
                self._counts[s] = 0
            if self._conn is not None:
                self._conn.execute("DELETE FROM funnel_events")
                self._conn.commit()
        return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
