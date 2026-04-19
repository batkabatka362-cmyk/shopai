"""Dialog memory — conversational state across owner turns.

Owners don't ask questions in single-shot RPC style. They have
back-and-forth: *"кill bad audio ads"* → *"actually, scale them
instead"* → *"how much budget?"*. Each turn refers implicitly to the
last (pronoun, ellipsis, "instead", "also"). Without dialog memory
the brain treats each message in isolation and feels lobotomised.

This module keeps a small in-memory + SQLite-persisted dialog
session per (owner_id, channel). Each turn is recorded with:

  • role        — "owner" | "brain"
  • text        — raw message
  • intent      — extracted (e.g. "kill_ad", "ask_budget", …)
  • entities    — extracted slots (niche, sku, amount …)
  • references  — what prior turn ids this turn likely refers to
  • ts          — wall-clock

Intent + entity extraction is small, regex-based, deterministic, and
augmented from a synonym table that already understands the
Mongolian-transliteration commerce vocabulary built up in
goal_compiler.

Pure stdlib. SQLite optional.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.dialog_memory")


Role = Literal["owner", "brain"]


@dataclass
class Turn:
    id: str
    session_id: str
    role: Role
    text: str
    intent: str = ""
    entities: dict[str, Any] = field(default_factory=dict)
    references: tuple[str, ...] = ()
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "text": self.text,
            "intent": self.intent,
            "entities": dict(self.entities),
            "references": list(self.references),
            "ts": self.ts,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS dialog_turns (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    text        TEXT NOT NULL,
    intent      TEXT NOT NULL DEFAULT '',
    entities    TEXT NOT NULL DEFAULT '{}',
    references_ TEXT NOT NULL DEFAULT '',
    ts          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_session
    ON dialog_turns(session_id, ts);
"""


# ── Intent + entity extractors ─────────────────────────────

# Verb → canonical intent. Built on the same vocabulary the
# goal_compiler uses, plus a few dialog-specific intents.
_INTENT_RULES: list[tuple[str, str]] = [
    # Order matters: meta-modifiers (revise/addendum/ask) win over
    # raw verbs so "actually scale them" tags as `revise`, not `scale`.
    (r"\b(actually|instead|haritsuul)\b", "revise"),
    (r"\b(also|too|deer ni|nemj)\b", "addendum"),
    (r"\b(why|yagaad|how)\b", "ask_explanation"),
    (r"\b(when|hezee)\b", "ask_when"),
    (r"\b(budget|spend|hudliin|tugrug|usd|\$)\b", "ask_budget"),
    (r"\b(report|show|tell|namd)\b", "report"),
    (r"\b(thanks|sain|baisan)\b", "ack"),
    (r"\b(kill|stop|pause|zogso)\b", "kill"),
    (r"\b(scale|grow|increase|nem)\b", "scale"),
    (r"\b(launch|start|ehlu)\b", "launch"),
    (r"\b(publish|post|tav)\w*", "publish"),
    (r"\b(sync|import|ingest)\b", "sync"),
    (r"\b(refund|buts)\w*", "refund"),
]


_NUMERIC_AMOUNT = re.compile(
    r"\$?\s*(\d+(?:\.\d+)?)\s*(?:/?\s*(?:day|day|udur|өдөр))?",
    re.IGNORECASE,
)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_NICHE_HINTS = re.compile(
    r"\b(audio|fashion|home|beauty|tools|sports|tech|gadget)\b",
    re.IGNORECASE,
)
_SKU_HINT = re.compile(
    r"\b(sku[-_:#]?\s*\w+|p\d{2,}|product[\s_-]?\d+)\b",
    re.IGNORECASE,
)
_PRONOUN = re.compile(
    r"\b(it|them|those|that|this|tend|ene|ter|tedge|teriig|tegj)\b",
    re.IGNORECASE,
)


def extract_intent(text: str) -> str:
    txt = (text or "").lower()
    for pattern, intent in _INTENT_RULES:
        if re.search(pattern, txt):
            return intent
    return "unknown"


def extract_entities(text: str) -> dict[str, Any]:
    txt = (text or "")
    out: dict[str, Any] = {}
    amount = _NUMERIC_AMOUNT.findall(txt)
    if amount:
        try:
            out["amount_usd"] = float(amount[0])
        except (TypeError, ValueError):
            logger.debug("amount parse skipped: %r", amount[0])
    pct = _PERCENT.findall(txt)
    if pct:
        try:
            out["percent"] = float(pct[0])
        except (TypeError, ValueError):
            logger.debug("percent parse skipped: %r", pct[0])
    niche = _NICHE_HINTS.findall(txt)
    if niche:
        out["niche"] = niche[0].lower()
    sku = _SKU_HINT.findall(txt)
    if sku:
        out["sku_hint"] = sku[0].lower()
    return out


# ── Engine ────────────────────────────────────────────────

class DialogMemory:
    def __init__(
        self, db_path: str | Path | None = None,
        *,
        max_session_len: int = 200,
    ) -> None:
        if max_session_len < 1:
            raise ValueError("max_session_len must be ≥ 1")
        self._lock = threading.Lock()
        self._max_session_len = int(max_session_len)
        # In-memory tail per session — fast access, durable copy in SQLite
        self._sessions: dict[str, list[Turn]] = {}
        self._conn: sqlite3.Connection | None = None
        if db_path is not None:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(path), check_same_thread=False,
            )
            with self._lock:
                self._conn.execute("PRAGMA busy_timeout=5000")
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.executescript(_SCHEMA)
                self._conn.commit()

    # ── Recording ────────────────────────────────────────

    def record(
        self,
        session_id: str,
        role: Role,
        text: str,
        *,
        intent: str | None = None,
        entities: dict[str, Any] | None = None,
    ) -> Turn:
        if not session_id or not text:
            raise ValueError("session_id and text required")
        if role not in ("owner", "brain"):
            raise ValueError("role must be owner|brain")
        derived_intent = intent or (
            extract_intent(text) if role == "owner" else ""
        )
        derived_entities = entities or (
            extract_entities(text) if role == "owner" else {}
        )
        history = self._sessions.get(session_id, [])
        references = self._infer_references(text, history)
        turn = Turn(
            id=uuid.uuid4().hex,
            session_id=session_id,
            role=role,
            text=text.strip(),
            intent=derived_intent,
            entities=dict(derived_entities),
            references=references,
            ts=time.time(),
        )
        with self._lock:
            buf = self._sessions.setdefault(session_id, [])
            buf.append(turn)
            # Cap memory copy
            if len(buf) > self._max_session_len:
                self._sessions[session_id] = buf[-self._max_session_len:]
            if self._conn is not None:
                import json
                self._conn.execute(
                    "INSERT INTO dialog_turns(id, session_id, role, "
                    "text, intent, entities, references_, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        turn.id, turn.session_id, turn.role,
                        turn.text, turn.intent,
                        json.dumps(turn.entities, sort_keys=True),
                        ",".join(turn.references),
                        turn.ts,
                    ),
                )
                self._conn.commit()
        return turn

    # ── Reference inference ──────────────────────────────

    def _infer_references(
        self, text: str, history: list[Turn],
    ) -> tuple[str, ...]:
        """If the new text contains a pronoun, point at the last
        owner OR brain turn that mentioned a noun-like entity."""
        if not history:
            return ()
        if not _PRONOUN.search(text or ""):
            return ()
        # Walk history backward; first turn with non-empty entities wins.
        for prior in reversed(history):
            if prior.entities:
                return (prior.id,)
        # No anchored noun anywhere — refer to the last turn.
        return (history[-1].id,)

    # ── Queries ──────────────────────────────────────────

    def history(
        self, session_id: str, *, limit: int = 50,
    ) -> list[Turn]:
        buf = self._sessions.get(session_id, [])
        return buf[-int(max(1, limit)):]

    def latest(
        self,
        session_id: str,
        *,
        role: Role | None = None,
    ) -> Turn | None:
        buf = self._sessions.get(session_id, [])
        for t in reversed(buf):
            if role is None or t.role == role:
                return t
        return None

    def open_intent(self, session_id: str) -> str | None:
        """The most recent owner intent that has NOT been answered by
        a subsequent brain turn — useful for "what is the brain
        currently being asked to do?"."""
        buf = self._sessions.get(session_id, [])
        last_owner: Turn | None = None
        for t in reversed(buf):
            if t.role == "brain" and last_owner is None:
                # Encountered a brain turn with no pending owner intent
                return None
            if t.role == "owner":
                last_owner = t
                break
        return last_owner.intent if last_owner else None

    def merge_entities(self, session_id: str) -> dict[str, Any]:
        """Combine all entities seen in the session, with later turns
        overriding earlier ones — useful for slot-filling answers."""
        merged: dict[str, Any] = {}
        for t in self._sessions.get(session_id, []):
            for k, v in t.entities.items():
                merged[k] = v
        return merged

    # ── Reset / stats ────────────────────────────────────

    def reset(self, session_id: str) -> int:
        with self._lock:
            n = len(self._sessions.pop(session_id, []))
            if self._conn is not None:
                self._conn.execute(
                    "DELETE FROM dialog_turns WHERE session_id=?",
                    (session_id,),
                )
                self._conn.commit()
        return n

    def stats(self) -> dict[str, Any]:
        return {
            "sessions": len(self._sessions),
            "total_turns": sum(
                len(b) for b in self._sessions.values()
            ),
            "by_session": {
                sid: len(b) for sid, b in self._sessions.items()
            },
        }

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
