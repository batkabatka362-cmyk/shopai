"""Brain state synthesizer — holistic snapshot + priorities.

Track 9 of AGI_HARDENING_PLAN. Sprint 3 + hardening Tracks 1-8
shipped ~50 brain modules each with its own ``stats()``. The
owner shouldn't have to run ``shopai risk`` + ``shopai memory``
+ ``shopai trust`` + ``shopai brain-learned`` + ``shopai crisis``
just to know "how's my autonomous system doing today?"

This synthesizer pulls all signals into one BrainState snapshot
with a derived priority list — the three things the owner
should pay attention to right now, ranked.

Priorities are rule-based, deterministic:

  * ``crisis.red`` → top priority every time.
  * ``tripwire.utilisation > 0.8`` → "approaching daily cap".
  * ``rulebook.proposed > 5 and active == 0`` → "proposals need
    review" (owner is the bottleneck for adoption).
  * ``consolidator.stale_archived > 0`` → "memory growth stalled".
  * ``trust.ranked()[0] < 0.3`` → "top source is weak".
  * ``rationale.total == 0`` → "no decisions recorded yet".

All signals are dependency-injected so tests run offline and the
synthesizer never hard-couples to a specific module version.

Pure stdlib. Deterministic. Thread-safe (RLock).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("core.brain.brain_state_synthesizer")


@dataclass
class PriorityItem:
    level: str                # "critical" | "warning" | "info"
    code: str
    message: str
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass
class BrainState:
    ts: float
    crisis_level: str
    halted: bool
    tripwire_utilisation: float
    tripwire_remaining_usd: float
    rule_counts: dict[str, int]
    memory_counts: dict[str, int]
    trust_top: tuple[tuple[str, float], ...]
    rationale_total: int
    priorities: tuple[PriorityItem, ...]
    notes: tuple[str, ...] = ()
    # Wave A-B-D snapshot fields (default empty so existing
    # callers that construct BrainState directly keep working).
    agentic_enabled_channels: tuple[str, ...] = ()
    moby_win_rate: dict[str, Any] = field(default_factory=dict)
    fal_weekly_spend_usd: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "crisis_level": self.crisis_level,
            "halted": self.halted,
            "tripwire_utilisation": round(
                self.tripwire_utilisation, 4,
            ),
            "tripwire_remaining_usd": round(
                self.tripwire_remaining_usd, 2,
            ),
            "rule_counts": dict(self.rule_counts),
            "memory_counts": dict(self.memory_counts),
            "trust_top": [
                {"source": s, "trust": round(t, 4)}
                for s, t in self.trust_top
            ],
            "rationale_total": self.rationale_total,
            "priorities": [
                p.as_dict() for p in self.priorities
            ],
            "notes": list(self.notes),
            "agentic_enabled_channels": list(
                self.agentic_enabled_channels,
            ),
            "moby_win_rate": dict(self.moby_win_rate),
            "fal_weekly_spend_usd": round(
                self.fal_weekly_spend_usd, 4,
            ),
        }


_LEVEL_ORDER = {
    "critical": 0, "warning": 1, "info": 2,
}


class BrainStateSynthesizer:
    """Holistic cross-module snapshot + priority derivation."""

    def __init__(
        self,
        *,
        crisis_responder: Any = None,
        risk_tripwire: Any = None,
        rulebook: Any = None,
        memory_consolidator: Any = None,
        trust_calibrator: Any = None,
        rationale_ledger: Any = None,
        now_fn: Any = None,
    ) -> None:
        self._lock = threading.RLock()
        self._crisis = crisis_responder
        self._tripwire = risk_tripwire
        self._rulebook = rulebook
        self._consolidator = memory_consolidator
        self._trust = trust_calibrator
        self._rationale = rationale_ledger
        self._now_fn = now_fn or time.time

    # ── Lazy singletons ──────────────────────────────────

    def _get_crisis(self) -> Any:
        if self._crisis is None:
            try:
                from core.crisis.response import (
                    get_crisis_responder,
                )
                self._crisis = get_crisis_responder()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "crisis resp load: %s", exc,
                )
        return self._crisis

    def _get_tripwire(self) -> Any:
        if self._tripwire is None:
            try:
                from core.risk.tripwire import (
                    get_risk_tripwire,
                )
                self._tripwire = get_risk_tripwire()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "tripwire load: %s", exc,
                )
        return self._tripwire

    def _get_rulebook(self) -> Any:
        if self._rulebook is None:
            try:
                from core.learning.rulebook import (
                    get_rulebook,
                )
                self._rulebook = get_rulebook()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "rulebook load: %s", exc,
                )
        return self._rulebook

    def _get_consolidator(self) -> Any:
        if self._consolidator is None:
            try:
                from core.memory.consolidator import (
                    get_consolidator,
                )
                self._consolidator = get_consolidator()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "consolidator load: %s", exc,
                )
        return self._consolidator

    def _get_trust(self) -> Any:
        if self._trust is None:
            try:
                from core.data.source_trust_calibrator import (
                    get_calibrator,
                )
                self._trust = get_calibrator()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "trust load: %s", exc,
                )
        return self._trust

    def _get_rationale(self) -> Any:
        if self._rationale is None:
            try:
                from core.decision.rationale_ledger import (
                    get_rationale_ledger,
                )
                self._rationale = get_rationale_ledger()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "rationale load: %s", exc,
                )
        return self._rationale

    # ── Synthesis ────────────────────────────────────────

    def snapshot(self) -> BrainState:
        notes: list[str] = []
        # Crisis
        crisis_level = "unknown"
        halted = False
        crisis = self._get_crisis()
        if crisis is not None:
            try:
                state = crisis.detect_state()
                crisis_level = state.level
                halted = state.halted
            except Exception as exc:  # noqa: BLE001
                notes.append(f"crisis read: {exc}")
        # Tripwire
        util = 0.0
        remaining = 0.0
        tripwire = self._get_tripwire()
        if tripwire is not None:
            try:
                s = tripwire.status()
                util = float(
                    s.get("today", {}).get(
                        "utilisation", 0.0,
                    ),
                )
                remaining = float(
                    s.get("today", {}).get(
                        "remaining_usd", 0.0,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                notes.append(f"tripwire read: {exc}")
        # Rulebook
        rule_counts: dict[str, int] = {}
        book = self._get_rulebook()
        if book is not None:
            try:
                stats = book.stats()
                rule_counts = dict(
                    stats.get("by_status") or {},
                )
            except Exception as exc:  # noqa: BLE001
                notes.append(f"rulebook read: {exc}")
        # Memory
        mem_counts: dict[str, int] = {}
        consolidator = self._get_consolidator()
        if consolidator is not None:
            try:
                mstats = consolidator.stats()
                mem_counts = {
                    k: int(mstats.get(k, 0) or 0)
                    for k in (
                        "episodes", "concepts",
                        "procedures", "cold_archive",
                    )
                }
            except Exception as exc:  # noqa: BLE001
                notes.append(f"memory read: {exc}")
        # Trust
        trust_top: list[tuple[str, float]] = []
        trust = self._get_trust()
        if trust is not None:
            try:
                trust_top = list(trust.ranked())[:5]
            except Exception as exc:  # noqa: BLE001
                notes.append(f"trust read: {exc}")
        # Rationale
        rationale_total = 0
        rationale = self._get_rationale()
        if rationale is not None:
            try:
                rationale_total = int(
                    rationale.stats().get(
                        "total_rationales", 0,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                notes.append(f"rationale read: {exc}")

        priorities = self._derive_priorities(
            crisis_level=crisis_level,
            halted=halted,
            tripwire_utilisation=util,
            rule_counts=rule_counts,
            memory_counts=mem_counts,
            trust_top=trust_top,
            rationale_total=rationale_total,
        )
        # Wave A-B-D rollup: agentic channels, moby trust,
        # fal video budget. Each is best-effort — a failing
        # source only adds a note, never blocks the snapshot.
        agentic_channels = self._collect_agentic(notes)
        moby_rate = self._collect_moby(notes)
        fal_spend = self._collect_fal(notes)

        return BrainState(
            ts=float(self._now_fn()),
            crisis_level=crisis_level,
            halted=halted,
            tripwire_utilisation=util,
            tripwire_remaining_usd=remaining,
            rule_counts=rule_counts,
            memory_counts=mem_counts,
            trust_top=tuple(trust_top),
            rationale_total=rationale_total,
            priorities=tuple(priorities),
            notes=tuple(notes),
            agentic_enabled_channels=tuple(agentic_channels),
            moby_win_rate=moby_rate,
            fal_weekly_spend_usd=fal_spend,
        )

    # ── Wave A-B-D collectors (all best-effort) ──────────

    @staticmethod
    def _collect_agentic(notes: list[str]) -> list[str]:
        """Return the list of enabled agentic channels. Silent
        on missing bridge (returns [])."""
        try:
            from core.bridge.agentic_storefront import (
                get_agentic_bridge,
            )
            statuses = get_agentic_bridge().status()
        except Exception as exc:  # noqa: BLE001
            notes.append(f"agentic bridge: {exc}")
            return []
        return [
            s.channel for s in statuses
            if bool(getattr(s, "enabled", False))
        ]

    @staticmethod
    def _collect_moby(notes: list[str]) -> dict[str, Any]:
        try:
            from core.brain.moby_vote_comparator import (
                get_moby_vote_comparator,
            )
            return (
                get_moby_vote_comparator().win_rate()
                or {}
            )
        except Exception as exc:  # noqa: BLE001
            notes.append(f"moby comparator: {exc}")
            return {}

    @staticmethod
    def _collect_fal(notes: list[str]) -> float:
        """Return ``total_spend_usd`` across all SKUs. That
        gives the operator a weekly burn number at a glance."""
        try:
            from core.adapters.fal.video_router import (
                FalVideoRouter,
            )
            router = FalVideoRouter()
            try:
                stats = router.stats()
            finally:
                router.close()
            return float(
                stats.get("total_spend_usd", 0) or 0,
            )
        except Exception as exc:  # noqa: BLE001
            notes.append(f"fal router: {exc}")
            return 0.0

    def _derive_priorities(
        self,
        *,
        crisis_level: str,
        halted: bool,
        tripwire_utilisation: float,
        rule_counts: dict[str, int],
        memory_counts: dict[str, int],
        trust_top: list[tuple[str, float]],
        rationale_total: int,
    ) -> list[PriorityItem]:
        priorities: list[PriorityItem] = []
        if crisis_level == "red" or halted:
            priorities.append(PriorityItem(
                level="critical",
                code="crisis_red",
                message="Autopilot halted — crisis active.",
                detail=(
                    "Run `shopai crisis status` then "
                    "`shopai crisis events` for details."
                ),
            ))
        if tripwire_utilisation >= 0.8:
            priorities.append(PriorityItem(
                level="warning",
                code="tripwire_high",
                message=(
                    f"Daily ad spend at "
                    f"{tripwire_utilisation:.0%} of cap."
                ),
                detail="Risk of hitting the daily cap soon.",
            ))
        proposed = int(rule_counts.get("proposed", 0) or 0)
        active = int(rule_counts.get("active", 0) or 0)
        if proposed >= 5 and active == 0:
            priorities.append(PriorityItem(
                level="warning",
                code="rules_unreviewed",
                message=(
                    f"{proposed} learned rules waiting for "
                    "owner review."
                ),
                detail=(
                    "Use `shopai brain-learned list "
                    "--status proposed` to inspect."
                ),
            ))
        if (
            memory_counts.get("cold_archive", 0) > 0
            and memory_counts.get("concepts", 0) == 0
        ):
            priorities.append(PriorityItem(
                level="warning",
                code="memory_stalled",
                message=(
                    "All semantic concepts archived — "
                    "memory growth stalled."
                ),
                detail=(
                    "Check if autopilot is running via "
                    "`shopai autopilot` or run "
                    "`shopai memory consolidate`."
                ),
            ))
        if trust_top and trust_top[0][1] < 0.3:
            name, score = trust_top[0]
            priorities.append(PriorityItem(
                level="warning",
                code="trust_weak",
                message=(
                    f"Top-ranked source '{name}' trust "
                    f"only {score:.0%}."
                ),
                detail=(
                    "Consider adjusting baselines via "
                    "`shopai trust baseline`."
                ),
            ))
        if rationale_total == 0:
            priorities.append(PriorityItem(
                level="info",
                code="rationale_empty",
                message="No decisions recorded yet.",
                detail=(
                    "Run `shopai autopilot` to generate a "
                    "first decision trail."
                ),
            ))
        # Sort critical > warning > info, then stable by code
        priorities.sort(
            key=lambda p: (
                _LEVEL_ORDER.get(p.level, 99),
                p.code,
            ),
        )
        return priorities


# ── Singleton ───────────────────────────────────────────────

_SINGLETON: BrainStateSynthesizer | None = None
_SINGLETON_LOCK = threading.Lock()


def get_brain_state_synthesizer() -> BrainStateSynthesizer:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = BrainStateSynthesizer()
    return _SINGLETON


def reset_brain_state_synthesizer_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = None
