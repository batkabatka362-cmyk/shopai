"""IntelligentMemory — 6-layer memory system for real AI intelligence.

NOT a database. A BRAIN.

Layers:
  L0: Raw buffer (incoming data, temporary)
  L1: Filtered data (cleaned, validated)
  L2: Structured features (extracted signals)
  L3: Scored memory (evaluated 1-5, tagged)
  L4: Pattern memory (repeated observations → patterns)
  L5: Rule memory (patterns → actionable rules)
  L6: Strategy memory (rules → decision strategies)

Data flows UP through layers. Bad data doesn't get deleted — stored separately.
Memory is used by DecisionEngine BEFORE every decision.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from utils.helpers import safe_float, safe_int
from utils.logger import get_logger

logger = get_logger("brain.memory")

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "brain_memory.db"


def _v1_initial_schema(conn: sqlite3.Connection) -> None:
    """v1: Original IntelligentMemory schema (memories, patterns, rules, bad_data)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            layer       INTEGER NOT NULL,
            category    TEXT NOT NULL,
            input_data  TEXT DEFAULT '{}',
            action      TEXT DEFAULT '',
            result      TEXT DEFAULT '{}',
            score       REAL DEFAULT 3.0,
            tags        TEXT DEFAULT '[]',
            features    TEXT DEFAULT '{}',
            source      TEXT DEFAULT '',
            store_id    TEXT DEFAULT '',
            timestamp   REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS patterns (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern     TEXT NOT NULL,
            category    TEXT NOT NULL,
            frequency   INTEGER DEFAULT 1,
            avg_score   REAL DEFAULT 3.0,
            evidence    TEXT DEFAULT '[]',
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rules (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            rule        TEXT NOT NULL,
            category    TEXT NOT NULL,
            condition   TEXT NOT NULL,
            action      TEXT NOT NULL,
            confidence  REAL DEFAULT 0.5,
            uses        INTEGER DEFAULT 0,
            successes   INTEGER DEFAULT 0,
            source_pattern TEXT DEFAULT '',
            created_at  REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bad_data (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            category    TEXT NOT NULL,
            data        TEXT NOT NULL,
            reason      TEXT NOT NULL,
            score       REAL DEFAULT 1.0,
            analyzed    INTEGER DEFAULT 0,
            timestamp   REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mem_layer ON memories(layer, category);
        CREATE INDEX IF NOT EXISTS idx_mem_score ON memories(score);
        CREATE INDEX IF NOT EXISTS idx_mem_tags ON memories(tags);
        CREATE INDEX IF NOT EXISTS idx_patterns_cat ON patterns(category);
        CREATE INDEX IF NOT EXISTS idx_rules_cat ON rules(category);
    """)


def _v2_unique_pattern_rule_indexes(conn: sqlite3.Connection) -> None:
    """v2: Add UNIQUE indexes on patterns.pattern and rules.rule.

    Without these, two threads racing on the same pattern_str /
    rule text in `_detect_patterns` / `_generate_rule` could both
    pass their existence check and both INSERT — leaving duplicate
    rows that then double-count toward downstream rule activation
    and pattern frequency.

    The UNIQUE indexes also enable atomic UPSERT (INSERT ... ON
    CONFLICT(pattern) DO UPDATE) so the check-then-write race is
    eliminated entirely. Existing duplicates are deduplicated
    by keeping the highest-frequency row per pattern.
    """
    # Dedupe patterns first — keep the row with the highest frequency
    # per pattern (arbitrary tiebreak by lowest id).
    conn.executescript("""
        DELETE FROM patterns
        WHERE id NOT IN (
            SELECT MIN(id) FROM patterns
            GROUP BY pattern
            HAVING MAX(frequency) = frequency
        );
        DELETE FROM patterns
        WHERE id NOT IN (
            SELECT MIN(id) FROM patterns GROUP BY pattern
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_patterns_pattern_unique
            ON patterns(pattern);

        DELETE FROM rules
        WHERE id NOT IN (
            SELECT MIN(id) FROM rules GROUP BY rule
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_rules_rule_unique
            ON rules(rule);
    """)


_MIGRATIONS: list[tuple[int, str, Any]] = [
    (1, "initial schema", _v1_initial_schema),
    (2, "unique pattern + rule indexes", _v2_unique_pattern_rule_indexes),
]
_SCHEMA_VERSION = max(m[0] for m in _MIGRATIONS)


class MemoryRecord:
    """A single memory entry with full context."""

    __slots__ = ("id", "layer", "category", "input_data", "action", "result",
                 "score", "tags", "features", "timestamp", "source", "store_id")

    def __init__(self, layer: int, category: str, input_data: dict,
                 action: str = "", result: dict | None = None,
                 score: float = 3.0, tags: list[str] | None = None,
                 features: dict | None = None, source: str = "",
                 store_id: str = "") -> None:
        self.id = 0
        self.layer = layer
        self.category = category
        self.input_data = input_data
        self.action = action
        self.result = result or {}
        self.score = score  # 1-5
        self.tags = tags or []
        self.features = features or {}
        self.timestamp = time.time()
        self.source = source
        self.store_id = store_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "layer": self.layer, "category": self.category,
            "action": self.action, "score": self.score, "tags": self.tags,
            "features": self.features, "timestamp": self.timestamp,
            "source": self.source,
        }


class IntelligentMemory:
    """6-layer memory system — the AI's brain."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path or _DB_PATH)
        self._local = threading.local()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        # In-memory pattern cache
        self._pattern_cache: dict[str, dict] = {}
        self._rules: list[dict] = []
        # get_rules() cache: category → (generation, expires_at, rows).
        # Hot callers: strategy_planner, multi_store_brain, reasoning_chain,
        # rule_health, strategy_expander, autonomous/controller.
        self._rules_cache: dict[str, tuple[int, float, list[dict[str, Any]]]] = {}
        self._rules_cache_gen = 0
        self._rules_cache_ttl = 2.0

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "c") or self._local.c is None:
            self._local.c = sqlite3.connect(self._db_path, timeout=10)
            self._local.c.row_factory = sqlite3.Row
            self._local.c.execute("PRAGMA journal_mode=WAL")
        return self._local.c

    def _init_schema(self) -> None:
        from core.db.migrations import Migrator, register_schema
        Migrator(self._conn(), "brain_memory", _MIGRATIONS).run()
        register_schema("brain_memory", Path(self._db_path), _SCHEMA_VERSION)

    # ── L0: Raw Buffer ───────────────────────────────────────

    def ingest(self, category: str, data: dict, source: str = "",
               store_id: str = "") -> int:
        """L0: Ingest raw data. Returns memory ID."""
        score = self._evaluate_data(category, data)
        if score <= 1:
            self._store_bad_data(category, data, "Low quality score")
            return 0

        features = self._extract_features(category, data)
        tags = self._auto_tag(category, data, features)

        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO memories (layer, category, input_data, score, tags, features, source, store_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (2 if score >= 3 else 1, category, json.dumps(data, default=str),
             score, json.dumps(tags), json.dumps(features), source, store_id, time.time()),
        )
        conn.commit()

        # Only L2-tier data (score >= 3) feeds pattern
        # detection so junk ingests don't flood the table.
        # Wrapped so a pattern failure can't abort the ingest
        # caller — the store write is the data-integrity
        # guarantee; patterns are a derivative signal.
        if score >= 3:
            try:
                self._detect_patterns(category, features, score)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "observational pattern detection failed: %s", exc,
                )

        return cur.lastrowid or 0

    # ── L3: Record Decision + Result ─────────────────────────

    def record_decision(self, category: str, input_data: dict, action: str,
                        result: dict, score: float, tags: list[str] | None = None,
                        store_id: str = "") -> int:
        """L3: Record a scored decision with full context."""
        features = self._extract_features(category, input_data)
        all_tags = list(set((tags or []) + self._auto_tag(category, input_data, features)))

        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO memories (layer, category, input_data, action, result, score, tags, features, store_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (3, category, json.dumps(input_data, default=str), action,
             json.dumps(result, default=str), score, json.dumps(all_tags),
             json.dumps(features), store_id, time.time()),
        )
        conn.commit()

        # Try to detect patterns
        self._detect_patterns(category, features, score)

        return cur.lastrowid or 0

    # ── L4: Pattern Detection ────────────────────────────────

    def _detect_patterns(self, category: str, features: dict, score: float) -> None:
        """L4: Detect repeated patterns from scored memories."""
        # Build pattern key from features
        key_parts = []
        for k, v in sorted(features.items()):
            if isinstance(v, str) and v:
                key_parts.append(f"{k}={v}")
            elif isinstance(v, bool):
                key_parts.append(f"{k}={'T' if v else 'F'}")
            elif isinstance(v, (int, float)):
                bucket = "high" if v > 0.6 else "mid" if v > 0.3 else "low"
                key_parts.append(f"{k}={bucket}")

        if not key_parts:
            return

        pattern_key = f"{category}|{'|'.join(key_parts[:5])}"
        outcome = "good" if score >= 4 else "bad" if score <= 2 else "neutral"
        pattern_str = f"{pattern_key}→{outcome}"

        conn = self._conn()
        now = time.time()
        # Atomic UPSERT — prevents the check-then-write race that
        # previously let two threads both INSERT the same pattern.
        # The v2 migration added a UNIQUE index on patterns.pattern
        # so this conflict target is valid.
        conn.execute(
            """
            INSERT INTO patterns
                (pattern, category, frequency, avg_score, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?, ?)
            ON CONFLICT(pattern) DO UPDATE SET
                frequency = frequency + 1,
                avg_score = round(
                    (avg_score * frequency + excluded.avg_score) / (frequency + 1),
                    3
                ),
                updated_at = excluded.updated_at
            """,
            (pattern_str, category, score, now, now),
        )
        # Re-read so we know whether the post-update frequency hit
        # the rule-generation threshold.
        row = conn.execute(
            "SELECT frequency, avg_score FROM patterns WHERE pattern = ?",
            (pattern_str,),
        ).fetchone()
        conn.commit()
        if row and row["frequency"] >= 3:
            self._generate_rule(category, pattern_str, row["avg_score"])

    # ── L5: Rule Generation ──────────────────────────────────

    def _generate_rule(self, category: str, pattern: str, avg_score: float) -> None:
        """L5: Convert repeated pattern into actionable rule."""
        parts = pattern.split("→")
        if len(parts) != 2:
            return

        condition = parts[0]
        outcome = parts[1]

        if outcome == "good":
            action = "prefer"
            confidence = min(0.9, avg_score / 5)
        elif outcome == "bad":
            action = "avoid"
            confidence = min(0.9, (5 - avg_score) / 5)
        else:
            return

        rule_text = f"When {condition}: {action} (score: {avg_score:.1f})"

        conn = self._conn()
        # Atomic INSERT OR IGNORE — relies on the v2 UNIQUE index
        # on rules.rule to make duplicate inserts a no-op rather
        # than a check-then-write race.
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO rules
                (rule, category, condition, action, confidence,
                 source_pattern, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (rule_text, category, condition, action, confidence, pattern, time.time()),
        )
        conn.commit()
        if cur.rowcount > 0:
            # Only bump cache generation when we actually inserted —
            # this prevents needless cache invalidation churn from
            # repeated calls on already-existing rules.
            self._rules_cache_gen += 1
            logger.info("New rule: %s", rule_text)

    # ── Retrieval (CRITICAL for decisions) ───────────────────

    def retrieve_for_decision(self, category: str, context: dict,
                              limit: int = 10) -> dict[str, Any]:
        """Retrieve relevant memories for making a decision.

        Returns best cases, similar cases, failure cases, and applicable rules.
        """
        conn = self._conn()

        # Best cases (score >= 4)
        best = conn.execute(
            "SELECT * FROM memories WHERE category = ? AND score >= 4 ORDER BY score DESC, timestamp DESC LIMIT ?",
            (category, limit),
        ).fetchall()

        # Failure cases (score <= 2)
        failures = conn.execute(
            "SELECT * FROM memories WHERE category = ? AND score <= 2 ORDER BY timestamp DESC LIMIT ?",
            (category, limit),
        ).fetchall()

        # Recent cases
        recent = conn.execute(
            "SELECT * FROM memories WHERE category = ? AND layer >= 3 ORDER BY timestamp DESC LIMIT ?",
            (category, limit),
        ).fetchall()

        # Applicable rules
        rules = conn.execute(
            "SELECT * FROM rules WHERE category = ? ORDER BY confidence DESC LIMIT 10",
            (category,),
        ).fetchall()

        # Patterns
        patterns = conn.execute(
            "SELECT * FROM patterns WHERE category = ? AND frequency >= 2 ORDER BY frequency DESC LIMIT 10",
            (category,),
        ).fetchall()

        return {
            "best_cases": [self._row_to_dict(r) for r in best],
            "failures": [self._row_to_dict(r) for r in failures],
            "recent": [self._row_to_dict(r) for r in recent],
            "rules": [dict(r) for r in rules],
            "patterns": [dict(r) for r in patterns],
            "total_memories": self._count(category),
        }

    def get_rules(self, category: str = "") -> list[dict[str, Any]]:
        now = time.time()
        cached = self._rules_cache.get(category)
        if cached:
            gen, expires, result = cached
            if gen == self._rules_cache_gen and now < expires:
                # Return a fresh copy so callers can mutate the
                # returned dicts without poisoning the cache. The
                # previous version handed out a shared list whose
                # entries any caller could mutate, leaking changes
                # into every subsequent reader of the same cache
                # entry.
                return [dict(r) for r in result]

        if category:
            rows = self._conn().execute(
                "SELECT * FROM rules WHERE category = ? ORDER BY confidence DESC", (category,),
            ).fetchall()
        else:
            rows = self._conn().execute("SELECT * FROM rules ORDER BY confidence DESC").fetchall()
        result = [dict(r) for r in rows]
        self._rules_cache[category] = (
            self._rules_cache_gen, now + self._rules_cache_ttl, result,
        )
        # Same defensive copy on the cold path so the cached object
        # and the returned object can never alias.
        return [dict(r) for r in result]

    # ── Bad Data Storage ─────────────────────────────────────

    def _store_bad_data(self, category: str, data: dict, reason: str) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO bad_data (category, data, reason, score, timestamp) VALUES (?,?,?,?,?)",
            (category, json.dumps(data, default=str), reason, 1.0, time.time()),
        )
        conn.commit()

    def get_bad_data(self, category: str = "", limit: int = 20) -> list[dict]:
        if category:
            rows = self._conn().execute(
                "SELECT * FROM bad_data WHERE category = ? ORDER BY timestamp DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT * FROM bad_data ORDER BY timestamp DESC LIMIT ?", (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Feature Extraction ───────────────────────────────────

    @staticmethod
    def _extract_features(category: str, data: dict) -> dict[str, Any]:
        """Extract meaningful features from raw data."""
        features: dict[str, Any] = {}

        if category in ("pricing", "product"):
            features["has_price"] = bool(data.get("price"))
            features["has_cost"] = bool(data.get("cost"))
            # Use safe_float so a string like "$10.99" or "" doesn't
            # crash the entire feature extractor mid-cycle.
            # Previously `float(data.get("price", 0) or 0)` raised
            # ValueError on any non-numeric string and propagated
            # all the way out of `record_decision` / `ingest`.
            price = safe_float(data.get("price"))
            cost = safe_float(data.get("cost"))
            if price > 0 and cost > 0:
                from utils.finance import margin as _margin
                features["margin"] = _margin(price, cost, precision=2)
                features["price_tier"] = "premium" if price > 40 else "mid" if price > 20 else "budget"
            features["has_images"] = bool(data.get("image_url") or data.get("images"))
            features["category"] = data.get("category", data.get("product_type", ""))

        elif category in ("customer", "segment"):
            features["order_count"] = safe_int(
                data.get("orders", data.get("orders_count", 0))
            )
            features["is_repeat"] = features["order_count"] > 1
            features["total_spent"] = safe_float(data.get("total_spent"))
            features["is_high_value"] = features["total_spent"] > 100

        elif category == "decision":
            features["decision_type"] = data.get("type", "")
            features["confidence"] = data.get("confidence", 0)

        return features

    @staticmethod
    def _evaluate_data(category: str, data: dict) -> float:
        """Score data quality 1-5."""
        score = 3.0
        if not data:
            return 1.0
        if isinstance(data, dict):
            # More fields = higher quality
            non_empty = sum(1 for v in data.values() if v)
            if non_empty > 5:
                score += 0.5
            if non_empty < 2:
                score -= 1.0
            # Has key fields
            if data.get("price") or data.get("total"):
                score += 0.5
            if data.get("cost") or data.get("cogs"):
                score += 0.5
        return max(1.0, min(5.0, score))

    @staticmethod
    def _auto_tag(category: str, data: dict, features: dict) -> list[str]:
        """Auto-generate tags from data."""
        tags = [category]
        if features.get("margin"):
            m = features["margin"]
            tags.append("high_margin" if m > 0.6 else "mid_margin" if m > 0.3 else "low_margin")
        if features.get("price_tier"):
            tags.append(features["price_tier"])
        if features.get("is_repeat"):
            tags.append("repeat_buyer")
        if features.get("is_high_value"):
            tags.append("high_value")
        return tags

    # ── Stats ────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        conn = self._conn()
        layers = conn.execute("SELECT layer, COUNT(*) as c FROM memories GROUP BY layer").fetchall()
        categories = conn.execute("SELECT category, COUNT(*) as c FROM memories GROUP BY category").fetchall()
        patterns = conn.execute("SELECT COUNT(*) as c FROM patterns").fetchone()
        rules = conn.execute("SELECT COUNT(*) as c FROM rules").fetchone()
        bad = conn.execute("SELECT COUNT(*) as c FROM bad_data").fetchone()

        return {
            "total_memories": sum(r["c"] for r in layers),
            "by_layer": {f"L{r['layer']}": r["c"] for r in layers},
            "by_category": {r["category"]: r["c"] for r in categories},
            "patterns": patterns["c"] if patterns else 0,
            "rules": rules["c"] if rules else 0,
            "bad_data": bad["c"] if bad else 0,
        }

    def _count(self, category: str) -> int:
        r = self._conn().execute("SELECT COUNT(*) as c FROM memories WHERE category = ?", (category,)).fetchone()
        return r["c"] if r else 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        for k in ("input_data", "result", "tags", "features"):
            if k in d and isinstance(d[k], str):
                try:
                    d[k] = json.loads(d[k])
                except json.JSONDecodeError:
                    pass
        return d

    def close(self) -> None:
        if hasattr(self._local, "c") and self._local.c:
            self._local.c.close()
            self._local.c = None


_instance: IntelligentMemory | None = None

def get_brain_memory() -> IntelligentMemory:
    global _instance
    if _instance is None:
        _instance = IntelligentMemory()
    return _instance
