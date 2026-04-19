"""Social proof aggregator — mine testimonials for ad creative.

Reviews and testimonials are the single highest-converting element
in ad creatives, yet they live in disparate places: Shopify reviews
metafields, Judge.me, Loox, TrustPilot, customer emails. This
module collects any available review text, clusters by theme, and
surfaces short high-signal quotes the CreativeStep / storefront
blocks can drop in.

Sources supported:

  • Shopify product metafields — if the store stamps review text
    under ``reviews/collected`` (Judge.me / Loox do this natively).
  • MemoryIntelligence ``category=review`` events — any path that
    ingests third-party reviews lands here.

Clustering is keyword-based (ship speed, quality, price, design,
support, trust) — cheap and deterministic; an optional LLM pass
can re-tag ambiguous reviews if configured.

Output:
  SocialProofPack(product_id=…, themes={quality: [quote, ...], …},
                   top_quotes=[...], star_rating_avg=…, review_count=…)

Pure Python lookup + keyword match. Safe to call per-launch or
once per cycle.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DB_PATH = Path("data/memory_intelligence.db")

_THEMES = {
    "quality":      ("quality", "well-made", "sturdy", "durable",
                     "premium", "solid"),
    "shipping":     ("fast", "quick", "arrived", "delivered", "on time",
                     "shipping"),
    "price":        ("price", "cheap", "worth", "value", "affordable"),
    "design":       ("beautiful", "gorgeous", "color", "style", "look",
                     "design"),
    "support":      ("support", "help", "response", "customer service"),
    "trust":        ("legit", "authentic", "real", "trusted", "scam-free"),
    "recommend":    ("recommend", "tell my friends", "love", "best", "5 stars"),
}


@dataclass
class Quote:
    text: str
    stars: int
    source: str
    themes: list[str] = field(default_factory=list)

    @property
    def signal(self) -> int:
        """Weight used for ranking. Longer, higher-star, multi-theme
        quotes rank above filler."""
        return (self.stars * 3
                + len(self.themes) * 2
                + min(len(self.text), 200) // 40)

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "stars": self.stars,
            "source": self.source,
            "themes": self.themes,
        }


@dataclass
class SocialProofPack:
    product_id: int | None = None
    review_count: int = 0
    star_rating_avg: float = 0.0
    themes: dict[str, list[Quote]] = field(default_factory=dict)
    top_quotes: list[Quote] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "review_count": self.review_count,
            "star_rating_avg": round(self.star_rating_avg, 2),
            "themes": {
                k: [q.as_dict() for q in v]
                for k, v in self.themes.items()
            },
            "top_quotes": [q.as_dict() for q in self.top_quotes],
        }


# ── Public API ──────────────────────────────────────────────

def aggregate(product_id: int | None = None, top_k: int = 5) -> SocialProofPack:
    """Aggregate reviews into a SocialProofPack."""
    reviews = _load_reviews(product_id=product_id)
    if not reviews:
        return SocialProofPack(product_id=product_id)

    star_sum = 0.0
    star_n = 0
    quotes: list[Quote] = []
    for r in reviews:
        text = (r.get("text") or "").strip()
        if not text:
            continue
        stars = int(r.get("stars") or r.get("rating") or 0)
        source = r.get("source") or "memory"
        themes = _tag_themes(text)
        if stars:
            star_sum += stars
            star_n += 1
        quotes.append(Quote(
            text=text[:280], stars=stars, source=source,
            themes=themes,
        ))

    # Theme buckets
    by_theme: dict[str, list[Quote]] = defaultdict(list)
    for q in quotes:
        for t in q.themes:
            by_theme[t].append(q)
    for bucket in by_theme.values():
        bucket.sort(key=lambda q: -q.signal)
        del bucket[3:]    # cap at 3 per theme so renderer stays light

    # Top quotes overall
    ranked = sorted(quotes, key=lambda q: -q.signal)[:top_k]

    return SocialProofPack(
        product_id=product_id,
        review_count=len(quotes),
        star_rating_avg=(star_sum / star_n) if star_n else 0.0,
        themes=dict(by_theme),
        top_quotes=ranked,
    )


# ── Internals ───────────────────────────────────────────────

def _load_reviews(product_id: int | None) -> list[dict[str, Any]]:
    if not _DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        if product_id:
            cur.execute(
                "SELECT content FROM memories "
                "WHERE category='review' "
                "  AND tags LIKE ? "
                "ORDER BY timestamp DESC LIMIT 300",
                (f"%product:{product_id}%",),
            )
        else:
            cur.execute(
                "SELECT content FROM memories "
                "WHERE category='review' "
                "ORDER BY timestamp DESC LIMIT 300",
            )
        rows = cur.fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for (content_json,) in rows:
        try:
            c = json.loads(content_json or "{}")
        except (json.JSONDecodeError, ValueError):
            continue
        out.append(c)
    return out


def _tag_themes(text: str) -> list[str]:
    """Keyword-based theme tagger. Return every theme whose keyword
    set matches at least once. Case-insensitive."""
    lower = text.lower()
    tags = []
    for theme, keywords in _THEMES.items():
        if any(kw in lower for kw in keywords):
            tags.append(theme)
    return tags


def record_review(
    product_id: int,
    text: str,
    stars: int = 0,
    source: str = "unknown",
) -> int:
    """Helper so external importers (Judge.me / Loox hooks) can drop
    a review directly into memory."""
    try:
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        mid = mi.create(
            category="review",
            content={"text": text, "stars": stars, "source": source,
                     "product_id": product_id},
            action="review",
            score=3.5 + (stars / 10.0),
            tags=["review", source, f"product:{product_id}",
                  f"stars:{stars}"],
        )
        return int(mid) if mid else 0
    except Exception:
        return 0
