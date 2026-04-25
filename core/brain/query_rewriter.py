"""Query rewriter — vague NL query → structured search request.

Owners type vague queries like 'cheap audio gear with good
reviews from last month'. search_index (v17-D4) wants structured
(terms, filters) pairs. Query rewriter sits between them: it
extracts filters (price band, niche, date range, rating), rewrites
the residual as a clean term vector, and surfaces suggested
canonical forms.

Pure-rule extraction — zero LLM, sub-ms latency.

APIs:

  rewrite(query) → RewriteResult(
      terms,                 # cleaned search terms
      filters,               # structured filter dict
      suggestions,           # alternative phrasings owner may have meant
      confidence,            # 0-1 how well the rewriter understood
  )

The rewriter ships patterns for price bands, niches, dates,
ratings, product categories. register_extractor adds custom ones.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass
class RewriteResult:
    terms: str
    filters: dict[str, Any] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)
    confidence: float = 0.0
    raw_query: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "terms": self.terms,
            "filters": self.filters,
            "suggestions": self.suggestions,
            "confidence": round(self.confidence, 3),
            "raw_query": self.raw_query,
        }


# ── Pattern matchers ───────────────────────────────────────

_PRICE_RE = re.compile(
    r"(?:under|below|less than)\s*\$?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_PRICE_OVER_RE = re.compile(
    r"(?:over|above|more than|at least)\s*\$?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_PRICE_RANGE_RE = re.compile(
    r"\$?(\d+)\s*(?:-|to)\s*\$?(\d+)",
    re.IGNORECASE,
)
_CHEAP_RE = re.compile(r"\b(cheap|budget|affordable|low[-\s]?price)\b",
                        re.IGNORECASE)
_PREMIUM_RE = re.compile(r"\b(premium|luxury|high[-\s]?end|expensive)\b",
                          re.IGNORECASE)

_NICHES = {
    "audio": ("audio", "speaker", "headphone", "earbud", "headset"),
    "fashion": ("fashion", "clothing", "apparel", "dress", "shirt"),
    "beauty": ("beauty", "skincare", "makeup", "cosmetic"),
    "home": ("home", "decor", "kitchen", "furniture"),
    "fitness": ("fitness", "gym", "workout", "exercise"),
    "pet": ("pet", "dog", "cat", "puppy"),
    "tech": ("tech", "gadget", "electronic", "device"),
}

_RATING_RE = re.compile(
    r"(?:at\s+least\s+)?([1-5])\s*(?:star|\+)",
    re.IGNORECASE,
)
_GOOD_REVIEW_RE = re.compile(
    r"\b(good|great|excellent|top[-\s]?rated)\s+(review|rating)s?",
    re.IGNORECASE,
)

_DATE_LAST_N_RE = re.compile(
    r"last\s+(\d+)\s+(day|days|week|weeks|month|months)",
    re.IGNORECASE,
)
_DATE_NAMED_RE = {
    "last_week": re.compile(r"\blast\s+week\b", re.IGNORECASE),
    "this_week": re.compile(r"\bthis\s+week\b", re.IGNORECASE),
    "last_month": re.compile(r"\blast\s+month\b", re.IGNORECASE),
    "this_month": re.compile(r"\bthis\s+month\b", re.IGNORECASE),
    "today": re.compile(r"\btoday\b", re.IGNORECASE),
    "yesterday": re.compile(r"\byesterday\b", re.IGNORECASE),
}


Extractor = Callable[[str], tuple[dict[str, Any], list[str]]]


def _extract_price(query: str) -> tuple[dict[str, Any], list[str]]:
    filters: dict[str, Any] = {}
    hits: list[str] = []
    # Numeric patterns cascade — only one numeric interpretation.
    if m := _PRICE_RANGE_RE.search(query):
        filters["price_min"] = float(m.group(1))
        filters["price_max"] = float(m.group(2))
        hits.append(m.group(0))
    elif m := _PRICE_RE.search(query):
        filters["price_max"] = float(m.group(1))
        hits.append(m.group(0))
    elif m := _PRICE_OVER_RE.search(query):
        filters["price_min"] = float(m.group(1))
        hits.append(m.group(0))
    # Qualitative keywords run independently — 'cheap' / 'premium'
    # still needs to be stripped from the residual even when the
    # numeric branch already ran.
    if m := _CHEAP_RE.search(query):
        filters.setdefault("price_band", "impulse")
        hits.append(m.group(0))
    if m := _PREMIUM_RE.search(query):
        filters.setdefault("price_band", "premium")
        hits.append(m.group(0))
    return filters, hits


def _extract_niche(query: str) -> tuple[dict[str, Any], list[str]]:
    q = query.lower()
    for niche, keywords in _NICHES.items():
        for kw in keywords:
            # Word-boundary substring match
            if re.search(rf"\b{re.escape(kw)}", q):
                return {"niche": niche}, [kw]
    return {}, []


def _extract_rating(query: str) -> tuple[dict[str, Any], list[str]]:
    if m := _RATING_RE.search(query):
        return {"min_stars": int(m.group(1))}, [m.group(0)]
    if _GOOD_REVIEW_RE.search(query):
        return {"min_stars": 4}, ["good reviews"]
    return {}, []


def _extract_date(query: str) -> tuple[dict[str, Any], list[str]]:
    now = dt.datetime.utcnow()
    if m := _DATE_LAST_N_RE.search(query):
        n = int(m.group(1))
        unit = m.group(2).lower()
        days = {
            "day": 1, "days": 1,
            "week": 7, "weeks": 7,
            "month": 30, "months": 30,
        }.get(unit, 1)
        cutoff = now - dt.timedelta(days=n * days)
        return {"since_ts": cutoff.timestamp()}, [m.group(0)]
    for name, pattern in _DATE_NAMED_RE.items():
        if m := pattern.search(query):
            cutoff = now
            if name == "last_week":
                cutoff = now - dt.timedelta(days=7)
            elif name == "this_week":
                cutoff = now - dt.timedelta(days=now.weekday())
            elif name == "last_month":
                cutoff = now - dt.timedelta(days=30)
            elif name == "this_month":
                cutoff = dt.datetime(now.year, now.month, 1)
            elif name == "today":
                cutoff = dt.datetime(now.year, now.month, now.day)
            elif name == "yesterday":
                cutoff = dt.datetime(now.year, now.month, now.day) \
                    - dt.timedelta(days=1)
            return {"since_ts": cutoff.timestamp()}, [m.group(0)]
    return {}, []


_DEFAULT_EXTRACTORS: tuple[Extractor, ...] = (
    _extract_price,
    _extract_niche,
    _extract_rating,
    _extract_date,
)


# ── Rewriter ───────────────────────────────────────────────

class QueryRewriter:
    def __init__(self) -> None:
        self._extractors: list[Extractor] = list(_DEFAULT_EXTRACTORS)

    def register_extractor(self, fn: Extractor) -> None:
        self._extractors.append(fn)

    def rewrite(self, query: str) -> RewriteResult:
        raw = query or ""
        if not raw.strip():
            return RewriteResult(terms="", raw_query=raw)
        filters: dict[str, Any] = {}
        all_hits: list[str] = []
        for ext in self._extractors:
            try:
                f, hits = ext(raw)
            except Exception:
                continue
            # Merge without overwriting existing keys (first extractor wins)
            for k, v in f.items():
                filters.setdefault(k, v)
            all_hits.extend(hits)
        # Strip matched hits from residual to form clean terms
        residual = raw
        for hit in sorted(all_hits, key=len, reverse=True):
            residual = re.sub(
                re.escape(hit), " ", residual, flags=re.IGNORECASE,
            )
        residual = re.sub(r"\s+", " ", residual).strip()
        # Confidence scales with how much of the query we parsed
        non_blank = sum(1 for w in raw.split() if w.strip())
        extracted_words = sum(
            len(h.split()) for h in all_hits
        )
        conf = (
            min(1.0, (extracted_words + 1) / (non_blank + 1))
            if non_blank else 0.0
        )
        suggestions = self._suggestions(residual, filters)
        return RewriteResult(
            terms=residual,
            filters=filters,
            suggestions=suggestions,
            confidence=conf,
            raw_query=raw,
        )

    @staticmethod
    def _suggestions(
        residual: str, filters: dict[str, Any],
    ) -> list[str]:
        """Offer a cleaner canonical phrasing the owner may have meant."""
        bits: list[str] = []
        if "niche" in filters:
            bits.append(filters["niche"])
        if "price_band" in filters:
            bits.append(filters["price_band"])
        if residual:
            bits.append(residual)
        canonical = " ".join(bits).strip()
        if not canonical:
            return []
        return [canonical]
