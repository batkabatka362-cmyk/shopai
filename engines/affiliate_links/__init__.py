"""Affiliate Links Engine — W963-9.

Closes the affiliate-engine substrate gap: the existing
``engines.affiliate`` module designs programs + calculates
commissions + pays partners via gift cards, but operators
have no way to GENERATE the trackable referral URLs that
partners promote in the first place.

This engine generates trackable per-partner referral URLs in
the standard ``?ref=<code>`` query-param format that downstream
order webhooks can attribute back. Codes are deterministic per
partner-email so re-running for the same partner returns the
same code (idempotent for sharing across multiple channels).

CLI:
  shopai affiliate generate-link --partner-name "Mary" \
                                  --partner-email mary@example.com \
                                  [--shop-url X.myshopify.com]

Tracking model (operator implements):
  - URL format: https://<shop>/?ref=<6-char code>
  - When customer lands with ?ref=X, set a 30-day cookie
  - On checkout, attach cookie value to order.note_attributes
  - engines.affiliate.commission_calculator joins by code

The engine generates the link + a per-partner Shopify metafield
record so the operator can review who has been issued codes
without re-deriving.
"""
from .flow import AffiliateLinksEngine

__all__ = ["AffiliateLinksEngine"]
