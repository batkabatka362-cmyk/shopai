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

import logging
import os


_ENV_FLAG = "SHOPAI_ENABLE_LIVE_EXECUTION"

_logger = logging.getLogger("shopai.core.system.live_execution")


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


def check_gate_drift(
    initial_dry_run: bool,
    *,
    request_live: bool,
    step: str,
) -> bool:
    """Defensive invariant check used at money-commit points in
    the publisher + activator pipelines. If someone (or the
    owner) flips ``SHOPAI_ENABLE_LIVE_EXECUTION`` mid-launch,
    the decision's ``dry_run`` flag — computed once at entry —
    would silently disagree with the runtime gate.

    We never override the caller's already-computed flag. A
    drift means the pipeline commits with its original intent
    but the operator sees a warning log + a True return value
    so monitoring / tests can assert the drift was seen.

    Returns ``True`` when drift detected, else ``False``.
    """
    live_now = request_live and is_live_execution_enabled()
    dry_now = not live_now
    if dry_now == initial_dry_run:
        return False
    _logger.warning(
        "live-gate drift detected at step=%s: initial dry_run=%s "
        "but re-check dry_run=%s (request.live=%s, env=%s). "
        "Pipeline proceeds with initial intent.",
        step, initial_dry_run, dry_now, request_live,
        "1" if is_live_execution_enabled() else "0",
    )
    return True
