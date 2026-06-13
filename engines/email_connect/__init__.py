"""Email Connect Engine — W963-8.

Operator-facing wrapper around the existing email adapter
substrate (BrevoAdapter / ResendAdapter at core/adapters/email/).
Mirrors the W963-7 ads_launcher pattern:

  shopai email status                  -- which ESP is wired?
  shopai email connect <provider>      -- save API key to .env
                                          (0o600 perm hygiene)
  shopai email send-test --to X        -- verify the wire-up works

Why this matters: the email_marketing + cart_recovery engines
already have substrate for generating campaign content. Without
an ESP wired, the messages have nowhere to go. This engine is
the last-mile connection.

Currently supports the 4 ESP providers known to core/adapters/
config.py: brevo, resend, sendgrid, klaviyo. The first two have
adapters wired; sendgrid + klaviyo are reserved env-var slots
for future adapters.
"""
from .flow import EmailConnectEngine

__all__ = ["EmailConnectEngine"]
