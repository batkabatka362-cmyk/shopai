"""Autobiographical narrative — the store tells its own story.

Memory stores *what happened*. Metacognition scores how the brain
itself is doing. Neither produces the kind of running story a
human operator has about their store: "last week we tried luxury
tone on audio, it flopped, but the gardening scale-up paid off".

narrative.compose_week() walks the last 7 days of memory and
assembles a structured weekly story:

  • *Wins* — launches that scaled, rules that converted, owner
    praise events.
  • *Setbacks* — kills, down-votes, refunds.
  • *Lessons* — rules promoted to level-3 strategies this week,
    with source counts.
  • *Bets* — hypotheses registered or resolved this week.
  • *Open loops* — overdue hypotheses, stalled goals, unresolved
    contradictions.

Output is a ``Story`` dataclass that renders both a structured
dict (for the dashboard) and a human markdown digest (for the
owner). Zero LLM — an optional ``narrator`` callable can be
passed in for LLM polishing, but the baseline output is already
readable.

Run weekly via ``compose_week()``. Persisted as a ``category=
narrative level=2 score=4.0`` memory event so retrieval can quote
"last week's digest said we shouldn't push luxury tone on audio
again" when adjacent decisions come up.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from utils.logger import get_logger


logger = get_logger("brain.narrative")

_DB_PATH = Path("data/memory_intelligence.db")
_WEEK_S = 7 * 86_400


@dataclass
class StoryItem:
    kind: str                     # win | setback | lesson | bet | open
    headline: str
    detail: str = ""
    memory_id: int | None = None
    score: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "headline": self.headline,
            "detail": self.detail,
            "memory_id": self.memory_id,
            "score": round(self.score, 2),
        }


@dataclass
class Story:
    period: str                   # e.g. "2026-04-13..2026-04-19"
    generated_at: float = field(default_factory=time.time)
    wins: list[StoryItem] = field(default_factory=list)
    setbacks: list[StoryItem] = field(default_factory=list)
    lessons: list[StoryItem] = field(default_factory=list)
    bets: list[StoryItem] = field(default_factory=list)
    open_loops: list[StoryItem] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "generated_at": self.generated_at,
            "wins": [x.as_dict() for x in self.wins],
            "setbacks": [x.as_dict() for x in self.setbacks],
            "lessons": [x.as_dict() for x in self.lessons],
            "bets": [x.as_dict() for x in self.bets],
            "open_loops": [x.as_dict() for x in self.open_loops],
            "totals": {
                "wins": len(self.wins),
                "setbacks": len(self.setbacks),
                "lessons": len(self.lessons),
                "bets": len(self.bets),
                "open_loops": len(self.open_loops),
            },
        }

    def to_markdown(self) -> str:
        """Human-readable weekly digest."""
        lines = [f"# ShopAI weekly narrative — {self.period}", ""]
        sections = [
            ("Wins",       self.wins,     ":white_check_mark:"),
            ("Setbacks",   self.setbacks, ":warning:"),
            ("Lessons",    self.lessons,  ":book:"),
            ("Bets",       self.bets,     ":game_die:"),
            ("Open loops", self.open_loops, ":mag:"),
        ]
        for title, items, _emoji in sections:
            lines.append(f"## {title}")
            if not items:
                lines.append("  _(nothing this week)_")
            else:
                for it in items:
                    bullet = f"- **{it.headline}**"
                    if it.detail:
                        bullet += f" — {it.detail}"
                    lines.append(bullet)
            lines.append("")
        return "\n".join(lines)


# ── Public API ──────────────────────────────────────────────

def compose_week(
    db_path: Path | str | None = None,
    now: float | None = None,
    narrator: Callable[[Story], str] | None = None,
) -> Story:
    """Walk the last 7 days of memory, synthesise the weekly story.

    ``narrator`` is an optional callable that returns polished prose
    given the structured story — useful when an LLM is configured.
    """
    db = Path(db_path) if db_path else _DB_PATH
    cutoff = (now or time.time()) - _WEEK_S
    story = Story(period=_period_label(cutoff, now or time.time()))
    if not db.exists():
        return story
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT id, category, action, score, level, content "
            "FROM memories WHERE timestamp >= ? "
            "ORDER BY timestamp ASC",
            (cutoff,),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        logger.debug("narrative fetch failed: %s", exc)
        conn.close()
        return story
    finally:
        try:
            conn.close()
        except Exception as exc:
            logger.debug("narrative conn close: %s", exc)

    for mid, cat, action, score, level, content in rows:
        item = _categorise_row(mid, cat, action, score, level, content)
        if item is None:
            continue
        bucket = getattr(story, _bucket_for(item.kind))
        bucket.append(item)

    # Keep the digest tight: top 5 per bucket by score.
    _trim(story)
    if narrator:
        try:
            narrator(story)   # side-effect only: may enrich in place
        except Exception as exc:
            logger.debug("narrator callback failed: %s", exc)
    _persist(story)
    return story


# ── Row → item classification ──────────────────────────────

def _categorise_row(
    mid: int, cat: str, action: str, score: float,
    level: int, content: str | None,
) -> StoryItem | None:
    content_obj = _parse_content(content)
    headline = _headline_from(cat, action, content_obj)
    score = float(score or 0.0)
    level = int(level or 0)

    # Wins
    if cat == "launch" and action == "scaled":
        return StoryItem("win", headline,
                         detail=f"scaled from cycle {content_obj.get('cycle', '?')}",
                         memory_id=mid, score=score)
    if cat == "feedback" and _is_up_vote(content_obj):
        return StoryItem("win", headline,
                         detail="owner up-vote",
                         memory_id=mid, score=score)
    if cat == "order":
        return StoryItem("win", headline,
                         detail=f"order memorised",
                         memory_id=mid, score=score)

    # Setbacks
    if cat == "launch" and action == "killed":
        return StoryItem("setback", headline,
                         detail=f"killed (ROAS too low)",
                         memory_id=mid, score=score)
    if cat == "feedback" and _is_down_vote(content_obj):
        return StoryItem("setback", headline,
                         detail="owner down-vote",
                         memory_id=mid, score=score)
    if cat == "refund":
        return StoryItem("setback", headline,
                         detail="refund processed",
                         memory_id=mid, score=score)

    # Lessons
    if cat == "transfer_strategy":
        return StoryItem("lesson", headline,
                         detail="cross-niche pattern mined",
                         memory_id=mid, score=score)
    if level >= 3 and cat not in ("order", "launch"):
        return StoryItem("lesson", headline,
                         detail=f"promoted to strategy",
                         memory_id=mid, score=score)

    # Bets
    if cat == "hypothesis":
        return StoryItem("bet", headline,
                         detail=f"verdict={action}",
                         memory_id=mid, score=score)

    # Open loops
    if cat == "contradiction":
        return StoryItem("open", headline,
                         detail="contradiction unresolved",
                         memory_id=mid, score=score)
    if cat == "goal_status" and action == "transition_paused":
        return StoryItem("open", headline,
                         detail="goal paused",
                         memory_id=mid, score=score)
    return None


def _parse_content(content: str | None) -> dict[str, Any]:
    if not content:
        return {}
    try:
        obj = json.loads(content)
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _is_up_vote(content: dict[str, Any]) -> bool:
    return int(content.get("sign", 0)) > 0


def _is_down_vote(content: dict[str, Any]) -> bool:
    return int(content.get("sign", 0)) < 0


def _headline_from(
    cat: str, action: str, content: dict[str, Any],
) -> str:
    if "launch_id" in content:
        return f"{cat}:{action} — launch {content['launch_id']}"
    if "subject" in content:
        return f"{cat}:{action} — {content['subject']}"
    if "niche" in content:
        return f"{cat}:{action} — {content['niche']}"
    return f"{cat}:{action}"


def _bucket_for(kind: str) -> str:
    return {
        "win": "wins",
        "setback": "setbacks",
        "lesson": "lessons",
        "bet": "bets",
        "open": "open_loops",
    }[kind]


def _trim(story: Story, per_bucket: int = 5) -> None:
    for field_name in ("wins", "setbacks", "lessons", "bets", "open_loops"):
        items = getattr(story, field_name)
        items.sort(key=lambda x: -x.score)
        setattr(story, field_name, items[:per_bucket])


def _period_label(start_s: float, end_s: float) -> str:
    import datetime as dt
    s = dt.datetime.utcfromtimestamp(start_s).date().isoformat()
    e = dt.datetime.utcfromtimestamp(end_s).date().isoformat()
    return f"{s}..{e}"


def _persist(story: Story) -> None:
    try:
        from core.memory.unified_memory import get_unified_memory
        mi = get_unified_memory().get_memory_intelligence()
        mi.create(
            category="narrative",
            content=story.as_dict(),
            action="weekly_digest",
            score=4.0,
            memory_type="semantic",
            tags=["narrative", "weekly", story.period],
        )
    except Exception as exc:
        logger.debug("narrative persist failed: %s", exc)
