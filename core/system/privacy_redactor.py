"""Privacy redactor — strip PII from logs, narratives, prompts.

Every log line, inner_monologue entry, and LLM prompt could
leak customer data: emails, phone numbers, card numbers, home
addresses. GDPR + basic hygiene say no. A redactor applied
uniformly keeps the brain free to log verbosely without paying
a compliance bill.

PrivacyRedactor applies a battery of regex patterns, each
replacing matches with a deterministic placeholder. Patterns
ship with defaults; custom ones can be registered. Redacted
payloads are still usable for debugging (email domains are
preserved, card numbers keep last 4) but the sensitive bits
are gone.

Default patterns:

  email           alice@ex.com → [EMAIL:ex.com]
  phone           +1 415 555 1234 → [PHONE]
  card_number     4111-1111-1111-1234 → [CARD:****1234]
  ssn             123-45-6789 → [SSN]
  ip_v4           192.168.1.1 → [IP]
  iban            AB12 3456 ... → [IBAN]

APIs:

  redact(text) → (cleaned, matches_count)
  redact_dict(payload) → deep-walked redacted copy
  register_pattern(name, pattern, replacement_fn)
  stats()

Pure stdlib regex. Deterministic. Zero LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


Replacer = Callable[[re.Match], str]


@dataclass
class RedactionRule:
    name: str
    pattern: re.Pattern
    replacer: Replacer


# ── Default replacers ──────────────────────────────────────

def _email_replacer(m: re.Match) -> str:
    domain = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
    return f"[EMAIL:{domain}]" if domain else "[EMAIL]"


def _card_replacer(m: re.Match) -> str:
    digits = re.sub(r"\D", "", m.group(0))
    last4 = digits[-4:] if len(digits) >= 4 else ""
    return f"[CARD:****{last4}]" if last4 else "[CARD]"


_DEFAULT_RULES: tuple[tuple[str, str, Replacer], ...] = (
    # Order matters — specific patterns first so the generic phone
    # regex doesn't swallow IBAN / card / SSN digit runs.
    ("email",
     r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})",
     _email_replacer),
    ("iban",
     r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){4,7}\b",
     lambda m: "[IBAN]"),
    ("card_number",
     r"\b(?:\d[\s\-]?){13,19}\b",
     _card_replacer),
    ("ssn",
     r"\b\d{3}-\d{2}-\d{4}\b",
     lambda m: "[SSN]"),
    ("ip_v4",
     r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
     lambda m: "[IP]"),
    ("phone",
     r"\+?\d[\d\-\s\(\)]{8,}\d",
     lambda m: "[PHONE]"),
)


# ── Redactor ────────────────────────────────────────────────

class PrivacyRedactor:
    def __init__(self) -> None:
        self._rules: list[RedactionRule] = []
        self._counts: dict[str, int] = {}
        self._install_defaults()

    def register_pattern(
        self, name: str, pattern: str,
        replacer: str | Replacer = "[REDACTED]",
    ) -> None:
        if not name:
            raise ValueError("rule name required")
        replacer_fn: Replacer
        if callable(replacer):
            replacer_fn = replacer
        else:
            literal = str(replacer)
            replacer_fn = lambda m: literal  # noqa: E731
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(
                f"invalid regex for {name!r}: {exc}",
            ) from exc
        self._rules = [r for r in self._rules if r.name != name]
        self._rules.append(RedactionRule(
            name=name, pattern=compiled, replacer=replacer_fn,
        ))

    def deregister(self, name: str) -> bool:
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        return len(self._rules) < before

    def rules(self) -> list[str]:
        return [r.name for r in self._rules]

    # ── Core ───────────────────────────────────────────────

    def redact(self, text: str) -> tuple[str, int]:
        """Return (cleaned_text, total_matches)."""
        if not text:
            return "", 0
        out = text
        total = 0
        for rule in self._rules:
            new_out, count = rule.pattern.subn(rule.replacer, out)
            out = new_out
            total += count
            self._counts[rule.name] = self._counts.get(rule.name, 0) + count
        return out, total

    def redact_dict(
        self, payload: Any,
    ) -> Any:
        """Deep-walk dicts/lists/tuples and redact every string leaf."""
        if isinstance(payload, str):
            cleaned, _ = self.redact(payload)
            return cleaned
        if isinstance(payload, dict):
            return {
                k: self.redact_dict(v) for k, v in payload.items()
            }
        if isinstance(payload, list):
            return [self.redact_dict(x) for x in payload]
        if isinstance(payload, tuple):
            return tuple(self.redact_dict(x) for x in payload)
        return payload

    # ── Introspection ─────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "rules": self.rules(),
            "counts": dict(self._counts),
            "total_redacted": sum(self._counts.values()),
        }

    def reset_counts(self) -> None:
        self._counts.clear()

    # ── Defaults ──────────────────────────────────────────

    def _install_defaults(self) -> None:
        for name, pattern, replacer in _DEFAULT_RULES:
            self._rules.append(RedactionRule(
                name=name,
                pattern=re.compile(pattern),
                replacer=replacer,
            ))
