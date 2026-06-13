"""Engine name -> Autonomy domain name translation.

W963-80 arm_recommender uses ENGINE names from the W963
revenue-engine vocabulary (ads_launcher / loyalty /
cart_recovery / ...). The W963 autonomy bridge
(core.automation.autonomy_armed) uses DOMAIN names
(marketing / customer_support / fulfillment / ...).

This module is the single source of truth that maps
between them, so the W963-82 auto-disarm hook can take
a recommender engine name and arm/disarm the right
autonomy domain.

When an engine maps to NO autonomy domain (e.g.
content_publisher -- standalone, no autonomy substrate
yet), the lookup returns None and the auto-disarm hook
silently skips it (logging at debug). This is by design:
the recommender can recommend things the autonomy bridge
doesn't yet implement; visibility (W963-81) covers that
gap until the substrate catches up.

The autonomy domains themselves are declared in
core.automation.autonomy_armed.DOMAIN_APPLY_FLAGS -- ten
ant-colony domains. We map to those by behavioural class.
"""
from __future__ import annotations


# Engine -> autonomy domain. None values mean the engine
# has no autonomy domain (yet); auto-disarm skips them.
_ENGINE_TO_DOMAIN: dict[str, str | None] = {
    # Spend engines -> marketing autonomy domain
    # (the marketing autonomy bridge owns ad-budget pause).
    "ads_launcher":         "marketing",
    "pinterest_publisher":  "marketing",
    "instagram_publisher":  "marketing",
    "tiktok_publisher":     "marketing",
    # Conservation engines map to their autonomy substrates
    # where one exists.
    "refund_applier":       "customer_support",
    "discount_cleanup":     "discount_cleanup",
    # Revenue-driving engines: no autonomy substrate yet.
    # arm_recommender CAN recommend arming them, but the
    # actual arm/disarm goes through the standard
    # SHOPAI_<engine>_AGI_GUARDRAIL env-var path -- not
    # the autonomy bridge. So this mapping returns None
    # to signal "skip auto-apply for this engine".
    "loyalty":              None,
    "cart_recovery":        None,
    "browse_recovery":      None,
    "email_marketing":      None,
    "welcome_series":       None,
    "affiliate":            None,
    "churn_prediction":     None,
    "review_request":       None,
    # Exploration / kickstart engines: no autonomy
    # substrate.
    "transfer_scan":        None,
    "content_publisher":    None,
    "product_sourcer":      None,
    "blog_post_generator":  None,
    # Destructive engines covered by their own substrates.
    "product_lifecycle":    None,
}


def engine_to_domain(engine: str) -> str | None:
    """Look up the autonomy domain for an engine name.

    Returns the domain name when the engine has an
    autonomy bridge; None when there is no bridge (the
    engine is real but doesn't have an autonomy substrate
    yet, so auto-disarm should skip it).

    Returns None for unknown engine names too -- the
    auto-disarm hook should never raise on a recommender
    suggestion it doesn't recognise.
    """
    return _ENGINE_TO_DOMAIN.get(engine)


def engines_with_autonomy_domain() -> list[str]:
    """Return the subset of recommender engines that DO
    map to an autonomy domain -- useful for the W963-82
    auto-disarm bridge's enumeration."""
    return [
        eng for eng, dom in _ENGINE_TO_DOMAIN.items()
        if dom is not None
    ]


def domains_used() -> list[str]:
    """Return the distinct autonomy domains we map to."""
    seen: set[str] = set()
    out: list[str] = []
    for dom in _ENGINE_TO_DOMAIN.values():
        if dom is None or dom in seen:
            continue
        seen.add(dom)
        out.append(dom)
    return out
