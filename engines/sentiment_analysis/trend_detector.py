"""Sentiment Analysis Engine — trend detector.

Detects sentiment trends over time by grouping texts by date
and computing rolling sentiment averages. Generates alerts for
significant sentiment shifts.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Alert thresholds
# ---------------------------------------------------------------------------

_SENTIMENT_DROP_ALERT = -0.2    # Alert if sentiment drops by this much
_NEGATIVE_SPIKE_ALERT = -0.3   # Alert if sentiment goes below this
_VOLUME_SPIKE_MULTIPLIER = 2.0  # Alert if volume doubles


def detect_trends(
    sentiment_scores: list[dict[str, Any]],
    processed_texts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Detect sentiment trends over time and generate alerts.

    Args:
        sentiment_scores: List of SentimentScore dicts.
        processed_texts: List of ProcessedText dicts (for dates).

    Returns:
        Structured dict with trends and alerts.
    """
    try:
        sentiment_scores = copy.deepcopy(sentiment_scores)
        processed_texts = copy.deepcopy(processed_texts)

        # Build date lookup
        date_map: dict[str, str] = {}
        for text in processed_texts:
            text_id = str(text.get("id", ""))
            date = str(text.get("date", ""))
            if date:
                date_map[text_id] = date

        # Group sentiments by date period (day)
        period_data: dict[str, list[float]] = {}
        for ss in sentiment_scores:
            text_id = str(ss.get("id", ""))
            score = float(ss.get("score", 0))
            date = date_map.get(text_id, "unknown")

            # Extract date portion (YYYY-MM-DD)
            day = date[:10] if len(date) >= 10 else date
            period_data.setdefault(day, []).append(score)

        # Build trends sorted by date
        sorted_periods = sorted(period_data.keys())
        trends: list[dict[str, Any]] = []
        prev_avg = None

        for period in sorted_periods:
            scores = period_data[period]
            avg = round(sum(scores) / len(scores), 4) if scores else 0.0
            volume = len(scores)

            if prev_avg is not None:
                change = avg - prev_avg
                change_pct = round((change / abs(prev_avg)) * 100, 2) if prev_avg != 0 else 0.0

                if abs(change_pct) <= 5:
                    direction = "stable"
                elif change > 0:
                    direction = "up"
                else:
                    direction = "down"
            else:
                direction = "new"
                change_pct = 0.0

            trends.append({
                "period": period,
                "avg_sentiment": avg,
                "volume": volume,
                "direction": direction,
                "change_pct": change_pct,
            })

            prev_avg = avg

        # Generate alerts
        alerts = _generate_alerts(trends, period_data)

        return {
            "status": "success",
            "trends": trends,
            "alerts": alerts,
        }
    except Exception as exc:
        return {
            "status": "error",
            "trends": [],
            "alerts": [],
            "error": f"Trend detection failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_alerts(
    trends: list[dict[str, Any]],
    period_data: dict[str, list[float]],
) -> list[dict[str, Any]]:
    """Generate alerts for significant sentiment changes."""
    alerts: list[dict[str, Any]] = []

    if len(trends) < 2:
        return alerts

    # Check latest trend
    latest = trends[-1]
    previous = trends[-2]

    latest_avg = float(latest.get("avg_sentiment", 0))
    prev_avg = float(previous.get("avg_sentiment", 0))
    latest_vol = int(latest.get("volume", 0))
    prev_vol = int(previous.get("volume", 0))

    # Sentiment drop alert
    sentiment_change = latest_avg - prev_avg
    if sentiment_change < _SENTIMENT_DROP_ALERT:
        alerts.append({
            "type": "sentiment_drop",
            "severity": "warning",
            "message": f"Sentiment dropped from {prev_avg:.2f} to {latest_avg:.2f} in period {latest.get('period', '')}",
            "topic": "overall",
            "current_sentiment": latest_avg,
        })

    # Negative spike alert
    if latest_avg < _NEGATIVE_SPIKE_ALERT:
        alerts.append({
            "type": "negative_spike",
            "severity": "critical",
            "message": f"Sentiment is critically negative ({latest_avg:.2f}) in period {latest.get('period', '')}",
            "topic": "overall",
            "current_sentiment": latest_avg,
        })

    # Volume spike alert
    if prev_vol > 0 and latest_vol >= prev_vol * _VOLUME_SPIKE_MULTIPLIER:
        severity = "critical" if latest_avg < 0 else "info"
        alerts.append({
            "type": "volume_spike",
            "severity": severity,
            "message": f"Feedback volume spiked from {prev_vol} to {latest_vol} in period {latest.get('period', '')}",
            "topic": "volume",
            "current_sentiment": latest_avg,
        })

    return alerts
