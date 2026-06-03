"""Welcome-series email templates.

3-email cadence keyed by stage:
  - stage_1 (immediate): brand intro + WELCOME15 discount
  - stage_2 (~48h later): best-seller showcase
  - stage_3 (~5d later): UGC / community prompt

Templates substitute:
  {customer_name}       -- first name (falls back to "there")
  {store_name}          -- store display name
  {discount_code}       -- typically WELCOME15
  {shop_url}            -- root URL for CTA links
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WelcomeEmail:
    stage: int
    subject: str
    body_html: str


_STAGE_1 = WelcomeEmail(
    stage=1,
    subject=(
        "Welcome to {store_name}, {customer_name} — here's "
        "15% off"
    ),
    body_html=(
        "<p>Hi {customer_name},</p>"
        "<p>Thanks for joining us at <b>{store_name}</b>. "
        "We obsess over every product in the lineup — "
        "carefully selected, honestly described, and made to "
        "earn a place in your routine.</p>"
        "<p>As a welcome, here's <b>15% off</b> your first "
        "order with code <b>{discount_code}</b>.</p>"
        "<p><a href=\"{shop_url}\" style=\"display:inline-"
        "block; padding:12px 24px; background:#000; "
        "color:#fff; text-decoration:none; border-radius:"
        "4px;\">Browse the shop</a></p>"
        "<p>With gratitude,<br>The {store_name} Team</p>"
    ),
)


_STAGE_2 = WelcomeEmail(
    stage=2,
    subject=(
        "{customer_name}, the bestsellers everyone is "
        "loving"
    ),
    body_html=(
        "<p>Hi {customer_name},</p>"
        "<p>Now that you've found us, here are the products "
        "our community keeps coming back to. They're chosen "
        "for a reason — and most reviewers say they delivered "
        "more than expected.</p>"
        "<p>If you saw something you liked yesterday but "
        "haven't pulled the trigger, your "
        "<b>{discount_code}</b> code is still good for one "
        "more week.</p>"
        "<p><a href=\"{shop_url}/collections/best-sellers\" "
        "style=\"display:inline-block; padding:12px 24px; "
        "background:#000; color:#fff; text-decoration:none; "
        "border-radius:4px;\">Shop the bestsellers</a></p>"
        "<p>Cheers,<br>The {store_name} Team</p>"
    ),
)


_STAGE_3 = WelcomeEmail(
    stage=3,
    subject=(
        "{customer_name}, join the {store_name} community"
    ),
    body_html=(
        "<p>Hi {customer_name},</p>"
        "<p>One thing we've learned: the most useful product "
        "intel comes from customers, not from us. So if you "
        "do end up trying something from the shop, we'd "
        "love your honest take afterward.</p>"
        "<p>In the meantime, follow along for the latest "
        "drops + customer photos that make us smile.</p>"
        "<p><a href=\"{shop_url}\" style=\"display:inline-"
        "block; padding:12px 24px; background:#000; "
        "color:#fff; text-decoration:none; border-radius:"
        "4px;\">Visit the shop</a></p>"
        "<p>With gratitude,<br>The {store_name} Team</p>"
    ),
)


_STAGES: dict[int, WelcomeEmail] = {
    1: _STAGE_1, 2: _STAGE_2, 3: _STAGE_3,
}


def get_stage(stage: int) -> WelcomeEmail:
    """Return the welcome email for the given stage (1..3).
    Falls back to stage 1 for unknown stages."""
    return _STAGES.get(stage, _STAGE_1)


def render(
    email: WelcomeEmail,
    *,
    customer_name: str | None,
    store_name: str | None,
    discount_code: str | None,
    shop_url: str | None,
) -> tuple[str, str]:
    """Substitute the bindings and return (subject, body_html)."""
    ctx = {
        "customer_name": (customer_name or "there").split()[0],
        "store_name": store_name or "the team",
        "discount_code": discount_code or "WELCOME15",
        "shop_url": shop_url or "https://shopify.com",
    }
    return (
        email.subject.format(**ctx),
        email.body_html.format(**ctx),
    )


def all_stages() -> list[int]:
    """Return the supported stage numbers."""
    return sorted(_STAGES.keys())
