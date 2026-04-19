"""Adaptive prompt engine — prompts self-improve by output quality.

LLM prompts in ShopAI (ContentStep, CreativeStep, oracle, reasoner)
are hard-coded strings. When a prompt under-performs (LLM outputs
malformed JSON, SEO score stays low, ad variants all flop), we
have no channel to evolve it without a code change.

This module maintains a **prompt bank**:

    bank.register(name, variants=[...])
    bank.pick(name)              → selects a variant via Thompson sampling
    bank.score(name, variant_id, reward)
                                  → records reward (0-1) per run, feeding
                                    the Beta posterior.

Variants compete. Winners get more traffic; losers fade. When the
best variant's posterior lower bound exceeds another's upper bound,
the loser is pruned and the pool regenerates a mutation of the
winner (swap a sentence, tweak a constraint).

Persistence: data/prompt_bank.db — separate from the memory store
because prompts are engineering artefacts, not episodic data.

Mutation helpers:
  • swap_sentences(text)    — light rearrange
  • add_constraint(text, c) — append a rule
  • tighten(text)           — trim filler words via token list

No LLM needed for the policy; a second LLM call COULD mutate
variants but the deterministic mutations already beat hand-tuning
in practice.
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DB_PATH = Path("data/prompt_bank.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prompt_variants (
    id             TEXT PRIMARY KEY,
    prompt_name    TEXT NOT NULL,
    text           TEXT NOT NULL,
    alpha          REAL NOT NULL DEFAULT 1.0,
    beta           REAL NOT NULL DEFAULT 1.0,
    uses           INTEGER NOT NULL DEFAULT 0,
    total_reward   REAL NOT NULL DEFAULT 0.0,
    created_at     REAL NOT NULL,
    last_used      REAL NOT NULL DEFAULT 0,
    pruned         INTEGER NOT NULL DEFAULT 0,
    metadata       TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_pv_name ON prompt_variants(prompt_name, pruned);
"""


_lock = threading.Lock()


@dataclass
class Variant:
    id: str
    prompt_name: str
    text: str
    alpha: float = 1.0
    beta: float = 1.0
    uses: int = 0
    total_reward: float = 0.0
    created_at: float = 0.0
    last_used: float = 0.0
    pruned: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def mean_reward(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def uncertainty(self) -> float:
        a, b = self.alpha, self.beta
        denom = (a + b) ** 2 * (a + b + 1)
        return math.sqrt(a * b / denom) if denom > 0 else 0.5

    def sample(self, rng: random.Random | None = None) -> float:
        rng = rng or random
        # Approximate beta draw via gamma sampling
        return rng.betavariate(self.alpha, self.beta)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prompt_name": self.prompt_name,
            "text": self.text,
            "mean_reward": round(self.mean_reward, 3),
            "uncertainty": round(self.uncertainty, 3),
            "uses": self.uses,
            "total_reward": round(self.total_reward, 3),
            "pruned": self.pruned,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "metadata": self.metadata,
        }


class PromptBank:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path) if db_path else _DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            conn = sqlite3.connect(str(self._path))
            conn.executescript(_SCHEMA)
            conn.commit()
            conn.close()

    def register(self, prompt_name: str, variants: list[str]) -> list[Variant]:
        """Register a set of seed variants. Idempotent — second call
        with the same variants is a no-op."""
        out: list[Variant] = []
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                cur = conn.cursor()
                for text in variants:
                    cur.execute(
                        "SELECT id FROM prompt_variants "
                        "WHERE prompt_name=? AND text=?",
                        (prompt_name, text),
                    )
                    row = cur.fetchone()
                    if row:
                        out.append(self._row_to_variant(
                            self._fetch_by_id(conn, row[0])))
                        continue
                    vid = f"pv_{uuid.uuid4().hex[:10]}"
                    cur.execute(
                        "INSERT INTO prompt_variants "
                        "(id, prompt_name, text, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (vid, prompt_name, text, time.time()),
                    )
                    out.append(self._row_to_variant(
                        self._fetch_by_id(conn, vid)))
                conn.commit()
            finally:
                conn.close()
        return out

    def pick(
        self,
        prompt_name: str,
        rng_seed: int | None = None,
    ) -> Variant | None:
        """Thompson-sample a variant. Returns None if no variants."""
        live = self._live(prompt_name)
        if not live:
            return None
        rng = random.Random(rng_seed) if rng_seed is not None else random
        best = max(live, key=lambda v: v.sample(rng))
        self._increment_use(best.id)
        return best

    def score(self, variant_id: str, reward: float) -> None:
        """Record reward in [0, 1]. Splits the Beta update into alpha /
        beta weighted by reward + (1 - reward). Also increments use
        count so offline backfills work (no prior ``pick`` call needed)."""
        reward = max(0.0, min(1.0, float(reward)))
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE prompt_variants SET "
                    "alpha = alpha + ?, beta = beta + ?, "
                    "total_reward = total_reward + ?, "
                    "uses = uses + 1, "
                    "last_used = ? "
                    "WHERE id=?",
                    (reward, 1.0 - reward, reward,
                     time.time(), variant_id),
                )
                conn.commit()
            finally:
                conn.close()
        self._maybe_prune_and_mutate(variant_id)

    def list_all(
        self, prompt_name: str, include_pruned: bool = False,
    ) -> list[Variant]:
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                cur = conn.cursor()
                if include_pruned:
                    cur.execute(
                        "SELECT * FROM prompt_variants "
                        "WHERE prompt_name=? ORDER BY alpha DESC",
                        (prompt_name,),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM prompt_variants "
                        "WHERE prompt_name=? AND pruned=0 "
                        "ORDER BY alpha DESC",
                        (prompt_name,),
                    )
                rows = cur.fetchall()
            finally:
                conn.close()
        return [self._row_to_variant(r) for r in rows]

    # ── Internals ───────────────────────────────────────────

    def _live(self, prompt_name: str) -> list[Variant]:
        return [v for v in self.list_all(prompt_name) if not v.pruned]

    def _increment_use(self, variant_id: str) -> None:
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                conn.execute(
                    "UPDATE prompt_variants SET uses = uses + 1, "
                    "last_used = ? WHERE id=?",
                    (time.time(), variant_id),
                )
                conn.commit()
            finally:
                conn.close()

    def _fetch_by_id(self, conn: sqlite3.Connection, vid: str):
        cur = conn.cursor()
        cur.execute("SELECT * FROM prompt_variants WHERE id=?", (vid,))
        return cur.fetchone()

    @staticmethod
    def _row_to_variant(row) -> Variant:
        if row is None:
            return None
        try:
            metadata = json.loads(row[10] or "{}")
        except (json.JSONDecodeError, ValueError):
            metadata = {}
        return Variant(
            id=row[0], prompt_name=row[1], text=row[2],
            alpha=float(row[3] or 1), beta=float(row[4] or 1),
            uses=int(row[5] or 0),
            total_reward=float(row[6] or 0),
            created_at=float(row[7] or 0),
            last_used=float(row[8] or 0),
            pruned=bool(row[9]),
            metadata=metadata,
        )

    def _maybe_prune_and_mutate(self, touched_id: str) -> None:
        """If the best variant's lower 95 CI > another's upper 95 CI,
        prune the loser and spawn a mutation of the winner."""
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT prompt_name FROM prompt_variants WHERE id=?",
                    (touched_id,),
                )
                row = cur.fetchone()
            finally:
                conn.close()
        if not row:
            return
        live = self._live(row[0])
        if len(live) < 2:
            return
        live.sort(key=lambda v: -v.mean_reward)
        winner = live[0]
        loser = live[-1]
        lo_w = winner.mean_reward - 1.96 * winner.uncertainty
        up_l = loser.mean_reward + 1.96 * loser.uncertainty
        if winner.uses < 20 or loser.uses < 20:
            return
        if lo_w <= up_l:
            return
        self._prune(loser.id)
        self._spawn_mutation(winner)

    def _prune(self, variant_id: str) -> None:
        with _lock:
            conn = sqlite3.connect(str(self._path))
            try:
                conn.execute(
                    "UPDATE prompt_variants SET pruned=1 WHERE id=?",
                    (variant_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def _spawn_mutation(self, parent: Variant) -> None:
        mutations = [
            tighten(parent.text),
            add_constraint(parent.text, "Keep the response under 120 words."),
            swap_sentences(parent.text),
        ]
        # Pick the first mutation that isn't already in the bank
        for m in mutations:
            if not m or m == parent.text:
                continue
            # Register under parent's name — child inherits via db row
            self.register(parent.prompt_name, [m])
            break


# ── Deterministic mutation helpers ──────────────────────────

def swap_sentences(text: str) -> str:
    parts = [s.strip().rstrip(".") for s in text.split(". ") if s.strip()]
    if len(parts) <= 1:
        return text
    parts[0], parts[-1] = parts[-1], parts[0]
    joined = ". ".join(parts)
    return joined + ("." if text.endswith(".") else "")


def add_constraint(text: str, constraint: str) -> str:
    if not constraint or constraint in text:
        return text
    sep = "\n" if "\n" in text else " "
    return text + sep + constraint


def tighten(text: str) -> str:
    filler = {
        "really", "very", "just", "basically",
        "actually", "obviously", "simply",
    }
    tokens = text.split()
    trimmed = [t for t in tokens if t.strip(",.!?").lower() not in filler]
    return " ".join(trimmed) if len(trimmed) < len(tokens) else text


# ── Singleton ────────────────────────────────────────────────

_BANK_LOCK = threading.Lock()
_BANK: PromptBank | None = None


def bank() -> PromptBank:
    global _BANK
    with _BANK_LOCK:
        if _BANK is None:
            _BANK = PromptBank()
    return _BANK
