"""Budget cap resolution.

Operators configure caps via env vars in a 4-level
hierarchy (most specific wins). Resolved at call time so
.env changes take effect without restarting the process.
"""
from __future__ import annotations

import os


def _normalise_sid_for_env(sid: str) -> str:
    """Match W963-116's per-store cred helper. Operator-
    side hyphens become underscores; case-flattened to
    upper. 'store-a' -> 'STORE_A'."""
    if not sid:
        return ""
    return sid.replace("-", "_").upper()


def _normalise_adapter_for_env(adapter: str) -> str:
    """Upper-case the adapter name. 'meta_ads' ->
    'META_ADS'. 'cj_dropshipping' -> 'CJ_DROPSHIPPING'."""
    if not adapter:
        return ""
    return adapter.upper().replace("-", "_")


def _parse_amount(raw: str | None) -> float | None:
    """Parse a budget string. W963-124 round-8 #4 fix.

    Returns:
      - None    when UNSET (env var absent, empty,
                whitespace, or 'unset' / 'null')
      - 0.0     when explicitly UNLIMITED ('unlimited' /
                'none' / 'off')
      - >0.0    valid positive cap
      - None    on PARSE ERROR (pre-fix typos like
                '1,000' returned 0.0 which the caller
                treated as 'unlimited' -- operator wallet
                silently uncapped on typo. Now None
                means 'unresolvable, try next level')

    Operator-friendly: '5', '5.50', '$5', '5 USD',
    '5.50 USD', '1,000', '1_000' all parse to positive
    floats. Negative numbers clamp to 0 (unlimited).
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    low = s.lower()
    if low in ("unlimited", "none", "off"):
        return 0.0
    if low in ("unset", "null"):
        return None
    # Strip currency markers + operator-friendly
    # thousands separators
    for noise in ("$", "usd", " ", ",", "_"):
        low = low.replace(noise, "")
    try:
        v = float(low)
    except (TypeError, ValueError):
        # W963-124 round-8 #4: return None (not 0.0) so
        # the caller falls through to the next
        # resolution level instead of treating a typo
        # as 'unlimited'.
        import logging
        logging.getLogger(__name__).warning(
            "budget_config: cannot parse "
            "DAILY_BUDGET_USD value %r -- treating as "
            "UNSET (will fall through to next level)",
            raw,
        )
        return None
    if v < 0:
        return 0.0
    return v


def _read_env(name: str) -> float | None:
    """Helper: read env var + parse. Returns None when
    the var is absent (so the resolution chain falls
    through). 0.0 means explicit unlimited; >0 means
    a positive cap; None means UNSET."""
    val = os.environ.get(name)
    return _parse_amount(val)


def resolve_cap(
    *,
    store_id: str = "",
    adapter: str = "",
) -> float:
    """Resolve the applicable daily budget cap in USD.

    Resolution chain (most specific wins).
    W963-124 round-8 #3 fix: each level is consulted
    distinctly; a level set to 0.0 ('unlimited')
    SHORT-CIRCUITS the chain (operator intent honoured)
    rather than falling through. Pre-fix the truthiness
    check 'if cap > 0' conflated 'unset' with 'unlimited'
    so an operator could not unlimit a specific
    (store, adapter) pair against a finite fleet cap.

    Returns:
      0.0 = explicit unlimited at the most-specific
            level that was set
      >0.0 = positive cap from the most-specific level
      0.0 = nothing set anywhere (still unlimited but
            via the unconfigured-fleet path)
    """
    sid_norm = _normalise_sid_for_env(store_id)
    ad_norm = _normalise_adapter_for_env(adapter)

    # Level 1: per-store, per-adapter
    if sid_norm and ad_norm:
        cap = _read_env(
            f"SHOPAI_STORE_{sid_norm}_"
            f"{ad_norm}_DAILY_BUDGET_USD"
        )
        if cap is not None:
            return cap

    # Level 2: per-store total
    if sid_norm:
        cap = _read_env(
            f"SHOPAI_STORE_{sid_norm}_DAILY_BUDGET_USD"
        )
        if cap is not None:
            return cap

    # Level 3: fleet-wide per-adapter
    if ad_norm:
        cap = _read_env(
            f"{ad_norm}_DAILY_BUDGET_USD"
        )
        if cap is not None:
            return cap

    # Level 4: fleet-wide total
    cap = _read_env("SHOPAI_DAILY_BUDGET_USD")
    if cap is not None:
        return cap

    # Nothing set anywhere -> unlimited
    return 0.0


def resolve_warn_ratio() -> float:
    """Read the warn-threshold ratio from env.

    Default 0.7 (warn at 70% of cap). Operator can tune
    via SHOPAI_BUDGET_WARN_RATIO=0.5 etc. Clamped to
    [0.1, 0.99].
    """
    raw = os.environ.get(
        "SHOPAI_BUDGET_WARN_RATIO", "",
    ).strip()
    if not raw:
        return 0.7
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.7
    return max(0.1, min(0.99, v))
