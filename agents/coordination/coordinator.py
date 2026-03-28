"""Coordinator — coordinates multi-agent tasks."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
from agents.manager.agent_manager import AgentManager

logger = get_logger("agents.coordinator")


class Coordinator:
    def __init__(self, agent_manager: AgentManager | None = None) -> None:
        self._manager = agent_manager or AgentManager()

    def coordinate(self, task: dict[str, Any], agent_roles: list[str]) -> dict[str, Any]:
        results = {}
        for role in agent_roles:
            agent_id = self._manager.create_agent(role)
            self._manager.assign_task(agent_id, task)
            results[role] = {"agent_id": agent_id, "status": "assigned"}
        logger.info("Coordinated %d agents for task", len(agent_roles))
        return {"status": "coordinated", "agents": results}
