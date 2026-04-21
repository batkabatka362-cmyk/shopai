"""AgentManager — lifecycle management for all agents."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone


class AgentManager:
    """Manages agent lifecycle: registration, start/stop, status tracking."""

    def __init__(self) -> None:
        self._agents: dict[str, dict] = {}
        # Lock guarding _agents mutations. Multiple cycles +
        # the dispatcher can race on register_agent /
        # start_agent / stop_agent — without the lock the
        # idempotency checks would observe stale state.
        self._lock = threading.Lock()

    def register_agent(self, agent_id: str, agent_type: str, config: dict) -> dict:
        """Register a new agent and return its record."""
        with self._lock:
            if agent_id in self._agents:
                raise ValueError(f"Agent already registered: {agent_id}")

            now = datetime.now(timezone.utc).isoformat()
            record = {
                "id": agent_id,
                "type": agent_type,
                "status": "registered",
                "config": dict(config) if isinstance(config, dict) else {},
                "created_at": now,
                "last_active": now,
            }
            self._agents[agent_id] = record
            return dict(record)

    def deregister_agent(self, agent_id: str) -> bool:
        """Remove an agent. Returns True if it existed."""
        with self._lock:
            if agent_id not in self._agents:
                return False
            del self._agents[agent_id]
            return True

    def get_agent(self, agent_id: str) -> dict:
        """Return agent record or raise KeyError."""
        with self._lock:
            if agent_id not in self._agents:
                raise KeyError(f"Unknown agent: {agent_id}")
            return dict(self._agents[agent_id])

    def list_agents(self, agent_type: str | None = None) -> list[dict]:
        """List all agents, optionally filtered by type.

        Defensive `.get("type")` so a future record missing the
        field can't crash the filter with KeyError.
        """
        with self._lock:
            if agent_type is not None:
                matching = [
                    a for a in self._agents.values()
                    if a.get("type") == agent_type
                ]
            else:
                matching = list(self._agents.values())
            return [dict(a) for a in matching]

    def start_agent(self, agent_id: str) -> dict:
        """Set agent status to 'running'."""
        with self._lock:
            if agent_id not in self._agents:
                raise KeyError(f"Unknown agent: {agent_id}")

            agent = self._agents[agent_id]
            # Defensive .get so a manually-injected record without
            # status doesn't crash the comparison with KeyError.
            if agent.get("status") == "running":
                raise RuntimeError(f"Agent {agent_id} is already running")

            agent["status"] = "running"
            agent["last_active"] = datetime.now(timezone.utc).isoformat()
            return dict(agent)

    def stop_agent(self, agent_id: str) -> dict:
        """Set agent status to 'stopped'."""
        with self._lock:
            if agent_id not in self._agents:
                raise KeyError(f"Unknown agent: {agent_id}")

            agent = self._agents[agent_id]
            if agent.get("status") == "stopped":
                raise RuntimeError(f"Agent {agent_id} is already stopped")

            agent["status"] = "stopped"
            agent["last_active"] = datetime.now(timezone.utc).isoformat()
            return dict(agent)

    def get_agent_status(self, agent_id: str) -> str:
        """Return the current status string for an agent."""
        with self._lock:
            if agent_id not in self._agents:
                raise KeyError(f"Unknown agent: {agent_id}")
            return self._agents[agent_id].get("status", "unknown")


# ── Singleton ─────────────────────────────────────────────

_SINGLETON: "AgentManager | None" = None
_SINGLETON_LOCK = threading.Lock()


def get_agent_manager() -> "AgentManager":
    """Canonical AgentManager for the process. Matches the
    pattern used by every other facade (brain, memory,
    moby_vote_comparator, …) so CLI + MCP + daemons all
    observe the same agent registry."""
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = AgentManager()
    return _SINGLETON


def reset_agent_manager_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = None
