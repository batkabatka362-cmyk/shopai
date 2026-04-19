"""Deliberation loop — multi-step think → critique → revise → commit.

A single pass of ``brain().think()`` is shallow. AGI-level reasoning
requires the brain to *talk to itself*: propose → challenge → revise →
commit. That is the deliberation loop.

Flow per call:

    1. PROPOSE    — initial candidate action (from policy, cases, or
                     caller-supplied seed)
    2. CRITIQUE   — counter_argument + critic_panel find the soft spots
    3. REVISE     — if critics raise valid blockers, regenerate with
                     blockers excluded
    4. VOTE       — voting_ensemble across revision history picks the
                     final candidate when revisions remain uncertain
    5. COMMIT     — return the winning action + full reasoning trail

The loop is bounded: ``max_rounds`` caps the think→revise cycles so
a pathological critic never stalls. Every round is captured in the
``DeliberationTrace`` and (optionally) mirrored to the experience
recorder.

Pure stdlib. Deterministic given seeds. No LLM calls.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("brain.deliberation_loop")


ProposeFn = Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any] | None]
CritiqueFn = Callable[[dict[str, Any], dict[str, Any]], list[dict[str, Any]]]


@dataclass
class DeliberationRound:
    round_num: int
    candidate: dict[str, Any]
    critiques: list[dict[str, Any]] = field(default_factory=list)
    revised: bool = False
    score: float = 0.0
    blockers: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "round_num": self.round_num,
            "candidate": self.candidate,
            "critiques": list(self.critiques),
            "revised": self.revised,
            "score": round(self.score, 4),
            "blockers": list(self.blockers),
        }


@dataclass
class DeliberationTrace:
    question_id: str
    winner: dict[str, Any] | None
    rounds: list[DeliberationRound] = field(default_factory=list)
    commit_reason: str = ""
    converged: bool = False
    elapsed_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "winner": self.winner,
            "rounds": [r.as_dict() for r in self.rounds],
            "commit_reason": self.commit_reason,
            "converged": self.converged,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


# ── Helpers: critique severity + scoring ──────────────────

_SEVERITY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}


def _is_blocker(critique: dict[str, Any]) -> bool:
    level = str(critique.get("severity", "")).lower()
    return _SEVERITY_RANK.get(level, 0) >= 2


def _critique_score(critiques: Iterable[dict[str, Any]]) -> float:
    """Sum of critique severities; lower is better for the candidate."""
    total = 0
    for c in critiques:
        total += _SEVERITY_RANK.get(str(c.get("severity", "")).lower(), 0)
    return float(total)


def _fingerprint(candidate: dict[str, Any]) -> str:
    """Stable key for dedup detection."""
    return "|".join(
        f"{k}={v}" for k, v in sorted(candidate.items())
    )


# ── Main loop ─────────────────────────────────────────────

def deliberate(
    question_id: str,
    context: dict[str, Any],
    propose: ProposeFn,
    critique: CritiqueFn,
    *,
    seed_candidate: dict[str, Any] | None = None,
    max_rounds: int = 5,
    mirror: bool = False,
) -> DeliberationTrace:
    """Run the think → critique → revise loop."""
    if max_rounds < 1:
        raise ValueError("max_rounds must be ≥ 1")
    started = time.monotonic()
    trace = DeliberationTrace(question_id=question_id, winner=None)
    active_blockers: list[str] = []
    seen_fingerprints: set[str] = set()

    for n in range(1, max_rounds + 1):
        if seed_candidate is not None and n == 1:
            candidate = dict(seed_candidate)
        else:
            try:
                candidate = propose(
                    {**context, "blocked": list(active_blockers)},
                    [r.as_dict() for r in trace.rounds],
                ) or {}
            except Exception as exc:
                trace.commit_reason = f"propose_raised: {exc}"
                break

        if not candidate:
            trace.commit_reason = "no_candidate_produced"
            break

        fp = _fingerprint(candidate)
        if fp in seen_fingerprints:
            # Re-proposed same candidate — loop isn't helping.
            trace.commit_reason = "converged_on_repeat_candidate"
            trace.converged = True
            break
        seen_fingerprints.add(fp)

        try:
            critiques = list(critique(candidate, context) or [])
        except Exception as exc:
            critiques = [
                {"severity": "critical",
                 "note": f"critique_raised: {exc}"},
            ]

        blockers = [
            str(c.get("note") or c.get("reason") or "")
            for c in critiques
            if _is_blocker(c)
        ]
        score = _critique_score(critiques)
        round_rec = DeliberationRound(
            round_num=n, candidate=candidate,
            critiques=critiques, score=score,
            blockers=blockers,
        )
        trace.rounds.append(round_rec)

        if not blockers:
            trace.winner = candidate
            trace.commit_reason = (
                "no_blockers"
                if n == 1 else f"clean_revision_round_{n}"
            )
            trace.converged = True
            break

        # Accumulate blockers so the next proposal sees them as
        # excluded patterns.
        round_rec.revised = True
        active_blockers = list({*active_blockers, *blockers})

    else:
        # Exhausted max_rounds — pick the round with the lowest score
        # (fewest / least-severe critiques).
        if trace.rounds:
            best = min(trace.rounds, key=lambda r: r.score)
            trace.winner = best.candidate
            trace.commit_reason = (
                f"budget_exhausted_picking_round_{best.round_num}"
            )

    trace.elapsed_ms = (time.monotonic() - started) * 1000.0
    if mirror:
        _mirror_trace(trace)
    return trace


# ── Adapter helpers — connect to existing modules ────────

def from_counter_argument_and_critic_panel(
    *,
    counter_arg_probes: Iterable[Callable[[dict[str, Any]], dict[str, Any] | None]]
        | None = None,
) -> CritiqueFn:
    """Build a CritiqueFn that calls counter_argument + critic_panel."""
    def _critique(
        candidate: dict[str, Any], context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            from core.brain import counter_argument as ca
            for rep in ca.run(candidate, context=context):
                out.append({
                    "source": "counter_argument",
                    "severity": rep.severity,
                    "note": rep.message,
                })
        except Exception as exc:
            # counter_argument schema varies across versions; treat any
            # failure as "no critiques from this source" and continue.
            logger.debug("counter_argument unavailable: %s", exc)
        try:
            from core.brain import critic_panel as cp
            verdict = cp.evaluate(candidate, context=context)
            for c in verdict.critiques:
                out.append({
                    "source": c.role,
                    "severity": c.severity,
                    "note": c.note,
                })
        except Exception as exc:
            logger.debug("critic_panel unavailable: %s", exc)
        if counter_arg_probes:
            for probe in counter_arg_probes:
                try:
                    r = probe(candidate)
                    if r:
                        out.append(r)
                except Exception:
                    continue
        return out
    return _critique


def _mirror_trace(trace: DeliberationTrace) -> None:
    try:
        from core.brain import experience_recorder as er
        er._write(   # noqa: SLF001 (intentional; same-package hook)
            kind="deliberation",
            cycle_id=trace.question_id,
            payload=trace.as_dict(),
        )
    except Exception:
        return
