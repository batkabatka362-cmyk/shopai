"""Tree-search planner — Monte Carlo Tree Search over action sequences.

The offline sandbox (v6-D5) runs *one* plan through a simulator.
The hierarchical planner (v4) decomposes *one* goal. Neither
searches the space of "which sequence of N actions over the next
30 days maximises expected ROAS?" — that's a planning problem.

MCTSPlanner runs a bounded-cost UCB1 tree search where:

  • State is a frozen tuple summarising the store's observable
    situation (cash_on_hand_band, open_launches, days_in_cycle).
  • Actions are drawn from the world model's action vocabulary.
  • Rollouts use a lightweight random policy + WorldModel's
    predicted outcome distribution for each (state, action) pair.
  • Reward is projected ROAS — net revenue / ad spend — folded
    across the rollout horizon.

Cost-aware: the search has a budget in simulations (default 200)
and time (default 2 seconds). Single-threaded; no LLM.

The planner returns the best-action-at-root plus a narrative
trace so the owner sees *why* it picked that move — which
branches it considered, what payoff each projected.

Design notes:

  • Classic UCB1: Q(s,a) + c·sqrt(ln N(s) / n(s,a)), default c=1.4.
  • Tree is a dict keyed by (state_key, depth) to keep memory bounded.
  • Rollout uses ``world_model().predict`` to sample outcomes —
    when uninformed, falls back to the epsilon-greedy curiosity
    policy's exploration mean.
  • Action mask blocks illegal moves (e.g. ``scale`` when no open
    launches, ``kill`` when none to kill).
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from core.brain.world_model import ACTIONS, Context, WorldModel, world_model
from utils.logger import get_logger


logger = get_logger("brain.tree_search")


@dataclass(frozen=True)
class State:
    cash_band: str = "mid"          # low | mid | high
    open_launches: int = 0
    days_elapsed: int = 0
    niche: str = "unknown"
    price_band: str = "mid"
    margin_band: str = "mid"
    copy_tone: str = "friendly"

    def as_context(self) -> Context:
        return Context(
            niche=self.niche,
            price_band=self.price_band,
            margin_band=self.margin_band,
            copy_tone=self.copy_tone,
        )

    def key(self) -> tuple:
        return (self.cash_band, self.open_launches,
                self.days_elapsed, self.niche,
                self.price_band, self.margin_band, self.copy_tone)


@dataclass
class Node:
    state_key: tuple
    visits: int = 0
    total_reward: float = 0.0
    children: dict[str, "Node"] = field(default_factory=dict)

    def mean(self) -> float:
        return self.total_reward / max(1, self.visits)


@dataclass
class PlanStep:
    action: str
    projected_reward: float
    confidence: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "projected_reward": round(self.projected_reward, 3),
            "confidence": round(self.confidence, 3),
        }


@dataclass
class PlanTrace:
    best_action: str
    expected_reward: float
    simulations: int
    depth: int
    branches: list[PlanStep] = field(default_factory=list)
    elapsed_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "best_action": self.best_action,
            "expected_reward": round(self.expected_reward, 3),
            "simulations": self.simulations,
            "depth": self.depth,
            "elapsed_s": round(self.elapsed_s, 3),
            "branches": [b.as_dict() for b in self.branches],
        }


# ── Action masking ──────────────────────────────────────────

def _legal_actions(state: State) -> list[str]:
    legal: list[str] = []
    for a in ACTIONS:
        if a == "scale" and state.open_launches == 0:
            continue
        if a == "kill" and state.open_launches == 0:
            continue
        if a == "launch" and state.cash_band == "low":
            continue
        legal.append(a)
    return legal or ["wait"]


def _apply_action(state: State, action: str) -> State:
    """Deterministic mock transition. World model handles the noisy
    reward; we just advance the state skeleton."""
    if action == "launch":
        return State(
            cash_band=state.cash_band,
            open_launches=state.open_launches + 1,
            days_elapsed=state.days_elapsed + 1,
            niche=state.niche, price_band=state.price_band,
            margin_band=state.margin_band, copy_tone=state.copy_tone,
        )
    if action == "kill":
        return State(
            cash_band=state.cash_band,
            open_launches=max(0, state.open_launches - 1),
            days_elapsed=state.days_elapsed + 1,
            niche=state.niche, price_band=state.price_band,
            margin_band=state.margin_band, copy_tone=state.copy_tone,
        )
    if action == "wait":
        return State(
            cash_band=state.cash_band,
            open_launches=state.open_launches,
            days_elapsed=state.days_elapsed + 3,
            niche=state.niche, price_band=state.price_band,
            margin_band=state.margin_band, copy_tone=state.copy_tone,
        )
    # scale / hold / add_cross_sell: +1 day, no structural change
    return State(
        cash_band=state.cash_band,
        open_launches=state.open_launches,
        days_elapsed=state.days_elapsed + 1,
        niche=state.niche, price_band=state.price_band,
        margin_band=state.margin_band, copy_tone=state.copy_tone,
    )


# ── Planner ─────────────────────────────────────────────────

class MCTSPlanner:
    def __init__(
        self,
        wm: WorldModel | None = None,
        c_ucb: float = 1.4,
        rollout_depth: int = 5,
        seed: int | None = None,
    ) -> None:
        self._wm = wm or world_model()
        self._c = c_ucb
        self._depth = rollout_depth
        self._rng = random.Random(seed)

    def plan(
        self,
        root: State,
        simulations: int = 200,
        time_budget_s: float = 2.0,
        reward_kpi: str = "roas",
    ) -> PlanTrace:
        root_node = Node(state_key=root.key())
        start = time.monotonic()
        sim_count = 0
        while sim_count < simulations:
            if time.monotonic() - start > time_budget_s:
                break
            self._run_simulation(root, root_node, reward_kpi)
            sim_count += 1

        branches: list[PlanStep] = []
        for action, child in root_node.children.items():
            branches.append(PlanStep(
                action=action,
                projected_reward=child.mean(),
                confidence=child.visits / max(1, root_node.visits),
            ))
        branches.sort(key=lambda b: -b.projected_reward)

        if not branches:
            # No children at all — fall back to a safe wait.
            return PlanTrace(
                best_action="wait",
                expected_reward=0.0,
                simulations=sim_count,
                depth=self._depth,
                branches=[],
                elapsed_s=time.monotonic() - start,
            )
        return PlanTrace(
            best_action=branches[0].action,
            expected_reward=branches[0].projected_reward,
            simulations=sim_count,
            depth=self._depth,
            branches=branches,
            elapsed_s=time.monotonic() - start,
        )

    # ── MCTS internals ──────────────────────────────────────

    def _run_simulation(
        self,
        state: State,
        node: Node,
        reward_kpi: str,
        depth: int = 0,
    ) -> float:
        if depth >= self._depth:
            return 0.0
        legal = _legal_actions(state)
        # Expansion — add any missing children
        for a in legal:
            if a not in node.children:
                node.children[a] = Node(
                    state_key=_apply_action(state, a).key(),
                )
        # Selection via UCB1 — prefer unvisited, then highest UCB
        action = self._select(node, legal)
        child = node.children[action]
        # Reward from world model (one-step look-ahead)
        pred = self._wm.predict(state.as_context(), action, reward_kpi)
        immediate = pred.mean if pred.samples >= 2 else self._bootstrap(action)
        # Recurse into child for longer-horizon value
        next_state = _apply_action(state, action)
        future = self._run_simulation(next_state, child, reward_kpi,
                                      depth + 1)
        # Total — discounted future
        reward = immediate + 0.7 * future
        # Back-prop
        node.visits += 1
        node.total_reward += reward
        child.visits += 1
        child.total_reward += reward
        return reward

    def _select(self, node: Node, legal: list[str]) -> str:
        # Unvisited first for exploration completeness.
        for a in legal:
            if node.children[a].visits == 0:
                return a
        # Otherwise UCB1 over visited.
        ln_parent = math.log(max(1, node.visits))
        best_a, best_ucb = legal[0], -float("inf")
        for a in legal:
            child = node.children[a]
            if child.visits == 0:
                return a
            exploit = child.mean()
            explore = self._c * math.sqrt(ln_parent / child.visits)
            ucb = exploit + explore
            if ucb > best_ucb:
                best_ucb, best_a = ucb, a
        return best_a

    def _bootstrap(self, action: str) -> float:
        """When WM has no prior, fall back to an optimistic default so
        the tree still explores."""
        # Slight bias toward active actions over ``wait``.
        if action == "wait":
            return 0.1
        return 0.5 + self._rng.random() * 0.3
