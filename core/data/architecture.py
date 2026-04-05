"""Data Architecture — 12-domain structured data store.

NOT a database. An intelligence foundation.

Every piece of data entering the system gets:
  1. Domain classification (which of 12 domains?)
  2. Feature extraction (what signals matter?)
  3. Result attachment (what happened after using this data?)
  4. Score assignment (1-5, how useful was this?)
  5. Tag generation (for retrieval)

12 Domains:
  Product    — product attributes, margins, performance
  Marketing  — campaigns, channels, content performance
  Action     — things the system DID (price changes, launches)
  Result     — what HAPPENED after an action
  Decision   — choices made with context + reasoning
  Feedback   — external signals (reviews, complaints, returns)
  Experiment — A/B tests, simulations, hypotheses
  Feature    — extracted signals from raw data
  Knowledge  — learned facts, rules, strategies
  System     — system performance, errors, latency
  ToolUsage  — which tools/engines used, success rates
  Simulation — what-if scenarios, predictions vs actuals

Flow:
  Execution → Data capture → Feature transform → Result attach → Score → Store
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("data.architecture")

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "data_architecture.db"

# ── Domain Definitions ───────────────────────────────────────

DOMAINS = {
    "product": {
        "required": ["id"],
        "features": ["price", "cost", "margin", "category", "inventory", "has_images", "has_description"],
        "score_fields": ["margin", "conversion_rate", "revenue"],
    },
    "marketing": {
        "required": ["channel"],
        "features": ["channel", "campaign_type", "audience_size", "spend", "impressions", "clicks", "conversions"],
        "score_fields": ["roas", "ctr", "conversion_rate", "cpc"],
    },
    "action": {
        "required": ["action_type"],
        "features": ["action_type", "target", "magnitude", "domain", "confidence"],
        "score_fields": ["outcome_score", "impact"],
    },
    "result": {
        "required": ["action_id"],
        "features": ["action_type", "success", "impact_magnitude", "time_to_effect"],
        "score_fields": ["revenue_impact", "conversion_impact", "customer_impact"],
    },
    "decision": {
        "required": ["choice"],
        "features": ["category", "options_count", "confidence", "memory_used", "rules_applied"],
        "score_fields": ["outcome_score", "accuracy"],
    },
    "feedback": {
        "required": ["source"],
        "features": ["source", "sentiment", "topic", "urgency"],
        "score_fields": ["actionability", "impact"],
    },
    "experiment": {
        "required": ["hypothesis"],
        "features": ["experiment_type", "variants", "sample_size", "duration", "confidence_level"],
        "score_fields": ["statistical_significance", "effect_size", "practical_impact"],
    },
    "feature": {
        "required": ["feature_name", "value"],
        "features": ["feature_name", "data_type", "source_domain", "freshness"],
        "score_fields": ["predictive_power", "stability", "coverage"],
    },
    "knowledge": {
        "required": ["content"],
        "features": ["knowledge_type", "domain", "confidence", "evidence_count"],
        "score_fields": ["usefulness", "accuracy", "applicability"],
    },
    "system": {
        "required": ["event_type"],
        "features": ["event_type", "component", "severity", "latency_ms"],
        "score_fields": ["impact", "recoverability"],
    },
    "tool_usage": {
        "required": ["tool_name"],
        "features": ["tool_name", "engine_name", "input_size", "output_size", "latency_ms", "success"],
        "score_fields": ["effectiveness", "efficiency", "reliability"],
    },
    "simulation": {
        "required": ["scenario"],
        "features": ["scenario_type", "variables", "assumptions_count", "time_horizon"],
        "score_fields": ["prediction_accuracy", "confidence", "practical_value"],
    },
}

DOMAIN_NAMES = list(DOMAINS.keys())


class DataRecord:
    """A single data record with full context."""

    __slots__ = ("id", "domain", "data", "features", "result", "score",
                 "tags", "source", "action_id", "store_id", "timestamp", "ttl")

    def __init__(self, domain: str, data: dict, features: dict | None = None,
                 result: dict | None = None, score: float = 0.0,
                 tags: list[str] | None = None, source: str = "",
                 action_id: str = "", store_id: str = "", ttl: int = 0) -> None:
        self.id = 0
        self.domain = domain
        self.data = data
        self.features = features or {}
        self.result = result or {}
        self.score = score
        self.tags = tags or []
        self.source = source
        self.action_id = action_id
        self.store_id = store_id
        self.timestamp = time.time()
        self.ttl = ttl  # 0 = permanent

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "domain": self.domain, "features": self.features,
            "score": self.score, "tags": self.tags, "source": self.source,
            "action_id": self.action_id, "timestamp": self.timestamp,
        }


class DataArchitecture:
    """12-domain structured data store — AI intelligence foundation."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path or _DB_PATH)
        self._local = threading.local()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        # Domain stats cache
        self._stats_cache: dict[str, dict] = {}
        self._stats_ts = 0.0

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "c") or self._local.c is None:
            self._local.c = sqlite3.connect(self._db_path, timeout=10)
            self._local.c.row_factory = sqlite3.Row
            self._local.c.execute("PRAGMA journal_mode=WAL")
        return self._local.c

    def _init_schema(self) -> None:
        self._conn().executescript("""
            CREATE TABLE IF NOT EXISTS records (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                domain      TEXT NOT NULL,
                data        TEXT DEFAULT '{}',
                features    TEXT DEFAULT '{}',
                result      TEXT DEFAULT '{}',
                score       REAL DEFAULT 0.0,
                tags        TEXT DEFAULT '[]',
                source      TEXT DEFAULT '',
                action_id   TEXT DEFAULT '',
                store_id    TEXT DEFAULT '',
                timestamp   REAL NOT NULL,
                ttl         INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS domain_stats (
                domain      TEXT PRIMARY KEY,
                total       INTEGER DEFAULT 0,
                avg_score   REAL DEFAULT 0.0,
                last_write  REAL DEFAULT 0.0
            );
            CREATE TABLE IF NOT EXISTS action_results (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                action_id   TEXT NOT NULL,
                action_type TEXT NOT NULL,
                action_data TEXT DEFAULT '{}',
                result_data TEXT DEFAULT '{}',
                score       REAL DEFAULT 0.0,
                latency_s   REAL DEFAULT 0.0,
                timestamp   REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rec_domain ON records(domain);
            CREATE INDEX IF NOT EXISTS idx_rec_score ON records(score);
            CREATE INDEX IF NOT EXISTS idx_rec_tags ON records(tags);
            CREATE INDEX IF NOT EXISTS idx_rec_ts ON records(timestamp);
            CREATE INDEX IF NOT EXISTS idx_rec_action ON records(action_id);
            CREATE INDEX IF NOT EXISTS idx_rec_store ON records(store_id);
            CREATE INDEX IF NOT EXISTS idx_ar_action ON action_results(action_id);
            CREATE INDEX IF NOT EXISTS idx_ar_type ON action_results(action_type);
        """)
        self._conn().commit()

    # ══════════════════════════════════════════════════════════
    # CAPTURE — data enters the system
    # ══════════════════════════════════════════════════════════

    def capture(self, domain: str, data: dict, source: str = "",
                store_id: str = "", action_id: str = "",
                score: float = 0.0, tags: list[str] | None = None,
                ttl: int = 0) -> int:
        """Capture data into a domain.

        Flow: validate → extract features → score → tag → store

        Args:
            domain: One of 12 domains
            data: Raw data dict
            source: Where this came from (engine name, api, user)
            store_id: Which store
            action_id: Link to an action (for result tracking)
            score: Pre-assigned score (0 = auto-score)
            tags: Pre-assigned tags (auto-tags always added)
            ttl: Time-to-live seconds (0 = permanent)

        Returns:
            Record ID (0 if rejected)
        """
        if domain not in DOMAINS:
            logger.warning("Unknown domain: %s", domain)
            return 0

        # Validate required fields
        schema = DOMAINS[domain]
        for field in schema["required"]:
            if not data.get(field):
                logger.debug("Missing required field %s for domain %s", field, domain)
                return 0

        # Extract features
        features = self._extract_features(domain, data)

        # Auto-score if not provided
        if score <= 0:
            score = self._auto_score(domain, data, features)

        # Auto-tag
        auto_tags = self._auto_tag(domain, data, features)
        all_tags = list(set((tags or []) + auto_tags))

        # Store
        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO records (domain, data, features, score, tags, source,
               action_id, store_id, timestamp, ttl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (domain, json.dumps(data, default=str), json.dumps(features, default=str),
             score, json.dumps(all_tags), source, action_id, store_id,
             time.time(), ttl),
        )
        conn.commit()

        # Update domain stats
        self._update_domain_stats(domain, score)

        return cur.lastrowid or 0

    def capture_batch(self, domain: str, records: list[dict],
                      source: str = "", store_id: str = "") -> dict[str, int]:
        """Capture multiple records efficiently."""
        captured = 0
        rejected = 0
        for rec in records:
            rid = self.capture(domain, rec, source=source, store_id=store_id)
            if rid > 0:
                captured += 1
            else:
                rejected += 1
        return {"captured": captured, "rejected": rejected, "total": len(records)}

    # ══════════════════════════════════════════════════════════
    # ACTION-RESULT TRACKING — link actions to outcomes
    # ══════════════════════════════════════════════════════════

    def record_action(self, action_id: str, action_type: str,
                      action_data: dict, store_id: str = "") -> int:
        """Record an action taken by the system."""
        rid = self.capture("action", {
            "id": action_id, "action_type": action_type,
            **action_data,
        }, source="system", store_id=store_id, action_id=action_id)

        conn = self._conn()
        conn.execute(
            """INSERT INTO action_results (action_id, action_type, action_data, timestamp)
               VALUES (?, ?, ?, ?)""",
            (action_id, action_type, json.dumps(action_data, default=str), time.time()),
        )
        conn.commit()
        return rid

    def attach_result(self, action_id: str, result_data: dict,
                      score: float = 0.0, latency_s: float = 0.0) -> None:
        """Attach a result to a previous action — CRITICAL for learning."""
        conn = self._conn()
        conn.execute(
            """UPDATE action_results SET result_data = ?, score = ?, latency_s = ?
               WHERE action_id = ?""",
            (json.dumps(result_data, default=str), score, latency_s, action_id),
        )
        conn.commit()

        # Also capture as a result domain record
        self.capture("result", {
            "action_id": action_id, "success": score >= 3.0,
            "impact_magnitude": score, **result_data,
        }, source="outcome", action_id=action_id, score=score)

    def get_action_results(self, action_type: str = "",
                           limit: int = 50) -> list[dict[str, Any]]:
        """Get action→result pairs for learning."""
        conn = self._conn()
        if action_type:
            rows = conn.execute(
                """SELECT * FROM action_results WHERE action_type = ?
                   AND result_data != '{}' ORDER BY timestamp DESC LIMIT ?""",
                (action_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM action_results WHERE result_data != '{}'
                   ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ══════════════════════════════════════════════════════════
    # RETRIEVE — get data for decisions
    # ══════════════════════════════════════════════════════════

    def query(self, domain: str, min_score: float = 0.0,
              tags: list[str] | None = None, limit: int = 50,
              since: float = 0.0, store_id: str = "") -> list[dict[str, Any]]:
        """Query records from a domain with filters."""
        conn = self._conn()
        sql = "SELECT * FROM records WHERE domain = ?"
        params: list[Any] = [domain]

        if min_score > 0:
            sql += " AND score >= ?"
            params.append(min_score)
        if since > 0:
            sql += " AND timestamp >= ?"
            params.append(since)
        if store_id:
            sql += " AND store_id = ?"
            params.append(store_id)

        sql += " ORDER BY score DESC, timestamp DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        results = [self._row_to_dict(r) for r in rows]

        # Tag filter (post-query since tags are JSON)
        if tags:
            tag_set = set(tags)
            results = [r for r in results
                       if tag_set.intersection(set(r.get("tags", [])))]

        return results

    def get_best(self, domain: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get highest-scored records from a domain."""
        return self.query(domain, min_score=4.0, limit=limit)

    def get_failures(self, domain: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get lowest-scored records — failures are gold for learning."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM records WHERE domain = ? AND score <= 2.0 ORDER BY timestamp DESC LIMIT ?",
            (domain, limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_recent(self, domain: str, limit: int = 20,
                   hours: float = 24.0) -> list[dict[str, Any]]:
        """Get recent records from a domain."""
        since = time.time() - (hours * 3600)
        return self.query(domain, since=since, limit=limit)

    def get_by_action(self, action_id: str) -> list[dict[str, Any]]:
        """Get all records linked to an action."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM records WHERE action_id = ? ORDER BY timestamp",
            (action_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_context_for_decision(self, domain: str,
                                 context: dict | None = None) -> dict[str, Any]:
        """Build full context for a decision — best, failures, recent, stats."""
        best = self.get_best(domain, limit=5)
        failures = self.get_failures(domain, limit=5)
        recent = self.get_recent(domain, limit=10, hours=48)
        stats = self.get_domain_stats(domain)

        return {
            "domain": domain,
            "best_cases": best,
            "failures": failures,
            "recent": recent,
            "stats": stats,
            "total_records": stats.get("total", 0),
        }

    # ══════════════════════════════════════════════════════════
    # FEATURE EXTRACTION — transform raw data into signals
    # ══════════════════════════════════════════════════════════

    def _extract_features(self, domain: str, data: dict) -> dict[str, Any]:
        """Extract meaningful features from raw data per domain."""
        features: dict[str, Any] = {}
        schema = DOMAINS[domain]

        # Extract defined features
        for f in schema["features"]:
            val = data.get(f)
            if val is not None:
                features[f] = val

        # Domain-specific enrichment
        if domain == "product":
            price = float(data.get("price", 0) or 0)
            cost = float(data.get("cost", 0) or 0)
            if price > 0 and cost > 0:
                features["margin"] = round((price - cost) / price, 3)
                features["markup"] = round((price - cost) / cost, 3)
            features["price_tier"] = (
                "premium" if price > 50 else "mid" if price > 20 else "budget"
            ) if price > 0 else "unknown"
            features["has_images"] = bool(
                data.get("images") or data.get("image") or data.get("image_url")
            )
            features["has_description"] = bool(
                str(data.get("body_html", data.get("description", ""))).strip()
            )
            features["inventory"] = int(data.get("inventory_quantity", 0))

        elif domain == "marketing":
            spend = float(data.get("spend", 0) or 0)
            revenue = float(data.get("revenue", 0) or 0)
            clicks = int(data.get("clicks", 0) or 0)
            impressions = int(data.get("impressions", 0) or 0)
            conversions = int(data.get("conversions", 0) or 0)
            if spend > 0:
                features["roas"] = round(revenue / spend, 2)
                features["cpc"] = round(spend / max(clicks, 1), 2)
            if impressions > 0:
                features["ctr"] = round(clicks / impressions, 4)
            if clicks > 0:
                features["conversion_rate"] = round(conversions / clicks, 4)

        elif domain == "action":
            features["has_target"] = bool(data.get("target"))
            features["has_confidence"] = bool(data.get("confidence"))

        elif domain == "decision":
            features["had_memory"] = bool(data.get("memory_used"))
            features["had_rules"] = bool(data.get("rules_applied"))
            features["options_count"] = int(data.get("options_count", data.get("options_considered", 0)) or 0)

        elif domain == "experiment":
            features["has_control"] = bool(data.get("control_group"))
            features["has_hypothesis"] = bool(data.get("hypothesis"))
            sample = int(data.get("sample_size", 0) or 0)
            features["sample_sufficient"] = sample >= 100

        elif domain == "tool_usage":
            features["success"] = bool(data.get("success", True))
            latency = float(data.get("latency_ms", 0) or 0)
            features["fast"] = latency < 1000
            features["slow"] = latency > 5000

        elif domain == "simulation":
            predicted = data.get("predicted")
            actual = data.get("actual")
            if predicted is not None and actual is not None:
                try:
                    features["prediction_error"] = abs(float(predicted) - float(actual))
                    features["prediction_accurate"] = features["prediction_error"] < float(predicted) * 0.2
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

        return features

    # ══════════════════════════════════════════════════════════
    # SCORING — rate data quality and usefulness
    # ══════════════════════════════════════════════════════════

    def _auto_score(self, domain: str, data: dict, features: dict) -> float:
        """Score data 1-5 based on completeness and quality."""
        score = 3.0
        schema = DOMAINS[domain]

        # Completeness: how many defined features are present?
        defined = schema["features"]
        present = sum(1 for f in defined if features.get(f) is not None)
        completeness = present / max(len(defined), 1)
        score += (completeness - 0.5) * 2  # -1 to +1

        # Score fields present and positive?
        score_fields = schema["score_fields"]
        for sf in score_fields:
            val = data.get(sf) or features.get(sf)
            if val is not None:
                try:
                    if float(val) > 0:
                        score += 0.2
                except (TypeError, ValueError):
                    pass

        # Penalty for minimal data
        non_empty = sum(1 for v in data.values() if v)
        if non_empty < 2:
            score -= 1.0

        return max(1.0, min(5.0, round(score, 1)))

    def _auto_tag(self, domain: str, data: dict, features: dict) -> list[str]:
        """Generate tags for retrieval."""
        tags = [domain]

        # Source tag
        source = data.get("source", "")
        if source:
            tags.append(f"src:{source}")

        # Domain-specific tags
        if domain == "product":
            tier = features.get("price_tier", "")
            if tier:
                tags.append(tier)
            margin = features.get("margin", 0)
            if isinstance(margin, (int, float)):
                if margin > 0.6:
                    tags.append("high_margin")
                elif margin > 0.3:
                    tags.append("mid_margin")
                elif margin > 0:
                    tags.append("low_margin")
                elif margin < 0:
                    tags.append("negative_margin")
            cat = data.get("category", data.get("product_type", ""))
            if cat:
                tags.append(f"cat:{str(cat).lower()}")

        elif domain == "marketing":
            channel = data.get("channel", "")
            if channel:
                tags.append(f"ch:{channel}")
            roas = features.get("roas", 0)
            if isinstance(roas, (int, float)):
                if roas > 3:
                    tags.append("high_roas")
                elif roas > 1:
                    tags.append("profitable")
                elif roas > 0:
                    tags.append("unprofitable")

        elif domain == "action":
            action_type = data.get("action_type", "")
            if action_type:
                tags.append(f"act:{action_type}")

        elif domain == "decision":
            cat = data.get("category", "")
            if cat:
                tags.append(f"dec:{cat}")
            if features.get("had_memory"):
                tags.append("memory_informed")

        elif domain == "experiment":
            exp_type = data.get("experiment_type", "")
            if exp_type:
                tags.append(f"exp:{exp_type}")

        elif domain == "tool_usage":
            tool = data.get("tool_name", "")
            if tool:
                tags.append(f"tool:{tool}")
            if features.get("success"):
                tags.append("success")
            else:
                tags.append("failure")
            if features.get("slow"):
                tags.append("slow")

        elif domain == "system":
            severity = data.get("severity", "")
            if severity:
                tags.append(f"sev:{severity}")

        return tags

    # ══════════════════════════════════════════════════════════
    # DOMAIN STATS
    # ══════════════════════════════════════════════════════════

    def _update_domain_stats(self, domain: str, score: float) -> None:
        conn = self._conn()
        existing = conn.execute(
            "SELECT total, avg_score FROM domain_stats WHERE domain = ?",
            (domain,),
        ).fetchone()

        if existing:
            new_total = existing["total"] + 1
            new_avg = (existing["avg_score"] * existing["total"] + score) / new_total
            conn.execute(
                "UPDATE domain_stats SET total = ?, avg_score = ?, last_write = ? WHERE domain = ?",
                (new_total, round(new_avg, 2), time.time(), domain),
            )
        else:
            conn.execute(
                "INSERT INTO domain_stats (domain, total, avg_score, last_write) VALUES (?, ?, ?, ?)",
                (domain, 1, score, time.time()),
            )
        conn.commit()

    def get_domain_stats(self, domain: str = "") -> dict[str, Any]:
        """Get stats for a domain or all domains."""
        conn = self._conn()
        if domain:
            row = conn.execute(
                "SELECT * FROM domain_stats WHERE domain = ?", (domain,),
            ).fetchone()
            return dict(row) if row else {"domain": domain, "total": 0, "avg_score": 0.0}
        else:
            rows = conn.execute("SELECT * FROM domain_stats ORDER BY total DESC").fetchall()
            return {
                "domains": {r["domain"]: {"total": r["total"], "avg_score": r["avg_score"]} for r in rows},
                "total_records": sum(r["total"] for r in rows),
            }

    def get_stats(self) -> dict[str, Any]:
        """Full system stats."""
        domain_stats = self.get_domain_stats()
        conn = self._conn()
        action_count = conn.execute("SELECT COUNT(*) as c FROM action_results").fetchone()
        result_count = conn.execute(
            "SELECT COUNT(*) as c FROM action_results WHERE result_data != '{}'",
        ).fetchone()

        return {
            **domain_stats,
            "actions_tracked": action_count["c"] if action_count else 0,
            "results_attached": result_count["c"] if result_count else 0,
            "result_rate": round(
                (result_count["c"] / max(action_count["c"], 1)) * 100
            ) if action_count and result_count else 0,
        }

    # ══════════════════════════════════════════════════════════
    # CLEANUP — expire old TTL records
    # ══════════════════════════════════════════════════════════

    def cleanup_expired(self) -> int:
        """Remove records past their TTL."""
        conn = self._conn()
        now = time.time()
        cur = conn.execute(
            "DELETE FROM records WHERE ttl > 0 AND (timestamp + ttl) < ?",
            (now,),
        )
        conn.commit()
        return cur.rowcount

    # ══════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        for k in ("data", "features", "result", "tags", "action_data", "result_data"):
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
_instance: DataArchitecture | None = None


def get_data_architecture() -> DataArchitecture:
    global _instance
    if _instance is None:
        _instance = DataArchitecture()
    return _instance
