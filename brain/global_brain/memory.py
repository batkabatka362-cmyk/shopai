"""Global Brain Memory — stores knowledge from all agents.

Global Brain нь:
  - Бүх agent-ийн decision, result, алдаа, амжилтын pattern хадгална
  - Agent ажил эхлэхээс өмнө энэ сангаас мэдээлэл авна
  - Duplicate learning байхгүй (нэг алдааг дахин давтахгүй)
  - Pattern extraction хийнэ (давтагдсан амжилтыг ойлгоно)

Storage: ~/.shopai/data/brain/
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any


try:
    from core.memory.storage_config import get_path
    _BRAIN_DIR = get_path("brain")
except Exception:
    _BRAIN_DIR = "/tmp/shopai_brain"


class GlobalBrainMemory:
    """Central knowledge store shared across all agents."""

    def __init__(self, brain_dir: str | None = None) -> None:
        self._dir = brain_dir or _BRAIN_DIR
        os.makedirs(self._dir, exist_ok=True)
        self._lock = threading.RLock()
        self._knowledge: list[dict[str, Any]] = []
        self._patterns: list[dict[str, Any]] = []
        self._load()

    # ── Write: Agent → Global Brain ──

    def record(
        self,
        agent: str,
        goal: str,
        engines_used: list[str],
        result_score: int,
        success: bool,
        key_findings: list[str] | None = None,
        failures: list[str] | None = None,
        category: str = "",
    ) -> str:
        """Record an agent's execution result into global knowledge."""
        with self._lock:
            entry_id = f"kb_{int(time.time())}_{len(self._knowledge)}"
            entry = {
                "id": entry_id,
                "agent": agent,
                "goal": goal,
                "engines_used": engines_used,
                "result_score": result_score,
                "success": success,
                "key_findings": key_findings or [],
                "failures": failures or [],
                "category": category,
                "timestamp": time.time(),
            }
            self._knowledge.append(entry)
            self._detect_patterns()
            self._persist()
            return entry_id

    # ── Read: Global Brain → Agent ──

    def query(
        self,
        agent: str | None = None,
        goal: str | None = None,
        category: str | None = None,
        success_only: bool = False,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Query global knowledge for relevant past experiences."""
        with self._lock:
            results = self._knowledge

            if agent:
                results = [r for r in results if r["agent"] == agent]
            if goal:
                results = [r for r in results if goal.lower() in r["goal"].lower()]
            if category:
                results = [r for r in results if category.lower() in r.get("category", "").lower()]
            if success_only:
                results = [r for r in results if r["success"]]

            return results[-limit:]

    def get_failures(self, category: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Get past failures — what NOT to do."""
        with self._lock:
            failures = [k for k in self._knowledge if not k["success"]]
            if category:
                failures = [f for f in failures if category.lower() in f.get("category", "").lower()]
            return failures[-limit:]

    def get_patterns(self) -> list[dict[str, Any]]:
        """Get detected patterns from accumulated knowledge."""
        with self._lock:
            return list(self._patterns)

    def get_success_rate(self, agent: str | None = None) -> dict[str, Any]:
        """Get success rate statistics."""
        with self._lock:
            entries = self._knowledge
            if agent:
                entries = [e for e in entries if e["agent"] == agent]
            if not entries:
                return {"total": 0, "success_rate": 0}
            successes = sum(1 for e in entries if e["success"])
            return {
                "total": len(entries),
                "successes": successes,
                "failures": len(entries) - successes,
                "success_rate": round(successes / len(entries) * 100, 1),
            }

    def get_stats(self) -> dict[str, Any]:
        """Get global brain statistics."""
        with self._lock:
            by_agent: dict[str, int] = {}
            by_category: dict[str, int] = {}
            for e in self._knowledge:
                by_agent[e["agent"]] = by_agent.get(e["agent"], 0) + 1
                cat = e.get("category", "unknown")
                if cat:
                    by_category[cat] = by_category.get(cat, 0) + 1

            return {
                "total_entries": len(self._knowledge),
                "total_patterns": len(self._patterns),
                "by_agent": by_agent,
                "by_category": by_category,
                "overall_success_rate": self.get_success_rate()["success_rate"],
            }

    # ── Pattern Detection ──

    def _detect_patterns(self) -> None:
        """Detect recurring patterns from accumulated knowledge."""
        self._patterns = []

        if len(self._knowledge) < 5:
            return

        # Pattern 1: Category success patterns
        category_stats: dict[str, dict] = {}
        for e in self._knowledge:
            cat = e.get("category", "")
            if not cat:
                continue
            if cat not in category_stats:
                category_stats[cat] = {"total": 0, "successes": 0, "scores": []}
            category_stats[cat]["total"] += 1
            if e["success"]:
                category_stats[cat]["successes"] += 1
            category_stats[cat]["scores"].append(e["result_score"])

        for cat, stats in category_stats.items():
            if stats["total"] >= 3:
                rate = stats["successes"] / stats["total"]
                avg_score = sum(stats["scores"]) / len(stats["scores"])
                if rate >= 0.7:
                    self._patterns.append({
                        "type": "category_success",
                        "category": cat,
                        "success_rate": round(rate * 100),
                        "avg_score": round(avg_score),
                        "insight": f"Category '{cat}' consistently performs well ({rate*100:.0f}% success)",
                    })
                elif rate <= 0.3:
                    self._patterns.append({
                        "type": "category_failure",
                        "category": cat,
                        "success_rate": round(rate * 100),
                        "avg_score": round(avg_score),
                        "insight": f"Category '{cat}' consistently underperforms ({rate*100:.0f}% success) — avoid",
                    })

        # Pattern 2: Engine combination patterns
        combo_stats: dict[str, dict] = {}
        for e in self._knowledge:
            combo = ",".join(sorted(e.get("engines_used", [])))
            if not combo:
                continue
            if combo not in combo_stats:
                combo_stats[combo] = {"total": 0, "successes": 0}
            combo_stats[combo]["total"] += 1
            if e["success"]:
                combo_stats[combo]["successes"] += 1

        for combo, stats in combo_stats.items():
            if stats["total"] >= 3:
                rate = stats["successes"] / stats["total"]
                if rate >= 0.7:
                    self._patterns.append({
                        "type": "engine_combo_success",
                        "engines": combo.split(","),
                        "success_rate": round(rate * 100),
                        "insight": f"Engine combo [{combo}] has {rate*100:.0f}% success rate",
                    })

    # ── Persistence ──

    def _persist(self) -> None:
        if len(self._knowledge) > 10000:
            self._knowledge = self._knowledge[-10000:]
        try:
            path = os.path.join(self._dir, "knowledge.json")
            # W962-62: per-pid temp suffix + utf-8 +
            # ensure_ascii=False. Pre-fix Shopify product names
            # / customer notes / engine narratives with non-ASCII
            # would raise UnicodeEncodeError on Windows; the
            # bare Exception catch swallowed it so the brain
            # silently stopped persisting.
            tmp = path + ".tmp." + str(os.getpid())
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "knowledge": self._knowledge,
                        "patterns": self._patterns,
                    },
                    f, default=str, ensure_ascii=False,
                )
            os.replace(tmp, path)
        except Exception:
            pass

    def _load(self) -> None:
        try:
            path = os.path.join(self._dir, "knowledge.json")
            if os.path.exists(path):
                # W962-62: utf-8 so cp1252 doesn't reject
                # UTF-8 content written by other processes.
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                self._knowledge = data.get("knowledge", [])
                self._patterns = data.get("patterns", [])
        except Exception:
            self._knowledge = []
            self._patterns = []
