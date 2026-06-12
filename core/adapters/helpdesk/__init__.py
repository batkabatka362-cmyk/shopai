"""W963-145: customer support / helpdesk adapter category.

Gorgias (Shopify-native), Tidio, Zendesk, Intercom,
Reamaze all share the same shape: ticket / conversation
based with customer email + history + macros / canned
replies.

Unlocks the customer_support_autonomy domain
(W101-109): without a ticketing adapter the auto-tag
+ auto-reply pipeline had no surface to write to.

Per-store routing via active_store thread-local +
SHOPAI_STORE_<SID>_GORGIAS_API_KEY chain (W963-117).
"""
from ._base import HelpdeskBaseAdapter

__all__ = ["HelpdeskBaseAdapter"]
