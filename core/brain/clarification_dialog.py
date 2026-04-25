"""Clarification dialog — detect ambiguous inputs, draft questions.

Owner inputs arrive in natural language and sometimes lack enough
structure to execute. Instead of guessing, the brain should ask one
focused question *before* spending tokens or burning an API call.

Common ambiguity shapes we handle:

  • Missing required slot (e.g. budget: "launch the ad" without $)
  • Pronoun without antecedent ("kill it" — kill what?)
  • Quantifier without unit ("bump it 10" — 10%? dollars? cents?)
  • Underspecified scope ("all products" — which store?)

Each ambiguity yields an ``AmbiguityFinding`` with a drafted question.
A ``ClarificationRequest`` packs the top-priority finding into one
message (we ask one thing at a time; owners are busy). Callers can
mark a request resolved, stamping the answer onto the owner input for
re-processing.

Pure stdlib, deterministic, LLM-free (pattern detection by rules).
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.clarification_dialog")


Kind = Literal[
    "missing_slot", "unresolved_pronoun",
    "missing_unit", "scope_ambiguous",
]


@dataclass
class AmbiguityFinding:
    kind: Kind
    field: str
    evidence: str
    question: str
    priority: int   # 1 = highest

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "field": self.field,
            "evidence": self.evidence,
            "question": self.question,
            "priority": self.priority,
        }


@dataclass
class ClarificationRequest:
    id: str
    original_input: str
    finding: AmbiguityFinding
    status: Literal["open", "answered", "dismissed"]
    created_ts: float
    resolved_ts: float | None = None
    answer: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "original_input": self.original_input,
            "finding": self.finding.as_dict(),
            "status": self.status,
            "created_ts": self.created_ts,
            "resolved_ts": self.resolved_ts,
            "answer": self.answer,
        }


_PRONOUNS = {
    "it", "them", "this", "that", "these", "those", "him", "her",
}

_UNIT_VERBS = {
    "bump", "raise", "lower", "cut", "increase", "decrease",
    "change", "set", "adjust", "shift",
}


def _tokenise(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:\.\d+)?", text.lower())


class ClarificationDialog:
    def __init__(
        self,
        *,
        required_slots: Iterable[str] = (),
        context_resolver: Callable[[str], bool] | None = None,
    ) -> None:
        """``required_slots`` are field names the owner must supply
        (e.g. "budget", "store", "product_id"). ``context_resolver``
        takes a pronoun and returns True if prior context resolves it.
        """
        self._required = tuple(required_slots)
        self._resolver = context_resolver
        self._lock = threading.Lock()
        self._open: dict[str, ClarificationRequest] = {}
        self._closed: dict[str, ClarificationRequest] = {}

    # ── Detection ────────────────────────────────────────

    def find_ambiguities(
        self,
        text: str,
        *,
        provided_slots: dict[str, Any] | None = None,
    ) -> list[AmbiguityFinding]:
        if not text:
            raise ValueError("text required")
        findings: list[AmbiguityFinding] = []
        provided = {k for k, v in (provided_slots or {}).items() if v}
        tokens = _tokenise(text)
        # Required slots
        for slot in self._required:
            if slot in provided:
                continue
            findings.append(AmbiguityFinding(
                kind="missing_slot",
                field=slot,
                evidence=f"slot '{slot}' not provided",
                question=(
                    f"What value should we use for "
                    f"'{slot.replace('_', ' ')}'?"
                ),
                priority=1,
            ))
        # Pronouns
        for token in tokens:
            if token in _PRONOUNS:
                if self._resolver and self._resolver(token):
                    continue
                findings.append(AmbiguityFinding(
                    kind="unresolved_pronoun",
                    field=token,
                    evidence=(
                        f"pronoun '{token}' has no recent referent"
                    ),
                    question=(
                        f"When you say '{token}', which item "
                        f"do you mean?"
                    ),
                    priority=2,
                ))
                break
        # Number-without-unit after a verb like bump/raise
        for i, token in enumerate(tokens):
            if token in _UNIT_VERBS:
                # Look for a number within the next 4 tokens without
                # a unit immediately after.
                window = tokens[i + 1 : i + 5]
                for j, tk in enumerate(window):
                    if re.fullmatch(r"\d+(?:\.\d+)?", tk):
                        nxt = window[j + 1] if j + 1 < len(window) else ""
                        units = {
                            "percent", "%", "dollars", "dollar",
                            "usd", "cents", "units", "orders",
                            "impressions",
                        }
                        if nxt.lower() in units:
                            break
                        findings.append(AmbiguityFinding(
                            kind="missing_unit",
                            field=tk,
                            evidence=(
                                f"'{token} {tk}' has no unit"
                            ),
                            question=(
                                f"Is '{tk}' a percent, a dollar "
                                f"amount, or something else?"
                            ),
                            priority=2,
                        ))
                        break
                break
        # Scope
        scope_hits = {"all", "every", "each", "everything"}
        if any(t in scope_hits for t in tokens):
            if "store" not in provided:
                findings.append(AmbiguityFinding(
                    kind="scope_ambiguous",
                    field="store",
                    evidence="bulk quantifier without store scope",
                    question=(
                        "Which store does 'all' refer to — "
                        "one store or every connected store?"
                    ),
                    priority=3,
                ))
        findings.sort(key=lambda f: f.priority)
        return findings

    # ── Request lifecycle ────────────────────────────────

    def draft(
        self,
        text: str,
        *,
        provided_slots: dict[str, Any] | None = None,
    ) -> ClarificationRequest | None:
        findings = self.find_ambiguities(
            text, provided_slots=provided_slots,
        )
        if not findings:
            return None
        top = findings[0]
        request = ClarificationRequest(
            id=uuid.uuid4().hex,
            original_input=text,
            finding=top,
            status="open",
            created_ts=time.time(),
        )
        with self._lock:
            self._open[request.id] = request
        return request

    def answer(
        self, request_id: str, answer_text: str,
    ) -> ClarificationRequest:
        if not answer_text:
            raise ValueError("answer_text required")
        with self._lock:
            request = self._open.pop(request_id, None)
            if request is None:
                raise ValueError(
                    f"unknown or closed request {request_id!r}",
                )
            request.status = "answered"
            request.answer = answer_text
            request.resolved_ts = time.time()
            self._closed[request_id] = request
            return request

    def dismiss(self, request_id: str) -> ClarificationRequest:
        with self._lock:
            request = self._open.pop(request_id, None)
            if request is None:
                raise ValueError(
                    f"unknown or closed request {request_id!r}",
                )
            request.status = "dismissed"
            request.resolved_ts = time.time()
            self._closed[request_id] = request
            return request

    # ── Queries ──────────────────────────────────────────

    def open_requests(self) -> list[ClarificationRequest]:
        with self._lock:
            return sorted(
                self._open.values(),
                key=lambda r: -r.created_ts,
            )

    def get(self, request_id: str) -> ClarificationRequest | None:
        with self._lock:
            return (
                self._open.get(request_id)
                or self._closed.get(request_id)
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "open": len(self._open),
                "closed": len(self._closed),
                "required_slots": len(self._required),
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._open) + len(self._closed)
            self._open.clear()
            self._closed.clear()
        return n
