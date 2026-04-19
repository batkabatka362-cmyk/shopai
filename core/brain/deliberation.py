"""Multi-agent deliberation — Bull / Bear / Judge.

Single LLM responses drift toward the first plausible answer. For
major calls (kill $500 of spend, scale to $200/day, pivot niche)
we run three specialised agents in sequence:

    BULL  — argues FOR the proposal, cites the best evidence for it.
    BEAR  — argues AGAINST, cites failure modes and risk.
    JUDGE — reads both, picks a verdict with an explicit confidence
            and a short rationale.

The judge is intentionally a *different* adapter preference (DeepSeek
→ Gemini → Groq) to avoid a single model confirming its own bias.
Each agent's argument is a Trace.Evidence citation so the full
deliberation is auditable via the decision_trace layer.

Cost target: ≤ 3 LLM calls × 400 tokens each ≈ $0.01 per
deliberation. Latency: 3-9 s. Used only on decisions above a
configurable stake threshold (default >$100 budget impact).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any


_MAX_TOKENS_PER_AGENT = 400
_DEFAULT_STAKE_USD = 100.0


@dataclass
class AgentReply:
    agent: str                    # "bull" | "bear" | "judge"
    text: str
    adapter: str = ""
    model: str = ""
    duration_s: float = 0.0
    error: str | None = None


@dataclass
class Verdict:
    verdict: str                  # "proceed" | "reject" | "hold"
    confidence: float             # 0-1
    rationale: str
    stake_usd: float = 0.0
    proposal: str = ""
    bull: AgentReply | None = None
    bear: AgentReply | None = None
    judge: AgentReply | None = None
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
            "stake_usd": round(self.stake_usd, 2),
            "proposal": self.proposal,
            "ts": self.ts,
            "bull": self.bull.__dict__ if self.bull else None,
            "bear": self.bear.__dict__ if self.bear else None,
            "judge": self.judge.__dict__ if self.judge else None,
        }


def deliberate(
    proposal: str,
    stake_usd: float = 0.0,
    context_memories: list[dict[str, Any]] | None = None,
) -> Verdict:
    """Run the three-agent deliberation on *proposal*.

    Cheap stake cap: when stake_usd < DEFAULT_STAKE_USD the function
    short-circuits with a single-agent verdict from the reasoner.
    """
    if not proposal:
        return _blank(proposal, stake_usd, "(empty proposal)")

    if stake_usd < _DEFAULT_STAKE_USD:
        return _short_circuit(proposal, stake_usd)

    context = _format_context(context_memories or [])

    bull = _call_agent(
        agent="bull",
        system=_BULL_SYSTEM,
        user=_agent_user(proposal, context, role="bull"),
        prefer=("groq", "gemini", "deepseek"),
    )
    bear = _call_agent(
        agent="bear",
        system=_BEAR_SYSTEM,
        user=_agent_user(proposal, context, role="bear"),
        prefer=("groq", "gemini", "deepseek"),
    )
    judge = _call_agent(
        agent="judge",
        system=_JUDGE_SYSTEM,
        user=_judge_user(proposal, bull.text, bear.text),
        prefer=("deepseek", "gemini", "groq"),
        max_tokens=500,
    )

    parsed = _parse_judgment(judge.text)
    return Verdict(
        verdict=parsed.get("verdict") or "hold",
        confidence=float(parsed.get("confidence") or 0.5),
        rationale=parsed.get("rationale") or judge.text[:400],
        stake_usd=float(stake_usd),
        proposal=proposal,
        bull=bull, bear=bear, judge=judge,
        ts=time.time(),
    )


# ── Prompts ──────────────────────────────────────────────────

_BULL_SYSTEM = (
    "You are the BULL — you argue FOR the proposal below. Cite the "
    "strongest supporting signals from the context. Be specific: "
    "numbers, cited memory ids, adapter costs. 80-120 words."
)

_BEAR_SYSTEM = (
    "You are the BEAR — you argue AGAINST the proposal below. Surface "
    "failure modes, hidden costs, opportunity cost. Avoid rhetoric — "
    "stick to facts. 80-120 words."
)

_JUDGE_SYSTEM = (
    "You are the JUDGE. Read the Bull and Bear arguments and emit a "
    "verdict JSON object: "
    '{"verdict":"proceed|reject|hold","confidence":0-1,"rationale":"<=120 words"}. '
    "Prefer hold when evidence is thin. No commentary outside the JSON."
)


def _agent_user(proposal: str, context: str, role: str) -> str:
    return (
        f"Proposal: {proposal}\n\n"
        f"Context (memories / facts / signals):\n{context or '(none)'}\n\n"
        f"Argue {role.upper()} as instructed."
    )


def _judge_user(proposal: str, bull: str, bear: str) -> str:
    return (
        f"Proposal: {proposal}\n\n"
        f"BULL argument:\n{bull or '(silent)'}\n\n"
        f"BEAR argument:\n{bear or '(silent)'}\n\n"
        "Return JSON verdict only."
    )


# ── LLM plumbing ─────────────────────────────────────────────

def _call_agent(
    agent: str,
    system: str,
    user: str,
    prefer: tuple[str, ...],
    max_tokens: int = _MAX_TOKENS_PER_AGENT,
) -> AgentReply:
    reply = AgentReply(agent=agent, text="")
    started = time.monotonic()
    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
        from core.adapters.router import RouteContext
    except Exception as exc:
        reply.error = f"adapters unavailable: {exc}"
        reply.duration_s = time.monotonic() - started
        return reply

    try:
        result = get_router().execute(
            capability=Capability.CHAT_COMPLETE,
            params={
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.5 if agent != "judge" else 0.2,
            },
            context=RouteContext(prefer=list(prefer)),
        )
    except Exception as exc:
        reply.error = f"{type(exc).__name__}: {exc}"
        reply.duration_s = time.monotonic() - started
        return reply

    reply.duration_s = time.monotonic() - started
    reply.adapter = getattr(result, "adapter", "") or ""
    reply.model = getattr(result, "model", "") or ""
    if not getattr(result, "ok", False):
        reply.error = str(getattr(result, "error", ""))[:200]
        return reply
    reply.text = ((getattr(result, "data", {}) or {}).get("text") or "").strip()
    return reply


def _format_context(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return ""
    lines = []
    for m in memories[:8]:
        content = m.get("content")
        if isinstance(content, dict):
            content = ", ".join(f"{k}={v}" for k, v in list(content.items())[:4])
        content = str(content or "")[:160].replace("\n", " ")
        lines.append(
            f"  [#{m.get('id', '?')}] {m.get('category', '?')}/"
            f"{m.get('action', '?')} score={m.get('score', 0)}  {content}"
        )
    return "\n".join(lines)


def _parse_judgment(text: str) -> dict[str, Any]:
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _short_circuit(proposal: str, stake_usd: float) -> Verdict:
    """Skip Bull/Bear when stake < threshold — cheap single-agent pass
    that still produces a structured verdict."""
    reply = _call_agent(
        agent="judge",
        system=_JUDGE_SYSTEM,
        user=(f"Proposal: {proposal}\n\nStake is ${stake_usd:.2f} — "
              "emit the verdict JSON directly. No Bull/Bear needed "
              "for low-stake calls."),
        prefer=("groq", "gemini", "deepseek"),
    )
    parsed = _parse_judgment(reply.text)
    return Verdict(
        verdict=parsed.get("verdict") or "proceed",
        confidence=float(parsed.get("confidence") or 0.6),
        rationale=parsed.get("rationale") or reply.text[:200],
        stake_usd=stake_usd,
        proposal=proposal,
        judge=reply,
        ts=time.time(),
    )


def _blank(proposal: str, stake_usd: float, reason: str) -> Verdict:
    return Verdict(
        verdict="hold",
        confidence=0.0,
        rationale=reason,
        stake_usd=stake_usd,
        proposal=proposal,
        ts=time.time(),
    )
