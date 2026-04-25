"""Moby vote comparator — owner-requested Option 3.

Wave C-1 A7 of IMPLEMENTATION_PLAN_2026. For every campaign /
budget / creative decision, ShopAI's DecisionBrain now votes
alongside Triple Whale's Moby Agents. When the two disagree
we log (moby_vote, shopai_vote, "") to MobyAdapter. Once the
real outcome lands — via OutcomeRecorder fires from paid
orders — we resolve the matching disagreement row so that
``win_rate_by_source()`` becomes a real per-decision-kind
trust signal after ~30 days.

Why a separate module (rather than mutating DecisionBrain):
  * DecisionBrain already has 20+ call sites. Wiring Moby
    into each is high churn.
  * A pure comparator is auditable, dependency-injected, and
    testable without pulling in Meta Ads + RL + memory.
  * We can delete this module in 90 days if Moby's
    recommendations track ours — zero blast radius.

Responsibilities:

  * ``compare_votes(shopai_votes, moby_recs)`` → list of
    logged disagreements + agreements, with stable entity
    matching by ``entity_id`` (campaign / adset id).
  * ``resolve_outcome(decision_id, actual)`` → forwards to
    the adapter's update_disagreement_outcome.
  * ``win_rate()`` → pass-through summary.

Pure stdlib. Adapter is injectable for offline tests.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("core.brain.moby_vote_comparator")


@dataclass
class ShopAIVote:
    """A single DecisionBrain vote on a campaign/adset/creative."""

    decision_id: str
    entity_id: str                # matches Moby's entity_id
    action: str                   # e.g. "pause", "increase_budget"
    confidence: float = 0.5
    note: str = ""


@dataclass
class CompareReport:
    decision_ids: tuple[str, ...] = ()
    agreements: tuple[str, ...] = ()
    disagreements_logged: tuple[str, ...] = ()
    no_moby_rec: tuple[str, ...] = ()
    errors: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_ids": list(self.decision_ids),
            "agreements": list(self.agreements),
            "disagreements_logged": (
                list(self.disagreements_logged)
            ),
            "no_moby_rec": list(self.no_moby_rec),
            "errors": dict(self.errors),
        }


def _normalize(action: str) -> str:
    """Collapse semantically-equivalent phrasings so we don't
    log spurious disagreements. ``scale_up`` and
    ``increase_budget`` mean the same thing."""
    s = (action or "").strip().lower()
    synonyms = {
        "scale_up": "increase_budget",
        "scale": "increase_budget",
        "boost": "increase_budget",
        "scale_down": "decrease_budget",
        "cut": "decrease_budget",
        "off": "pause",
        "stop": "pause",
        "halt": "pause",
        "kill": "pause",
        "on": "resume",
        "unpause": "resume",
        "launch": "activate",
    }
    return synonyms.get(s, s)


class MobyVoteComparator:
    """Compare ShopAI votes to Moby recs + log disagreements."""

    def __init__(
        self,
        *,
        adapter: Any = None,
    ) -> None:
        self._adapter = adapter
        self._lock = threading.RLock()
        self._last_report: CompareReport | None = None

    def _get_adapter(self) -> Any:
        if self._adapter is not None:
            return self._adapter
        try:
            from core.adapters.triplewhale.moby import (
                get_moby_adapter,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "moby adapter lazy import: %s", exc,
            )
            return None
        self._adapter = get_moby_adapter()
        return self._adapter

    def compare_votes(
        self,
        shopai_votes: list[ShopAIVote],
        moby_recs: list[Any],
    ) -> CompareReport:
        """Pair each ShopAI vote with the matching Moby rec and
        log disagreements. Returns a structured report."""
        adapter = self._get_adapter()
        by_entity: dict[str, Any] = {}
        for rec in moby_recs or []:
            eid = str(
                getattr(rec, "entity_id", "") or "",
            )
            if eid:
                by_entity[eid] = rec
        decision_ids: list[str] = []
        agreements: list[str] = []
        disagreements: list[str] = []
        no_rec: list[str] = []
        errors: dict[str, str] = {}
        for vote in shopai_votes or []:
            if not isinstance(vote, ShopAIVote):
                continue
            if not vote.decision_id:
                continue
            decision_ids.append(vote.decision_id)
            rec = by_entity.get(vote.entity_id)
            if rec is None:
                no_rec.append(vote.decision_id)
                continue
            moby_action = _normalize(
                getattr(rec, "recommendation", ""),
            )
            shopai_action = _normalize(vote.action)
            if moby_action == shopai_action:
                agreements.append(vote.decision_id)
                continue
            # Disagreement. Only log if we have an adapter.
            if adapter is None:
                errors[vote.decision_id] = (
                    "no adapter"
                )
                continue
            try:
                adapter.record_disagreement(
                    decision_id=vote.decision_id,
                    moby_vote=(
                        getattr(rec, "recommendation", "")
                        or moby_action
                    ),
                    shopai_vote=(
                        vote.action or shopai_action
                    ),
                    note=vote.note,
                )
                disagreements.append(vote.decision_id)
            except ValueError as exc:
                # record_disagreement raises when votes agree
                # after normalisation differences — treat as
                # agreement.
                logger.debug(
                    "dedup agreement: %s", exc,
                )
                agreements.append(vote.decision_id)
            except Exception as exc:  # noqa: BLE001
                errors[vote.decision_id] = str(exc)
        report = CompareReport(
            decision_ids=tuple(decision_ids),
            agreements=tuple(agreements),
            disagreements_logged=tuple(disagreements),
            no_moby_rec=tuple(no_rec),
            errors=errors,
        )
        with self._lock:
            self._last_report = report
        return report

    def resolve_outcome(
        self,
        *,
        decision_id: str,
        actual: str,
    ) -> bool:
        """Once an actual outcome is observed (from
        OutcomeRecorder / order webhook), resolve the logged
        disagreement so win-rate reflects reality."""
        if not decision_id:
            return False
        if not actual:
            return False
        adapter = self._get_adapter()
        if adapter is None:
            return False
        try:
            return bool(
                adapter.update_disagreement_outcome(
                    decision_id=decision_id,
                    actual_outcome=_normalize(actual),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "moby resolve failed: %s", exc,
            )
            return False

    def win_rate(self) -> dict[str, Any]:
        """Pass-through to adapter; empty dict when unavailable."""
        adapter = self._get_adapter()
        if adapter is None:
            return {}
        try:
            return adapter.win_rate_by_source()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "win_rate pass-through: %s", exc,
            )
            return {}

    def last_report(self) -> CompareReport | None:
        with self._lock:
            return self._last_report


# ── Singleton ─────────────────────────────────────────────

_SINGLETON: MobyVoteComparator | None = None
_SINGLETON_LOCK = threading.Lock()


def get_moby_vote_comparator() -> MobyVoteComparator:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = MobyVoteComparator()
    return _SINGLETON


def reset_moby_vote_comparator_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = None
