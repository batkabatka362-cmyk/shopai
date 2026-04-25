"""Candidate fusion — cross-source dedup + trust-weighted merge.

Track 3b of AGI_HARDENING_PLAN. WinnerSearcher currently dedupes
by `canonical_key()` (title-slug sha1 prefix) so same product
from two sources produces one kept entry. But it keeps only the
*first* seen — discarding corroborating evidence. With the
SourceTrustCalibrator live, we can do better: merge duplicates,
combining evidence across sources and boosting confidence when
multiple trusted sources agree.

Merge policy (deterministic):

  * When 2+ candidates share ``canonical_key``, build one merged
    ``ProductCandidate``:
      - title: prefer the longest non-empty
      - price: trust-weighted average (falls back to first
               non-zero)
      - cost: mirror of price logic
      - image_url, url: first non-empty
      - tags: union
      - saturation_score: min across duplicates (lowest saturation
        wins)
      - daily_sales: max (strongest demand signal)
      - raw: ``sources`` list collected into raw["sources"] for
        audit
  * ``boost`` = 1 + 0.2 * (n_sources - 1) — caps at +80% for 5-
    source agreement. Emitted separately so WinnerSearcher can
    multiply it into the score.

Pure stdlib. LLM-free. Deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from agents.research.winner_searcher import ProductCandidate
from utils.logger import get_logger


logger = get_logger("agents.research.candidate_fusion")


@dataclass
class FusionResult:
    merged: tuple[ProductCandidate, ...]
    boost_map: dict[str, float]          # canonical_key → boost

    def as_dict(self) -> dict[str, Any]:
        return {
            "merged_count": len(self.merged),
            "boost_map": dict(self.boost_map),
        }


def _trust_for(
    calibrator: Any, source: str,
) -> float:
    if calibrator is None:
        return 1.0
    try:
        return max(
            0.01,
            min(1.0, float(
                calibrator.trust(source)
            )),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "trust lookup for %s failed: %s",
            source, exc,
        )
        return 1.0


def _weighted_avg(
    values: list[tuple[float, float]],
) -> float:
    """values = [(value, weight), ...]. Returns 0 when empty."""
    positive = [(v, w) for v, w in values if v > 0]
    if not positive:
        return 0.0
    total_w = sum(w for _, w in positive)
    if total_w <= 0:
        return positive[0][0]
    return sum(v * w for v, w in positive) / total_w


def fuse_candidates(
    candidates: Iterable[ProductCandidate],
    *,
    calibrator: Any = None,
    boost_per_extra_source: float = 0.2,
    boost_cap: float = 1.8,
) -> FusionResult:
    """Merge duplicate candidates by canonical_key.

    Returns ``FusionResult`` with (merged tuple, boost map). The
    merged list has one entry per canonical_key; singleton keys
    pass through unchanged.
    """
    if boost_per_extra_source < 0:
        raise ValueError(
            "boost_per_extra_source must be ≥ 0",
        )
    if boost_cap < 1.0:
        raise ValueError("boost_cap must be ≥ 1.0")

    buckets: dict[str, list[ProductCandidate]] = {}
    for c in candidates or []:
        key = c.canonical_key()
        buckets.setdefault(key, []).append(c)

    merged: list[ProductCandidate] = []
    boost_map: dict[str, float] = {}

    for key, rows in buckets.items():
        if len(rows) == 1:
            merged.append(rows[0])
            boost_map[key] = 1.0
            continue
        weights = [
            (_trust_for(calibrator, r.source), r)
            for r in rows
        ]
        # Title: longest
        title = ""
        for r in rows:
            if len(r.title) > len(title):
                title = r.title
        # Price / cost: trust-weighted
        price = _weighted_avg(
            [
                (float(r.price), w)
                for w, r in weights
            ],
        )
        cost = _weighted_avg(
            [
                (float(r.cost), w)
                for w, r in weights
            ],
        )
        # Image / URL: first non-empty
        image_url = next(
            (r.image_url for r in rows if r.image_url),
            "",
        )
        url = next(
            (r.url for r in rows if r.url), "",
        )
        # Tags: union, preserve order of first appearance
        seen: set[str] = set()
        tags: list[str] = []
        for r in rows:
            for t in r.tags or ():
                if t not in seen:
                    seen.add(t)
                    tags.append(t)
        saturation = min(r.saturation_score for r in rows)
        daily_sales = max(
            float(r.daily_sales) for r in rows
        )
        # External_id: keep the first source's id, since
        # downstream Shopify lookups use it
        first = rows[0]
        raw_blob: dict[str, Any] = dict(first.raw or {})
        raw_blob["sources"] = [
            {
                "source": r.source,
                "external_id": r.external_id,
                "price": r.price,
                "cost": r.cost,
            }
            for r in rows
        ]
        merged_candidate = ProductCandidate(
            source=first.source,
            external_id=first.external_id,
            title=title,
            price=price,
            cost=cost,
            daily_sales=daily_sales,
            saturation_score=saturation,
            image_url=image_url,
            url=url,
            tags=tuple(tags),
            raw=raw_blob,
        )
        merged.append(merged_candidate)
        extra = len(rows) - 1
        boost = min(
            float(boost_cap),
            1.0 + boost_per_extra_source * extra,
        )
        boost_map[key] = boost

    return FusionResult(
        merged=tuple(merged),
        boost_map=dict(boost_map),
    )
