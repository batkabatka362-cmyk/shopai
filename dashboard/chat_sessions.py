"""Persistent chat session store — Option J.

A tiny JSON-backed store that lets the dashboard remember chat
transcripts across page reloads and browsers. Lives on disk at
``~/.shopai/chat_sessions.json`` by default so a single-operator box
naturally gets one inbox regardless of which tab they opened.

Design notes
------------
* Single file, read-modify-write under a process-wide ``threading.Lock``.
  Fine for a single-operator dashboard; if we ever hit meaningful
  concurrency we'll graduate to SQLite.
* Hard caps on sessions (``MAX_SESSIONS``) and turns per session
  (``MAX_TURNS``) so a runaway client can't balloon the file.
* Every mutation writes the whole file atomically via temp-file +
  rename so we never leave a half-written JSON behind.
* Fail-soft on any I/O or parse error: the store behaves like an empty
  store rather than crashing the chat endpoint.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("dashboard.chat_sessions")


# Tunables — centralised so tests can monkeypatch without reaching into
# the store implementation.
MAX_SESSIONS = 50
MAX_TURNS = 50
MAX_TITLE_LEN = 80
MAX_CONTENT_LEN = 4000


def _default_store_path() -> Path:
    """Location for the on-disk sessions file.

    Honors ``SHOPAI_CHAT_SESSIONS_PATH`` so tests and ops can redirect
    storage without touching the user's real inbox.
    """
    override = os.environ.get("SHOPAI_CHAT_SESSIONS_PATH")
    if override:
        return Path(override)
    return Path.home() / ".shopai" / "chat_sessions.json"


class SessionStore:
    """Thread-safe JSON-backed chat session store.

    Public surface is intentionally small:

    * ``list()`` — session summaries (no turn bodies).
    * ``get(sid)`` — one session with turns, or ``None``.
    * ``save(sid, turns, title=None)`` — upsert; returns the stored id.
    * ``delete(sid)`` — remove one session; returns True if it existed.
    * ``clear()`` — wipe the whole file. Used by tests.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path else _default_store_path()
        self._lock = threading.Lock()

    # ── Public API ─────────────────────────────────────────

    def list(self) -> list[dict[str, Any]]:
        """Return a list of session summaries, newest first."""
        with self._lock:
            data = self._read()
        out: list[dict[str, Any]] = []
        for s in data.get("sessions", []):
            out.append({
                "id": s.get("id"),
                "title": s.get("title", ""),
                "created_at": s.get("created_at", 0),
                "updated_at": s.get("updated_at", 0),
                "turn_count": len(s.get("turns", []) or []),
            })
        out.sort(key=lambda s: s["updated_at"], reverse=True)
        return out

    def get(self, sid: str) -> dict[str, Any] | None:
        with self._lock:
            data = self._read()
        for s in data.get("sessions", []):
            if s.get("id") == sid:
                # Defensive copy so callers can't mutate the file image.
                return {
                    "id": s["id"],
                    "title": s.get("title", ""),
                    "created_at": s.get("created_at", 0),
                    "updated_at": s.get("updated_at", 0),
                    "turns": list(s.get("turns", []) or []),
                }
        return None

    def save(
        self,
        sid: str | None,
        turns: list[dict],
        title: str | None = None,
    ) -> str:
        """Upsert a session. Returns the id actually written.

        When ``sid`` is falsy or unknown we mint a fresh id. When the
        client-supplied title is empty we derive one from the first user
        turn so the sidebar label isn't blank.
        """
        clean_turns = self._sanitise_turns(turns)
        now = time.time()

        with self._lock:
            data = self._read()
            sessions = data.get("sessions", [])
            existing_idx = self._index_of(sessions, sid)

            if existing_idx >= 0:
                session = sessions[existing_idx]
                session["turns"] = clean_turns
                session["updated_at"] = now
                if title:
                    session["title"] = self._clean_title(title)
                elif not session.get("title"):
                    session["title"] = self._derive_title(clean_turns)
                written_id = session["id"]
            else:
                written_id = sid or _mint_id()
                session = {
                    "id": written_id,
                    "title": self._clean_title(title)
                             if title else self._derive_title(clean_turns),
                    "created_at": now,
                    "updated_at": now,
                    "turns": clean_turns,
                }
                sessions.append(session)

            # Trim oldest sessions if we've blown the cap.
            if len(sessions) > MAX_SESSIONS:
                sessions.sort(key=lambda s: s.get("updated_at", 0))
                sessions[:] = sessions[-MAX_SESSIONS:]

            data["sessions"] = sessions
            self._write(data)
        return written_id

    def delete(self, sid: str) -> bool:
        if not sid:
            return False
        with self._lock:
            data = self._read()
            sessions = data.get("sessions", [])
            new = [s for s in sessions if s.get("id") != sid]
            if len(new) == len(sessions):
                return False
            data["sessions"] = new
            self._write(data)
        return True

    def clear(self) -> None:
        """Wipe the store. Used by tests and ``POST /api/chat/sessions``
        with ``{"action": "clear"}`` — never exposed as a plain GET."""
        with self._lock:
            self._write({"sessions": []})

    # ── Internal helpers ───────────────────────────────────

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"sessions": []}
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "chat sessions file unreadable (%s); starting fresh", exc,
            )
            return {"sessions": []}
        if not isinstance(data, dict) or "sessions" not in data:
            return {"sessions": []}
        if not isinstance(data["sessions"], list):
            data["sessions"] = []
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replace: write to temp file in the same directory,
        # then rename. Guarantees we never leave a truncated file behind.
        fd, tmp = tempfile.mkstemp(
            prefix=".chat_sessions-", suffix=".tmp",
            dir=str(self._path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except Exception:
            # Best-effort cleanup; the original file is untouched.
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def _index_of(sessions: list[dict], sid: str | None) -> int:
        if not sid:
            return -1
        for i, s in enumerate(sessions):
            if s.get("id") == sid:
                return i
        return -1

    @staticmethod
    def _sanitise_turns(turns: Any) -> list[dict]:
        """Normalise the supplied turns into ``[{role, content, ts}, ...]``.

        Drops malformed entries, trims content length, and caps the list
        to ``MAX_TURNS`` keeping the most recent slice — mirrors the
        client-side clamp so both ends agree.
        """
        if not isinstance(turns, list):
            return []
        clean: list[dict] = []
        for t in turns:
            if not isinstance(t, dict):
                continue
            role = t.get("role")
            content = t.get("content")
            if role not in ("user", "assistant") or not isinstance(content, str):
                continue
            clean.append({
                "role": role,
                "content": content[:MAX_CONTENT_LEN],
                "ts": float(t.get("ts") or time.time()),
            })
        return clean[-MAX_TURNS:]

    @staticmethod
    def _clean_title(title: str) -> str:
        return (title or "").strip().replace("\n", " ")[:MAX_TITLE_LEN]

    @staticmethod
    def _derive_title(turns: list[dict]) -> str:
        for t in turns:
            if t.get("role") == "user":
                return SessionStore._clean_title(t.get("content", ""))
        return "New chat"


def _mint_id() -> str:
    # Human-readable-ish prefix + collision-resistant suffix.
    return f"sess-{int(time.time())}-{uuid.uuid4().hex[:8]}"


# ── Module-level singleton ─────────────────────────────────

_default_store: SessionStore | None = None
_default_lock = threading.Lock()


def get_session_store() -> SessionStore:
    """Lazy singleton so the dashboard doesn't touch the filesystem at
    import time. Tests call ``reset_session_store`` + env vars to point
    at a throwaway path."""
    global _default_store
    with _default_lock:
        if _default_store is None:
            _default_store = SessionStore()
        return _default_store


def reset_session_store() -> None:
    """Drop the cached singleton — tests use this between runs."""
    global _default_store
    with _default_lock:
        _default_store = None
