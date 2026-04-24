"""Social scheduler — queue + publish organic posts.

Engine wraps the new SOCIAL_* adapter surface with two
responsibilities:

  1. Queue posts for the future (SQLite-backed so the queue
     survives daemon restarts).
  2. Process the queue on each autopilot cycle — ship posts
     whose ``publish_at`` has passed to the configured
     platforms via the SmartRouter.

Public surface:

    from engines.social_scheduler import SocialScheduler

    sch = SocialScheduler.open()
    sch.enqueue(
        platforms=("instagram", "facebook_page"),
        text="Cozy mushroom lamp — new drop live.",
        image_url="https://cdn.../hero.jpg",
        publish_at_unix=1800000000,
        trace_id="winner:P-12345",
    )
    summary = sch.process_due(router=router)
    # {"published": 2, "failed": 0, "skipped": 0}
"""
from engines.social_scheduler.scheduler import (
    SocialPost,
    SocialScheduler,
)

__all__ = ["SocialPost", "SocialScheduler"]
