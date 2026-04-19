"""Inner monologue — thought-stream trace for introspection.

Decision traces (v4) record *the* verdict and *the* evidence. An
inner monologue is different: it's a running log of the brain's
incremental thoughts while it deliberates — hypotheses tried and
discarded, analogies considered, cells of working memory flagged
relevant, tentative conclusions overturned.

Why this matters: humans who can remember their chain of thought
catch self-contradictions earlier, explain decisions faster, and
learn from *how* they reasoned, not just what they concluded.

Monologue is a cycle-scoped stream with:

  • ``say(speaker, thought)`` — append one inner utterance.
  • ``aside(metadata)`` — attach structured data to the last line.
  • ``checkpoint(label)`` — name a moment so replays can fast-
    forward to it.
  • ``dump()`` — structured transcript for the dashboard.
  • ``render_markdown()`` — human-readable recap for explainability.

Speakers are free-form strings (``planner``, ``debate.bull``,
``reward_model``, ``ethics``). The log is bounded by
``max_entries`` to stay cheap; oldest entries fall off.

Thread-safe singleton (per cycle). Not persisted — if the cycle
wants to keep the monologue, ``dump()`` is called and written to
memory as ``category=monologue score=3.5`` by the caller.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable


_DEFAULT_MAX = 500


@dataclass
class Utterance:
    seq: int
    ts: float
    speaker: str
    thought: str
    aside: dict[str, Any] = field(default_factory=dict)
    checkpoint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "speaker": self.speaker,
            "thought": self.thought,
            "aside": self.aside,
            "checkpoint": self.checkpoint,
        }


# ── Monologue ───────────────────────────────────────────────

class InnerMonologue:
    def __init__(self, max_entries: int = _DEFAULT_MAX) -> None:
        self._max = int(max_entries)
        self._entries: deque[Utterance] = deque(maxlen=self._max)
        self._lock = threading.RLock()
        self._seq = 0

    # ── Writing ─────────────────────────────────────────────

    def say(self, speaker: str, thought: str) -> int:
        with self._lock:
            self._seq += 1
            self._entries.append(Utterance(
                seq=self._seq, ts=time.time(),
                speaker=speaker.strip(), thought=thought.strip(),
            ))
            return self._seq

    def aside(self, data: dict[str, Any]) -> bool:
        """Attach structured metadata to the most recent utterance."""
        with self._lock:
            if not self._entries:
                return False
            last = self._entries[-1]
            last.aside = {**last.aside, **data}
            return True

    def checkpoint(self, label: str) -> int:
        """Emit a named marker so replays can skip to it."""
        with self._lock:
            self._seq += 1
            self._entries.append(Utterance(
                seq=self._seq, ts=time.time(),
                speaker="system", thought=f"checkpoint: {label}",
                checkpoint=label.strip(),
            ))
            return self._seq

    def reset(self) -> int:
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
            self._seq = 0
            return n

    # ── Reading ─────────────────────────────────────────────

    def entries(
        self,
        speaker: str | None = None,
        since_seq: int = 0,
    ) -> list[Utterance]:
        with self._lock:
            items = list(self._entries)
        if speaker:
            items = [u for u in items if u.speaker == speaker]
        if since_seq:
            items = [u for u in items if u.seq > since_seq]
        return items

    def since_checkpoint(self, label: str) -> list[Utterance]:
        """Everything said *after* the checkpoint labelled ``label``."""
        with self._lock:
            items = list(self._entries)
        cp_seq: int | None = None
        for u in items:
            if u.checkpoint == label:
                cp_seq = u.seq
                break
        if cp_seq is None:
            return []
        return [u for u in items if u.seq > cp_seq]

    def speakers(self) -> list[str]:
        with self._lock:
            return sorted({u.speaker for u in self._entries})

    def dump(self) -> list[dict[str, Any]]:
        return [u.as_dict() for u in self.entries()]

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    # ── Rendering ──────────────────────────────────────────

    def render_markdown(
        self, max_lines: int = 50, speakers: Iterable[str] | None = None,
    ) -> str:
        items = self.entries()
        if speakers:
            wanted = set(speakers)
            items = [u for u in items if u.speaker in wanted]
        items = items[-max_lines:]
        lines = ["# Inner monologue", ""]
        for u in items:
            if u.checkpoint:
                lines.append(f"--- **{u.checkpoint}** ---")
                continue
            lines.append(f"`{u.speaker}`: {u.thought}")
            if u.aside:
                bits = ", ".join(f"{k}={v}" for k, v in u.aside.items())
                lines.append(f"   _({bits})_")
        return "\n".join(lines)


# ── Singleton ────────────────────────────────────────────────

_MONO_LOCK = threading.Lock()
_MONO: InnerMonologue | None = None


def monologue() -> InnerMonologue:
    global _MONO
    if _MONO is None:
        with _MONO_LOCK:
            if _MONO is None:
                _MONO = InnerMonologue()
    return _MONO
