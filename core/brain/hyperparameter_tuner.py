"""Hyperparameter tuner — learn the right knob value from outcomes.

ShopAI has hundreds of magic numbers: kill thresholds, retry budgets,
attention weights, exploration epsilons. Hand-tuning them is fragile.
The hyperparameter tuner treats each knob as a multi-armed bandit
over a *finite, discrete* set of candidate values, and reports which
value is currently winning.

Two estimators per arm: Beta posterior (success rate) and a Welford
mean for the reward magnitude. The recommended arm balances both:

    score(arm) = mean(arm) × success_rate(arm)

so a knob value that wins occasionally with high payoff still beats a
boring-but-safe value that wins more often but with lower payoff —
unless we ask for ``policy="safe"`` which prefers success rate alone.

Persistence is optional via SQLite. Pure stdlib. Deterministic.

Usage:

    tuner.register("kill_threshold", arms=[1.2, 1.5, 1.8, 2.0])
    val = tuner.suggest("kill_threshold")            # current pick
    # ... use val, observe outcome ...
    tuner.observe("kill_threshold", arm=val,
                  reward=12.0, success=True)
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.hyperparameter_tuner")


Policy = Literal["best", "safe"]


@dataclass
class Arm:
    value: Any
    pulls: int = 0
    wins: int = 0
    reward_mean: float = 0.0
    reward_m2: float = 0.0    # Welford running sum of squares
    last_used_ts: float = 0.0

    @property
    def success_rate(self) -> float:
        # Laplace smoothing: 1/(2+pulls) prior of 0.5
        return (self.wins + 1.0) / (self.pulls + 2.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "pulls": self.pulls,
            "wins": self.wins,
            "reward_mean": round(self.reward_mean, 4),
            "success_rate": round(self.success_rate, 4),
            "last_used_ts": self.last_used_ts,
        }


@dataclass
class Knob:
    name: str
    arms: list[Arm] = field(default_factory=list)
    description: str = ""

    def arm(self, value: Any) -> Arm | None:
        for a in self.arms:
            if a.value == value:
                return a
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arms": [a.as_dict() for a in self.arms],
            "description": self.description,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS hp_observations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    knob      TEXT NOT NULL,
    arm_value TEXT NOT NULL,
    reward    REAL NOT NULL,
    success   INTEGER NOT NULL,
    ts        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hp_knob ON hp_observations(knob);
"""


class HyperparameterTuner:
    def __init__(
        self,
        db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._knobs: dict[str, Knob] = {}
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

    # ── Registration ─────────────────────────────────────

    def register(
        self,
        name: str,
        arms: Iterable[Any],
        *,
        description: str = "",
        overwrite: bool = False,
    ) -> Knob:
        if not name:
            raise ValueError("knob name required")
        arm_list = [Arm(value=v) for v in arms]
        if not arm_list:
            raise ValueError("knob needs at least one arm")
        if name in self._knobs and not overwrite:
            raise ValueError(f"knob {name!r} already registered")
        knob = Knob(name=name, arms=arm_list, description=description)
        self._knobs[name] = knob
        if self._conn is not None:
            self._replay(name)
        return knob

    def unregister(self, name: str) -> bool:
        return self._knobs.pop(name, None) is not None

    def get(self, name: str) -> Knob | None:
        return self._knobs.get(name)

    def knobs(self) -> list[Knob]:
        return list(self._knobs.values())

    # ── Observe ──────────────────────────────────────────

    def observe(
        self,
        name: str,
        arm: Any,
        *,
        reward: float = 0.0,
        success: bool = True,
    ) -> None:
        knob = self._knobs.get(name)
        if knob is None:
            raise ValueError(f"unknown knob {name!r}")
        arm_obj = knob.arm(arm)
        if arm_obj is None:
            raise ValueError(
                f"arm {arm!r} not registered for knob {name!r}",
            )
        with self._lock:
            arm_obj.pulls += 1
            if success:
                arm_obj.wins += 1
            # Welford update for reward
            delta = float(reward) - arm_obj.reward_mean
            arm_obj.reward_mean += delta / arm_obj.pulls
            delta2 = float(reward) - arm_obj.reward_mean
            arm_obj.reward_m2 += delta * delta2
            arm_obj.last_used_ts = time.time()
            if self._conn is not None:
                import json
                self._conn.execute(
                    "INSERT INTO hp_observations"
                    "(knob, arm_value, reward, success, ts) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        name,
                        json.dumps(arm),
                        float(reward),
                        1 if success else 0,
                        arm_obj.last_used_ts,
                    ),
                )
                self._conn.commit()

    def _replay(self, name: str) -> None:
        if self._conn is None:
            return
        import json
        knob = self._knobs[name]
        with self._lock:
            rows = self._conn.execute(
                "SELECT arm_value, reward, success, ts "
                "FROM hp_observations WHERE knob=? ORDER BY ts ASC",
                (name,),
            ).fetchall()
        for arm_json, reward, success, ts in rows:
            try:
                arm_value = json.loads(arm_json)
            except (json.JSONDecodeError, ValueError):
                continue
            arm_obj = knob.arm(arm_value)
            if arm_obj is None:
                continue
            arm_obj.pulls += 1
            if success:
                arm_obj.wins += 1
            delta = float(reward) - arm_obj.reward_mean
            arm_obj.reward_mean += delta / arm_obj.pulls
            delta2 = float(reward) - arm_obj.reward_mean
            arm_obj.reward_m2 += delta * delta2
            arm_obj.last_used_ts = float(ts)

    # ── Suggest ──────────────────────────────────────────

    def _score(self, arm: Arm, policy: Policy) -> float:
        if policy == "safe":
            return arm.success_rate
        # Default "best" — payoff × success rate
        return max(0.0, arm.reward_mean) * arm.success_rate

    def suggest(
        self,
        name: str,
        *,
        policy: Policy = "best",
        explore_unseen: bool = True,
    ) -> Any:
        knob = self._knobs.get(name)
        if knob is None:
            raise ValueError(f"unknown knob {name!r}")
        if not knob.arms:
            raise ValueError(f"knob {name!r} has no arms")
        # If any arm has zero pulls and explore_unseen is set, return
        # the first such arm — this guarantees we sample everything
        # before exploiting.
        if explore_unseen:
            for a in knob.arms:
                if a.pulls == 0:
                    return a.value
        return max(knob.arms, key=lambda a: self._score(a, policy)).value

    def best_arm(
        self, name: str, *, policy: Policy = "best",
    ) -> Arm | None:
        knob = self._knobs.get(name)
        if knob is None or not knob.arms:
            return None
        # Only consider arms with at least one pull when reporting
        # "best" — otherwise score is meaningless.
        candidates = [a for a in knob.arms if a.pulls > 0]
        if not candidates:
            return None
        return max(candidates, key=lambda a: self._score(a, policy))

    # ── Stats / maintenance ──────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "knobs": len(self._knobs),
            "by_knob": {
                name: {
                    "arms": len(k.arms),
                    "pulls": sum(a.pulls for a in k.arms),
                }
                for name, k in self._knobs.items()
            },
        }

    def reset(self, name: str | None = None) -> int:
        n = 0
        with self._lock:
            for kn in (
                [name] if name else list(self._knobs.keys())
            ):
                knob = self._knobs.get(kn)
                if knob is None:
                    continue
                for a in knob.arms:
                    n += a.pulls
                    a.pulls = 0
                    a.wins = 0
                    a.reward_mean = 0.0
                    a.reward_m2 = 0.0
            if self._conn is not None:
                if name:
                    self._conn.execute(
                        "DELETE FROM hp_observations WHERE knob=?",
                        (name,),
                    )
                else:
                    self._conn.execute(
                        "DELETE FROM hp_observations",
                    )
                self._conn.commit()
        return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
