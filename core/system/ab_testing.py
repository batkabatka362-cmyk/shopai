"""A/B Testing Framework — experiment, measure, learn.

NOT random testing. Intelligent experimentation.

Every experiment:
  1. Hypothesis: "changing X will improve Y"
  2. Variants: control (current) vs treatment (new)
  3. Measurement: track metrics for each variant
  4. Analysis: statistical significance check
  5. Decision: adopt winner or declare inconclusive
  6. Memory: store result for future decisions

Integrates with:
  - SmartExecutor: simulations become experiments
  - MemoryIntelligence: experiment results → patterns → rules
  - DataArchitecture: experiment domain capture
  - PriceHistory: price experiments tracked over time
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import math
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("ab_testing")

_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "ab_testing.db"


def _v1_initial_schema(conn: sqlite3.Connection) -> None:
    """v1: experiments + observations tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS experiments (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            hypothesis  TEXT NOT NULL,
            category    TEXT DEFAULT '',
            variants    TEXT DEFAULT '[]',
            status      TEXT DEFAULT 'active',
            winner      TEXT DEFAULT '',
            metrics     TEXT DEFAULT '{}',
            sample_sizes TEXT DEFAULT '{}',
            created_at  REAL NOT NULL,
            completed_at REAL DEFAULT 0.0
        );
        CREATE TABLE IF NOT EXISTS observations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id TEXT NOT NULL,
            variant     TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            value       REAL NOT NULL,
            timestamp   REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_obs_exp ON observations(experiment_id);
        CREATE INDEX IF NOT EXISTS idx_obs_var ON observations(experiment_id, variant);
    """)


_MIGRATIONS: list[tuple[int, str, Any]] = [
    (1, "initial schema", _v1_initial_schema),
]
_SCHEMA_VERSION = max(m[0] for m in _MIGRATIONS)


class Experiment:
    """A single A/B experiment."""

    def __init__(self, name: str, hypothesis: str, category: str = "",
                 variants: list[str] | None = None) -> None:
        self.id = ""
        self.name = name
        self.hypothesis = hypothesis
        self.category = category
        self.variants = variants or ["control", "treatment"]
        self.status = "active"  # active, completed, cancelled
        self.winner = ""
        self.created_at = time.time()
        self.completed_at = 0.0
        self.metrics: dict[str, dict[str, float]] = {v: {} for v in self.variants}
        self.sample_sizes: dict[str, int] = {v: 0 for v in self.variants}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "hypothesis": self.hypothesis,
            "category": self.category, "variants": self.variants,
            "status": self.status, "winner": self.winner,
            "metrics": self.metrics, "sample_sizes": self.sample_sizes,
            "created_at": self.created_at, "completed_at": self.completed_at,
        }


class ABTestingFramework:
    """Intelligent A/B testing with automatic analysis."""

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
        Migrator(self._conn(), "ab_testing", _MIGRATIONS).run()
        register_schema("ab_testing", Path(self._db_path), _SCHEMA_VERSION)

    # == CREATE EXPERIMENT =========================================

    def create_experiment(self, name: str, hypothesis: str,
                          category: str = "",
                          variants: list[str] | None = None) -> str:
        """Create a new A/B experiment. Returns experiment ID."""
        exp_id = f"exp_{int(time.time()*1000)}"
        variants = variants or ["control", "treatment"]

        conn = self._conn()
        conn.execute(
            "INSERT INTO experiments (id, name, hypothesis, category, variants, created_at) VALUES (?,?,?,?,?,?)",
            (exp_id, name, hypothesis, category, json.dumps(variants), time.time()),
        )
        conn.commit()
        logger.info("Experiment created: %s [%s] %s", exp_id, name, hypothesis)
        return exp_id

    # == RECORD OBSERVATION ========================================

    def record(self, experiment_id: str, variant: str,
               metric_name: str, value: float) -> None:
        """Record a metric observation for a variant."""
        conn = self._conn()
        conn.execute(
            "INSERT INTO observations (experiment_id, variant, metric_name, value, timestamp) VALUES (?,?,?,?,?)",
            (experiment_id, variant, metric_name, value, time.time()),
        )
        conn.commit()

    def record_batch(self, experiment_id: str, variant: str,
                     metrics: dict[str, float]) -> None:
        """Record multiple metrics at once."""
        conn = self._conn()
        now = time.time()
        for name, value in metrics.items():
            conn.execute(
                "INSERT INTO observations (experiment_id, variant, metric_name, value, timestamp) VALUES (?,?,?,?,?)",
                (experiment_id, variant, name, value, now),
            )
        conn.commit()

    # == ANALYSIS ==================================================

    def analyze(self, experiment_id: str) -> dict[str, Any]:
        """Analyze an experiment — compare variants statistically."""
        conn = self._conn()
        exp = conn.execute(
            "SELECT * FROM experiments WHERE id = ?", (experiment_id,),
        ).fetchone()
        if not exp:
            return {"error": "Experiment not found"}

        variants = json.loads(exp["variants"])
        results: dict[str, dict] = {}

        for variant in variants:
            rows = conn.execute(
                "SELECT metric_name, AVG(value) as avg, COUNT(*) as n, "
                "MIN(value) as min_val, MAX(value) as max_val "
                "FROM observations WHERE experiment_id = ? AND variant = ? "
                "GROUP BY metric_name",
                (experiment_id, variant),
            ).fetchall()

            variant_metrics: dict[str, dict] = {}
            total_n = 0
            for r in rows:
                # Calculate std dev
                vals = conn.execute(
                    "SELECT value FROM observations WHERE experiment_id = ? AND variant = ? AND metric_name = ?",
                    (experiment_id, variant, r["metric_name"]),
                ).fetchall()
                values = [v["value"] for v in vals]
                n = len(values)
                avg = sum(values) / n if n > 0 else 0
                variance = sum((x - avg) ** 2 for x in values) / n if n > 1 else 0
                std = math.sqrt(variance)

                variant_metrics[r["metric_name"]] = {
                    "avg": round(avg, 4),
                    "std": round(std, 4),
                    "n": n,
                    "min": r["min_val"],
                    "max": r["max_val"],
                }
                total_n = max(total_n, n)

            results[variant] = {"metrics": variant_metrics, "sample_size": total_n}

        # Compare variants
        comparison = self._compare_variants(results, variants)

        return {
            "experiment_id": experiment_id,
            "name": exp["name"],
            "hypothesis": exp["hypothesis"],
            "status": exp["status"],
            "variants": results,
            "comparison": comparison,
        }

    def _compare_variants(self, results: dict, variants: list[str]) -> dict[str, Any]:
        """Compare variants and determine winner."""
        if len(variants) < 2:
            return {"result": "insufficient_variants"}

        control = variants[0]
        treatment = variants[1]

        c_data = results.get(control, {}).get("metrics", {})
        t_data = results.get(treatment, {}).get("metrics", {})

        if not c_data or not t_data:
            return {"result": "insufficient_data"}

        wins = {control: 0, treatment: 0}
        metric_comparisons = {}

        for metric in set(list(c_data.keys()) + list(t_data.keys())):
            c = c_data.get(metric, {})
            t = t_data.get(metric, {})
            c_avg = c.get("avg", 0)
            t_avg = t.get("avg", 0)
            c_n = c.get("n", 0)
            t_n = t.get("n", 0)

            if c_n < 2 or t_n < 2:
                metric_comparisons[metric] = {"result": "insufficient_data"}
                continue

            # Effect size
            diff = t_avg - c_avg
            diff_pct = (diff / c_avg * 100) if c_avg != 0 else 0

            # Simple significance: is the difference > 1 std dev?
            c_std = c.get("std", 0)
            t_std = t.get("std", 0)
            pooled_std = math.sqrt((c_std**2 + t_std**2) / 2) if (c_std + t_std) > 0 else 1

            significant = abs(diff) > pooled_std * 0.5  # 0.5 SD threshold
            winner = treatment if diff > 0 else control

            if significant:
                wins[winner] += 1

            metric_comparisons[metric] = {
                "control_avg": round(c_avg, 4),
                "treatment_avg": round(t_avg, 4),
                "diff": round(diff, 4),
                "diff_pct": round(diff_pct, 1),
                "significant": significant,
                "winner": winner if significant else "tie",
            }

        overall_winner = max(wins, key=wins.get) if max(wins.values()) > 0 else "inconclusive"

        return {
            "result": "conclusive" if max(wins.values()) > 0 else "inconclusive",
            "winner": overall_winner,
            "wins": wins,
            "metrics": metric_comparisons,
        }

    # == AUTO-EXPERIMENT FROM SMART EXECUTOR =======================

    def create_from_simulation(self, action_type: str, predicted: dict,
                               actual: dict, score: float) -> str:
        """Auto-create or reuse experiment from SmartExecutor simulation."""
        # Reuse existing active experiment for same action_type
        conn = self._conn()
        existing = conn.execute(
            "SELECT id FROM experiments WHERE category = ? AND status = 'active' LIMIT 1",
            (action_type,),
        ).fetchone()

        if existing:
            exp_id = existing["id"]
        else:
            exp_id = self.create_experiment(
                name=f"sim_{action_type}",
                hypothesis=f"{action_type} simulation predicts positive outcome",
                category=action_type,
                variants=["predicted", "actual"],
            )

        # Record predicted metrics
        pred_metrics = {}
        for k, v in predicted.items():
            if isinstance(v, (int, float)):
                pred_metrics[k] = float(v)
        if pred_metrics:
            self.record_batch(exp_id, "predicted", pred_metrics)

        # Record actual metrics
        actual_metrics = {}
        for k, v in actual.items():
            if isinstance(v, (int, float)):
                actual_metrics[k] = float(v)
        actual_metrics["score"] = score
        if actual_metrics:
            self.record_batch(exp_id, "actual", actual_metrics)

        return exp_id

    # == COMPLETE EXPERIMENT =======================================

    def complete(self, experiment_id: str) -> dict[str, Any]:
        """Complete an experiment and record the winner."""
        analysis = self.analyze(experiment_id)
        winner = analysis.get("comparison", {}).get("winner", "inconclusive")

        conn = self._conn()
        conn.execute(
            "UPDATE experiments SET status = 'completed', winner = ?, completed_at = ? WHERE id = ?",
            (winner, time.time(), experiment_id),
        )
        conn.commit()

        # Store in MemoryIntelligence
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            mi.create(
                category="experiment",
                content={"experiment_id": experiment_id,
                         "hypothesis": analysis.get("hypothesis", ""),
                         "winner": winner,
                         "comparison": analysis.get("comparison", {})},
                action="experiment_complete",
                result={"winner": winner},
                score=4.0 if winner != "inconclusive" else 2.5,
                memory_type="semantic",
                tags=["experiment", analysis.get("name", ""), winner],
            )
        except Exception as exc:
            logger.debug("experiment memory capture failed: %s", exc)

        logger.info("Experiment %s completed: winner=%s", experiment_id, winner)
        return analysis

    # == STATS =====================================================

    def get_stats(self) -> dict[str, Any]:
        conn = self._conn()
        total = conn.execute("SELECT COUNT(*) as c FROM experiments").fetchone()
        active = conn.execute("SELECT COUNT(*) as c FROM experiments WHERE status = 'active'").fetchone()
        completed = conn.execute("SELECT COUNT(*) as c FROM experiments WHERE status = 'completed'").fetchone()
        obs = conn.execute("SELECT COUNT(*) as c FROM observations").fetchone()
        return {
            "total_experiments": total["c"] if total else 0,
            "active": active["c"] if active else 0,
            "completed": completed["c"] if completed else 0,
            "total_observations": obs["c"] if obs else 0,
        }

    def get_active(self) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM experiments WHERE status = 'active' ORDER BY created_at DESC",
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        if hasattr(self._local, "c") and self._local.c:
            self._local.c.close()
            self._local.c = None


_instance: ABTestingFramework | None = None

def get_ab_testing() -> ABTestingFramework:
    global _instance
    if _instance is None:
        _instance = ABTestingFramework()
    return _instance
