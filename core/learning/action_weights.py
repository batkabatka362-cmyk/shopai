"""ActionWeightStore — closes the learning loop.

Pre-fix the ShopAI learning pipeline recorded outcomes to
memory but **never fed them back into the next decision**.
``DecisionEngine._score_options`` computed a ``memory_boost``
/ ``memory_penalty`` based on raw similar-case counts, but
the ``LearningPipeline._update_weights`` counter just
incremented an integer and threw it away. Brain's next
``think()`` call had no mechanism to consult accumulated
learning.

This module provides the missing glue: a small, auditable
weight store keyed by ``(category, action)`` pair, updated
with an exponential moving average of outcome scores, and
persisted to a SQLite table so weights survive restarts.

Flow:

  1. Brain picks an action (DecisionEngine.decide → Decision).
  2. Action runs, outcome is scored 0..5.
  3. ``DecisionEngine.record_outcome`` calls
     ``ActionWeightStore.record(category, action, score)``.
  4. Weight is updated: ``w = 0.9 * old + 0.1 * (score/5 * 2)``
     (normalised so weight 1.0 == neutral, 2.0 == strong
     positive, 0.0 == strong negative).
  5. Next time brain picks options in the same category,
     ``DecisionEngine._score_options`` multiplies each
     option's final score by the learned weight via
     ``ActionWeightStore.get(category, action)``.
  6. Over time, consistently successful actions rise in the
     ranking; consistently failing actions sink.

Design constraints:

  * **In-memory first, SQLite second** — reads are hot-path
    (every decision), so the store keeps a dict cache and
    only writes to disk on update + reload on startup.
  * **Thread-safe** — ``RLock`` pattern reused from
    ``core/rate_limiter/`` + ``core/adapters/registry``.
  * **Bounded** — weights clamped to ``[_MIN_WEIGHT,
    _MAX_WEIGHT]`` so a single catastrophic outcome can't
    permanently kill an action, and a lucky win can't
    rocket it to the moon.
  * **EMA smoothing** — alpha = 0.1 so the store learns from
    10 consecutive outcomes before saturating. Prevents
    thrashing from a single noisy cycle.
  * **No ML libraries** — hand-written arithmetic. The brain
    must stay explainable; operators need to be able to
    trace why a weight changed to which outcome.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from utils.helpers import safe_float
from utils.logger import get_logger

logger = get_logger("learning.weights")


# Weight update math.
#
# ``weight`` lives in [_MIN_WEIGHT, _MAX_WEIGHT]. Update rule:
#
#     scaled = (score / 5.0) * 2.0           # score in [0,5] → scaled in [0,2]
#     w_new  = (1 - ALPHA) * w_old + ALPHA * scaled
#
# With ALPHA = 0.1 the store moves from 1.0 → 2.0 in ~22
# consecutive perfect (5.0) outcomes, and 1.0 → 0.0 in ~22
# consecutive total-failure (0.0) outcomes. A single outlier
# shifts the weight by at most ``ALPHA * 2`` = 0.2.

_ALPHA = 0.1
_NEUTRAL_WEIGHT = 1.0
_MIN_WEIGHT = 0.1
_MAX_WEIGHT = 2.0

# Maximum outcome score the store expects. Score values in
# ShopAI's memory layer live in [0, 5]. Defensive clamping
# guards against calling code that feeds in something out of
# range.
_MAX_SCORE = 5.0

_DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "action_weights.db"
)


class ActionWeightStore:
    """Thread-safe weight store for ``(category, action)`` pairs.

    Usage::

        store = get_action_weight_store()

        # recording an outcome
        store.record("pricing", "lower_10pct", score=4.2)

        # reading a weight (returns 1.0 if unknown)
        w = store.get("pricing", "lower_10pct")

        # applying to a scored option
        option["final_score"] *= w
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._lock = threading.RLock()
        self._cache: dict[tuple[str, str], float] = {}
        self._sample_counts: dict[tuple[str, str], int] = {}
        self._init_db()
        self._reload()

    # ── Persistence ────────────────────────────────────────────

    def _init_db(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("weights: failed to create dir %s: %s",
                           self._db_path.parent, exc)
            return

        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS action_weights (
                        category  TEXT NOT NULL,
                        action    TEXT NOT NULL,
                        weight    REAL NOT NULL,
                        samples   INTEGER NOT NULL DEFAULT 0,
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (category, action)
                    )
                """)
                conn.commit()
        except sqlite3.Error as exc:
            logger.warning("weights: db init failed: %s", exc)

    def _reload(self) -> None:
        """Load every row into the in-memory cache. Called on
        construction so decision reads don't pay SQLite cost
        on the hot path."""
        with self._lock:
            self._cache.clear()
            self._sample_counts.clear()
            try:
                with sqlite3.connect(self._db_path) as conn:
                    for row in conn.execute(
                        "SELECT category, action, weight, samples "
                        "FROM action_weights"
                    ):
                        cat, act, weight, samples = row
                        self._cache[(str(cat), str(act))] = float(weight)
                        self._sample_counts[(str(cat), str(act))] = int(samples)
            except sqlite3.Error as exc:
                logger.debug("weights: reload failed (empty store): %s", exc)

    def _persist(self, category: str, action: str) -> None:
        """Write one row back to SQLite. Called inside the
        lock after a weight update. Failures are logged but
        don't propagate — a disk hiccup should never break a
        real decision call."""
        key = (category, action)
        weight = self._cache.get(key, _NEUTRAL_WEIGHT)
        samples = self._sample_counts.get(key, 0)
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO action_weights "
                    "(category, action, weight, samples, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(category, action) DO UPDATE SET "
                    "weight = excluded.weight, "
                    "samples = excluded.samples, "
                    "updated_at = excluded.updated_at",
                    (category, action, weight, samples, time.time()),
                )
                conn.commit()
        except sqlite3.Error as exc:
            logger.warning(
                "weights: persist failed for %s/%s: %s",
                category, action, exc,
            )

    # ── Public API ─────────────────────────────────────────────

    def get(self, category: str, action: str) -> float:
        """Return the current weight for ``(category, action)``.

        Unknown pairs return the neutral default (1.0). Calls
        are fast — the in-memory cache is the only touch on
        the hot path.
        """
        if not category or not action:
            return _NEUTRAL_WEIGHT
        with self._lock:
            return self._cache.get((category, action), _NEUTRAL_WEIGHT)

    def record(
        self,
        category: str,
        action: str,
        score: float,
    ) -> float:
        """Record an outcome for ``(category, action)`` and
        return the updated weight.

        ``score`` is the outcome's quality in the ShopAI
        memory scale of [0, 5]. Values outside that range are
        clamped defensively.

        Update rule: EMA with alpha=0.1 applied to the score
        normalised to the weight space.
        """
        if not category or not action:
            return _NEUTRAL_WEIGHT

        # Clamp + normalise. score/5 is in [0,1], * 2 maps
        # neutral outcome (2.5/5 = 0.5) to weight 1.0, perfect
        # outcome (5/5 = 1.0) to weight 2.0, total failure to 0.0.
        score_val = max(0.0, min(_MAX_SCORE, safe_float(score)))
        scaled = (score_val / _MAX_SCORE) * 2.0

        key = (category, action)
        with self._lock:
            old_weight = self._cache.get(key, _NEUTRAL_WEIGHT)
            new_weight = (1.0 - _ALPHA) * old_weight + _ALPHA * scaled
            # Clamp to [MIN, MAX] so outliers can't escape.
            new_weight = max(_MIN_WEIGHT, min(_MAX_WEIGHT, new_weight))
            self._cache[key] = new_weight
            self._sample_counts[key] = self._sample_counts.get(key, 0) + 1
            self._persist(category, action)
            return new_weight

    def reset(self, category: str | None = None) -> None:
        """Clear weights for *category*, or the entire store
        when ``category`` is ``None``. Test helper + operator
        override."""
        with self._lock:
            if category is None:
                self._cache.clear()
                self._sample_counts.clear()
                try:
                    with sqlite3.connect(self._db_path) as conn:
                        conn.execute("DELETE FROM action_weights")
                        conn.commit()
                except sqlite3.Error as exc:
                    logger.debug("action weights full reset failed: %s", exc)
                return
            keys_to_drop = [k for k in self._cache if k[0] == category]
            for k in keys_to_drop:
                self._cache.pop(k, None)
                self._sample_counts.pop(k, None)
            try:
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute(
                        "DELETE FROM action_weights WHERE category = ?",
                        (category,),
                    )
                    conn.commit()
            except sqlite3.Error as exc:
                logger.debug("action weights category reset failed: %s", exc)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe view of every weight + sample
        count. Used by the observability dashboard."""
        with self._lock:
            return {
                f"{cat}:{act}": {
                    "weight": round(weight, 4),
                    "samples": self._sample_counts.get((cat, act), 0),
                }
                for (cat, act), weight in self._cache.items()
            }

    def stats(self) -> dict[str, Any]:
        """High-level counters for logs + tests."""
        with self._lock:
            total_samples = sum(self._sample_counts.values())
            return {
                "entries": len(self._cache),
                "total_samples": total_samples,
                "min_weight": _MIN_WEIGHT,
                "max_weight": _MAX_WEIGHT,
                "neutral_weight": _NEUTRAL_WEIGHT,
                "alpha": _ALPHA,
            }


# ── Module-level singleton ─────────────────────────────────


_store: ActionWeightStore | None = None
_store_lock = threading.Lock()


def get_action_weight_store(db_path: Path | None = None) -> ActionWeightStore:
    """Return the process-wide ``ActionWeightStore`` singleton.

    The singleton is constructed on first call and reused
    forever. Tests that need isolation should call
    ``reset_action_weight_store()`` with an explicit temp
    path.
    """
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ActionWeightStore(db_path)
    return _store


def reset_action_weight_store(db_path: Path | None = None) -> ActionWeightStore:
    """Replace the singleton with a fresh store. Test helper;
    not used by production code."""
    global _store
    with _store_lock:
        _store = ActionWeightStore(db_path)
    return _store
