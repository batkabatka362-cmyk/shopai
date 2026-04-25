"""World model — a causal transition model of the store.

ShopAI's memory stores *what happened*. Belief-state tracks
*current* parameter estimates. Neither tells the brain:

    "If we set ad_budget=$40 on a premium-tone audio product,
     what does the ROAS distribution look like 3 days later?"

Answering that needs a *transition model*: P(outcome | action,
context). That's the world model. Once learned, every other
subsystem can plan ahead, imagine counterfactuals, and debate
what would happen — without spending real ad dollars.

Design (deterministic, no LLM):

  • Context is discretised into a feature vector (niche, price_band,
    margin_band, copy_tone).
  • Action is one of a small fixed vocabulary: launch | scale |
    kill | hold | add_cross_sell | wait.
  • Outcome is a named KPI (roas | cvr | revenue | aov) with a
    numeric value.
  • Each (context, action, kpi) cell keeps a streaming
    Gaussian summary (Welford) of the realised value and a
    count. Predictions return mean + 1-sigma band + sample size.
  • ``update(...)`` is called from the learning loop whenever an
    outcome arrives; ``predict(...)`` is consulted by planner,
    debate, and the offline sandbox.

Persistence: ``data/world_model.db`` (SQLite) so the model
survives restarts. Thread-safe single-writer pattern.

Failure isolation: unknown contexts fall back to the global
marginal (collapse the feature vector gradually until matches
found).
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


logger = get_logger("brain.world_model")

_DB_PATH = Path("data/world_model.db")

# Fixed action + KPI vocabularies so the table stays tight.
ACTIONS = (
    "launch", "scale", "kill", "hold",
    "add_cross_sell", "wait",
)
KPIS = ("roas", "cvr", "revenue", "aov", "spend")

_FEATURES = ("niche", "price_band", "margin_band", "copy_tone")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cells (
    niche       TEXT NOT NULL,
    price_band  TEXT NOT NULL,
    margin_band TEXT NOT NULL,
    copy_tone   TEXT NOT NULL,
    action      TEXT NOT NULL,
    kpi         TEXT NOT NULL,
    n           INTEGER NOT NULL DEFAULT 0,
    mean        REAL NOT NULL DEFAULT 0.0,
    m2          REAL NOT NULL DEFAULT 0.0,
    last_update REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (niche, price_band, margin_band, copy_tone,
                 action, kpi)
);
CREATE INDEX IF NOT EXISTS idx_action_kpi ON cells(action, kpi);
"""


@dataclass
class Prediction:
    mean: float
    stdev: float
    samples: int
    specificity: int              # 4=exact, 3/2/1=partial, 0=no data
    band: str                     # "tight" | "loose" | "uninformed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "mean": round(self.mean, 3),
            "stdev": round(self.stdev, 3),
            "samples": self.samples,
            "specificity": self.specificity,
            "band": self.band,
        }


@dataclass
class Context:
    niche: str = "unknown"
    price_band: str = "mid"
    margin_band: str = "mid"
    copy_tone: str = "friendly"

    def as_tuple(self) -> tuple[str, str, str, str]:
        return (self.niche, self.price_band,
                self.margin_band, self.copy_tone)

    def coarsened(self, keep: int) -> "Context":
        """Return a less-specific context by blanking fields.

        ``keep=4`` → full. ``keep=0`` → fully marginal."""
        vals = list(self.as_tuple())
        for i in range(keep, 4):
            vals[i] = "*"
        return Context(*vals)


# ── Public API ──────────────────────────────────────────────

class WorldModel:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db = Path(db_path) if db_path else _DB_PATH
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Updating ────────────────────────────────────────────

    def update(
        self,
        context: Context | dict[str, Any],
        action: str,
        kpi: str,
        value: float,
    ) -> None:
        """Fold one realised outcome into the transition model.

        Silently skips unknown actions / KPIs — the caller doesn't
        need to pre-validate."""
        if action not in ACTIONS or kpi not in KPIS:
            return
        ctx = context if isinstance(context, Context) else Context(**context)
        # Also fold the outcome into each coarsening (for fallback).
        with self._lock, self._connect() as conn:
            for keep in (4, 3, 2, 1, 0):
                c = ctx.coarsened(keep)
                self._fold(conn, c, action, kpi, float(value))
            conn.commit()

    @staticmethod
    def _fold(
        conn: sqlite3.Connection,
        ctx: Context,
        action: str,
        kpi: str,
        value: float,
    ) -> None:
        row = conn.execute(
            "SELECT n, mean, m2 FROM cells WHERE niche=? AND "
            "price_band=? AND margin_band=? AND copy_tone=? "
            "AND action=? AND kpi=?",
            (*ctx.as_tuple(), action, kpi),
        ).fetchone()
        if row is None:
            n, mean, m2 = 0, 0.0, 0.0
        else:
            n, mean, m2 = row
        # Welford update
        n += 1
        delta = value - mean
        mean += delta / n
        delta2 = value - mean
        m2 += delta * delta2
        conn.execute(
            "INSERT OR REPLACE INTO cells "
            "(niche, price_band, margin_band, copy_tone, action, kpi, "
            " n, mean, m2, last_update) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (*ctx.as_tuple(), action, kpi, n, mean, m2, time.time()),
        )

    # ── Prediction ──────────────────────────────────────────

    def predict(
        self,
        context: Context | dict[str, Any],
        action: str,
        kpi: str,
    ) -> Prediction:
        """Fetch P(kpi | context, action). Falls back to coarser
        context when exact data is absent."""
        if action not in ACTIONS or kpi not in KPIS:
            return _uninformed()
        ctx = context if isinstance(context, Context) else Context(**context)
        with self._connect() as conn:
            for keep in (4, 3, 2, 1, 0):
                c = ctx.coarsened(keep)
                row = conn.execute(
                    "SELECT n, mean, m2 FROM cells WHERE niche=? AND "
                    "price_band=? AND margin_band=? AND copy_tone=? "
                    "AND action=? AND kpi=?",
                    (*c.as_tuple(), action, kpi),
                ).fetchone()
                if row and row[0] >= 2:
                    n, mean, m2 = row
                    var = m2 / max(1, n - 1)
                    return Prediction(
                        mean=mean,
                        stdev=math.sqrt(max(0.0, var)),
                        samples=int(n),
                        specificity=keep,
                        band=_band_for(n, var),
                    )
        return _uninformed()

    def rank_actions(
        self,
        context: Context | dict[str, Any],
        kpi: str = "roas",
    ) -> list[tuple[str, Prediction]]:
        """Return every action sorted by mean predicted KPI
        (descending). Useful as a quick best-action oracle."""
        ctx = context if isinstance(context, Context) else Context(**context)
        out: list[tuple[str, Prediction]] = []
        for action in ACTIONS:
            pred = self.predict(ctx, action, kpi)
            out.append((action, pred))
        out.sort(key=lambda kv: -kv[1].mean if kv[1].samples else 0)
        return out

    # ── Introspection ──────────────────────────────────────

    def size(self) -> int:
        """Number of non-marginal cells with data."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM cells "
                "WHERE niche!='*' AND n>0"
            ).fetchone()
        return int(row[0]) if row else 0

    def summary(self) -> dict[str, Any]:
        """Aggregate stats: how many cells, how many exact, avg sample
        size. The opportunity-scout surfaces this as 'world-model
        coverage = X%' in the weekly digest."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*), SUM(n), AVG(n) FROM cells WHERE n>0"
            ).fetchone()
            exact = conn.execute(
                "SELECT COUNT(*) FROM cells "
                "WHERE niche!='*' AND price_band!='*' AND "
                "margin_band!='*' AND copy_tone!='*' AND n>0"
            ).fetchone()
        cells = int(row[0] or 0)
        total = int(row[1] or 0)
        avg = float(row[2] or 0.0)
        exact_cells = int(exact[0] or 0)
        return {
            "cells_with_data": cells,
            "exact_cells": exact_cells,
            "total_observations": total,
            "avg_samples_per_cell": round(avg, 2),
        }

    # ── Bulk ingest (replay memory) ─────────────────────────

    def ingest_records(
        self,
        records: Iterable[dict[str, Any]],
    ) -> int:
        """Fold a batch of outcome records. Each record must carry
        ``context`` (dict), ``action``, ``kpi``, ``value``. Returns
        the number of records successfully folded."""
        count = 0
        for r in records:
            try:
                self.update(
                    context=r.get("context", {}),
                    action=r.get("action", ""),
                    kpi=r.get("kpi", ""),
                    value=float(r.get("value", 0.0)),
                )
                count += 1
            except Exception as exc:
                logger.debug("world_model ingest row failed: %s", exc)
        return count


def _uninformed() -> Prediction:
    return Prediction(
        mean=0.0, stdev=0.0, samples=0,
        specificity=0, band="uninformed",
    )


def _band_for(n: int, var: float) -> str:
    if n < 5:
        return "loose"
    # Coefficient-of-variation-ish bucketing. Tight means we trust the
    # mean; loose means sigma dominates.
    if var < 0.25:
        return "tight"
    return "loose"


# ── Singleton ────────────────────────────────────────────────

_WM_LOCK = threading.Lock()
_WM: WorldModel | None = None


def world_model() -> WorldModel:
    global _WM
    if _WM is None:
        with _WM_LOCK:
            if _WM is None:
                _WM = WorldModel()
    return _WM
