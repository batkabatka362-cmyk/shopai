"""Payment adapters.

Wraps payment processors (PayPal today; Stripe / others later)
behind ``BaseAdapter`` so the brain can ask the smart router for
``Capability.PAYMENT_REFUND`` etc. without knowing which vendor
will service the call.

Why payment adapters are P0 (Wave 1):

* Refund / capture / dispute handling is the most expensive
  capability gap to leave open — every unanswered refund either
  loses the customer (chargeback) or the merchandise (no recall).
* Once an adapter is registered the rest of the core picks it up
  for free: ``SmartRouter`` routes to it, ``MetricsCollector``
  tracks success rate / latency / cost, and ``RouteContext``
  budgets / fallbacks work out of the box.

Bootstrap usage::

    from core.adapters.payment.bootstrap import register_all
    register_all()

PayPal-only for now. Adding Stripe / Adyen later just means a
new ``StripeAdapter(PaymentBaseAdapter)`` plus an entry in
``_PAYMENT_ADAPTER_CLASSES``.
"""
from ._base import PaymentBaseAdapter
from .paypal import PayPalAdapter
from .stripe import StripeAdapter

__all__ = [
    "PaymentBaseAdapter",
    "PayPalAdapter",
    "StripeAdapter",
]
