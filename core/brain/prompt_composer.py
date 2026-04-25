"""Prompt composer — brain-state-aware prompt builder atop prompt_templates.

``core/system/prompt_templates.py`` holds PRIMITIVE versioned
templates: name + version + f-string body. ``prompt_composer`` is
the layer ABOVE: it composes multiple templates with *live brain
state* injection so prompts automatically include the brain's:

  • self_narrative identity line
  • compacted cycle context
  • recent experience (few-shot examples)
  • current owner style weights
  • an explicit budget / caller-supplied slots

A ``ComposedPrompt`` carries:

  • body            — the final prompt string
  • slot_sources    — which provider filled each slot (audit)
  • byte_size       — so callers don't blow an LLM token budget
  • templates_used  — base + overlay names + versions

Providers are dependency-injected so the composer is testable
without touching real singletons. All providers failure-soft.

Pure stdlib. Deterministic given injected providers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("brain.prompt_composer")


@dataclass
class ComposedPrompt:
    body: str
    slot_sources: dict[str, str]   # slot_name → provider_name
    byte_size: int
    templates_used: list[tuple[str, int]] = field(default_factory=list)
    missing_slots: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "body": self.body,
            "slot_sources": dict(self.slot_sources),
            "byte_size": self.byte_size,
            "templates_used": list(self.templates_used),
            "missing_slots": list(self.missing_slots),
        }


@dataclass
class SlotProvider:
    name: str                       # identifies provider in trail
    fn: Callable[[], Any]           # returns slot value
    slot: str                       # slot name it fills

    def __post_init__(self) -> None:
        if not self.name or not self.slot:
            raise ValueError("SlotProvider needs name + slot")


# ── Built-in provider factories ──────────────────────────

def identity_provider(
    narrator_fn: Callable[[], dict[str, Any]] | None = None,
) -> SlotProvider:
    """Pulls identity_line from self_narrative (or injected fn)."""
    def _fn() -> str:
        if narrator_fn is None:
            return "ShopAI commerce executor"
        try:
            n = narrator_fn()
        except Exception as exc:
            logger.debug("narrator_fn failed: %s", exc)
            return "ShopAI commerce executor"
        return str(n.get("identity_line") or "ShopAI commerce executor")
    return SlotProvider(name="self_narrative", fn=_fn, slot="identity")


def context_provider(
    compactor_fn: Callable[[], dict[str, Any]] | None = None,
) -> SlotProvider:
    """Pulls compacted context (from context_compactor)."""
    def _fn() -> str:
        if compactor_fn is None:
            return "(no context)"
        try:
            brief = compactor_fn()
        except Exception as exc:
            logger.debug("context compactor failed: %s", exc)
            return "(context unavailable)"
        fields = brief.get("fields") or {}
        if not fields:
            return "(no context)"
        return "\n".join(
            f"{k}: {v}" for k, v in sorted(fields.items())
        )
    return SlotProvider(name="context_compactor", fn=_fn, slot="context")


def examples_provider(
    examples_fn: Callable[[], list[dict[str, Any]]] | None = None,
    *,
    slot: str = "examples",
    max_examples: int = 3,
) -> SlotProvider:
    """Pulls a few-shot example list."""
    def _fn() -> str:
        if examples_fn is None:
            return ""
        try:
            items = list(examples_fn())[:max_examples]
        except Exception as exc:
            logger.debug("examples_fn failed: %s", exc)
            return ""
        if not items:
            return ""
        lines = []
        for i, ex in enumerate(items, 1):
            q = str(ex.get("question", ex.get("input", "")))[:200]
            a = str(ex.get("answer", ex.get("output", "")))[:200]
            lines.append(f"Example {i}:\nQ: {q}\nA: {a}")
        return "\n\n".join(lines)
    return SlotProvider(name="experience_recorder", fn=_fn, slot=slot)


def owner_style_provider(
    weights_fn: Callable[[], dict[str, float]] | None = None,
) -> SlotProvider:
    """Pulls owner_model style descriptor."""
    def _fn() -> str:
        if weights_fn is None:
            return "normal"
        try:
            w = weights_fn() or {}
        except Exception as exc:
            logger.debug("weights_fn failed: %s", exc)
            return "normal"
        if not w:
            return "normal"
        dominant = max(w.items(), key=lambda kv: kv[1])
        return str(dominant[0])
    return SlotProvider(
        name="owner_model", fn=_fn, slot="owner_style",
    )


# ── Composer ─────────────────────────────────────────────

class PromptComposer:
    def __init__(
        self,
        *,
        template_render: Callable[[str, dict[str, Any]], str] | None
            = None,
        template_version_lookup: Callable[[str], int] | None = None,
    ) -> None:
        self._render = template_render
        self._version = template_version_lookup
        self._providers: dict[str, SlotProvider] = {}

    def register(self, provider: SlotProvider) -> None:
        self._providers[provider.slot] = provider

    def unregister(self, slot: str) -> bool:
        return self._providers.pop(slot, None) is not None

    def providers(self) -> list[SlotProvider]:
        return list(self._providers.values())

    # ── Compose ──────────────────────────────────────────

    def _resolve_slots(
        self,
        overrides: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, str]]:
        resolved: dict[str, str] = {}
        sources: dict[str, str] = {}
        # Overrides win first
        for slot, value in overrides.items():
            resolved[slot] = str(value)
            sources[slot] = "override"
        # Then providers fill what's missing
        for slot, provider in self._providers.items():
            if slot in resolved:
                continue
            try:
                value = provider.fn()
            except Exception as exc:
                logger.debug(
                    "provider %s raised: %s",
                    provider.name, exc,
                )
                continue
            resolved[slot] = str(value)
            sources[slot] = provider.name
        return resolved, sources

    def compose(
        self,
        *,
        base_template: str,
        overlay_templates: Iterable[str] = (),
        slot_overrides: dict[str, Any] | None = None,
        required_slots: Iterable[str] = (),
    ) -> ComposedPrompt:
        if not base_template:
            raise ValueError("base_template required")
        overrides = dict(slot_overrides or {})
        resolved, sources = self._resolve_slots(overrides)

        missing: list[str] = []
        for slot in required_slots:
            if slot not in resolved:
                missing.append(str(slot))

        templates_used: list[tuple[str, int]] = []
        body_parts: list[str] = []
        for name in (base_template, *overlay_templates):
            version = 0
            if self._version is not None:
                try:
                    version = int(self._version(name))
                except Exception as exc:
                    logger.debug(
                        "version lookup failed for %s: %s",
                        name, exc,
                    )
            templates_used.append((name, version))
            if self._render is None:
                # Fallback — treat the template name as the literal body
                body_parts.append(name)
                continue
            try:
                body_parts.append(self._render(name, resolved))
            except Exception as exc:
                logger.debug(
                    "render %s failed: %s", name, exc,
                )
                body_parts.append(f"[[template {name!r} unavailable]]")
        body = "\n\n".join(
            part for part in body_parts if part
        ).strip()
        return ComposedPrompt(
            body=body,
            slot_sources=sources,
            byte_size=len(body.encode("utf-8")),
            templates_used=templates_used,
            missing_slots=missing,
        )

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "providers": len(self._providers),
            "has_renderer": self._render is not None,
            "slots": sorted(self._providers.keys()),
        }
