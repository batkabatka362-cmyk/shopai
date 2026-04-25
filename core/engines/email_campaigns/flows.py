"""Flow definitions for the email campaign engine.

A *flow* is a sequence of timed emails triggered by a specific
customer event. Each ``FlowStep`` has a ``delay_minutes`` offset
from the enrollment timestamp + a ``subject`` / ``body``
template with ``{placeholder}`` tags filled from per-enrollment
context.

Four canonical flows — same set the old
``execution/marketing/email_sequences.py`` defined, but now with
proper typed structure + longer, more specific copy the brain
can A/B test over time.

Pure data — no side effects, no IO. Safe to ``import *``.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FlowStep:
    """One email inside a flow.

    ``delay_minutes`` is offset from the enrollment moment, not
    from the previous step. Steps fire in sorted order so this
    also forms the sort key. All timing math uses minutes
    (instead of days) so tests can exercise the scheduler
    without waiting in real time.
    """

    step_id: str                     # unique within the flow
    delay_minutes: int               # offset from enrollment
    subject: str                     # template with {tags}
    body: str                        # template with {tags}
    # Required context keys the body/subject reference. If any
    # are missing at render time, the dispatcher skips the send
    # (not a silent failure — marks status=skipped_missing_ctx).
    required_context: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.delay_minutes < 0:
            raise ValueError(
                f"step {self.step_id}: delay_minutes must "
                f"be >= 0",
            )
        if not self.subject.strip() or not self.body.strip():
            raise ValueError(
                f"step {self.step_id}: subject + body required",
            )


@dataclass(frozen=True)
class Flow:
    """A complete campaign flow — e.g. ``abandoned_cart``."""

    flow_id: str
    description: str
    steps: tuple[FlowStep, ...]

    def ordered_steps(self) -> tuple[FlowStep, ...]:
        """Steps by delay_minutes — the schedule sort key."""
        return tuple(
            sorted(self.steps, key=lambda s: s.delay_minutes)
        )


# ── Day → minutes helpers (readability) ──────────────────

_DAY = 24 * 60
_HOUR = 60


# ── Flow definitions ─────────────────────────────────────

_WELCOME = Flow(
    flow_id="welcome",
    description=(
        "New subscriber — 3 emails across first week. Frame: "
        "welcome + product discovery + deadline for discount."
    ),
    steps=(
        FlowStep(
            step_id="welcome_intro",
            delay_minutes=0,
            subject=(
                "Welcome to {store_name} — your 15% off is inside"
            ),
            body=(
                "Hi {first_name},\n\n"
                "Thanks for joining {store_name}. Here's 15% off "
                "your first order — use code {discount_code} at "
                "checkout.\n\n"
                "Browse our best sellers: {store_url}\n\n"
                "— The {store_name} team"
            ),
            required_context=(
                "first_name", "store_name", "store_url",
                "discount_code",
            ),
        ),
        FlowStep(
            step_id="welcome_top_picks",
            delay_minutes=3 * _DAY,
            subject="Our most-loved products, hand-picked for you",
            body=(
                "Hi {first_name},\n\n"
                "Since you just joined {store_name}, here are the "
                "three products our community loves most:\n\n"
                "{top_products}\n\n"
                "Your 15% off code is still active: "
                "{discount_code}\n\n"
                "{store_url}"
            ),
            required_context=(
                "first_name", "store_name", "store_url",
                "top_products", "discount_code",
            ),
        ),
        FlowStep(
            step_id="welcome_deadline",
            delay_minutes=7 * _DAY,
            subject=(
                "Last chance — your 15% off expires tomorrow"
            ),
            body=(
                "Hi {first_name},\n\n"
                "Heads up — your {discount_code} code expires "
                "in 24 hours. If there's anything you've had "
                "your eye on, now's the time.\n\n"
                "{store_url}\n\n"
                "— {store_name}"
            ),
            required_context=(
                "first_name", "store_name", "store_url",
                "discount_code",
            ),
        ),
    ),
)


_ABANDONED_CART = Flow(
    flow_id="abandoned_cart",
    description=(
        "Buyer added to cart but didn't check out. Two emails "
        "across 24h — gentle reminder then a 10% nudge."
    ),
    steps=(
        FlowStep(
            step_id="abandoned_reminder",
            delay_minutes=1 * _HOUR,
            subject="You left {item_name} behind — still yours",
            body=(
                "Hi {first_name},\n\n"
                "Your {item_name} is still in your cart — we "
                "held it for you.\n\n"
                "Finish your order: {cart_url}\n\n"
                "If you have questions, just reply to this email."
            ),
            required_context=(
                "first_name", "item_name", "cart_url",
            ),
        ),
        FlowStep(
            step_id="abandoned_discount",
            delay_minutes=1 * _DAY,
            subject="Still thinking? Here's 10% off {item_name}",
            body=(
                "Hi {first_name},\n\n"
                "We held {item_name} in your cart one more "
                "day. Use code {discount_code} for 10% off:\n\n"
                "{cart_url}\n\n"
                "This offer expires in 24 hours."
            ),
            required_context=(
                "first_name", "item_name", "cart_url",
                "discount_code",
            ),
        ),
    ),
)


_POST_PURCHASE = Flow(
    flow_id="post_purchase",
    description=(
        "Customer just bought. Thank-you + review request + "
        "cross-sell at 2-week mark."
    ),
    steps=(
        FlowStep(
            step_id="post_thank_you",
            delay_minutes=3 * _DAY,
            subject="How's your {product_name}?",
            body=(
                "Hi {first_name},\n\n"
                "Just checking in — your {product_name} arrived "
                "a few days ago. We hope it's living up to the "
                "hype.\n\n"
                "If you have 30 seconds, we'd love a review: "
                "{review_url}\n\n"
                "Thanks for choosing {store_name}."
            ),
            required_context=(
                "first_name", "product_name", "review_url",
                "store_name",
            ),
        ),
        FlowStep(
            step_id="post_cross_sell",
            delay_minutes=14 * _DAY,
            subject="Based on your last order — hand-picked for you",
            body=(
                "Hi {first_name},\n\n"
                "Customers who bought {product_name} also loved:\n\n"
                "{recommendations}\n\n"
                "Use code {discount_code} for 10% off your next "
                "order: {store_url}"
            ),
            required_context=(
                "first_name", "product_name", "recommendations",
                "store_url", "discount_code",
            ),
        ),
    ),
)


_WIN_BACK = Flow(
    flow_id="win_back",
    description=(
        "Inactive customer (no order in 60+ days). One email, "
        "20% off — bigger hook than first-time welcome."
    ),
    steps=(
        FlowStep(
            step_id="win_back_offer",
            delay_minutes=0,
            subject="We miss you — here's 20% off, on us",
            body=(
                "Hi {first_name},\n\n"
                "It's been a while since your last order at "
                "{store_name}. We've added a bunch of new "
                "products and wanted to say: come back, and "
                "we'll throw in 20% off.\n\n"
                "Use code {discount_code} at checkout: "
                "{store_url}\n\n"
                "Expires in 14 days."
            ),
            required_context=(
                "first_name", "store_name", "store_url",
                "discount_code",
            ),
        ),
    ),
)


#: Canonical registry of every flow keyed by ``flow_id``.
FLOWS: dict[str, Flow] = {
    _WELCOME.flow_id: _WELCOME,
    _ABANDONED_CART.flow_id: _ABANDONED_CART,
    _POST_PURCHASE.flow_id: _POST_PURCHASE,
    _WIN_BACK.flow_id: _WIN_BACK,
}


def get_flow(flow_id: str) -> Flow | None:
    """Return the flow by id, or None if unknown."""
    return FLOWS.get(flow_id)


def list_flow_ids() -> list[str]:
    return sorted(FLOWS.keys())
