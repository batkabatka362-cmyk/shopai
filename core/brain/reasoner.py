"""Multi-step reasoning chain.

Most ShopAI decisions are single-shot: one LLM call, one verdict.
When the owner asks "should I kill every launch in the sports
niche and pivot to pets?" that's not a scoring question — it's a
research / hypothesise / test / evaluate loop, and a single LLM
prompt collapses all four phases into a confident guess.

``Reasoner`` runs each phase as its own router call with memory
context injected between phases, so every conclusion is grounded
in the memory store rather than hallucinated:

  1. RESEARCH — pull the top semantic memories for the question
     plus per-launch evaluator state; hand both to the LLM with a
     "summarise what we know" prompt.
  2. HYPOTHESIZE — using the research summary, generate 2-3
     concrete hypotheses the owner could act on.
  3. TEST — for each hypothesis, identify the cheapest signal that
     would confirm or refute it (e.g. "launch two SKUs in pets",
     "pull Meta audience stats for sports buyers").
  4. EVALUATE — rank the hypotheses by expected information gain
     and return a ranked plan.

Intentional constraints (CLAUDE.md §4b.C — cost/latency budget):
  • 4 router calls per reasoning run, capped at 500-1200 tokens each
  • RESEARCH uses Groq (fast + cheap); EVALUATE uses DeepSeek when
    available (deeper reasoning) with fallback chain to Gemini → Groq
  • Total run target: under $0.02 and under 8 s latency

Result is a structured ``ReasoningResult`` so callers can drive a
UI or a downstream action queue without regex-parsing the LLM text.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("brain.reasoner")


@dataclass
class Step:
    phase: str
    duration_s: float
    adapter: str = ""
    model: str = ""
    tokens_out: int = 0
    text: str = ""
    error: str | None = None


@dataclass
class ReasoningResult:
    question: str
    summary: str = ""
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    ranked: list[dict[str, Any]] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    duration_s: float = 0.0
    cost_usd: float = 0.0
    memory_ids: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "summary": self.summary,
            "hypotheses": self.hypotheses,
            "ranked": self.ranked,
            "duration_s": round(self.duration_s, 2),
            "cost_usd": round(self.cost_usd, 4),
            "memory_ids": self.memory_ids,
            "steps": [
                {
                    "phase": s.phase,
                    "duration_s": round(s.duration_s, 2),
                    "adapter": s.adapter,
                    "model": s.model,
                    "tokens_out": s.tokens_out,
                    "error": s.error,
                }
                for s in self.steps
            ],
        }


def reason(question: str, k_memories: int = 6) -> ReasoningResult:
    """Run the 4-phase chain. Never raises — degenerate inputs
    return a partial result so callers can still render something."""
    result = ReasoningResult(question=question.strip())
    started = time.monotonic()

    if not result.question:
        return result

    memories = _pull_memories(result.question, k=k_memories)
    result.memory_ids = [m["id"] for m in memories]

    # ── RESEARCH ──────────────────────────────────────────
    research_text, s1 = _call_llm(
        phase="research",
        prompt=_research_prompt(result.question, memories),
        max_tokens=600, temperature=0.3,
        prefer=("groq", "gemini", "deepseek"),
    )
    result.summary = research_text
    result.steps.append(s1)

    # ── HYPOTHESIZE ───────────────────────────────────────
    hyp_text, s2 = _call_llm(
        phase="hypothesize",
        prompt=_hypothesize_prompt(result.question, research_text),
        max_tokens=500, temperature=0.7,
        prefer=("groq", "gemini"),
    )
    result.steps.append(s2)
    result.hypotheses = _parse_hypotheses(hyp_text)

    # ── TEST ──────────────────────────────────────────────
    if result.hypotheses:
        test_text, s3 = _call_llm(
            phase="test",
            prompt=_test_prompt(result.hypotheses),
            max_tokens=600, temperature=0.3,
            prefer=("groq", "gemini"),
        )
        result.steps.append(s3)
        _attach_tests(result.hypotheses, test_text)

    # ── EVALUATE ──────────────────────────────────────────
    if result.hypotheses:
        eval_text, s4 = _call_llm(
            phase="evaluate",
            prompt=_evaluate_prompt(result.question, result.hypotheses),
            max_tokens=500, temperature=0.2,
            prefer=("deepseek", "gemini", "groq"),
        )
        result.steps.append(s4)
        result.ranked = _parse_ranked(eval_text, result.hypotheses)

    result.duration_s = time.monotonic() - started
    return result


# ── Prompts (compact to respect the cost budget) ───────────────

def _research_prompt(question: str, memories: list[dict[str, Any]]) -> str:
    lines = [
        "You are the research agent inside an autonomous e-commerce brain.",
        f"Question: {question!r}",
        "Relevant prior memories (each row: category / action / level / score / tags / content excerpt):",
    ]
    for m in memories:
        tags = m.get("tags") or ""
        if isinstance(tags, list):
            tags = ",".join(tags)
        content = m.get("content") or ""
        if isinstance(content, dict):
            content = json.dumps(content)
        content = str(content)[:200].replace("\n", " ")
        lines.append(
            f"  [{m['category']}/{m['action']} lvl={m['level']} "
            f"score={m['score']}] tags={tags} content={content}"
        )
    lines.append(
        "\nWrite a 5-bullet summary of WHAT WE ALREADY KNOW from these memories. "
        "No speculation, no suggestions, just facts + counts. 120 words max."
    )
    return "\n".join(lines)


def _hypothesize_prompt(question: str, research: str) -> str:
    return (
        "You are the hypothesis-generation agent.\n"
        f"Question: {question!r}\n"
        "Research summary (from memory):\n" + (research or "(no data)") + "\n\n"
        "Generate 2-3 concrete, actionable hypotheses. "
        "Return a compact JSON array only:\n"
        '  [{"id":"h1","claim":"<one sentence>","impact":"<high|med|low>"}, ...]\n'
        "No commentary, no markdown fences."
    )


def _test_prompt(hypotheses: list[dict[str, Any]]) -> str:
    bullets = "\n".join(f"  - {h['id']}: {h['claim']}" for h in hypotheses)
    return (
        "You are the test-design agent.\n"
        "For each hypothesis below, design the cheapest possible test:\n"
        f"{bullets}\n\n"
        "Return JSON only:\n"
        '  [{"id":"h1","test":"<one sentence>","signal":"<what we\'ll measure>","cost_usd":<number>}, ...]'
    )


def _evaluate_prompt(question: str, hypotheses: list[dict[str, Any]]) -> str:
    bullets = "\n".join(
        f"  {h['id']}: {h.get('claim')} — test: {h.get('test', '(none)')}"
        for h in hypotheses
    )
    return (
        "You are the evaluation agent. Rank the hypotheses by expected "
        "information gain per dollar (IG/$). Higher rank = worth testing first.\n"
        f"Question: {question!r}\n"
        f"Hypotheses:\n{bullets}\n\n"
        "Return JSON only:\n"
        '  [{"id":"h1","rank":1,"rationale":"<one sentence>"}, ...]'
    )


# ── Memory + LLM helpers ───────────────────────────────────────

def _pull_memories(query: str, k: int) -> list[dict[str, Any]]:
    """Semantic retrieval first; fall back to level>=2 recent rules if
    the embedding index is empty or unconfigured."""
    out: list[dict[str, Any]] = []
    try:
        from core.memory.semantic_index import retrieve_similar
        hits = retrieve_similar(query, k=k, level_min=0)
        for h in hits:
            out.append(h["memory"])
    except Exception as exc:
        logger.debug("semantic retrieval failed: %s", exc)

    if out:
        return out

    # Fallback: level>=2 rules ordered by score
    import sqlite3
    from pathlib import Path
    db = Path("data/memory_intelligence.db")
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, level, category, action, content, tags, score "
            "FROM memories WHERE level >= 2 "
            "ORDER BY score DESC, use_count DESC LIMIT ?",
            (int(k),),
        )
        for r in cur.fetchall():
            out.append({
                "id": r[0], "level": r[1], "category": r[2],
                "action": r[3], "content": r[4],
                "tags": r[5], "score": r[6],
            })
    finally:
        conn.close()
    return out


def _call_llm(
    phase: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    prefer: tuple[str, ...],
) -> tuple[str, Step]:
    """Single LLM call with adapter preference. Returns (text, Step)."""
    started = time.monotonic()
    step = Step(phase=phase, duration_s=0.0)
    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
        from core.adapters.router import RouteContext
    except Exception as exc:
        step.error = f"adapters unavailable: {exc}"
        step.duration_s = time.monotonic() - started
        return "", step

    try:
        result = get_router().execute(
            capability=Capability.CHAT_COMPLETE,
            params={
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            context=RouteContext(prefer=list(prefer)),
        )
    except Exception as exc:
        step.error = f"{type(exc).__name__}: {exc}"
        step.duration_s = time.monotonic() - started
        return "", step

    step.duration_s = time.monotonic() - started
    step.adapter = getattr(result, "adapter", "") or ""
    step.model = getattr(result, "model", "") or ""
    step.tokens_out = int(getattr(result, "tokens_out", 0) or 0)

    if not getattr(result, "ok", False):
        step.error = str(getattr(result, "error", ""))[:200]
        return "", step

    text = (getattr(result, "data", {}) or {}).get("text", "") or ""
    return text.strip(), step


# ── Response parsers ───────────────────────────────────────────

def _extract_json_array(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return []
    return [d for d in data if isinstance(d, dict)]


def _parse_hypotheses(text: str) -> list[dict[str, Any]]:
    items = _extract_json_array(text)
    out: list[dict[str, Any]] = []
    for i, item in enumerate(items[:3]):
        out.append({
            "id": str(item.get("id") or f"h{i + 1}"),
            "claim": str(item.get("claim") or "").strip(),
            "impact": str(item.get("impact") or "med").lower(),
        })
    return out


def _attach_tests(hypotheses: list[dict[str, Any]], text: str) -> None:
    for item in _extract_json_array(text):
        hid = str(item.get("id") or "")
        for h in hypotheses:
            if h["id"] == hid:
                h["test"] = str(item.get("test") or "").strip()
                h["signal"] = str(item.get("signal") or "").strip()
                try:
                    h["cost_usd"] = float(item.get("cost_usd") or 0)
                except (TypeError, ValueError):
                    h["cost_usd"] = 0.0
                break


def _parse_ranked(text: str, hypotheses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rank_by_id = {}
    for item in _extract_json_array(text):
        hid = str(item.get("id") or "")
        try:
            rank = int(item.get("rank") or 99)
        except (TypeError, ValueError):
            rank = 99
        rank_by_id[hid] = (rank, str(item.get("rationale") or ""))
    ranked = []
    for h in hypotheses:
        rank, reason = rank_by_id.get(h["id"], (99, ""))
        ranked.append({**h, "rank": rank, "rationale": reason})
    ranked.sort(key=lambda x: x["rank"])
    return ranked
