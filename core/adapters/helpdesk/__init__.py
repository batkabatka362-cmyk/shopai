"""Helpdesk / customer support adapters.

  * ``intercom`` — Intercom Conversations + Contacts API

Bootstrap::

    from core.adapters.helpdesk.bootstrap import register_all
    register_all()
"""
from ._base import HelpdeskBaseAdapter

__all__ = ["HelpdeskBaseAdapter"]
