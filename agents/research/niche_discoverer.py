"""Niche discoverer — trend-driven niche clustering.

Answers owner direction §5: "bid songolt eswel chiglel barih bish
harin trend data deer vndeslej brand niche bvteej chaddag bolgoh ni
zuw baih" — don't hand-pick a niche, let the brain discover which
niche is trending from the winner-source pool and adapt quarterly.

Input: a list of ``ProductCandidate`` instances (from
``WinnerSearcher``). Output: a ranked list of ``NicheReport``
objects, each carrying:

  * label               — "pet" / "kitchen" / "fitness" / ...
  * candidate_count     — how many products cluster here
  * avg_margin          — mean margin_pct across the cluster
  * avg_demand          — mean daily_sales
  * saturation_score    — mean (higher = more crowded)
  * trend_direction     — "rising" / "stable" / "falling" vs a
                          previous snapshot
  * rollup_score        — composite rank (margin × demand ÷ saturation)

Niche labels come from a keyword dictionary (extensible). Unknown
candidates go into "other". Trend direction is computed by
comparing current report to a saved snapshot from the last run
(persisted via SQLite when a db_path is given).

Pure stdlib, deterministic, LLM-free. Complements ``concept_former``
(unsupervised event clustering) by operating on *product candidates*
not decision events, and emitting owner-facing niche labels.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("agents.research.niche_discoverer")


# Niche dictionary — extendable via ``register_niche``. Tokens are
# matched case-insensitively against title + tags.
_DEFAULT_NICHES: dict[str, tuple[str, ...]] = {
    "pet": (
        "pet", "dog", "cat", "feeder", "leash",
        "collar", "toy",
    ),
    "kitchen": (
        "kitchen", "blender", "knife", "cutlery",
        "cook", "utensil", "pan", "bowl",
    ),
    "fitness": (
        "fitness", "gym", "yoga", "resistance",
        "band", "dumbbell", "mat", "sport",
    ),
    "beauty": (
        "beauty", "skincare", "makeup", "cream",
        "serum", "mask", "hair", "nail",
    ),
    "home": (
        "home", "decor", "lamp", "light", "pillow",
        "blanket", "rug", "curtain", "vase",
    ),
    "gadget": (
        "gadget", "charger", "cable", "hub",
        "wireless", "bluetooth", "phone",
        "headphone",
    ),
    "fashion": (
        "fashion", "dress", "shirt", "bag", "belt",
        "watch", "jewelry", "necklace",
    ),
    "baby": (
        "baby", "toddler", "stroller", "bib",
        "crib", "diaper",
    ),
    "auto": (
        "auto", "car", "vehicle", "dashboard",
        "tire", "motorcycle",
    ),
    "outdoor": (
        "outdoor", "camping", "hike", "tent",
        "backpack", "bike",
    ),
}


@dataclass
class NicheReport:
    label: str
    candidate_count: int
    avg_margin: float
    avg_demand: float
    saturation_score: float
    rollup_score: float
    trend_direction: str = "stable"    # "rising" / "falling" / "stable"
    example_titles: tuple[str, ...] = ()
    trend_signal_score: float = 0.0     # external signal (0-1)
    ranked_score: float = 0.0           # rollup * (1 + trend_signal)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "candidate_count": self.candidate_count,
            "avg_margin": round(self.avg_margin, 4),
            "avg_demand": round(self.avg_demand, 4),
            "saturation_score": round(
                self.saturation_score, 4,
            ),
            "rollup_score": round(self.rollup_score, 4),
            "trend_direction": self.trend_direction,
            "example_titles": list(self.example_titles),
            "trend_signal_score": round(
                self.trend_signal_score, 4,
            ),
            "ranked_score": round(self.ranked_score, 4),
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS niche_snapshots (
    label          TEXT NOT NULL,
    snapshot_ts    REAL NOT NULL,
    candidate_count INTEGER NOT NULL,
    avg_margin     REAL NOT NULL,
    avg_demand     REAL NOT NULL,
    saturation     REAL NOT NULL,
    rollup         REAL NOT NULL,
    PRIMARY KEY (label, snapshot_ts)
);
CREATE INDEX IF NOT EXISTS idx_niche_label
    ON niche_snapshots(label);
"""


def _label_for(
    title: str,
    tags: Iterable[str],
    niches: dict[str, tuple[str, ...]],
) -> str:
    """Return the niche label matching the most tokens in title +
    tags. Ties broken by first-registered niche."""
    source = (title or "").lower()
    for t in tags or ():
        source += " " + str(t).lower()
    best_label = "other"
    best_hits = 0
    for label, tokens in niches.items():
        hits = sum(1 for token in tokens if token in source)
        if hits > best_hits:
            best_hits = hits
            best_label = label
    return best_label


class NicheDiscoverer:
    """Clusters winner candidates by niche + tracks trend direction."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        niches: dict[str, tuple[str, ...]] | None = None,
        rising_threshold: float = 1.15,
        falling_threshold: float = 0.85,
        trend_scorer: Any = None,
    ) -> None:
        if rising_threshold <= 1.0:
            raise ValueError(
                "rising_threshold must be > 1",
            )
        if falling_threshold >= 1.0:
            raise ValueError(
                "falling_threshold must be < 1",
            )
        self._lock = threading.Lock()
        self._niches: dict[str, tuple[str, ...]] = dict(
            niches if niches is not None else _DEFAULT_NICHES,
        )
        self._rising = float(rising_threshold)
        self._falling = float(falling_threshold)
        self._trend_scorer = trend_scorer
        self._conn: sqlite3.Connection | None = None
        self._last_reports: list[NicheReport] = []
        if db_path is not None:
            path = Path(db_path)
            path.parent.mkdir(
                parents=True, exist_ok=True,
            )
            self._conn = sqlite3.connect(
                str(path), check_same_thread=False,
            )
            with self._lock:
                self._conn.execute(
                    "PRAGMA busy_timeout=5000",
                )
                self._conn.execute(
                    "PRAGMA journal_mode=WAL",
                )
                self._conn.executescript(_SCHEMA)
                self._conn.commit()

    # ── Niche dictionary ────────────────────────────────

    def register_niche(
        self, label: str, tokens: Iterable[str],
    ) -> None:
        if not label:
            raise ValueError("label required")
        tokens_tuple = tuple(
            t.strip().lower() for t in tokens if t
        )
        if not tokens_tuple:
            raise ValueError("at least one token required")
        with self._lock:
            self._niches[label] = tokens_tuple

    def unregister_niche(self, label: str) -> bool:
        with self._lock:
            return self._niches.pop(label, None) is not None

    def niches(self) -> dict[str, tuple[str, ...]]:
        with self._lock:
            return dict(self._niches)

    # ── Core: discover ───────────────────────────────────

    def discover(
        self,
        candidates: Iterable[Any],
        *,
        persist: bool = True,
        example_limit: int = 3,
    ) -> list[NicheReport]:
        # Group candidates by niche label
        grouped: dict[str, list[Any]] = defaultdict(list)
        with self._lock:
            niches = dict(self._niches)
        for c in candidates:
            title = str(
                getattr(c, "title", "") or "",
            )
            tags = tuple(
                getattr(c, "tags", ()) or (),
            )
            label = _label_for(title, tags, niches)
            grouped[label].append(c)
        # Build reports
        reports: list[NicheReport] = []
        for label, items in grouped.items():
            if not items:
                continue
            margins = [
                float(getattr(c, "margin_pct", 0.0))
                for c in items
            ]
            demands = [
                float(getattr(c, "daily_sales", 0.0))
                for c in items
            ]
            saturations = [
                float(getattr(c, "saturation_score", 0.0))
                for c in items
            ]
            avg_m = sum(margins) / len(margins)
            avg_d = sum(demands) / len(demands)
            avg_s = sum(saturations) / len(saturations)
            # rollup: margin × log(demand+1) × (1 - saturation)
            import math
            rollup = (
                avg_m
                * math.log1p(avg_d)
                * max(0.0, 1.0 - avg_s)
            )
            examples = tuple(
                str(getattr(c, "title", ""))[:60]
                for c in items[: max(1, int(example_limit))]
            )
            reports.append(NicheReport(
                label=label,
                candidate_count=len(items),
                avg_margin=avg_m,
                avg_demand=avg_d,
                saturation_score=avg_s,
                rollup_score=rollup,
                example_titles=examples,
            ))
        # Attach trend direction by comparing rollup to the most
        # recent snapshot (if any) per label.
        for r in reports:
            prior = self._last_rollup(r.label)
            if prior is None or prior <= 0:
                r.trend_direction = "stable"
            elif r.rollup_score / prior >= self._rising:
                r.trend_direction = "rising"
            elif r.rollup_score / prior <= self._falling:
                r.trend_direction = "falling"
            else:
                r.trend_direction = "stable"
        # Apply external trend signal (Google Trends etc.) if a
        # scorer was injected. Failures degrade to 0.0 so ranking
        # collapses back to pure rollup.
        scorer = self._trend_scorer
        for r in reports:
            signal = 0.0
            if scorer is not None:
                tokens = niches.get(r.label, ())
                try:
                    raw = scorer(r.label, tokens)
                    signal = max(0.0, min(1.0, float(raw)))
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "trend_scorer(%s) failed: %s",
                        r.label, exc,
                    )
                    signal = 0.0
            r.trend_signal_score = signal
            r.ranked_score = r.rollup_score * (1.0 + signal)
        reports.sort(
            key=lambda r: -r.ranked_score,
        )
        # Persist snapshot for next-run trend comparison
        if persist and self._conn is not None:
            self._save_snapshot(reports)
        with self._lock:
            self._last_reports = list(reports)
        return reports

    def _last_rollup(self, label: str) -> float | None:
        if self._conn is None:
            return None
        with self._lock:
            cur = self._conn.execute(
                "SELECT rollup FROM niche_snapshots "
                "WHERE label = ? "
                "ORDER BY snapshot_ts DESC LIMIT 1",
                (label,),
            )
            row = cur.fetchone()
        return float(row[0]) if row else None

    def _save_snapshot(
        self, reports: list[NicheReport],
    ) -> None:
        if self._conn is None:
            return
        ts = time.time()
        with self._lock:
            for r in reports:
                self._conn.execute(
                    "INSERT INTO niche_snapshots("
                    "  label, snapshot_ts, candidate_count,"
                    "  avg_margin, avg_demand, saturation,"
                    "  rollup"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        r.label, ts, r.candidate_count,
                        r.avg_margin, r.avg_demand,
                        r.saturation_score, r.rollup_score,
                    ),
                )
            self._conn.commit()

    # ── Queries ──────────────────────────────────────────

    def last_reports(self) -> list[NicheReport]:
        with self._lock:
            return list(self._last_reports)

    def rising_niches(self) -> list[NicheReport]:
        return [
            r for r in self.last_reports()
            if r.trend_direction == "rising"
        ]

    def history(
        self,
        label: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if self._conn is None:
            return []
        with self._lock:
            cur = self._conn.execute(
                "SELECT snapshot_ts, candidate_count, "
                "avg_margin, avg_demand, saturation, "
                "rollup FROM niche_snapshots "
                "WHERE label = ? "
                "ORDER BY snapshot_ts DESC LIMIT ?",
                (label, max(1, int(limit))),
            )
            rows = cur.fetchall()
        return [
            {
                "snapshot_ts": float(r[0]),
                "candidate_count": int(r[1]),
                "avg_margin": float(r[2]),
                "avg_demand": float(r[3]),
                "saturation_score": float(r[4]),
                "rollup_score": float(r[5]),
            }
            for r in rows
        ]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_snapshots = 0
            if self._conn is not None:
                cur = self._conn.execute(
                    "SELECT COUNT(*) FROM niche_snapshots",
                )
                total_snapshots = cur.fetchone()[0]
            return {
                "niche_labels": sorted(
                    self._niches.keys(),
                ),
                "last_report_count": len(
                    self._last_reports,
                ),
                "total_snapshots": total_snapshots,
                "rising_threshold": self._rising,
                "falling_threshold": self._falling,
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._last_reports)
            self._last_reports.clear()
            if self._conn is not None:
                self._conn.execute(
                    "DELETE FROM niche_snapshots",
                )
                self._conn.commit()
        return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


# ── Default factory ─────────────────────────────────────────

_DEFAULT_SINGLETON: NicheDiscoverer | None = None
_SINGLETON_LOCK = threading.Lock()


def build_default_niche_discoverer(
    *,
    db_path: str | None = "data/niches.db",
    trends_adapter: Any = None,
    eu_weight: float = 0.5,
    attach_trend_scorer: bool = True,
) -> NicheDiscoverer:
    """Return a NicheDiscoverer pre-wired with the Google Trends
    scorer so ``ranked_score`` mixes external trend signal into
    every discover() call.

    ``attach_trend_scorer=False`` disables the scorer (useful for
    offline tests). ``trends_adapter`` is injected for tests;
    production leaves it None so a default ``GoogleTrendsAdapter``
    is constructed.
    """
    scorer = None
    if attach_trend_scorer:
        try:
            from agents.research.trend_scorer import (
                make_google_trends_scorer,
            )
            if trends_adapter is None:
                from core.adapters.trends import (
                    GoogleTrendsAdapter,
                )
                trends_adapter = GoogleTrendsAdapter()
            scorer = make_google_trends_scorer(
                trends_adapter,
                geo="US",
                eu_weight=eu_weight,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "trend scorer wire-in failed, "
                "degrading to scorer=None: %s",
                exc,
            )
            scorer = None
    return NicheDiscoverer(
        db_path=db_path,
        trend_scorer=scorer,
    )


def get_default_niche_discoverer() -> NicheDiscoverer:
    """Module-level singleton — first call builds, subsequent
    calls return the cached instance."""
    global _DEFAULT_SINGLETON
    if _DEFAULT_SINGLETON is None:
        with _SINGLETON_LOCK:
            if _DEFAULT_SINGLETON is None:
                _DEFAULT_SINGLETON = (
                    build_default_niche_discoverer()
                )
    return _DEFAULT_SINGLETON


def reset_default_niche_discoverer_for_tests() -> None:
    """Clear the singleton (test-only helper)."""
    global _DEFAULT_SINGLETON
    with _SINGLETON_LOCK:
        if _DEFAULT_SINGLETON is not None:
            try:
                _DEFAULT_SINGLETON.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "reset niche discoverer close "
                    "skipped: %s",
                    exc,
                )
        _DEFAULT_SINGLETON = None
