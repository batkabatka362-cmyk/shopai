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


def _parse_amount(raw: str) -> float:
    """Parse a budget string. '5', '5.50', '$5', '5 USD',
    'unlimited', '' -> appropriate floats.

    'unlimited' / 'none' / 'off' return 0.0 (no cap).
    Empty / whitespace -> 0.0.
    Invalid -> 0.0 (operator typo doesn't crash).
    """
    if not raw or not raw.strip():
        return 0.0
    s = raw.strip().lower()
    if s in ("unlimited", "none", "off", "0"):
        return 0.0
    # Strip currency markers
    for noise in ("$", "usd", " "):
        s = s.replace(noise, "")
    try:
        return max(0.0, float(s))
    except (TypeError, ValueError):
        return 0.0


def resolve_cap(
    *,
    store_id: str = "",
    adapter: str = "",
) -> float:
    """Resolve the applicable daily budget cap in USD.

    Resolution chain (most specific wins):

      1. SHOPAI_STORE_<SID>_<ADAPTER>_DAILY_BUDGET_USD
      2. SHOPAI_STORE_<SID>_DAILY_BUDGET_USD
      3. <ADAPTER>_DAILY_BUDGET_USD
      4. SHOPAI_DAILY_BUDGET_USD

    Returns 0.0 when no cap is set (treated as
    unlimited).
    """
    sid_norm = _normalise_sid_for_env(store_id)
    ad_norm = _normalise_adapter_for_env(adapter)

    # Level 1: per-store, per-adapter
    if sid_norm and ad_norm:
        env = (
            f"SHOPAI_STORE_{sid_norm}_"
            f"{ad_norm}_DAILY_BUDGET_USD"
        )
        cap = _parse_amount(os.environ.get(env, ""))
        if cap > 0:
            return cap

    # Level 2: per-store total
    if sid_norm:
        env = (
            f"SHOPAI_STORE_{sid_norm}_DAILY_BUDGET_USD"
        )
        cap = _parse_amount(os.environ.get(env, ""))
        if cap > 0:
            return cap

    # Level 3: fleet-wide per-adapter
    if ad_norm:
        env = f"{ad_norm}_DAILY_BUDGET_USD"
        cap = _parse_amount(os.environ.get(env, ""))
        if cap > 0:
            return cap

    # Level 4: fleet-wide total
    cap = _parse_amount(
        os.environ.get("SHOPAI_DAILY_BUDGET_USD", ""),
    )
    return cap


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
