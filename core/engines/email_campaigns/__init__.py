"""Email Campaign Engine — automated lifecycle flows.

Orchestrates the Brevo / Resend email adapters (commodity) into
multi-step customer flows the store's brain schedules over days
or weeks. Replaces the earlier ``execution/marketing/
email_sequences.py`` skeleton with a live, SQLite-scheduled,
adapter-aware engine.

Supported flows:

  * ``welcome``         — new subscribers, 3 emails day 0/3/7
  * ``abandoned_cart``  — cart left unconverted, 2 emails day
                          0/1 after abandonment
  * ``post_purchase``   — 2 emails day 3/14 after order paid
  * ``win_back``        — inactive customers, 1 email

Public surface::

    from core.engines.email_campaigns import get_engine

    engine = get_engine()

    # 1. Enroll a customer into a flow with per-customer context
    engine.enroll(
        "customer@example.com",
        flow="abandoned_cart",
        context={"item_name": "Galaxy Projector",
                 "cart_url": "https://deguar.myshopify.com/cart/r/abc"},
    )

    # 2. Autopilot cycle (or cron) drains due items
    report = engine.dispatch_due()
    # → {"sent": N, "errors": M, "skipped_unconfigured": K}

    # 3. Owner inspects via CLI
    #   shopai email-stats
    engine.stats()
    # → {"flows": {"post_purchase": {...}}, ...}

Architectural layering per ``docs/BUSINESS_MODEL_MATRIX.md``:

  * CORE (ours):       flow definitions, scheduler, dispatcher
  * COMMODITY (swap):  Brevo / Resend (via existing adapters)
  * WIRING (opt-in):   ``engine.enroll(...)`` call sites —
                       order_handler, customer_created webhook,
                       inactive-customer daemon sweep
"""
from core.engines.email_campaigns.engine import (
    EmailCampaignEngine,
    get_engine,
    reset_singleton_for_tests,
)
from core.engines.email_campaigns.flows import (
    FLOWS,
    Flow,
    FlowStep,
)
from core.engines.email_campaigns.queue import (
    EnrollmentStatus,
    ScheduledEmail,
    ScheduleQueue,
)

__all__ = [
    "EmailCampaignEngine",
    "get_engine",
    "reset_singleton_for_tests",
    "FLOWS",
    "Flow",
    "FlowStep",
    "EnrollmentStatus",
    "ScheduledEmail",
    "ScheduleQueue",
]
