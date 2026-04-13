"""SkillRegistry — runtime skill acquisition and invocation.

A "skill" is a named, callable, validated unit of behavior the AI
can decide to use. Skills are registered at runtime (not hardcoded)
so the system can grow new abilities while it's running, validate
them against history, and compose them into more complex behaviors.

A skill carries:

    name              unique identifier
    description       what it does
    signature         declared input/output schema (informal dict)
    implementation    callable: (inputs) → result dict
    tags              optional categorization
    accuracy          measured by validation against past episodes
    use_count         how many times invoked
    success_count     how many invocations met success_predicate
    last_used         epoch seconds

Lifecycle:

    1. propose(skill_def)
         Add the skill to the registry as `unvalidated`. It can't
         be invoked yet.

    2. validate(name, episodes, success_predicate)
         Run the skill against a list of past episodes (or any
         training set), measure how often the result matches the
         predicate, store an accuracy score. If accuracy >=
         min_accuracy (default 0.6), promote to `validated`.

    3. invoke(name, inputs)
         Call the implementation. Records the use, optionally
         scores the result via success_predicate, updates the
         skill's success_count.

    4. retire(name, reason)
         Move to `retired` state. Won't be invoked again but the
         history is kept for audit.

Composition: a skill's implementation can be a chain of other
skills via `compose(parent_name, child_names)`. The parent
implementation calls each child in sequence, threading outputs.

This is in-memory by design — skills are code, not data, so
persisting them across restarts requires re-importing the module
that defines them. The registry tracks metadata + accuracy + usage
in memory, which is what dashboards and the cognitive Mind care
about.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from utils.logger import get_logger

logger = get_logger("cognitive.skill_registry")


# ── Lifecycle states ──────────────────────────────────────────

STATE_UNVALIDATED = "unvalidated"
STATE_VALIDATED = "validated"
STATE_RETIRED = "retired"

ACTIVE_STATES = frozenset({STATE_UNVALIDATED, STATE_VALIDATED})

# Default minimum accuracy required for a skill to be promoted
_DEFAULT_MIN_ACCURACY = 0.6


SkillImpl = Callable[[dict[str, Any]], dict[str, Any]]
SuccessPredicate = Callable[[dict[str, Any]], bool]


@dataclass
class Skill:
    """A registered skill."""
    name: str
    description: str = ""
    signature: dict[str, Any] = field(default_factory=dict)
    implementation: Optional[SkillImpl] = None
    tags: list[str] = field(default_factory=list)
    state: str = STATE_UNVALIDATED
    accuracy: float = 0.0
    validated_against: int = 0   # number of episodes used in validation
    use_count: int = 0
    success_count: int = 0
    composed_of: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_used: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "signature": self.signature,
            "tags": list(self.tags),
            "state": self.state,
            "accuracy": round(self.accuracy, 3),
            "validated_against": self.validated_against,
            "use_count": self.use_count,
            "success_count": self.success_count,
            "success_rate": round(
                self.success_count / self.use_count, 3,
            ) if self.use_count else 0.0,
            "composed_of": list(self.composed_of),
            "created_at": self.created_at,
            "last_used": self.last_used,
        }


class SkillNotFound(KeyError):
    pass


class SkillNotInvocable(RuntimeError):
    pass


class SkillRegistry:
    """In-memory registry of runtime-defined skills."""

    def __init__(
        self,
        *,
        min_accuracy: float = _DEFAULT_MIN_ACCURACY,
    ) -> None:
        self._skills: dict[str, Skill] = {}
        self._min_accuracy = float(min_accuracy)
        self._lock = threading.RLock()

    # ── Registration ───────────────────────────────────────────

    def propose(
        self,
        name: str,
        implementation: SkillImpl,
        *,
        description: str = "",
        signature: Optional[dict] = None,
        tags: Optional[list[str]] = None,
    ) -> Skill:
        """Register a new skill in `unvalidated` state.

        It's stored but cannot be invoked until validate() promotes
        it to `validated`. Re-proposing the same name overwrites the
        existing skill (the previous validation/usage stats are
        reset because a new implementation is a new skill in
        practice).
        """
        if not name or not name.strip():
            raise ValueError("skill name required")
        if not callable(implementation):
            raise ValueError(
                f"skill {name!r}: implementation must be callable",
            )

        with self._lock:
            skill = Skill(
                name=name.strip(),
                description=description,
                signature=signature or {},
                implementation=implementation,
                tags=list(tags or []),
                state=STATE_UNVALIDATED,
            )
            self._skills[skill.name] = skill
            logger.info("Skill proposed: %s", skill.name)
            return skill

    def validate(
        self,
        name: str,
        episodes: list[dict[str, Any]],
        *,
        success_predicate: Optional[SuccessPredicate] = None,
        min_accuracy: Optional[float] = None,
    ) -> float:
        """Validate a skill against past episodes.

        Args:
            name: skill name
            episodes: list of past episodes; each episode should be a
                dict with at least an 'input' key. The skill is invoked
                with episode['input'] and the result is checked.
            success_predicate: callable(result) → bool. If None, the
                default predicate just checks `result.get("status") in
                ("ok", "success")`.
            min_accuracy: override the registry's default threshold.

        Returns:
            The measured accuracy (0..1). The skill is promoted to
            `validated` if accuracy ≥ threshold.
        """
        with self._lock:
            skill = self._skills.get(name)
            if skill is None:
                raise SkillNotFound(name)
            if skill.implementation is None:
                raise SkillNotInvocable(f"skill {name!r} has no implementation")
            if not episodes:
                logger.warning("Skill %s: no validation episodes", name)
                skill.accuracy = 0.0
                skill.validated_against = 0
                return 0.0

        predicate = success_predicate or _default_success_predicate
        successes = 0
        attempts = 0
        for ep in episodes:
            if not isinstance(ep, dict):
                continue
            inputs = ep.get("input")
            if inputs is None:
                continue
            attempts += 1
            try:
                result = skill.implementation(inputs)
                if not isinstance(result, dict):
                    continue
                if predicate(result):
                    successes += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Skill %s validation: implementation raised %s", name, exc,
                )

        threshold = (
            min_accuracy if min_accuracy is not None else self._min_accuracy
        )
        accuracy = (successes / attempts) if attempts > 0 else 0.0

        with self._lock:
            skill.accuracy = accuracy
            skill.validated_against = attempts
            if accuracy >= threshold:
                if skill.state != STATE_VALIDATED:
                    skill.state = STATE_VALIDATED
                    logger.info(
                        "Skill %s promoted: accuracy=%.2f ≥ %.2f",
                        name, accuracy, threshold,
                    )
            else:
                logger.info(
                    "Skill %s not promoted: accuracy=%.2f < %.2f",
                    name, accuracy, threshold,
                )
        return accuracy

    def retire(self, name: str, reason: str = "") -> None:
        """Move a skill to retired state. Cannot be invoked anymore."""
        with self._lock:
            skill = self._skills.get(name)
            if not skill:
                return
            skill.state = STATE_RETIRED
            logger.info("Skill retired: %s (%s)", name, reason)

    # ── Invocation ─────────────────────────────────────────────

    def invoke(
        self,
        name: str,
        inputs: dict[str, Any],
        *,
        success_predicate: Optional[SuccessPredicate] = None,
    ) -> dict[str, Any]:
        """Invoke a validated skill.

        Returns the implementation's result. Records the use,
        increments success_count if `success_predicate(result)` (or
        the default) is True. Raises if the skill isn't validated.
        """
        with self._lock:
            skill = self._skills.get(name)
            if skill is None:
                raise SkillNotFound(name)
            if skill.state != STATE_VALIDATED:
                raise SkillNotInvocable(
                    f"skill {name!r} is in state {skill.state!r}, "
                    "must be 'validated' to invoke",
                )
            if skill.implementation is None:
                raise SkillNotInvocable(f"skill {name!r} has no implementation")
            impl = skill.implementation

        # Run outside the lock to allow concurrent invocations
        try:
            result = impl(inputs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skill %s raised: %s", name, exc)
            with self._lock:
                skill.use_count += 1
                skill.last_used = time.time()
            return {"status": "error", "error": str(exc)[:200]}

        if not isinstance(result, dict):
            result = {"status": "error", "error": "skill returned non-dict"}

        predicate = success_predicate or _default_success_predicate
        with self._lock:
            skill.use_count += 1
            skill.last_used = time.time()
            if predicate(result):
                skill.success_count += 1
        return result

    # ── Composition ────────────────────────────────────────────

    def compose(
        self,
        name: str,
        child_names: list[str],
        *,
        description: str = "",
        tags: Optional[list[str]] = None,
    ) -> Skill:
        """Define a new skill as a chain of existing validated skills.

        The parent's implementation calls each child in order with
        the running result dict, merging the child's output back in.
        Children must already be validated; if any are missing or
        not validated, the composition fails fast.
        """
        if not child_names:
            raise ValueError("compose() requires at least one child")
        with self._lock:
            for child in child_names:
                s = self._skills.get(child)
                if s is None:
                    raise SkillNotFound(child)
                if s.state != STATE_VALIDATED:
                    raise SkillNotInvocable(
                        f"child skill {child!r} not validated "
                        f"(state={s.state!r})",
                    )

            # Build the chained implementation. We capture the registry
            # itself so each child invocation goes through invoke()
            # and updates per-child stats.
            registry = self

            def _chained(inputs: dict[str, Any]) -> dict[str, Any]:
                state = dict(inputs or {})
                for child in child_names:
                    out = registry.invoke(child, state)
                    if isinstance(out, dict):
                        state.update(out)
                state.setdefault("status", "success")
                return state

            skill = Skill(
                name=name.strip(),
                description=description or f"chain: {' → '.join(child_names)}",
                implementation=_chained,
                tags=list(tags or []),
                composed_of=list(child_names),
                state=STATE_UNVALIDATED,
            )
            self._skills[skill.name] = skill
            logger.info(
                "Composed skill: %s = %s", skill.name, " → ".join(child_names),
            )
            return skill

    # ── Read API ───────────────────────────────────────────────

    def get(self, name: str) -> Optional[Skill]:
        with self._lock:
            return self._skills.get(name)

    def list_skills(
        self,
        *,
        state: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> list[Skill]:
        with self._lock:
            out = list(self._skills.values())
        if state:
            out = [s for s in out if s.state == state]
        if tag:
            out = [s for s in out if tag in s.tags]
        out.sort(key=lambda s: (s.state, -s.accuracy, s.name))
        return out

    def stats(self) -> dict[str, Any]:
        with self._lock:
            skills = list(self._skills.values())
        by_state: dict[str, int] = {}
        for s in skills:
            by_state[s.state] = by_state.get(s.state, 0) + 1
        validated = [s for s in skills if s.state == STATE_VALIDATED]
        return {
            "total": len(skills),
            "by_state": by_state,
            "validated": len(validated),
            "avg_accuracy": (
                sum(s.accuracy for s in validated) / len(validated)
                if validated else 0.0
            ),
            "total_invocations": sum(s.use_count for s in skills),
            "total_successes": sum(s.success_count for s in skills),
        }


# ── Helpers ───────────────────────────────────────────────────


def _default_success_predicate(result: dict[str, Any]) -> bool:
    """Default: result['status'] is 'ok' or 'success'."""
    if not isinstance(result, dict):
        return False
    return result.get("status") in ("ok", "success", "completed")


# ── Singleton accessor ────────────────────────────────────────


_instance: Optional[SkillRegistry] = None
_instance_lock = threading.Lock()


def get_skill_registry() -> SkillRegistry:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SkillRegistry()
    return _instance
