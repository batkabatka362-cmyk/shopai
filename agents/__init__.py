"""Agents module — multi-agent management, communication, and coordination."""

from agents.manager.agent_manager import AgentManager
from agents.manager.agent_registry import AgentRegistry
from agents.manager.agent_loader import AgentLoader
from agents.communication.message_bus import MessageBus
from agents.communication.protocol import Protocol
from agents.communication.negotiation import Negotiation
from agents.coordination.coordinator import Coordinator
from agents.coordination.consensus import Consensus
from agents.coordination.conflict_resolver import ConflictResolver

__all__ = [
    "AgentManager",
    "AgentRegistry",
    "AgentLoader",
    "MessageBus",
    "Protocol",
    "Negotiation",
    "Coordinator",
    "Consensus",
    "ConflictResolver",
]
