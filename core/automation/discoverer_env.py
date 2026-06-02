"""Per-store discoverer env knob helper (W879).

Most discoverers have a global limit env (e.g.
``SHOPAI_SHIPPING_ALERT_DISCOVER_DAYS=60``). Operators with
heterogeneous stores want to override per-store (e.g.
``SHOPAI_SHIPPING_ALERT_DISCOVER_DAYS_STORE_7=14``).

This module standardises the resolution order:

  1. ``SHOPAI_<DOMAIN_UPPER>_DISCOVER_<KNOB>_<STORE_UPPER>``
  2. ``SHOPAI_<DOMAIN_UPPER>_DISCOVER_<KNOB>``
  3. ``default`` argument

Store IDs are normalised (replace ``-`` with ``_``, uppercase)
so ``store-7`` becomes ``STORE_7`` in the env name. Numbers
+ letters only after normalisation -- exotic characters
silently dropped.

Helpers return the resolved value as ``int`` (the common
case for limits) or ``float`` for ratios.
"""
from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

_SAFE = re.compile(r"[^A-Z0-9_]")


def _normalise(s: str) -> str:
    return _SAFE.sub("", str(s).replace("-", "_").upper())


def _resolve(
    domain: str,
    knob: str,
    store_id: str | None,
    legacy_env: str | None = None,
) -> str | None:
    """Resolve env value with per-store / global / legacy /
    None fallback order.

    W887: ``legacy_env`` lets callers migrate non-standard
    naming knobs (e.g. ``SHOPAI_CUSTOMER_OUTREACH_VIP_USD``)
    to the DISCOVER_<KNOB> convention while keeping the
    legacy var live. Lookup order:

      1. per-store standard naming (DISCOVER_<KNOB>_<STORE>)
      2. global standard naming (DISCOVER_<KNOB>)
      3. legacy_env (if supplied) -- per-store first, then bare
      4. None (caller falls back to default)
    """
    dom = _normalise(domain)
    knob_n = _normalise(knob)
    if store_id:
        per_store = os.environ.get(
            f"SHOPAI_{dom}_DISCOVER_{knob_n}_"
            f"{_normalise(store_id)}",
        )
        if per_store is not None and per_store != "":
            return per_store
    global_v = os.environ.get(
        f"SHOPAI_{dom}_DISCOVER_{knob_n}",
    )
    if global_v is not None and global_v != "":
        return global_v
    if legacy_env:
        # Try per-store legacy first
        if store_id:
            per_store_legacy = os.environ.get(
                f"{legacy_env}_{_normalise(store_id)}",
            )
            if per_store_legacy:
                return per_store_legacy
        bare_legacy = os.environ.get(legacy_env)
        if bare_legacy:
            return bare_legacy
    return None


def resolve_int(
    domain: str,
    knob: str,
    *,
    default: int,
    store_id: str | None = None,
    min_value: int | None = None,
    legacy_env: str | None = None,
) -> int:
    """Resolve a per-store int knob.

    W887: ``legacy_env`` enables back-compat migrations -- when
    a non-standard env name was already in use, callers can
    pass it as the legacy fallback so existing operators don't
    have to rename their env at migration time."""
    raw = _resolve(domain, knob, store_id, legacy_env)
    if raw is None:
        out = default
    else:
        try:
            out = int(raw)
        except (TypeError, ValueError):
            # W962-56: surface operator-typo at WARN. Pre-fix
            # the bad value silently fell back to default, so
            # `SHOPAI_FOO_DISCOVER_LIMIT=fifty` produced the
            # default behaviour with no visible signal.
            logger.warning(
                "discoverer_env: int parse failed for "
                "domain=%s knob=%s store=%s raw=%r -> "
                "falling back to default=%d",
                domain, knob, store_id, raw, default,
            )
            out = default
    if min_value is not None and out < min_value:
        out = min_value
    return out


def resolve_float(
    domain: str,
    knob: str,
    *,
    default: float,
    store_id: str | None = None,
    legacy_env: str | None = None,
) -> float:
    """Resolve a per-store float knob with optional legacy
    back-compat fallback."""
    raw = _resolve(domain, knob, store_id, legacy_env)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        # W962-56: surface operator-typo at WARN.
        logger.warning(
            "discoverer_env: float parse failed for "
            "domain=%s knob=%s store=%s raw=%r -> "
            "falling back to default=%g",
            domain, knob, store_id, raw, default,
        )
        return default
