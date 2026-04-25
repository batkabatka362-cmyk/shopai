"""Obsidian feedback learner — stub.

Reads a configured Obsidian vault for down-rated notes and
promotes their patterns into lessons. The stub reports "nothing
learned" so the controller's reflection phase records a no-op
entry instead of crashing on a missing module.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FeedbackReport:
    lessons_written: int = 0
    down_rated: int = 0
    themes_found: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "lessons_written": self.lessons_written,
            "down_rated": self.down_rated,
            "themes_found": self.themes_found,
        }


def learn_from_feedback(vault_path: str) -> FeedbackReport:
    return FeedbackReport()
