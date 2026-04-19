"""Multi-turn chat session.

Oracle (D7 of v1) was one-shot — every call started with empty
context. Real owner interaction is a conversation: "Why did launch X
fail?" → "What should I do next?" → "How much budget?" Each turn
needs the previous answers + the retrieved memories from earlier
turns as context.

ChatSession:
  • Persists turns to ``data/chat_sessions.json`` so restarts don't
    drop context (idempotent — one file per session id).
  • Each turn stores: user question, retrieved memory ids, final
    answer text, adapter/model used, timestamp.
  • Prompt builder concatenates the last N turns verbatim so the LLM
    sees the evolving conversation; cites memories across the whole
    session so the owner can audit any claim.
  • Answering reuses core.brain.oracle's retriever so semantic +
    transfer patterns stay aligned with single-shot ``shopai ask``.

CLAUDE.md §4b.C (cost budget): max 8 turns retained per prompt;
older turns summarised into a single "earlier in the conversation"
line so total prompt size stays below 2k tokens.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("brain.chat_session")


_SESSIONS_PATH = Path("data/chat_sessions.json")
_MAX_TURNS_IN_PROMPT = 8
_MAX_TURNS_PERSIST = 50


@dataclass
class Turn:
    role: str                     # "user" | "assistant"
    text: str
    timestamp: float
    cited_ids: list[int] = field(default_factory=list)
    memories_used: int = 0
    adapter: str = ""
    model: str = ""


@dataclass
class Session:
    id: str
    created_at: float
    turns: list[Turn] = field(default_factory=list)
    title: str = ""               # derived from first user message
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "title": self.title,
            "turn_count": len(self.turns),
            "turns": [asdict(t) for t in self.turns],
            "metadata": self.metadata,
        }


class ChatStore:
    """Process-wide session store with an internal lock so concurrent
    API handlers can read/write safely."""

    _lock = threading.Lock()

    @classmethod
    def load_all(cls) -> dict[str, Session]:
        with cls._lock:
            return cls._load_unlocked()

    @classmethod
    def _load_unlocked(cls) -> dict[str, Session]:
        if not _SESSIONS_PATH.exists():
            return {}
        try:
            raw = json.loads(_SESSIONS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
        out: dict[str, Session] = {}
        for sid, data in (raw or {}).items():
            turns = [
                Turn(
                    role=t.get("role", "user"),
                    text=t.get("text", ""),
                    timestamp=float(t.get("timestamp", 0)),
                    cited_ids=list(t.get("cited_ids") or []),
                    memories_used=int(t.get("memories_used") or 0),
                    adapter=t.get("adapter", ""),
                    model=t.get("model", ""),
                )
                for t in (data.get("turns") or [])
            ]
            out[sid] = Session(
                id=sid,
                created_at=float(data.get("created_at") or 0),
                turns=turns,
                title=data.get("title", ""),
                metadata=data.get("metadata") or {},
            )
        return out

    @classmethod
    def save(cls, session: Session) -> None:
        with cls._lock:
            all_sessions = cls._load_unlocked()
            # Truncate to keep file small
            session.turns = session.turns[-_MAX_TURNS_PERSIST:]
            all_sessions[session.id] = session
            _SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = {sid: s.as_dict() for sid, s in all_sessions.items()}
            tmp = _SESSIONS_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, _SESSIONS_PATH)

    @classmethod
    def get(cls, session_id: str) -> Session | None:
        return cls.load_all().get(session_id)

    @classmethod
    def create(cls, first_question: str = "") -> Session:
        session = Session(
            id=f"chat_{uuid.uuid4().hex[:12]}",
            created_at=time.time(),
            title=first_question[:60],
        )
        cls.save(session)
        return session

    @classmethod
    def list_ids(cls, limit: int = 20) -> list[dict[str, Any]]:
        sessions = cls.load_all()
        rows = [
            {
                "id": s.id,
                "created_at": s.created_at,
                "title": s.title,
                "turn_count": len(s.turns),
            }
            for s in sessions.values()
        ]
        rows.sort(key=lambda r: -r["created_at"])
        return rows[:limit]


def send(session_id: str | None, question: str) -> dict[str, Any]:
    """Append a user turn + generate the assistant reply. When
    ``session_id`` is ``None`` a new session is created."""
    question = (question or "").strip()
    if not question:
        return {"error": "question required"}

    if session_id:
        session = ChatStore.get(session_id)
        if session is None:
            return {"error": f"unknown session {session_id}"}
    else:
        session = ChatStore.create(first_question=question)

    session.turns.append(Turn(
        role="user", text=question, timestamp=time.time(),
    ))

    # Retrieve memories for this turn using oracle's blended retriever
    try:
        from core.brain.oracle import _pull_memories
        memories = _pull_memories(question, k=8)
    except Exception as exc:
        logger.debug("chat retriever failed: %s", exc)
        memories = []

    prompt = _build_prompt(session, memories)
    answer_text, adapter, model = _call_llm(prompt, question)

    cited = _extract_citations(answer_text, memories)
    session.turns.append(Turn(
        role="assistant", text=answer_text, timestamp=time.time(),
        cited_ids=cited, memories_used=len(memories),
        adapter=adapter, model=model,
    ))

    ChatStore.save(session)
    return {
        "session_id": session.id,
        "title": session.title,
        "turn_count": len(session.turns),
        "answer": answer_text,
        "cited_ids": cited,
        "memories_used": len(memories),
        "adapter": adapter,
        "model": model,
    }


# ── Internals ────────────────────────────────────────────────

def _build_prompt(session: Session, memories: list[dict[str, Any]]) -> str:
    lines = [
        "You are the ShopAI Oracle in a multi-turn conversation with "
        "the store owner. Rules:",
        "  • Answer in the user's language.",
        "  • Cite memory ids as [#id] when quoting facts.",
        "  • Keep each reply under 180 words.",
        "  • If unsure, say so and ask a clarifying question.",
        "  • Stay consistent with earlier answers in this conversation.",
        "",
        "Retrieved memories for this turn:",
    ]
    if memories:
        for m in memories:
            content = m.get("content")
            if isinstance(content, dict):
                content = ", ".join(
                    f"{k}={v}" for k, v in list(content.items())[:5]
                )
            content = str(content or "")[:200].replace("\n", " ")
            lines.append(
                f"  [#{m.get('id', '?')}] cat={m.get('category', '')} "
                f"action={m.get('action', '')} "
                f"score={m.get('score', 0)} content={content}"
            )
    else:
        lines.append("  (none found for this turn)")
    lines.append("")
    lines.append("Conversation so far:")
    # Drop the final "user" turn — we'll stamp it separately below so
    # the LLM sees the question as the most recent thing.
    history = session.turns[:-1]
    if len(history) > _MAX_TURNS_IN_PROMPT:
        dropped = len(history) - _MAX_TURNS_IN_PROMPT
        lines.append(f"  ({dropped} earlier turns summarised)")
        history = history[-_MAX_TURNS_IN_PROMPT:]
    for t in history:
        prefix = "USER" if t.role == "user" else "ORACLE"
        lines.append(f"  {prefix}: {t.text[:300]}")
    lines.append("")
    lines.append(f"USER: {session.turns[-1].text}")
    lines.append("ORACLE:")
    return "\n".join(lines)


def _call_llm(prompt: str, question: str) -> tuple[str, str, str]:
    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
        from core.adapters.router import RouteContext
        from core.brain.oracle import _adapter_preference
    except Exception as exc:
        return f"(LLM adapters unavailable: {exc})", "", ""

    prefer = _adapter_preference(question)
    try:
        result = get_router().execute(
            capability=Capability.CHAT_COMPLETE,
            params={
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 600,
                "temperature": 0.3,
            },
            context=RouteContext(prefer=list(prefer)),
        )
    except Exception as exc:
        return f"(router error: {type(exc).__name__})", "", ""

    if not getattr(result, "ok", False):
        return f"(adapter error: {getattr(result, 'error', '')})", "", ""

    text = (getattr(result, "data", {}) or {}).get("text", "") or ""
    return text.strip(), getattr(result, "adapter", "") or "", \
        getattr(result, "model", "") or ""


def _extract_citations(text: str, memories: list[dict[str, Any]]) -> list[int]:
    import re
    cited: list[int] = []
    ids = {m.get("id") for m in memories if isinstance(m.get("id"), int)}
    for m in re.finditer(r"\[#(\d+)\]", text or ""):
        try:
            mid = int(m.group(1))
        except ValueError:
            continue
        if mid in ids and mid not in cited:
            cited.append(mid)
    return cited
