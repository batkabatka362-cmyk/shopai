from __future__ import annotations

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

    def initialize(self, config: dict[str, Any] | None = None) -> None:
        self.global_state.initialize(config)
        logger.info("StateManager initialized")

    def create_session(self, session_id: str | None = None) -> SessionState:
        session = SessionState(session_id)
        self._sessions[session.session_id] = session
        self.global_state.get("active_sessions", {})[session.session_id] = True
        logger.info("Session created: %s", session.session_id)
        return session

    def get_session(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def close_session(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session:
            session.close()
            active = self.global_state.get("active_sessions", {})
            active.pop(session_id, None)

    def list_sessions(self) -> list[str]:
        return list(self._sessions.keys())

    def snapshot(self) -> dict[str, Any]:
        return {
            "global": self.global_state.snapshot(),
            "runtime_metrics": self.runtime.get_metrics(),
            "active_tasks": len(self.runtime.get_active_tasks()),
            "sessions": {
                sid: s.snapshot() for sid, s in self._sessions.items()
            },
        }
