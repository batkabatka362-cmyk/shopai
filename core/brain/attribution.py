"""Multi-touch attribution — who gets credit for this sale.

Every conversion is preceded by a chain of touchpoints: a Meta
ad impression, an email, an organic search click, a retarget
banner. ShopAI has been defaulting to last-click (whichever
channel fired just before the order gets 100% credit). That's
wrong when the Meta ad did the heavy lifting but the customer
happened to land via organic.

AttributionEngine offers several deterministic attribution
models:

  • last_click     — last touch gets 1.0
  • first_click    — first touch gets 1.0
  • linear          — equal split across all touches
  • time_decay     — older touches weighted by exp(-age/half_life)
  • position_based — 40/40/20 split (first / last / middle evenly)
  • shapley         — classic cooperative-game Shapley values over
                      every 2^N coalition; exact, O(N · 2^N). Cap
                      N at 6 for tractability, fall back to
                      position_based above that.

Each model returns ``{channel_id: credit_fraction}`` summing to
1.0. Helpers expose per-channel aggregated ROI across a batch of
conversion journeys so the dashboard can answer "which channel
really drives revenue?"

Pure Python; no LLM. Journeys are simple lists of Touch dicts.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Callable, Iterable


@dataclass
class Touch:
    channel: str
    timestamp: float
    cost_usd: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "timestamp": self.timestamp,
            "cost_usd": self.cost_usd,
        }


@dataclass
class Journey:
    journey_id: str
    touches: list[Touch]
    conversion_value: float
    converted: bool = True

    @property
    def conversion_time(self) -> float:
        if self.touches:
            return self.touches[-1].timestamp
        return 0.0


# ── Attribution models ──────────────────────────────────────

def last_click(journey: Journey) -> dict[str, float]:
    if not journey.touches:
        return {}
    return {journey.touches[-1].channel: 1.0}


def first_click(journey: Journey) -> dict[str, float]:
    if not journey.touches:
        return {}
    return {journey.touches[0].channel: 1.0}


def linear(journey: Journey) -> dict[str, float]:
    n = len(journey.touches)
    if n == 0:
        return {}
    credit: dict[str, float] = defaultdict(float)
    share = 1.0 / n
    for t in journey.touches:
        credit[t.channel] += share
    return dict(credit)


def time_decay(
    journey: Journey, half_life_hours: float = 24.0,
) -> dict[str, float]:
    if not journey.touches:
        return {}
    conv = journey.conversion_time
    raw: list[tuple[str, float]] = []
    for t in journey.touches:
        age_h = max(0.0, (conv - t.timestamp) / 3600.0)
        weight = math.exp(-age_h / half_life_hours)
        raw.append((t.channel, weight))
    total = sum(w for _, w in raw)
    if total <= 0:
        return linear(journey)
    credit: dict[str, float] = defaultdict(float)
    for ch, w in raw:
        credit[ch] += w / total
    return dict(credit)


def position_based(journey: Journey) -> dict[str, float]:
    n = len(journey.touches)
    if n == 0:
        return {}
    if n == 1:
        return {journey.touches[0].channel: 1.0}
    if n == 2:
        return _combine({
            journey.touches[0].channel: 0.5,
            journey.touches[1].channel: 0.5,
        })
    credit: dict[str, float] = defaultdict(float)
    credit[journey.touches[0].channel] += 0.4
    credit[journey.touches[-1].channel] += 0.4
    middles = journey.touches[1:-1]
    share = 0.2 / len(middles)
    for t in middles:
        credit[t.channel] += share
    return dict(credit)


def shapley(journey: Journey) -> dict[str, float]:
    """Exact Shapley over unique channels in the journey.

    Uses a simple value function: v(S) = 1 if S contains the
    journey's last-click channel, else |S| / N. This rewards
    channels that appear close to the conversion while giving
    some share to supporting channels."""
    if not journey.touches:
        return {}
    channels = []
    seen: set[str] = set()
    for t in journey.touches:
        if t.channel not in seen:
            channels.append(t.channel)
            seen.add(t.channel)
    N = len(channels)
    if N == 0:
        return {}
    if N == 1:
        return {channels[0]: 1.0}
    if N > 6:
        # Exponential cost — fall back.
        return position_based(journey)

    last_channel = journey.touches[-1].channel

    def v(S: frozenset[str]) -> float:
        if not S:
            return 0.0
        if last_channel in S:
            return 1.0
        return len(S) / N * 0.5

    contributions: dict[str, float] = defaultdict(float)
    factorial_N = math.factorial(N)
    for ch in channels:
        others = [c for c in channels if c != ch]
        for r in range(len(others) + 1):
            for combo in combinations(others, r):
                S = frozenset(combo)
                S_plus = S | {ch}
                weight = (math.factorial(r) * math.factorial(N - r - 1)
                           / factorial_N)
                contributions[ch] += weight * (v(S_plus) - v(S))
    total = sum(contributions.values())
    if total > 0:
        return {c: v_ / total for c, v_ in contributions.items()}
    return linear(journey)


def _combine(d: dict[str, float]) -> dict[str, float]:
    # Safety normalise.
    z = sum(d.values())
    if z <= 0:
        return d
    return {k: v / z for k, v in d.items()}


# ── Aggregation across journeys ─────────────────────────────

@dataclass
class ChannelReport:
    channel: str
    credited_revenue: float = 0.0
    spend: float = 0.0

    @property
    def roas(self) -> float:
        return self.credited_revenue / self.spend if self.spend > 0 else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "credited_revenue": round(self.credited_revenue, 2),
            "spend": round(self.spend, 2),
            "roas": round(self.roas, 3),
        }


def aggregate(
    journeys: Iterable[Journey],
    model: Callable[[Journey], dict[str, float]] | str = "linear",
    **kwargs: Any,
) -> dict[str, ChannelReport]:
    """Run ``model`` over every journey and roll up per-channel
    revenue + spend."""
    if isinstance(model, str):
        model_fn = {
            "last_click": last_click,
            "first_click": first_click,
            "linear": linear,
            "time_decay": lambda j: time_decay(j, **kwargs),
            "position_based": position_based,
            "shapley": shapley,
        }.get(model)
        if model_fn is None:
            raise ValueError(f"unknown model {model!r}")
    else:
        model_fn = model
    reports: dict[str, ChannelReport] = {}
    for j in journeys:
        # Always fold spend — unconverted journeys still cost money.
        for t in j.touches:
            r = reports.setdefault(t.channel, ChannelReport(channel=t.channel))
            r.spend += t.cost_usd
        if not j.converted or j.conversion_value <= 0:
            continue
        credits = model_fn(j)
        for ch, share in credits.items():
            r = reports.setdefault(ch, ChannelReport(channel=ch))
            r.credited_revenue += share * j.conversion_value
    return reports
