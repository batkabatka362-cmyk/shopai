"""Cart Recovery Engine — public API.

Recovers abandoned carts through targeted interventions: emails, popups,
discounts, and retargeting.

Exports only the CartRecoveryEngine orchestrator class.
"""
from .flow import CartRecoveryEngine

__all__ = ["CartRecoveryEngine"]
