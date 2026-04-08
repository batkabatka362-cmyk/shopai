"""Search Executor — runs search queries and returns raw results.

Responsibility: take a list of ``SearchQuery`` dicts, execute them
against a real search backend, and return unified
``RawSearchResult`` lists.

**Important:** this module used to ship an 8-entry hardcoded
"simulated corpus" of fake article titles (``"Market Overview:
Key Industry Trends"``, ``"Consumer Spending Report 2025"``, ...)
with ``example.com`` / ``reports.example.org`` URLs. The
``execute_searches`` helper scored those fake entries via a token
overlap heuristic, so every research query returned the same 5
fictional "sources" regardless of topic. Every downstream engine
that consumed ``raw_results`` was building its analysis on
fiction.

The fake corpus has been removed. ``execute_searches`` now
returns an empty list and a ``adapter_required`` marker via the
flow's ``_error_output`` path — the caller short-circuits with a
clean "no backend available" signal. The real backend (Brave
Search / Serper / DDGS) will be wired in via the adapter layer.

Model note: no model usage — pure I/O layer.
"""
from __future__ import annotations

import copy
from typing import Any

from .types import SearchQuery, RawSearchResult


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute_searches(
    queries: list[SearchQuery],
    *,
    max_results_per_query: int = 5,
) -> list[RawSearchResult]:
    """Execute a batch of search queries and return raw results.

    Never mutates *queries* — works on a deep copy.

    Pre-cleanup this function ran each query against an 8-entry
    hardcoded corpus and returned fictional "sources" with
    ``example.com`` URLs. The backend has been removed and
    replaced with an explicit empty-list return, which the caller
    handles via its existing "no results" path (``flow.py`` line
    97 calls ``_error_output`` with ``reason="Search executor
    returned no results."`` — the engine cleanly signals the gap
    instead of generating fake research). A real adapter
    (Brave / Serper / DDGS) will fill this module in.
    """
    safe_queries: list[SearchQuery] = copy.deepcopy(queries)

    if not safe_queries:
        return []

    # Previously: ran every query through ``_simulate_search`` over
    # ``_SIMULATED_CORPUS`` and returned 5 fake hits. Now: return
    # nothing so the caller routes to the "no backend" branch.
    _ = max_results_per_query  # signature preserved for backwards compat
    return []
