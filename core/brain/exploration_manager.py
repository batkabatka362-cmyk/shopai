"""Exploration manager — central bandit chooser for the whole brain.

Lots of subsystems already make exploit-or-explore choices ad hoc:
discount strategist tries new offers, skill_library probes untested
skills, hyperparameter_tuner prefers unseen arms. The exploration
manager centralises the *policy* (ε-greedy, Thompson sampling, UCB1)
so callers just say "pick one of these candidates" and the manager
handles the exploration logic + records the outcome.

Each ``Bandit`` keeps per-arm posteriors (Beta(α, β)) and supports
three strategies:

  • epsilon_greedy(epsilon)   — best with prob 1-ε, random otherwise
  • thompson_sample()         — sample from each Beta, pick arg-max
  • ucb1()                    — choose by mean + sqrt(2 ln n / pulls)

All arms must be added before the first pick; ``observe`` is how
callers feed back success/failure.

Pure stdlib. Deterministic given a seed. Persistence is optional via
SQLite.
"""
from __future__ import annotations

import math
import random
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.exploration_manager")


Strategy = Literal["epsilon_greedy", "thompson", "ucb1"]


@dataclass
class _Arm:
    name: str
    alpha: float = 1.0
    beta: float = 1.0
    last_pulled_ts: float = 0.0

    @property
    def pulls(self) -> int:
        return int(self.alpha + self.beta - 2.0)

    @property
    def mean(self) -> float:
        denom = self.alpha + self.beta
        return self.alpha / denom if denom > 0 else 0.5

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "alpha": round(self.alpha, 4),
            "beta": round(self.beta, 4),
            "pulls": self.pulls,
            "mean": round(self.mean, 4),
            "last_pulled_ts": self.last_pulled_ts,
        }


@dataclass
class BanditSnapshot:
    bandit: str
    strategy: Strategy
    arms: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "bandit": self.bandit,
            "strategy": self.strategy,
            "arms": list(self.arms),
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS bandit_arms (
    bandit          TEXT NOT NULL,
    arm             TEXT NOT NULL,
    alpha           REAL NOT NULL DEFAULT 1.0,
    beta            REAL NOT NULL DEFAULT 1.0,
    last_pulled_ts  REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (bandit, arm)
);
"""


class ExplorationManager:
    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        seed: int | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._bandits: dict[str, dict[str, _Arm]] = {}
        self._strategies: dict[str, Strategy] = {}
        self._rng = random.Random(seed)
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

    def register(
        self,
        bandit: str,
        arms: Iterable[str],
        *,
        strategy: Strategy = "thompson",
    ) -> None:
        if not bandit:
            raise ValueError("bandit name required")
        if strategy not in ("epsilon_greedy", "thompson", "ucb1"):
            raise ValueError("invalid strategy")
        arm_names = [str(a) for a in arms if str(a)]
        if not arm_names:
            raise ValueError("need at least one arm")
        with self._lock:
            existing = self._bandits.get(bandit, {})
            for n in arm_names:
                if n not in existing:
                    existing[n] = _Arm(name=n)
            self._bandits[bandit] = existing
            self._strategies[bandit] = strategy
            if self._conn is not None:
                for arm in existing.values():
                    self._conn.execute(
                        "INSERT OR IGNORE INTO bandit_arms"
                        "(bandit, arm) VALUES (?, ?)",
                        (bandit, arm.name),
                    )
                self._conn.commit()

    def unregister(self, bandit: str) -> bool:
        with self._lock:
            present = bandit in self._bandits
            self._bandits.pop(bandit, None)
            self._strategies.pop(bandit, None)
            if self._conn is not None:
                self._conn.execute(
                    "DELETE FROM bandit_arms WHERE bandit=?",
                    (bandit,),
                )
                self._conn.commit()
        return present

    def _load(self) -> None:
        if self._conn is None:
            return
        with self._lock:
            for row in self._conn.execute(
                "SELECT bandit, arm, alpha, beta, last_pulled_ts "
                "FROM bandit_arms",
            ):
                self._bandits.setdefault(row[0], {})[row[1]] = _Arm(
                    name=row[1],
                    alpha=float(row[2]),
                    beta=float(row[3]),
                    last_pulled_ts=float(row[4]),
                )
                self._strategies.setdefault(row[0], "thompson")

    # ── Selection strategies ─────────────────────────────

    def _epsilon_greedy(
        self, arms: list[_Arm], epsilon: float,
    ) -> _Arm:
        if not arms:
            raise ValueError("no arms")
        if self._rng.random() < epsilon:
            return self._rng.choice(arms)
        return max(arms, key=lambda a: a.mean)

    def _thompson(self, arms: list[_Arm]) -> _Arm:
        # Sample from each Beta and pick the highest sample.
        return max(
            arms,
            key=lambda a: self._rng.betavariate(a.alpha, a.beta),
        )

    def _ucb1(self, arms: list[_Arm]) -> _Arm:
        total_pulls = sum(a.pulls for a in arms)
        if total_pulls == 0:
            return arms[0]
        # Any unseen arm gets infinite priority — try it first.
        for a in arms:
            if a.pulls == 0:
                return a
        return max(
            arms,
            key=lambda a: (
                a.mean + math.sqrt(2.0 * math.log(total_pulls) / a.pulls)
            ),
        )

    def pick(
        self,
        bandit: str,
        *,
        strategy: Strategy | None = None,
        epsilon: float = 0.1,
    ) -> str:
        if bandit not in self._bandits:
            raise ValueError(f"unknown bandit {bandit!r}")
        arms = list(self._bandits[bandit].values())
        if not arms:
            raise ValueError(f"bandit {bandit!r} has no arms")
        s = strategy or self._strategies.get(bandit, "thompson")
        if s == "epsilon_greedy":
            chosen = self._epsilon_greedy(arms, epsilon=epsilon)
        elif s == "ucb1":
            chosen = self._ucb1(arms)
        else:
            chosen = self._thompson(arms)
        return chosen.name

    # ── Feedback ─────────────────────────────────────────

    def observe(
        self, bandit: str, arm: str, *, success: bool,
    ) -> None:
        if bandit not in self._bandits:
            raise ValueError(f"unknown bandit {bandit!r}")
        arms = self._bandits[bandit]
        if arm not in arms:
            raise ValueError(
                f"arm {arm!r} not registered for {bandit!r}",
            )
        with self._lock:
            a = arms[arm]
            if success:
                a.alpha += 1.0
            else:
                a.beta += 1.0
            a.last_pulled_ts = time.time()
            if self._conn is not None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO bandit_arms"
                    "(bandit, arm, alpha, beta, last_pulled_ts) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        bandit, arm, a.alpha, a.beta,
                        a.last_pulled_ts,
                    ),
                )
                self._conn.commit()

    # ── Introspection ────────────────────────────────────

    def snapshot(self, bandit: str) -> BanditSnapshot:
        if bandit not in self._bandits:
            raise ValueError(f"unknown bandit {bandit!r}")
        return BanditSnapshot(
            bandit=bandit,
            strategy=self._strategies[bandit],
            arms=[a.as_dict() for a in self._bandits[bandit].values()],
        )

    def stats(self) -> dict[str, Any]:
        return {
            "bandits": len(self._bandits),
            "by_bandit": {
                name: {
                    "arms": len(arms),
                    "total_pulls": sum(a.pulls for a in arms.values()),
                    "strategy": self._strategies.get(name, "thompson"),
                }
                for name, arms in self._bandits.items()
            },
        }

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
