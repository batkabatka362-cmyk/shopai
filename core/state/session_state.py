from __future__ import annotations

from typing import Any

from utils.helpers import generate_id, timestamp_now
from utils.logger import get_logger

logger = get_logger("state.session")


class SessionState:
    """Tracks state for a single user/task session."""

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id or generate_id("sess")
        self.created_at = timestamp_now()
        self._data: dict[str, Any] = {}
        self._history: list[dict[str, Any]] = []
        self._status = "active"
        logger.info("Session %s created", self.session_id)

    @property
    def status(self) -> str:
        return self._status

    def activate(self) -> None:
        self._status = "active"

    def pause(self) -> None:
        self._status = "paused"

    def close(self) -> None:
        self._status = "closed"
        logger.info("Session %s closed", self.session_id)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._history.append({
            "action": "set",
            "key": key,
            "timestamp": timestamp_now(),
        })

    def get_history(self) -> list[dict[str, Any]]:
        return list(self._history)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self._status,
            "created_at": self.created_at,
            "data": dict(self._data),
        }
