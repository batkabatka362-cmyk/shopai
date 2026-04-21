"""Manager subpackage — agent lifecycle and registry."""

from agents.manager.agent_manager import (
    AgentManager,
    get_agent_manager,
    reset_agent_manager_for_tests,
)
from agents.manager.agent_registry import AgentRegistry
from agents.manager.agent_loader import AgentLoader

__all__ = [
    "AgentManager",
    "AgentRegistry",
    "AgentLoader",
    "get_agent_manager",
    "reset_agent_manager_for_tests",
]
