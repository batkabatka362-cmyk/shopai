"""SMS adapter family.

Concrete adapters live here (Twilio today; MessageBird,
Vonage, Plivo later). They share the :class:`SmsBaseAdapter`
skeleton and wire into the router through
:func:`core.adapters.sms.bootstrap.register_all`.
"""
from __future__ import annotations

from ._base import SmsBaseAdapter
from .twilio import TwilioAdapter

__all__ = [
    "SmsBaseAdapter",
    "TwilioAdapter",
]
