"""MemoryIntelligence - 4-level memory hierarchy for AI intelligence.

NOT a feature. The AI brain core.

4 Levels:
  L0: Event   - raw observations with features+action+result+score
  L1: Pattern - repeated observations grouped into patterns  
  L2: Rule    - patterns promoted to actionable rules
  L3: Strategy - rules combined into decision strategies

4 Types:
  working    - current cycle context (ephemeral)
  episodic   - specific decision memories (permanent)
  semantic   - general knowledge/facts (permanent)
  procedural - how-to rules and strategies (permanent)

Creation Pipeline:
  Execution -> Data capture -> Feature transform -> Result attach -> Score -> Store

Retrieval:
  similarity search + tag filter + score filter + recency boost

Evolution:
  Event -> Pattern (3+ similar) -> Rule (5+ evidence) -> Strategy (10+ uses, >70%% success)
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("memory.intelligence")

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "memory_intelligence.db"

MEMORY_LEVELS = {"event": 0, "pattern": 1, "rule": 2, "strategy": 3}
MEMORY_TYPES = ["working", "episodic", "semantic", "procedural"]
PROMOTION_THRESHOLDS = {"event_to_pattern": 3, "pattern_to_rule": 5, "rule_to_strategy": 10}
SCORE_THRESHOLDS = {"useless": 1.0, "weak": 2.0, "neutral": 3.0, "useful": 4.0, "critical": 5.0}


class MemoryEntry:
    """A single memory with full context."""

    __slots__ = (
        "id", "level", "memory_type", "category", "content", "features",
        "action", "result", "score", "confidence", "tags", "evidence_count",
        "use_count", "success_count", "source_ids", "parent_id",
        "timestamp", "last_used", "last_updated",
    )

    def __init__(self, level: int = 0, memory_type: str = "episodic",
                 category: str = "", content: dict | None = None,
                 features: dict | None = None, action: str = "",
                 result: dict | None = None, score: float = 3.0,
                 tags: list[str] | None = None, source_ids: list[int] | None = None,
                 parent_id: int = 0) -> None:
        self.id = 0
        self.level = level
        self.memory_type = memory_type
        self.category = category
        self.content = content or {}
        self.features = features or {}
        self.action = action
        self.result = result or {}
        self.score = score
        self.confidence = score / 5.0
        self.tags = tags or []
        self.evidence_count = 1
        self.use_count = 0
        self.success_count = 0
        self.source_ids = source_ids or []
        self.parent_id = parent_id
        self.timestamp = time.time()
        self.last_used = 0.0
        self.last_updated = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "level": self.level, "memory_type": self.memory_type,
            "category": self.category, "score": self.score, "confidence": self.confidence,
            "tags": self.tags, "evidence_count": self.evidence_count,
            "use_count": self.use_count, "success_count": self.success_count,
            "timestamp": self.timestamp,
        }


class MemoryIntelligence:
    """4-level memory hierarchy - the AI brain core."""

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
        self._conn().executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                level           INTEGER NOT NULL DEFAULT 0,
                memory_type     TEXT NOT NULL DEFAULT 'episodic',
                category        TEXT NOT NULL,
                content         TEXT DEFAULT '{}',
                features        TEXT DEFAULT '{}',
                action          TEXT DEFAULT '',
                result          TEXT DEFAULT '{}',
                score           REAL DEFAULT 3.0,
                confidence      REAL DEFAULT 0.5,
                tags            TEXT DEFAULT '[]',
                evidence_count  INTEGER DEFAULT 1,
                use_count       INTEGER DEFAULT 0,
                success_count   INTEGER DEFAULT 0,
                source_ids      TEXT DEFAULT '[]',
                parent_id       INTEGER DEFAULT 0,
                timestamp       REAL NOT NULL,
                last_used       REAL DEFAULT 0.0,
                last_updated    REAL DEFAULT 0.0
            );
            CREATE TABLE IF NOT EXISTS promotions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id   INTEGER NOT NULL,
                target_id   INTEGER NOT NULL,
                from_level  INTEGER NOT NULL,
                to_level    INTEGER NOT NULL,
                reason      TEXT DEFAULT '',
                timestamp   REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta_memory (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id   INTEGER NOT NULL,
                event       TEXT NOT NULL,
                outcome     TEXT DEFAULT '',
                timestamp   REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS failure_analysis (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                failure_data TEXT DEFAULT '{}',
                root_cause  TEXT DEFAULT '',
                pattern_id  INTEGER DEFAULT 0,
                rule_id     INTEGER DEFAULT 0,
                category    TEXT NOT NULL,
                severity    TEXT DEFAULT 'medium',
                resolved    INTEGER DEFAULT 0,
                timestamp   REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mi_level ON memories(level);
            CREATE INDEX IF NOT EXISTS idx_mi_type ON memories(memory_type);
            CREATE INDEX IF NOT EXISTS idx_mi_cat ON memories(category);
            CREATE INDEX IF NOT EXISTS idx_mi_score ON memories(score);
            CREATE INDEX IF NOT EXISTS idx_mi_tags ON memories(tags);
            CREATE INDEX IF NOT EXISTS idx_mi_parent ON memories(parent_id);
            CREATE INDEX IF NOT EXISTS idx_mi_ts ON memories(timestamp);
            CREATE INDEX IF NOT EXISTS idx_meta_mid ON meta_memory(memory_id);
            CREATE INDEX IF NOT EXISTS idx_fa_cat ON failure_analysis(category);
        """)
        self._conn().commit()


    # == CREATION - data enters memory ============================

    def create(self, category: str, content: dict, action: str = "",
               result: dict | None = None, score: float = 3.0,
               memory_type: str = "episodic", tags: list[str] | None = None,
               source_ids: list[int] | None = None,
               features: dict | None = None) -> int:
        """Create a new memory. Every memory MUST have features+score.

        Args:
            category: Domain (product, marketing, pricing, etc.)
            content: The actual data (NOT raw - must be meaningful)
            action: What action was taken
            result: What happened after
            score: Quality/usefulness 1-5
            memory_type: working/episodic/semantic/procedural
            tags: For retrieval
            source_ids: Parent memory IDs (for promoted memories)
            features: Extracted signals (auto-extracted if not provided)

        Returns:
            Memory ID (0 if rejected)
        """
        if not category:
            return 0
        score = max(1.0, min(5.0, score))

        if not features:
            features = self._extract_features(category, content)

        auto_tags = self._auto_tag(category, content, features, score)
        all_tags = list(set((tags or []) + auto_tags))
        confidence = score / 5.0

        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO memories (level, memory_type, category, content, features,
               action, result, score, confidence, tags, source_ids, timestamp, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (0, memory_type, category, json.dumps(content, default=str),
             json.dumps(features, default=str), action,
             json.dumps(result or {}, default=str), score, confidence,
             json.dumps(all_tags), json.dumps(source_ids or []),
             time.time(), time.time()),
        )
        conn.commit()
        mid = cur.lastrowid or 0

        # Check if this triggers a promotion
        self._check_promotion(category)

        return mid

    def create_from_decision(self, category: str, input_data: dict,
                             action: str, result: dict, score: float,
                             tags: list[str] | None = None) -> int:
        """Create memory from a decision outcome - the most important type."""
        features = self._extract_features(category, input_data)
        features["decision_action"] = action
        if result:
            features["had_result"] = True
            features["result_positive"] = score >= 3.0

        all_tags = list(set((tags or []) + ["decision", category, action]))
        if score >= 4:
            all_tags.append("success")
        elif score <= 2:
            all_tags.append("failure")

        # Credit rules if this decision scored well
        if score >= 3.5:
            self.record_rule_success(category, score)

        return self.create(
            category=category, content=input_data, action=action,
            result=result, score=score, memory_type="episodic",
            tags=all_tags, features=features,
        )


    # == RETRIEVAL - get memories for decisions ====================

    def retrieve(self, category: str, min_score: float = 0.0,
                 tags: list[str] | None = None, limit: int = 20,
                 memory_type: str | None = None,
                 level: int | None = None) -> list[dict[str, Any]]:
        """Retrieve memories with scoring: 70%% score + 30%% recency."""
        conn = self._conn()
        sql = "SELECT * FROM memories WHERE category = ?"
        params: list[Any] = [category]

        if min_score > 0:
            sql += " AND score >= ?"
            params.append(min_score)
        if memory_type:
            sql += " AND memory_type = ?"
            params.append(memory_type)
        if level is not None:
            sql += " AND level = ?"
            params.append(level)

        sql += " ORDER BY score DESC, timestamp DESC LIMIT ?"
        params.append(limit * 2)  # Fetch extra for reranking

        rows = conn.execute(sql, params).fetchall()
        results = [self._row_to_dict(r) for r in rows]

        # Tag filter
        if tags:
            tag_set = set(tags)
            results = [r for r in results
                       if tag_set.intersection(set(r.get("tags", [])))]

        # Recency boost: final_score = score * 0.7 + recency * 0.3
        now = time.time()
        seven_days = 7 * 86400
        for r in results:
            age = now - r.get("timestamp", now)
            recency = max(0.0, 1.0 - age / seven_days)
            r["_final_score"] = r.get("score", 3.0) * 0.7 + recency * 5.0 * 0.3

        results.sort(key=lambda x: x.get("_final_score", 0), reverse=True)
        results = results[:limit]

        # Record usage
        ids = [r["id"] for r in results if r.get("id")]
        if ids:
            self._record_use(ids)

        return results

    def retrieve_for_decision(self, category: str,
                              context: dict | None = None) -> dict[str, Any]:
        """Build full decision context - best, patterns, rules, strategies, failures."""
        conn = self._conn()

        best = conn.execute(
            "SELECT * FROM memories WHERE category = ? AND level = 0 AND score >= 4 ORDER BY score DESC, timestamp DESC LIMIT 10",
            (category,),
        ).fetchall()

        patterns = conn.execute(
            "SELECT * FROM memories WHERE category = ? AND level = 1 ORDER BY evidence_count DESC, score DESC LIMIT 10",
            (category,),
        ).fetchall()

        rules = conn.execute(
            "SELECT * FROM memories WHERE category = ? AND level = 2 ORDER BY confidence DESC, use_count DESC LIMIT 10",
            (category,),
        ).fetchall()

        strategies = conn.execute(
            "SELECT * FROM memories WHERE category = ? AND level = 3 ORDER BY confidence DESC LIMIT 5",
            (category,),
        ).fetchall()

        failures = conn.execute(
            "SELECT * FROM memories WHERE category = ? AND score <= 2 ORDER BY timestamp DESC LIMIT 10",
            (category,),
        ).fetchall()

        total = conn.execute(
            "SELECT COUNT(*) as c FROM memories WHERE category = ?", (category,),
        ).fetchone()

        # Record usage for returned memories
        all_ids = []
        for group in (best, patterns, rules, strategies, failures):
            all_ids.extend(r["id"] for r in group)
        if all_ids:
            self._record_use(all_ids)

        return {
            "best_events": [self._row_to_dict(r) for r in best],
            "patterns": [self._row_to_dict(r) for r in patterns],
            "rules": [self._row_to_dict(r) for r in rules],
            "strategies": [self._row_to_dict(r) for r in strategies],
            "failures": [self._row_to_dict(r) for r in failures],
            "total_memories": total["c"] if total else 0,
        }


    # == SCORING - update memory scores ============================

    def update_score(self, memory_id: int, new_score: float,
                     reason: str = "") -> None:
        """Update a memory's score based on new evidence."""
        new_score = max(1.0, min(5.0, new_score))
        conn = self._conn()
        conn.execute(
            "UPDATE memories SET score = ?, confidence = ?, last_updated = ? WHERE id = ?",
            (new_score, new_score / 5.0, time.time(), memory_id),
        )
        if new_score >= 4:
            conn.execute(
                "UPDATE memories SET success_count = success_count + 1 WHERE id = ?",
                (memory_id,),
            )
        conn.commit()
        # Meta tracking
        conn.execute(
            "INSERT INTO meta_memory (memory_id, event, outcome, timestamp) VALUES (?,?,?,?)",
            (memory_id, "score_update", f"{new_score:.1f}: {reason}", time.time()),
        )
        conn.commit()

    # == PROMOTION - events -> patterns -> rules -> strategies =====

    def _check_promotion(self, category: str) -> None:
        """Check if any memories should be promoted to a higher level."""
        self._promote_events_to_pattern(category)
        self._promote_patterns_to_rules(category)
        self._promote_rules_to_strategies(category)

    def _promote_events_to_pattern(self, category: str) -> None:
        """3+ similar high-scoring events -> 1 pattern."""
        conn = self._conn()
        threshold = PROMOTION_THRESHOLDS["event_to_pattern"]

        events = conn.execute(
            "SELECT * FROM memories WHERE category = ? AND level = 0 AND score >= 2.0 ORDER BY timestamp DESC LIMIT 100",
            (category,),
        ).fetchall()

        if len(events) < threshold:
            return

        # Group by feature similarity (coarse: top 2 features for broader patterns)
        groups: dict[str, list] = {}
        for e in events:
            features = json.loads(e["features"]) if isinstance(e["features"], str) else e["features"]
            # Build grouping key from top 2 non-trivial features
            key_parts = []
            for k, v in sorted(features.items()):
                if len(key_parts) >= 2:
                    break
                if isinstance(v, bool):
                    key_parts.append(f"{k}={'T' if v else 'F'}")
                elif isinstance(v, str) and v:
                    key_parts.append(f"{k}={v[:15]}")
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    bucket = "high" if v > 0.5 else "low"
                    key_parts.append(f"{k}={bucket}")
            group_key = "|".join(key_parts) if key_parts else "default"

            # Also group by action for decision memories
            action = e["action"] if e["action"] else ""
            if action and action not in ("failure",):
                group_key = f"{action}|{group_key}"

            groups.setdefault(group_key, []).append(e)

        for group_key, group_events in groups.items():
            if len(group_events) < threshold:
                continue

            # Check if pattern already exists
            existing = conn.execute(
                "SELECT id FROM memories WHERE category = ? AND level = 1 AND action = ?",
                (category, f"pattern:{group_key}"),
            ).fetchone()
            if existing:
                # Update evidence count
                conn.execute(
                    "UPDATE memories SET evidence_count = ?, last_updated = ? WHERE id = ?",
                    (len(group_events), time.time(), existing["id"]),
                )
                conn.commit()
                continue

            # Create pattern
            avg_score = sum(e["score"] for e in group_events) / len(group_events)
            event_ids = [e["id"] for e in group_events]
            pattern_content = {
                "group_key": group_key,
                "event_count": len(group_events),
                "avg_score": round(avg_score, 2),
                "observation": f"Pattern in {category}: {group_key} (seen {len(group_events)} times, avg score {avg_score:.1f})",
            }

            cur = conn.execute(
                """INSERT INTO memories (level, memory_type, category, content, features,
                   action, score, confidence, tags, evidence_count, source_ids, timestamp, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (1, "semantic", category, json.dumps(pattern_content),
                 json.dumps({"group_key": group_key}), f"pattern:{group_key}",
                 avg_score, avg_score / 5.0, json.dumps([category, "pattern", group_key]),
                 len(group_events), json.dumps(event_ids), time.time(), time.time()),
            )
            conn.commit()
            target_id = cur.lastrowid or 0

            # Record promotion
            for eid in event_ids:
                self._record_promotion(eid, target_id, 0, 1, f"pattern:{group_key}")

            logger.info("Pattern detected [%s]: %s (%d events, score %.1f)",
                        category, group_key, len(group_events), avg_score)


    def _promote_patterns_to_rules(self, category: str) -> None:
        """Patterns with enough evidence -> rules."""
        conn = self._conn()
        threshold = PROMOTION_THRESHOLDS["pattern_to_rule"]

        patterns = conn.execute(
            "SELECT * FROM memories WHERE category = ? AND level = 1 AND evidence_count >= ?",
            (category, threshold),
        ).fetchall()

        for p in patterns:
            # Check if rule already exists for this pattern
            existing = conn.execute(
                "SELECT id FROM memories WHERE category = ? AND level = 2 AND parent_id = ?",
                (category, p["id"]),
            ).fetchone()
            if existing:
                continue

            content = json.loads(p["content"]) if isinstance(p["content"], str) else p["content"]
            group_key = content.get("group_key", p["action"] if p["action"] else "")
            avg_score = content.get("avg_score", p["score"])

            if avg_score >= 3.5:
                rule_action = "prefer"
                confidence = min(0.9, avg_score / 5.0)
            elif avg_score <= 2.5:
                rule_action = "avoid"
                confidence = min(0.9, (5.0 - avg_score) / 5.0)
            else:
                continue  # Neutral patterns don't become rules

            rule_text = f"When {group_key}: {rule_action} (evidence: {p['evidence_count']}, score: {avg_score:.1f})"
            rule_content = {
                "rule": rule_text,
                "condition": group_key,
                "recommended_action": rule_action,
                "evidence_count": p["evidence_count"],
                "avg_score": avg_score,
            }

            cur = conn.execute(
                """INSERT INTO memories (level, memory_type, category, content, features,
                   action, score, confidence, tags, evidence_count, parent_id,
                   source_ids, timestamp, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (2, "procedural", category, json.dumps(rule_content),
                 json.dumps({"condition": group_key, "action": rule_action}),
                 rule_action, avg_score, confidence,
                 json.dumps([category, "rule", rule_action]),
                 p["evidence_count"], p["id"], json.dumps([p["id"]]),
                 time.time(), time.time()),
            )
            conn.commit()
            target_id = cur.lastrowid or 0
            self._record_promotion(p["id"], target_id, 1, 2, f"rule:{rule_action}")
            logger.info("Rule generated [%s]: %s", category, rule_text)

    def _promote_rules_to_strategies(self, category: str) -> None:
        """High-performing rules -> strategies."""
        conn = self._conn()
        threshold = PROMOTION_THRESHOLDS["rule_to_strategy"]

        rules = conn.execute(
            "SELECT * FROM memories WHERE category = ? AND level = 2 AND use_count >= ?",
            (category, threshold),
        ).fetchall()

        qualifying = []
        for r in rules:
            if r["use_count"] > 0:
                success_rate = r["success_count"] / r["use_count"]
                if success_rate >= 0.7:
                    qualifying.append(r)

        if not qualifying:
            return  # Need at least one qualifying rule

        # Check if strategy already exists
        existing = conn.execute(
            "SELECT id FROM memories WHERE category = ? AND level = 3",
            (category,),
        ).fetchone()
        if existing:
            # Update existing strategy with new rules
            conn.execute(
                "UPDATE memories SET evidence_count = ?, last_updated = ? WHERE id = ?",
                (len(qualifying), time.time(), existing["id"]),
            )
            conn.commit()
            return

        # Create strategy from qualifying rules
        rule_ids = [r["id"] for r in qualifying]
        rule_summaries = []
        for r in qualifying:
            rc = json.loads(r["content"]) if isinstance(r["content"], str) else r["content"]
            rule_summaries.append(rc.get("rule", str(rc)[:80]))

        avg_score = sum(r["score"] for r in qualifying) / len(qualifying)
        strategy_content = {
            "strategy": f"Strategy for {category}: {len(qualifying)} proven rules",
            "rules": rule_summaries,
            "rule_count": len(qualifying),
            "avg_confidence": round(avg_score / 5.0, 2),
        }

        cur = conn.execute(
            """INSERT INTO memories (level, memory_type, category, content, features,
               action, score, confidence, tags, evidence_count, source_ids,
               timestamp, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (3, "procedural", category, json.dumps(strategy_content),
             json.dumps({"rule_count": len(qualifying)}),
             "strategy", avg_score, avg_score / 5.0,
             json.dumps([category, "strategy"]),
             len(qualifying), json.dumps(rule_ids), time.time(), time.time()),
        )
        conn.commit()
        target_id = cur.lastrowid or 0
        for rid in rule_ids:
            self._record_promotion(rid, target_id, 2, 3, "strategy")
        logger.info("Strategy created [%s]: %d rules combined", category, len(qualifying))


    # == FAILURE INTELLIGENCE - failures are gold ==================

    def record_failure(self, category: str, failure_data: dict,
                       root_cause: str = "", severity: str = "medium") -> int:
        """Record a failure for learning. Bad memory = gold."""
        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO failure_analysis (failure_data, root_cause, category, severity, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (json.dumps(failure_data, default=str), root_cause, category, severity, time.time()),
        )
        conn.commit()
        failure_id = cur.lastrowid or 0

        # Create low-score event memory
        self.create(
            category=category,
            content={"failure": failure_data, "root_cause": root_cause},
            action="failure",
            result={"severity": severity},
            score=1.5,
            memory_type="episodic",
            tags=["failure", severity, category],
        )

        # Check for repeated failures -> auto-generate avoidance rule
        similar = conn.execute(
            "SELECT COUNT(*) as c FROM failure_analysis WHERE category = ? AND root_cause = ? AND root_cause != ''",
            (category, root_cause),
        ).fetchone()

        if similar and similar["c"] >= 3 and root_cause:
            # Generate avoidance rule
            rule_content = {
                "rule": f"AVOID: {root_cause} (caused {similar['c']} failures in {category})",
                "condition": root_cause,
                "recommended_action": "avoid",
                "failure_count": similar["c"],
            }
            conn.execute(
                """INSERT INTO memories (level, memory_type, category, content, features,
                   action, score, confidence, tags, evidence_count, timestamp, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (2, "procedural", category, json.dumps(rule_content),
                 json.dumps({"root_cause": root_cause, "failure_count": similar["c"]}),
                 "avoid", 2.0, 0.8,
                 json.dumps([category, "rule", "avoid", "from_failure"]),
                 similar["c"], time.time(), time.time()),
            )
            conn.commit()
            logger.info("Avoidance rule from failures [%s]: %s (%d failures)",
                        category, root_cause, similar["c"])

        return failure_id

    def analyze_failures(self, category: str = "",
                         limit: int = 20) -> list[dict[str, Any]]:
        """Analyze failure patterns."""
        conn = self._conn()
        if category:
            rows = conn.execute(
                """SELECT root_cause, COUNT(*) as count, category,
                   GROUP_CONCAT(severity) as severities
                   FROM failure_analysis WHERE category = ? AND root_cause != ''
                   GROUP BY root_cause ORDER BY count DESC LIMIT ?""",
                (category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT root_cause, COUNT(*) as count, category,
                   GROUP_CONCAT(severity) as severities
                   FROM failure_analysis WHERE root_cause != ''
                   GROUP BY root_cause ORDER BY count DESC LIMIT ?""",
                (limit,),
            ).fetchall()

        results = []
        for r in rows:
            # Check if a rule was generated
            has_rule = conn.execute(
                "SELECT id FROM memories WHERE level = 2 AND category = ? AND action = 'avoid' AND content LIKE ?",
                (r["category"], f"%{r['root_cause'][:40]}%"),
            ).fetchone()
            results.append({
                "root_cause": r["root_cause"],
                "count": r["count"],
                "category": r["category"],
                "has_rule": bool(has_rule),
            })
        return results


    # == META MEMORY - track which memories are useful =============

    def _record_use(self, memory_ids: list[int]) -> None:
        """Record that memories were used (for meta tracking)."""
        conn = self._conn()
        now = time.time()
        for mid in memory_ids:
            conn.execute(
                "UPDATE memories SET use_count = use_count + 1, last_used = ? WHERE id = ?",
                (now, mid),
            )
            conn.execute(
                "INSERT INTO meta_memory (memory_id, event, timestamp) VALUES (?, ?, ?)",
                (mid, "used", now),
            )
        conn.commit()

    def record_rule_success(self, category: str, score: float) -> int:
        """Record success for rules that were used in a decision.

        When a decision scores well (>= 3.5), credit the rules that were
        used (retrieved) for that category. This is how rules earn
        success_count for strategy promotion.
        """
        if score < 3.5:
            return 0
        conn = self._conn()
        rules = conn.execute(
            "SELECT id FROM memories WHERE level = 2 AND category = ? AND use_count > 0",
            (category,),
        ).fetchall()
        updated = 0
        for r in rules:
            conn.execute(
                "UPDATE memories SET success_count = success_count + 1, last_updated = ? WHERE id = ?",
                (time.time(), r["id"]),
            )
            updated += 1
        if updated:
            conn.commit()
            # Check if any rules now qualify for strategy promotion
            self._promote_rules_to_strategies(category)
        return updated

    def _record_promotion(self, source_id: int, target_id: int,
                          from_level: int, to_level: int, reason: str) -> None:
        """Record a level promotion."""
        self._conn().execute(
            "INSERT INTO promotions (source_id, target_id, from_level, to_level, reason, timestamp) VALUES (?,?,?,?,?,?)",
            (source_id, target_id, from_level, to_level, reason, time.time()),
        )
        self._conn().commit()

    def get_meta_stats(self) -> dict[str, Any]:
        """Get meta-memory statistics."""
        conn = self._conn()
        most_used = conn.execute(
            "SELECT id, category, action, use_count, score FROM memories ORDER BY use_count DESC LIMIT 10",
        ).fetchall()
        never_used = conn.execute(
            "SELECT COUNT(*) as c FROM memories WHERE use_count = 0 AND timestamp < ?",
            (time.time() - 86400,),
        ).fetchone()
        promotions = conn.execute("SELECT COUNT(*) as c FROM promotions").fetchone()
        level_dist = conn.execute(
            "SELECT level, COUNT(*) as c FROM memories GROUP BY level",
        ).fetchall()

        return {
            "most_used": [{"id": r["id"], "category": r["category"],
                           "action": r["action"], "use_count": r["use_count"],
                           "score": r["score"]} for r in most_used],
            "never_used_count": never_used["c"] if never_used else 0,
            "total_promotions": promotions["c"] if promotions else 0,
            "level_distribution": {
                ["event", "pattern", "rule", "strategy"][r["level"]]: r["c"]
                for r in level_dist if r["level"] < 4
            },
        }

    def prune_unused(self, days: int = 30) -> int:
        """Prune unused event-level memories. Never prune patterns/rules/strategies."""
        cutoff = time.time() - (days * 86400)
        conn = self._conn()
        cur = conn.execute(
            "DELETE FROM memories WHERE level = 0 AND use_count = 0 AND timestamp < ?",
            (cutoff,),
        )
        conn.commit()
        pruned = cur.rowcount
        if pruned:
            logger.info("Pruned %d unused event memories (older than %d days)", pruned, days)
        return pruned


    # == FEATURE EXTRACTION ========================================

    @staticmethod
    def _extract_features(category: str, content: dict) -> dict[str, Any]:
        """Extract meaningful features from content."""
        features: dict[str, Any] = {}
        if not isinstance(content, dict):
            return features

        if category in ("pricing", "product"):
            price = float(content.get("price", 0) or 0)
            cost = float(content.get("cost", 0) or 0)
            features["has_price"] = price > 0
            features["has_cost"] = cost > 0
            if price > 0 and cost > 0:
                features["margin"] = round((price - cost) / price, 2)
                features["price_tier"] = "premium" if price > 50 else "mid" if price > 20 else "budget"
            features["has_images"] = bool(
                content.get("images") or content.get("image") or content.get("image_url")
            )
            features["category"] = content.get("category", content.get("product_type", ""))

        elif category in ("customer", "segment"):
            features["order_count"] = int(content.get("orders_count", content.get("orders", 0)) or 0)
            features["is_repeat"] = features["order_count"] > 1
            features["total_spent"] = float(content.get("total_spent", 0) or 0)
            features["is_high_value"] = features["total_spent"] > 100

        elif category == "marketing":
            features["channel"] = content.get("channel", "")
            spend = float(content.get("spend", 0) or 0)
            revenue = float(content.get("revenue", 0) or 0)
            if spend > 0:
                features["roas"] = round(revenue / spend, 2)
            features["has_conversions"] = int(content.get("conversions", 0) or 0) > 0

        elif category == "decision":
            features["confidence"] = float(content.get("confidence", content.get("score", 0)) or 0)
            features["memory_used"] = bool(content.get("memory_used"))
            features["options_count"] = int(content.get("options_considered", content.get("options_count", 0)) or 0)

        else:
            # Generic: extract all numeric and boolean fields
            for k, v in content.items():
                if isinstance(v, bool):
                    features[k] = v
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    features[k] = v
                elif isinstance(v, str) and v and len(v) < 50:
                    features[k] = v

        return features

    # == AUTO TAGGING ==============================================

    @staticmethod
    def _auto_tag(category: str, content: dict, features: dict,
                  score: float) -> list[str]:
        """Generate tags for retrieval."""
        tags = [category]

        # Score-based tags
        if score >= 4.5:
            tags.append("excellent")
        elif score >= 3.5:
            tags.append("good")
        elif score >= 2.5:
            tags.append("neutral")
        else:
            tags.append("poor")

        # Domain-specific
        if category in ("product", "pricing"):
            margin = features.get("margin", 0)
            if isinstance(margin, (int, float)):
                if margin > 0.6:
                    tags.append("high_margin")
                elif margin > 0.3:
                    tags.append("mid_margin")
                elif margin > 0:
                    tags.append("low_margin")
            tier = features.get("price_tier", "")
            if tier:
                tags.append(tier)

        elif category == "marketing":
            channel = features.get("channel", "")
            if channel:
                tags.append(f"ch:{channel}")
            roas = features.get("roas", 0)
            if isinstance(roas, (int, float)) and roas > 1:
                tags.append("profitable")

        elif category in ("customer", "segment"):
            if features.get("is_repeat"):
                tags.append("repeat_buyer")
            if features.get("is_high_value"):
                tags.append("high_value")

        return tags


    # == CONVENIENCE GETTERS =======================================

    def get_rules(self, category: str = "") -> list[dict[str, Any]]:
        """Get all level-2 rule memories."""
        conn = self._conn()
        if category:
            rows = conn.execute(
                "SELECT * FROM memories WHERE level = 2 AND category = ? ORDER BY confidence DESC",
                (category,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memories WHERE level = 2 ORDER BY confidence DESC",
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_strategies(self, category: str = "") -> list[dict[str, Any]]:
        """Get all level-3 strategy memories."""
        conn = self._conn()
        if category:
            rows = conn.execute(
                "SELECT * FROM memories WHERE level = 3 AND category = ? ORDER BY confidence DESC",
                (category,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memories WHERE level = 3 ORDER BY confidence DESC",
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_patterns(self, category: str = "") -> list[dict[str, Any]]:
        """Get all level-1 pattern memories."""
        conn = self._conn()
        if category:
            rows = conn.execute(
                "SELECT * FROM memories WHERE level = 1 AND category = ? ORDER BY evidence_count DESC",
                (category,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memories WHERE level = 1 ORDER BY evidence_count DESC",
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # == STATS =====================================================

    def get_stats(self) -> dict[str, Any]:
        """Full system stats."""
        conn = self._conn()
        levels = conn.execute("SELECT level, COUNT(*) as c FROM memories GROUP BY level").fetchall()
        categories = conn.execute("SELECT category, COUNT(*) as c FROM memories GROUP BY category").fetchall()
        types = conn.execute("SELECT memory_type, COUNT(*) as c FROM memories GROUP BY memory_type").fetchall()
        promotions = conn.execute("SELECT COUNT(*) as c FROM promotions").fetchone()
        failures = conn.execute("SELECT COUNT(*) as c FROM failure_analysis").fetchone()
        avg_score = conn.execute("SELECT AVG(score) as avg FROM memories").fetchone()
        total = sum(r["c"] for r in levels)

        level_names = ["event", "pattern", "rule", "strategy"]
        return {
            "total_memories": total,
            "by_level": {level_names[r["level"]] if r["level"] < 4 else f"L{r['level']}": r["c"] for r in levels},
            "by_category": {r["category"]: r["c"] for r in categories},
            "by_type": {r["memory_type"]: r["c"] for r in types},
            "promotions": promotions["c"] if promotions else 0,
            "failures": failures["c"] if failures else 0,
            "avg_score": round(avg_score["avg"], 2) if avg_score and avg_score["avg"] else 0.0,
        }

    # == HELPERS ===================================================

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        for k in ("content", "features", "result", "tags", "source_ids"):
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


# Singleton
_instance: MemoryIntelligence | None = None


def get_memory_intelligence() -> MemoryIntelligence:
    global _instance
    if _instance is None:
        _instance = MemoryIntelligence()
    return _instance
