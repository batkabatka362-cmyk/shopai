"""CRM adapters — customer relationship management integrations.

HubSpot today; Salesforce / Pipedrive later.
"""
from __future__ import annotations

from ._base import CrmBaseAdapter
from .hubspot import HubSpotAdapter

__all__ = [
    "CrmBaseAdapter",
    "HubSpotAdapter",
]
