"""Winner searcher — autonomous winning-product discovery.

M2.1 of the AGI roadmap: find products worth launching before the
brain even decides how. Given N pluggable sources (AliExpress
trending, Amazon BSR, TikTok product spy, Meta ad library), the
searcher:

  1. Fetches candidates from every registered source.
  2. Dedupes by canonical key (title slug + source fingerprint).
  3. Scores each: margin * demand * (1 - saturation).
  4. Publishes the top-N into knowledge_base so ``goal_decomposer``
     can pick them up for launch planning.
  5. Feeds the brain learners — funnel, concept_former, decision
     reversal detector — when a winner is committed.

Sources implement the ``WinnerSource`` ABC. Real sources (AliScraper,
Amazon BSR crawler, TikTok Spy via Apify) live under
``agents/research/sources/`` and are registered at startup. This
module ships with ``StaticWinnerSource`` for tests and deterministic
smoke runs; external-API sources are feature-flag wrapped so they
don't activate without explicit config.

Pure stdlib, deterministic given inputs. Complements
``winner_selector.py`` (A/B test winner picker) — that module
chooses WHICH variant wins; this one chooses WHICH product to
launch.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("agents.research.winner_searcher")


@dataclass
class ProductCandidate:
    """Normalised product shape produced by every source."""
    source: str
    external_id: str
    title: str
    price: float                  # retail; assumed USD
    cost: float = 0.0             # wholesale/landed
    daily_sales: float = 0.0      # demand proxy
    saturation_score: float = 0.0  # 0..1, higher = more competitors
    image_url: str = ""
    url: str = ""
    tags: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def margin_pct(self) -> float:
        if self.price <= 0:
            return 0.0
        return max(0.0, (self.price - self.cost) / self.price)

    def canonical_key(self) -> str:
        """Key used for dedupe across sources."""
        slug = re.sub(r"[^a-z0-9]+", "_", self.title.lower()).strip("_")
        return hashlib.sha1(slug.encode("utf-8")).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "external_id": self.external_id,
            "title": self.title,
            "price": round(self.price, 4),
            "cost": round(self.cost, 4),
            "daily_sales": round(self.daily_sales, 4),
            "saturation_score": round(self.saturation_score, 4),
            "margin_pct": round(self.margin_pct, 4),
            "image_url": self.image_url,
            "url": self.url,
            "tags": list(self.tags),
        }


@dataclass
class WinnerScore:
    candidate: ProductCandidate
    score: float
    components: dict[str, float]   # margin / demand / saturation breakdown

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.as_dict(),
            "score": round(self.score, 4),
            "components": {
                k: round(v, 4)
                for k, v in self.components.items()
            },
        }


class WinnerSource(ABC):
    """Pluggable source for product candidates."""

    name: str = ""

    @abstractmethod
    def fetch(self, *, limit: int = 100) -> list[ProductCandidate]:
        """Return a list of candidates. Best-effort; raise
        sparingly — the searcher isolates source failures."""
        raise NotImplementedError

    def is_available(self) -> bool:
        """Subclasses guard on env config here."""
        return True


class StaticWinnerSource(WinnerSource):
    """Deterministic source for tests + smoke runs.

    Ships with a fixed candidate list; callers can override via
    __init__ to inject whatever seed they need.
    """
    name = "static"

    def __init__(
        self,
        candidates: Iterable[ProductCandidate] | None = None,
        *,
        name: str = "static",
    ) -> None:
        self.name = name
        self._seed = list(candidates or [])

    def fetch(self, *, limit: int = 100) -> list[ProductCandidate]:
        return list(self._seed[: max(1, int(limit))])


def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


def _demand_component(daily_sales: float) -> float:
    """Log-compressed demand score so one mega-seller doesn't
    dominate the ranking. 0 orders/day → 0, 100/day → ~0.88."""
    import math
    if daily_sales <= 0:
        return 0.0
    return _clip(math.log1p(daily_sales) / math.log1p(200.0))


@dataclass
class WinnerSearchResult:
    candidates_examined: int
    deduped: int
    sources_used: tuple[str, ...]
    ranked: list[WinnerScore]
    published: list[str]        # kb subjects written
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidates_examined": self.candidates_examined,
            "deduped": self.deduped,
            "sources_used": list(self.sources_used),
            "ranked": [r.as_dict() for r in self.ranked],
            "published": list(self.published),
            "ts": self.ts,
        }


def _hooks_on() -> bool:
    return os.getenv("SHOPAI_BRAIN_HOOKS", "") == "1"


class WinnerSearcher:
    """Orchestrate fetch → dedupe → score → publish pipeline."""

    def __init__(
        self,
        *,
        sources: Iterable[WinnerSource] | None = None,
        margin_weight: float = 0.35,
        demand_weight: float = 0.4,
        saturation_weight: float = 0.25,
        min_margin_pct: float = 0.15,
        knowledge_base: Any = None,
    ) -> None:
        w_total = (
            margin_weight + demand_weight + saturation_weight
        )
        if abs(w_total - 1.0) > 1e-6:
            raise ValueError(
                "weights must sum to 1.0",
            )
        if not 0.0 <= min_margin_pct < 1.0:
            raise ValueError(
                "min_margin_pct must be in [0, 1)",
            )
        self._lock = threading.Lock()
        self._sources: list[WinnerSource] = list(sources or [])
        self._mw = float(margin_weight)
        self._dw = float(demand_weight)
        self._sw = float(saturation_weight)
        self._min_margin = float(min_margin_pct)
        self._kb = knowledge_base
        self._history: list[WinnerSearchResult] = []

    # ── Source registry ─────────────────────────────────

    def register_source(self, source: WinnerSource) -> None:
        with self._lock:
            self._sources.append(source)

    def unregister_source(self, name: str) -> bool:
        with self._lock:
            before = len(self._sources)
            self._sources = [
                s for s in self._sources if s.name != name
            ]
            return len(self._sources) < before

    # ── Pipeline ────────────────────────────────────────

    def _fetch_all(
        self, *, per_source_limit: int,
    ) -> tuple[list[ProductCandidate], tuple[str, ...]]:
        with self._lock:
            sources = list(self._sources)
        gathered: list[ProductCandidate] = []
        used: list[str] = []
        for src in sources:
            try:
                if not src.is_available():
                    continue
                items = src.fetch(limit=per_source_limit)
                gathered.extend(items)
                used.append(src.name or src.__class__.__name__)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "source %s fetch failed: %s",
                    src.name or src.__class__.__name__, exc,
                )
        return gathered, tuple(used)

    def _dedupe(
        self, candidates: list[ProductCandidate],
    ) -> list[ProductCandidate]:
        seen: dict[str, ProductCandidate] = {}
        for c in candidates:
            key = c.canonical_key()
            prior = seen.get(key)
            # Prefer the candidate with higher margin * demand
            if prior is None:
                seen[key] = c
            else:
                old_s = prior.margin_pct * (prior.daily_sales or 1.0)
                new_s = c.margin_pct * (c.daily_sales or 1.0)
                if new_s > old_s:
                    seen[key] = c
        return list(seen.values())

    def score(
        self, candidate: ProductCandidate,
    ) -> WinnerScore:
        margin = _clip(candidate.margin_pct)
        demand = _demand_component(candidate.daily_sales)
        saturation_fit = 1.0 - _clip(candidate.saturation_score)
        components = {
            "margin": self._mw * margin,
            "demand": self._dw * demand,
            "saturation_fit": self._sw * saturation_fit,
        }
        total = sum(components.values())
        return WinnerScore(
            candidate=candidate,
            score=total,
            components=components,
        )

    def search(
        self,
        *,
        per_source_limit: int = 100,
        top_n: int = 10,
        publish: bool = True,
    ) -> WinnerSearchResult:
        if top_n < 1:
            raise ValueError("top_n must be ≥ 1")
        gathered, used = self._fetch_all(
            per_source_limit=per_source_limit,
        )
        deduped = self._dedupe(gathered)
        # Enforce margin floor before scoring — a 5% margin is dead
        # on arrival whatever the demand.
        eligible = [
            c for c in deduped
            if c.margin_pct >= self._min_margin
        ]
        ranked = [self.score(c) for c in eligible]
        ranked.sort(key=lambda s: -s.score)
        top = ranked[: max(1, int(top_n))]
        published: list[str] = []
        if publish and top:
            published = self._publish_winners(top)
        result = WinnerSearchResult(
            candidates_examined=len(gathered),
            deduped=len(deduped),
            sources_used=used,
            ranked=top,
            published=published,
            ts=time.time(),
        )
        with self._lock:
            self._history.append(result)
            if len(self._history) > 100:
                del self._history[: len(self._history) - 100]
        return result

    def _publish_winners(
        self, top: list[WinnerScore],
    ) -> list[str]:
        """Write each winner into knowledge_base + feed brain."""
        subjects: list[str] = []
        kb = self._kb
        if kb is None:
            try:
                from core.memory.knowledge_base import KnowledgeBase
                kb = KnowledgeBase()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "knowledge_base unavailable: %s", exc,
                )
                kb = None
        # Cache brain ref once
        brain = None
        if _hooks_on():
            try:
                from core.brain.brain_facade import brain as _brain
                brain = _brain()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "brain unavailable: %s", exc,
                )
        for rank, scored in enumerate(top, start=1):
            c = scored.candidate
            subject = (
                f"winner.{c.canonical_key()}"
            )
            if kb is not None:
                try:
                    kb.assert_fact(
                        subject, "title",
                        c.title,
                        source=f"winner_searcher:{c.source}",
                    )
                    kb.assert_fact(
                        subject, "score",
                        round(scored.score, 4),
                        source="winner_searcher",
                    )
                    kb.assert_fact(
                        subject, "margin_pct",
                        round(c.margin_pct, 4),
                        source="winner_searcher",
                    )
                    kb.assert_fact(
                        subject, "rank",
                        rank,
                        source="winner_searcher",
                    )
                    kb.assert_fact(
                        subject, "url",
                        c.url,
                        source=c.source,
                    )
                    subjects.append(subject)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "kb assert failed for %s: %s",
                        subject, exc,
                    )
            # Brain-side ingestion — each published winner is a
            # decision target for future launch tracking, and a
            # concept to cluster.
            if brain is not None:
                try:
                    brain.observe_concept(
                        {
                            "kind": "winner_candidate",
                            "source": c.source,
                            "title": c.title[:64],
                            "margin_band": _margin_band(
                                c.margin_pct,
                            ),
                            "saturation_band": _band(
                                c.saturation_score,
                            ),
                        },
                        outcome_sign="pos",
                    )
                    brain.record_decision(
                        target=subject,
                        action="pick_winner",
                        rationale=(
                            f"score={scored.score:.3f}; "
                            f"margin={c.margin_pct:.2f}; "
                            f"demand={c.daily_sales:.1f}/d"
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "brain winner ingest failed: %s", exc,
                    )
        return subjects

    # ── Queries ──────────────────────────────────────────

    def recent(
        self, *, limit: int = 10,
    ) -> list[WinnerSearchResult]:
        with self._lock:
            return list(
                self._history[-max(1, int(limit)):],
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            source_names = sorted(
                s.name or s.__class__.__name__
                for s in self._sources
            )
            return {
                "sources": len(self._sources),
                "source_names": source_names,
                "searches": len(self._history),
                "weights": {
                    "margin": self._mw,
                    "demand": self._dw,
                    "saturation": self._sw,
                },
                "min_margin_pct": self._min_margin,
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._history)
            self._history.clear()
        return n


def _margin_band(pct: float) -> str:
    if pct >= 0.7:
        return "hi"
    if pct >= 0.4:
        return "mid"
    return "lo"


def _band(v: float) -> str:
    c = _clip(v)
    if c >= 0.66:
        return "hi"
    if c >= 0.33:
        return "mid"
    return "lo"
