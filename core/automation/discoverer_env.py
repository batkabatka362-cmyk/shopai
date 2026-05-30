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

import os
import re

_SAFE = re.compile(r"[^A-Z0-9_]")


def _normalise(s: str) -> str:
    return _SAFE.sub("", str(s).replace("-", "_").upper())


def _resolve(
    domain: str,
    knob: str,
    store_id: str | None,
) -> str | None:
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
    return None


def resolve_int(
    domain: str,
    knob: str,
    *,
    default: int,
    store_id: str | None = None,
    min_value: int | None = None,
) -> int:
    """Resolve a per-store int knob with global fallback."""
    raw = _resolve(domain, knob, store_id)
    if raw is None:
        out = default
    else:
        try:
            out = int(raw)
        except (TypeError, ValueError):
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
) -> float:
    """Resolve a per-store float knob with global fallback."""
    raw = _resolve(domain, knob, store_id)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default
