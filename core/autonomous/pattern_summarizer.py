"""Pattern summarizer — write learned-rule narratives to Obsidian.

The brain's MemoryIntelligence promotes Event → Pattern → Rule →
Strategy by counting similarity + outcome scores. Those records live
in SQLite as JSON blobs that are hard to eyeball. Once per day (or on
demand) we ask the Model 3 (research LLM) to summarise the top-N most
used rules + strategies into a short markdown note and drop it in the
Obsidian vault under ``Knowledge/brain-summary-YYYY-MM-DD.md``.

Why this matters:
  • Owners can scan the brain's conclusions without a SQL client.
  • Obsidian's graph view surfaces links between patterns.
  • The ``feedback_learner`` module (future) can read down-rated notes
    to teach the brain which conclusions were wrong — closing the
    last mile of the learning loop.

No-ops cleanly when the vault is unconfigured or the LLM router is
down — the brain keeps learning either way.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("autonomous.pattern_summarizer")


def summarise(
    top_n: int = 15,
    vault_path: str | None = None,
) -> dict[str, Any]:
    """Summarise top-N rules + strategies into an Obsidian note.

    Returns ``{"status": "...", "note": "<path>", "bytes": N}`` —
    never raises, so the daemon can call this unconditionally.
    """
    vault = Path(vault_path or os.environ.get("OBSIDIAN_VAULT_PATH", "./vault"))
    if not vault.exists():
        return {"status": "no_vault", "vault": str(vault)}

    try:
        memories = _collect_top(top_n)
    except Exception as exc:
        logger.warning("pattern_summarizer collect failed: %s", exc)
        return {"status": "memory_error", "error": str(exc)[:200]}

    if not memories:
        return {"status": "no_memories"}

    narrative = _ask_llm(memories) or _fallback_narrative(memories)

    note_path = _write_note(vault, narrative, memories)
    if note_path is None:
        return {"status": "write_failed"}

    return {
        "status": "ok",
        "note": str(note_path),
        "bytes": note_path.stat().st_size,
        "rule_count": len([m for m in memories if m.get("level") == 2]),
        "strategy_count": len([m for m in memories if m.get("level") == 3]),
    }


def _collect_top(top_n: int) -> list[dict[str, Any]]:
    import sqlite3

    db_path = Path("data/memory_intelligence.db")
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "SELECT category, level, action, score, evidence_count, "
        "use_count, success_count, content "
        "FROM memories WHERE level >= 2 "
        "ORDER BY level DESC, score DESC, use_count DESC "
        "LIMIT ?",
        (int(top_n),),
    )
    rows = []
    for r in cur.fetchall():
        try:
            content = json.loads(r[7]) if r[7] else {}
        except (json.JSONDecodeError, ValueError):
            content = {}
        rows.append({
            "category": r[0], "level": r[1], "action": r[2],
            "score": r[3], "evidence_count": r[4],
            "use_count": r[5], "success_count": r[6],
            "content": content,
        })
    conn.close()
    return rows


def _ask_llm(memories: list[dict[str, Any]]) -> str:
    """Ask the research LLM for a human narrative. Empty string on
    any failure — caller falls back to the deterministic template."""
    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
    except Exception:
        return ""

    # Keep the prompt compact — Groq's fast model is fine for a
    # descriptive summary; reserve DeepSeek for tasks that actually
    # need deep reasoning.
    lines: list[str] = []
    for m in memories[:15]:
        kind = "strategy" if m["level"] == 3 else "rule"
        lines.append(
            f"- {kind} [{m['category']}] action={m['action']} "
            f"score={m['score']} uses={m['use_count']} wins={m['success_count']}"
        )
    prompt = (
        "You are a senior e-commerce operations analyst. Given the "
        "brain's top learned rules and strategies below, write a 200-word "
        "markdown summary in three sections:\n"
        "  ## What the brain learned\n"
        "  ## Where it might be wrong\n"
        "  ## What to test next\n"
        "Be specific. Don't repeat the table. Use bullet points.\n\n"
        + "\n".join(lines)
    )
    try:
        result = get_router().execute(
            capability=Capability.CHAT_COMPLETE,
            params={
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 450,
                "temperature": 0.3,
            },
        )
    except Exception as exc:
        logger.debug("summariser LLM failed: %s", exc)
        return ""
    if not result.ok or not result.data:
        return ""
    return (result.data.get("text") or "").strip()


def _fallback_narrative(memories: list[dict[str, Any]]) -> str:
    rules = [m for m in memories if m.get("level") == 2]
    strategies = [m for m in memories if m.get("level") == 3]
    lines = ["## What the brain learned\n"]
    for m in rules[:8]:
        lines.append(
            f"- Rule `{m['category']}` / {m['action']} — score {m['score']}, "
            f"{m['use_count']} uses, {m['success_count']} wins"
        )
    if strategies:
        lines.append("\n## Strategies promoted\n")
        for m in strategies[:5]:
            lines.append(f"- `{m['category']}` — score {m['score']} ({m['use_count']} uses)")
    lines.append(
        "\n## Where it might be wrong\n"
        "- Rules with uses but zero wins were promoted on similarity alone; revisit after more orders.\n"
        "- Advisory actions (no direct Shopify write) don't yet carry a revenue outcome.\n"
    )
    lines.append(
        "## What to test next\n"
        "- Vary the product copy tone on a small launch batch and watch CVR per tone.\n"
        "- Launch a second product in the highest-scoring category to confirm the pattern.\n"
    )
    return "\n".join(lines)


def _write_note(
    vault: Path,
    narrative: str,
    memories: list[dict[str, Any]],
) -> Path | None:
    today = dt.date.today().isoformat()
    title = f"brain-summary-{today}"
    target_dir = vault / "Knowledge"
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / f"{title}.md"

    frontmatter = {
        "kind": "brain_summary",
        "date": today,
        "rule_count": len([m for m in memories if m.get("level") == 2]),
        "strategy_count": len([m for m in memories if m.get("level") == 3]),
        "tags": ["brain", "summary", "learning"],
    }
    fm_lines = ["---"]
    for k, v in frontmatter.items():
        fm_lines.append(f"{k}: {json.dumps(v) if not isinstance(v, str) else v}")
    fm_lines.append("---\n")

    body_table = ["\n## Top memories\n", "| Level | Category | Action | Score | Uses | Wins |",
                  "|---|---|---|---|---|---|"]
    for m in memories:
        body_table.append(
            f"| {m['level']} | {m['category']} | {m['action']} | "
            f"{m['score']} | {m['use_count']} | {m['success_count']} |"
        )

    try:
        out.write_text(
            "\n".join(fm_lines) + narrative + "\n" + "\n".join(body_table) + "\n",
            encoding="utf-8",
        )
        return out
    except Exception as exc:
        logger.warning("failed to write %s: %s", out, exc)
        return None
