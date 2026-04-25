"""Auto-replay coordinator — stub.

Scans the adapter dead-letter queue for entries that could be
retried. The stub returns an empty ``ReplayReport`` so the
controller records a zero-count phase without crashing. Real
implementation would read from the dead-letter store and call a
registered replay callback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReplayReport:
    ready: list[Any] = field(default_factory=list)
    degraded: list[Any] = field(default_factory=list)
    replayed: list[Any] = field(default_factory=list)
    skipped_recent: int = 0
    callback_invocations: int = 0
    callback_failures: int = 0


class _AutoReplayCoordinator:
    def scan(self) -> ReplayReport:
        return ReplayReport()


_COORDINATOR = _AutoReplayCoordinator()


def get_auto_replay_coordinator() -> _AutoReplayCoordinator:
    return _COORDINATOR
