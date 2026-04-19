"""Conversational interface — "shopai ask <question>".

One-shot Q&A over the brain's memory store. Strategy:

  1. Retrieve top semantic + transfer memories for the question
     (weighted mix: 70% semantic, 30% transfer strategies — the
     abstract patterns generalise better for unfamiliar niches).
  2. Build a tight prompt with those rows as context.
  3. Route to Groq for short answers (< 300 tokens), DeepSeek for
     deep questions, Gemini for "show me the data" questions.
  4. Return the answer, the memory ids it cited, and a confidence
     score based on how densely the memories covered the topic.

Rules enforced in the prompt (CLAUDE.md §4b.H — observability):
  • Answer IN the same language the question was asked
  • Cite memory ids inline as ``[#123]`` so the owner can audit
  • If the memory store is silent on the topic, say so — don't
    hallucinate
  • Max 150 words unless the owner asks "explain more"
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("brain.oracle")


_DEEP_TRIGGERS = ("why", "explain", "analyse", "deep", "what should", "strategy")
_QUICK_TRIGGERS = ("status", "how many", "list", "show")


@dataclass
class Answer:
    question: str
    text: str = ""
    cited_ids: list[int] = field(default_factory=list)
    memories_used: int = 0
    adapter: str = ""
    model: str = ""
    duration_s: float = 0.0
    confidence: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.text,
            "cited_ids": self.cited_ids,
            "memories_used": self.memories_used,
            "adapter": self.adapter,
            "model": self.model,
            "duration_s": round(self.duration_s, 2),
            "confidence": round(self.confidence, 3),
        }


def ask(question: str, k_memories: int = 8) -> Answer:
    """Answer *question* using the brain's memory + LLM chain."""
    ans = Answer(question=question.strip())
    if not ans.question:
        return ans

    started = time.monotonic()
    memories = _pull_memories(ans.question, k_memories)
    ans.memories_used = len(memories)

    # Confidence = coverage signal: more level>=2 rows + tighter top
    # cosine → higher confidence. Max 1.0.
    if memories:
        high_level = sum(1 for m in memories if (m.get("level") or 0) >= 2)
        coverage = min(1.0, (high_level + len(memories) * 0.3) / 5.0)
        ans.confidence = round(coverage, 3)

    prompt = _build_prompt(ans.question, memories)
    prefer = _adapter_preference(ans.question)

    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
        from core.adapters.router import RouteContext
    except Exception as exc:
        ans.text = f"(LLM adapters unavailable: {exc})"
        ans.duration_s = time.monotonic() - started
        return ans

    try:
        result = get_router().execute(
            capability=Capability.CHAT_COMPLETE,
            params={
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
                "temperature": 0.25,
            },
            context=RouteContext(prefer=list(prefer)),
        )
    except Exception as exc:
        ans.text = f"(router failure: {type(exc).__name__})"
        ans.duration_s = time.monotonic() - started
        return ans

    if not getattr(result, "ok", False):
        ans.text = f"(adapter error: {getattr(result, 'error', '')})"
        ans.duration_s = time.monotonic() - started
        return ans

    text = (getattr(result, "data", {}) or {}).get("text", "") or ""
    ans.text = text.strip()
    ans.adapter = getattr(result, "adapter", "") or ""
    ans.model = getattr(result, "model", "") or ""
    ans.cited_ids = _extract_citations(ans.text, memories)
    ans.duration_s = time.monotonic() - started
    return ans


# ── Retrieval + prompt helpers ───────────────────────────────

def _pull_memories(question: str, k: int) -> list[dict[str, Any]]:
    """Blend semantic retrieval with the top transfer strategies. The
    transfer layer gives the oracle cross-niche intuition even when
    the question targets a niche with no local evidence."""
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    try:
        from core.memory.semantic_index import retrieve_similar
        for h in retrieve_similar(question, k=max(1, int(k * 0.7)), level_min=0):
            m = h["memory"]
            if m["id"] in seen:
                continue
            rows.append(m)
            seen.add(m["id"])
    except Exception as exc:
        logger.debug("semantic retrieval failed: %s", exc)

    try:
        from core.brain.transfer_learner import retrieve_for_niche
        # Niche is embedded in the question text; just pull the global
        # top-K transfer strategies here.
        transfer = retrieve_for_niche(niche="", k=max(1, int(k * 0.3)))
        for t in transfer:
            tid = t.get("id") or -1
            if tid in seen:
                continue
            rows.append({
                "id": tid,
                "level": 3,
                "category": "transfer_strategy",
                "action": "transfer_pattern",
                "content": {k: v for k, v in t.items() if k not in ("id", "score")},
                "score": t.get("score", 3.0),
            })
            seen.add(tid)
    except Exception as exc:
        logger.debug("transfer retrieval failed: %s", exc)

    return rows[:k]


def _build_prompt(question: str, memories: list[dict[str, Any]]) -> str:
    lines = [
        "You are the ShopAI Oracle, a senior e-commerce analyst that "
        "answers questions using ONLY the memory excerpts below. Rules:",
        "  • Answer in the same language as the question.",
        "  • Cite memory ids inline as [#id] whenever you quote a fact.",
        "  • If the memories don't cover the question, say \"no evidence "
        "    in memory\" — DO NOT invent.",
        "  • Max 150 words unless the question ends in \"explain more\".",
        "",
        f"Question: {question}",
        "",
        "Memory excerpts:",
    ]
    for m in memories:
        content = m.get("content")
        if isinstance(content, dict):
            content = ", ".join(f"{k}={v}" for k, v in list(content.items())[:6])
        content = str(content or "")[:240].replace("\n", " ")
        lines.append(
            f"  [#{m.get('id', '?')}] cat={m.get('category', '')} "
            f"action={m.get('action', '')} lvl={m.get('level', 0)} "
            f"score={m.get('score', 0)} content={content}"
        )
    if not memories:
        lines.append("  (no retrieved memories)")
    lines.append("")
    lines.append("Answer now. Remember: cite [#id] when quoting, never invent.")
    return "\n".join(lines)


def _adapter_preference(question: str) -> tuple[str, ...]:
    q = question.lower()
    if any(t in q for t in _DEEP_TRIGGERS):
        return ("deepseek", "gemini", "groq")
    if any(t in q for t in _QUICK_TRIGGERS):
        return ("groq", "gemini")
    return ("groq", "gemini", "deepseek")


def _extract_citations(text: str, memories: list[dict[str, Any]]) -> list[int]:
    if not text:
        return []
    cited: list[int] = []
    memory_ids = {m.get("id") for m in memories if isinstance(m.get("id"), int)}
    for m in re.finditer(r"\[#(\d+)\]", text):
        try:
            mid = int(m.group(1))
        except ValueError:
            continue
        if mid in memory_ids and mid not in cited:
            cited.append(mid)
    return cited
