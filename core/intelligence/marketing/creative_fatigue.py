"""Creative fatigue detection — ads lose 30-40% effectiveness after 2-3 weeks."""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_float, safe_int


def _fatigue_action(signals: int, days: int) -> str:
    if signals >= 3:
        return "URGENT: Pause and refresh creative immediately"
    if signals >= 2:
        return "Rotate creative within 48 hours"
    if days > 14:
        return "Schedule creative refresh this week"
    return "Healthy — monitor weekly"


def detect_creative_fatigue(campaigns: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect ad creative fatigue — ads lose 30-40% effectiveness after 2-3 weeks.

    Signals:
      - CTR declining over time
      - CPA increasing
      - Frequency > 3 (same person seeing ad 3+ times)
    """
    fatigued = []
    healthy = []

    for campaign in campaigns:
        if not isinstance(campaign, dict):
            continue

        name = campaign.get("name", campaign.get("id", "unknown"))
        days_running = safe_int(campaign.get("days_running", 0))
        ctr = safe_float(campaign.get("ctr", 0))
        ctr_7d_ago = safe_float(campaign.get("ctr_7d_ago", ctr))
        frequency = safe_float(campaign.get("frequency", 1))
        cpa = safe_float(campaign.get("cpa", 0))
        cpa_7d_ago = safe_float(campaign.get("cpa_7d_ago", cpa))

        fatigue_signals = 0
        reasons = []

        # CTR declining
        if ctr_7d_ago > 0 and ctr < ctr_7d_ago * 0.8:
            fatigue_signals += 1
            reasons.append(f"CTR dropped {round((1 - ctr/ctr_7d_ago) * 100)}% in 7 days")

        # High frequency
        if frequency > 3:
            fatigue_signals += 1
            reasons.append(f"Frequency {frequency:.1f} — audience seeing ad too often")

        # CPA increasing
        if cpa_7d_ago > 0 and cpa > cpa_7d_ago * 1.3:
            fatigue_signals += 1
            reasons.append(f"CPA increased {round((cpa/cpa_7d_ago - 1) * 100)}%")

        # Running too long without refresh
        if days_running > 21:
            fatigue_signals += 1
            reasons.append(f"Running {days_running} days without creative refresh")

        is_fatigued = fatigue_signals >= 2

        entry = {
            "campaign": name,
            "days_running": days_running,
            "fatigue_signals": fatigue_signals,
            "is_fatigued": is_fatigued,
            "reasons": reasons,
            "action": _fatigue_action(fatigue_signals, days_running),
        }

        if is_fatigued:
            fatigued.append(entry)
        else:
            healthy.append(entry)

    return {
        "fatigued_campaigns": len(fatigued),
        "healthy_campaigns": len(healthy),
        "details": fatigued + healthy,
        "estimated_waste": f"{len(fatigued) * 35}% budget waste on fatigued creatives" if fatigued else "No waste detected",
    }
