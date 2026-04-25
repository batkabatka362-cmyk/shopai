"""Counterfactual simulator — 'what if I had done X instead?'

regret_minimizer estimates regret from past decisions; but we never
simulate the *actual alternate history* forward. This module takes a
starting state, a candidate action sequence, and a transition model
(callable given state + action → next_state + observed reward), then
rolls the simulation forward under a random-seeded policy.

Two modes:

  • ``simulate(start, actions, transition, steps=N)``
      Deterministic roll-out of a fixed action list.

  • ``compare_alternatives(start, alternatives, transition, policy,
                             horizon=N, trials=T)``
      For each ``alternative`` (first action), roll out ``policy`` for
      ``horizon`` steps, ``trials`` times with different seeds,
      aggregate expected return + variance. Returns ranked list so the
      caller can pick the action with the best risk-adjusted value.

Pure stdlib. Deterministic given seeds.
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable


StateDict = dict[str, Any]
TransitionFn = Callable[[StateDict, str], tuple[StateDict, float]]
PolicyFn = Callable[[StateDict, random.Random], str | None]


@dataclass
class RolloutStep:
    action: str
    reward: float
    state_after: StateDict = field(default_factory=dict)


@dataclass
class Rollout:
    total_reward: float
    steps: list[RolloutStep] = field(default_factory=list)
    final_state: StateDict = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_reward": round(self.total_reward, 4),
            "n_steps": len(self.steps),
            "actions": [s.action for s in self.steps],
            "rewards": [round(s.reward, 4) for s in self.steps],
        }


@dataclass
class AlternativeReport:
    first_action: str
    mean_return: float
    stdev_return: float
    worst_case: float
    best_case: float
    n_trials: int
    horizon: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "first_action": self.first_action,
            "mean_return": round(self.mean_return, 4),
            "stdev_return": round(self.stdev_return, 4),
            "worst_case": round(self.worst_case, 4),
            "best_case": round(self.best_case, 4),
            "n_trials": self.n_trials,
            "horizon": self.horizon,
        }


def simulate(
    start: StateDict,
    actions: list[str],
    transition: TransitionFn,
    *,
    max_steps: int | None = None,
) -> Rollout:
    """Deterministic roll-out of a fixed action list."""
    state = dict(start)
    steps: list[RolloutStep] = []
    total_r = 0.0
    limit = len(actions) if max_steps is None else min(
        max_steps, len(actions),
    )
    for i in range(limit):
        act = actions[i]
        try:
            next_state, reward = transition(state, act)
        except Exception:
            break
        state = dict(next_state)
        total_r += float(reward)
        steps.append(RolloutStep(
            action=act, reward=float(reward),
            state_after=dict(state),
        ))
    return Rollout(
        total_reward=total_r, steps=steps,
        final_state=state,
    )


def _rollout_policy(
    start: StateDict,
    first_action: str,
    policy: PolicyFn,
    transition: TransitionFn,
    horizon: int,
    rng: random.Random,
) -> float:
    state = dict(start)
    # Step 1 — forced first action (the alternative under test)
    try:
        state, r = transition(state, first_action)
    except Exception:
        return 0.0
    total = float(r)
    # Subsequent steps follow the caller-supplied policy
    for _ in range(max(0, horizon - 1)):
        act = policy(state, rng)
        if act is None:
            break
        try:
            state, r = transition(state, act)
        except Exception:
            break
        total += float(r)
    return total


def compare_alternatives(
    start: StateDict,
    alternatives: list[str],
    transition: TransitionFn,
    policy: PolicyFn,
    *,
    horizon: int = 5,
    trials: int = 20,
    seed: int | None = None,
) -> list[AlternativeReport]:
    """For each alternative first action, Monte-Carlo roll-out the
    caller's policy and return ranked risk-adjusted reports."""
    if not alternatives:
        return []
    if horizon < 1:
        raise ValueError("horizon must be ≥ 1")
    if trials < 1:
        raise ValueError("trials must be ≥ 1")

    base_seed = seed if seed is not None else random.randint(0, 2**30)
    reports: list[AlternativeReport] = []

    for alt in alternatives:
        returns: list[float] = []
        for t in range(trials):
            rng = random.Random(base_seed + hash(alt) + t)
            returns.append(_rollout_policy(
                start, alt, policy, transition, horizon, rng,
            ))
        mean = sum(returns) / len(returns)
        sd = statistics.pstdev(returns) if len(returns) > 1 else 0.0
        reports.append(AlternativeReport(
            first_action=alt, mean_return=mean,
            stdev_return=sd,
            worst_case=min(returns), best_case=max(returns),
            n_trials=trials, horizon=horizon,
        ))
    reports.sort(key=lambda r: -r.mean_return)
    return reports


def risk_adjusted_best(
    reports: list[AlternativeReport],
    *,
    risk_aversion: float = 0.5,
) -> AlternativeReport | None:
    """Pick by mean − risk_aversion × stdev. High risk_aversion favours
    the stable option even if lower mean."""
    if not reports:
        return None
    return max(
        reports,
        key=lambda r: r.mean_return - risk_aversion * r.stdev_return,
    )
