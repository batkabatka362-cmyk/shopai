"""Cognitive core — true-autonomy layer on top of brain/memory/intelligence.

This package adds the missing pieces that turn a reactive engine pipeline
into a self-directed cognitive system:

    self_model       introspection: what I can do, what I don't know
    goals            self-directed goal generation + hierarchy + revision
    reflection       meta-cognition: reviewing past decisions for lessons
    planner          LLM-backed plan decomposition + backtracking  (phase 2)
    imagination      counterfactual simulation of hypothetical futures (phase 2)
    curiosity        knowledge-gap driven exploration                 (phase 2)
    consolidation    "sleep" phase — reprocessing + pruning memories  (phase 3)
    skill_registry   runtime skill acquisition + validation           (phase 3)
    theory_of_mind   customer / competitor models                     (phase 3)
    mind             unified cognitive loop                           (phase 4)

Each module is independently importable and testable. The `mind` module
at the top ties them together into the main cognitive cycle.
"""
from core.cognitive.consolidation import (
    Consolidation,
    ConsolidationReport,
    get_consolidation,
)
from core.cognitive.curiosity import (
    Curiosity,
    CuriosityCandidate,
    CuriosityRecommendation,
    get_curiosity,
)
from core.cognitive.skill_registry import (
    Skill,
    SkillNotFound,
    SkillNotInvocable,
    SkillRegistry,
    get_skill_registry,
)
from core.cognitive.goals import GoalManager, get_goal_manager
from core.cognitive.imagination import (
    ImaginedOutcome,
    ImaginedPlan,
    Imagination,
    get_imagination,
)
from core.cognitive.planner import (
    HeuristicPlanBackend,
    LLMPlanBackend,
    Plan,
    Planner,
    PlanStep,
    get_planner,
)
from core.cognitive.reflection import (
    Lesson,
    Reflection,
    ReflectionReport,
    get_reflection,
)
from core.cognitive.self_model import SelfModel, get_self_model

__all__ = [
    "SelfModel", "get_self_model",
    "GoalManager", "get_goal_manager",
    "Reflection", "ReflectionReport", "Lesson", "get_reflection",
    "Planner", "Plan", "PlanStep",
    "LLMPlanBackend", "HeuristicPlanBackend",
    "get_planner",
    "Imagination", "ImaginedOutcome", "ImaginedPlan", "get_imagination",
    "Curiosity", "CuriosityCandidate", "CuriosityRecommendation",
    "get_curiosity",
    "Consolidation", "ConsolidationReport", "get_consolidation",
    "SkillRegistry", "Skill", "SkillNotFound", "SkillNotInvocable",
    "get_skill_registry",
]
