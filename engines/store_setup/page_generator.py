"""Niche-aware standard storefront page generator.

Every Shopify store needs a handful of standard pages beyond
the product / collection grid: About, Contact, FAQ, Shipping
info. Manually drafting + pasting these is the same friction
that legal policies had pre-PR #363.

This module generates HTML bodies for those pages with niche
and brand interpolation. Operator pairs it with
``page_applier.apply_pages`` to push them via the existing
``SHOPIFY_CREATE_PAGE`` adapter.

Return shape::

    {
        "About": "<h1>About Acme</h1>...",
        "Contact": "<h1>Contact Us</h1>...",
        "FAQ": "<h1>Frequently Asked Questions</h1>...",
        "Shipping & Returns": "<h1>Shipping...</h1>...",
    }

The keys are the page TITLES (used as-is by
``SHOPIFY_CREATE_PAGE``); the applier derives handles
(``about``, ``contact``, ``faq``, ``shipping-returns``)
deterministically.
"""
from __future__ import annotations

_NICHE_TAGLINES: dict[str, str] = {
    "fashion": (
        "Curated fashion for everyday confidence."
    ),
    "beauty": (
        "Clean beauty, formulated for results."
    ),
    "home": (
        "Thoughtful home goods, built to last."
    ),
    "tech": (
        "Premium tech accessories that just work."
    ),
    "food": (
        "Artisanal food + drink, straight to your door."
    ),
    "general": (
        "Quality products you can trust."
    ),
}


def _about_body(
    store_name: str, niche: str, founder_name: str | None,
) -> str:
    tagline = _NICHE_TAGLINES.get(
        niche, _NICHE_TAGLINES["general"],
    )
    founder_line = (
        f"<p>Founded by {founder_name}, {store_name} grew "
        f"out of a simple belief: customers deserve better.</p>"
        if founder_name else
        f"<p>{store_name} was founded on a simple belief: "
        f"customers deserve better.</p>"
    )
    return (
        f"<h1>About {store_name}</h1>"
        f"<p><em>{tagline}</em></p>"
        f"{founder_line}"
        "<p>Every product we ship has been tested by our "
        "team. Every email we send has been read first. "
        "Every customer email gets a human response, "
        "fast.</p>"
        "<h2>Our promise</h2>"
        "<ul>"
        "<li><strong>Quality first:</strong> we don't ship "
        "what we wouldn't use ourselves.</li>"
        "<li><strong>Fast support:</strong> 24-hour response "
        "to every inquiry.</li>"
        "<li><strong>Honest pricing:</strong> no hidden fees, "
        "no fake discounts.</li>"
        "</ul>"
    )


def _contact_body(
    store_name: str, support_email: str | None,
) -> str:
    contact_line = (
        f"<li><strong>Email:</strong> "
        f"<a href=\"mailto:{support_email}\">"
        f"{support_email}</a></li>"
        if support_email else
        "<li><strong>Form:</strong> use the "
        "<a href=\"/pages/contact\">contact form</a> on "
        "this page.</li>"
    )
    return (
        "<h1>Contact Us</h1>"
        f"<p>Questions about {store_name}? Order issues? "
        "Wholesale inquiries? We're here.</p>"
        "<h2>Reach us</h2>"
        "<ul>"
        f"{contact_line}"
        "<li><strong>Hours:</strong> Monday-Friday, "
        "9am-5pm</li>"
        "</ul>"
        "<p>We aim to respond within 24 business hours. "
        "For order-specific questions, please include your "
        "order number.</p>"
    )


def _faq_body(store_name: str, niche: str) -> str:
    refund_window = {
        "fashion": "14 days",
        "food": "no returns (perishable)",
        "general": "30 days",
    }.get(niche, "30 days")
    return (
        "<h1>Frequently Asked Questions</h1>"
        "<h2>Orders &amp; Shipping</h2>"
        "<h3>How long until my order ships?</h3>"
        "<p>Orders typically ship within 1-3 business days "
        "of payment confirmation.</p>"
        "<h3>Do you ship internationally?</h3>"
        "<p>Yes, we ship to most countries. International "
        "delivery takes 7-21 business days; customs delays "
        "may apply.</p>"
        "<h3>How can I track my order?</h3>"
        "<p>Once your order ships, you'll receive a "
        "tracking link by email.</p>"
        "<h2>Returns &amp; Refunds</h2>"
        "<h3>What's your return policy?</h3>"
        f"<p>{store_name} offers {refund_window} returns "
        "for unused items in original packaging. See our "
        "<a href=\"/policies/refund-policy\">refund "
        "policy</a> for details.</p>"
        "<h3>How long do refunds take?</h3>"
        "<p>Approved refunds are processed within 5-10 "
        "business days to the original payment method.</p>"
        "<h2>Products</h2>"
        "<h3>Are your products authentic?</h3>"
        "<p>Every product is sourced directly from the "
        "manufacturer or authorized distributors. We never "
        "sell counterfeits.</p>"
    )


def _shipping_body(store_name: str) -> str:
    return (
        "<h1>Shipping &amp; Returns</h1>"
        f"<p>{store_name} ships worldwide. Here's what to "
        "expect.</p>"
        "<h2>Processing time</h2>"
        "<p>Most orders ship within 1-3 business days of "
        "payment.</p>"
        "<h2>Delivery times</h2>"
        "<ul>"
        "<li><strong>Domestic:</strong> 3-7 business days "
        "after shipping.</li>"
        "<li><strong>International:</strong> 7-21 business "
        "days; customs delays possible.</li>"
        "</ul>"
        "<h2>Shipping costs</h2>"
        "<p>Calculated at checkout based on weight + "
        "destination.</p>"
        "<h2>Returns</h2>"
        "<p>See our <a href=\"/policies/refund-policy\">"
        "refund policy</a> for full details on returns "
        "and refunds.</p>"
    )


_PAGE_BUILDERS = {
    "About": _about_body,
    "Contact": _contact_body,
    "FAQ": _faq_body,
    "Shipping & Returns": _shipping_body,
}


def generate_pages(
    *,
    store_name: str,
    niche: str = "general",
    founder_name: str | None = None,
    support_email: str | None = None,
) -> dict[str, str]:
    """Generate HTML bodies for the 4 standard storefront pages.

    Args:
        store_name: Display name (interpolated into bodies).
            Empty/whitespace string returns an empty dict.
        niche: Lowercase niche key for tone hints. Unknown
            niches fall back to ``general``.
        founder_name: Optional founder name for the About page.
            When None, the page uses a brand-only origin
            sentence.
        support_email: Real customer-support email shown on the
            Contact page. When None / empty / a placeholder
            domain (example.com, test.com, localhost), the
            Contact page falls back to a /pages/contact form
            link -- never to a fake mailto.

    Returns:
        ``{page_title: html_body}``. Pass straight into
        :func:`page_applier.apply_pages`.
    """
    name = (store_name or "").strip()
    if not name:
        return {}
    niche_n = (niche or "general").strip().lower() or "general"
    safe_email = _sanitize_email(support_email)

    out: dict[str, str] = {}
    for title, builder in _PAGE_BUILDERS.items():
        try:
            if builder is _about_body:
                out[title] = builder(name, niche_n, founder_name)
            elif builder is _faq_body:
                out[title] = builder(name, niche_n)
            elif builder is _contact_body:
                out[title] = builder(name, safe_email)
            else:
                out[title] = builder(name)
        except Exception:  # noqa: BLE001
            continue
    return out


_PLACEHOLDER_DOMAINS: frozenset[str] = frozenset({
    "example.com", "example.org", "example.net",
    "test.com", "localhost", "invalid",
})


def _sanitize_email(value: str | None) -> str | None:
    """Reject placeholder / clearly-fake emails so the Contact
    page never ships a working-looking mailto that bounces.
    """
    raw = (value or "").strip()
    if not raw or "@" not in raw:
        return None
    domain = raw.rsplit("@", 1)[-1].lower()
    if domain in _PLACEHOLDER_DOMAINS:
        return None
    return raw
