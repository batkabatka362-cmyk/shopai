"""Coordination subpackage — task coordination, consensus, and conflict resolution."""

from agents.coordination.coordinator import Coordinator
from agents.coordination.consensus import Consensus
from agents.coordination.conflict_resolver import ConflictResolver

__all__ = ["Coordinator", "Consensus", "ConflictResolver"]
