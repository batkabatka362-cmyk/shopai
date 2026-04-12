"""Imagination — counterfactual simulation of hypothetical futures.

Where the Planner says "here are 6 possible steps", Imagination
answers "and here's what each one would probably do if I tried it".
The point is to evaluate alternatives in the safety of the AI's
own head before committing real cost in the world.

Two integration patterns:

  1. Evaluate one step
        outcome = imagination.imagine_step(step)
        # outcome.predicted_score, .predicted_cost, .confidence

  2. Evaluate a whole plan
        result = imagination.imagine_plan(plan)
        # result.expected_score, .expected_cost, .step_outcomes

  3. Compare plans (counterfactual A/B)
        comparison = imagination.compare([plan_a, plan_b, plan_c])
        # comparison["best"] → the plan with the best expected value
        # comparison["ranked"] → sorted list

The evaluator that produces the per-step prediction is pluggable.
The default is a fully heuristic evaluator that combines:

    - SelfModel score for any matching capability (if available)
    - Recent memory episodes whose action keyword overlaps the step
    - The step's own confidence / cost / impact estimates

Callers can plug in a stronger evaluator (e.g. wrap SmartExecutor's
simulate mode) by passing `evaluator=` to the constructor.

No real Shopify calls. No real AI inference (unless the injected
evaluator does that). Imagination is pure prediction — its job is
to keep the AI from learning the hard way.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from utils.logger import get_logger

logger = get_logger("cognitive.imagination")


# Tunable weights for combining sources of evidence
_WEIGHT_SELF_MODEL = 0.45
_WEIGHT_MEMORY = 0.30
_WEIGHT_STEP_PRIOR = 0.25


@dataclass
class ImaginedOutcome:
    """Predicted outcome of a single step."""
    description: str
    predicted_score: float = 0.5      # 0..1
    predicted_cost: float = 0.5       # 0..1
    confidence: float = 0.5           # how sure we are about the prediction
    sources: list[str] = field(default_factory=list)
    notes: str = ""

    def expected_value(self) -> float:
        """A single number capturing how attractive this step looks.

        expected_value = predicted_score - 0.5 * predicted_cost
        Higher is better. Range: roughly [-0.5, 1.0].
        """
        return self.predicted_score - 0.5 * self.predicted_cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "predicted_score": round(self.predicted_score, 3),
            "predicted_cost": round(self.predicted_cost, 3),
            "confidence": round(self.confidence, 3),
            "expected_value": round(self.expected_value(), 3),
            "sources": list(self.sources),
            "notes": self.notes,
        }


@dataclass
class ImaginedPlan:
    """Predicted outcome of a whole plan (sequence of steps)."""
    plan_what: str
    step_outcomes: list[ImaginedOutcome] = field(default_factory=list)
    expected_score: float = 0.0       # weighted by confidence
    expected_cost: float = 0.0        # sum across steps
    overall_confidence: float = 0.0
    backend: str = ""

    def expected_value(self) -> float:
        return self.expected_score - 0.5 * self.expected_cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_what": self.plan_what,
            "step_outcomes": [o.to_dict() for o in self.step_outcomes],
            "expected_score": round(self.expected_score, 3),
            "expected_cost": round(self.expected_cost, 3),
            "overall_confidence": round(self.overall_confidence, 3),
            "expected_value": round(self.expected_value(), 3),
            "backend": self.backend,
            "step_count": len(self.step_outcomes),
        }


# An evaluator turns a step (dict-like with a `description`) into an
# ImaginedOutcome. The default uses SelfModel + memory + step priors.
StepEvaluator = Callable[[Any], ImaginedOutcome]


class Imagination:
    """Counterfactual simulator. Stateless except for injected deps.

    Two evaluation paths stack. The default heuristic evaluator
    combines SelfModel + memory + step priors. When an LLM is
    available, the public ``imagine_step`` calls the LLM evaluator
    FIRST and falls back to the heuristic on any failure. This
    way the AI gets richer predictions (with reasoning text) when
    LLM is up and still works deterministically when not.
    """

    def __init__(
        self,
        *,
        self_model: Any = None,
        memory: Any = None,
        evaluator: Optional[StepEvaluator] = None,
        llm: Any = None,
        use_llm: bool = True,
    ) -> None:
        self._self_model = self_model
        self._memory = memory
        # When no custom evaluator is supplied, the heuristic IS the
        # evaluator. We track whether a CUSTOM evaluator overrode the
        # default so the LLM-first path only fires for the default.
        self._has_custom_evaluator = evaluator is not None
        self._evaluator = evaluator or self._default_evaluator
        self._llm = llm
        self._use_llm = bool(use_llm)
        # Goal context the caller may set for richer LLM predictions
        self._current_goal: str = ""

    # ── Public API ─────────────────────────────────────────────

    def imagine_step(self, step: Any) -> ImaginedOutcome:
        """Predict the outcome of one step.

        Accepts either a PlanStep dataclass, a dict with 'description',
        or a plain string. When an LLM is available, prefers the
        LLM evaluator over the heuristic; on LLM failure falls back
        to heuristics so the cognitive loop never stalls.
        """
        # Try LLM first if enabled and the caller didn't supply a
        # custom evaluator that they explicitly want to use
        if self._use_llm and not self._has_custom_evaluator:
            llm_outcome = self._llm_evaluate(step)
            if llm_outcome is not None:
                return llm_outcome

        try:
            return self._evaluator(step)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Imagination: evaluator raised %s", exc)
            desc = self._step_description(step)
            return ImaginedOutcome(
                description=desc,
                predicted_score=0.5,
                predicted_cost=0.5,
                confidence=0.0,
                sources=["evaluator_error"],
                notes=str(exc)[:120],
            )

    def imagine_plan(self, plan: Any) -> ImaginedPlan:
        """Predict the cumulative outcome of a whole plan.

        Sets the current_goal context so the LLM evaluator (if
        active) can frame each step's prediction against the parent
        goal. The context is cleared at the end so it doesn't leak
        between plans.
        """
        plan_what = self._plan_what(plan)
        steps = self._plan_steps(plan)
        backend = getattr(plan, "backend", "") or ""

        result = ImaginedPlan(plan_what=plan_what, backend=backend)
        if not steps:
            return result

        previous_goal = self._current_goal
        self._current_goal = plan_what
        try:
            outcomes = [self.imagine_step(s) for s in steps]
        finally:
            self._current_goal = previous_goal
        result.step_outcomes = outcomes

        # Confidence-weighted average score across steps
        total_weight = sum(o.confidence for o in outcomes) or 1.0
        weighted_score = sum(o.predicted_score * o.confidence for o in outcomes) / total_weight
        result.expected_score = weighted_score
        result.expected_cost = sum(o.predicted_cost for o in outcomes)
        result.overall_confidence = sum(o.confidence for o in outcomes) / len(outcomes)
        return result

    def compare(self, plans: list[Any]) -> dict[str, Any]:
        """Imagine each plan and return a ranked comparison.

        Returns:
            {
              "ranked":   [ImaginedPlan, ...] sorted by expected_value desc,
              "best":     the top ImaginedPlan (or None if no plans),
              "by_value": {plan_what: expected_value} for quick lookup
            }
        """
        if not plans:
            return {"ranked": [], "best": None, "by_value": {}}

        imagined = [self.imagine_plan(p) for p in plans]
        ranked = sorted(imagined, key=lambda x: x.expected_value(), reverse=True)
        return {
            "ranked": ranked,
            "best": ranked[0] if ranked else None,
            "by_value": {p.plan_what: p.expected_value() for p in imagined},
        }

    # ── Default evaluator ──────────────────────────────────────

    def _default_evaluator(self, step: Any) -> ImaginedOutcome:
        """Heuristic predictor combining SelfModel + memory + step priors.

        Each source contributes a sub-score in [0, 1]:

          self_model_score   from SelfModel.get_capability(subject)
                              if the step references a known capability
          memory_score        from average score of recent episodes whose
                              action overlaps the step's keywords
          step_prior          from the step's own confidence/impact/cost
                              fields if it has them (PlanStep dataclass)

        The final predicted_score is a weighted sum. Predicted_cost
        is taken from the step prior unless we have direct memory
        evidence to override it. Confidence is the product of how
        many sources contributed and their individual confidences.
        """
        desc = self._step_description(step)
        if not desc:
            return ImaginedOutcome(
                description="(empty step)",
                predicted_score=0.5,
                predicted_cost=0.5,
                confidence=0.0,
                sources=[],
            )

        sources: list[str] = []

        # ─── Source 1: SelfModel ────────────────────────────
        sm_score, sm_conf, sm_subject = self._self_model_signal(desc)
        if sm_score is not None:
            sources.append(f"self_model:{sm_subject}")

        # ─── Source 2: Memory ───────────────────────────────
        mem_score, mem_conf, mem_n = self._memory_signal(desc)
        if mem_score is not None:
            sources.append(f"memory:n={mem_n}")

        # ─── Source 3: Step prior ──────────────────────────
        prior_score = self._step_prior_score(step)
        prior_conf = self._step_prior_confidence(step)
        prior_cost = self._step_prior_cost(step)
        if prior_score is not None:
            sources.append("step_prior")

        # ─── Combine into a single weighted score ───────────
        # A source only contributes if it produced an actual score.
        # The step's `confidence` field alone (without an estimate)
        # is metadata, not a signal.
        weighted_sum = 0.0
        weight_total = 0.0
        contributing_confidences: list[float] = []
        if sm_score is not None:
            weighted_sum += _WEIGHT_SELF_MODEL * sm_score * sm_conf
            weight_total += _WEIGHT_SELF_MODEL * sm_conf
            contributing_confidences.append(sm_conf)
        if mem_score is not None:
            weighted_sum += _WEIGHT_MEMORY * mem_score * mem_conf
            weight_total += _WEIGHT_MEMORY * mem_conf
            contributing_confidences.append(mem_conf)
        if prior_score is not None:
            weighted_sum += _WEIGHT_STEP_PRIOR * prior_score * prior_conf
            weight_total += _WEIGHT_STEP_PRIOR * prior_conf
            contributing_confidences.append(prior_conf)

        if weight_total > 0:
            predicted_score = weighted_sum / weight_total
        else:
            predicted_score = 0.5  # no information → neutral

        # Confidence: average of contributing sources, scaled by how many
        if contributing_confidences:
            base_conf = sum(contributing_confidences) / len(contributing_confidences)
            # More sources → more confident, capped at 0.95
            multiplier = min(1.0, 0.5 + 0.25 * len(contributing_confidences))
            confidence = min(0.95, base_conf * multiplier)
        else:
            confidence = 0.0

        return ImaginedOutcome(
            description=desc,
            predicted_score=max(0.0, min(1.0, predicted_score)),
            predicted_cost=prior_cost if prior_cost is not None else 0.5,
            confidence=confidence,
            sources=sources,
            notes=(
                f"sm={sm_score!r} mem={mem_score!r} prior={prior_score!r}"
                if (sm_score is not None or mem_score is not None) else ""
            ),
        )

    # ── Signal extractors ──────────────────────────────────────

    def _self_model_signal(
        self, description: str,
    ) -> tuple[Optional[float], float, str]:
        """Look up the SelfModel for any capability whose name appears
        in the step description. Returns (score, confidence, subject).
        """
        if self._self_model is None:
            return None, 0.0, ""
        try:
            caps = self._self_model.capabilities()
        except Exception:  # noqa: BLE001
            return None, 0.0, ""

        desc_lower = description.lower()
        for cap in caps:
            name = cap.get("name", "")
            if not name:
                continue
            # Try exact substring match
            if name.lower() in desc_lower:
                return (
                    float(cap.get("score", 0.5)),
                    float(cap.get("confidence", 0.0)),
                    name,
                )
            # Strip the prefix (engine.X → X) and try again
            short = name.split(".", 1)[-1].lower()
            if short and short in desc_lower:
                return (
                    float(cap.get("score", 0.5)),
                    float(cap.get("confidence", 0.0)),
                    name,
                )
        return None, 0.0, ""

    def _memory_signal(
        self, description: str,
    ) -> tuple[Optional[float], float, int]:
        """Find recent memory episodes whose action keywords overlap
        the step description. Average their scores."""
        if self._memory is None:
            return None, 0.0, 0
        retrieve = getattr(self._memory, "retrieve", None)
        if not callable(retrieve):
            return None, 0.0, 0

        keywords = _extract_keywords(description)
        if not keywords:
            return None, 0.0, 0

        # Pull recent episodes from a few categories
        episodes: list[dict] = []
        for cat in ("action", "decision", "result"):
            try:
                episodes.extend(retrieve(category=cat, limit=50) or [])
            except Exception:  # noqa: BLE001
                continue

        if not episodes:
            return None, 0.0, 0

        # Filter by keyword overlap with the action / content fields
        relevant: list[float] = []
        for ep in episodes:
            text_blob = " ".join(str(ep.get(k, "")) for k in (
                "action", "subject", "content", "category",
            )).lower()
            if any(kw in text_blob for kw in keywords):
                raw_score = ep.get("score")
                if raw_score is None:
                    continue
                try:
                    s = float(raw_score)
                except (TypeError, ValueError):
                    continue
                # Normalize 1-5 scale to 0-1
                if s > 1.0:
                    s = max(0.0, min(1.0, (s - 1.0) / 4.0))
                else:
                    s = max(0.0, min(1.0, s))
                relevant.append(s)

        if not relevant:
            return None, 0.0, 0
        avg = sum(relevant) / len(relevant)
        # Confidence grows with sample size, saturates at ~10 episodes
        conf = min(0.9, len(relevant) / 10.0)
        return avg, conf, len(relevant)

    @staticmethod
    def _step_prior_score(step: Any) -> Optional[float]:
        """Pull a prior expected score out of a PlanStep / dict.

        Uses estimated_impact (from PlanStep) as the default proxy
        for "expected outcome quality" if no other field is set.
        """
        for attr in ("expected_score", "estimated_impact"):
            v = _attr_or_key(step, attr)
            if v is not None:
                try:
                    return max(0.0, min(1.0, float(v)))
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _step_prior_confidence(step: Any) -> float:
        v = _attr_or_key(step, "confidence")
        if v is None:
            return 0.5
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.5

    @staticmethod
    def _step_prior_cost(step: Any) -> Optional[float]:
        for attr in ("expected_cost", "estimated_cost", "cost"):
            v = _attr_or_key(step, attr)
            if v is not None:
                try:
                    return max(0.0, min(1.0, float(v)))
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _step_description(step: Any) -> str:
        if isinstance(step, str):
            return step
        v = _attr_or_key(step, "description")
        if v:
            return str(v)
        return str(step)

    @staticmethod
    def _plan_what(plan: Any) -> str:
        v = _attr_or_key(plan, "goal_what")
        if v:
            return str(v)
        v = _attr_or_key(plan, "what")
        if v:
            return str(v)
        return ""

    @staticmethod
    def _plan_steps(plan: Any) -> list[Any]:
        v = _attr_or_key(plan, "steps")
        if isinstance(v, list):
            return v
        return []


# ── Helpers ───────────────────────────────────────────────────


_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "for", "with", "to", "in", "on",
    "at", "by", "from", "this", "that", "is", "are", "be", "do", "did",
    "does", "have", "has", "had", "it", "its", "as", "we", "i", "all",
    "any", "some", "into", "out", "up", "down", "over", "under",
    "via", "per",
})

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.]+")


def _extract_keywords(text: str) -> list[str]:
    """Tokenize a step description and drop stopwords + tiny words.

    Dotted/underscored compound tokens (e.g. ``engine.pricing``,
    ``customer_journey``) are kept whole AND split into their parts so
    a step containing ``engine.pricing`` matches a memory action of
    just ``pricing``.
    """
    if not text:
        return []
    words = [w.lower() for w in _WORD_RE.findall(text)]
    out: list[str] = []
    for w in words:
        if len(w) > 2 and w not in _STOPWORDS:
            out.append(w)
            # Also yield each part of dotted/underscored compounds
            for part in re.split(r"[._]", w):
                if part != w and len(part) > 2 and part not in _STOPWORDS:
                    out.append(part)
    # Dedupe while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for w in out:
        if w not in seen:
            seen.add(w)
            deduped.append(w)
    return deduped[:8]


def _attr_or_key(obj: Any, name: str) -> Any:
    """Read an attribute or dict key, returning None if absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


# ── LLM evaluator (instance method patched on by class) ──────


def _imagination_llm_evaluate(self, step: Any) -> Optional[ImaginedOutcome]:
    """LLM-backed step evaluator.

    Returns an ImaginedOutcome built from the LLM response, or
    None on any failure (no LLM, unparseable JSON, exception). The
    public imagine_step() falls back to the heuristic evaluator
    on None.
    """
    desc = self._step_description(step)
    if not desc:
        return None

    llm = self._get_llm()
    if llm is None:
        return None
    try:
        if not llm.is_available():
            return None
    except Exception:  # noqa: BLE001
        return None

    try:
        from core.system.prompt_library import get_prompt
    except Exception:  # noqa: BLE001
        return None
    template = get_prompt("imagination.evaluate_step")
    if template is None:
        return None

    # Build a small context block from current SelfModel + memory
    context_lines: list[str] = []
    if self._self_model is not None:
        try:
            strengths = self._self_model.strengths(top_n=2)
            if strengths:
                context_lines.append(
                    "Strengths: " + ", ".join(s["name"] for s in strengths)
                )
            weaknesses = self._self_model.weaknesses(top_n=2)
            if weaknesses:
                context_lines.append(
                    "Weaknesses: " + ", ".join(w["name"] for w in weaknesses)
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("self-model context fetch failed: %s", exc)
    context_block = ("Self-model:\n" + "\n".join(context_lines) + "\n\n") if context_lines else ""

    rendered = template.render(
        step_description=desc,
        goal_what=self._current_goal or "(no parent goal)",
        context_block=context_block,
    )

    try:
        structured = llm.ask_structured(
            role=template.role,
            prompt=rendered.user,
            system_prompt=rendered.system,
            schema_hint=template.schema_hint,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Imagination LLM call failed: %s", exc)
        return None

    if not getattr(structured, "ok", False):
        return None

    data = structured.data or {}
    try:
        score = max(0.0, min(1.0, float(data.get("predicted_score", 0.5))))
        cost = max(0.0, min(1.0, float(data.get("predicted_cost", 0.5))))
        conf = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        return None

    risks_field = data.get("risks") or []
    risks = ", ".join(str(r) for r in risks_field[:3]) if isinstance(risks_field, list) else ""
    notes_parts = []
    if data.get("reasoning"):
        notes_parts.append(str(data["reasoning"])[:300])
    if risks:
        notes_parts.append(f"risks: {risks}")

    return ImaginedOutcome(
        description=desc,
        predicted_score=score,
        predicted_cost=cost,
        confidence=conf,
        sources=["llm"],
        notes="; ".join(notes_parts),
    )


def _imagination_get_llm(self) -> Any:
    """Lazily resolve the LLM adapter."""
    if self._llm is not None:
        return self._llm
    try:
        from core.system.llm_adapter import get_llm
        return get_llm()
    except Exception:  # noqa: BLE001
        return None


# Patch onto the class so subclasses can override cleanly
Imagination._llm_evaluate = _imagination_llm_evaluate
Imagination._get_llm = _imagination_get_llm


# ── Singleton accessor ────────────────────────────────────────


_instance: Optional[Imagination] = None


def get_imagination() -> Imagination:
    global _instance
    if _instance is None:
        _instance = Imagination()
    return _instance
