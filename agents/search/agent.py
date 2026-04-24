"""SearchAgent — unified cross-source search.

One query, many sources. The agent dispatches in parallel to:

  * ``WEB_SEARCH``                — Serper / Brave / DDGS
    (whichever the router picks — catches blogs, reviews,
    news articles, pricing comparisons).
  * ``SOURCING_SEARCH_PRODUCTS``  — CJ + AutoDS supplier
    catalogs. Optional — only hit when ``scope`` includes
    ``"products"`` (default "all" hits everything).

Results are normalised into ``SearchResult`` dataclasses,
deduped by URL when the same link shows up from multiple
sources, and ranked by a simple source-weight + position
formula. Caller gets one ordered list.

Why a dedicated agent (rather than letting each engine call
the router directly):

  * **Scope gating** — product-launch engine wants supplier
    catalogs; the content engine wants web pages + news.
    The scope argument captures that once, in one place.
  * **Fan-out cost control** — if web search is configured
    but sourcing isn't, we skip the latter entirely rather
    than letting SmartRouter raise NoAdapterAvailable on
    every call.
  * **Dedup across sources** — the same product page can
    appear on both a supplier catalog and as a web result;
    the agent keeps the richer copy.
  * **Owner surface** — one ``SearchAgent.search(query)``
    call from CLI / MCP / owner-dialog → structured answer.

Typical use:

    from agents.search import SearchAgent
    from core.adapters import get_router

    agent = SearchAgent(router=get_router())
    hits = agent.search(
        "cozy mushroom lamp",
        scope=("web", "products"),
        limit=10,
    )
    for h in hits:
        print(h.source, h.title, h.url)
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any, Iterable

from utils.logger import get_logger

logger = get_logger("agents.search")


_SOURCE_WEIGHTS = {
    # Product sources weigh heavier than generic web when the
    # query is product-shaped (the scope argument controls
    # WHICH sources run; the weight controls RANKING WITHIN
    # the merged list).
    "cj_dropshipping": 1.20,
    "autods":          1.10,
    "serper":          1.00,
    "brave":           0.95,
    "ddgs":            0.85,
}

_DEFAULT_LIMIT = 10


@dataclasses.dataclass(frozen=True)
class SearchResult:
    """Normalised search hit — shape-agnostic to the
    underlying adapter. ``price_usd`` is populated only for
    sourcing hits; ``snippet`` is populated only for web
    hits. ``raw`` keeps the vendor payload for callers that
    need fields we didn't normalise."""

    source: str           # e.g. "cj_dropshipping", "serper"
    kind: str             # "product" | "web"
    title: str
    url: str
    snippet: str = ""
    price_usd: float = 0.0
    image_url: str = ""
    score: float = 0.0
    raw: dict[str, Any] = dataclasses.field(
        default_factory=dict,
    )


class SearchAgent:
    """Owner-facing cross-source search.

    Instantiate once per session with a ``router``; every
    call to ``search()`` reuses the same router so adapter
    metrics accumulate cleanly.
    """

    def __init__(
        self,
        router: Any | None = None,
        *,
        logger_: logging.Logger | None = None,
    ) -> None:
        self._router = router
        self._log = logger_ or logger

    # ── Public API ────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        scope: Iterable[str] = ("all",),
        limit: int = _DEFAULT_LIMIT,
    ) -> list[SearchResult]:
        """Run a search across the requested scopes.

        ``scope`` — ``"all"`` (default) hits web + products;
        ``"web"`` only, ``"products"`` only, or any subset
        like ``("web",)`` to skip product catalogs.
        ``limit`` — max results returned per source. The
        merged+deduped list is capped at 2*limit so callers
        see both source types even when the web side
        dominates volume.
        """
        q = (query or "").strip()
        if not q:
            raise ValueError("query: required")
        try:
            lim = max(1, min(int(limit), 50))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"limit must be int (got {limit!r})",
            ) from exc

        scope_set = _resolve_scope(scope)
        hits: list[SearchResult] = []

        if "web" in scope_set:
            hits.extend(self._run_web(q, lim))
        if "products" in scope_set:
            hits.extend(self._run_products(q, lim))

        return _merge_and_rank(hits, max_results=lim * 2)

    # ── Per-source runners ────────────────────────────

    def _run_web(
        self, query: str, limit: int,
    ) -> list[SearchResult]:
        if self._router is None:
            self._log.debug("router unavailable — skip web search")
            return []
        try:
            from core.adapters import Capability
        except Exception:  # noqa: BLE001
            return []
        try:
            result = self._router.execute(
                Capability.WEB_SEARCH,
                {"query": query, "max_results": limit},
            )
        except Exception as exc:  # noqa: BLE001
            self._log.warning(
                "web search failed: %s: %s",
                type(exc).__name__, exc,
            )
            return []
        if not getattr(result, "ok", False):
            self._log.debug(
                "web search returned not-ok: %s",
                getattr(result, "error", "unknown"),
            )
            return []
        return list(
            _normalise_web_results(
                getattr(result, "data", {}) or {},
                source=getattr(result, "adapter", "web"),
            ),
        )

    def _run_products(
        self, query: str, limit: int,
    ) -> list[SearchResult]:
        if self._router is None:
            return []
        try:
            from core.adapters import Capability
        except Exception:  # noqa: BLE001
            return []
        try:
            result = self._router.execute(
                Capability.SOURCING_SEARCH_PRODUCTS,
                {"query": query, "limit": limit},
            )
        except Exception as exc:  # noqa: BLE001
            self._log.warning(
                "product search failed: %s: %s",
                type(exc).__name__, exc,
            )
            return []
        if not getattr(result, "ok", False):
            self._log.debug(
                "product search returned not-ok: %s",
                getattr(result, "error", "unknown"),
            )
            return []
        return list(
            _normalise_product_results(
                getattr(result, "data", {}) or {},
                source=getattr(result, "adapter", "products"),
            ),
        )


# ── Helpers ───────────────────────────────────────────


_SCOPE_CHOICES = {"all", "web", "products"}


def _resolve_scope(scope: Iterable[str]) -> set[str]:
    """Expand ``"all"`` into the concrete source set and
    reject unknown values early."""
    out: set[str] = set()
    for s in scope or ():
        sv = str(s).lower().strip()
        if not sv:
            continue
        if sv not in _SCOPE_CHOICES:
            raise ValueError(
                f"scope must be a subset of "
                f"{sorted(_SCOPE_CHOICES)} (got {sv!r})",
            )
        if sv == "all":
            out.update({"web", "products"})
        else:
            out.add(sv)
    return out or {"web", "products"}


def _normalise_web_results(
    data: dict[str, Any], *, source: str,
) -> list[SearchResult]:
    rows = data.get("results") or data.get("items") or []
    if not isinstance(rows, list):
        return []
    out: list[SearchResult] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or row.get("link") or "")
        if not url:
            continue
        out.append(SearchResult(
            source=source,
            kind="web",
            title=str(row.get("title") or ""),
            url=url,
            snippet=str(
                row.get("snippet")
                or row.get("description")
                or "",
            ),
            score=_score(source, position=i),
            raw=row,
        ))
    return out


def _normalise_product_results(
    data: dict[str, Any], *, source: str,
) -> list[SearchResult]:
    rows = data.get("products") or []
    if not isinstance(rows, list):
        return []
    out: list[SearchResult] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        images = row.get("images") or []
        image_url = ""
        if isinstance(images, list) and images:
            image_url = str(images[0]) if images[0] else ""
        try:
            price = float(
                row.get("suggested_price_usd")
                or row.get("cost_usd")
                or 0.0,
            )
        except (TypeError, ValueError):
            price = 0.0
        out.append(SearchResult(
            source=str(row.get("source") or source),
            kind="product",
            title=str(row.get("title") or ""),
            url=str(row.get("raw_url") or ""),
            snippet=str(row.get("description") or "")[:280],
            price_usd=price,
            image_url=image_url,
            score=_score(
                str(row.get("source") or source),
                position=i,
            ),
            raw=row,
        ))
    return out


def _score(source: str, *, position: int) -> float:
    """Source weight × (1 / position). Position is 0-based so
    the first hit scores the source weight itself; every
    subsequent hit decays by ~20%."""
    weight = _SOURCE_WEIGHTS.get(source, 0.5)
    decay = 1.0 / (1.0 + 0.2 * max(0, position))
    return round(weight * decay, 4)


def _merge_and_rank(
    hits: list[SearchResult], *, max_results: int,
) -> list[SearchResult]:
    """Dedup by URL (keep highest-score copy) + sort by score
    descending."""
    by_url: dict[str, SearchResult] = {}
    for hit in hits:
        key = hit.url or f"__{hit.source}:{hit.title}"
        existing = by_url.get(key)
        if existing is None or hit.score > existing.score:
            by_url[key] = hit
    merged = sorted(
        by_url.values(), key=lambda r: r.score, reverse=True,
    )
    return merged[:max_results]
