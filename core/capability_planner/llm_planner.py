"""LLM-augmented planner.

Wraps the deterministic Planner with semantic seed-selection
via a local Ollama LLM. Falls back to the deterministic
planner when:
  - Ollama isn't running.
  - The configured model isn't pulled.
  - LLM call raises / times out.
  - LLM returns no parseable capability names.

Architecture
------------
The LLM is ONLY responsible for seed selection -- the hardest
part of planning where substring matching breaks down (e.g.
"abandoned cart" -> cart_recovery, "drive repeat purchases"
-> loyalty + email_marketing, "find new niches" ->
trend_discovery).

Once the LLM picks 1-5 capability names, the deterministic
planner's machinery takes over:
  - Validates names against the registry.
  - Walks ``composes_with`` for chain expansion.
  - Picks the orchestrator shortcut when applicable.
  - Appends ``audit_store`` verification.
  - Dedupes the CLI sequence.

Bounded blast radius: an LLM mistake at worst produces
irrelevant seeds, and the deterministic chain still walks
correctly. The fallback path ensures the planner never gets
WORSE than the deterministic version.

Why local Ollama (not cloud)
----------------------------
The model_router system already targets local-first
(``ModelTier.LOCAL`` is the default for low-complexity
prompts). Seed selection from a 96-entry catalog is a small
classification task -- well within local model capability.
Cloud APIs require credentials and add latency + cost; the
operator can swap in cloud explicitly via env var or arg.

Prompt design
-------------
The catalog is compressed to ``name -> when_to_use`` per
entry (~96 entries × ~100 chars ≈ 10KB, fits in 8K context).
System prompt instructs JSON-list output.

LLM responses are parsed with a forgiving extractor that
hunts for a JSON array even when the model adds prose
around it.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from core.capability_registry import (
    Capability,
    get_registry,
)
from core.capability_registry.bootstrap import (
    ensure_registered,
)

from .plan import Plan
from .planner import Planner

logger = logging.getLogger(__name__)

# Default Ollama model for planning. Qwen2.5 is a structured-
# output worker model -- a good fit for "given catalog +
# goal, emit a JSON list".
_DEFAULT_LLM_MODEL: str = "qwen2.5"

# Max capability names the LLM is allowed to return as seeds.
# Anything beyond 5 is noise; the deterministic walker will
# expand each seed's composition graph anyway.
_MAX_SEEDS: int = 5

# Per-capability blurb max length in the compressed catalog.
# Keeps the prompt within context budget while preserving the
# LLM-readable signal.
_BLURB_MAX_CHARS: int = 160


_PLANNER_SYSTEM_PROMPT: str = (
    "You are a capability selection assistant for ShopAI, "
    "an autonomous AI merchant on Shopify.\n"
    "\n"
    "Given an operator goal and a catalog of registered "
    "capabilities, your job is to pick the 1-5 most "
    "relevant capabilities for accomplishing the goal.\n"
    "\n"
    "Output ONLY a JSON array of capability names (strings). "
    "No prose, no comments, no markdown. Just the JSON.\n"
    "\n"
    "Example outputs:\n"
    "  [\"store_design_engine\", \"apply_design\"]\n"
    "  [\"launch_store\"]\n"
    "  [\"email_marketing\", \"audience_targeting\"]\n"
    "\n"
    "Pick names ONLY from the catalog. Never invent names."
)


class LLMPlanner:
    """LLM-augmented planner. Public surface mirrors
    ``Planner.plan_for_goal`` so callers can swap planners
    behind the same call shape."""

    def __init__(
        self,
        *,
        model: str = _DEFAULT_LLM_MODEL,
        backend: Any | None = None,
        skip_bootstrap: bool = False,
    ) -> None:
        if not skip_bootstrap:
            ensure_registered()
        self._registry = get_registry()
        self._model = model
        # Inject backend for testing; otherwise lazy-load
        # Ollama at first call.
        self._backend = backend
        self._fallback = Planner(skip_bootstrap=True)

    def plan_for_goal(self, goal: str) -> Plan:
        """Build a Plan using LLM seed selection, with
        deterministic fallback.

        On any LLM unavailability / failure / empty result,
        falls back to ``Planner.plan_for_goal(goal)``. The
        returned Plan looks identical to the deterministic
        one except for a note explaining LLM was used.
        """
        goal_text = (goal or "").strip()
        if not goal_text:
            return self._fallback.plan_for_goal(goal_text)

        backend = self._resolve_backend()
        if backend is None:
            plan = self._fallback.plan_for_goal(goal_text)
            plan.notes.append(
                "LLM planner unavailable (Ollama not "
                "running). Fell back to deterministic walker."
            )
            return plan

        seed_names = self._llm_select_seeds(
            backend, goal_text,
        )
        if not seed_names:
            plan = self._fallback.plan_for_goal(goal_text)
            plan.notes.append(
                "LLM planner returned no valid seeds. Fell "
                "back to deterministic walker."
            )
            return plan

        # We got LLM-picked seeds. Use the deterministic
        # planner's chain expansion + verification with the
        # LLM seeds replacing the substring-matched ones.
        plan = self._build_plan_from_seeds(
            goal_text, seed_names,
        )
        plan.notes.insert(
            0,
            f"LLM-driven planner picked seeds: "
            f"{', '.join(seed_names)}",
        )
        return plan

    # ── Internals ─────────────────────────────────────────

    def _resolve_backend(self) -> Any | None:
        """Lazy-load OllamaBackend on first call. Returns
        None if Ollama isn't reachable. Tests inject backend
        via ``__init__``.

        Injected backends are still checked via
        ``is_available()`` so tests can simulate Ollama
        being down without rebuilding the backend.
        """
        if self._backend is not None:
            # Respect is_available() on injected backends too.
            try:
                if not self._backend.is_available():
                    return None
            except Exception as exc:  # noqa: BLE001
                # Backend without is_available() -> trust it
                logger.debug(
                    "backend.is_available() unsupported (%s)",
                    exc,
                )
            return self._backend
        try:
            from models.inference.ollama_backend import (
                OllamaBackend,
            )
            backend = OllamaBackend()
            if backend.is_available():
                self._backend = backend
                return backend
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "llm_planner: backend resolve raised: %s",
                exc,
            )
        return None

    def _llm_select_seeds(
        self, backend: Any, goal: str,
    ) -> list[str]:
        """Ask the LLM to pick 1-5 capability names from the
        catalog. Returns validated names (filtered against
        the registry); empty list on any failure or zero
        valid hits.
        """
        catalog = self._build_compressed_catalog()
        user_prompt = (
            f"Operator goal: {goal!r}\n"
            f"\n"
            f"Catalog (capability name -> when to use):\n"
            f"{catalog}\n"
            f"\n"
            f"Pick the 1-{_MAX_SEEDS} most relevant "
            f"capability names. JSON array only."
        )
        try:
            result = backend.generate(
                model_name=self._model,
                prompt=user_prompt,
                system_prompt=_PLANNER_SYSTEM_PROMPT,
                temperature=0.2,
                max_tokens=200,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "llm_planner: backend.generate raised: %s",
                exc,
            )
            return []

        text = (result or {}).get("text", "") or ""
        names = _parse_capability_list(text)
        # Filter to capabilities that actually exist in the
        # registry. An LLM hallucination becomes a silent
        # skip rather than a fake step.
        validated = []
        for n in names:
            if self._registry.get(n) is not None:
                if n not in validated:
                    validated.append(n)
                if len(validated) >= _MAX_SEEDS:
                    break
        return validated

    def _build_compressed_catalog(self) -> str:
        """Render the registry as ``name -> when_to_use``
        lines, capped at ``_BLURB_MAX_CHARS`` per line.

        The catalog is sorted alphabetically so the LLM sees
        a deterministic surface across runs.
        """
        lines: list[str] = []
        for cap in self._registry.all():
            blurb = (cap.when_to_use or cap.description or "").strip()
            if len(blurb) > _BLURB_MAX_CHARS:
                blurb = blurb[:_BLURB_MAX_CHARS] + "..."
            lines.append(f"- {cap.name}: {blurb}")
        return "\n".join(lines)

    def _build_plan_from_seeds(
        self, goal: str, seed_names: list[str],
    ) -> Plan:
        """Run the deterministic planner's chain expansion +
        verification on a hand-picked seed list. Reuses the
        deterministic planner's internals so the output Plan
        shape stays identical."""
        seeds: list[Capability] = []
        for name in seed_names:
            cap = self._registry.get(name)
            if cap is not None:
                seeds.append(cap)

        plan = Plan(goal=goal)
        plan.relevant_capabilities = [c.name for c in seeds]
        if not seeds:
            return plan

        # 1. Orchestrator shortcut (same logic as
        # deterministic planner)
        orch = self._fallback._pick_orchestrator(seeds)
        if orch is not None:
            plan.notes.append(
                f"Orchestrator '{orch.name}' covers the "
                f"LLM-picked seeds; using it instead of the "
                f"per-step CLIs."
            )
            plan.steps.append(
                self._fallback._step_for(
                    orch, role="orchestrator",
                ),
            )
            self._fallback._append_verification_step(
                plan, [orch],
            )
            self._fallback._finalise(plan)
            return plan

        # 2. Chain expansion per seed
        seen: set[str] = set()
        for seed in seeds:
            chain = self._fallback._walk_chain(seed)
            for cap in chain:
                if cap.name in seen:
                    continue
                seen.add(cap.name)
                plan.steps.append(
                    self._fallback._step_for(
                        cap,
                        role=self._fallback._infer_role(cap),
                    ),
                )

        # 3. Verification append
        self._fallback._append_verification_step(plan, seeds)
        self._fallback._finalise(plan)
        return plan


_JSON_ARRAY_RE = re.compile(r"\[[^\[\]]*\]", re.DOTALL)


def _parse_capability_list(text: str) -> list[str]:
    """Extract a JSON array of strings from LLM output.

    LLMs sometimes wrap their JSON in prose ("Here are the
    capabilities: [...]"). This parser hunts for the first
    bracketed array and tries ``json.loads``. Returns empty
    list on any parse failure.
    """
    if not text or not isinstance(text, str):
        return []
    # Try the whole text first
    candidates = [text.strip()]
    # Hunt for inline bracketed arrays
    for match in _JSON_ARRAY_RE.finditer(text):
        candidates.append(match.group(0))
    for cand in candidates:
        try:
            parsed = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(parsed, list):
            continue
        # Filter to strings only
        names = [
            str(x).strip() for x in parsed
            if isinstance(x, str) and x.strip()
        ]
        if names:
            return names
    return []


def plan_for_goal_with_llm(
    goal: str,
    *,
    model: str = _DEFAULT_LLM_MODEL,
) -> Plan:
    """Module-level shortcut for
    ``LLMPlanner(model=model).plan_for_goal(goal)``."""
    return LLMPlanner(model=model).plan_for_goal(goal)
