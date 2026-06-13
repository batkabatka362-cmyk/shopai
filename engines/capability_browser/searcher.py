"""Search and rank capabilities from the registry.

Ranking signal:
  - exact name match: highest
  - tag match: high
  - description token match: medium
  - when_to_use token match: medium
  - cli_command token match: low

Plus goal-to-cluster heuristics so phrases like "get traffic"
map to ads / pinterest / tiktok / content_publisher even
without exact tokens.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# Goal phrase → tag/keyword hints. The phrases below are the
# operator-natural goals; each maps to keywords that match the
# registry's description / when_to_use / tags fields.
_GOAL_KEYWORDS: dict[str, list[str]] = {
    "traffic": [
        "ads", "social", "content", "seo", "pinterest",
        "tiktok", "instagram",
    ],
    "convert": [
        "cro", "conversion", "checkout", "discount",
        "cart_recovery", "review",
    ],
    "earn": [
        "earn", "revenue", "earnings", "first sale",
        "monetize",
    ],
    "launch": [
        "launch", "store_configurator", "policies",
        "design", "products",
    ],
    "scale": [
        "fleet", "multi-store", "transfer", "expand",
    ],
    "diagnose": [
        "diagnose", "audit", "checkup", "trajectory",
        "funnel", "health",
    ],
    "retain": [
        "loyalty", "review", "welcome", "retention",
        "email", "churn",
    ],
}


@dataclass
class CapabilityHit:
    name: str
    kind: str
    description: str
    when_to_use: str = ""
    cli_commands: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    score: float = 0.0
    score_components: dict[str, float] = field(
        default_factory=dict,
    )


@dataclass
class BrowseReport:
    query: str
    kind_filter: str
    tag_filter: str
    total_registry: int = 0
    hits: list[CapabilityHit] = field(default_factory=list)


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokens(text: str) -> set[str]:
    if not isinstance(text, str):
        return set()
    return {
        t.lower()
        for t in _TOKEN_RE.findall(text)
        if len(t) >= 2
    }


def _goal_expansion(query: str) -> list[str]:
    """Expand short operator goal phrases into broader
    keyword sets."""
    q = (query or "").lower()
    out: list[str] = []
    for goal, kws in _GOAL_KEYWORDS.items():
        if goal in q:
            out.extend(kws)
    return out


def _score_capability(
    cap: Any,
    *,
    query_tokens: set[str],
    expanded_keywords: list[str],
) -> tuple[float, dict[str, float]]:
    """Score one capability against a query."""
    components: dict[str, float] = {}

    name = getattr(cap, "name", "") or ""
    description = getattr(cap, "description", "") or ""
    when_to_use = getattr(cap, "when_to_use", "") or ""
    tags = list(getattr(cap, "tags", []) or [])
    cli_commands = list(
        getattr(cap, "cli_commands", []) or [],
    )

    if not query_tokens and not expanded_keywords:
        # No query → uniform 1.0 baseline so ranking is by
        # registry order.
        return (1.0, {"baseline": 1.0})

    # Name match (highest signal)
    name_tokens = _tokens(name)
    name_hits = len(query_tokens & name_tokens)
    if name_hits:
        components["name"] = 5.0 * name_hits
    # Tag match
    tag_set = {t.lower() for t in tags}
    tag_hits = len(query_tokens & tag_set)
    if tag_hits:
        components["tag"] = 3.0 * tag_hits
    # Description
    desc_tokens = _tokens(description)
    desc_hits = len(query_tokens & desc_tokens)
    if desc_hits:
        components["description"] = 1.0 * desc_hits
    # when_to_use
    wtu_tokens = _tokens(when_to_use)
    wtu_hits = len(query_tokens & wtu_tokens)
    if wtu_hits:
        components["when_to_use"] = 1.5 * wtu_hits
    # cli command
    for c in cli_commands:
        c_tokens = _tokens(c)
        if query_tokens & c_tokens:
            components["cli"] = (
                components.get("cli", 0.0) + 0.5
            )
    # Goal expansion: any token from the expanded keyword
    # list matched in any field counts as a soft hit.
    if expanded_keywords:
        expanded_set = set(
            _tokens(" ".join(expanded_keywords))
        )
        soft_hits = (
            len(expanded_set & name_tokens) * 2.0
            + len(expanded_set & tag_set) * 1.5
            + len(expanded_set & desc_tokens) * 0.5
            + len(expanded_set & wtu_tokens) * 0.75
        )
        if soft_hits:
            components["goal_expansion"] = round(
                soft_hits, 2,
            )

    score = sum(components.values())
    return (round(score, 3), components)


def search_capabilities(
    *,
    query: str = "",
    kind_filter: str = "",
    tag_filter: str = "",
    top: int = 20,
) -> BrowseReport:
    """Search + rank capabilities. Falls back to empty report
    when registry isn't available."""
    report = BrowseReport(
        query=query, kind_filter=kind_filter,
        tag_filter=tag_filter,
    )
    try:
        from core.capability_registry.bootstrap import (
            ensure_registered,
        )
        from core.capability_registry import get_registry
        ensure_registered()
        registry = get_registry()
        all_caps = list(registry.all() or [])
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "capability_browser: registry import failed: %s",
            exc,
        )
        return report

    report.total_registry = len(all_caps)
    query_tokens = _tokens(query)
    expanded = _goal_expansion(query)

    kind_filter_l = (kind_filter or "").strip().lower()
    tag_filter_l = (tag_filter or "").strip().lower()

    hits: list[CapabilityHit] = []
    for cap in all_caps:
        # Kind filter
        if kind_filter_l:
            cap_kind = str(
                getattr(cap, "kind", "") or "",
            ).lower()
            if cap_kind != kind_filter_l:
                continue
        # Tag filter
        if tag_filter_l:
            tag_set = {
                str(t).lower()
                for t in (getattr(cap, "tags", []) or [])
            }
            if tag_filter_l not in tag_set:
                continue

        score, components = _score_capability(
            cap,
            query_tokens=query_tokens,
            expanded_keywords=expanded,
        )
        if (
            (query_tokens or expanded)
            and score == 0.0
        ):
            # When the operator searched and nothing matched,
            # exclude.
            continue
        hits.append(
            CapabilityHit(
                name=str(getattr(cap, "name", "") or ""),
                kind=str(getattr(cap, "kind", "") or ""),
                description=str(
                    getattr(cap, "description", "") or "",
                )[:200],
                when_to_use=str(
                    getattr(cap, "when_to_use", "") or "",
                )[:200],
                cli_commands=list(
                    getattr(cap, "cli_commands", []) or [],
                ),
                tags=list(getattr(cap, "tags", []) or []),
                score=score,
                score_components=components,
            )
        )

    hits.sort(key=lambda h: h.score, reverse=True)
    if top > 0:
        hits = hits[:top]
    report.hits = hits
    return report


def goal_suggestions() -> list[str]:
    """Return the canonical operator goal phrases."""
    return sorted(_GOAL_KEYWORDS.keys())
