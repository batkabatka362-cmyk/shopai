"""RL Pricing Agent — learns optimal prices from experience.

NOT formula-based. Learns from actual outcomes.

Algorithm: Multi-Armed Bandit with Thompson Sampling
  - Each product has price "arms" (buckets)
  - Each arm tracks: successes (revenue up) and failures (revenue down)
  - Thompson Sampling selects the best arm probabilistically
  - Over time, converges on optimal price per product

Why MAB over deep RL:
  - Works with small data (15 products, few orders)
  - No neural network needed (pure Python)
  - Explores automatically (no epsilon tuning)
  - Interpretable (can explain why a price was chosen)

State: product features (margin, category, competitor prices)
Actions: price adjustments (-20%, -10%, keep, +10%, +20%)
Reward: margin * conversion signal (from memory scores)
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("rl.pricing")

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "rl_pricing.db"

# Price adjustment actions
PRICE_ACTIONS = {
    "lower_20pct": -0.20,
    "lower_10pct": -0.10,
    "lower_5pct": -0.05,
    "keep": 0.00,
    "raise_5pct": 0.05,
    "raise_10pct": 0.10,
    "raise_20pct": 0.20,
}

ACTION_NAMES = list(PRICE_ACTIONS.keys())


def _v1_initial_schema(conn: sqlite3.Connection) -> None:
    """v1: arm_stats + decisions + outcomes."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS arm_stats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id  TEXT NOT NULL,
            action      TEXT NOT NULL,
            alpha       REAL DEFAULT 1.0,
            beta        REAL DEFAULT 1.0,
            pulls       INTEGER DEFAULT 0,
            total_reward REAL DEFAULT 0.0,
            avg_reward  REAL DEFAULT 0.0,
            last_pulled REAL DEFAULT 0.0,
            UNIQUE(product_id, action)
        );
        CREATE TABLE IF NOT EXISTS decisions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id  TEXT NOT NULL,
            action      TEXT NOT NULL,
            current_price REAL NOT NULL,
            recommended_price REAL NOT NULL,
            confidence  REAL DEFAULT 0.5,
            context     TEXT DEFAULT '{}',
            timestamp   REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS outcomes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id INTEGER NOT NULL,
            product_id  TEXT NOT NULL,
            action      TEXT NOT NULL,
            reward      REAL DEFAULT 0.0,
            revenue_impact REAL DEFAULT 0.0,
            timestamp   REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_arm_product ON arm_stats(product_id);
        CREATE INDEX IF NOT EXISTS idx_dec_product ON decisions(product_id);
    """)


_MIGRATIONS: list[tuple[int, str, Any]] = [
    (1, "initial schema", _v1_initial_schema),
]
_SCHEMA_VERSION = max(m[0] for m in _MIGRATIONS)


class PricingAgent:
    """RL pricing agent using Thompson Sampling."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path or _DB_PATH)
        self._local = threading.local()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "c") or self._local.c is None:
            self._local.c = sqlite3.connect(self._db_path, timeout=10)
            self._local.c.row_factory = sqlite3.Row
            self._local.c.execute("PRAGMA journal_mode=WAL")
        return self._local.c

    def _init_schema(self) -> None:
        from core.db.migrations import Migrator, register_schema
        Migrator(self._conn(), "rl_pricing", _MIGRATIONS).run()
        register_schema("rl_pricing", Path(self._db_path), _SCHEMA_VERSION)

    # == INITIALIZE ARMS ==========================================

    def initialize_product(self, product_id: str) -> None:
        """Initialize arms for a new product."""
        conn = self._conn()
        for action in ACTION_NAMES:
            conn.execute(
                "INSERT OR IGNORE INTO arm_stats (product_id, action, alpha, beta) VALUES (?,?,?,?)",
                (str(product_id), action, 1.0, 1.0),
            )
        conn.commit()

    # == SELECT ACTION (Thompson Sampling) =========================

    def select_action(self, product_id: str, current_price: float,
                      cost: float = 0.0, context: dict | None = None) -> dict[str, Any]:
        """Select best price action using Thompson Sampling.

        Returns:
            {action, recommended_price, confidence, reason, alternatives}
        """
        pid = str(product_id)
        self.initialize_product(pid)

        conn = self._conn()
        arms = conn.execute(
            "SELECT * FROM arm_stats WHERE product_id = ?", (pid,),
        ).fetchall()

        # Thompson Sampling: sample from Beta(alpha, beta) for each arm
        samples = {}
        for arm in arms:
            alpha = max(arm["alpha"], 0.1)
            beta_val = max(arm["beta"], 0.1)
            # Beta distribution sampling using inverse transform
            sample = self._beta_sample(alpha, beta_val)
            samples[arm["action"]] = {
                "sample": sample,
                "alpha": alpha,
                "beta": beta_val,
                "pulls": arm["pulls"],
                "avg_reward": arm["avg_reward"],
            }

        # Filter out actions that would price below cost
        valid_actions = {}
        for action_name, info in samples.items():
            adj = PRICE_ACTIONS[action_name]
            new_price = round(current_price * (1 + adj), 2)
            if cost > 0 and new_price < cost * 1.05:
                continue  # Don't price below cost + 5%
            valid_actions[action_name] = info

        if not valid_actions:
            valid_actions = {"keep": samples.get("keep", {"sample": 0.5})}

        # Select best arm
        best_action = max(valid_actions, key=lambda a: valid_actions[a]["sample"])
        best_info = valid_actions[best_action]

        adj = PRICE_ACTIONS[best_action]
        recommended_price = round(current_price * (1 + adj), 2)

        # Confidence = how much better is the best vs second best
        sorted_actions = sorted(valid_actions.items(), key=lambda x: -x[1]["sample"])
        if len(sorted_actions) >= 2:
            gap = sorted_actions[0][1]["sample"] - sorted_actions[1][1]["sample"]
            confidence = min(0.95, 0.5 + gap)
        else:
            confidence = 0.5

        # Exploration bonus: prefer less-explored arms occasionally
        total_pulls = sum(a["pulls"] for a in valid_actions.values())
        if total_pulls > 0 and best_info["pulls"] > total_pulls * 0.5:
            # This arm is over-explored, maybe try something else
            confidence *= 0.9

        # Record decision
        dec_id = self._record_decision(
            pid, best_action, current_price, recommended_price,
            confidence, context or {},
        )

        # Top alternatives
        alternatives = []
        for action_name, info in sorted_actions[1:3]:
            alt_adj = PRICE_ACTIONS[action_name]
            alt_price = round(current_price * (1 + alt_adj), 2)
            alternatives.append({
                "action": action_name,
                "price": alt_price,
                "score": round(info["sample"], 3),
                "pulls": info["pulls"],
            })

        return {
            "action": best_action,
            "recommended_price": recommended_price,
            "current_price": current_price,
            "price_change_pct": round(adj * 100, 1),
            "confidence": round(confidence, 3),
            "reason": self._build_reason(best_action, best_info, total_pulls),
            "decision_id": dec_id,
            "alternatives": alternatives,
            "exploration_rate": round(1.0 / max(total_pulls + 1, 1), 3),
        }

    # == RECORD OUTCOME ============================================

    def record_outcome(self, product_id: str, action: str,
                       reward: float, revenue_impact: float = 0.0,
                       decision_id: int = 0) -> None:
        """Record the outcome of a pricing action — the RL learning step.

        reward: 0-1 (0 = bad outcome, 1 = good outcome)
        """
        pid = str(product_id)
        conn = self._conn()

        # Update arm stats using Bayesian update
        if reward > 0.5:
            # Success: increment alpha
            conn.execute(
                "UPDATE arm_stats SET alpha = alpha + ?, pulls = pulls + 1, "
                "total_reward = total_reward + ?, last_pulled = ? WHERE product_id = ? AND action = ?",
                (reward, reward, time.time(), pid, action),
            )
        else:
            # Failure: increment beta
            conn.execute(
                "UPDATE arm_stats SET beta = beta + ?, pulls = pulls + 1, "
                "last_pulled = ? WHERE product_id = ? AND action = ?",
                (1.0 - reward, time.time(), pid, action),
            )

        # Update avg_reward
        arm = conn.execute(
            "SELECT pulls, total_reward FROM arm_stats WHERE product_id = ? AND action = ?",
            (pid, action),
        ).fetchone()
        if arm and arm["pulls"] > 0:
            conn.execute(
                "UPDATE arm_stats SET avg_reward = ? WHERE product_id = ? AND action = ?",
                (round(arm["total_reward"] / arm["pulls"], 3), pid, action),
            )

        # Record outcome
        conn.execute(
            "INSERT INTO outcomes (decision_id, product_id, action, reward, revenue_impact, timestamp) VALUES (?,?,?,?,?,?)",
            (decision_id, pid, action, reward, revenue_impact, time.time()),
        )
        conn.commit()

        logger.debug("RL update [%s/%s]: reward=%.2f", pid, action, reward)

    # == LEARN FROM MEMORY =========================================

    def learn_from_memory(self) -> dict[str, Any]:
        """Learn from MemoryIntelligence pricing decisions."""
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
        except Exception:
            return {"learned": 0}

        # Get all pricing memories with scores
        memories = mi.retrieve("pricing", min_score=0.0, limit=100)
        learned = 0

        for mem in memories:
            pid = ""
            action = mem.get("action", "")
            score = mem.get("score", 3.0)

            # Extract product_id from content
            content = mem.get("content", {})
            if isinstance(content, dict):
                pid = str(content.get("id", content.get("product_id", "")))

            if not pid or not action:
                continue

            # Convert memory score (1-5) to reward (0-1)
            reward = (score - 1.0) / 4.0  # 1→0, 5→1

            # Map memory action to our RL actions
            rl_action = self._map_action(action)
            if rl_action:
                self.initialize_product(pid)
                self.record_outcome(pid, rl_action, reward)
                learned += 1

        logger.info("RL learned from %d memory records", learned)
        return {"learned": learned}

    # == RECOMMEND FOR ALL PRODUCTS ================================

    def recommend_all(self, products: list[dict]) -> list[dict[str, Any]]:
        """Get pricing recommendations for all products."""
        recommendations = []
        for p in products:
            pid = str(p.get("id", ""))
            price = float(p.get("price", 0))
            cost = float(p.get("cost", 0))
            if not pid or price <= 0:
                continue

            rec = self.select_action(pid, price, cost, context={
                "category": p.get("product_type", p.get("category", "")),
                "name": p.get("name", p.get("title", "")),
            })
            recommendations.append(rec)

        return recommendations

    # == HELPERS ===================================================

    @staticmethod
    def _beta_sample(alpha: float, beta_val: float) -> float:
        """Sample from Beta(alpha, beta) distribution.
        Uses Joehnk's method for pure Python."""
        if alpha <= 0 or beta_val <= 0:
            return 0.5
        # Simple approximation: mean + noise based on variance
        mean = alpha / (alpha + beta_val)
        variance = (alpha * beta_val) / ((alpha + beta_val) ** 2 * (alpha + beta_val + 1))
        std = math.sqrt(variance) if variance > 0 else 0.01
        # Sample using normal approximation (good for alpha, beta > 1)
        sample = mean + random.gauss(0, std)
        return max(0.001, min(0.999, sample))

    @staticmethod
    def _map_action(memory_action: str) -> str:
        """Map memory action names to RL action names."""
        action_map = {
            "keep_price": "keep",
            "keep": "keep",
            "lower_10pct": "lower_10pct",
            "raise_10pct": "raise_10pct",
            "lower_price": "lower_10pct",
            "raise_price": "raise_10pct",
            "deep_discount": "lower_20pct",
            "premium_price": "raise_20pct",
        }
        return action_map.get(memory_action, "")

    @staticmethod
    def _build_reason(action: str, info: dict, total_pulls: int) -> str:
        pulls = info.get("pulls", 0)
        avg = info.get("avg_reward", 0)
        if pulls == 0:
            return f"Exploring {action} (no data yet)"
        if pulls < 3:
            return f"{action}: early exploration ({pulls} trials, avg reward {avg:.2f})"
        return f"{action}: learned from {pulls} trials (avg reward {avg:.2f}, {total_pulls} total)"

    def _record_decision(self, product_id: str, action: str,
                         current_price: float, recommended_price: float,
                         confidence: float, context: dict) -> int:
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO decisions (product_id, action, current_price, recommended_price, confidence, context, timestamp) VALUES (?,?,?,?,?,?,?)",
            (product_id, action, current_price, recommended_price, confidence,
             json.dumps(context, default=str), time.time()),
        )
        conn.commit()
        return cur.lastrowid or 0

    # == STATS =====================================================

    def get_stats(self) -> dict[str, Any]:
        conn = self._conn()
        products = conn.execute("SELECT COUNT(DISTINCT product_id) as c FROM arm_stats").fetchone()
        decisions = conn.execute("SELECT COUNT(*) as c FROM decisions").fetchone()
        outcomes = conn.execute("SELECT COUNT(*) as c FROM outcomes").fetchone()
        total_pulls = conn.execute("SELECT SUM(pulls) as s FROM arm_stats").fetchone()
        return {
            "products_tracked": products["c"] if products else 0,
            "decisions": decisions["c"] if decisions else 0,
            "outcomes": outcomes["c"] if outcomes else 0,
            "total_arm_pulls": int(total_pulls["s"] or 0) if total_pulls else 0,
        }

    def get_product_arms(self, product_id: str) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM arm_stats WHERE product_id = ? ORDER BY avg_reward DESC",
            (str(product_id),),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        if hasattr(self._local, "c") and self._local.c:
            self._local.c.close()
            self._local.c = None


_instance: PricingAgent | None = None

def get_pricing_agent() -> PricingAgent:
    global _instance
    if _instance is None:
        _instance = PricingAgent()
    return _instance
