"""Owner model — learn the owner's preferences from their feedback.

ShopAI's actions live or die by the owner's reaction. But the brain
currently treats feedback as uniform: an up-vote bumps one rule, a
down-vote nicks one rule. The owner's *style* (cautious vs
aggressive, cost-sensitive vs growth-first, auto-approve vs approve-
every-thing) never becomes explicit knowledge the brain can reason
about.

OwnerModel captures that style as a small set of scalar preferences
learned online from owner decisions:

  • risk_tolerance   — ratio of approved bold actions to all bold ones
  • autonomy_tolerance — how much owner lets ShopAI run without review
  • cost_sensitivity — approve rate weighted by action cost
  • growth_preference — approve rate for scale-type vs conservative
  • velocity         — how quickly owner responds (h between action
                        and feedback)

Each is a Beta-posterior (Laplace-smoothed alpha/beta). ``weights()``
returns a dict usable by ``utility_blender`` to bias the multi-
objective score toward the owner's actual taste.

Every feedback event is persisted to SQLite; the public ``record``
method accepts a simple (action_kind, cost_usd, bold, approved, …)
record and updates all relevant posteriors.

Pure stdlib. Deterministic. No LLM.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_SCHEMA = """
CREATE TABLE IF NOT EXISTS owner_feedback (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           REAL NOT NULL,
    action_kind  TEXT NOT NULL,
    cost_usd     REAL NOT NULL DEFAULT 0,
    bold         INTEGER NOT NULL DEFAULT 0,
    approved     INTEGER NOT NULL,
    latency_s    REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_of_kind ON owner_feedback(action_kind, ts);
"""


def _beta_mean(alpha: float, beta: float) -> float:
    denom = alpha + beta
    return alpha / denom if denom > 0 else 0.5


@dataclass
class Preferences:
    risk_tolerance: float
    autonomy_tolerance: float
    cost_sensitivity: float
    growth_preference: float
    velocity_h: float
    n_feedback: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk_tolerance": round(self.risk_tolerance, 4),
            "autonomy_tolerance": round(self.autonomy_tolerance, 4),
            "cost_sensitivity": round(self.cost_sensitivity, 4),
            "growth_preference": round(self.growth_preference, 4),
            "velocity_h": round(self.velocity_h, 2),
            "n_feedback": self.n_feedback,
        }

    def weights(self) -> dict[str, float]:
        """Map preferences to utility_blender weight hints.

        Returns weights summing to ~1 across four canonical
        objectives used across the brain.
        """
        # growth_preference moves weight between roas and stability.
        g = max(0.0, min(1.0, self.growth_preference))
        # cost_sensitivity moves weight toward cost minimisation.
        c = max(0.0, min(1.0, self.cost_sensitivity))
        # risk_tolerance moves weight between safety floor and reach.
        r = max(0.0, min(1.0, self.risk_tolerance))

        raw = {
            "roas":        0.20 + 0.30 * g,
            "refund_rate": 0.15 + 0.20 * (1.0 - r),
            "cost":        0.10 + 0.30 * c,
            "stability":   0.15 + 0.20 * (1.0 - g),
        }
        total = sum(raw.values()) or 1.0
        return {k: v / total for k, v in raw.items()}


class OwnerModel:
    def __init__(
        self, db_path: str | Path = "data/owner_model.db",
    ) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Record a single feedback event ────────────────────

    def record(
        self,
        *,
        action_kind: str,
        approved: bool,
        cost_usd: float = 0.0,
        bold: bool = False,
        latency_s: float = 0.0,
    ) -> None:
        if not action_kind:
            raise ValueError("action_kind required")
        with self._lock:
            self._conn.execute(
                "INSERT INTO owner_feedback("
                "  ts, action_kind, cost_usd, bold, approved, latency_s"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    time.time(), str(action_kind),
                    float(cost_usd), 1 if bold else 0,
                    1 if approved else 0, float(latency_s),
                ),
            )
            self._conn.commit()

    # ── Derive preferences from history ───────────────────

    def _rows(self) -> list[tuple[Any, ...]]:
        with self._lock:
            return self._conn.execute(
                "SELECT action_kind, cost_usd, bold, approved, latency_s "
                "FROM owner_feedback",
            ).fetchall()

    def preferences(self) -> Preferences:
        rows = self._rows()
        # Start with Laplace priors so a cold start returns 0.5 everywhere.
        risk_a = risk_b = 1.0
        cost_weighted_a = cost_weighted_b = 1.0
        growth_a = growth_b = 1.0
        autonomy_a = autonomy_b = 1.0
        lat_sum = 0.0
        lat_n = 0

        for action_kind, cost, bold, approved, latency in rows:
            approved_b = int(approved) == 1
            bold_b = int(bold) == 1
            cost = float(cost or 0.0)
            latency = float(latency or 0.0)

            # risk_tolerance: approved-rate on bold actions
            if bold_b:
                if approved_b:
                    risk_a += 1.0
                else:
                    risk_b += 1.0

            # cost_sensitivity: only material-cost samples contribute;
            # a rejected $0.01 action is not a cost signal. We then
            # weight by dollar amount so one $100 rejection matters
            # much more than ten $2 rejections.
            if cost >= 1.0:
                w = min(cost, 100.0) / 10.0
                if approved_b:
                    cost_weighted_a += w
                else:
                    cost_weighted_b += w

            # growth_preference: approve rate on scale-type kinds
            if "scale" in action_kind or "grow" in action_kind:
                if approved_b:
                    growth_a += 1.0
                else:
                    growth_b += 1.0

            # autonomy_tolerance: approve-without-edit rate.
            # If latency > 0 the owner reviewed; <=0.01 = auto-approved.
            if latency <= 0.01:
                autonomy_a += 1.0
            else:
                autonomy_b += 1.0
                if latency > 0:
                    lat_sum += latency
                    lat_n += 1

        return Preferences(
            risk_tolerance=_beta_mean(risk_a, risk_b),
            autonomy_tolerance=_beta_mean(autonomy_a, autonomy_b),
            cost_sensitivity=(
                # Higher cost_sensitivity = more rejections on pricey
                # actions. Flip so "owner hates cost" → high.
                1.0 - _beta_mean(cost_weighted_a, cost_weighted_b)
            ),
            growth_preference=_beta_mean(growth_a, growth_b),
            velocity_h=(
                (lat_sum / lat_n) / 3600.0 if lat_n > 0 else 0.0
            ),
            n_feedback=len(rows),
        )

    def weights(self) -> dict[str, float]:
        return self.preferences().weights()

    # ── Summary + maintenance ─────────────────────────────

    def summary(self) -> dict[str, Any]:
        prefs = self.preferences()
        return {
            "preferences": prefs.as_dict(),
            "weights": prefs.weights(),
        }

    def clear(self) -> int:
        with self._lock:
            n = self._conn.execute(
                "SELECT COUNT(*) FROM owner_feedback",
            ).fetchone()[0]
            self._conn.execute("DELETE FROM owner_feedback")
            self._conn.commit()
        return int(n)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
