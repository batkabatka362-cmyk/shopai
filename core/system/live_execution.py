"""Single source of truth for the live-execution gate.

CLAUDE.md §4b/G paranoid-mode rule: "enable_live_execution=true"
AND the per-request ``live=True`` BOTH have to be on for any
real Shopify / Meta Ads / fal.ai write. Pre-audit the checker
lived as a copy-paste ``_enable_live_execution()`` in both
``execution/launch/publisher_bundle.py`` and
``execution/launch/campaign_activator.py``. Two copies of the
same safety gate invites drift — a future bug in one would
silently diverge from the other.

This module centralises the gate so every write path agrees.
One function, one env var, one test. Callers import
``is_live_execution_enabled()`` and compose with their own
per-request ``live`` flag.

Pure stdlib. No state. No LLM.
"""
from __future__ import annotations

import os


_ENV_FLAG = "SHOPAI_ENABLE_LIVE_EXECUTION"


def is_live_execution_enabled() -> bool:
    """Return True iff live execution is enabled at the
    instance level. Callers compose with their per-request
    ``live`` bit:

        dry_run = not (request.live and
                       is_live_execution_enabled())

    This keeps a stray env flag from causing writes when the
    caller never asked for them, and vice versa.
    """
    return os.getenv(_ENV_FLAG, "") == "1"
