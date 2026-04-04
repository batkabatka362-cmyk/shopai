"""ExperienceAccumulator — permanent knowledge that grows with every action.

The AI stores everything it learns:
  - Which products sell well and why
  - Which prices convert best
  - Which marketing strategies work
  - Which mistakes to avoid
  - What tools give best results
  - Customer behavior patterns

Knowledge is stored in SQLite for persistence across restarts.
The AI becomes smarter over time — it NEVER forgets.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("experience")

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "experience.db"


class ExperienceAccumulator:
    """Permanent learning storage — the AI's growing brain."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path or _DB_PATH)
        self._local = threading.local()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path, timeout=10)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_schema(self) -> None:
        self._get_conn().executescript("""
            -- What the AI has learned about products
            CREATE TABLE IF NOT EXISTS product_knowledge (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id  TEXT NOT NULL,
                store_id    TEXT DEFAULT '',
                knowledge_type TEXT NOT NULL,
                insight     TEXT NOT NULL,
                confidence  REAL DEFAULT 0.5,
                evidence    TEXT DEFAULT '{}',
                learned_at  REAL NOT NULL,
                times_confirmed INTEGER DEFAULT 1,
                last_confirmed REAL DEFAULT 0
            );

            -- Decisions and their outcomes (what worked, what didn't)
            CREATE TABLE IF NOT EXISTS decision_outcomes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_type TEXT NOT NULL,
                decision_data TEXT NOT NULL,
                outcome     TEXT NOT NULL,
                success     INTEGER DEFAULT 0,
                impact_score REAL DEFAULT 0,
                store_id    TEXT DEFAULT '',
                engine      TEXT DEFAULT '',
                created_at  REAL NOT NULL
            );

            -- Strategies that work (or don't)
            CREATE TABLE IF NOT EXISTS strategy_knowledge (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy    TEXT NOT NULL,
                category    TEXT NOT NULL,
                effectiveness REAL DEFAULT 0.5,
                conditions  TEXT DEFAULT '{}',
                evidence_count INTEGER DEFAULT 1,
                last_used   REAL DEFAULT 0,
                created_at  REAL NOT NULL,
                notes       TEXT DEFAULT ''
            );

            -- Mistakes to never repeat
            CREATE TABLE IF NOT EXISTS mistake_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                mistake_type TEXT NOT NULL,
                description TEXT NOT NULL,
                cause       TEXT DEFAULT '',
                prevention  TEXT DEFAULT '',
                severity    TEXT DEFAULT 'medium',
                store_id    TEXT DEFAULT '',
                created_at  REAL NOT NULL
            );

            -- Tool effectiveness tracking
            CREATE TABLE IF NOT EXISTS tool_knowledge (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name   TEXT NOT NULL,
                action      TEXT NOT NULL,
                success_rate REAL DEFAULT 0.5,
                avg_duration REAL DEFAULT 0,
                total_uses  INTEGER DEFAULT 0,
                best_for    TEXT DEFAULT '',
                updated_at  REAL NOT NULL
            );

            -- Market intelligence gathered
            CREATE TABLE IF NOT EXISTS market_intelligence (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                topic       TEXT NOT NULL,
                insight     TEXT NOT NULL,
                source      TEXT DEFAULT '',
                confidence  REAL DEFAULT 0.5,
                relevance   TEXT DEFAULT 'general',
                expires_at  REAL DEFAULT 0,
                created_at  REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_pk_product ON product_knowledge(product_id);
            CREATE INDEX IF NOT EXISTS idx_pk_type ON product_knowledge(knowledge_type);
            CREATE INDEX IF NOT EXISTS idx_do_type ON decision_outcomes(decision_type);
            CREATE INDEX IF NOT EXISTS idx_sk_category ON strategy_knowledge(category);
            CREATE INDEX IF NOT EXISTS idx_mi_topic ON market_intelligence(topic);
        """)
        self._get_conn().commit()

    # ── Learn About Products ─────────────────────────────────

    def learn_product(self, product_id: str, knowledge_type: str, insight: str,
                      confidence: float = 0.5, evidence: dict | None = None,
                      store_id: str = "") -> None:
        """Store a learning about a product."""
        conn = self._get_conn()
        # Check if similar knowledge exists
        existing = conn.execute(
            """SELECT id, times_confirmed, confidence FROM product_knowledge
               WHERE product_id = ? AND knowledge_type = ? AND insight = ?""",
            (product_id, knowledge_type, insight),
        ).fetchone()

        if existing:
            # Reinforce existing knowledge
            new_confidence = min(0.99, existing["confidence"] + 0.05)
            conn.execute(
                """UPDATE product_knowledge SET times_confirmed = times_confirmed + 1,
                   confidence = ?, last_confirmed = ? WHERE id = ?""",
                (new_confidence, time.time(), existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO product_knowledge
                   (product_id, store_id, knowledge_type, insight, confidence, evidence, learned_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (product_id, store_id, knowledge_type, insight, confidence,
                 json.dumps(evidence or {}), time.time()),
            )
        conn.commit()

    def get_product_knowledge(self, product_id: str) -> list[dict[str, Any]]:
        """Get everything AI knows about a product."""
        rows = self._get_conn().execute(
            "SELECT * FROM product_knowledge WHERE product_id = ? ORDER BY confidence DESC",
            (product_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Learn From Decisions ─────────────────────────────────

    def record_decision_outcome(self, decision_type: str, decision_data: dict,
                                outcome: dict, success: bool, impact_score: float = 0,
                                store_id: str = "", engine: str = "") -> None:
        """Record what happened after a decision — for future learning."""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO decision_outcomes
               (decision_type, decision_data, outcome, success, impact_score, store_id, engine, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (decision_type, json.dumps(decision_data), json.dumps(outcome),
             1 if success else 0, impact_score, store_id, engine, time.time()),
        )
        conn.commit()

        # Auto-learn strategies from outcomes
        if success and impact_score > 0.5:
            self._learn_strategy_from_outcome(decision_type, decision_data, impact_score)

    def get_similar_decisions(self, decision_type: str, limit: int = 20) -> list[dict[str, Any]]:
        """Get past decisions of similar type to inform current decision."""
        rows = self._get_conn().execute(
            """SELECT * FROM decision_outcomes WHERE decision_type = ?
               ORDER BY created_at DESC LIMIT ?""",
            (decision_type, limit),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["decision_data"] = json.loads(d["decision_data"])
            d["outcome"] = json.loads(d["outcome"])
            results.append(d)
        return results

    def get_success_rate(self, decision_type: str) -> dict[str, Any]:
        """Get success rate for a type of decision."""
        conn = self._get_conn()
        total = conn.execute(
            "SELECT COUNT(*) as c FROM decision_outcomes WHERE decision_type = ?",
            (decision_type,),
        ).fetchone()
        successes = conn.execute(
            "SELECT COUNT(*) as c FROM decision_outcomes WHERE decision_type = ? AND success = 1",
            (decision_type,),
        ).fetchone()
        t = total["c"] if total else 0
        s = successes["c"] if successes else 0
        return {
            "decision_type": decision_type,
            "total": t,
            "successes": s,
            "success_rate": round(s / t, 3) if t > 0 else 0,
        }

    # ── Strategy Knowledge ───────────────────────────────────

    def learn_strategy(self, strategy: str, category: str, effectiveness: float,
                       conditions: dict | None = None, notes: str = "") -> None:
        """Store a strategy that works (or doesn't)."""
        conn = self._get_conn()
        existing = conn.execute(
            "SELECT id, evidence_count, effectiveness FROM strategy_knowledge WHERE strategy = ? AND category = ?",
            (strategy, category),
        ).fetchone()

        if existing:
            # Weighted average of effectiveness
            old_eff = existing["effectiveness"]
            count = existing["evidence_count"]
            new_eff = (old_eff * count + effectiveness) / (count + 1)
            conn.execute(
                """UPDATE strategy_knowledge SET effectiveness = ?, evidence_count = evidence_count + 1,
                   last_used = ?, notes = ? WHERE id = ?""",
                (round(new_eff, 4), time.time(), notes, existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO strategy_knowledge
                   (strategy, category, effectiveness, conditions, last_used, created_at, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (strategy, category, effectiveness, json.dumps(conditions or {}),
                 time.time(), time.time(), notes),
            )
        conn.commit()

    def get_best_strategies(self, category: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get the most effective strategies for a category."""
        rows = self._get_conn().execute(
            """SELECT * FROM strategy_knowledge WHERE category = ?
               ORDER BY effectiveness DESC LIMIT ?""",
            (category, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def _learn_strategy_from_outcome(self, decision_type: str, decision_data: dict,
                                     impact: float) -> None:
        """Auto-extract strategies from successful outcomes."""
        strategy = f"{decision_type}: {json.dumps(decision_data, default=str)[:200]}"
        self.learn_strategy(strategy, decision_type, impact)

    # ── Mistake Tracking ─────────────────────────────────────

    def record_mistake(self, mistake_type: str, description: str,
                       cause: str = "", prevention: str = "",
                       severity: str = "medium", store_id: str = "") -> None:
        """Record a mistake so the AI never repeats it."""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO mistake_log
               (mistake_type, description, cause, prevention, severity, store_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (mistake_type, description, cause, prevention, severity, store_id, time.time()),
        )
        conn.commit()
        logger.warning("Mistake recorded [%s]: %s", mistake_type, description[:100])

    def get_mistakes(self, mistake_type: str = "", limit: int = 20) -> list[dict[str, Any]]:
        """Get past mistakes to avoid repeating them."""
        if mistake_type:
            rows = self._get_conn().execute(
                "SELECT * FROM mistake_log WHERE mistake_type = ? ORDER BY created_at DESC LIMIT ?",
                (mistake_type, limit),
            ).fetchall()
        else:
            rows = self._get_conn().execute(
                "SELECT * FROM mistake_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Tool Knowledge ───────────────────────────────────────

    def update_tool_knowledge(self, tool_name: str, action: str,
                              success_rate: float, avg_duration: float,
                              total_uses: int, best_for: str = "") -> None:
        """Update what AI knows about tool effectiveness."""
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO tool_knowledge
               (tool_name, action, success_rate, avg_duration, total_uses, best_for, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (tool_name, action, success_rate, avg_duration, total_uses, best_for, time.time()),
        )
        conn.commit()

    def get_best_tool(self, action: str) -> dict[str, Any] | None:
        """Get the best tool for a specific action based on experience."""
        row = self._get_conn().execute(
            "SELECT * FROM tool_knowledge WHERE action = ? ORDER BY success_rate DESC LIMIT 1",
            (action,),
        ).fetchone()
        return dict(row) if row else None

    # ── Market Intelligence ──────────────────────────────────

    def store_market_intel(self, topic: str, insight: str, source: str = "",
                           confidence: float = 0.5, relevance: str = "general",
                           expires_hours: int = 24) -> None:
        """Store market intelligence gathered from external sources."""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO market_intelligence
               (topic, insight, source, confidence, relevance, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (topic, insight, source, confidence, relevance,
             time.time() + (expires_hours * 3600), time.time()),
        )
        conn.commit()

    def get_market_intel(self, topic: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get relevant market intelligence (non-expired)."""
        rows = self._get_conn().execute(
            """SELECT * FROM market_intelligence
               WHERE topic LIKE ? AND (expires_at = 0 OR expires_at > ?)
               ORDER BY created_at DESC LIMIT ?""",
            (f"%{topic}%", time.time(), limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Overall Knowledge Summary ────────────────────────────

    def get_knowledge_summary(self) -> dict[str, Any]:
        """Get summary of everything AI has learned."""
        conn = self._get_conn()

        product_count = conn.execute("SELECT COUNT(*) as c FROM product_knowledge").fetchone()
        decision_count = conn.execute("SELECT COUNT(*) as c FROM decision_outcomes").fetchone()
        strategy_count = conn.execute("SELECT COUNT(*) as c FROM strategy_knowledge").fetchone()
        mistake_count = conn.execute("SELECT COUNT(*) as c FROM mistake_log").fetchone()
        tool_count = conn.execute("SELECT COUNT(*) as c FROM tool_knowledge").fetchone()
        market_count = conn.execute("SELECT COUNT(*) as c FROM market_intelligence").fetchone()

        # Overall decision success rate
        total_decisions = conn.execute("SELECT COUNT(*) as c FROM decision_outcomes").fetchone()
        successful = conn.execute("SELECT COUNT(*) as c FROM decision_outcomes WHERE success = 1").fetchone()

        return {
            "product_insights": product_count["c"] if product_count else 0,
            "decisions_recorded": decision_count["c"] if decision_count else 0,
            "strategies_learned": strategy_count["c"] if strategy_count else 0,
            "mistakes_logged": mistake_count["c"] if mistake_count else 0,
            "tools_evaluated": tool_count["c"] if tool_count else 0,
            "market_intel": market_count["c"] if market_count else 0,
            "overall_success_rate": round(
                (successful["c"] / total_decisions["c"]) if total_decisions and total_decisions["c"] > 0 else 0, 3
            ),
        }

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# Singleton
_experience: ExperienceAccumulator | None = None


def get_experience() -> ExperienceAccumulator:
    global _experience
    if _experience is None:
        _experience = ExperienceAccumulator()
    return _experience
