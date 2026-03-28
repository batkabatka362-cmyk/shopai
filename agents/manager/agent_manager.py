"""Agent Manager — lifecycle management for agents."""
from __future__ import annotations
from typing import Any
from utils.helpers import generate_id
from utils.logger import get_logger

logger = get_logger("agents.manager")


class AgentManager:
    def __init__(self) -> None:
        self._agents: dict[str, dict[str, Any]] = {}

    def create_agent(self, role: str, config: dict[str, Any] | None = None) -> str:
        agent_id = generate_id("agent")
        self._agents[agent_id] = {"role": role, "status": "idle", "config": config or {}}
        logger.info("Created agent %s (role=%s)", agent_id, role)
        return agent_id

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        return self._agents.get(agent_id)

    def assign_task(self, agent_id: str, task: dict[str, Any]) -> bool:
        agent = self._agents.get(agent_id)
        if not agent:
            return False
        agent["status"] = "working"
        agent["current_task"] = task
        return True

    def release(self, agent_id: str) -> None:
        agent = self._agents.get(agent_id)
        if agent:
            agent["status"] = "idle"
            agent.pop("current_task", None)

    def list_agents(self, status: str | None = None) -> list[str]:
        if status:
            return [aid for aid, a in self._agents.items() if a["status"] == status]
        return list(self._agents.keys())
