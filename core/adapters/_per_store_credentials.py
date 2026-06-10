"""W963-116: per-store credential resolution helper.

Reusable infrastructure for the 20-store autonomous AGI
vision. W963-115 added per-store routing to the Shopify
adapter via StoreManager. This module generalises the
pattern to EVERY adapter category (Meta Ads, Google Ads,
Klaviyo, OpenAI, ElevenLabs, Pexels, ...) without
requiring each adapter to re-implement the lookup chain.

Resolution chain (highest to lowest priority):

  1. Per-store env var:
     SHOPAI_STORE_<SID_UPPER>_<ENV_VAR_NAME>
     e.g. SHOPAI_STORE_STORE_A_META_ADS_ACCESS_TOKEN
     active when ``active_store(sid)`` thread-local set.

  2. Fleet-wide env var (canonical):
     <ENV_VAR_NAME>
     e.g. META_ADS_ACCESS_TOKEN
     The default for single-store empires + fallback for
     multi-store empires that didn't set per-store
     overrides.

Adapter migration: replace any direct
``get_config().get(self.config_alias)`` call with
``resolve_per_store(self.config_alias)``. Existing
tests + single-store behaviour unchanged because step 2
mirrors the pre-fix path.

Per-store env var naming follows operator-friendly
conventions:
  * SID is uppercased; hyphens become underscores
    (operator writes ``store-a`` in StoreManager but the
    env var is ``SHOPAI_STORE_STORE_A_...``).
  * The trailing portion is the canonical
    ``ENV_VAR_NAME`` from ``core.adapters.config``
    (e.g. ``META_ADS_ACCESS_TOKEN``).

Example 3-store empire .env:

  # Fleet defaults (used for the active store + as
  # fallback for any store without an override)
  META_ADS_ACCESS_TOKEN=fleet_default
  META_ADS_ACCOUNT_ID=act_000

  # Per-store overrides
  SHOPAI_STORE_STORE_A_META_ADS_ACCESS_TOKEN=token_a
  SHOPAI_STORE_STORE_A_META_ADS_ACCOUNT_ID=act_111
  SHOPAI_STORE_STORE_B_META_ADS_ACCESS_TOKEN=token_b
  SHOPAI_STORE_STORE_B_META_ADS_ACCOUNT_ID=act_222
  # store_c has no override -> falls back to fleet
  # default (act_000)
"""
from __future__ import annotations

import os


def _normalise_sid_for_env(sid: str) -> str:
    """Convert a store_id (often kebab-case like
    'store-a') to the ENV_VAR-friendly form (upper-case
    with underscores: 'STORE_A')."""
    if not sid:
        return ""
    return sid.replace("-", "_").upper()


def _per_store_env_var(sid: str, env_name: str) -> str:
    """Build the per-store env var name for a given (sid,
    canonical_env_name) pair. Returns '' when sid is
    empty."""
    if not sid or not env_name:
        return ""
    return f"SHOPAI_STORE_{_normalise_sid_for_env(sid)}_{env_name}"


def resolve_per_store(
    alias: str, *, default: str = "",
) -> str:
    """Resolve an adapter credential via per-store override
    + fleet-wide fallback.

    Args:
        alias: The canonical alias as registered in
            ``core.adapters.config.ENV_ALIASES``
            (e.g. ``"meta_ads_access_token"``).
        default: Returned when neither per-store nor fleet
            env var is set.

    Returns:
        The first non-empty value in the lookup chain, or
        ``default`` when both are absent.

    Operator behaviour:
      * Single-store empire with one .env value: works
        exactly as before W963-116 -- step 2 hit.
      * Multi-store empire with per-store overrides: each
        cycle wrapped in active_store(sid) sees that
        store's credentials at step 1.
      * Multi-store empire WITHOUT per-store overrides:
        every store falls back to the same fleet-default
        value at step 2 -- safe degradation, no crashes.

    Returns empty string (not raise) when nothing matches
    so callers can implement their own "missing
    credential" error message with vendor-specific context.
    """
    if not alias:
        return default
    try:
        from core.context import get_active_store_id
        sid = get_active_store_id() or ""
    except Exception:  # noqa: BLE001
        sid = ""

    from core.adapters.config import get_config
    cfg = get_config()
    env_name = cfg.env_var_for(alias)

    # Step 1: per-store env var
    if sid and env_name:
        per_store_var = _per_store_env_var(sid, env_name)
        if per_store_var:
            value = os.environ.get(per_store_var, "")
            if value:
                return value

    # Step 2: fleet-wide env var (via AdapterConfig cache)
    return cfg.get(alias) or default


def has_per_store(alias: str) -> bool:
    """True iff resolve_per_store(alias) would return a
    non-empty value. Mirrors AdapterConfig.has but honours
    the active_store thread-local."""
    return bool(resolve_per_store(alias))
