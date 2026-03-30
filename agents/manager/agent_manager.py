"""AgentManager — lifecycle management for all agents."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


class AgentManager:
    """Manages agent lifecycle: registration, start/stop, status tracking."""

    def __init__(self) -> None:
        self._agents: dict[str, dict] = {}

    def register_agent(self, agent_id: str, agent_type: str, config: dict) -> dict:
        """Register a new agent and return its record."""
        if agent_id in self._agents:
            raise ValueError(f"Agent already registered: {agent_id}")

        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": agent_id,
            "type": agent_type,
            "status": "registered",
            "config": dict(config),
            "created_at": now,
            "last_active": now,
        }
        self._agents[agent_id] = record
        return dict(record)

    def deregister_agent(self, agent_id: str) -> bool:
        """Remove an agent. Returns True if it existed."""
        if agent_id not in self._agents:
            return False
        del self._agents[agent_id]
        return True

    def get_agent(self, agent_id: str) -> dict:
        """Return agent record or raise KeyError."""
        if agent_id not in self._agents:
            raise KeyError(f"Unknown agent: {agent_id}")
        return dict(self._agents[agent_id])

    def list_agents(self, agent_type: str | None = None) -> list[dict]:
        """List all agents, optionally filtered by type."""
        agents = self._agents.values()
        if agent_type is not None:
            agents = [a for a in agents if a["type"] == agent_type]
        else:
            agents = list(agents)
        return [dict(a) for a in agents]

    def start_agent(self, agent_id: str) -> dict:
        """Set agent status to 'running'."""
        if agent_id not in self._agents:
            raise KeyError(f"Unknown agent: {agent_id}")

        agent = self._agents[agent_id]
        if agent["status"] == "running":
            raise RuntimeError(f"Agent {agent_id} is already running")

        agent["status"] = "running"
        agent["last_active"] = datetime.now(timezone.utc).isoformat()
        return dict(agent)

    def stop_agent(self, agent_id: str) -> dict:
        """Set agent status to 'stopped'."""
        if agent_id not in self._agents:
            raise KeyError(f"Unknown agent: {agent_id}")

        agent = self._agents[agent_id]
        if agent["status"] == "stopped":
            raise RuntimeError(f"Agent {agent_id} is already stopped")

        agent["status"] = "stopped"
        agent["last_active"] = datetime.now(timezone.utc).isoformat()
        return dict(agent)

    def get_agent_status(self, agent_id: str) -> str:
        """Return the current status string for an agent."""
        if agent_id not in self._agents:
            raise KeyError(f"Unknown agent: {agent_id}")
        return self._agents[agent_id]["status"]
