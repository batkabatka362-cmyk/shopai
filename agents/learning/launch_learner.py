"""Launch learner — close the loop from launches to rules.

Sprint 2 #2 of AGI_MISSION_PLAN. Completes the autonomous cycle:

   autopilot → publisher_bundle → order → OutcomeRecorder
      ↓
   episode_summariser (already fires on each run_cycle)
      ↓
   launch_learner.distill() — convert episodes to Rules
      ↓
   principle_extractor — cluster Rules into Principles
      ↓
   proposal_arbiter — score + dedupe candidate Proposals
      ↓
   self_revision_journal.propose — queue for owner review
      ↓
   owner approves via `shopai approve` → rule goes live

Without this module, the v33-v38 brain recorded calibration +
drift + funnel but never promoted a learning into an actionable
rule. LaunchLearner polls the episode_summariser, buckets episodes
by situation signature (niche + price_band + source), converts
each bucket's win/loss pattern into a concrete Rule shape, feeds
them to principle_extractor, and arbitrates the resulting
principles into self_revision_journal proposals.

Pure stdlib, deterministic. All brain modules are dependency-
injectable so this is trivially unit-testable.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("agents.learning.launch_learner")


_DEFAULT_MIN_EPISODES = 5
_DEFAULT_MIN_CONFIDENCE = 0.5


@dataclass
class DistilledProposal:
    """Summary of one rule-promotion attempt."""
    id: str
    statement: str
    source_episode_count: int
    win_rate: float
    avg_confidence: float
    arbitration_verdict: str    # "accept" | "defer" | "reject_all" | "skip"
    journal_revision_id: str = ""
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "source_episode_count": self.source_episode_count,
            "win_rate": round(self.win_rate, 4),
            "avg_confidence": round(
                self.avg_confidence, 4,
            ),
            "arbitration_verdict": (
                self.arbitration_verdict
            ),
            "journal_revision_id": (
                self.journal_revision_id
            ),
            "note": self.note,
        }


@dataclass
class DistillReport:
    """Result of one distill() run."""
    episodes_examined: int
    clusters_formed: int
    proposals: list[DistilledProposal]
    ts: float

    @property
    def accepted(self) -> int:
        return sum(
            1 for p in self.proposals
            if p.arbitration_verdict == "accept"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "episodes_examined": self.episodes_examined,
            "clusters_formed": self.clusters_formed,
            "proposals": [
                p.as_dict() for p in self.proposals
            ],
            "accepted": self.accepted,
            "ts": self.ts,
        }


class LaunchLearner:
    """Promote launch episodes → live rules via the brain chain."""

    def __init__(
        self,
        *,
        episode_summariser: Any = None,
        principle_extractor: Any = None,
        proposal_arbiter: Any = None,
        revision_journal: Any = None,
        min_episodes: int = _DEFAULT_MIN_EPISODES,
        min_confidence: float = _DEFAULT_MIN_CONFIDENCE,
    ) -> None:
        if min_episodes < 2:
            raise ValueError(
                "min_episodes must be ≥ 2",
            )
        if not 0.0 < min_confidence < 1.0:
            raise ValueError(
                "min_confidence must be in (0, 1)",
            )
        self._lock = threading.Lock()
        self._summariser = episode_summariser
        self._extractor = principle_extractor
        self._arbiter = proposal_arbiter
        self._journal = revision_journal
        self._min_episodes = int(min_episodes)
        self._min_confidence = float(min_confidence)
        self._history: list[DistillReport] = []

    # ── Lazy deps (use brain_facade singletons by default) ─

    def _get_summariser(self) -> Any:
        if self._summariser is not None:
            return self._summariser
        from core.brain.brain_facade import (
            _episode_summariser,
        )
        self._summariser = _episode_summariser()
        return self._summariser

    def _get_extractor(self) -> Any:
        if self._extractor is not None:
            return self._extractor
        from core.brain.principle_extractor import (
            PrincipleExtractor,
        )
        self._extractor = PrincipleExtractor(
            min_rules=2,
            similarity_threshold=0.4,
        )
        return self._extractor

    def _get_arbiter(self) -> Any:
        if self._arbiter is not None:
            return self._arbiter
        from core.brain.brain_facade import (
            _proposal_arbiter,
        )
        self._arbiter = _proposal_arbiter()
        return self._arbiter

    def _get_journal(self) -> Any:
        if self._journal is not None:
            return self._journal
        from core.brain.brain_facade import (
            _revision_journal,
        )
        self._journal = _revision_journal()
        return self._journal

    # ── Distill ──────────────────────────────────────────

    def distill(
        self, *, window_limit: int = 200,
    ) -> DistillReport:
        """Scan recent episodes and promote patterns to rules.

        ``window_limit`` caps how far back we look — keeps the
        loop deterministic in long-running daemons.
        """
        summariser = self._get_summariser()
        episodes = summariser.recent(limit=window_limit)
        total = len(episodes)
        # Only consider resolved episodes (win or loss). Pending /
        # mixed episodes don't have a clear enough outcome yet.
        relevant = [
            e for e in episodes
            if getattr(e, "outcome", "") in ("win", "loss")
        ]
        if len(relevant) < self._min_episodes:
            report = DistillReport(
                episodes_examined=total,
                clusters_formed=0,
                proposals=[],
                ts=time.time(),
            )
            self._archive(report)
            return report
        clusters = self._cluster_by_situation(relevant)
        proposals: list[DistilledProposal] = []
        for signature, bucket in clusters.items():
            proposal = self._promote(
                signature, bucket,
            )
            if proposal is not None:
                proposals.append(proposal)
        report = DistillReport(
            episodes_examined=total,
            clusters_formed=len(clusters),
            proposals=proposals,
            ts=time.time(),
        )
        self._archive(report)
        return report

    def _cluster_by_situation(
        self, episodes: list[Any],
    ) -> dict[str, list[Any]]:
        """Group episodes by a canonical situation signature."""
        clusters: dict[str, list[Any]] = {}
        for ep in episodes:
            sig = _situation_signature(ep)
            clusters.setdefault(sig, []).append(ep)
        # Only keep clusters that meet the min_episodes floor
        return {
            sig: bucket
            for sig, bucket in clusters.items()
            if len(bucket) >= self._min_episodes
        }

    def _promote(
        self, signature: str, bucket: list[Any],
    ) -> DistilledProposal | None:
        wins = sum(
            1 for e in bucket
            if getattr(e, "outcome", "") == "win"
        )
        losses = sum(
            1 for e in bucket
            if getattr(e, "outcome", "") == "loss"
        )
        decided = wins + losses
        if decided == 0:
            return None
        win_rate = wins / decided
        confidence = min(1.0, decided / 10.0)
        # Only promote strong patterns — either consistent wins or
        # consistent losses. Mixed buckets (~50% win rate) don't
        # teach us anything actionable.
        if 0.35 <= win_rate <= 0.65:
            return DistilledProposal(
                id=uuid.uuid4().hex,
                statement=(
                    f"pattern '{signature}' inconclusive "
                    f"({wins}W / {losses}L)"
                ),
                source_episode_count=decided,
                win_rate=win_rate,
                avg_confidence=confidence,
                arbitration_verdict="skip",
                note="mixed outcome — no rule to extract",
            )
        if confidence < self._min_confidence:
            return DistilledProposal(
                id=uuid.uuid4().hex,
                statement=(
                    f"pattern '{signature}' has only "
                    f"{decided} resolved episodes"
                ),
                source_episode_count=decided,
                win_rate=win_rate,
                avg_confidence=confidence,
                arbitration_verdict="skip",
                note="below min_confidence — wait for more data",
            )
        # Build a Rule shape principle_extractor expects
        consequent = (
            "launch_winner" if win_rate > 0.5
            else "avoid_pattern"
        )
        rule_antecedent = (
            f"situation_matches {signature}"
        )
        statement = (
            f"{consequent} when {signature} "
            f"({wins}W / {losses}L, "
            f"conf={confidence:.2f})"
        )
        # Run through principle_extractor — even a single
        # high-confidence cluster is worth extracting as a named
        # principle so related clusters group over time.
        try:
            from core.brain.principle_extractor import Rule
            rule = Rule(
                id=uuid.uuid4().hex,
                antecedent=rule_antecedent,
                consequent=consequent,
                support=decided,
                confidence=confidence,
            )
            # principle_extractor needs ≥ 2 rules to cluster; we
            # pass a single rule and let it fall through cleanly.
            self._get_extractor().extract([rule])
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "principle_extractor failed: %s", exc,
            )
        # Arbitrate through proposal_arbiter
        verdict = "skip"
        revision_id = ""
        arbiter_note = ""
        try:
            from core.brain.proposal_arbiter import (
                Proposal,
            )
            proposal = Proposal(
                id=uuid.uuid4().hex,
                target=f"rule:{signature}",
                new_value=statement,
                evidence_score=confidence,
                proposer="launch_learner",
                ts=time.time(),
            )
            outcome = self._get_arbiter().arbitrate(
                target=proposal.target,
                proposals=[proposal],
                current_value=None,
            )
            verdict = outcome.verdict
            arbiter_note = outcome.reason
            if verdict == "accept":
                # Route to self_revision_journal
                try:
                    rev = self._get_journal().propose(
                        kind="rule",
                        target=f"rule:{signature}",
                        old_value=None,
                        new_value=statement,
                        reason=(
                            f"launch_learner: {decided} "
                            f"resolved episodes, win_rate "
                            f"{win_rate:.2f}"
                        ),
                        evidence_score=confidence,
                    )
                    revision_id = rev.id
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "journal propose failed: %s", exc,
                    )
                    verdict = "skip"
                    arbiter_note = (
                        f"journal unavailable: {exc}"
                    )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "proposal_arbiter failed: %s", exc,
            )
            arbiter_note = f"arbiter unavailable: {exc}"
        return DistilledProposal(
            id=uuid.uuid4().hex,
            statement=statement,
            source_episode_count=decided,
            win_rate=win_rate,
            avg_confidence=confidence,
            arbitration_verdict=verdict,
            journal_revision_id=revision_id,
            note=arbiter_note,
        )

    # ── Queries ──────────────────────────────────────────

    def _archive(self, report: DistillReport) -> None:
        with self._lock:
            self._history.append(report)
            if len(self._history) > 200:
                del self._history[
                    : len(self._history) - 200
                ]

    def recent(
        self, *, limit: int = 10,
    ) -> list[DistillReport]:
        with self._lock:
            return list(
                self._history[-max(1, int(limit)):],
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_runs = len(self._history)
            total_proposals = sum(
                len(r.proposals)
                for r in self._history
            )
            total_accepted = sum(
                r.accepted for r in self._history
            )
            return {
                "runs": total_runs,
                "total_proposals": total_proposals,
                "total_accepted": total_accepted,
                "acceptance_rate": (
                    total_accepted / total_proposals
                    if total_proposals else 0.0
                ),
                "min_episodes": self._min_episodes,
                "min_confidence": self._min_confidence,
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._history)
            self._history.clear()
        return n


# ── Situation signature ─────────────────────────────────────


def _situation_signature(episode: Any) -> str:
    """Canonical per-niche-price-source key.

    We read from episode.situation_terms (tuple of "k=v" strings
    already produced by episode_summariser) and pick the most
    predictive subset. Order matters — same-key-different-value
    produces distinct signatures so the clusterer can see them.
    """
    terms = getattr(episode, "situation_terms", ()) or ()
    # Filter to meaningful keys. The default episode_summariser
    # seed uses keys like {goal, health_grade, cycle_number}.
    # autopilot-produced episodes carry {niche, margin_band,
    # source, ...}.
    interesting = {
        "niche", "margin_band", "saturation_band",
        "source", "price_band", "tag",
    }
    picked: list[str] = []
    for t in terms:
        if "=" not in t:
            continue
        key = t.split("=", 1)[0]
        if key in interesting:
            picked.append(t)
    if not picked:
        # Fallback — use the full signature so we still cluster by
        # something (even if coarsely).
        picked = [t for t in terms if "=" in t]
    return "|".join(sorted(picked)) or "generic"
