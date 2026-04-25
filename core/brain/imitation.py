"""Imitation learning — infer the owner's implicit rules.

Outcome-based learning (orders/ROAS) is slow and narrow. Owners make
dozens of implicit decisions a day — approving a launch, editing a
product title, overriding an AI verdict, pasting a URL with specific
parameters. Each demonstration carries signal the brain can learn
from *before* revenue data comes in.

Module mechanics:

  1. ``record_demonstration(kind, before, after, context)`` — called
     anywhere the owner modifies brain state. Persisted as
     ``category=demonstration score=4.5``.
  2. ``diff_against_ai_would_have(demonstration)`` — what the brain
     would have chosen at the same moment; difference = owner's
     implicit preference signal.
  3. ``mine(top_k)`` — every cycle, cluster similar demonstrations
     and propose a candidate rule ("when price < $10, owner
     overrides AI and sets copy_tone=urgent"). Rules with ≥ 3
     supporting demonstrations promote to level 2 (rule).

No LLM needed for the mining; the rules are emergent from the
demonstration table. Day-7 plan synthesizer can use them as
preference priors.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("brain.imitation")

_DB_PATH = Path("data/memory_intelligence.db")
_MIN_EVIDENCE_FOR_RULE = 3


@dataclass
class Demonstration:
    id: int
    kind: str               # "approve" | "override" | "edit" | "reject"
    before: dict[str, Any]
    after: dict[str, Any]
    context: dict[str, Any]
    timestamp: float

    def diff(self) -> dict[str, Any]:
        """Shallow key-wise diff — fields whose value changed."""
        out: dict[str, Any] = {}
        for k in set(self.before) | set(self.after):
            if self.before.get(k) != self.after.get(k):
                out[k] = {
                    "before": self.before.get(k),
                    "after": self.after.get(k),
                }
        return out


@dataclass
class ImitationRule:
    trigger: dict[str, Any]      # feature pattern
    action: dict[str, Any]       # what the owner consistently does
    evidence: int                 # number of demonstrations supporting it
    confidence: float
    sample_demo_ids: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "action": self.action,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 3),
            "sample_demo_ids": self.sample_demo_ids[:5],
        }


def record_demonstration(
    kind: str,
    before: dict[str, Any],
    after: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> int:
    """Record one owner action. Returns the memory id."""
    try:
        from core.memory.unified_memory import get_unified_memory
        mi = get_unified_memory().get_memory_intelligence()
        mid = mi.create(
            category="demonstration",
            content={
                "kind": kind,
                "before": before,
                "after": after,
                "context": context or {},
            },
            action=kind,
            score=4.5,
            tags=["demonstration", "imitation", kind],
        )
        return int(mid) if mid else 0
    except Exception:
        return 0


def mine(top_k: int = 5) -> list[ImitationRule]:
    """Group demonstrations by their (kind, feature-diff key) and emit
    rules whose evidence count ≥ MIN_EVIDENCE_FOR_RULE."""
    demos = _load_demonstrations(limit=500)
    if not demos:
        return []

    # Signature = (kind, sorted diff keys)
    groups: dict[tuple, list[Demonstration]] = defaultdict(list)
    for d in demos:
        diff = d.diff()
        sig = (d.kind, tuple(sorted(diff.keys())))
        groups[sig].append(d)

    rules: list[ImitationRule] = []
    for (kind, keys), members in groups.items():
        if len(members) < _MIN_EVIDENCE_FOR_RULE:
            continue
        # Majority "after" value per diff key
        action: dict[str, Any] = {}
        for key in keys:
            values = Counter(
                json.dumps(m.after.get(key), sort_keys=True, default=str)
                for m in members
            )
            top_value, top_count = values.most_common(1)[0]
            # Only record stable after-values (>=60% consistency)
            if top_count / len(members) >= 0.6:
                try:
                    action[key] = json.loads(top_value)
                except (json.JSONDecodeError, ValueError):
                    action[key] = top_value
        if not action:
            continue
        # Trigger = most common context values across members
        trigger: dict[str, Any] = {"kind": kind}
        context_keys = Counter(
            k for m in members for k in (m.context or {}).keys()
        )
        for k, count in context_keys.items():
            if count / len(members) < 0.6:
                continue
            values = Counter(
                json.dumps(m.context.get(k), sort_keys=True, default=str)
                for m in members
            )
            top_value, top_count = values.most_common(1)[0]
            if top_count / len(members) >= 0.6:
                try:
                    trigger[k] = json.loads(top_value)
                except (json.JSONDecodeError, ValueError):
                    trigger[k] = top_value

        confidence = min(1.0, len(members) / 10.0)
        rules.append(ImitationRule(
            trigger=trigger,
            action=action,
            evidence=len(members),
            confidence=confidence,
            sample_demo_ids=[m.id for m in members],
        ))

    rules.sort(key=lambda r: (-r.evidence, -r.confidence))
    promoted = rules[:top_k]
    for r in promoted:
        _persist_rule(r)
    return promoted


# ── Internals ────────────────────────────────────────────────

def _load_demonstrations(limit: int) -> list[Demonstration]:
    if not _DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, content, timestamp FROM memories "
            "WHERE category='demonstration' "
            "ORDER BY timestamp DESC LIMIT ?",
            (int(limit),),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    out: list[Demonstration] = []
    for mid, content_json, ts in rows:
        try:
            c = json.loads(content_json or "{}")
        except (json.JSONDecodeError, ValueError):
            continue
        out.append(Demonstration(
            id=int(mid),
            kind=str(c.get("kind") or "edit"),
            before=dict(c.get("before") or {}),
            after=dict(c.get("after") or {}),
            context=dict(c.get("context") or {}),
            timestamp=float(ts or 0),
        ))
    return out


def _persist_rule(rule: ImitationRule) -> None:
    try:
        from core.memory.unified_memory import get_unified_memory
        mi = get_unified_memory().get_memory_intelligence()
        mi.create(
            category="imitation_rule",
            content=rule.as_dict(),
            action="mined_from_demos",
            score=3.0 + 2.0 * rule.confidence,
            memory_type="semantic",
            tags=["imitation", "mined_rule"],
        )
    except Exception as exc:
        logger.debug("imitation rule persist failed: %s", exc)
