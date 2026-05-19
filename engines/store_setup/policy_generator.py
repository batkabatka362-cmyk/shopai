"""Niche-aware legal policy body generator.

Every Shopify store needs legal pages (refund / privacy /
terms / shipping / etc.) -- legally required in most
jurisdictions for selling online. The standard approach is
to crib a template from another store; the autonomous
approach is to generate jurisdiction- and niche-appropriate
text per store.

This module is the FIRST cut: deterministic template-based
generation per niche, with placeholders interpolated from
the store's name + region + niche. The output is HTML so
the storefront renderer treats it as rich text. A later PR
should swap the templates for LLM-generated bodies (with
operator review) but the template path stays as the safe
default for cold starts when no LLM is configured.

Return shape::

    {
        "REFUND_POLICY": "<p>30-day refund...</p>",
        "PRIVACY_POLICY": "...",
        "TERMS_OF_SERVICE": "...",
        "SHIPPING_POLICY": "...",
        "CONTACT_INFORMATION": "...",
    }

Coverage: the 5 essential policies that every store needs
to launch. LEGAL_NOTICE and SUBSCRIPTION_POLICY are
opt-in via the ``include_legal_notice`` and
``include_subscription_policy`` kwargs since they're
EU-specific / sub-only respectively.
"""
from __future__ import annotations

from typing import Any


# Niche-specific tone adjustments
_NICHE_REFUND_WINDOWS: dict[str, int] = {
    "fashion": 14,
    "beauty": 30,
    "home": 30,
    "tech": 30,
    "food": 0,  # food typically non-refundable
    "general": 30,
}


def _refund_template(
    store_name: str, niche: str, region: str,
) -> str:
    days = _NICHE_REFUND_WINDOWS.get(
        niche.lower(), _NICHE_REFUND_WINDOWS["general"],
    )
    if days == 0:
        return (
            "<h2>Refund Policy</h2>"
            f"<p>Due to the nature of {niche} products, "
            f"all sales at {store_name} are final. We do not "
            "accept returns or refunds unless the product "
            "arrives damaged or defective.</p>"
            "<p>If your order arrives damaged, please contact "
            "us within 48 hours of delivery with photos for "
            "review.</p>"
        )
    return (
        "<h2>Refund Policy</h2>"
        f"<p>{store_name} offers a {days}-day refund policy. "
        f"You have {days} days from the date of delivery to "
        "request a refund.</p>"
        "<p>To be eligible for a refund, items must be unused, "
        "in original packaging, and accompanied by a receipt "
        "or proof of purchase.</p>"
        "<p>Once we receive your returned item, we will inspect "
        "it and notify you of the approval or rejection of "
        "your refund. Approved refunds are processed within "
        "5-10 business days to the original payment method.</p>"
        f"<p>Shipping costs are non-refundable. "
        f"{region.upper()}-based customers can ship returns "
        "to the address provided in your order confirmation.</p>"
    )


def _privacy_template(
    store_name: str, niche: str, region: str,
) -> str:
    return (
        "<h2>Privacy Policy</h2>"
        f"<p>{store_name} (\"we\", \"us\", \"our\") respects "
        "your privacy and is committed to protecting your "
        "personal data. This policy explains what we collect, "
        "how we use it, and your rights.</p>"
        "<h3>Information we collect</h3>"
        "<ul>"
        "<li>Contact information (name, email, phone, address) "
        "when you place an order or sign up.</li>"
        "<li>Payment details processed securely by our payment "
        "providers (we never store full card numbers).</li>"
        "<li>Browsing data (cookies, IP address, page views) to "
        "improve your experience.</li>"
        "</ul>"
        "<h3>How we use it</h3>"
        "<ul>"
        "<li>Fulfil and ship your orders.</li>"
        "<li>Send order confirmations and shipping updates.</li>"
        "<li>Improve our products and services.</li>"
        f"<li>Send marketing communications (with consent for "
        f"{region.upper()} customers).</li>"
        "</ul>"
        "<h3>Your rights</h3>"
        "<p>You can request access, correction, or deletion of "
        "your personal data at any time by contacting us. "
        f"EU/UK customers have additional GDPR rights. "
        f"California customers have CCPA rights. Contact us "
        "to exercise any of these rights.</p>"
    )


def _terms_template(
    store_name: str, niche: str, region: str,
) -> str:
    return (
        "<h2>Terms of Service</h2>"
        f"<p>By accessing or using {store_name}, you agree to "
        "be bound by these terms. If you don't agree, please "
        "don't use our services.</p>"
        "<h3>Eligibility</h3>"
        "<p>You must be at least 18 years old (or the age of "
        f"majority in your jurisdiction) to purchase from "
        f"{store_name}.</p>"
        "<h3>Orders and pricing</h3>"
        "<p>All prices are shown in the displayed currency and "
        "include applicable taxes where indicated. We reserve "
        "the right to refuse or cancel orders due to product "
        "availability, pricing errors, or suspected fraud.</p>"
        "<h3>Intellectual property</h3>"
        f"<p>All content on {store_name} (text, images, logos) "
        "is our property or used with permission. You may not "
        "reproduce or distribute it without written consent.</p>"
        "<h3>Limitation of liability</h3>"
        f"<p>{store_name} is not liable for indirect, "
        "incidental, or consequential damages arising from "
        "your use of our services, to the maximum extent "
        "permitted by law.</p>"
        "<h3>Changes</h3>"
        "<p>We may update these terms at any time. Continued "
        "use after changes means acceptance of the new terms.</p>"
    )


def _shipping_template(
    store_name: str, niche: str, region: str,
) -> str:
    return (
        "<h2>Shipping Policy</h2>"
        f"<p>{store_name} ships orders within 1-3 business "
        f"days of receipt. Delivery times vary by destination:</p>"
        "<ul>"
        "<li><strong>Domestic:</strong> 3-7 business days.</li>"
        "<li><strong>International:</strong> 7-21 business "
        "days (customs delays possible).</li>"
        "</ul>"
        "<p>Tracking information is provided once your order "
        "ships. Shipping costs are calculated at checkout based "
        "on weight and destination.</p>"
        "<p>For undeliverable packages returned to us, we will "
        "contact you to arrange re-shipment. Re-shipping costs "
        "are the customer's responsibility unless the failure "
        "was on our end.</p>"
    )


def _contact_template(
    store_name: str, niche: str, region: str,
) -> str:
    return (
        "<h2>Contact Us</h2>"
        f"<p>Questions or concerns? Reach out to {store_name}:</p>"
        "<ul>"
        "<li><strong>Email:</strong> support@example.com</li>"
        "<li><strong>Hours:</strong> Monday-Friday, 9am-5pm "
        f"local time ({region.upper()})</li>"
        "</ul>"
        "<p>We respond to most inquiries within 24 business "
        "hours.</p>"
    )


_TEMPLATE_FUNCTIONS: dict[str, Any] = {
    "REFUND_POLICY": _refund_template,
    "PRIVACY_POLICY": _privacy_template,
    "TERMS_OF_SERVICE": _terms_template,
    "SHIPPING_POLICY": _shipping_template,
    "CONTACT_INFORMATION": _contact_template,
}


def generate_policies(
    *,
    store_name: str,
    niche: str = "general",
    region: str = "us",
    include_legal_notice: bool = False,
    include_subscription_policy: bool = False,
) -> dict[str, str]:
    """Generate niche-aware HTML bodies for the essential
    Shopify shop policies.

    Args:
        store_name: Display name for the store (interpolated
            into policy text). Trimmed before use.
        niche: Lowercase niche key (``fashion``, ``beauty``,
            ``home``, ``tech``, ``food``, ``general``).
            Unknown values fall back to ``general``.
        region: Lowercase region code (``us``, ``eu``,
            ``uk``, ``ca``). Used for jurisdiction hints in
            the policy text.
        include_legal_notice: When True, also emit an
            ``Impressum``-style notice for EU markets.
        include_subscription_policy: When True, also emit a
            recurring-billing policy for subscription stores.

    Returns:
        Dict of ``policy_type -> html_body`` ready to pass
        straight into ``Capability.SHOPIFY_UPDATE_SHOP_POLICY``.
        Empty dict if ``store_name`` is empty.
    """
    name = (store_name or "").strip()
    if not name:
        return {}
    niche_n = (niche or "general").strip().lower() or "general"
    region_n = (region or "us").strip().lower() or "us"

    out: dict[str, str] = {}
    for policy_type, fn in _TEMPLATE_FUNCTIONS.items():
        try:
            out[policy_type] = fn(name, niche_n, region_n)
        except Exception:  # noqa: BLE001
            # Defensive: a template raising shouldn't poison
            # the batch. Skip that policy; caller still gets
            # the others.
            continue

    if include_legal_notice:
        out["LEGAL_NOTICE"] = (
            "<h2>Legal Notice / Impressum</h2>"
            f"<p>{name}</p>"
            "<p>For EU customers: this notice satisfies the "
            "Impressum requirement under German law and similar "
            "transparency rules across the EU.</p>"
            "<p>Contact: support@example.com</p>"
        )

    if include_subscription_policy:
        out["SUBSCRIPTION_POLICY"] = (
            "<h2>Subscription Policy</h2>"
            f"<p>{name} offers recurring subscription plans. "
            "Subscriptions renew automatically until cancelled.</p>"
            "<ul>"
            "<li>Cancel anytime via your account dashboard or "
            "by contacting support.</li>"
            "<li>Changes take effect at the next billing cycle.</li>"
            "<li>No refunds for already-billed cycles unless "
            "required by law.</li>"
            "</ul>"
        )

    return out
