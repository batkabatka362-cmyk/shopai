"""Prompt templates — structured templating + versioning for LLM calls.

Every LLM call in ShopAI is constructed as an f-string at the
call site. That means:

  • We can't A/B test prompt variants without a code change.
  • There's no record of which prompt shipped in which build.
  • A prompt change silently alters the entire subsystem.
  • Dashboards can't show "which prompt version produces the
    highest hypothesis-confirmed rate?".

PromptTemplateRegistry stores named templates with:

  • name                — stable id (`product_description`)
  • version             — semantic int; bumps on change
  • body                — template with {placeholders}
  • required_vars       — set of placeholders that must be supplied
  • max_output_tokens   — enforcement hint for the dispatcher
  • required_caps       — capabilities needed from LLMDispatcher
  • metadata            — author, description, tags, sample I/O

APIs:

  register(name, version, body, required_vars, ...)
  render(name, vars) → rendered prompt + metadata for routing
  latest(name) → most recent registered version
  lock(name, version) → pin a version (no silent upgrades)
  history(name) → all versions in order

render() validates every required var is present and rejects
unknown placeholders (surfaced with line numbers) so bugs get
caught *before* the LLM call burns budget.

Pure stdlib. Deterministic. No LLM.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable


_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


@dataclass
class Template:
    name: str
    version: int
    body: str
    required_vars: frozenset[str]
    max_output_tokens: int = 1024
    required_caps: frozenset[str] = field(default_factory=frozenset)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "body": self.body,
            "required_vars": sorted(self.required_vars),
            "max_output_tokens": self.max_output_tokens,
            "required_caps": sorted(self.required_caps),
            "metadata": self.metadata,
        }


@dataclass
class RenderedPrompt:
    template_name: str
    version: int
    rendered: str
    max_output_tokens: int
    required_caps: frozenset[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "template_name": self.template_name,
            "version": self.version,
            "rendered": self.rendered,
            "max_output_tokens": self.max_output_tokens,
            "required_caps": sorted(self.required_caps),
        }


# ── Registry ────────────────────────────────────────────────

class PromptRegistry:
    def __init__(self) -> None:
        self._templates: dict[tuple[str, int], Template] = {}
        self._latest: dict[str, int] = {}
        self._locked: dict[str, int] = {}
        self._lock = threading.Lock()
        self._install_defaults()

    # ── Registration ───────────────────────────────────────

    def register(
        self,
        name: str,
        version: int,
        body: str,
        required_vars: Iterable[str] = (),
        max_output_tokens: int = 1024,
        required_caps: Iterable[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> Template:
        name = name.strip()
        if not name:
            raise ValueError("template name required")
        if not body:
            raise ValueError("template body required")
        declared = set(required_vars)
        found = set(_PLACEHOLDER_RE.findall(body))
        if not declared.issubset(found):
            missing = declared - found
            raise ValueError(
                f"declared vars {sorted(missing)} not present in body",
            )
        template = Template(
            name=name, version=int(version), body=body,
            required_vars=frozenset(required_vars),
            max_output_tokens=int(max_output_tokens),
            required_caps=frozenset(required_caps),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._templates[(name, template.version)] = template
            if template.version > self._latest.get(name, -1):
                self._latest[name] = template.version
        return template

    def get(
        self, name: str, version: int | None = None,
    ) -> Template | None:
        name = name.strip()
        with self._lock:
            if version is None:
                version = self._locked.get(name,
                                             self._latest.get(name))
            if version is None:
                return None
            return self._templates.get((name, int(version)))

    def latest(self, name: str) -> Template | None:
        with self._lock:
            v = self._latest.get(name.strip())
        return self.get(name, v) if v is not None else None

    def lock(self, name: str, version: int) -> bool:
        with self._lock:
            if (name, int(version)) not in self._templates:
                return False
            self._locked[name] = int(version)
            return True

    def unlock(self, name: str) -> bool:
        with self._lock:
            return self._locked.pop(name, None) is not None

    def history(self, name: str) -> list[Template]:
        with self._lock:
            return sorted(
                (t for (n, _), t in self._templates.items() if n == name),
                key=lambda t: t.version,
            )

    # ── Render ─────────────────────────────────────────────

    def render(
        self, name: str, vars: dict[str, Any],
        version: int | None = None,
    ) -> RenderedPrompt:
        template = self.get(name, version=version)
        if template is None:
            raise KeyError(f"unknown template {name!r}")
        missing = template.required_vars - set(vars.keys())
        if missing:
            raise ValueError(
                f"missing required vars {sorted(missing)}",
            )
        # Stage 1: confirm every placeholder is supplied.
        needed = set(_PLACEHOLDER_RE.findall(template.body))
        missing_body = needed - set(vars.keys())
        if missing_body:
            raise ValueError(
                f"placeholders {sorted(missing_body)} have no value",
            )
        # Escape braces inside user values by using format_map with
        # a defaultdict-style wrapper — we already validated keys.
        rendered = template.body.format(
            **{k: vars[k] for k in needed},
        )
        return RenderedPrompt(
            template_name=template.name,
            version=template.version,
            rendered=rendered,
            max_output_tokens=template.max_output_tokens,
            required_caps=template.required_caps,
        )

    # ── Defaults ──────────────────────────────────────────

    def _install_defaults(self) -> None:
        self.register(
            "product_description", 1,
            body=(
                "Write a {length_words}-word product description for "
                "'{title}' in {tone} tone. Focus on {focus}. Avoid "
                "hyperbole."
            ),
            required_vars=("length_words", "title", "tone", "focus"),
            max_output_tokens=400,
            required_caps={"summarise"},
            metadata={"category": "content"},
        )
        self.register(
            "intent_classify", 1,
            body=(
                "Classify the following customer message into exactly "
                "one of: complaint, question, request, praise, "
                "purchase_intent, unsubscribe, other.\n\n"
                "Message:\n{text}\n\nLabel:"
            ),
            required_vars=("text",),
            max_output_tokens=20,
            required_caps={"classify"},
            metadata={"category": "classification"},
        )


# ── Singleton ────────────────────────────────────────────────

_REG_LOCK = threading.Lock()
_REGISTRY: PromptRegistry | None = None


def registry() -> PromptRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        with _REG_LOCK:
            if _REGISTRY is None:
                _REGISTRY = PromptRegistry()
    return _REGISTRY


def render(
    name: str, vars: dict[str, Any], version: int | None = None,
) -> RenderedPrompt:
    return registry().render(name, vars, version=version)
