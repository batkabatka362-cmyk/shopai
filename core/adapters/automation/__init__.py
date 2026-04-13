"""Workflow automation adapters.

  * ``zapier`` — Zapier NLA (Natural Language Actions) API

Bootstrap::

    from core.adapters.automation.bootstrap import register_all
    register_all()
"""
from ._base import AutomationBaseAdapter

__all__ = ["AutomationBaseAdapter"]
