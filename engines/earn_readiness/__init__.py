"""W963-108: earn-readiness composer.

Single command that answers "am I ready to fire the first
cycle?" by aggregating signals from api-status / go-live /
autonomy-doctor / cycle-history / api_inventory + emitting
a READY / WARN / NOT_READY verdict with prioritized
next-actions.
"""
from .flow import EarnReadinessEngine

__all__ = ["EarnReadinessEngine"]
