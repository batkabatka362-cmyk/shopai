"""Working-memory scratchpad — short-lived reasoning notes.

Long-term memory (MemoryIntelligence) holds episodic + semantic
knowledge. The reasoner / oracle / chat session handle medium-term
conversation context. Between them sits a gap: **in-flight
reasoning state** that multiple tool calls in a single decision
need to share, but should NOT bleed into the permanent store.

Example use cases:
  • A `reason()` chain writes its hypothesis list, then the next
    phase reads it without re-generating.
  • The planner decomposes a goal and stamps the intermediate
    subgoals so multi-agent deliberation can reference them.
  • An owner chat session pins a product_id as "the product we're
    talking about" — subsequent turns don't need to re-ask.

Design:
  • Process-wide singleton keyed by ``session_id`` (UUID, created
    on demand).
  • Each note has a namespace (``session/planner`` etc.), a key, a
    JSON-serialisable value, and a TTL — default 15 minutes.
  • Expired notes are harvested lazily on read.
  • Capacity-bounded: each namespace keeps at most N most-recent
    notes (default 50) to stay token-efficient.

Persistence is intentionally in-memory; restarts clear scratchpads
because stale intermediate reasoning is a bug, not a feature.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


_DEFAULT_TTL_S = 15 * 60
_DEFAULT_NAMESPACE_CAP = 50


@dataclass
class Note:
    key: str
    namespace: str
    value: Any
    expires_at: float
    created_at: float = 0.0

    def is_expired(self, now: float | None = None) -> bool:
        return (now or time.time()) >= self.expires_at

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "namespace": self.namespace,
            "value": self.value,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
        }


class Scratchpad:
    """A single session's scratchpad."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._lock = threading.Lock()
        # namespace -> OrderedDict[key -> Note]
        self._data: dict[str, OrderedDict[str, Note]] = {}

    def write(
        self,
        namespace: str,
        key: str,
        value: Any,
        ttl_s: int = _DEFAULT_TTL_S,
        cap: int = _DEFAULT_NAMESPACE_CAP,
    ) -> Note:
        note = Note(
            key=key, namespace=namespace, value=value,
            expires_at=time.time() + int(ttl_s),
            created_at=time.time(),
        )
        with self._lock:
            ns = self._data.setdefault(namespace, OrderedDict())
            ns[key] = note
            ns.move_to_end(key)
            while len(ns) > cap:
                ns.popitem(last=False)
        return note

    def read(self, namespace: str, key: str) -> Any | None:
        now = time.time()
        with self._lock:
            ns = self._data.get(namespace)
            if not ns:
                return None
            note = ns.get(key)
            if note is None:
                return None
            if note.is_expired(now):
                ns.pop(key, None)
                return None
            return note.value

    def delete(self, namespace: str, key: str) -> bool:
        with self._lock:
            ns = self._data.get(namespace)
            if not ns or key not in ns:
                return False
            ns.pop(key, None)
            return True

    def list_namespace(self, namespace: str) -> list[Note]:
        now = time.time()
        with self._lock:
            ns = self._data.get(namespace) or OrderedDict()
            live: list[Note] = []
            expired_keys = []
            for k, n in ns.items():
                if n.is_expired(now):
                    expired_keys.append(k)
                else:
                    live.append(n)
            for k in expired_keys:
                ns.pop(k, None)
        return live

    def purge_expired(self) -> int:
        now = time.time()
        purged = 0
        with self._lock:
            for namespace in list(self._data.keys()):
                ns = self._data[namespace]
                for k in list(ns.keys()):
                    if ns[k].is_expired(now):
                        ns.pop(k, None)
                        purged += 1
                if not ns:
                    self._data.pop(namespace, None)
        return purged

    def size(self) -> int:
        with self._lock:
            return sum(len(ns) for ns in self._data.values())

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "session_id": self.session_id,
                "size": self.size(),
                "namespaces": {
                    ns: [n.as_dict() for n in ordered.values()]
                    for ns, ordered in self._data.items()
                },
            }


# ── Global registry keyed by session id ─────────────────────

_registry_lock = threading.Lock()
_registry: dict[str, Scratchpad] = {}


def session(session_id: str | None = None) -> Scratchpad:
    """Return the scratchpad for *session_id*, creating one on demand.

    Omitted session_id → creates a fresh random-UUID session. Callers
    that want stable context across calls must pass the id back in."""
    sid = session_id or f"sp_{uuid.uuid4().hex[:12]}"
    with _registry_lock:
        pad = _registry.get(sid)
        if pad is None:
            pad = Scratchpad(sid)
            _registry[sid] = pad
    return pad


def drop_session(session_id: str) -> bool:
    with _registry_lock:
        return _registry.pop(session_id, None) is not None


def purge_all_expired() -> int:
    purged = 0
    with _registry_lock:
        sids = list(_registry.keys())
    for sid in sids:
        purged += _registry[sid].purge_expired()
    return purged


def stats() -> dict[str, Any]:
    with _registry_lock:
        sessions = list(_registry.values())
    return {
        "session_count": len(sessions),
        "total_notes": sum(s.size() for s in sessions),
    }
