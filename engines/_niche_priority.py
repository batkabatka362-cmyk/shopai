"""Niche-aware cluster prioritization.

Wave 73: orchestrator priority maps (Wave 8 + Wave 37) are
uniform across stores. But a beauty store benefits from
different cluster emphasis than a tech store:

  - beauty:  merchandising (visual products) + content +
             retention (loyalty programs work well)
  - fashion: merchandising + content + acquisition (trend-
             driven; new customers matter most)
  - home:    quality (durable goods need reviews) +
             merchandising + retention
  - tech:    quality (reviews + warranty are critical) +
             pricing (competitive market) + merchandising
  - food:    fulfillment (perishables) + retention +
             pricing
  - general: default fleet-wide priority

This module ships a per-niche cluster preference list that
SUPPLEMENTS the base priority's cluster_focus. When a store
has a niche set, the orchestrator merges the niche
preferences with the lifecycle priority to produce a tighter
focus list.

## Algorithm

Given:
  base_focus     = ["acquisition", "merchandising",
                    "pricing", "quality"]  (Wave 37 launching)
  niche_focus    = niche_cluster_focus("beauty")
                 = ["merchandising", "content", "retention"]

Result (merge order: niche first, then base):
  resolved = ["merchandising", "content", "retention",
              "acquisition", "pricing", "quality"]

Dedupes (each cluster appears once). opt-in clusters
(setup, content) still filtered upstream by the supervisor
when not in cluster_override.

NOTE: this is ADVISORY substrate. Captain selection within a
cluster is unchanged; the niche only affects WHICH clusters
get activated + in what order.
"""
from __future__ import annotations


# Per-niche cluster preference (ordered, higher = higher priority)
_NICHE_PRIORITIES: dict[str, list[str]] = {
    "beauty": [
        "merchandising",  # visual products, ranking matters
        "content",        # before/after, tutorials drive sales
        "retention",      # loyalty programs work well in beauty
        "acquisition",
        "quality",
    ],
    "fashion": [
        "merchandising",  # seasonal trending products
        "content",        # lookbooks, styling
        "acquisition",    # trend-driven, churn-heavy
        "quality",
        "retention",
    ],
    "home": [
        "quality",        # durable goods need positive reviews
        "merchandising",
        "retention",
        "fulfillment",    # shipping matters for large items
        "pricing",
    ],
    "tech": [
        "quality",        # reviews + warranty critical
        "pricing",        # competitive market
        "merchandising",  # search + filter matter
        "acquisition",
        "retention",
    ],
    "food": [
        "fulfillment",    # perishables, delivery speed
        "retention",      # subscription model dominant
        "pricing",
        "quality",
        "merchandising",
    ],
    "general": [
        # No niche-specific bias; use base
    ],
}


def niche_cluster_focus(niche: str | None) -> list[str]:
    """Return per-niche cluster preference list.

    Empty list when niche is unknown OR ``general`` (caller
    should fall back to base priority unchanged).
    """
    if not niche:
        return []
    return list(_NICHE_PRIORITIES.get(niche.lower(), []))


def merge_with_base(
    base_focus: list[str],
    niche: str | None,
) -> list[str]:
    """Merge base priority cluster_focus with niche preference.

    Niche clusters come FIRST, then any base clusters not
    already in the niche list (dedup-preserving).
    """
    niche_focus = niche_cluster_focus(niche)
    if not niche_focus:
        return list(base_focus)
    seen: set[str] = set()
    out: list[str] = []
    for c in niche_focus + list(base_focus):
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def supported_niches() -> list[str]:
    """List of niches with a defined preference."""
    return sorted(
        n for n in _NICHE_PRIORITIES
        if _NICHE_PRIORITIES[n]
    )
