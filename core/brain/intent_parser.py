"""Intent parser — owner free-text → structured action.

Owners type commands like "launch the blue widget at 20 a day in
audio" or "kill anything under 1.5 roas after 3 days". Today
every such string goes to an LLM and comes back as unstructured
text — cost every request, latency every request, and zero
reproducibility.

IntentParser matches free text against a small catalogue of
regex-backed verbs and extracts the parameters deterministically.
When it matches confidently, the caller never needs the LLM:

    parse("launch blue widget $20/day audio")
    → Intent(verb="launch",
             args={"product": "blue widget",
                   "budget_day": 20.0,
                   "niche": "audio"},
             confidence=0.93)

Verbs covered (extensible via ``register_verb``):

  launch     — create a new product / campaign
  kill       — stop a running launch / campaign
  scale      — increase budget / allocation
  pause      — temporarily halt
  resume     — re-activate
  price      — set a price
  schedule   — set timing / window
  ask        — free-form query forwarded to oracle
  goal       — add a new goal_agenda entry

If nothing matches confidently, ``parse`` returns Intent(verb=
"unknown", ...) with a list of nearest verbs by Jaccard overlap
so the UI can suggest "did you mean?".

Pure regex + dictionary matching, zero LLM. Dictionaries are
auditable so new phrasings are a one-line change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass
class Intent:
    verb: str                        # "launch" | "kill" | ... | "unknown"
    args: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0          # 0..1
    raw: str = ""
    suggestions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "verb": self.verb,
            "args": self.args,
            "confidence": round(self.confidence, 3),
            "raw": self.raw,
            "suggestions": self.suggestions,
        }


# ── Dictionaries ────────────────────────────────────────────

_VERB_KEYWORDS: dict[str, tuple[str, ...]] = {
    "launch":   ("launch", "start", "run ad", "open"),
    "kill":     ("kill", "stop", "end", "shut down", "turn off"),
    "scale":    ("scale", "increase", "bump", "raise budget", "ramp"),
    "pause":    ("pause", "hold"),
    "resume":   ("resume", "unpause", "restart"),
    "price":    ("set price", "price", "change price", "sell at"),
    "schedule": ("schedule", "every friday", "weekly", "daily at"),
    "ask":      ("what", "how", "why", "when", "where", "explain"),
    "goal":     ("add goal", "new goal", "aim for", "target"),
}


_NICHES = (
    "audio", "fashion", "gardening", "fitness", "electronics",
    "beauty", "toys", "kitchen", "pets", "health", "home",
    "tech", "apparel", "sports",
)


_PRICE_RE = re.compile(
    r"\$?\s*([0-9]+(?:\.[0-9]+)?)(?:\s*(?:usd|eur|gbp|a\s*day|/day))?",
    re.IGNORECASE,
)
_DAYS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*day", re.IGNORECASE,
)
_ROAS_RE = re.compile(
    r"(?:roas\s*(?:<|under|below|of)\s*([0-9]+(?:\.[0-9]+)?)"
    r"|(?:<|under|below)\s*([0-9]+(?:\.[0-9]+)?)\s*roas)",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*%")


# ── Parser ──────────────────────────────────────────────────

_CUSTOM_VERBS: dict[str, Callable[[str], dict[str, Any] | None]] = {}


def register_verb(
    name: str, handler: Callable[[str], dict[str, Any] | None],
) -> None:
    """Plug in a custom verb handler. Handler receives the lowercased
    text and returns args (or None if it doesn't match)."""
    _CUSTOM_VERBS[name] = handler


def parse(text: str) -> Intent:
    if not text or not text.strip():
        return Intent(verb="unknown", raw=text, confidence=0.0)
    raw = text
    t = text.lower().strip()

    # Custom verbs first (most specific)
    for name, handler in _CUSTOM_VERBS.items():
        args = handler(t)
        if args is not None:
            return Intent(
                verb=name, args=args, confidence=0.9, raw=raw,
            )

    # Score each known verb by keyword hit. Sentence-initial WH
    # words (what/how/why/...) pin the intent to ``ask`` — questions
    # shouldn't be mis-routed to launch just because they mention
    # launches.
    first_word = t.split()[0] if t.split() else ""
    if first_word in ("what", "how", "why", "when", "where", "who"):
        return Intent(
            verb="ask", args={"question": raw},
            confidence=0.9, raw=raw,
        )
    scores: dict[str, int] = {}
    for verb, keywords in _VERB_KEYWORDS.items():
        # Multi-word phrases ('new goal', 'turn off') outrank
        # single-word hits ('scale') so a longer, more specific
        # keyword always wins the verb assignment.
        scores[verb] = sum(
            len(kw.split()) for kw in keywords if kw in t
        )
    top_verb, top_score = max(scores.items(), key=lambda kv: kv[1])
    if top_score == 0:
        # No match — return suggestions by token Jaccard
        return Intent(
            verb="unknown", raw=raw, confidence=0.0,
            suggestions=_suggest_verbs(t),
        )

    # Extract arguments based on which verb fired
    args: dict[str, Any] = {}
    _extract_common(t, args)
    if top_verb == "launch":
        _extract_product(t, args)
    elif top_verb == "kill":
        # ROAS threshold + days
        if m := _ROAS_RE.search(t):
            val = m.group(1) or m.group(2)
            if val is not None:
                args["roas_below"] = float(val)
        if m := _DAYS_RE.search(t):
            args["after_days"] = float(m.group(1))
    elif top_verb == "scale":
        if m := _PERCENT_RE.search(t):
            args["factor_pct"] = float(m.group(1))
    elif top_verb == "price":
        if m := _PRICE_RE.search(t):
            args["price_usd"] = float(m.group(1))
    elif top_verb == "goal":
        # Everything after the goal keyword
        for kw in _VERB_KEYWORDS["goal"]:
            if kw in t:
                args["text"] = raw.split(kw, 1)[-1].strip()
                break
    elif top_verb == "ask":
        args["question"] = raw

    # Confidence: 0.5 baseline + 0.1 per matched keyword + 0.05 per arg
    confidence = min(
        1.0, 0.5 + 0.1 * top_score + 0.05 * len(args),
    )
    return Intent(
        verb=top_verb, args=args, confidence=confidence, raw=raw,
    )


# ── Helpers ────────────────────────────────────────────────

def _extract_common(t: str, args: dict[str, Any]) -> None:
    # Niche
    for n in _NICHES:
        if n in t:
            args["niche"] = n
            break
    # Budget: "$20", "20 a day", "$20/day"
    if m := re.search(
        r"\$\s*([0-9]+(?:\.[0-9]+)?)\s*(?:a\s*day|/day|per day)?",
        t, re.IGNORECASE,
    ):
        val = float(m.group(1))
        if "day" in t:
            args["budget_day"] = val
        else:
            args["budget"] = val
    else:
        # Dollar-less "20 a day"
        if m := re.search(
            r"(\d+(?:\.\d+)?)\s*a\s*day", t, re.IGNORECASE,
        ):
            args["budget_day"] = float(m.group(1))


def _extract_product(t: str, args: dict[str, Any]) -> None:
    """Best-effort product name: tokens between 'launch' and the first
    known terminator (price / niche / day)."""
    m = re.search(
        r"launch\s+(?:the\s+)?(.+?)(?:\s+at\s|\s+\$|\s+for\s|\s+in\s|\s+\d|$)",
        t,
    )
    if m:
        product = m.group(1).strip()
        if product:
            args["product"] = product


def _suggest_verbs(t: str, k: int = 3) -> list[str]:
    tokens = set(re.findall(r"[a-z]+", t))
    scored: list[tuple[str, float]] = []
    for verb, keywords in _VERB_KEYWORDS.items():
        kw_tokens = {w for kw in keywords for w in kw.split()}
        if not kw_tokens:
            continue
        inter = tokens & kw_tokens
        union = tokens | kw_tokens
        jac = len(inter) / max(1, len(union))
        scored.append((verb, jac))
    scored.sort(key=lambda kv: -kv[1])
    return [v for v, s in scored[:k] if s > 0]


# ── Introspection ───────────────────────────────────────────

def known_verbs() -> list[str]:
    return list(_VERB_KEYWORDS.keys()) + list(_CUSTOM_VERBS.keys())
