"""PromptLibrary — centralized, versioned prompt templates.

Inline prompt strings inside cognitive modules cause two problems:

  1. Drift: a tweak in `planner.py` doesn't reach `imagination.py`,
     so the AI prompts itself differently in different phases.
  2. Untrackable changes: a typo in a system prompt is invisible
     in commit history because it lives inside a long Python file.

PromptLibrary fixes both. Every prompt the system sends to an LLM
is registered here with:

    name      stable identifier the caller looks up
    version   semver-ish (1, 2, 3 …) so reflective code can audit
              which prompt version produced which output
    purpose   one-line human description of what the prompt does
    system    system-prompt content (model role / output rules)
    template  user-prompt template with named placeholders

Usage:

    from core.system.prompt_library import get_prompt
    prompt = get_prompt("planner.decompose_goal")
    rendered = prompt.render(goal_what="Improve engine.pricing")

    response = llm.ask(
        role="reasoner",
        prompt=rendered.user,
        system_prompt=rendered.system,
    )

The library is designed so cognitive modules read prompts by name
instead of carrying string literals. Adding a new prompt is one
file change in one place — every consumer benefits immediately.

Version bumping: when you edit a prompt's content, increment its
version number AND keep the old version in the registry under
the old version key. This lets reflection compare A/B prompt
variants and learn which performed better over time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RenderedPrompt:
    """A prompt that has been substituted with caller arguments."""
    name: str
    version: int
    system: str
    user: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "system": self.system,
            "user": self.user,
        }


@dataclass
class PromptTemplate:
    """A reusable prompt template with placeholders."""
    name: str
    version: int
    purpose: str
    system: str
    template: str
    placeholders: list[str] = field(default_factory=list)
    role: str = "general"
    schema_hint: str = ""

    def render(self, **kwargs) -> RenderedPrompt:
        """Substitute placeholders into the template.

        Missing placeholders are replaced with an empty string and
        a warning comment is appended to the user prompt so the
        caller can spot the mismatch in logs.
        """
        missing = [p for p in self.placeholders if p not in kwargs]
        try:
            user = self.template.format(**{
                **{p: "" for p in self.placeholders},
                **{k: str(v) for k, v in kwargs.items()},
            })
        except (KeyError, IndexError) as exc:
            user = self.template + f"\n\n# render error: {exc}"
        if missing:
            user += f"\n\n# warning: missing placeholders {missing}"
        return RenderedPrompt(
            name=self.name,
            version=self.version,
            system=self.system,
            user=user,
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "purpose": self.purpose,
            "role": self.role,
            "placeholders": list(self.placeholders),
            "schema_hint": self.schema_hint,
        }


# ── Registry ──────────────────────────────────────────────────


class PromptLibrary:
    """Process-wide registry of prompt templates."""

    def __init__(self) -> None:
        self._prompts: dict[str, PromptTemplate] = {}
        self._versions: dict[str, list[PromptTemplate]] = {}

    def register(self, template: PromptTemplate) -> None:
        """Register or replace a prompt by name.

        Older versions of the same name are kept in `_versions[name]`
        so callers can look up an old version explicitly via
        `get(name, version=1)`.
        """
        if not template.name:
            raise ValueError("PromptTemplate.name required")
        existing = self._prompts.get(template.name)
        if existing and existing.version != template.version:
            # Archive the old version before overwriting
            self._versions.setdefault(template.name, []).append(existing)
        self._prompts[template.name] = template

    def get(self, name: str, *, version: Optional[int] = None) -> Optional[PromptTemplate]:
        """Look up a prompt by name. If `version` is set, return that
        specific historical version (or None if not archived)."""
        if version is None:
            return self._prompts.get(name)
        current = self._prompts.get(name)
        if current and current.version == version:
            return current
        for old in self._versions.get(name, []):
            if old.version == version:
                return old
        return None

    def list_prompts(self) -> list[PromptTemplate]:
        return sorted(self._prompts.values(), key=lambda p: p.name)

    def history(self, name: str) -> list[PromptTemplate]:
        """All known versions of a prompt, oldest first."""
        archived = list(self._versions.get(name, []))
        current = self._prompts.get(name)
        if current:
            archived.append(current)
        return sorted(archived, key=lambda p: p.version)


# ── Built-in prompts ─────────────────────────────────────────
#
# Every prompt the cognitive package uses is defined here. Adding
# a new prompt: append a PromptTemplate to BUILT_IN_PROMPTS and
# call get_prompt(name) from your module.
#
# When editing an existing prompt, INCREMENT its version. The
# library archives the previous version automatically so reflection
# can compare A/B variants over time.

BUILT_IN_PROMPTS: list[PromptTemplate] = [
    # ── Planner ──────────────────────────────────────────────
    PromptTemplate(
        name="planner.decompose_goal",
        version=1,
        purpose="Break a goal into 3-6 concrete executable steps",
        role="reasoner",
        system=(
            "You are a planning assistant for an autonomous e-commerce "
            "AI named ShopAI. Given a goal, decompose it into 3-6 "
            "concrete, executable steps. Each step should be small "
            "enough to attempt in isolation. Think about what data "
            "needs to be gathered, what actions taken, and how the "
            "outcome will be measured.\n\n"
            "Output ONLY a JSON object of the form:\n"
            '{"steps": ['
            '{"description": "...", "rationale": "...", '
            '"expected_outcome": "...", "estimated_cost": 0.0-1.0, '
            '"estimated_impact": 0.0-1.0, "confidence": 0.0-1.0}, ...]}\n'
            "Cost is the effort to execute. Impact is the expected "
            "progress toward the goal. Confidence is how sure you are "
            "this step is the right thing to do."
        ),
        template=(
            "Goal: {goal_what}\n"
            "{context_block}"
            "Decompose this into 3-6 concrete steps. Return JSON only."
        ),
        placeholders=["goal_what", "context_block"],
        schema_hint='{"steps": [{"description": str, "rationale": str, ...}]}',
    ),

    # ── Reflection ───────────────────────────────────────────
    PromptTemplate(
        name="reflection.summarize_episodes",
        version=1,
        purpose="Read recent episodes and write a narrative lesson summary",
        role="analyzer",
        system=(
            "You are a meta-cognitive reviewer for an autonomous "
            "e-commerce AI. You will be given a list of recent "
            "decision episodes. Your job is to identify patterns, "
            "extract lessons, and recommend actions.\n\n"
            "Output ONLY a JSON object:\n"
            '{"lessons": ['
            '{"type": "improvement|regression|strength|weakness|pattern", '
            '"subject": "...", "evidence": "...", '
            '"recommended_action": "...", "confidence": 0.0-1.0}, ...]}\n'
            "Be concise. Each lesson should be one sentence of evidence."
        ),
        template=(
            "Recent episodes ({episode_count}):\n"
            "{episodes_json}\n\n"
            "What patterns do you see? What should I learn? Return JSON only."
        ),
        placeholders=["episode_count", "episodes_json"],
        schema_hint='{"lessons": [{"type": str, "subject": str, ...}]}',
    ),

    # ── Imagination ──────────────────────────────────────────
    PromptTemplate(
        name="imagination.evaluate_step",
        version=1,
        purpose="Predict the outcome of one plan step before execution",
        role="reasoner",
        system=(
            "You are simulating the future for an autonomous e-commerce "
            "AI. Given a single planned step and the current store "
            "context, predict what will probably happen if it executes.\n\n"
            "Output ONLY a JSON object:\n"
            '{"predicted_score": 0.0-1.0, '
            '"predicted_cost": 0.0-1.0, '
            '"confidence": 0.0-1.0, '
            '"reasoning": "...", '
            '"risks": ["..."]}\n'
            "predicted_score = how well it achieves the parent goal. "
            "predicted_cost = effort/risk. confidence = how sure you are."
        ),
        template=(
            "Step: {step_description}\n"
            "Goal: {goal_what}\n"
            "{context_block}"
            "Predict the outcome. Return JSON only."
        ),
        placeholders=["step_description", "goal_what", "context_block"],
        schema_hint='{"predicted_score": float, "predicted_cost": float, "confidence": float, "reasoning": str, "risks": [str]}',
    ),

    # ── TheoryOfMind ─────────────────────────────────────────
    PromptTemplate(
        name="theory_of_mind.predict_response",
        version=1,
        purpose="Predict how an external agent will react to an action",
        role="analyzer",
        system=(
            "You are modeling the behavior of an external agent (a "
            "customer segment or competitor) for an autonomous "
            "e-commerce AI. Given the agent's known beliefs and traits "
            "and a hypothetical action the AI might take, predict how "
            "the agent will react.\n\n"
            "Output ONLY a JSON object:\n"
            '{"predicted_response": "...", '
            '"confidence": 0.0-1.0, '
            '"reasoning": "...", '
            '"alternative_responses": [{"response": "...", "probability": 0.0-1.0}]}'
        ),
        template=(
            "Agent: {agent_name} (kind={agent_kind})\n"
            "Traits: {agent_traits}\n"
            "Beliefs about them: {agent_beliefs}\n"
            "Proposed action: {action}\n\n"
            "How will this agent react? Return JSON only."
        ),
        placeholders=[
            "agent_name", "agent_kind", "agent_traits",
            "agent_beliefs", "action",
        ],
        schema_hint='{"predicted_response": str, "confidence": float, "reasoning": str}',
    ),

    # ── Curiosity ────────────────────────────────────────────
    PromptTemplate(
        name="curiosity.pick_target",
        version=1,
        purpose="Pick the most interesting unknown to explore next",
        role="reasoner",
        system=(
            "You are the curiosity drive for an autonomous e-commerce "
            "AI. You will be given a list of capabilities the AI knows "
            "very little about. Pick the ONE most worth exploring next, "
            "considering: novelty, potential impact on revenue, low "
            "exploration cost, and synergy with the AI's existing "
            "strengths.\n\n"
            "Output ONLY a JSON object:\n"
            '{"target": "...", '
            '"reason": "...", '
            '"expected_payoff": 0.0-1.0, '
            '"first_step": "..."}'
        ),
        template=(
            "Unknown capabilities ({count}):\n"
            "{candidates_json}\n\n"
            "Current strengths: {strengths_json}\n\n"
            "Pick one to explore next. Return JSON only."
        ),
        placeholders=["count", "candidates_json", "strengths_json"],
        schema_hint='{"target": str, "reason": str, "expected_payoff": float, "first_step": str}',
    ),

    # ── Decision (used by brain.decision_engine) ────────────
    PromptTemplate(
        name="decision.pricing_recommendation",
        version=1,
        purpose="Recommend a pricing action given product + market data",
        role="reasoner",
        system=(
            "You are a pricing specialist for an autonomous e-commerce "
            "AI. Given a product's current price, cost, recent sales, "
            "and competitor prices, recommend ONE pricing action: "
            "raise, lower, or hold. Be cautious — small adjustments "
            "are usually safer than dramatic ones.\n\n"
            "Output ONLY a JSON object:\n"
            '{"action": "raise|lower|hold", '
            '"new_price": float, '
            '"delta_pct": float, '
            '"reasoning": "...", '
            '"confidence": 0.0-1.0, '
            '"risks": ["..."]}'
        ),
        template=(
            "Product: {product_name}\n"
            "Current price: {price}\n"
            "Cost: {cost}\n"
            "Margin: {margin_pct}%\n"
            "Recent sales (last 30d): {recent_sales}\n"
            "Competitor prices: {competitor_prices}\n\n"
            "Recommend a pricing action. Return JSON only."
        ),
        placeholders=[
            "product_name", "price", "cost", "margin_pct",
            "recent_sales", "competitor_prices",
        ],
        schema_hint='{"action": str, "new_price": float, "reasoning": str, "confidence": float}',
    ),

    # ── Mind think (ad-hoc reasoning) ────────────────────────
    PromptTemplate(
        name="mind.think",
        version=1,
        purpose="Generic reasoning prompt for ad-hoc 'shopai mind think'",
        role="reasoner",
        system=(
            "You are ShopAI, an autonomous e-commerce AI. You have "
            "access to your own memory, capabilities, and a set of "
            "skills. Answer questions about what you would do, what "
            "you've learned, and what you recommend. Be concrete and "
            "honest about uncertainty."
        ),
        template=(
            "{self_context}"
            "Question: {question}"
        ),
        placeholders=["self_context", "question"],
    ),
]


# ── Singleton accessor ────────────────────────────────────────


_library: Optional[PromptLibrary] = None


def get_library() -> PromptLibrary:
    """Return the process-wide PromptLibrary, building it on first
    call from BUILT_IN_PROMPTS."""
    global _library
    if _library is None:
        _library = PromptLibrary()
        for tmpl in BUILT_IN_PROMPTS:
            _library.register(tmpl)
    return _library


def get_prompt(name: str, *, version: Optional[int] = None) -> Optional[PromptTemplate]:
    """Shortcut: look up a prompt by name from the global library."""
    return get_library().get(name, version=version)


def render_prompt(name: str, **kwargs) -> Optional[RenderedPrompt]:
    """Shortcut: look up a prompt and render it in one call.

    Returns None if the prompt name is unknown.
    """
    template = get_prompt(name)
    if template is None:
        return None
    return template.render(**kwargs)
