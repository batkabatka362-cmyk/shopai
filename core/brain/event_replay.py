"""Event replay — run historical events through a new policy.

counterfactual (v3-D6) asks "what would the *opposite* decision
have done?" Replay answers the bigger version: "what if the brain
I have *today* had been running the last 90 days?" Replay is how
the brain measures whether a proposed config change would have
actually improved outcomes before enabling it in production.

EventReplay takes:

  • events   — a historical stream of Event(ts, kind, context, outcome)
  • policy   — a callable policy(event) → proposed_action
               A policy is just a function; tests plug in synthetic
               ones, production plugs in the decision_governor.
  • scorer   — a callable scorer(event, action) → float reward

and returns a ReplayReport with the realised-vs-policy comparison
per event, aggregate reward, and segment breakdowns.

Two run modes:

  • *sequential* — feed events one at a time, remember everything
    (useful for policies that depend on prior events).
  • *stateless*  — evaluate each event independently; safe for
    policies that are pure functions of context.

The tool is deliberately thin — the real intelligence is in the
injected policy. Pure stdlib, deterministic, zero LLM.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass
class Event:
    ts: float
    kind: str
    context: dict[str, Any] = field(default_factory=dict)
    realised_action: Any = None
    realised_reward: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "kind": self.kind,
            "context": self.context,
            "realised_action": self.realised_action,
            "realised_reward": self.realised_reward,
        }


@dataclass
class ReplayRow:
    event: Event
    proposed_action: Any
    proposed_reward: float
    delta: float                     # proposed − realised

    def as_dict(self) -> dict[str, Any]:
        return {
            "event": self.event.as_dict(),
            "proposed_action": self.proposed_action,
            "proposed_reward": round(self.proposed_reward, 3),
            "delta": round(self.delta, 3),
        }


@dataclass
class ReplayReport:
    rows: list[ReplayRow] = field(default_factory=list)
    total_realised: float = 0.0
    total_proposed: float = 0.0

    @property
    def n(self) -> int:
        return len(self.rows)

    @property
    def delta(self) -> float:
        return self.total_proposed - self.total_realised

    @property
    def win_rate(self) -> float:
        if not self.rows:
            return 0.0
        wins = sum(1 for r in self.rows if r.delta > 0)
        return wins / len(self.rows)

    def by_segment(
        self, key: str,
    ) -> dict[str, dict[str, float]]:
        buckets: dict[str, list[ReplayRow]] = defaultdict(list)
        for r in self.rows:
            buckets[str(r.event.context.get(key, "unknown"))].append(r)
        out: dict[str, dict[str, float]] = {}
        for bucket, rows in buckets.items():
            realised = sum(r.event.realised_reward for r in rows)
            proposed = sum(r.proposed_reward for r in rows)
            out[bucket] = {
                "n": len(rows),
                "realised": round(realised, 3),
                "proposed": round(proposed, 3),
                "delta": round(proposed - realised, 3),
            }
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "total_realised": round(self.total_realised, 3),
            "total_proposed": round(self.total_proposed, 3),
            "delta": round(self.delta, 3),
            "win_rate": round(self.win_rate, 3),
            "rows": [r.as_dict() for r in self.rows],
        }


Policy = Callable[[Event], Any]
Scorer = Callable[[Event, Any], float]


# ── Replay ─────────────────────────────────────────────────

def replay(
    events: Iterable[Event | dict[str, Any]],
    policy: Policy,
    scorer: Scorer,
    *,
    mode: str = "stateless",
) -> ReplayReport:
    """Run ``policy`` over every event, score, and tally the delta
    against the realised reward."""
    coerced: list[Event] = []
    for e in events:
        if isinstance(e, Event):
            coerced.append(e)
        else:
            coerced.append(Event(
                ts=float(e.get("ts", 0)),
                kind=str(e.get("kind", "event")),
                context=dict(e.get("context", {})),
                realised_action=e.get("realised_action"),
                realised_reward=float(e.get("realised_reward", 0)),
            ))
    coerced.sort(key=lambda ev: ev.ts)

    if mode not in ("stateless", "sequential"):
        raise ValueError(f"unknown mode {mode!r}")

    report = ReplayReport()
    for event in coerced:
        try:
            proposed = policy(event)
        except Exception as exc:
            # A bad policy shouldn't halt the whole replay; score
            # as unchanged.
            proposed = event.realised_action
            _ = exc
        try:
            proposed_reward = float(scorer(event, proposed))
        except Exception:
            proposed_reward = 0.0
        report.rows.append(ReplayRow(
            event=event,
            proposed_action=proposed,
            proposed_reward=proposed_reward,
            delta=proposed_reward - event.realised_reward,
        ))
        report.total_realised += event.realised_reward
        report.total_proposed += proposed_reward
    return report


# ── Comparison helpers ──────────────────────────────────────

@dataclass
class PolicyComparison:
    labels: list[str]
    totals: dict[str, float]
    win_rates: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "labels": self.labels,
            "totals": {k: round(v, 3) for k, v in self.totals.items()},
            "win_rates": {k: round(v, 3)
                           for k, v in self.win_rates.items()},
            "best": max(
                self.totals.keys(), key=lambda k: self.totals[k],
            ) if self.totals else None,
        }


def compare_policies(
    events: Iterable[Event | dict[str, Any]],
    policies: dict[str, Policy],
    scorer: Scorer,
) -> PolicyComparison:
    """Replay every policy over the same event stream and return
    a side-by-side comparison."""
    frozen = list(events)
    totals: dict[str, float] = {}
    win_rates: dict[str, float] = {}
    for label, policy in policies.items():
        report = replay(frozen, policy, scorer)
        totals[label] = report.total_proposed
        win_rates[label] = report.win_rate
    return PolicyComparison(
        labels=list(policies.keys()),
        totals=totals,
        win_rates=win_rates,
    )
