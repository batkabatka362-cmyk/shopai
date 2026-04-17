"""Helpdesk / customer support adapters.

  * ``intercom`` — Intercom Conversations + Contacts API
  * ``zendesk``  — Zendesk Ticketing v2 API
  * ``crisp``    — Crisp Chat v1 API

Bootstrap::

    from core.adapters.helpdesk.bootstrap import register_all
    register_all()
"""
from ._base import HelpdeskBaseAdapter

__all__ = ["HelpdeskBaseAdapter"]
