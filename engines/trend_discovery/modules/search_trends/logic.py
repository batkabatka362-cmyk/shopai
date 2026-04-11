"""Search trends decision logic — which trending keywords to act on.

Not all rising keywords are worth pursuing. This decides:
  - Is the keyword commercially viable?
  - Can we rank for it realistically?
  - Is the growth sustainable or a spike?
"""
from __future__ import annotations

from typing import Any


def decide_keyword_pursuit(keyword_data: dict[str, Any]) -> dict[str, Any]:
    """Should we target this keyword?"""
    score = keyword_data.get("opportunity_score", 0)
    volume = keyword_data.get("volume", 0)
    growth = keyword_data.get("growth_pct", 0)
    competition = keyword_data.get("competition", "medium")
    intent = keyword_data.get("intent", "informational")

    # Scoring
    pursuit_score = score

    # Volume gate — need minimum traffic
    if volume < 500:
        pursuit_score -= 20
        volume_note = "Low volume (<500) — niche, may not generate enough traffic"
    elif volume > 10000:
        pursuit_score += 10
        volume_note = "High volume — significant traffic potential"
    else:
        volume_note = "Adequate volume"

    # Intent boost
    if intent == "transactional":
        pursuit_score += 10
        intent_note = "Transactional intent — high purchase likelihood"
    elif intent == "commercial":
        pursuit_score += 5
        intent_note = "Commercial intent — comparison/research phase"
    else:
        intent_note = "Informational intent — content opportunity but not direct sales"

    # Competition penalty
    if competition == "high":
        pursuit_score -= 15
        comp_note = "High competition — hard to rank, expensive ads"
    elif competition == "low":
        pursuit_score += 10
        comp_note = "Low competition — easy ranking opportunity"
    else:
        comp_note = "Medium competition — achievable with effort"

    # Sustainability check
    if growth > 200:
        pursuit_score -= 10
        growth_note = f"Extreme growth ({growth}%) — possibly unsustainable spike"
    elif 20 < growth < 100:
        pursuit_score += 5
        growth_note = f"Healthy growth ({growth}%) — sustainable trend"
    else:
        growth_note = f"Growth at {growth}%"

    pursuit_score = max(0, min(100, pursuit_score))

    if pursuit_score >= 65:
        verdict = "target"
        action = "Create product + content targeting this keyword"
    elif pursuit_score >= 40:
        verdict = "consider"
        action = "Research further — create content first, product later"
    else:
        verdict = "skip"
        action = "Not worth targeting at this time"

    return {
        "verdict": verdict,
        "pursuit_score": pursuit_score,
        "action": action,
        "factors": {
            "volume": volume_note,
            "intent": intent_note,
            "competition": comp_note,
            "growth": growth_note,
        },
    }


def cluster_keywords(keywords: list[dict[str, Any]]) -> dict[str, Any]:
    """Group related keywords into clusters for content strategy.

    Clusters help create content that ranks for multiple related keywords.
    """
    clusters: dict[str, list] = {}

    for kw in keywords:
        term = kw.get("keyword", "").lower()
        # Simple clustering by shared words
        words = set(term.split())
        placed = False

        for cluster_name, members in clusters.items():
            cluster_words = set(cluster_name.split())
            overlap = len(words & cluster_words)
            if overlap >= 1 and len(words) > 1:
                members.append(kw)
                placed = True
                break

        if not placed:
            clusters[term] = [kw]

    # Score clusters
    scored_clusters = []
    for name, members in clusters.items():
        total_volume = sum(m.get("volume", 0) for m in members)
        avg_growth = sum(m.get("growth_pct", 0) for m in members) / max(len(members), 1)
        scored_clusters.append({
            "cluster": name,
            "keywords": [m.get("keyword", "") for m in members],
            "keyword_count": len(members),
            "total_volume": total_volume,
            "avg_growth": round(avg_growth, 1),
            "priority": "high" if total_volume > 5000 and avg_growth > 20 else "medium" if total_volume > 1000 else "low",
        })

    scored_clusters.sort(key=lambda c: c["total_volume"], reverse=True)

    return {
        "clusters": scored_clusters,
        "total_clusters": len(scored_clusters),
        "strategy": "Target top 3 clusters with dedicated product + content pages",
    }


def rank_keyword_opportunities(keywords: list[dict[str, Any]], max_targets: int = 10) -> list[dict[str, Any]]:
    """Rank all keywords by opportunity and return top targets."""
    ranked = []
    for kw in keywords:
        decision = decide_keyword_pursuit(kw)
        ranked.append({**kw, **decision})

    ranked.sort(key=lambda k: k["pursuit_score"], reverse=True)
    return ranked[:max_targets]
