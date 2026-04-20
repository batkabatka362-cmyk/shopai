"""Failure taxonomy — categorise failures for pattern matching.

error_pattern_library tracks (signature, remedy, worked). But the
*signature* is opaque text ("shopify:429"). Owners and other
subsystems want coarser buckets:

    ``capacity``   — rate limit / quota exhausted
    ``validation`` — input shape rejected
    ``timeout``    — call exceeded deadline
    ``api``        — remote error we can't help (5xx)
    ``logic``      — our code / state broken
    ``external``   — downstream tool degraded
    ``auth``       — credentials / permission problem

This module classifies a failure by matching patterns (regex +
keyword) against the error message, HTTP status, exception type.
The output is a ``FailureCategory`` with confidence. Aggregated
counts show which category dominates so owners know whether to
invest in capacity (scale out) or logic (bug fix).

Pure stdlib, deterministic. LLM-free.
"""
from __future__ import annotations

import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.failure_taxonomy")


Category = Literal[
    "capacity", "validation", "timeout",
    "api", "logic", "external", "auth", "unknown",
]


@dataclass
class ClassificationRule:
    id: str
    category: Category
    status_codes: tuple[int, ...] = ()
    exception_types: tuple[str, ...] = ()
    message_patterns: tuple[str, ...] = ()
    priority: int = 100     # lower wins

    def matches(
        self,
        *,
        message: str,
        status_code: int | None,
        exception_type: str,
    ) -> bool:
        if status_code is not None and (
            status_code in self.status_codes
        ):
            return True
        if (
            exception_type
            and exception_type in self.exception_types
        ):
            return True
        if message:
            for pat in self.message_patterns:
                if re.search(pat, message, re.IGNORECASE):
                    return True
        return False


@dataclass
class FailureRecord:
    id: str
    category: Category
    rule_id: str
    message: str
    status_code: int | None
    exception_type: str
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "rule_id": self.rule_id,
            "message": self.message,
            "status_code": self.status_code,
            "exception_type": self.exception_type,
            "ts": self.ts,
        }


_DEFAULT_RULES: tuple[ClassificationRule, ...] = (
    ClassificationRule(
        id="r_capacity",
        category="capacity",
        status_codes=(429,),
        message_patterns=(
            r"rate[\- ]?limit",
            r"too many requests",
            r"quota",
        ),
        priority=10,
    ),
    ClassificationRule(
        id="r_timeout",
        category="timeout",
        status_codes=(408, 504),
        exception_types=(
            "TimeoutError", "asyncio.TimeoutError",
        ),
        message_patterns=(
            r"timeout", r"timed? out", r"deadline exceeded",
        ),
        priority=20,
    ),
    ClassificationRule(
        id="r_auth",
        category="auth",
        status_codes=(401, 403),
        message_patterns=(
            r"unauthori[sz]ed",
            r"forbidden",
            r"invalid (?:token|credential)",
            r"access denied",
        ),
        priority=15,
    ),
    ClassificationRule(
        id="r_validation",
        category="validation",
        status_codes=(400, 422),
        exception_types=("ValueError", "TypeError"),
        message_patterns=(
            r"invalid", r"malformed", r"schema",
            r"required field",
        ),
        priority=30,
    ),
    ClassificationRule(
        id="r_api",
        category="api",
        status_codes=(500, 502, 503),
        message_patterns=(
            r"internal server error",
            r"bad gateway",
            r"service unavailable",
        ),
        priority=40,
    ),
    ClassificationRule(
        id="r_external",
        category="external",
        message_patterns=(
            r"downstream", r"upstream", r"unreachable",
            r"connection refused",
        ),
        priority=50,
    ),
    ClassificationRule(
        id="r_logic",
        category="logic",
        exception_types=(
            "AssertionError", "KeyError", "AttributeError",
            "IndexError", "RuntimeError",
        ),
        priority=60,
    ),
)


class FailureTaxonomy:
    def __init__(
        self,
        *,
        rules: Iterable[ClassificationRule] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._rules: list[ClassificationRule] = list(
            rules if rules is not None else _DEFAULT_RULES,
        )
        self._rules.sort(key=lambda r: r.priority)
        self._records: list[FailureRecord] = []
        self._counts: dict[str, int] = defaultdict(int)

    # ── Registry ─────────────────────────────────────────

    def register_rule(self, rule: ClassificationRule) -> None:
        with self._lock:
            self._rules.append(rule)
            self._rules.sort(key=lambda r: r.priority)

    def unregister_rule(self, rule_id: str) -> bool:
        with self._lock:
            before = len(self._rules)
            self._rules = [
                r for r in self._rules if r.id != rule_id
            ]
            return len(self._rules) < before

    # ── Classify ─────────────────────────────────────────

    def classify(
        self,
        *,
        message: str = "",
        status_code: int | None = None,
        exception_type: str = "",
        ts: float | None = None,
    ) -> FailureRecord:
        import time
        import uuid
        timestamp = float(ts if ts is not None else time.time())
        with self._lock:
            rules = list(self._rules)
        chosen: ClassificationRule | None = None
        for rule in rules:
            try:
                if rule.matches(
                    message=message,
                    status_code=status_code,
                    exception_type=exception_type,
                ):
                    chosen = rule
                    break
            except Exception as exc:
                logger.debug(
                    "rule %s matches raised: %s",
                    rule.id, exc,
                )
                continue
        if chosen is None:
            record = FailureRecord(
                id=uuid.uuid4().hex,
                category="unknown",
                rule_id="",
                message=str(message),
                status_code=status_code,
                exception_type=str(exception_type),
                ts=timestamp,
            )
        else:
            record = FailureRecord(
                id=uuid.uuid4().hex,
                category=chosen.category,
                rule_id=chosen.id,
                message=str(message),
                status_code=status_code,
                exception_type=str(exception_type),
                ts=timestamp,
            )
        with self._lock:
            self._records.append(record)
            self._counts[record.category] += 1
            if len(self._records) > 1000:
                del self._records[
                    : len(self._records) - 1000
                ]
        return record

    # ── Queries ──────────────────────────────────────────

    def counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def dominant_category(self) -> str | None:
        with self._lock:
            if not self._counts:
                return None
            return max(
                self._counts.items(), key=lambda kv: kv[1],
            )[0]

    def recent(
        self, *, limit: int = 20,
    ) -> list[FailureRecord]:
        with self._lock:
            return list(
                self._records[-max(1, int(limit)):],
            )

    def rules(self) -> list[ClassificationRule]:
        with self._lock:
            return list(self._rules)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total": len(self._records),
                "by_category": dict(self._counts),
                "dominant": self.dominant_category(),
                "rules": len(self._rules),
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._records)
            self._records.clear()
            self._counts.clear()
        return n
