"""Pattern miner — episode → RuleBook proposal.

Track 1b of AGI_HARDENING_PLAN. Sprint 2 shipped ``launch_learner``
which distills launch episodes into proposals for the revision
journal. This module is the next layer up: it mines *outcome
events* for repeated patterns (3+ similar failures or 5+ similar
wins) and promotes them into the RuleBook as ``proposed`` rules.

Heuristic:

  * Bucket outcome events by a ``situation_signature`` — a stable
    tuple of (capability_name, kpi, kpi_band, ok). ``kpi_band`` is
    a coarsening of the raw kpi_value into { "low", "mid", "high" }
    so similar-but-not-identical numbers collide.
  * When a bucket has ≥ ``min_evidence`` members and its failure
    rate ≥ ``fail_rate_floor``, emit a ``kill_signature`` proposal.
  * When a bucket has ≥ ``min_wins`` with win rate ≥ ``win_rate_floor``,
    emit a ``replay_signature`` proposal.

Pure stdlib. Deterministic. LLM-free. Safe to run on every cycle —
the RuleBook dedupes by (origin, pattern, action).
"""
from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("core.learning.pattern_miner")


_DEFAULT_MIN_EVIDENCE = 3
_DEFAULT_MIN_WINS = 5
_DEFAULT_FAIL_RATE_FLOOR = 0.60
_DEFAULT_WIN_RATE_FLOOR = 0.70


def _kpi_band(value: float) -> str:
    v = float(value or 0.0)
    if v <= 0.5:
        return "low"
    if v <= 1.5:
        return "mid"
    return "high"


def _event_signature(event: Any) -> tuple[str, ...]:
    """Stable signature for an OutcomeEvent-like object.

    Accepts either a dataclass instance or a dict — tolerant so
    callers don't need to convert.
    """

    def _g(name: str, default: Any = "") -> Any:
        if isinstance(event, dict):
            return event.get(name, default)
        return getattr(event, name, default)

    capability = str(_g("capability_name") or "")
    kpi = str(_g("kpi") or "")
    kpi_value = float(_g("kpi_value", 0.0) or 0.0)
    ok = bool(_g("ok", False))
    return (capability, kpi, _kpi_band(kpi_value), str(ok))


@dataclass
class MiningReport:
    examined: int
    unique_signatures: int
    proposals_emitted: int
    skipped_low_evidence: int
    kill_proposals: tuple[str, ...] = ()
    replay_proposals: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "examined": self.examined,
            "unique_signatures": self.unique_signatures,
            "proposals_emitted": self.proposals_emitted,
            "skipped_low_evidence": (
                self.skipped_low_evidence
            ),
            "kill_proposals": list(self.kill_proposals),
            "replay_proposals": list(self.replay_proposals),
        }


class PatternMiner:
    """Run periodically over outcome events to surface patterns."""

    def __init__(
        self,
        *,
        rulebook: Any = None,
        min_evidence: int = _DEFAULT_MIN_EVIDENCE,
        min_wins: int = _DEFAULT_MIN_WINS,
        fail_rate_floor: float = _DEFAULT_FAIL_RATE_FLOOR,
        win_rate_floor: float = _DEFAULT_WIN_RATE_FLOOR,
    ) -> None:
        if min_evidence < 1:
            raise ValueError("min_evidence must be ≥ 1")
        if min_wins < 1:
            raise ValueError("min_wins must be ≥ 1")
        for name, v in (
            ("fail_rate_floor", fail_rate_floor),
            ("win_rate_floor", win_rate_floor),
        ):
            if not 0.0 <= v <= 1.0:
                raise ValueError(
                    f"{name} must be in [0, 1]",
                )
        self._lock = threading.Lock()
        self._rulebook = rulebook
        self._min_evidence = int(min_evidence)
        self._min_wins = int(min_wins)
        self._fail_floor = float(fail_rate_floor)
        self._win_floor = float(win_rate_floor)

    def _get_rulebook(self) -> Any:
        if self._rulebook is not None:
            return self._rulebook
        from core.learning.rulebook import get_rulebook
        self._rulebook = get_rulebook()
        return self._rulebook

    def mine(
        self,
        events: Iterable[Any],
    ) -> MiningReport:
        """Scan events, emit proposals into the RuleBook.

        Idempotent — the RuleBook collapses duplicate proposals
        into evidence_count bumps.
        """
        events_list = list(events or [])
        if not events_list:
            return MiningReport(
                examined=0,
                unique_signatures=0,
                proposals_emitted=0,
                skipped_low_evidence=0,
            )
        buckets: dict[
            tuple[str, ...], list[Any]
        ] = {}
        for ev in events_list:
            sig = _event_signature(ev)
            buckets.setdefault(sig, []).append(ev)
        kill_ids: list[str] = []
        replay_ids: list[str] = []
        proposals = 0
        skipped = 0
        book = self._get_rulebook()
        for sig, rows in buckets.items():
            capability, kpi, kpi_band, ok_str = sig
            if len(rows) < self._min_evidence:
                skipped += 1
                continue
            fails = sum(
                1 for r in rows
                if not bool(
                    r.get("ok") if isinstance(r, dict)
                    else getattr(r, "ok", False)
                )
            )
            total = len(rows)
            fail_rate = fails / total
            win_rate = 1.0 - fail_rate
            pattern_str = (
                f"capability={capability};kpi={kpi};"
                f"kpi_band={kpi_band}"
            )
            if (
                total >= self._min_evidence
                and fail_rate >= self._fail_floor
            ):
                rule = book.propose(
                    origin="pattern_miner",
                    pattern=pattern_str,
                    action="kill_signature",
                    evidence_count=total,
                    note=(
                        f"{fails}/{total} failed "
                        f"({fail_rate:.0%})"
                    ),
                )
                kill_ids.append(rule.rule_id)
                proposals += 1
                continue
            if (
                total >= self._min_wins
                and win_rate >= self._win_floor
            ):
                rule = book.propose(
                    origin="pattern_miner",
                    pattern=pattern_str,
                    action="replay_signature",
                    evidence_count=total,
                    note=(
                        f"{total - fails}/{total} wins "
                        f"({win_rate:.0%})"
                    ),
                )
                replay_ids.append(rule.rule_id)
                proposals += 1
        return MiningReport(
            examined=len(events_list),
            unique_signatures=len(buckets),
            proposals_emitted=proposals,
            skipped_low_evidence=skipped,
            kill_proposals=tuple(kill_ids),
            replay_proposals=tuple(replay_ids),
        )
