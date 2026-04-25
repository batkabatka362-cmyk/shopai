"""Offline simulation playground.

v3-D3's Monte-Carlo simulator projects a single intervention from
bootstrap samples. The planner (v3-D7 / v4-D1) produces action
DAGs but has no way to *execute* them against a synthetic world
to validate the plan before committing real money.

SimWorld is a deterministic in-memory market model. Every plan
action has a ``dry_run(world)`` that mutates synthetic state:
simulated sales, simulated spend, simulated inventory. After
running, the world exposes ``summary()`` with projected KPIs.

Key properties:

  • Stateless with respect to the real DB — no writes.
  • Deterministic given a seed, so tests reproduce.
  • Composes with plan.synthesize: ``SimWorld.run(plan)``
    walks every action node in topological order.
  • Returns a ``SimReport`` with projected revenue, cost, ROAS,
    killed/scaled launches, and per-step expected value.

Used by the planner's *proposal* phase before we promote it to
the action executor.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SimLaunch:
    launch_id: str
    niche: str = "default"
    daily_budget: float = 20.0
    roas: float = 2.0
    cvr: float = 0.02
    aov: float = 30.0
    days_live: float = 0.0
    status: str = "active"              # active | killed | scaled

    def step_one_day(self, rng: random.Random) -> tuple[float, float]:
        """One day tick. Returns (spend, revenue)."""
        if self.status != "active":
            return 0.0, 0.0
        # Add ±10 % noise around roas to keep sims lively
        drift = rng.gauss(1.0, 0.1)
        spend = self.daily_budget
        revenue = spend * self.roas * drift
        self.days_live += 1.0
        return spend, max(0.0, revenue)


@dataclass
class SimReport:
    projected_revenue: float
    projected_spend: float
    projected_roas: float
    active_at_end: int
    killed_during: int
    scaled_during: int
    per_step: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "projected_revenue": round(self.projected_revenue, 2),
            "projected_spend":   round(self.projected_spend, 2),
            "projected_roas":    round(self.projected_roas, 2),
            "active_at_end":     self.active_at_end,
            "killed_during":     self.killed_during,
            "scaled_during":     self.scaled_during,
            "steps":             len(self.per_step),
        }


class SimWorld:
    """Deterministic synthetic market. Not a game engine — the
    simplest thing that lets us A/B whole plans."""

    def __init__(self, seed: int = 7) -> None:
        self._rng = random.Random(seed)
        self.launches: dict[str, SimLaunch] = {}
        self.killed: list[str] = []
        self.scaled: list[str] = []
        self.ticks = 0
        self.step_log: list[dict[str, Any]] = []

    # ── World seed ──────────────────────────────────────────

    def seed_launch(
        self, launch_id: str,
        niche: str = "default",
        daily_budget: float = 20.0,
        roas: float = 2.0,
    ) -> SimLaunch:
        launch = SimLaunch(
            launch_id=launch_id, niche=niche,
            daily_budget=daily_budget, roas=roas,
        )
        self.launches[launch_id] = launch
        return launch

    # ── Plan execution ──────────────────────────────────────

    def apply_action(self, node: dict[str, Any]) -> dict[str, Any]:
        """Apply a single plan ActionNode-shaped dict. The planner
        already wraps per-kind params; we just read them."""
        params = node.get("params") or {}
        kind = params.get("kind") or node.get("kind") or ""
        entry = {"node_id": node.get("id"), "kind": kind,
                 "effects": []}
        if kind == "launch_product":
            lid = f"sim_{len(self.launches) + 1}"
            launch = self.seed_launch(
                lid,
                niche=params.get("niche", "default"),
                daily_budget=float(params.get("ad_budget_day", 20.0)),
                roas=float(params.get("seed_roas", 2.0)),
            )
            entry["effects"].append(
                f"seeded launch {lid} niche={launch.niche} "
                f"budget={launch.daily_budget}"
            )
        elif kind == "scale_launch":
            lid = params.get("launch_id") or ""
            factor = float(params.get("scale_factor", 2.0))
            launch = self.launches.get(lid)
            if launch and launch.status == "active":
                launch.daily_budget *= factor
                launch.status = "scaled"
                self.scaled.append(lid)
                entry["effects"].append(
                    f"scaled {lid} budget × {factor}"
                )
        elif kind == "kill_launch":
            lid = params.get("launch_id") or ""
            launch = self.launches.get(lid)
            if launch and launch.status != "killed":
                launch.status = "killed"
                self.killed.append(lid)
                entry["effects"].append(f"killed {lid}")
        elif kind == "simulate":
            # simulate is a plan-level annotation; nothing to mutate.
            entry["effects"].append("dry-run pricing signal observed")
        elif kind == "wait":
            days = int(params.get("days", 1))
            self.tick(days)
            entry["effects"].append(f"ticked {days} day(s)")
        elif kind == "add_cross_sell":
            # Crude uplift model: every active launch's AOV × 1.07
            for launch in self.launches.values():
                if launch.status != "killed":
                    launch.aov *= 1.07
            entry["effects"].append("cross-sell applied (+7% AOV)")
        elif kind == "run_reasoning":
            entry["effects"].append("reasoner ran (sandbox no-op)")
        else:
            entry["effects"].append(f"unrecognised kind {kind!r}")
        self.step_log.append(entry)
        return entry

    def run_plan(self, nodes: list[dict[str, Any]]) -> SimReport:
        """Walk nodes in the order given. Assumes topological order
        already — the planner builds DAGs that way."""
        for n in nodes:
            self.apply_action(n)
        # If the plan never explicitly waited, tick a default horizon
        # so launch effects materialise.
        if self.ticks == 0:
            self.tick(3)
        return self.report()

    # ── Core mechanics ──────────────────────────────────────

    def tick(self, days: int = 1) -> None:
        for _ in range(max(0, int(days))):
            self.ticks += 1
            # All still-active launches earn
            for launch in self.launches.values():
                if launch.status in ("active", "scaled"):
                    spend, revenue = launch.step_one_day(self._rng)
                    # Aggregate — but attribute to last-step log if any
                    if self.step_log:
                        last = self.step_log[-1]
                        last.setdefault("spend", 0.0)
                        last.setdefault("revenue", 0.0)
                        last["spend"] += spend
                        last["revenue"] += revenue

    def report(self) -> SimReport:
        total_rev = 0.0
        total_spend = 0.0
        for entry in self.step_log:
            total_rev += entry.get("revenue", 0.0)
            total_spend += entry.get("spend", 0.0)
        roas = total_rev / total_spend if total_spend > 0 else 0.0
        active = sum(
            1 for l in self.launches.values()
            if l.status in ("active", "scaled")
        )
        return SimReport(
            projected_revenue=total_rev,
            projected_spend=total_spend,
            projected_roas=roas,
            active_at_end=active,
            killed_during=len(self.killed),
            scaled_during=len(self.scaled),
            per_step=list(self.step_log),
        )


# ── Convenience ─────────────────────────────────────────────

def simulate_plan(plan_dict: dict[str, Any], seed: int = 7) -> SimReport:
    """Take a plan.as_dict() payload and return a SimReport."""
    nodes = plan_dict.get("nodes") or []
    return SimWorld(seed=seed).run_plan(nodes)
