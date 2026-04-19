"""Active query planner — pick the experiment that reduces uncertainty most.

evidence_sufficiency tells you *whether* you have enough. When you
don't, the next question is *which* missing datum would help most.
This is the job of expected information gain.

Model: the brain holds beliefs over a set of candidate hypotheses
(a discrete distribution). Each candidate *query* carries a predicted
answer distribution conditional on each hypothesis. The value of
running that query is the expected entropy drop:

    EIG(query) = H(hypotheses) − E_{answer}[H(hypotheses|answer)]

Callers supply:

  • hypotheses: ``{id: prior}`` summing to ~1
  • queries:    ``{query_id: {hyp_id: answer_distribution}}``

where answer_distribution is either:
  - a dict ``{answer_value: likelihood}``
  - a scalar (deterministic prediction — equivalent to {val: 1.0})

rank(..) returns queries sorted by EIG descending; the top query is
the one worth running next. When a query also has a cost, call
rank_with_cost(..) for EIG per cost.

Pure stdlib. Deterministic. No LLM.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass
class QueryValue:
    query_id: str
    expected_info_gain: float
    expected_info_gain_per_cost: float
    cost: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "expected_info_gain": round(self.expected_info_gain, 6),
            "expected_info_gain_per_cost": round(
                self.expected_info_gain_per_cost, 6,
            ),
            "cost": round(self.cost, 4),
        }


# ── Entropy utilities ─────────────────────────────────────

def _normalise(p: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(v)) for v in p.values())
    if total <= 0:
        return {}
    return {k: max(0.0, float(v)) / total for k, v in p.items()}


def entropy(p: dict[str, float]) -> float:
    q = _normalise(p)
    h = 0.0
    for v in q.values():
        if v > 0:
            h -= v * math.log(v, 2)
    return h


def _coerce_answer_dist(x: Any) -> dict[str, float]:
    if isinstance(x, dict):
        return _normalise({str(k): float(v) for k, v in x.items()})
    # Scalar — deterministic prediction.
    return {str(x): 1.0}


def _posterior_given_answer(
    hypotheses: dict[str, float],
    query_model: dict[str, Any],
    answer: str,
) -> dict[str, float]:
    """Bayesian update: P(H|answer) ∝ P(H) × P(answer|H)."""
    new: dict[str, float] = {}
    for hid, prior in hypotheses.items():
        model = query_model.get(hid)
        if model is None:
            likelihood = 0.0
        else:
            dist = _coerce_answer_dist(model)
            likelihood = dist.get(answer, 0.0)
        new[hid] = float(prior) * likelihood
    return _normalise(new)


# ── Planner ───────────────────────────────────────────────

def expected_info_gain(
    hypotheses: dict[str, float],
    query_model: dict[str, Any],
) -> float:
    """E[H(prior) − H(posterior|answer)] over the predicted answer
    distribution produced by mixing per-hypothesis models by prior."""
    priors = _normalise(hypotheses)
    if not priors:
        return 0.0
    h_prior = entropy(priors)

    # Marginal answer distribution: P(a) = Σ_h P(h) × P(a|h)
    marginal: dict[str, float] = defaultdict(float)
    for hid, p in priors.items():
        model = query_model.get(hid)
        if model is None:
            continue
        for ans, lik in _coerce_answer_dist(model).items():
            marginal[ans] += p * lik

    if not marginal:
        return 0.0

    eig = h_prior
    for ans, pa in marginal.items():
        if pa <= 0:
            continue
        posterior = _posterior_given_answer(priors, query_model, ans)
        eig -= pa * entropy(posterior)
    return max(0.0, eig)


def rank(
    hypotheses: dict[str, float],
    queries: dict[str, dict[str, Any]],
) -> list[QueryValue]:
    """Rank queries purely by information gain (ignoring cost)."""
    return rank_with_cost(hypotheses, queries, costs={})


def rank_with_cost(
    hypotheses: dict[str, float],
    queries: dict[str, dict[str, Any]],
    costs: dict[str, float] | None = None,
) -> list[QueryValue]:
    """Rank queries by EIG and by EIG-per-cost. Unknown costs default to 1."""
    costs = costs or {}
    out: list[QueryValue] = []
    for qid, model in queries.items():
        eig = expected_info_gain(hypotheses, model)
        cost = max(1e-9, float(costs.get(qid, 1.0)))
        out.append(QueryValue(
            query_id=qid,
            expected_info_gain=eig,
            expected_info_gain_per_cost=eig / cost,
            cost=cost,
        ))
    out.sort(key=lambda v: -v.expected_info_gain_per_cost)
    return out


def best(
    hypotheses: dict[str, float],
    queries: dict[str, dict[str, Any]],
    costs: dict[str, float] | None = None,
) -> QueryValue | None:
    """Convenience: return the single best query."""
    ranked = rank_with_cost(hypotheses, queries, costs)
    return ranked[0] if ranked else None
