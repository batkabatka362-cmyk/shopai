"""Persistent rationale ledger — owner-auditable decision traces.

Track 4 of AGI_HARDENING_PLAN. ``DecisionRationaleBuilder`` in
core/brain gathers a hierarchical rationale per decision into
memory. That's perfect for in-flight inspection but lost on
restart. This module writes the built Rationale to SQLite so
the owner can replay any decision months later:

    shopai why <decision_id>

Surface:

  * ``record(rationale_like)`` — accepts a ``Rationale``
    dataclass (or any object exposing decision_id + root tree)
    and serialises to JSON in one row.
  * ``get(decision_id)`` — returns the stored dict or None.
  * ``recent(limit)`` — newest first.
  * ``explain(decision_id)`` — owner-readable plain-text
    formatted tree.

Tolerant of multiple rationale shapes (Sprint 3's shipped
builder has RationaleNode with .id / .label / .detail /
.children / .ts / .weight — we serialise the tree via a
bounded walk with a node_limit to guard pathological inputs).

Pure stdlib. Thread-safe (RLock). LLM-free.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("core.decision.rationale_ledger")


_NODE_LIMIT = 1024


_SCHEMA = """
CREATE TABLE IF NOT EXISTS rationales (
    decision_id  TEXT PRIMARY KEY,
    summary      TEXT NOT NULL DEFAULT '',
    tree_json    TEXT NOT NULL DEFAULT '{}',
    ts           REAL NOT NULL,
    node_count   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_rationale_ts
    ON rationales(ts);
"""


@dataclass
class RationaleRecord:
    decision_id: str
    summary: str
    tree: dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0
    node_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "summary": self.summary,
            "tree": dict(self.tree),
            "ts": self.ts,
            "node_count": self.node_count,
        }


def _serialise_node(
    node: Any, *, budget: list[int],
) -> dict[str, Any]:
    """Serialise one rationale node. ``budget`` is a mutable
    [remaining] list so we share it across the recursion."""
    if budget[0] <= 0:
        return {"truncated": True}
    budget[0] -= 1

    def _g(name: str, default: Any = None) -> Any:
        if isinstance(node, dict):
            return node.get(name, default)
        return getattr(node, name, default)

    children = _g("children", []) or []
    return {
        "id": str(_g("id") or ""),
        "label": str(_g("label") or ""),
        "detail": str(_g("detail") or ""),
        "weight": float(_g("weight", 0.0) or 0.0),
        "ts": float(_g("ts", 0.0) or 0.0),
        "children": [
            _serialise_node(c, budget=budget)
            for c in children
            if budget[0] > 0
        ],
    }


def _count_nodes(tree: dict[str, Any]) -> int:
    if not isinstance(tree, dict):
        return 0
    total = 1
    for child in tree.get("children") or []:
        total += _count_nodes(child)
    return total


class PersistentRationaleLedger:
    """SQLite-backed rationale archive."""

    def __init__(
        self,
        db_path: str | Path = "data/rationale_ledger.db",
        *,
        now_fn: Any = None,
    ) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(
            parents=True, exist_ok=True,
        )
        self._lock = threading.RLock()
        self._now_fn = now_fn or time.time
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False,
        )
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Record ───────────────────────────────────────────

    def record(self, rationale: Any) -> RationaleRecord:
        if rationale is None:
            raise ValueError("rationale required")
        # Accept dataclass or dict; tolerate ``root`` pointing
        # to the root node OR the rationale itself being tree-
        # shaped.
        def _g(name: str, default: Any = None) -> Any:
            if isinstance(rationale, dict):
                return rationale.get(name, default)
            return getattr(rationale, name, default)

        decision_id = str(_g("decision_id") or "")
        if not decision_id:
            raise ValueError(
                "rationale.decision_id required",
            )
        summary = str(_g("summary") or "")
        ts = float(_g("ts") or self._now_fn())
        root = _g("root") or rationale
        budget = [_NODE_LIMIT]
        tree = _serialise_node(root, budget=budget)
        node_count = _count_nodes(tree)
        blob = json.dumps(tree, sort_keys=False)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO rationales("
                "decision_id, summary, tree_json, ts, "
                "node_count) VALUES(?, ?, ?, ?, ?)",
                (
                    decision_id, summary, blob,
                    ts, node_count,
                ),
            )
            self._conn.commit()
        return RationaleRecord(
            decision_id=decision_id,
            summary=summary,
            tree=tree,
            ts=ts,
            node_count=node_count,
        )

    # ── Query ────────────────────────────────────────────

    def get(
        self, decision_id: str,
    ) -> RationaleRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT decision_id, summary, tree_json, "
                "ts, node_count FROM rationales "
                "WHERE decision_id=?",
                (decision_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            tree = json.loads(row[2] or "{}")
        except (ValueError, TypeError):
            tree = {}
        return RationaleRecord(
            decision_id=row[0],
            summary=row[1],
            tree=tree,
            ts=float(row[3]),
            node_count=int(row[4]),
        )

    def recent(
        self, *, limit: int = 20,
    ) -> list[RationaleRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT decision_id FROM rationales "
                "ORDER BY ts DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [
            rec for rec in (
                self.get(r[0]) for r in rows
            )
            if rec is not None
        ]

    def explain(
        self, decision_id: str,
    ) -> str:
        rec = self.get(decision_id)
        if rec is None:
            return (
                f"No rationale found for "
                f"decision_id={decision_id!r}."
            )
        lines = [
            f"Decision: {decision_id}",
            f"Summary:  {rec.summary}",
            (
                f"When:     "
                f"{time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime(rec.ts))}"
            ),
            f"Nodes:    {rec.node_count}",
            "",
            "Trace:",
        ]
        self._format_node(rec.tree, indent=2, out=lines)
        return "\n".join(lines)

    def _format_node(
        self,
        node: dict[str, Any],
        *,
        indent: int,
        out: list[str],
    ) -> None:
        if not isinstance(node, dict):
            return
        if node.get("truncated"):
            out.append(" " * indent + "…(truncated)")
            return
        label = node.get("label", "")
        detail = node.get("detail", "")
        weight = node.get("weight", 0.0)
        tag = f"[{weight:+.2f}] " if weight else ""
        line = " " * indent + f"• {tag}{label}"
        if detail:
            line += f" — {detail[:80]}"
        out.append(line)
        for child in node.get("children", []) or []:
            self._format_node(
                child,
                indent=indent + 2,
                out=out,
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = int(self._conn.execute(
                "SELECT COUNT(*) FROM rationales",
            ).fetchone()[0])
        return {"total_rationales": total}

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ── Singleton ───────────────────────────────────────────────

_SINGLETON: PersistentRationaleLedger | None = None
_SINGLETON_LOCK = threading.Lock()


def get_rationale_ledger() -> PersistentRationaleLedger:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = PersistentRationaleLedger()
    return _SINGLETON


def reset_rationale_ledger_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            try:
                _SINGLETON.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "reset rationale_ledger close "
                    "skipped: %s", exc,
                )
        _SINGLETON = None
