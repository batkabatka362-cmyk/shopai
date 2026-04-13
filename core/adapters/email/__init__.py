"""Email adapters.

Each adapter wraps a single transactional/marketing email
vendor in the universal ``BaseAdapter`` interface so the brain
can route to it via ``Capability.SEND_EMAIL_TRANSACTIONAL`` or
``Capability.SEND_EMAIL_CAMPAIGN``:

  * ``brevo``  — Brevo (Sendinblue), 300/day = 9,000/month
                 forever free, unlimited contacts
  * ``resend`` — Resend, 3,000/month forever free, modern
                 developer API

Both vendors speak the same basic shape: POST a JSON body with
``{from, to, subject, html, text}`` and get back a message id.
The shared ``EmailBaseAdapter`` handles validation, HTTP
plumbing, and the normalised ``EmailMessage`` dict so concrete
adapters become ~60 lines of vendor-specific URL + payload
translation.

Bootstrap::

    from core.adapters.email.bootstrap import register_all
    register_all()

Importing this package alone does NOT register anything — call
``bootstrap.register_all()`` so test isolation stays clean.
"""
from ._base import EmailBaseAdapter, EmailMessage
from .klaviyo import KlaviyoAdapter
from .sendgrid import SendGridAdapter

__all__ = ["EmailBaseAdapter", "EmailMessage", "KlaviyoAdapter", "SendGridAdapter"]
