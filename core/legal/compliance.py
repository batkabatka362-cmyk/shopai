"""Legal page renderer — US/EU/UK-aware page templates.

Sprint 3 S3-2 (P0, L7). Before any live sale in US/EU the store
must display privacy, terms, returns, and shipping policies that
match the target market's baseline rules (CCPA for California,
GDPR for EU, UK GDPR for UK). Missing or copy-pasted policies are
a common cause of payment processor freezes and account bans.

This module is content-only: it renders the four core policy pages
as Markdown strings given a ``StoreProfile`` (name + contact email
+ region). A later iteration wires this to the Shopify pages API
via ``execution/content/publisher.py``.

Why scoped narrow:

  * Fraud-prevention value: zero. Payment risk value: high.
  * Audit-review: deterministic string output is trivially diffable
    against an owner-approved baseline, unlike LLM-generated
    copy.
  * LLM-free, pure stdlib — can ship even on an offline box.

The templates are *starter* policies written to be rule-following
but not jurisdiction-specific attorney-grade: every template ends
with an "Owner should review" block. Owner can swap in real legal
review output by providing a ``custom_sections`` override at
``render_legal_pages`` call time.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable


REGION_US = "US"
REGION_EU = "EU"
REGION_UK = "UK"

_SUPPORTED_REGIONS = (REGION_US, REGION_EU, REGION_UK)

_PAGE_KINDS = (
    "privacy",
    "terms",
    "returns",
    "shipping",
    "cookies",
)


@dataclass
class LegalPage:
    kind: str
    title: str
    markdown: str
    region: str
    updated_ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "markdown": self.markdown,
            "region": self.region,
            "updated_ts": self.updated_ts,
        }


@dataclass
class LegalPageSet:
    region: str
    store_name: str
    contact_email: str
    pages: tuple[LegalPage, ...] = field(default_factory=tuple)

    def get(self, kind: str) -> LegalPage | None:
        for p in self.pages:
            if p.kind == kind:
                return p
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "store_name": self.store_name,
            "contact_email": self.contact_email,
            "pages": [p.as_dict() for p in self.pages],
        }


# ── Section builders ───────────────────────────────────────


def _privacy(
    *, store_name: str, contact_email: str, region: str,
) -> str:
    rights = _privacy_rights_block(region)
    cookies_ref = (
        "See our Cookie Policy for how cookies are used."
    )
    return "\n".join([
        f"# Privacy Policy — {store_name}",
        "",
        "_Effective date_: " + _today_iso(),
        "",
        "## What we collect",
        "",
        "- Contact info: name, email, shipping + billing "
        "address, phone",
        "- Order history and preferences",
        "- Device + analytics data (IP, browser, page "
        "interactions) for fraud prevention and product "
        "improvement",
        "",
        "## Why we collect it",
        "",
        "- Process and ship your orders",
        "- Email order and shipping updates",
        "- Respond to customer service requests",
        "- Prevent fraud and secure our services",
        "- With your consent, marketing communications",
        "",
        "## Your rights",
        rights,
        "",
        "## Retention",
        "",
        "Order records are retained for 7 years to meet tax "
        "and accounting obligations. Marketing preferences "
        "are retained until you unsubscribe.",
        "",
        "## Sharing",
        "",
        "We do not sell personal data. We share data with "
        "the following categories of processors:",
        "",
        "- Payment processors (Shopify Payments, Stripe, "
        "PayPal) to complete transactions",
        "- Shipping carriers for delivery",
        "- Analytics and advertising partners with consent",
        "",
        "## Cookies",
        "",
        cookies_ref,
        "",
        "## Contact",
        "",
        f"Questions? Email us at **{contact_email}**.",
        "",
        "---",
        "_Owner should review with counsel before "
        "publishing — regional statutes change frequently._",
    ])


def _privacy_rights_block(region: str) -> str:
    if region == REGION_EU:
        return "\n".join([
            "",
            "Under the EU General Data Protection Regulation "
            "(GDPR) you have the right to:",
            "",
            "- Access the personal data we hold about you",
            "- Request rectification of inaccurate data",
            "- Request erasure (\"right to be forgotten\")",
            "- Restrict or object to processing",
            "- Data portability",
            "- Withdraw consent at any time",
            "- Lodge a complaint with your national data "
            "protection authority",
        ])
    if region == REGION_UK:
        return "\n".join([
            "",
            "Under the UK Data Protection Act 2018 and UK "
            "GDPR you have the right to:",
            "",
            "- Access, correct, or erase your data",
            "- Restrict or object to processing",
            "- Data portability",
            "- Complain to the UK Information "
            "Commissioner's Office (ICO)",
        ])
    # REGION_US
    return "\n".join([
        "",
        "Under the California Consumer Privacy Act (CCPA) "
        "and similar state statutes you may:",
        "",
        "- Request disclosure of categories of personal "
        "data we collect",
        "- Request deletion of personal data",
        "- Opt out of the \"sale\" or \"sharing\" of "
        "personal data (we do not sell data)",
        "- Not be discriminated against for exercising "
        "these rights",
    ])


def _terms(
    *, store_name: str, contact_email: str, region: str,
) -> str:
    governing = {
        REGION_US: "the laws of the State of Delaware, USA",
        REGION_EU: "the laws of Ireland (or your EU member "
        "state of residence, whichever affords greater "
        "protection)",
        REGION_UK: "the laws of England and Wales",
    }.get(region, "the laws of Delaware, USA")
    return "\n".join([
        f"# Terms of Service — {store_name}",
        "",
        "_Effective date_: " + _today_iso(),
        "",
        "## Acceptance",
        "",
        f"By using {store_name} you agree to these Terms. "
        "If you do not agree, please do not use the site.",
        "",
        "## Products + pricing",
        "",
        "Product descriptions and pricing may change without "
        "notice. We reserve the right to refuse or cancel "
        "orders, including pricing errors and suspected "
        "fraud.",
        "",
        "## Payment",
        "",
        "You authorise us to charge your payment method the "
        "total shown at checkout, including any applicable "
        "taxes and shipping fees.",
        "",
        "## Shipping + delivery",
        "",
        "See our Shipping Policy for delivery times, costs, "
        "and carrier information.",
        "",
        "## Returns + refunds",
        "",
        "See our Return Policy for full terms.",
        "",
        "## Limitation of liability",
        "",
        "To the extent permitted by law, our total liability "
        "for any claim arising from a product is limited to "
        "the amount you paid for that product. We are not "
        "responsible for indirect or consequential damages.",
        "",
        "## Governing law",
        "",
        f"These Terms are governed by {governing}.",
        "",
        "## Contact",
        "",
        f"Questions about these Terms? Email **{contact_email}**.",
        "",
        "---",
        "_Owner should review with counsel before "
        "publishing._",
    ])


def _returns(
    *, store_name: str, contact_email: str, region: str,
) -> str:
    window = 14 if region in (REGION_EU, REGION_UK) else 30
    cooling_off = ""
    if region in (REGION_EU, REGION_UK):
        cooling_off = (
            "\n\nUnder EU/UK consumer law you may cancel "
            "your order within 14 days of delivery without "
            "giving a reason (the \"cooling-off period\"). "
            "Return shipping is paid by you unless the item "
            "is defective or not as described."
        )
    return "\n".join([
        f"# Return + Refund Policy — {store_name}",
        "",
        "_Effective date_: " + _today_iso(),
        "",
        f"## Return window — {window} days",
        "",
        f"You may return most items within {window} days of "
        "delivery for a refund. Items must be unused, in "
        "original packaging, and accompanied by the order "
        "confirmation."
        + cooling_off,
        "",
        "## How to start a return",
        "",
        f"1. Email **{contact_email}** with your order "
        "number and reason",
        "2. We'll reply with return instructions and a "
        "return address",
        "3. Ship the item back at your own cost (unless the "
        "return is due to our error)",
        "",
        "## Refunds",
        "",
        "Refunds are issued to the original payment method "
        "within 7 business days of receiving the returned "
        "item.",
        "",
        "## Defective or wrong items",
        "",
        "If an item arrives defective or not as described, "
        "we cover return shipping and offer a full refund "
        "or replacement.",
        "",
        "## Non-returnable items",
        "",
        "- Perishables (food, flowers)",
        "- Custom or personalised products",
        "- Health and personal care items after opening",
        "- Digital downloads",
        "",
        "## Contact",
        "",
        f"Questions? Email **{contact_email}**.",
        "",
        "---",
        "_Owner should review with counsel and align with "
        "supplier return terms before publishing._",
    ])


def _shipping(
    *, store_name: str, contact_email: str, region: str,
) -> str:
    default_countries = {
        REGION_US: "United States and Canada",
        REGION_EU: "EU member states",
        REGION_UK: "United Kingdom",
    }.get(region, "the United States")
    return "\n".join([
        f"# Shipping Policy — {store_name}",
        "",
        "_Effective date_: " + _today_iso(),
        "",
        "## Where we ship",
        "",
        f"We currently ship to {default_countries}. Contact "
        "us if you need shipping to another region.",
        "",
        "## Processing time",
        "",
        "Orders are processed within 1-3 business days. You "
        "will receive a tracking number by email once your "
        "order ships.",
        "",
        "## Delivery times",
        "",
        "Standard delivery takes 7-15 business days "
        "depending on destination. Customs delays may add "
        "additional time for international orders.",
        "",
        "## Shipping costs",
        "",
        "Shipping cost is calculated at checkout based on "
        "destination and order weight. Some items qualify "
        "for free shipping.",
        "",
        "## Customs + duties",
        "",
        "For international orders, customers are responsible "
        "for any customs fees, import duties, or taxes "
        "imposed by their country.",
        "",
        "## Lost or damaged packages",
        "",
        f"If your package is lost or arrives damaged, email "
        f"**{contact_email}** within 7 days of the expected "
        "delivery date.",
        "",
        "## Contact",
        "",
        f"Shipping questions? Email **{contact_email}**.",
    ])


def _cookies(
    *, store_name: str, contact_email: str, region: str,
) -> str:
    consent = ""
    if region in (REGION_EU, REGION_UK):
        consent = (
            "\n\nUnder the EU ePrivacy Directive and GDPR "
            "(and the UK PECR) we ask for your consent "
            "before setting any non-essential cookies. You "
            "can withdraw consent at any time via the "
            "cookie banner."
        )
    return "\n".join([
        f"# Cookie Policy — {store_name}",
        "",
        "_Effective date_: " + _today_iso(),
        "",
        "## What cookies are",
        "",
        "Cookies are small text files placed on your device "
        "when you visit our site.",
        "",
        "## How we use cookies",
        "",
        "- Essential: login session, cart state, fraud "
        "prevention",
        "- Analytics: aggregated traffic statistics",
        "- Advertising: with your consent, relevant ads on "
        "Meta / Google / TikTok",
        "" + consent,
        "",
        "## Managing cookies",
        "",
        "You can block or delete cookies in your browser "
        "settings. Blocking essential cookies may prevent "
        "checkout from functioning.",
        "",
        "## Contact",
        "",
        f"Questions? Email **{contact_email}**.",
    ])


# ── Helpers ────────────────────────────────────────────────


def _today_iso() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _validate_email(email: str) -> None:
    if not email or "@" not in email or "." not in email:
        raise ValueError(
            f"contact_email looks invalid: {email!r}",
        )


# ── Public API ─────────────────────────────────────────────


def render_legal_pages(
    *,
    store_name: str,
    contact_email: str,
    region: str = REGION_US,
    include: Iterable[str] | None = None,
    custom_sections: dict[str, str] | None = None,
) -> LegalPageSet:
    """Render the four-to-five core legal pages for a region.

    Args:
      store_name:    the public storefront name.
      contact_email: owner's support / legal contact.
      region:        REGION_US | REGION_EU | REGION_UK.
      include:       which page kinds to render. Default is all.
                     Unknown kinds are silently skipped.
      custom_sections: optional override map ``{kind: markdown}``.
                     When a kind is present, its value replaces
                     the rendered template entirely.

    Returns:
      LegalPageSet with one LegalPage per requested kind.
    """
    if not store_name:
        raise ValueError("store_name required")
    _validate_email(contact_email)
    if region not in _SUPPORTED_REGIONS:
        raise ValueError(
            f"region must be one of {_SUPPORTED_REGIONS}, "
            f"got {region!r}",
        )
    custom = dict(custom_sections or {})
    wanted = tuple(include) if include else _PAGE_KINDS
    now = time.time()
    renderers = {
        "privacy": ("Privacy Policy", _privacy),
        "terms": ("Terms of Service", _terms),
        "returns": ("Return + Refund Policy", _returns),
        "shipping": ("Shipping Policy", _shipping),
        "cookies": ("Cookie Policy", _cookies),
    }
    pages: list[LegalPage] = []
    for kind in wanted:
        if kind not in renderers:
            continue
        title, fn = renderers[kind]
        if kind in custom:
            markdown = str(custom[kind])
        else:
            markdown = fn(
                store_name=store_name,
                contact_email=contact_email,
                region=region,
            )
        pages.append(LegalPage(
            kind=kind,
            title=title,
            markdown=markdown,
            region=region,
            updated_ts=now,
        ))
    return LegalPageSet(
        region=region,
        store_name=store_name,
        contact_email=contact_email,
        pages=tuple(pages),
    )
