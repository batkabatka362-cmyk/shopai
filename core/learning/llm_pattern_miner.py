"""LLM-assisted pattern miner — fuzzy patterns beyond the lexicon.

User request B. ``core/learning/pattern_miner`` does the
deterministic part — buckets by (capability, kpi, kpi_band, ok)
and emits RuleBook proposals for bucket-level patterns. That's
cheap, bias-free, and catches the easy cases.

This module layers an LLM *on top* for the fuzzy cases the
lexicon can't see — patterns that depend on free-form context
fields ("launches where ad copy uses 'luxury' tone and price >
$40 tend to underperform"). The LLM never replaces the
deterministic miner; it runs *after* and only on events the
deterministic miner flagged as unexplained.

Contract (LLM-agnostic):

  * Caller supplies an ``llm_client`` — a zero-arg-callable
    that takes a prompt string and returns a response string.
    Any model works: Groq/Gemini/DeepSeek/local Ollama.
  * Response shape the miner expects:

        PATTERN: <free-form pattern text>
        ACTION: kill|replay|hold
        EVIDENCE: <integer>
        CONFIDENCE: <0..1>
        (blank line between proposals)

  * A regex parser tolerates minor drift. Anything outside the
    shape is skipped with a `notes` entry — never raises.

Safety & budget:

  * ``call_cost_usd_cap`` — refuses to call if declared LLM cost
    would exceed the cap in a single sweep.
  * ``calls_per_sweep_cap`` — hard ceiling on LLM round-trips.
  * Every proposal still flows through RuleBook.propose() so
    the owner retains veto via 'shopai brain-learned list
    --status proposed'.
  * The whole module is a *no-op* when llm_client is None —
    callers get back an empty report and zero cost.

Pure stdlib. Thread-safe (Lock). Deterministic given fixed
llm_client responses.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("core.learning.llm_pattern_miner")


LLMClient = Callable[[str], str]


_DEFAULT_CALL_CAP = 5
_DEFAULT_COST_CAP_USD = 0.05
_DEFAULT_BATCH_SIZE = 30

_PROPOSAL_RE = re.compile(
    r"PATTERN:\s*(?P<pattern>.+?)\n"
    r"ACTION:\s*(?P<action>kill|replay|hold)\b.*?\n"
    r"EVIDENCE:\s*(?P<evidence>\d+).*?\n"
    r"CONFIDENCE:\s*(?P<confidence>[\d.]+)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class LLMProposal:
    pattern: str
    action: str            # "kill" | "replay" | "hold"
    evidence: int
    confidence: float
    rule_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "action": self.action,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 4),
            "rule_id": self.rule_id,
        }


@dataclass
class LLMMiningReport:
    examined: int
    llm_calls: int
    cost_usd: float
    proposals_emitted: int
    proposals: tuple[LLMProposal, ...] = ()
    notes: tuple[str, ...] = ()
    skipped_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "examined": self.examined,
            "llm_calls": self.llm_calls,
            "cost_usd": round(self.cost_usd, 5),
            "proposals_emitted": self.proposals_emitted,
            "proposals": [
                p.as_dict() for p in self.proposals
            ],
            "notes": list(self.notes),
            "skipped_reason": self.skipped_reason,
        }


_PROMPT_TEMPLATE = (
    "You are a pattern-detection assistant for an "
    "e-commerce autopilot. I'll give you {n} outcome "
    "events; you find up to 3 patterns the deterministic "
    "miner missed.\n\n"
    "Each event is a dict with fields:\n"
    "  - engine, kpi, kpi_value, ok (bool), context (dict)\n\n"
    "Respond with 0..3 proposals in this exact format:\n\n"
    "PATTERN: <text describing the rule scope>\n"
    "ACTION: kill|replay|hold\n"
    "EVIDENCE: <integer event count>\n"
    "CONFIDENCE: <float 0..1>\n\n"
    "Events:\n"
    "{events_json}\n"
)


def _default_cost_estimator(n_events: int) -> float:
    """Rough token-based cost estimate — caller can override."""
    # Assume ~120 tokens per event + 500 overhead; at Groq
    # Llama 3.3 70B rate ~ $0.0008 / 1k tokens.
    tokens = 500 + n_events * 120
    return (tokens / 1000.0) * 0.0008


def parse_llm_proposals(
    raw: str,
) -> tuple[list[LLMProposal], list[str]]:
    """Parse the LLM response into proposals + skip notes."""
    proposals: list[LLMProposal] = []
    notes: list[str] = []
    if not raw:
        notes.append("empty response")
        return proposals, notes
    matches = list(_PROPOSAL_RE.finditer(raw))
    if not matches:
        notes.append("no proposals found in response")
        return proposals, notes
    for m in matches:
        try:
            evidence = int(m.group("evidence"))
            conf = float(m.group("confidence"))
        except (TypeError, ValueError) as exc:
            notes.append(
                f"parse error on match: {exc}",
            )
            continue
        if evidence < 1 or not 0.0 <= conf <= 1.0:
            notes.append(
                "rejected: evidence ≥ 1 and confidence "
                "∈ [0, 1]",
            )
            continue
        pattern = m.group("pattern").strip()
        action = m.group("action").strip().lower()
        if not pattern:
            notes.append("rejected: empty pattern")
            continue
        proposals.append(LLMProposal(
            pattern=pattern,
            action=action,
            evidence=evidence,
            confidence=conf,
        ))
    return proposals, notes


class LLMPatternMiner:
    """LLM-assisted fuzzy pattern miner."""

    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        rulebook: Any = None,
        call_cost_usd_cap: float = _DEFAULT_COST_CAP_USD,
        calls_per_sweep_cap: int = _DEFAULT_CALL_CAP,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        cost_estimator: Callable[[int], float] | None = (
            None
        ),
        min_confidence_for_propose: float = 0.6,
    ) -> None:
        if call_cost_usd_cap < 0:
            raise ValueError(
                "call_cost_usd_cap must be ≥ 0",
            )
        if calls_per_sweep_cap < 1:
            raise ValueError(
                "calls_per_sweep_cap must be ≥ 1",
            )
        if batch_size < 1:
            raise ValueError("batch_size must be ≥ 1")
        if not 0.0 <= min_confidence_for_propose <= 1.0:
            raise ValueError(
                "min_confidence_for_propose must be "
                "in [0, 1]",
            )
        self._lock = threading.Lock()
        self._client = llm_client
        self._rulebook = rulebook
        self._cost_cap = float(call_cost_usd_cap)
        self._call_cap = int(calls_per_sweep_cap)
        self._batch = int(batch_size)
        self._cost_fn = (
            cost_estimator or _default_cost_estimator
        )
        self._min_conf = float(min_confidence_for_propose)

    def _get_rulebook(self) -> Any:
        if self._rulebook is not None:
            return self._rulebook
        try:
            from core.learning.rulebook import get_rulebook
            self._rulebook = get_rulebook()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "rulebook lazy load: %s", exc,
            )
        return self._rulebook

    def mine(
        self,
        events: Iterable[dict[str, Any]],
    ) -> LLMMiningReport:
        events_list = list(events or [])
        if self._client is None:
            return LLMMiningReport(
                examined=len(events_list),
                llm_calls=0,
                cost_usd=0.0,
                proposals_emitted=0,
                skipped_reason="no_llm_client",
            )
        if not events_list:
            return LLMMiningReport(
                examined=0,
                llm_calls=0,
                cost_usd=0.0,
                proposals_emitted=0,
                skipped_reason="no_events",
            )
        notes: list[str] = []
        all_props: list[LLMProposal] = []
        total_cost = 0.0
        calls = 0
        # Chunk the events so a giant buffer doesn't blow the
        # prompt window. Every chunk is its own LLM call subject
        # to the shared budget.
        for start in range(
            0, len(events_list), self._batch,
        ):
            if calls >= self._call_cap:
                notes.append(
                    "hit calls_per_sweep_cap",
                )
                break
            chunk = events_list[
                start: start + self._batch
            ]
            est = self._cost_fn(len(chunk))
            if total_cost + est > self._cost_cap:
                notes.append(
                    f"cost cap reached at "
                    f"${total_cost:.4f}; skipping "
                    f"remaining chunks",
                )
                break
            prompt = _PROMPT_TEMPLATE.format(
                n=len(chunk),
                events_json=json.dumps(
                    chunk, sort_keys=True,
                ),
            )
            try:
                raw = self._client(prompt)
            except Exception as exc:  # noqa: BLE001
                notes.append(
                    f"llm_client raised: {exc}",
                )
                continue
            calls += 1
            total_cost += est
            parsed, sub_notes = parse_llm_proposals(
                raw,
            )
            notes.extend(sub_notes)
            for prop in parsed:
                if prop.confidence < self._min_conf:
                    notes.append(
                        f"skipped low-confidence "
                        f"{prop.confidence:.2f}",
                    )
                    continue
                all_props.append(prop)
        # Push accepted proposals into the RuleBook
        emitted = 0
        book = self._get_rulebook()
        for prop in all_props:
            if book is None:
                emitted += 1
                continue
            try:
                rule = book.propose(
                    origin="llm_pattern_miner",
                    pattern=prop.pattern,
                    action=(
                        "kill_signature"
                        if prop.action == "kill"
                        else "replay_signature"
                        if prop.action == "replay"
                        else "hold_signature"
                    ),
                    evidence_count=prop.evidence,
                    note=(
                        f"confidence="
                        f"{prop.confidence:.2f}"
                    ),
                )
                prop.rule_id = rule.rule_id
                emitted += 1
            except Exception as exc:  # noqa: BLE001
                notes.append(
                    f"rulebook.propose raised: {exc}",
                )
        return LLMMiningReport(
            examined=len(events_list),
            llm_calls=calls,
            cost_usd=total_cost,
            proposals_emitted=emitted,
            proposals=tuple(all_props),
            notes=tuple(notes),
        )
