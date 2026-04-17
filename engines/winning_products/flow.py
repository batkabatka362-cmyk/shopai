"""Winning Products Engine — picks dropshipping winners from spy data.

Pipeline input comes from the ads_spy adapter family (Minea,
PiPiAds, BigSpy, Facebook Ads Library). Every record uses the
normalised shape that :mod:`core.adapters.ads_spy._base` produces,
so this engine never touches vendor-specific fields.

The engine's job is three-fold:

1.  **Aggregate** — accept records from any combination of spy
    sources the operator has configured and merge them into a
    single pool.

2.  **Dedupe by product** — the same winning product typically
    shows up on multiple spy feeds (Meta + TikTok + BigSpy). We
    treat "same product" as "same ``product_url`` after
    normalisation". Each dedupe group carries the best signal
    from each source plus a ``source_count`` which itself is a
    conviction multiplier — an ad appearing on 3 spy sources is
    materially safer than one that appears on one.

3.  **Score + rank + verdict** — a 100-point scoring rubric
    translates the raw spy signals into a single "how confident
    am I that this is a winner" number. Verdicts gate the
    downstream product-launch orchestrator:

        * ``strong_buy``  — score ≥ 80: launch without human review
                            (if auto-approve on) or flag as
                            top-priority for operator inbox
        * ``buy``         — score ≥ 60: recommended, expect operator
                            click to confirm
        * ``watch``       — score ≥ 40: keep monitoring; not yet
        * ``skip``        — score < 40: reject, noise

Input shape::

    {
        "spy_records": [<normalised spy record>, ...],
        "criteria": {
            "min_days_running":    7,     # drop ads newer than 1 week
            "max_price":           200,   # dropship sweet spot ceiling
            "min_price":           15,
            "require_product_url": True,  # drop records without a
                                          # landing-page URL
            "tier1_countries":     ["US", "CA", "AU", "UK"],
            "top_k":               10,
        },
    }

Output::

    {
        "status": "success",
        "data": {
            "winners": [<scored product>, ...],   # top-K
            "verdict_counts": {
                "strong_buy": 1, "buy": 4, "watch": 12, "skip": 85,
            },
            "total_records": 102,                 # raw input count
            "unique_products": 47,                # post-dedupe
            "sources_seen": ["minea", "fb_ads_library"],
        },
        "meta": {...},
        "error": None,
    }

The scoring weights are deliberately on-disk (constants below)
so an operator can tune them without a code change — every
constant is small, named, and commented with its rationale.
"""
from __future__ import annotations

import copy
import re
import time
from typing import Any

ENGINE_NAME = "winning_products"


# ── Scoring weights (total: 100) ─────────────────────────────
#
# The weights reflect a master dropshipper's intuition:
#
#   days_running is THE signal. An ad running 30+ days at
#   profitable CPA is the single best proof that a product is
#   a winner. Hence the biggest bucket.
#
#   source_count is the second-order signal: the same product
#   getting picked up by multiple spy tools materially reduces
#   the false-positive rate (one spy tool can be wrong about
#   "trending"; three agreeing is almost never wrong).
#
#   engagement_velocity (likes+comments+shares per day) proxies
#   for viral potential — a long-running ad with low engagement
#   is a "well-optimised evergreen" (boring but safe); high
#   velocity is a viral winner (high-reward, higher risk).
#
#   Everything else (views, country breadth, price fit) rounds
#   out the picture but shouldn't dominate.
_W_DAYS_RUNNING = 40
_W_SOURCE_COUNT = 15
_W_ENGAGEMENT_VELOCITY = 20
_W_VIEWS = 10
_W_COUNTRY_BREADTH = 10
_W_PRICE_FIT = 5

# Verdict thresholds — intentionally coarse. The goal is to
# spend operator attention on the fewer-but-higher-conviction
# candidates rather than drown them in watchlist noise.
_VERDICT_STRONG_BUY = 80
_VERDICT_BUY = 60
_VERDICT_WATCH = 40


class WinningProductsEngine:
    """Wrapper class for engine-registry compatibility.

    Mirrors the pattern that :class:`engines.product_research.
    ProductResearchEngine` uses so the registry's auto-discovery
    treats this engine the same as every other.
    """

    ENGINE_NAME = ENGINE_NAME
    engine_name = ENGINE_NAME

    def run(self, input_data: dict[str, Any] | None = None) -> dict[str, Any]:
        return run(input_data)


def _fail(msg: str, start: float) -> dict[str, Any]:
    return {
        "status": "error",
        "data": {},
        "meta": {
            "engine": ENGINE_NAME,
            "timestamp": time.time(),
            "elapsed_seconds": round(time.monotonic() - start, 3),
        },
        "error": msg,
    }


def run(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Public entry point.

    The function deep-copies its input so downstream mutation
    inside the scoring stages can never leak back into the
    caller's dict — mirrors the copy-on-entry contract that
    :class:`engines.base.BaseEngine` enforces for its subclass
    pipeline.
    """
    start = time.monotonic()
    data = copy.deepcopy(input_data or {})

    # Propagate upstream failures so a broken spy call doesn't
    # silently produce an empty winners list that the
    # orchestrator would interpret as "no good products this
    # cycle" (falsely).
    if data.get("status") == "fail":
        return _fail(data.get("error") or "Upstream failure", start)

    records = data.get("spy_records") or []
    if not isinstance(records, list):
        return _fail(
            f"'spy_records' must be a list, got {type(records).__name__}",
            start,
        )

    criteria = data.get("criteria") or {}
    if not isinstance(criteria, dict):
        criteria = {}

    min_days = int(criteria.get("min_days_running", 7))
    max_price = float(criteria.get("max_price", 200))
    min_price = float(criteria.get("min_price", 15))
    require_url = bool(criteria.get("require_product_url", True))
    tier1_countries = [
        str(c).upper() for c in
        (criteria.get("tier1_countries") or ["US", "CA", "AU", "UK"])
    ]
    top_k = int(criteria.get("top_k", 10))
    if top_k < 1:
        top_k = 10

    # ── Stage 1: filter ────────────────────────────────────
    filtered = _filter_records(
        records,
        min_days=min_days,
        require_url=require_url,
    )

    # ── Stage 2: dedupe by product ─────────────────────────
    grouped = _group_by_product(filtered)

    # ── Stage 3: score each unique product ────────────────
    sources_seen: set[str] = set()
    scored: list[dict[str, Any]] = []
    for product_key, records_for_product in grouped.items():
        for r in records_for_product:
            src = r.get("source") or ""
            if src:
                sources_seen.add(str(src))
        scored.append(
            _score_product(
                product_key,
                records_for_product,
                max_price=max_price,
                min_price=min_price,
                tier1_countries=tier1_countries,
            ),
        )

    # ── Stage 4: rank + verdict + trim ────────────────────
    scored.sort(key=lambda p: p.get("score", 0), reverse=True)
    verdict_counts = {
        "strong_buy": 0, "buy": 0, "watch": 0, "skip": 0,
    }
    for p in scored:
        v = p.get("verdict", "skip")
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    winners = scored[:top_k]

    elapsed = round(time.monotonic() - start, 3)
    return {
        "status": "success",
        "data": {
            "winners": winners,
            "verdict_counts": verdict_counts,
            "total_records": len(records),
            "total_after_filter": len(filtered),
            "unique_products": len(grouped),
            "sources_seen": sorted(sources_seen),
        },
        "meta": {
            "engine": ENGINE_NAME,
            "timestamp": time.time(),
            "elapsed_seconds": elapsed,
        },
        "error": None,
    }


# ---------------------------------------------------------------------------
# Internal stages
# ---------------------------------------------------------------------------


def _filter_records(
    records: list[dict[str, Any]],
    *,
    min_days: int,
    require_url: bool,
) -> list[dict[str, Any]]:
    """Drop obviously-noise records before we spend time scoring."""
    out: list[dict[str, Any]] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        # Fresh ads (< min_days) don't yet have the track record
        # we rank on. Keep them for a future pass, not this one.
        if int(r.get("days_running", 0) or 0) < min_days:
            continue
        product_url = str(r.get("product_url", "") or "")
        if require_url and not product_url:
            continue
        out.append(r)
    return out


def _group_by_product(
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group spy records by normalised product key.

    The key is derived from ``product_url`` (strip scheme, query
    string, and trailing slash) so the same Shopify product at
    ``https://store.com/products/x?ref=fb`` and
    ``https://store.com/products/x/`` groups together.
    When ``product_url`` is empty (free FB endpoint without a
    token often has this), fall back to ``advertiser`` + first
    few words of the headline so records still dedupe within a
    single source.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        key = _product_key(r)
        groups.setdefault(key, []).append(r)
    return groups


_URL_QUERY_RE = re.compile(r"[?#].*$")


def _product_key(record: dict[str, Any]) -> str:
    url = str(record.get("product_url", "") or "").strip().lower()
    if url:
        # Strip scheme
        for prefix in ("https://", "http://", "www."):
            if url.startswith(prefix):
                url = url[len(prefix):]
        # Drop query / fragment / trailing slash
        url = _URL_QUERY_RE.sub("", url).rstrip("/")
        return f"url:{url}"

    advertiser = str(record.get("advertiser", "") or "").strip().lower()
    headline = str(record.get("headline", "") or "").strip().lower()
    head_words = " ".join(headline.split()[:5])
    if advertiser or head_words:
        return f"heuristic:{advertiser}|{head_words}"
    return f"ad:{record.get('ad_id', '') or id(record)}"


def _score_product(
    product_key: str,
    records: list[dict[str, Any]],
    *,
    max_price: float,
    min_price: float,
    tier1_countries: list[str],
) -> dict[str, Any]:
    """Score a single (deduped) product on winning-product signals.

    Every record in ``records`` points at the same underlying
    product. We take the *best* signal for each dimension
    (max days_running, max views, etc.) so a product that
    a single spy source under-reported doesn't get penalised
    — conviction should go up, not down, with more data.
    """
    factors: dict[str, Any] = {}
    score = 0.0

    # ── Days running ─────────────────────────────────────
    max_days = max(
        (int(r.get("days_running", 0) or 0) for r in records),
        default=0,
    )
    # Piecewise: diminishing returns past 60 days.
    # 0d→0 | 7d→4 | 14d→10 | 30d→25 | 60d→35 | 90d→40
    if max_days >= 90:
        dr_score = _W_DAYS_RUNNING  # 40
    elif max_days >= 60:
        dr_score = 35
    elif max_days >= 30:
        dr_score = 25
    elif max_days >= 14:
        dr_score = 10
    elif max_days >= 7:
        dr_score = 4
    else:
        dr_score = 0
    factors["days_running"] = {
        "value": max_days,
        "score": dr_score,
        "weight": _W_DAYS_RUNNING,
        "detail": f"{max_days} days at best",
    }
    score += dr_score

    # ── Source count (conviction multiplier) ─────────────
    unique_sources = {str(r.get("source") or "") for r in records} - {""}
    source_count = len(unique_sources)
    # 1 source → 5/15 | 2 → 10/15 | 3+ → 15/15
    if source_count >= 3:
        sc_score = _W_SOURCE_COUNT
    elif source_count == 2:
        sc_score = 10
    elif source_count == 1:
        sc_score = 5
    else:
        sc_score = 0
    factors["source_count"] = {
        "value": source_count,
        "score": sc_score,
        "weight": _W_SOURCE_COUNT,
        "sources": sorted(unique_sources),
    }
    score += sc_score

    # ── Engagement velocity ─────────────────────────────
    # (likes + comments*2 + shares*3) per day — comments and
    # shares cost more effort than likes so weight them higher.
    best_velocity = 0.0
    for r in records:
        days = max(int(r.get("days_running", 0) or 0), 1)
        eng = r.get("engagement") or {}
        if not isinstance(eng, dict):
            continue
        likes = int(eng.get("likes", 0) or 0)
        comments = int(eng.get("comments", 0) or 0)
        shares = int(eng.get("shares", 0) or 0)
        per_day = (likes + comments * 2 + shares * 3) / days
        if per_day > best_velocity:
            best_velocity = per_day
    # 0/day→0 | 10/day→4 | 50/day→10 | 250/day→15 | 1000+/day→20
    if best_velocity >= 1000:
        ev_score = _W_ENGAGEMENT_VELOCITY
    elif best_velocity >= 250:
        ev_score = 15
    elif best_velocity >= 50:
        ev_score = 10
    elif best_velocity >= 10:
        ev_score = 4
    else:
        ev_score = 0
    factors["engagement_velocity"] = {
        "value": round(best_velocity, 2),
        "score": ev_score,
        "weight": _W_ENGAGEMENT_VELOCITY,
        "detail": f"{round(best_velocity, 1)} weighted engagements/day",
    }
    score += ev_score

    # ── Views ───────────────────────────────────────────
    def _views_of(r: dict[str, Any]) -> int:
        eng = r.get("engagement") or {}
        if not isinstance(eng, dict):
            return 0
        return int(eng.get("views", 0) or 0)

    max_views = max((_views_of(r) for r in records), default=0)
    # 0→0 | 10k→2 | 100k→5 | 500k→8 | 1M+→10
    if max_views >= 1_000_000:
        v_score = _W_VIEWS
    elif max_views >= 500_000:
        v_score = 8
    elif max_views >= 100_000:
        v_score = 5
    elif max_views >= 10_000:
        v_score = 2
    else:
        v_score = 0
    factors["views"] = {
        "value": max_views,
        "score": v_score,
        "weight": _W_VIEWS,
    }
    score += v_score

    # ── Country breadth (Tier 1 coverage) ───────────────
    countries_seen: set[str] = set()
    for r in records:
        for c in (r.get("country_targets") or []):
            countries_seen.add(str(c).upper())
    tier1_hits = sum(1 for c in tier1_countries if c in countries_seen)
    # 0→0 | 1→3 | 2→6 | 3→8 | 4+→10
    if tier1_hits >= 4:
        cb_score = _W_COUNTRY_BREADTH
    elif tier1_hits == 3:
        cb_score = 8
    elif tier1_hits == 2:
        cb_score = 6
    elif tier1_hits == 1:
        cb_score = 3
    else:
        cb_score = 0
    factors["country_breadth"] = {
        "tier1_hit_count": tier1_hits,
        "countries_seen": sorted(countries_seen),
        "score": cb_score,
        "weight": _W_COUNTRY_BREADTH,
    }
    score += cb_score

    # ── Price fit ───────────────────────────────────────
    price_estimate = 0.0
    for r in records:
        ps = r.get("product_signals") or {}
        if isinstance(ps, dict):
            pe = float(ps.get("price_estimate", 0) or 0)
            if pe > price_estimate:
                price_estimate = pe
    if min_price <= price_estimate <= max_price:
        pf_score = _W_PRICE_FIT
        pf_detail = f"${price_estimate:.2f} in sweet spot"
    elif price_estimate == 0:
        # No price info — can't penalise since many sources omit
        # this; give partial credit.
        pf_score = 2
        pf_detail = "price unknown"
    else:
        pf_score = 0
        pf_detail = f"${price_estimate:.2f} outside {min_price}-{max_price}"
    factors["price_fit"] = {
        "price_estimate": round(price_estimate, 2),
        "score": pf_score,
        "weight": _W_PRICE_FIT,
        "detail": pf_detail,
    }
    score += pf_score

    # ── Verdict ─────────────────────────────────────────
    verdict = _verdict_for(score)

    # ── Representative ad (for operator display) ───────
    # Pick the record with the most days_running + highest
    # engagement as the "face" of the product. This is what
    # the dashboard / approval-gate UI renders.
    hero = max(
        records,
        key=lambda r: (
            int(r.get("days_running", 0) or 0),
            _views_of(r),
        ),
    )

    return {
        "product_key": product_key,
        "score": round(score, 2),
        "verdict": verdict,
        "factors": factors,
        "source_count": source_count,
        "sources": sorted(unique_sources),
        "record_count": len(records),
        "hero_ad": {
            "ad_id":        hero.get("ad_id", ""),
            "source":       hero.get("source", ""),
            "advertiser":   hero.get("advertiser", ""),
            "product_url":  hero.get("product_url", ""),
            "creative_url": hero.get("creative_url", ""),
            "headline":     hero.get("headline", ""),
            "copy":         hero.get("copy", ""),
            "days_running": int(hero.get("days_running", 0) or 0),
            "raw_url":      hero.get("raw_url", ""),
        },
    }


def _verdict_for(score: float) -> str:
    if score >= _VERDICT_STRONG_BUY:
        return "strong_buy"
    if score >= _VERDICT_BUY:
        return "buy"
    if score >= _VERDICT_WATCH:
        return "watch"
    return "skip"
