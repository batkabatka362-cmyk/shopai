"""Causal discovery — extract X → Y edges from observational data.

The brain already has ``causal_inference.py`` and ``counterfactual``
but both *assume* a causal graph exists. Causal discovery goes the
other way: from raw observational rows, propose which variables
actually cause which.

Exact PC-algorithm with partial correlations is heavy — we use a
lightweight variant good enough for ShopAI's small variable sets:

  1. Build a correlation matrix over all observed variables.
  2. Any pair with |correlation| < ε is deemed independent.
  3. For every dependent pair (X, Y), test for a *conditioning set*
     Z (all other variables) under which they become conditionally
     independent. If such Z exists, (X, Y) is an *indirect* edge.
  4. Remaining pairs (directly dependent) form the skeleton.
  5. Temporal ordering breaks ties: if X is always observed before
     Y, orient edge X → Y.

Output: ``CausalGraph`` with directed + undirected edges, plus a
``narrative`` for the owner digest. Pure stdlib; no numpy.

This is *proposal*, not proof — the brain still runs hypotheses
(v7-D2) to confirm. But the discovery layer dramatically shrinks
the hypothesis search space.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Iterable


_EPS_INDEPENDENCE = 0.15          # |r| below → treat as independent
_EPS_CONDITIONAL = 0.30            # partial correlation threshold (generous
                                    # to handle 0/0 instability when a
                                    # confounder fully explains the link)


@dataclass
class Edge:
    source: str
    target: str
    directed: bool                  # False = undirected
    strength: float                 # |correlation|, 0..1
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "directed": self.directed,
            "strength": round(self.strength, 3),
            "rationale": self.rationale,
        }


@dataclass
class CausalGraph:
    variables: list[str]
    edges: list[Edge] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "variables": self.variables,
            "edges": [e.as_dict() for e in self.edges],
        }

    @property
    def directed_edges(self) -> list[Edge]:
        return [e for e in self.edges if e.directed]

    def parents_of(self, var: str) -> list[str]:
        return [e.source for e in self.edges
                 if e.directed and e.target == var]


# ── Statistical helpers ─────────────────────────────────────

def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def correlation(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation. Returns 0 for degenerate inputs."""
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    den = math.sqrt(vx * vy)
    if den <= 0:
        return 0.0
    return num / den


def partial_correlation(
    xs: list[float], ys: list[float], zs: list[list[float]],
) -> float:
    """Partial correlation of (xs, ys) given conditioning list zs.

    For small conditioning sets we use the recursive formula —
    partial correlation of X, Y given {Z1, ..., Zk} is defined
    recursively via:

        r(X, Y | Z) = (r(X, Y) − r(X, Z) r(Y, Z)) /
                       sqrt((1 − r(X, Z)^2)(1 − r(Y, Z)^2))
    """
    if not zs:
        return correlation(xs, ys)
    z = zs[0]
    rest = zs[1:]
    r_xy = partial_correlation(xs, ys, rest)
    r_xz = partial_correlation(xs, z, rest)
    r_yz = partial_correlation(ys, z, rest)
    denom = math.sqrt(max(0.0, (1 - r_xz ** 2) * (1 - r_yz ** 2)))
    if denom <= 0:
        return 0.0
    return (r_xy - r_xz * r_yz) / denom


# ── Discovery ───────────────────────────────────────────────

def discover(
    samples: Iterable[dict[str, float]],
    *,
    temporal_order: dict[str, int] | None = None,
    eps_independence: float = _EPS_INDEPENDENCE,
    eps_conditional: float = _EPS_CONDITIONAL,
) -> CausalGraph:
    """Build a causal skeleton from observational samples.

    Each sample is a dict of {variable: numeric_value}. Missing
    variables are skipped for that row.

    ``temporal_order`` maps variable → rank so ``rank(X) < rank(Y)``
    lets edges be oriented X → Y. Without this, remaining edges
    stay undirected.
    """
    samples = list(samples)
    if not samples:
        return CausalGraph(variables=[])

    # Collect all variables
    all_vars: set[str] = set()
    for row in samples:
        all_vars.update(row.keys())
    variables = sorted(all_vars)
    if len(variables) < 2:
        return CausalGraph(variables=variables)

    # Build column vectors, dropping rows missing any variable so the
    # correlation estimates stay on common rows.
    columns: dict[str, list[float]] = {v: [] for v in variables}
    for row in samples:
        if any(v not in row for v in variables):
            continue
        for v in variables:
            columns[v].append(float(row[v]))
    if any(len(c) < 2 for c in columns.values()):
        return CausalGraph(variables=variables)

    # Marginal correlation matrix
    corr: dict[tuple[str, str], float] = {}
    for a, b in combinations(variables, 2):
        r = correlation(columns[a], columns[b])
        corr[(a, b)] = r

    edges: list[Edge] = []
    for (a, b), r in corr.items():
        if abs(r) < eps_independence:
            continue
        # Check if any conditioning set makes them independent
        others = [v for v in variables if v not in (a, b)]
        conditionally_independent = False
        for k in range(1, min(len(others), 3) + 1):
            # Only test small subsets to keep it tractable (k ≤ 3)
            for combo in combinations(others, k):
                zs = [columns[z] for z in combo]
                pr = partial_correlation(
                    columns[a], columns[b], zs,
                )
                if abs(pr) < eps_conditional:
                    conditionally_independent = True
                    break
            if conditionally_independent:
                break
        if conditionally_independent:
            continue
        # Direct edge — orient if temporal order known
        directed = False
        source, target = a, b
        if temporal_order:
            ra = temporal_order.get(a)
            rb = temporal_order.get(b)
            if ra is not None and rb is not None and ra != rb:
                directed = True
                if ra > rb:
                    source, target = b, a
        rationale = (
            f"|r|={abs(r):.2f} above {eps_independence:.2f}; "
            f"no conditioning set makes them independent"
        )
        edges.append(Edge(
            source=source, target=target,
            directed=directed,
            strength=abs(r),
            rationale=rationale,
        ))

    edges.sort(key=lambda e: -e.strength)
    return CausalGraph(variables=variables, edges=edges)


# ── Introspection ───────────────────────────────────────────

def describe(graph: CausalGraph) -> str:
    if not graph.edges:
        return f"No causal edges found over {len(graph.variables)} variables"
    lines = [f"Causal graph over {', '.join(graph.variables)}:"]
    for e in graph.edges[:10]:
        arrow = "→" if e.directed else "—"
        lines.append(
            f"  {e.source} {arrow} {e.target} "
            f"(strength {e.strength:.2f})"
        )
    if len(graph.edges) > 10:
        lines.append(f"  … {len(graph.edges) - 10} more edges")
    return "\n".join(lines)
