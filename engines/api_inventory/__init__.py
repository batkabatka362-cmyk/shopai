"""W963-98: API inventory -- surface every adapter credential's status.

Answers the operator's "what do I need to set up?" question by
joining the canonical ENV_ALIASES registry in core/adapters/config.py
with a ROLE-based grouping (what does this credential unlock?).
"""
from .flow import ApiInventoryEngine

__all__ = ["ApiInventoryEngine"]
