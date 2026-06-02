"""KPI Tracker — tracks decision quality and business metrics.

Metrics tracked:
  - Decision accuracy: high confidence decisions that succeeded
  - Execution success rate by action type
  - Revenue per decision type
  - Data quality trend
  - Learning effectiveness: are patterns improving decisions?
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("intelligence.kpi")

try:
    from core.memory.storage_config import kpi_dir
    _KPI_DIR = kpi_dir()
except Exception:
    _KPI_DIR = "/tmp/shopai_kpi"


# W962-51: SHARED module-level lock across all KPITracker
# instances. The verifier confirmed multiple instances each
# get their own self._lock, but they all write to the same
# files in _KPI_DIR. Per-instance locks gave no protection
# against the inter-instance race that the 6 caller sites
# create. Hoisted to a module-level lock used by every
# instance.
_GLOBAL_LOCK = threading.RLock()


class KPITracker:
    """Tracks business KPIs and decision quality metrics."""

    def __init__(self) -> None:
        # W962-51: alias to the global lock so existing
        # `with self._lock:` blocks continue to work; the
        # actual mutex is shared across all instances now.
        self._lock = _GLOBAL_LOCK
        os.makedirs(_KPI_DIR, exist_ok=True)

    def record_decision_outcome(self, decision_id: str, decision_type: str,
                                 confidence: str, confidence_score: int,
                                 success: bool, data_quality: int,
                                 execution_results: dict[str, Any] | None = None) -> None:
        """Record a decision and its outcome for KPI analysis."""
        # Defensive coercion of public entry point. Audit pass 40.
        entry = {
            "decision_id": decision_id if isinstance(decision_id, str) else "",
            "decision_type": decision_type if isinstance(decision_type, str) else "unknown",
            "confidence": confidence if isinstance(confidence, str) else "unknown",
            "confidence_score": safe_int(confidence_score, default=50),
            "success": bool(success),
            "data_quality": safe_int(data_quality),
            "timestamp": time.time(),
        }
        if isinstance(execution_results, dict):
            entry["dispatched"] = safe_int(execution_results.get("dispatched"))
            entry["success_count"] = safe_int(execution_results.get("success_count"))
            entry["fail_count"] = safe_int(execution_results.get("fail_count"))

        self._append("decisions", entry)

    def record_revenue_event(self, decision_id: str, revenue: float,
                              cost: float = 0, conversion_count: int = 0,
                              impression_count: int = 0, click_count: int = 0) -> None:
        """Record a revenue event with e-commerce metrics."""
        # Defensive coercion. Audit pass 40.
        revenue = safe_float(revenue)
        cost = safe_float(cost)
        conversion_count = safe_int(conversion_count)
        impression_count = safe_int(impression_count)
        click_count = safe_int(click_count)

        entry = {
            "decision_id": decision_id if isinstance(decision_id, str) else "",
            "revenue": revenue,
            "cost": cost,
            "profit": round(revenue - cost, 2),
            "conversions": conversion_count,
            "impressions": impression_count,
            "clicks": click_count,
            "timestamp": time.time(),
        }

        # Calculate derived metrics
        if impression_count > 0:
            entry["ctr"] = round(click_count / impression_count * 100, 2)
        if impression_count > 0 and conversion_count > 0:
            entry["conversion_rate"] = round(conversion_count / impression_count * 100, 2)
        if conversion_count > 0 and cost > 0:
            entry["cac"] = round(cost / conversion_count, 2)
        if revenue > 0 and cost > 0:
            entry["roas"] = round(revenue / cost, 2)

        self._append("revenue_events", entry)

    def get_decision_kpis(self) -> dict[str, Any]:
        """Get decision quality KPIs."""
        decisions = self._load("decisions")
        if not decisions:
            return {"status": "no_data"}

        total = len(decisions)
        successes = sum(1 for d in decisions if d.get("success"))

        # Accuracy by confidence level
        by_confidence: dict[str, dict] = {}
        for d in decisions:
            conf = d.get("confidence", "unknown")
            if conf not in by_confidence:
                by_confidence[conf] = {"total": 0, "success": 0}
            by_confidence[conf]["total"] += 1
            if d.get("success"):
                by_confidence[conf]["success"] += 1

        for v in by_confidence.values():
            v["accuracy"] = round(v["success"] / max(v["total"], 1) * 100, 1)

        # By decision type
        by_type: dict[str, dict] = {}
        for d in decisions:
            dt = d.get("decision_type", "unknown")
            if dt not in by_type:
                by_type[dt] = {"total": 0, "success": 0}
            by_type[dt]["total"] += 1
            if d.get("success"):
                by_type[dt]["success"] += 1

        for v in by_type.values():
            v["success_rate"] = round(v["success"] / max(v["total"], 1) * 100, 1)

        # Data quality correlation
        quality_scores = [d.get("data_quality", 0) for d in decisions if d.get("success")]
        fail_quality = [d.get("data_quality", 0) for d in decisions if not d.get("success")]

        # Confidence calibration: does high confidence actually predict success?
        conf_scores = [d.get("confidence_score", 50) for d in decisions if d.get("success")]
        fail_conf = [d.get("confidence_score", 50) for d in decisions if not d.get("success")]

        return {
            "total_decisions": total,
            "overall_success_rate": round(successes / max(total, 1) * 100, 1),
            "by_confidence": by_confidence,
            "by_decision_type": by_type,
            "avg_quality_success": round(sum(quality_scores) / max(len(quality_scores), 1), 1),
            "avg_quality_fail": round(sum(fail_quality) / max(len(fail_quality), 1), 1),
            "avg_confidence_success": round(sum(conf_scores) / max(len(conf_scores), 1), 1),
            "avg_confidence_fail": round(sum(fail_conf) / max(len(fail_conf), 1), 1),
            "confidence_calibrated": (
                sum(conf_scores) / max(len(conf_scores), 1) >
                sum(fail_conf) / max(len(fail_conf), 1)
            ) if conf_scores and fail_conf else None,
        }

    def get_revenue_kpis(self) -> dict[str, Any]:
        """Get revenue and e-commerce KPIs."""
        events = self._load("revenue_events")
        if not events:
            return {"status": "no_data"}

        # Filter to dict entries only so generator expressions
        # below don't crash on a stray non-dict from a corrupted
        # file. Audit pass 40.
        events = [e for e in events if isinstance(e, dict)]
        if not events:
            return {"status": "no_data"}

        total_revenue = sum(safe_float(e.get("revenue")) for e in events)
        total_cost = sum(safe_float(e.get("cost")) for e in events)
        # ``int(e.get("conversions", 0))`` crashed on None /
        # non-numeric strings. safe_int handles both.
        total_conversions = sum(safe_int(e.get("conversions")) for e in events)
        total_impressions = sum(safe_int(e.get("impressions")) for e in events)
        total_clicks = sum(safe_int(e.get("clicks")) for e in events)

        return {
            "total_revenue": round(total_revenue, 2),
            "total_cost": round(total_cost, 2),
            "total_profit": round(total_revenue - total_cost, 2),
            "total_conversions": total_conversions,
            "overall_ctr": round(total_clicks / total_impressions * 100, 2) if total_impressions > 0 else None,
            "overall_conversion_rate": round(total_conversions / total_impressions * 100, 2) if total_impressions > 0 else None,
            "overall_cac": round(total_cost / total_conversions, 2) if total_conversions > 0 else None,
            "overall_roas": round(total_revenue / total_cost, 2) if total_cost > 0 else None,
            "events_tracked": len(events),
        }

    def _backup_corrupted(self, path: str) -> None:
        """Move a corrupted KPI file aside with a timestamp.

        Mirrors the observability pattern established in earlier
        audit passes (StoreSnapshot, FeedbackStore, CycleJournal)
        — never silently overwrite a file that failed to
        decode; keep it around so an operator can inspect what
        went wrong.
        """
        if not os.path.exists(path):
            return
        try:
            backup = f"{path}.corrupted.{int(time.time())}"
            os.replace(path, backup)
            logger.warning("kpi_tracker: corrupted file moved to %s", backup)
        except Exception as exc:  # noqa: BLE001
            logger.warning("kpi_tracker: failed to back up corrupted file %s: %s", path, exc)

    def _append(self, name: str, entry: dict) -> None:
        with self._lock:
            path = os.path.join(_KPI_DIR, f"{name}.json")
            entries: list = []
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        loaded = json.load(f)
                    entries = loaded if isinstance(loaded, list) else []
                    if not isinstance(loaded, list):
                        # Not a list → treat as corrupted, back
                        # it up, start fresh.
                        self._backup_corrupted(path)
                        entries = []
                except (json.JSONDecodeError, OSError):
                    self._backup_corrupted(path)
                    entries = []
            entries.append(entry)
            if len(entries) > 5000:
                entries = entries[-5000:]
            # W962-51: per-pid temp suffix so concurrent
            # processes don't collide on the rename target.
            tmp = path + ".tmp." + str(os.getpid())
            try:
                with open(tmp, "w") as f:
                    json.dump(entries, f)
                os.replace(tmp, path)
            except OSError as exc:
                logger.warning("kpi_tracker: failed to write %s: %s", path, exc)
                # Best-effort cleanup of the tmp file so we
                # don't leave garbage behind.
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except OSError as exc:
                    logger.debug("KPI tmp file cleanup failed: %s", exc)

    def _load(self, name: str) -> list[dict]:
        with self._lock:
            path = os.path.join(_KPI_DIR, f"{name}.json")
            if not os.path.exists(path):
                return []
            try:
                with open(path) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._backup_corrupted(path)
                return []
            if not isinstance(data, list):
                self._backup_corrupted(path)
                return []
            return data
