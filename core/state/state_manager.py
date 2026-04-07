from __future__ import annotations

import threading
from typing import Any

from utils.logger import get_logger
from .global_state import GlobalState
from .session_state import SessionState
from .runtime_state import RuntimeState

logger = get_logger("state.manager")


class StateManager:
    """Coordinates all state layers: global, session, and runtime."""

    def __init__(self) -> None:
        self.global_state = GlobalState()
        self.runtime = RuntimeState()
        self._sessions: dict[str, SessionState] = {}
        # Lock guarding the local _sessions dict so concurrent
        # create_session / close_session calls from web sessions
        # plus the autonomous loop don't race.
        self._lock = threading.Lock()

    def initialize(self, config: dict[str, Any] | None = None) -> None:
        self.global_state.initialize(config)
        logger.info("StateManager initialized")

    def create_session(self, session_id: str | None = None) -> SessionState:
        session = SessionState(session_id)
        with self._lock:
            self._sessions[session.session_id] = session
        # Previously: `self.global_state.get("active_sessions", {})[k] = True`
        # — the classic dict.get(k, default) antipattern. If
        # active_sessions wasn't in global_state yet (init not called,
        # reset, etc.), `.get` returned a brand-new ephemeral dict
        # and the assignment was immediately discarded. Use
        # _ensure_active_sessions to mutate the real dict.
        active = self._ensure_active_sessions()
        active[session.session_id] = True
        logger.info("Session created: %s", session.session_id)
        return session

    def get_session(self, session_id: str) -> SessionState | None:
        with self._lock:
            return self._sessions.get(session_id)

    def close_session(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
        if session:
            session.close()
            active = self._ensure_active_sessions()
            active.pop(session_id, None)

    def list_sessions(self) -> list[str]:
        with self._lock:
            return list(self._sessions.keys())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            sessions_snapshot = {
                sid: s.snapshot() for sid, s in self._sessions.items()
            }
        return {
            "global": self.global_state.snapshot(),
            "runtime_metrics": self.runtime.get_metrics(),
            "active_tasks": len(self.runtime.get_active_tasks()),
            "sessions": sessions_snapshot,
        }

    def _ensure_active_sessions(self) -> dict[str, Any]:
        """Return the real `active_sessions` dict in global_state,
        creating it if missing. Replaces every `.get(k, {})` site
        in this module so we always mutate the persistent dict
        rather than an ephemeral default."""
        active = self.global_state.get("active_sessions")
        if not isinstance(active, dict):
            active = {}
            self.global_state.set("active_sessions", active)
        return active
