"""Per-action staged-execution promotion ladder.

Closes the AGI audit's #4 gap (Staged Writeback Auto-Promotion).
``SmartExecutor`` historically defaulted to SIMULATE and capped
the most-confident path at DRY_RUN — even repeatedly-successful
actions never auto-advanced to LIVE. The audit flagged this as
"Only 3% of actions go LIVE" / "no mechanism for the system to
build trust in itself."

This module is the missing trust ladder. For each
``action_type`` it tracks the count of consecutive successes
since the last failure and exposes a ``current_tier`` of
``simulate`` → ``dry_run`` → ``live``. The executor consults the
tier when picking a mode; a successful execution at the current
tier ticks the count up; any failure demotes back to
``simulate``.

Storage is SQLite at ``data/promotion_tracker.db`` — same
pattern as the action-weight store, approval queue, etc.
Single table, no migrations yet (this is the v1 schema):

    action_type      TEXT PRIMARY KEY
    current_tier     TEXT NOT NULL  -- "simulate" | "dry_run" | "live"
    consecutive_ok   INTEGER NOT NULL -- since last failure / since
                                      -- the current tier was entered
    last_outcome     TEXT
    last_updated     REAL

Promotion thresholds default to 3 / 3 (3 successes at SIMULATE
unlocks DRY_RUN, 3 more unlocks LIVE) and are tunable per
:class:`PromotionTracker` instance for tests / cautious
operators.

Threading: a module-level RLock guards every read+write so the
API server's request handler threads can safely consult the
tracker concurrently.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("execution.promotion_tracker")

_DB_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "promotion_tracker.db"
)
_LOCK = threading.RLock()
_INSTANCE: "PromotionTracker | None" = None

# Tier ladder, lowest → highest trust.
TIER_SIMULATE = "simulate"
TIER_DRY_RUN = "dry_run"
TIER_LIVE = "live"
_TIER_ORDER = [TIER_SIMULATE, TIER_DRY_RUN, TIER_LIVE]


class PromotionTracker:
    """SQLite-backed ladder mapping action_type → current trust tier."""

    def __init__(
        self,
        *,
        db_path: Path | str | None = None,
        promote_threshold: int = 3,
    ) -> None:
        self._db_path = Path(db_path) if db_path else _DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._db_path), check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        # Successes-at-current-tier needed to promote to the next.
        # Same threshold for both transitions; a future iteration
        # could split simulate→dry_run from dry_run→live.
        self._promote_threshold = max(1, int(promote_threshold))

    def _init_schema(self) -> None:
        with _LOCK:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS promotions (
                    action_type    TEXT PRIMARY KEY,
                    current_tier   TEXT NOT NULL,
                    consecutive_ok INTEGER NOT NULL DEFAULT 0,
                    last_outcome   TEXT,
                    last_updated   REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_promo_tier
                    ON promotions(current_tier);
            """)
            self._conn.commit()

    # ── Public API ─────────────────────────────────────────────

    def current_tier(self, action_type: str) -> str:
        """Return the active tier for ``action_type``.

        Unknown action types start at :data:`TIER_SIMULATE` —
        the tracker doesn't pre-populate rows; the first
        ``record_success`` / ``record_failure`` call materialises
        an entry.
        """
        if not action_type:
            return TIER_SIMULATE
        with _LOCK:
            row = self._conn.execute(
                "SELECT current_tier FROM promotions WHERE action_type = ?",
                (action_type,),
            ).fetchone()
        if row is None:
            return TIER_SIMULATE
        return str(row["current_tier"])

    def record_success(self, action_type: str) -> dict[str, Any]:
        """Increment the success count; promote if threshold hit.

        Returns a snapshot of the post-update state:
        ``{tier, consecutive_ok, promoted}``. ``promoted`` is
        ``True`` when this call advanced the tier — useful for
        audit logs / API surface.
        """
        if not action_type:
            return {
                "tier": TIER_SIMULATE,
                "consecutive_ok": 0,
                "promoted": False,
            }
        return self._record_outcome(
            action_type, success=True,
        )

    def record_failure(self, action_type: str) -> dict[str, Any]:
        """Demote to :data:`TIER_SIMULATE` and zero the success count.

        Conservative-by-default: any failure resets the ladder
        regardless of how many prior successes accumulated. A
        future tunable could allow a "soft" demotion (one tier
        down) instead.
        """
        if not action_type:
            return {
                "tier": TIER_SIMULATE,
                "consecutive_ok": 0,
                "promoted": False,
            }
        return self._record_outcome(
            action_type, success=False,
        )

    def snapshot(self) -> list[dict[str, Any]]:
        """Per-action_type list of current state. API surface for
        the merchant page.
        """
        with _LOCK:
            rows = self._conn.execute(
                """SELECT action_type, current_tier, consecutive_ok,
                          last_outcome, last_updated
                   FROM promotions
                   ORDER BY last_updated DESC""",
            ).fetchall()
        return [
            {
                "action_type": r["action_type"],
                "current_tier": r["current_tier"],
                "consecutive_ok": int(r["consecutive_ok"]),
                "last_outcome": r["last_outcome"],
                "last_updated": r["last_updated"],
            }
            for r in rows
        ]

    # ── Internals ─────────────────────────────────────────────

    def _record_outcome(
        self, action_type: str, *, success: bool,
    ) -> dict[str, Any]:
        now = time.time()
        with _LOCK:
            row = self._conn.execute(
                "SELECT current_tier, consecutive_ok FROM promotions "
                "WHERE action_type = ?",
                (action_type,),
            ).fetchone()

            if row is None:
                tier = TIER_SIMULATE
                consec = 0
            else:
                tier = str(row["current_tier"])
                consec = int(row["consecutive_ok"])

            promoted = False
            if success:
                consec += 1
                if (
                    consec >= self._promote_threshold
                    and tier != TIER_LIVE
                ):
                    next_tier = _next_tier(tier)
                    if next_tier != tier:
                        tier = next_tier
                        consec = 0  # reset count for the new tier
                        promoted = True
                        logger.info(
                            "promotion_tracker: %s → %s",
                            action_type, tier,
                        )
            else:
                # Any failure → reset to simulate.
                if tier != TIER_SIMULATE:
                    logger.info(
                        "promotion_tracker: %s demoted (%s → %s) on failure",
                        action_type, tier, TIER_SIMULATE,
                    )
                tier = TIER_SIMULATE
                consec = 0

            self._conn.execute(
                """INSERT INTO promotions
                   (action_type, current_tier, consecutive_ok,
                    last_outcome, last_updated)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(action_type) DO UPDATE SET
                     current_tier   = excluded.current_tier,
                     consecutive_ok = excluded.consecutive_ok,
                     last_outcome   = excluded.last_outcome,
                     last_updated   = excluded.last_updated""",
                (
                    action_type, tier, consec,
                    "success" if success else "failure", now,
                ),
            )
            self._conn.commit()

        return {
            "tier": tier,
            "consecutive_ok": consec,
            "promoted": promoted,
        }


# ── Module helpers ─────────────────────────────────────────────


def get_promotion_tracker(
    *,
    db_path: Path | str | None = None,
    promote_threshold: int | None = None,
) -> PromotionTracker:
    """Process-wide :class:`PromotionTracker` singleton.

    Tests pass ``db_path`` to swap in a temp DB; production code
    leaves it ``None`` so every caller shares the same SQLite file.
    """
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None or db_path is not None:
            _INSTANCE = PromotionTracker(
                db_path=db_path,
                promote_threshold=promote_threshold or 3,
            )
    return _INSTANCE


def reset_promotion_tracker() -> None:
    """Drop the cached singleton — test fixture only."""
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is not None:
            try:
                _INSTANCE._conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("close failed: %s", exc)
        _INSTANCE = None


def _next_tier(current: str) -> str:
    """Return the tier one step above ``current``, or ``current``
    when already at the top of the ladder.
    """
    try:
        idx = _TIER_ORDER.index(current)
    except ValueError:
        return TIER_SIMULATE
    if idx + 1 >= len(_TIER_ORDER):
        return current
    return _TIER_ORDER[idx + 1]
