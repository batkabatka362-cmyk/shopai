"""Win-back sweep — dormant customers → email flow enrollment.

Runs once per autopilot cycle. Pulls dormant customers from
the LTV tracker, filters out anyone already enrolled in the
``win_back`` flow (idempotency + avoid enrolling the same
person twice), caps enrolments at ``max_per_cycle`` so a
newly-installed daemon with a backlog of 1000 dormant
customers doesn't dump them all on the same day, and enrols
the rest.

Pure orchestration. All business logic (who counts as
"dormant", the win_back flow steps) lives in the engines
this module glues together.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any


_logger = logging.getLogger("shopai.budget_buyer.winback")

# Cap per cycle — prevents a backlog of 500 dormant customers
# being hit all at once. 5/cycle × 12 cycles/day ≈ 60/day —
# a manageable inbox impression.
DEFAULT_MAX_PER_CYCLE = 5


@dataclass
class WinBackReport:
    dormant_total: int = 0
    already_enrolled: int = 0
    newly_enrolled: int = 0
    errors: int = 0
    errors_detail: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors_detail is None:
            self.errors_detail = []

    def as_dict(self) -> dict[str, Any]:
        return {
            "dormant_total": self.dormant_total,
            "already_enrolled": self.already_enrolled,
            "newly_enrolled": self.newly_enrolled,
            "errors": self.errors,
            "errors_detail": list(self.errors_detail[:5]),
        }


def _default_context() -> dict[str, str]:
    """Build the context dict the ``win_back`` flow expects.

    Pulls from env (SHOPAI_SHOPIFY_URL, SHOPAI_STORE_NAME,
    SHOPAI_EMAIL_COMEBACK_CODE). Caller may merge additional
    context via the ``context_override`` arg on ``sweep()``.
    """
    store_url = (os.environ.get("SHOPAI_SHOPIFY_URL") or "").strip()
    if store_url and not store_url.startswith("http"):
        store_url = f"https://{store_url}"
    return {
        "store_name": os.environ.get(
            "SHOPAI_STORE_NAME", "Deguar",
        ),
        "store_url": store_url or "",
        "discount_code": os.environ.get(
            "SHOPAI_EMAIL_COMEBACK_CODE", "COMEBACK20",
        ),
    }


def sweep(
    *,
    bb_engine: Any = None,
    email_engine: Any = None,
    max_per_cycle: int = DEFAULT_MAX_PER_CYCLE,
    context_override: dict[str, Any] | None = None,
) -> WinBackReport:
    """Enroll up to ``max_per_cycle`` dormant customers in the
    ``win_back`` email flow.

    ``bb_engine`` / ``email_engine`` are injectable for tests;
    production callers pass None and the module-level
    singletons resolve lazily.

    Skip rules:
      * Customer already has any ``win_back`` scheduled email
        (engine idempotency makes this safe either way, but
        checking up-front lets us enrol more fresh customers
        within the cap).
      * Customer has no email address stored.
      * Customer on the unsubscribe list — engine's
        ``enroll()`` catches this too + returns
        ``unsubscribed=True``; we just tally it.

    Returns a ``WinBackReport`` — autopilot cycle records
    ``newly_enrolled`` + ``errors`` on the cycle summary.
    """
    if bb_engine is None:
        from core.engines.budget_buyer import get_engine as _bb
        bb_engine = _bb()
    if email_engine is None:
        from core.engines.email_campaigns import (
            get_engine as _ec,
        )
        email_engine = _ec()

    report = WinBackReport()

    if max_per_cycle < 1:
        return report

    try:
        dormant = bb_engine.dormant_customers(limit=1000)
    except Exception as exc:  # noqa: BLE001
        report.errors += 1
        report.errors_detail.append(
            f"dormant lookup failed: {exc}",
        )
        return report

    report.dormant_total = len(dormant)
    if not dormant:
        return report

    base_ctx = _default_context()
    if context_override:
        base_ctx.update(
            {k: str(v) for k, v in context_override.items()},
        )

    newly = 0
    for customer in dormant:
        if newly >= max_per_cycle:
            break
        email = (customer.email or "").strip()
        if not email:
            continue

        # Skip customers already in the win-back flow — check
        # their existing scheduled rows. Either pending or
        # sent wins here; re-sending to someone who got the
        # email last month is noise.
        existing = email_engine.list_for_recipient(email)
        already_in_winback = any(
            r.flow_id == "win_back" for r in existing
        )
        if already_in_winback:
            report.already_enrolled += 1
            continue

        ctx = dict(base_ctx)
        # Derive first_name from email local-part as a safe
        # default — LTV store doesn't keep a first_name.
        ctx["first_name"] = (
            email.split("@", 1)[0] or "there"
        ).replace(".", " ").title()

        try:
            result = email_engine.enroll(
                email, flow="win_back", context=ctx,
            )
        except Exception as exc:  # noqa: BLE001
            report.errors += 1
            report.errors_detail.append(
                f"{email}: {type(exc).__name__}: {exc}",
            )
            continue

        if result.get("unsubscribed"):
            # Not a new enrollment, but not an error — still
            # count as "already handled" so the report makes
            # sense.
            report.already_enrolled += 1
            continue
        if result.get("enrolled", 0) > 0:
            newly += 1
            report.newly_enrolled = newly
        else:
            # enrolled=0 + skipped>0 + unsubscribed=False
            # means the flow was already in the queue
            # (partial enrollment state). Count as existing.
            report.already_enrolled += 1

    return report
