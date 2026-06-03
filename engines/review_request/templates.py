"""Review request email templates.

Per-niche subject + body pairs. Keeps tone matched to the
customer's purchase context: skincare buyers respond to
glow-up-focused asks; tech buyers to engineering-detail asks.

Template substitutions:
  {customer_name}   -- first name (falls back to "there")
  {product_title}   -- the product they bought
  {store_name}      -- store display name
  {review_link}     -- direct deep link to leave the review
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EmailTemplate:
    subject: str
    body_html: str


_BASELINE_BODY = """
<p>Hi {customer_name},</p>
<p>Hope you're loving your {product_title}!</p>
<p>Quick favor — would you mind sharing a short review? It
helps other shoppers decide and helps us improve. Even 1-2
sentences makes a difference.</p>
<p><a href=\"{review_link}\" style=\"display:inline-block;
padding:12px 24px; background:#000; color:#fff;
text-decoration:none; border-radius:4px;\">Leave a review</a></p>
<p>Thanks for your support,<br>
The {store_name} Team</p>
""".strip()


_NICHE_TEMPLATES: dict[str, EmailTemplate] = {
    "beauty": EmailTemplate(
        subject=(
            "{customer_name}, how is your {product_title}?"
        ),
        body_html=(
            "<p>Hi {customer_name},</p>"
            "<p>Hope your {product_title} is giving you the "
            "glow! 🌟</p>"
            "<p>If you have 30 seconds, we'd love to hear how "
            "it's working for you. Honest reviews — even "
            "one-line ones — help other shoppers find the "
            "right products and help us keep improving the "
            "lineup.</p>"
            "<p><a href=\"{review_link}\" style=\"display:"
            "inline-block; padding:12px 24px; background:#000;"
            " color:#fff; text-decoration:none; border-"
            "radius:4px;\">Share your experience</a></p>"
            "<p>With gratitude,<br>The {store_name} Team</p>"
        ),
    ),
    "fashion": EmailTemplate(
        subject=(
            "Loved your {product_title}, {customer_name}?"
        ),
        body_html=(
            "<p>Hi {customer_name},</p>"
            "<p>Curious how the {product_title} is fitting "
            "into your wardrobe. We design every piece to "
            "feel like a staple, and your feedback is how we "
            "stay honest about that.</p>"
            "<p>If you have a minute, we'd love a quick "
            "review — fit, fabric, your overall take. Even a "
            "sentence helps the next shopper decide.</p>"
            "<p><a href=\"{review_link}\" style=\"display:"
            "inline-block; padding:12px 24px; background:#000;"
            " color:#fff; text-decoration:none; border-"
            "radius:4px;\">Leave a review</a></p>"
            "<p>Cheers,<br>The {store_name} Team</p>"
        ),
    ),
    "home": EmailTemplate(
        subject=(
            "How is {product_title} working in your space?"
        ),
        body_html=(
            "<p>Hi {customer_name},</p>"
            "<p>Hope the {product_title} has found a happy "
            "home. We obsess over every detail of these "
            "pieces, and the truest measure of a good design "
            "is how it lives day-to-day.</p>"
            "<p>If you have a moment, a short review on how "
            "it's holding up would mean a lot — both for "
            "future shoppers and for us as we keep "
            "refining.</p>"
            "<p><a href=\"{review_link}\" style=\"display:"
            "inline-block; padding:12px 24px; background:#000;"
            " color:#fff; text-decoration:none; border-"
            "radius:4px;\">Share your review</a></p>"
            "<p>With thanks,<br>The {store_name} Team</p>"
        ),
    ),
    "tech": EmailTemplate(
        subject=(
            "Quick honest review of your {product_title}?"
        ),
        body_html=(
            "<p>Hi {customer_name},</p>"
            "<p>Hope the {product_title} is performing well. "
            "We engineer these products for daily reliability "
            "— and honest customer reviews are how we (and "
            "future buyers) learn what's actually working "
            "vs what needs improvement.</p>"
            "<p>Specifics help: durability, performance, fit "
            "with your setup, anything you'd change. Doesn't "
            "need to be long — a couple of sentences makes a "
            "real difference.</p>"
            "<p><a href=\"{review_link}\" style=\"display:"
            "inline-block; padding:12px 24px; background:#000;"
            " color:#fff; text-decoration:none; border-"
            "radius:4px;\">Leave a review</a></p>"
            "<p>Thanks,<br>The {store_name} Team</p>"
        ),
    ),
    "food": EmailTemplate(
        subject=(
            "How did {product_title} taste, {customer_name}?"
        ),
        body_html=(
            "<p>Hi {customer_name},</p>"
            "<p>Hope your {product_title} hit the spot. We "
            "source every product carefully and the best "
            "test of quality is whether it makes its way back "
            "into your kitchen for a second order.</p>"
            "<p>If you have a minute, we'd love your honest "
            "take — taste, freshness, anything you noticed. "
            "Your review helps the next person decide.</p>"
            "<p><a href=\"{review_link}\" style=\"display:"
            "inline-block; padding:12px 24px; background:#000;"
            " color:#fff; text-decoration:none; border-"
            "radius:4px;\">Share your taste</a></p>"
            "<p>With gratitude,<br>The {store_name} Team</p>"
        ),
    ),
}


def get_template(niche: str | None = None) -> EmailTemplate:
    """Return a per-niche template. Falls back to a baseline
    when the niche isn't recognised."""
    if niche:
        key = niche.strip().lower()
        tmpl = _NICHE_TEMPLATES.get(key)
        if tmpl:
            return tmpl
    return EmailTemplate(
        subject=(
            "{customer_name}, how was your {product_title}?"
        ),
        body_html=_BASELINE_BODY,
    )


def render(
    template: EmailTemplate,
    *,
    customer_name: str | None,
    product_title: str,
    store_name: str | None,
    review_link: str | None,
) -> tuple[str, str]:
    """Substitute the variable bindings and return (subject,
    body_html). Missing values fall back to sensible defaults so
    a missing first name doesn't print "Hi {customer_name}"."""
    ctx = {
        "customer_name": (customer_name or "there").split()[0],
        "product_title": product_title or "your order",
        "store_name": store_name or "the team",
        "review_link": review_link or "#",
    }
    return (
        template.subject.format(**ctx),
        template.body_html.format(**ctx),
    )
