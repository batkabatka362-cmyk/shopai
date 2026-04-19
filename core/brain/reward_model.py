"""Reward model — learn the owner's implicit reward function.

ShopAI optimises ROAS / CVR / revenue by default. But the owner
cares about more than explicit KPIs: a £100 order is worth more
if it's a repeat customer from a core niche; a CVR bump from
clickbait copy may still be a loss because the owner hates that
tone. Nothing in the brain captured this implicit preference
signal beyond raw feedback up/down votes.

RewardModel infers a latent preference vector from the owner's
historical feedback:

  features  = (niche, price_band, copy_tone, urgency_tone,
               discount_depth_band, time_of_day)
  signal    = up_vote (+1) / down_vote (-1) / outcome_bonus (+0.5)

For each feature value, we maintain a running log-likelihood
ratio (LLR) of "owner approves given this feature" vs baseline.
The overall reward for a candidate action is the sum of its
feature LLRs plus an explicit KPI-linear term (ROAS * α).

Key properties:

  • Transparent: every prediction comes with a breakdown of
    which features contributed what score.
  • Updatable online: a single new up/down vote updates the LLR
    table in O(features) time.
  • Falls back to KPI when the preference table is cold.

Persistence: ``data/reward_model.db`` (SQLite).

Pure statistics + counts. No LLM; scores are auditable by the
oracle / debate / dashboard.
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


logger = get_logger("brain.reward_model")

_DB_PATH = Path("data/reward_model.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feature_counts (
    feature     TEXT NOT NULL,
    value       TEXT NOT NULL,
    pos         INTEGER NOT NULL DEFAULT 0,
    neg         INTEGER NOT NULL DEFAULT 0,
    last_update REAL NOT NULL,
    PRIMARY KEY (feature, value)
);
CREATE TABLE IF NOT EXISTS global_counts (
    feature     TEXT PRIMARY KEY,
    pos_total   INTEGER NOT NULL DEFAULT 0,
    neg_total   INTEGER NOT NULL DEFAULT 0
);
"""


_FEATURES = (
    "niche", "price_band", "copy_tone", "urgency_tone",
    "discount_depth_band", "time_of_day",
)

_SMOOTHING = 1.0         # Laplace smoothing on counts


@dataclass
class Contribution:
    feature: str
    value: str
    llr: float                      # log-likelihood ratio

    def as_dict(self) -> dict[str, Any]:
        return {"feature": self.feature, "value": self.value,
                "llr": round(self.llr, 3)}


@dataclass
class RewardEstimate:
    total: float
    kpi_term: float
    preference_term: float
    contributions: list[Contribution] = field(default_factory=list)
    explainability: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": round(self.total, 3),
            "kpi_term": round(self.kpi_term, 3),
            "preference_term": round(self.preference_term, 3),
            "contributions": [c.as_dict() for c in self.contributions],
            "explainability": self.explainability,
        }


# ── Model ───────────────────────────────────────────────────

class RewardModel:
    def __init__(
        self,
        db_path: Path | str | None = None,
        kpi_weight: float = 0.5,
    ) -> None:
        self._db = Path(db_path) if db_path else _DB_PATH
        self._alpha = float(kpi_weight)
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Update ──────────────────────────────────────────────

    def record(
        self,
        features: dict[str, str],
        sign: float,
    ) -> None:
        """Fold one feedback event. ``sign`` in ``[-1, +1]`` range;
        fractional allowed (e.g. +0.5 for a confirmed-hypothesis
        bonus)."""
        if sign == 0 or not features:
            return
        pos_inc = 1 if sign > 0 else 0
        neg_inc = 1 if sign < 0 else 0
        if pos_inc == 0 and neg_inc == 0:
            # Fractional — weight across the sign
            # Treat |sign| as evidence strength.
            weight = abs(sign)
            pos_inc = weight if sign > 0 else 0
            neg_inc = weight if sign < 0 else 0
        with self._lock, self._connect() as conn:
            for feat in _FEATURES:
                val = features.get(feat)
                if val is None:
                    continue
                val = str(val).strip().lower()
                if not val:
                    continue
                conn.execute(
                    "INSERT INTO feature_counts "
                    "(feature, value, pos, neg, last_update) "
                    "VALUES (?,?,?,?,?) "
                    "ON CONFLICT(feature, value) DO UPDATE SET "
                    "  pos=pos+?, neg=neg+?, last_update=?",
                    (feat, val, pos_inc, neg_inc, time.time(),
                     pos_inc, neg_inc, time.time()),
                )
                conn.execute(
                    "INSERT INTO global_counts "
                    "(feature, pos_total, neg_total) "
                    "VALUES (?,?,?) "
                    "ON CONFLICT(feature) DO UPDATE SET "
                    "  pos_total=pos_total+?, neg_total=neg_total+?",
                    (feat, pos_inc, neg_inc,
                     pos_inc, neg_inc),
                )
            conn.commit()

    # ── Score ──────────────────────────────────────────────

    def score(
        self,
        features: dict[str, str],
        kpi_hint: float = 0.0,
    ) -> RewardEstimate:
        """Estimate reward for a candidate action described by
        ``features``. ``kpi_hint`` is the model-predicted scalar
        (e.g. projected ROAS) the KPI-linear term consumes."""
        contribs: list[Contribution] = []
        pref_total = 0.0
        with self._connect() as conn:
            for feat in _FEATURES:
                val = features.get(feat)
                if val is None:
                    continue
                val = str(val).strip().lower()
                llr = self._llr(conn, feat, val)
                if llr == 0.0:
                    continue
                contribs.append(Contribution(
                    feature=feat, value=val, llr=llr,
                ))
                pref_total += llr
        kpi_term = self._alpha * float(kpi_hint)
        total = pref_total + kpi_term
        explain = _explain(contribs, kpi_term, total)
        return RewardEstimate(
            total=total,
            kpi_term=kpi_term,
            preference_term=pref_total,
            contributions=sorted(contribs,
                                  key=lambda c: -abs(c.llr)),
            explainability=explain,
        )

    # ── LLR helper ─────────────────────────────────────────

    @staticmethod
    def _llr(conn: sqlite3.Connection, feat: str, val: str) -> float:
        row = conn.execute(
            "SELECT pos, neg FROM feature_counts "
            "WHERE feature=? AND value=?",
            (feat, val),
        ).fetchone()
        if not row:
            return 0.0
        pos, neg = row
        g = conn.execute(
            "SELECT pos_total, neg_total FROM global_counts "
            "WHERE feature=?",
            (feat,),
        ).fetchone()
        if not g:
            return 0.0
        pos_total, neg_total = g
        # Smoothed probabilities
        p_val_given_pos = (pos + _SMOOTHING) / (
            pos_total + _SMOOTHING * 2
        )
        p_val_given_neg = (neg + _SMOOTHING) / (
            neg_total + _SMOOTHING * 2
        )
        return math.log(p_val_given_pos / p_val_given_neg)

    # ── Introspection ─────────────────────────────────────

    def top_preferences(
        self, feature: str, k: int = 5,
    ) -> list[dict[str, Any]]:
        """Top ``k`` values of ``feature`` the owner most/least
        prefers. Signed llr so the dashboard can colour wins vs
        dislikes."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT value, pos, neg FROM feature_counts "
                "WHERE feature=?",
                (feature,),
            ).fetchall()
            g = conn.execute(
                "SELECT pos_total, neg_total FROM global_counts "
                "WHERE feature=?",
                (feature,),
            ).fetchone()
        if not g:
            return []
        pos_total, neg_total = g
        out = []
        for value, pos, neg in rows:
            p_pos = (pos + _SMOOTHING) / (pos_total + _SMOOTHING * 2)
            p_neg = (neg + _SMOOTHING) / (neg_total + _SMOOTHING * 2)
            llr = math.log(p_pos / p_neg)
            out.append({
                "value": value, "pos": int(pos), "neg": int(neg),
                "llr": round(llr, 3),
            })
        # Sort by descending absolute llr
        out.sort(key=lambda r: -abs(r["llr"]))
        return out[:k]

    def size(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT COUNT(*) FROM feature_counts"
            ).fetchone()
            glob = conn.execute(
                "SELECT SUM(pos_total + neg_total) FROM global_counts"
            ).fetchone()
        return {
            "feature_cells": int(rows[0] or 0),
            "total_feedback_events": int(glob[0] or 0),
        }


def _explain(
    contribs: list[Contribution], kpi_term: float, total: float,
) -> str:
    if not contribs and kpi_term == 0:
        return "no preference signal yet"
    top_two = sorted(contribs, key=lambda c: -abs(c.llr))[:2]
    bits = []
    for c in top_two:
        direction = "+" if c.llr > 0 else "−"
        bits.append(f"{direction}{abs(c.llr):.2f} {c.feature}={c.value}")
    if kpi_term:
        bits.append(f"+{kpi_term:.2f} KPI")
    return f"reward={total:+.2f} ({', '.join(bits)})"


# ── Singleton ────────────────────────────────────────────────

_RM_LOCK = threading.Lock()
_RM: RewardModel | None = None


def reward_model() -> RewardModel:
    global _RM
    if _RM is None:
        with _RM_LOCK:
            if _RM is None:
                _RM = RewardModel()
    return _RM
