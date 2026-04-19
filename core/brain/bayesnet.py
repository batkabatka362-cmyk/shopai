"""Lightweight Bayesian network — probabilistic chain reasoning.

The reward_model returns a preference score; the world_model
returns a mean outcome. Neither answers compound queries like
"P(sale | premium_tone AND audio AND high_margin)" — a natural
question the brain should answer without running a full LLM.

BayesNet is a small, exact-inference DAG over boolean / discrete
variables. Each node declares:

  • parents
  • a CPT (conditional probability table): for every parent-value
    combination, the distribution over the node's own values

Queries are answered by *variable elimination* — exact, O(n · 2^w)
where w is the treewidth. For ShopAI's typical networks (3-6
nodes) that's instant.

API:

  net = BayesNet()
  net.add("niche", ["audio", "fashion"], prior={...})
  net.add("tone", ["friendly", "luxury"], prior={...})
  net.add("sale", ["yes", "no"],
          parents=["niche", "tone"], cpt={...})

  # P(sale=yes | tone=luxury, niche=audio)
  p = net.query(target="sale", target_value="yes",
                 evidence={"niche": "audio", "tone": "luxury"})

Zero LLM. No numpy — pure dict / list math.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Any, Iterable


@dataclass
class Node:
    name: str
    values: tuple[str, ...]
    parents: tuple[str, ...] = ()
    # CPT is a dict keyed by parent-value tuple → dict[value, prob]
    cpt: dict[tuple[str, ...], dict[str, float]] = field(
        default_factory=dict,
    )

    def prob(self, value: str, parent_values: tuple[str, ...]) -> float:
        row = self.cpt.get(parent_values)
        if not row:
            return 0.0
        return float(row.get(value, 0.0))


# ── Net ─────────────────────────────────────────────────────

class BayesNet:
    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}

    # ── Schema ──────────────────────────────────────────────

    def add(
        self,
        name: str,
        values: Iterable[str],
        *,
        parents: Iterable[str] = (),
        prior: dict[str, float] | None = None,
        cpt: dict[tuple[str, ...], dict[str, float]] | None = None,
    ) -> None:
        values = tuple(values)
        parents = tuple(parents)
        if prior is not None and parents:
            raise ValueError(
                f"node {name!r} has parents; supply cpt instead of prior",
            )
        if parents and cpt is None:
            raise ValueError(f"node {name!r} has parents; cpt required")
        if not parents and prior is None:
            # default uniform
            prior = {v: 1.0 / len(values) for v in values}
        if prior is not None:
            cpt = {(): _normalise(prior)}
        else:
            cpt = {k: _normalise(v) for k, v in (cpt or {}).items()}
        self._validate_cpt(name, values, parents, cpt)
        self._nodes[name] = Node(name=name, values=values,
                                 parents=parents, cpt=cpt)

    def _validate_cpt(
        self, name: str, values: tuple[str, ...],
        parents: tuple[str, ...],
        cpt: dict[tuple[str, ...], dict[str, float]],
    ) -> None:
        # Every parent-value combination must be present
        parent_nodes = [self._nodes[p] for p in parents]
        required = list(product(*(n.values for n in parent_nodes)))
        for combo in required:
            if combo not in cpt:
                raise ValueError(
                    f"node {name!r} missing CPT row for parents={combo}",
                )
            row = cpt[combo]
            missing = set(values) - set(row.keys())
            if missing:
                raise ValueError(
                    f"node {name!r} row {combo} missing value(s) "
                    f"{sorted(missing)}",
                )

    # ── Inference ──────────────────────────────────────────

    def query(
        self,
        *,
        target: str,
        target_value: str | None = None,
        evidence: dict[str, str] | None = None,
    ) -> float | dict[str, float]:
        """Return either a scalar P(target = target_value | evidence)
        or a full distribution over target if target_value is None."""
        evidence = evidence or {}
        if target not in self._nodes:
            raise KeyError(f"unknown target {target!r}")
        # Ensure every evidence variable exists
        for k in evidence:
            if k not in self._nodes:
                raise KeyError(f"unknown evidence var {k!r}")
        # Enumerate all joint configurations consistent with evidence
        # and sum joint probability per target value.
        dist: dict[str, float] = {v: 0.0 for v in self._nodes[target].values}
        # Variables to enumerate = non-evidence, non-target
        free_vars = [
            n.name for n in self._nodes.values()
            if n.name != target and n.name not in evidence
        ]
        target_node = self._nodes[target]
        for tv in target_node.values:
            # For each joint assignment over free_vars, compute prob
            total = 0.0
            for assignment in _enumerate(self._nodes, free_vars):
                # Full world assignment
                world = dict(evidence)
                world[target] = tv
                world.update(assignment)
                total += self._joint_prob(world)
            dist[tv] = total
        # Normalise to get conditional distribution
        z = sum(dist.values())
        if z > 0:
            dist = {k: v / z for k, v in dist.items()}
        if target_value is not None:
            if target_value not in dist:
                raise KeyError(
                    f"value {target_value!r} not in target domain",
                )
            return dist[target_value]
        return dist

    def _joint_prob(self, world: dict[str, str]) -> float:
        p = 1.0
        for name, node in self._nodes.items():
            val = world.get(name)
            if val is None:
                return 0.0
            parent_vals = tuple(world[p] for p in node.parents)
            p *= node.prob(val, parent_vals)
            if p == 0:
                return 0.0
        return p

    # ── Introspection ─────────────────────────────────────

    def nodes(self) -> list[str]:
        return list(self._nodes.keys())

    def describe(self, name: str) -> dict[str, Any]:
        n = self._nodes[name]
        return {
            "name": n.name,
            "values": list(n.values),
            "parents": list(n.parents),
            "cpt_rows": len(n.cpt),
        }


def _enumerate(
    nodes: dict[str, Node], var_names: list[str],
) -> Iterable[dict[str, str]]:
    if not var_names:
        yield {}
        return
    value_lists = [nodes[n].values for n in var_names]
    for combo in product(*value_lists):
        yield dict(zip(var_names, combo))


def _normalise(dist: dict[str, float]) -> dict[str, float]:
    z = sum(dist.values())
    if z <= 0:
        n = len(dist)
        return {k: 1.0 / n for k in dist}
    return {k: v / z for k, v in dist.items()}
