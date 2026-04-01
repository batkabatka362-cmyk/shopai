"""Social trends decision logic — which viral products to pursue.

Not all viral content translates to product opportunity. This decides:
  - Is the virality product-driven or entertainment-driven?
  - Is the trend sustainable or a flash-in-the-pan?
  - Which platform strategy maximizes ROI?
"""
from __future__ import annotations

from typing import Any


def decide_social_pursuit(trend_data: dict[str, Any]) -> dict[str, Any]:
    """Should we pursue this viral product? Returns pursue/monitor/skip."""
    virality = trend_data.get("virality_score", 0)
    spread = trend_data.get("platform_spread", 0)
    creator_tier = trend_data.get("creator_tier", "unknown")
    hashtag_intent = trend_data.get("hashtag_purchase_intent", 0)
    composite = trend_data.get("composite_score", 0)

    pursuit_score = composite

    # Multi-platform confirmation is a strong signal
    if spread >= 3:
        pursuit_score += 15
        spread_note = "Cross-platform virality — high confidence demand signal"
    elif spread == 2:
        pursuit_score += 5
        spread_note = "Dual-platform presence — moderate confirmation"
    elif spread == 1:
        spread_note = "Single-platform only — needs confirmation before acting"
    else:
        pursuit_score -= 15
        spread_note = "No meaningful platform activity detected"

    # Creator-tier adjustment
    if creator_tier == "mega":
        pursuit_score -= 10
        creator_note = "Mega-creator driven — likely paid promo, not organic demand"
    elif creator_tier == "macro":
        pursuit_score -= 5
        creator_note = "Macro-creator driven — may be sponsored, verify organic interest"
    elif creator_tier in ("micro", "nano"):
        pursuit_score += 10
        creator_note = "Micro/nano-creator driven — strong organic signal"
    elif creator_tier == "mixed":
        pursuit_score += 5
        creator_note = "Mixed creator tiers — healthy organic spread"
    else:
        creator_note = "Creator tier unknown — cannot assess organic vs paid"

    # Hashtag purchase intent boost
    if hashtag_intent >= 0.5:
        pursuit_score += 10
        intent_note = "Strong purchase-intent hashtags (#TikTokMadeMeBuyIt, #MustHave)"
    elif hashtag_intent >= 0.2:
        pursuit_score += 5
        intent_note = "Some purchase intent in hashtags"
    else:
        intent_note = "Low purchase intent — may be entertainment-only virality"

    # Virality floor — need minimum engagement
    if virality < 20:
        pursuit_score -= 20
        virality_note = "Low virality — insufficient social proof"
    elif virality >= 70:
        pursuit_score += 5
        virality_note = "High virality — strong engagement metrics"
    else:
        virality_note = f"Moderate virality ({virality}/100)"

    pursuit_score = max(0, min(100, pursuit_score))

    if pursuit_score >= 70:
        verdict = "pursue"
        action = "Source product immediately — contact suppliers, validate margins"
    elif pursuit_score >= 40:
        verdict = "monitor"
        action = "Add to watchlist — check engagement trajectory in 24-48 hours"
    else:
        verdict = "skip"
        action = "Not a viable product opportunity at this time"

    return {
        "verdict": verdict,
        "pursuit_score": pursuit_score,
        "action": action,
        "factors": {
            "platform_spread": spread_note,
            "creator_tier": creator_note,
            "purchase_intent": intent_note,
            "virality": virality_note,
        },
    }


def assess_virality_sustainability(signals: dict[str, Any]) -> dict[str, Any]:
    """Is this a lasting trend or a short-lived fad?

    Signals used:
      - age_days: how long the trend has been active
      - growth_trajectory: accelerating, steady, decelerating
      - platform_spread: more platforms = more sustainable
      - content_type: educational/review vs pure entertainment
      - pinterest_present: Pinterest = search-driven = lasting
    """
    age_days = signals.get("age_days", 0)
    growth = signals.get("growth_trajectory", "unknown")
    spread = signals.get("platform_spread", 0)
    content = signals.get("content_type", "entertainment")
    on_pinterest = signals.get("pinterest_present", False)

    sustainability = 50  # baseline

    # Age assessment
    if age_days < 3:
        sustainability -= 15
        age_note = "Too early to assess — could spike and crash"
    elif 3 <= age_days <= 14:
        sustainability += 10
        age_note = "Active 3-14 days — in prime growth window"
    elif 14 < age_days <= 30:
        sustainability += 15
        age_note = "Sustained 2-4 weeks — strong staying power"
    else:
        sustainability += 5
        age_note = "30+ days — may be past peak growth, check velocity"

    # Growth trajectory
    if growth == "accelerating":
        sustainability += 15
        growth_note = "Accelerating growth — trend still building momentum"
    elif growth == "steady":
        sustainability += 10
        growth_note = "Steady growth — sustainable demand curve"
    elif growth == "decelerating":
        sustainability -= 10
        growth_note = "Decelerating — trend may be peaking"
    else:
        growth_note = "Growth trajectory unknown"

    # Platform spread
    if spread >= 3:
        sustainability += 15
        spread_note = "Multi-platform = deeper cultural penetration"
    elif spread == 2:
        sustainability += 5
        spread_note = "Two platforms — moderate staying power"
    else:
        sustainability -= 10
        spread_note = "Single platform — vulnerable to algorithm changes"

    # Content type
    if content in ("review", "educational", "tutorial"):
        sustainability += 10
        content_note = "Educational/review content = intent-driven, longer shelf life"
    elif content == "entertainment":
        sustainability -= 5
        content_note = "Entertainment content — virality may not convert to sales"
    else:
        content_note = "Mixed content types"

    # Pinterest presence is a strong sustainability signal
    if on_pinterest:
        sustainability += 10
        pinterest_note = "Present on Pinterest — search-driven demand, most durable"
    else:
        pinterest_note = "Not on Pinterest — no search-driven signal yet"

    sustainability = max(0, min(100, sustainability))

    if sustainability >= 70:
        outlook = "lasting_trend"
        window = "4-12 weeks of viable sales window"
    elif sustainability >= 45:
        outlook = "moderate_trend"
        window = "2-4 weeks — act quickly but trend may sustain"
    else:
        outlook = "likely_fad"
        window = "1-2 weeks max — only pursue if fast turnaround possible"

    return {
        "outlook": outlook,
        "sustainability_score": sustainability,
        "estimated_window": window,
        "factors": {
            "age": age_note,
            "growth": growth_note,
            "spread": spread_note,
            "content": content_note,
            "pinterest": pinterest_note,
        },
    }


def recommend_platform_strategy(platforms: dict[str, Any]) -> dict[str, Any]:
    """Which platform to focus marketing efforts on.

    Input: dict of platform names -> engagement data
    Returns: ranked platforms with strategy per platform.
    """
    platform_scores: list[dict[str, Any]] = []

    # TikTok
    tt = platforms.get("tiktok", {})
    tt_views = tt.get("views", 0)
    tt_shares = tt.get("shares", 0)
    tt_score = 0
    if tt_views > 0:
        tt_score = min(100, int(30 + (tt_views / 1_000_000) * 20 + (tt_shares / 10_000) * 20))
    platform_scores.append({
        "platform": "tiktok",
        "score": min(100, tt_score),
        "strategy": "Create short-form UGC-style content. Partner with micro-creators (10k-100k).",
        "best_for": "Rapid awareness and impulse purchases under $50",
        "timing": "Post 2-3x daily during trend window; peak hours 7-11pm",
    })

    # Instagram
    ig = platforms.get("instagram", {})
    ig_saves = ig.get("saves", 0)
    ig_shares = ig.get("shares", 0)
    ig_score = 0
    if ig_saves + ig_shares > 0:
        ig_score = min(100, int(25 + (ig_saves / 50_000) * 30 + (ig_shares / 20_000) * 20))
    platform_scores.append({
        "platform": "instagram",
        "score": min(100, ig_score),
        "strategy": "Reels for discovery, Stories for conversion. Use shoppable posts.",
        "best_for": "Mid-price lifestyle products ($20-$150), aesthetics-driven",
        "timing": "Reels 1x daily; Stories 3-5x daily with product links",
    })

    # Pinterest
    pt = platforms.get("pinterest", {})
    pt_repins = pt.get("repins", 0)
    pt_clicks = pt.get("clicks", 0)
    pt_score = 0
    if pt_repins + pt_clicks > 0:
        pt_score = min(100, int(20 + (pt_repins / 10_000) * 30 + (pt_clicks / 5_000) * 30))
    platform_scores.append({
        "platform": "pinterest",
        "score": min(100, pt_score),
        "strategy": "Create rich pins with direct product links. SEO-optimize pin descriptions.",
        "best_for": "Home decor, fashion, DIY, wedding — high-intent browsing",
        "timing": "Pin 5-10x daily; content has 3-6 month shelf life",
    })

    # YouTube
    yt = platforms.get("youtube", {})
    yt_views = yt.get("views", 0)
    yt_likes = yt.get("likes", 0)
    yt_score = 0
    if yt_views > 0:
        yt_score = min(100, int(20 + (yt_views / 500_000) * 30 + (yt_likes / 20_000) * 20))
    platform_scores.append({
        "platform": "youtube",
        "score": min(100, yt_score),
        "strategy": "Sponsor review videos and comparison content. Shorts for awareness.",
        "best_for": "High-ticket items ($50+), tech, detailed product comparisons",
        "timing": "Long-form 1-2x/week; Shorts 3-5x/week during trend window",
    })

    platform_scores.sort(key=lambda p: p["score"], reverse=True)
    primary = platform_scores[0] if platform_scores else None
    secondary = platform_scores[1] if len(platform_scores) > 1 else None

    return {
        "primary_platform": primary["platform"] if primary else "none",
        "platform_rankings": platform_scores,
        "strategy_summary": (
            f"Lead with {primary['platform']} ({primary['strategy'].split('.')[0]}), "
            f"support with {secondary['platform']}"
            if primary and secondary else "Insufficient data for platform recommendation"
        ),
    }
