"""Information gain — pick experiments that teach the brain the most.

ShopAI already runs hypotheses (v7-D2) and curiosity probes
(v3-D2). Neither *ranks* candidate experiments by how much they
would reduce the brain's uncertainty. Running the wrong
experiment wastes budget and rarely moves the needle.

InformationGainPlanner scores candidate experiments against:

  1. Expected information gain (EIG) — how much the posterior
     would shrink if we ran this experiment. Implemented as the
     entropy difference between the prior and expected posterior.
  2. Cost — dollars + time the experiment burns.
  3. Epistemic fit — prioritise experiments probing cold cells.

Utility = α · EIG − β · cost + γ · epistemic_novelty

The returned ``Ranking`` lists candidates in descending utility
with per-component breakdown so the dashboard can show *why* this
test was picked.

Entropy math: treat each candidate as a Beta posterior over a
binary outcome (e.g. "will this launch cross ROAS=2?"). EIG is the
expected drop in the posterior's variance after N additional
observations at the candidate's specificity.

Pure stdlib — uses math.log, no numpy. Zero LLM.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class Candidate:
    id: str
    label: str
    prior_alpha: float = 1.0          # Beta prior α
    prior_beta: float = 1.0           # Beta prior β
    cost_usd: float = 0.0
    expected_observations: int = 10   # how many outcomes the experiment yields
    epistemic_novelty: float = 0.5    # 0 = already well-explored, 1 = brand new
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def prior_mean(self) -> float:
        return self.prior_alpha / (self.prior_alpha + self.prior_beta)

    @property
    def prior_variance(self) -> float:
        a, b = self.prior_alpha, self.prior_beta
        return (a * b) / ((a + b) ** 2 * (a + b + 1))


@dataclass
class ScoredCandidate:
    candidate: Candidate
    utility: float
    eig: float
    cost_term: float
    novelty_term: float
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.candidate.id,
            "label": self.candidate.label,
            "utility": round(self.utility, 4),
            "eig": round(self.eig, 4),
            "cost_term": round(self.cost_term, 4),
            "novelty_term": round(self.novelty_term, 4),
            "rationale": self.rationale,
        }


@dataclass
class Ranking:
    top: list[ScoredCandidate] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"top": [s.as_dict() for s in self.top]}

    @property
    def best(self) -> ScoredCandidate | None:
        return self.top[0] if self.top else None


# ── Entropy helpers ─────────────────────────────────────────

def _beta_entropy(alpha: float, beta: float) -> float:
    """Closed-form differential entropy of Beta(α, β)."""
    from math import lgamma
    a, b = float(alpha), float(beta)
    if a <= 0 or b <= 0:
        return 0.0
    # H = log B(a, b) - (a-1) ψ(a) - (b-1) ψ(b) + (a+b-2) ψ(a+b)
    # We approximate ψ with log (valid for moderate a,b).
    log_B = lgamma(a) + lgamma(b) - lgamma(a + b)
    # Simple digamma approximation: ψ(x) ≈ log(x) - 1/(2x)
    def psi(x: float) -> float:
        if x <= 0:
            return 0.0
        return math.log(x) - 1.0 / (2.0 * x)
    return (log_B
            - (a - 1) * psi(a)
            - (b - 1) * psi(b)
            + (a + b - 2) * psi(a + b))


def expected_information_gain(
    alpha: float, beta: float, n_obs: int,
) -> float:
    """EIG after ``n_obs`` additional observations.

    Uses the entropy-difference approximation: entropy of the
    prior minus expected entropy of the posterior averaged over
    possible outcomes."""
    if n_obs <= 0 or alpha <= 0 or beta <= 0:
        return 0.0
    prior_H = _beta_entropy(alpha, beta)
    p_mean = alpha / (alpha + beta)
    # Expected successes = n_obs × p_mean (linearity of expectation).
    # Post-posterior under a single "typical" split:
    exp_k = p_mean * n_obs
    post_alpha = alpha + exp_k
    post_beta = beta + (n_obs - exp_k)
    post_H = _beta_entropy(post_alpha, post_beta)
    return max(0.0, prior_H - post_H)


# ── Planner ─────────────────────────────────────────────────

def rank(
    candidates: Iterable[Candidate],
    *,
    alpha_eig: float = 1.0,
    beta_cost: float = 0.05,
    gamma_novelty: float = 0.3,
    cost_cap_usd: float = 100.0,
    top_k: int = 10,
) -> Ranking:
    scored: list[ScoredCandidate] = []
    for c in candidates:
        eig = expected_information_gain(
            c.prior_alpha, c.prior_beta, c.expected_observations,
        )
        cost_term = min(1.0, c.cost_usd / max(1e-6, cost_cap_usd))
        novelty = max(0.0, min(1.0, c.epistemic_novelty))
        utility = (alpha_eig * eig
                    - beta_cost * cost_term
                    + gamma_novelty * novelty)
        scored.append(ScoredCandidate(
            candidate=c,
            utility=utility,
            eig=eig,
            cost_term=cost_term,
            novelty_term=novelty,
            rationale=_rationale(eig, cost_term, novelty),
        ))
    scored.sort(key=lambda s: -s.utility)
    return Ranking(top=scored[:top_k])


def _rationale(eig: float, cost_term: float, novelty: float) -> str:
    parts: list[str] = []
    if eig > 0.5:
        parts.append(f"high EIG {eig:.2f}")
    elif eig > 0.1:
        parts.append(f"modest EIG {eig:.2f}")
    else:
        parts.append(f"low EIG {eig:.2f}")
    if cost_term >= 0.5:
        parts.append(f"costly ({cost_term:.2f})")
    if novelty >= 0.7:
        parts.append("probes unexplored cell")
    return "; ".join(parts)


# ── Budget-constrained picker ────────────────────────────────

def pick_under_budget(
    candidates: Iterable[Candidate],
    total_budget_usd: float,
    **kwargs: Any,
) -> list[ScoredCandidate]:
    """Greedy: rank by utility then pick until budget is exhausted.
    Returns the selected subset in utility order."""
    ranking = rank(candidates, **kwargs)
    chosen: list[ScoredCandidate] = []
    remaining = float(total_budget_usd)
    for s in ranking.top:
        if s.candidate.cost_usd <= remaining:
            chosen.append(s)
            remaining -= s.candidate.cost_usd
        if remaining <= 0:
            break
    return chosen
