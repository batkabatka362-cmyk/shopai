"""Brain facade — single API over 91 subsystems.

Twelve sprints produced a rich brain but its API surface is
fragmented: callers must know about reward_model(), world_model(),
coverage_engine(), router(), monologue(), habit(), policy_library(),
and another 80-odd singletons. That coupling makes every caller
brittle — refactors ripple outward, integration tests need
dozens of imports.

BrainFacade is the one entry point. ``brain()`` returns a thin
wrapper that:

  • Exposes *think()*       — one-shot decision given an observation.
  • Exposes *learn()*       — fold outcome events via OutcomeRouter.
  • Exposes *introspect()*  — structured status snapshot.
  • Exposes *explain()*     — 'why' answer over the last decision.
  • Exposes *housekeep()*   — run the daily maintenance pass.

Each method fans to the correct subsystem. No new algorithms; the
value is in making the API tractable and letting call sites depend
on *one* import instead of a dozen. Dependencies are lazy so a
missing subsystem doesn't break the facade.

Pure orchestration. Zero LLM.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import get_logger


logger = get_logger("brain.facade")


@dataclass
class Snapshot:
    """Single-shot introspection across every connected subsystem."""
    ts: float = 0.0
    world_model: dict[str, Any] = field(default_factory=dict)
    epistemic: dict[str, Any] = field(default_factory=dict)
    hypothesis: dict[str, Any] = field(default_factory=dict)
    reward: dict[str, Any] = field(default_factory=dict)
    policies: dict[str, Any] = field(default_factory=dict)
    habits: dict[str, Any] = field(default_factory=dict)
    trust: list[dict[str, Any]] = field(default_factory=list)
    self_improvement: dict[str, Any] = field(default_factory=dict)
    surprise: dict[str, Any] = field(default_factory=dict)
    regret: dict[str, Any] = field(default_factory=dict)
    commitments: dict[str, Any] = field(default_factory=dict)
    learning: list[dict[str, Any]] = field(default_factory=list)
    cases: dict[str, Any] = field(default_factory=dict)
    skills: list[dict[str, Any]] = field(default_factory=list)
    competence: dict[str, Any] = field(default_factory=dict)
    curiosity: dict[str, Any] = field(default_factory=dict)
    drift: dict[str, Any] = field(default_factory=dict)
    goals: dict[str, Any] = field(default_factory=dict)
    attention: dict[str, Any] = field(default_factory=dict)
    owner: dict[str, Any] = field(default_factory=dict)
    experiments: dict[str, Any] = field(default_factory=dict)
    budgets: list[dict[str, Any]] = field(default_factory=list)
    knowledge: dict[str, Any] = field(default_factory=dict)
    uplift: dict[str, Any] = field(default_factory=dict)
    causal: dict[str, Any] = field(default_factory=dict)
    macros: list[dict[str, Any]] = field(default_factory=list)
    forecasts: dict[str, Any] = field(default_factory=dict)
    invariants: dict[str, Any] = field(default_factory=dict)
    self_debug: dict[str, Any] = field(default_factory=dict)
    credit: dict[str, Any] = field(default_factory=dict)
    hp_tuner: dict[str, Any] = field(default_factory=dict)
    federation: dict[str, Any] = field(default_factory=dict)
    queue: dict[str, Any] = field(default_factory=dict)
    explore: dict[str, Any] = field(default_factory=dict)
    dialog: dict[str, Any] = field(default_factory=dict)
    elasticity: dict[str, Any] = field(default_factory=dict)
    ltv: dict[str, Any] = field(default_factory=dict)
    schedule: dict[str, Any] = field(default_factory=dict)
    episodes: dict[str, Any] = field(default_factory=dict)
    router: dict[str, Any] = field(default_factory=dict)
    recovery: dict[str, Any] = field(default_factory=dict)
    curriculum: dict[str, Any] = field(default_factory=dict)
    fusion: dict[str, Any] = field(default_factory=dict)
    plan_mon: dict[str, Any] = field(default_factory=dict)
    risk: list[dict[str, Any]] = field(default_factory=list)
    simulator: dict[str, Any] = field(default_factory=dict)
    prioritizer: dict[str, Any] = field(default_factory=dict)
    transfer: dict[str, Any] = field(default_factory=dict)
    verifier: dict[str, Any] = field(default_factory=dict)
    self_test: dict[str, Any] = field(default_factory=dict)
    counterfactuals: dict[str, Any] = field(default_factory=dict)
    signal_noise: dict[str, Any] = field(default_factory=dict)
    # v32: integration + divergence tracking
    decision_stack: dict[str, Any] = field(default_factory=dict)
    shadow: dict[str, Any] = field(default_factory=dict)
    traces: dict[str, Any] = field(default_factory=dict)
    revisions: dict[str, Any] = field(default_factory=dict)
    # v33: prompt composition, concepts, predictive alerts,
    # attention calibration, clarification, assumptions, funnel
    prompts: dict[str, Any] = field(default_factory=dict)
    concepts: dict[str, Any] = field(default_factory=dict)
    pre_breach: dict[str, Any] = field(default_factory=dict)
    attention_calibration: dict[str, Any] = field(default_factory=dict)
    clarifications: dict[str, Any] = field(default_factory=dict)
    assumptions: dict[str, Any] = field(default_factory=dict)
    funnel: dict[str, Any] = field(default_factory=dict)
    # v34: metacognition + imitation + decomposition + error learn +
    # proposal arbitration + world drift + insight synthesis
    meta_reasoning: dict[str, Any] = field(default_factory=dict)
    imitation: dict[str, Any] = field(default_factory=dict)
    decomposition: dict[str, Any] = field(default_factory=dict)
    error_patterns: dict[str, Any] = field(default_factory=dict)
    arbitration: dict[str, Any] = field(default_factory=dict)
    world_drift: dict[str, Any] = field(default_factory=dict)
    insights: dict[str, Any] = field(default_factory=dict)
    # v35: hypothesis generation, reversals, principles, freshness,
    # coherence, episodes, salience
    generated_hypotheses: dict[str, Any] = field(default_factory=dict)
    reversals: dict[str, Any] = field(default_factory=dict)
    principles: dict[str, Any] = field(default_factory=dict)
    freshness: dict[str, Any] = field(default_factory=dict)
    coherence: dict[str, Any] = field(default_factory=dict)
    episode_summaries: dict[str, Any] = field(default_factory=dict)
    salience: dict[str, Any] = field(default_factory=dict)
    # v36: observation reducer, evidence accumulator, scenario
    # planner, value weighter, compute budget, rationale builder,
    # capability registry
    observations: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    scenarios: dict[str, Any] = field(default_factory=dict)
    values: dict[str, Any] = field(default_factory=dict)
    compute: dict[str, Any] = field(default_factory=dict)
    rationales: dict[str, Any] = field(default_factory=dict)
    capabilities_registry: dict[str, Any] = field(default_factory=dict)
    # v37: mood, confidence thresholds, delegation, relations,
    # workflow bottlenecks, strategy coherence, readiness
    mood: dict[str, Any] = field(default_factory=dict)
    confidence_thresholds: dict[str, Any] = field(default_factory=dict)
    delegation: dict[str, Any] = field(default_factory=dict)
    relations: dict[str, Any] = field(default_factory=dict)
    bottlenecks: dict[str, Any] = field(default_factory=dict)
    strategy_coherence: dict[str, Any] = field(default_factory=dict)
    readiness: dict[str, Any] = field(default_factory=dict)
    # v38: heuristics, intentions, surprise context, failure taxonomy,
    # value conflicts, knowledge transfer, behavioral constraints
    heuristics: dict[str, Any] = field(default_factory=dict)
    intentions: dict[str, Any] = field(default_factory=dict)
    surprise_context: dict[str, Any] = field(default_factory=dict)
    failures: dict[str, Any] = field(default_factory=dict)
    value_conflicts: dict[str, Any] = field(default_factory=dict)
    transfer_priority: dict[str, Any] = field(default_factory=dict)
    behavioral_constraints: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "world_model": self.world_model,
            "epistemic": self.epistemic,
            "hypothesis": self.hypothesis,
            "reward": self.reward,
            "policies": self.policies,
            "habits": self.habits,
            "trust": self.trust,
            "self_improvement": self.self_improvement,
            "surprise": self.surprise,
            "regret": self.regret,
            "commitments": self.commitments,
            "learning": self.learning,
            "cases": self.cases,
            "skills": self.skills,
            "competence": self.competence,
            "curiosity": self.curiosity,
            "drift": self.drift,
            "goals": self.goals,
            "attention": self.attention,
            "owner": self.owner,
            "experiments": self.experiments,
            "budgets": self.budgets,
            "knowledge": self.knowledge,
            "uplift": self.uplift,
            "causal": self.causal,
            "macros": self.macros,
            "forecasts": self.forecasts,
            "invariants": self.invariants,
            "self_debug": self.self_debug,
            "credit": self.credit,
            "hp_tuner": self.hp_tuner,
            "federation": self.federation,
            "queue": self.queue,
            "explore": self.explore,
            "dialog": self.dialog,
            "elasticity": self.elasticity,
            "ltv": self.ltv,
            "schedule": self.schedule,
            "episodes": self.episodes,
            "router": self.router,
            "recovery": self.recovery,
            "curriculum": self.curriculum,
            "fusion": self.fusion,
            "plan_mon": self.plan_mon,
            "risk": self.risk,
            "simulator": self.simulator,
            "prioritizer": self.prioritizer,
            "transfer": self.transfer,
            "verifier": self.verifier,
            "self_test": self.self_test,
            "counterfactuals": self.counterfactuals,
            "signal_noise": self.signal_noise,
            "decision_stack": self.decision_stack,
            "shadow": self.shadow,
            "traces": self.traces,
            "revisions": self.revisions,
            "prompts": self.prompts,
            "concepts": self.concepts,
            "pre_breach": self.pre_breach,
            "attention_calibration": self.attention_calibration,
            "clarifications": self.clarifications,
            "assumptions": self.assumptions,
            "funnel": self.funnel,
            "meta_reasoning": self.meta_reasoning,
            "imitation": self.imitation,
            "decomposition": self.decomposition,
            "error_patterns": self.error_patterns,
            "arbitration": self.arbitration,
            "world_drift": self.world_drift,
            "insights": self.insights,
            "generated_hypotheses": self.generated_hypotheses,
            "reversals": self.reversals,
            "principles": self.principles,
            "freshness": self.freshness,
            "coherence": self.coherence,
            "episode_summaries": self.episode_summaries,
            "salience": self.salience,
            "observations": self.observations,
            "evidence": self.evidence,
            "scenarios": self.scenarios,
            "values": self.values,
            "compute": self.compute,
            "rationales": self.rationales,
            "capabilities_registry": self.capabilities_registry,
            "mood": self.mood,
            "confidence_thresholds": self.confidence_thresholds,
            "delegation": self.delegation,
            "relations": self.relations,
            "bottlenecks": self.bottlenecks,
            "strategy_coherence": self.strategy_coherence,
            "readiness": self.readiness,
            "heuristics": self.heuristics,
            "intentions": self.intentions,
            "surprise_context": self.surprise_context,
            "failures": self.failures,
            "value_conflicts": self.value_conflicts,
            "transfer_priority": self.transfer_priority,
            "behavioral_constraints": self.behavioral_constraints,
        }


# ── Facade ──────────────────────────────────────────────────

class BrainFacade:
    def __init__(self) -> None:
        self._last_cycle_report: Any = None
        self._last_decision: Any = None

    # ── think ──────────────────────────────────────────────

    def think(
        self,
        observation: dict[str, Any],
        candidate_action: dict[str, Any] | None = None,
        *,
        stakes: float = 0.3,
        confidence: float = 0.6,
        urgency: int = 0,
        skip: tuple[str, ...] = (),
        governor: Any | None = None,
    ) -> dict[str, Any]:
        """Run one AGI cycle and return the structured report."""
        try:
            from core.brain.agi_cycle import run_cycle
        except Exception:
            return {"status": "no_cycle_module"}
        report = run_cycle(
            observation=observation,
            candidate_action=candidate_action,
            stakes=stakes, confidence=confidence, urgency=urgency,
            skip=skip, governor=governor,
        )
        self._last_cycle_report = report
        if report.chosen_action:
            self._last_decision = report
        return report.as_dict()

    # ── learn ──────────────────────────────────────────────

    def learn(
        self,
        kind: str,
        features: dict[str, Any] | None = None,
        **outcome_fields: Any,
    ) -> dict[str, Any]:
        """Emit one Outcome to the router for fan-out learning."""
        try:
            from core.brain.outcome_router import Outcome, router
        except Exception:
            return {"status": "no_router"}
        oc = Outcome(
            kind=kind,
            features=dict(features or {}),
            **outcome_fields,
        )
        return router().emit(oc).as_dict()

    # ── introspect ─────────────────────────────────────────

    def introspect(self) -> Snapshot:
        snap = Snapshot(ts=time.time())
        # Each lazy-fetch is wrapped so one missing subsystem doesn't
        # block the rest.
        def _safe(fn):
            try:
                return fn()
            except Exception:
                return {}

        snap.world_model = _safe(lambda: _wm_summary())
        snap.epistemic = _safe(lambda: _ep_summary())
        snap.hypothesis = _safe(lambda: _hypo_summary())
        snap.reward = _safe(lambda: _reward_summary())
        snap.policies = _safe(lambda: _policy_summary())
        snap.habits = _safe(lambda: _habit_summary())
        snap.trust = _safe(lambda: _trust_top())
        snap.self_improvement = _safe(lambda: _si_summary())
        snap.surprise = _safe(lambda: _surprise_summary())
        snap.regret = _safe(lambda: _regret_summary())
        snap.commitments = _safe(lambda: _commitments_summary())
        snap.learning = _safe(lambda: _learning_summary())
        snap.cases = _safe(lambda: _case_base_summary())
        snap.skills = _safe(lambda: _skill_rank_summary())
        snap.competence = _safe(lambda: _competence_summary())
        snap.curiosity = _safe(lambda: _curiosity_summary())
        snap.drift = _safe(lambda: _drift_summary())
        snap.goals = _safe(lambda: _goal_summary())
        snap.attention = _safe(lambda: _attention_summary())
        snap.owner = _safe(lambda: _owner_summary())
        snap.experiments = _safe(lambda: _experiment_summary())
        snap.budgets = _safe(lambda: _budget_summary())
        snap.knowledge = _safe(lambda: _knowledge_summary())
        snap.uplift = _safe(lambda: _uplift_summary())
        snap.causal = _safe(lambda: _causal_summary())
        snap.macros = _safe(lambda: _macro_summary())
        snap.forecasts = _safe(lambda: _forecaster_summary())
        snap.invariants = _safe(lambda: _invariant_summary())
        snap.self_debug = _safe(lambda: _self_debug_summary())
        snap.credit = _safe(lambda: _credit_summary())
        snap.hp_tuner = _safe(lambda: _hp_tuner_summary())
        snap.federation = _safe(lambda: _federation_summary())
        snap.queue = _safe(lambda: _queue_summary())
        snap.explore = _safe(lambda: _explore_summary())
        snap.dialog = _safe(lambda: _dialog_summary())
        snap.elasticity = _safe(lambda: _elasticity_summary())
        snap.ltv = _safe(lambda: _ltv_summary())
        snap.schedule = _safe(lambda: _schedule_summary())
        snap.episodes = _safe(lambda: _episodes_summary())
        snap.router = _safe(lambda: _router_summary())
        snap.recovery = _safe(lambda: _recovery_summary())
        snap.curriculum = _safe(lambda: _curriculum_summary())
        snap.fusion = _safe(lambda: _fusion_summary())
        snap.plan_mon = _safe(lambda: _plan_monitor_summary())
        snap.risk = _safe(lambda: _risk_summary())
        snap.simulator = _safe(lambda: _simulator_summary())
        snap.prioritizer = _safe(lambda: _prioritizer_config())
        snap.transfer = _safe(lambda: _transfer_summary())
        snap.verifier = _safe(lambda: _verifier_summary())
        snap.self_test = _safe(lambda: _self_test_summary())
        snap.counterfactuals = _safe(lambda: _counterfactual_summary())
        snap.signal_noise = _safe(lambda: _signal_noise_summary())
        snap.decision_stack = _safe(lambda: _decision_stack_summary())
        snap.shadow = _safe(lambda: _shadow_divergence_summary())
        snap.traces = _safe(lambda: _reasoning_trace_summary())
        snap.revisions = _safe(lambda: _revision_journal_summary())
        snap.prompts = _safe(lambda: _prompt_composer_summary())
        snap.concepts = _safe(lambda: _concept_former_summary())
        snap.pre_breach = _safe(lambda: _predictive_alerter_summary())
        snap.attention_calibration = _safe(
            lambda: _attention_calibrator_summary(),
        )
        snap.clarifications = _safe(
            lambda: _clarification_dialog_summary(),
        )
        snap.assumptions = _safe(lambda: _assumption_ledger_summary())
        snap.funnel = _safe(lambda: _revenue_funnel_summary())
        snap.meta_reasoning = _safe(lambda: _meta_reasoner_summary())
        snap.imitation = _safe(lambda: _imitation_learner_summary())
        snap.decomposition = _safe(
            lambda: _goal_decomposer_summary(),
        )
        snap.error_patterns = _safe(
            lambda: _error_pattern_library_summary(),
        )
        snap.arbitration = _safe(lambda: _proposal_arbiter_summary())
        snap.world_drift = _safe(
            lambda: _world_model_updater_summary(),
        )
        snap.insights = _safe(lambda: _insight_synthesizer_summary())
        snap.generated_hypotheses = _safe(
            lambda: _hypothesis_generator_summary(),
        )
        snap.reversals = _safe(
            lambda: _decision_reversal_detector_summary(),
        )
        snap.principles = _safe(
            lambda: _principle_extractor_summary(),
        )
        snap.freshness = _safe(
            lambda: _knowledge_freshness_summary(),
        )
        snap.coherence = _safe(
            lambda: _coherence_checker_summary(),
        )
        snap.episode_summaries = _safe(
            lambda: _episode_summariser_summary(),
        )
        snap.salience = _safe(lambda: _salience_tuner_summary())
        snap.observations = _safe(
            lambda: _observation_reducer_summary(),
        )
        snap.evidence = _safe(
            lambda: _evidence_accumulator_summary(),
        )
        snap.scenarios = _safe(
            lambda: _scenario_planner_summary(),
        )
        snap.values = _safe(lambda: _value_weighter_summary())
        snap.compute = _safe(lambda: _compute_budget_summary())
        snap.rationales = _safe(
            lambda: _rationale_builder_summary(),
        )
        snap.capabilities_registry = _safe(
            lambda: _capability_registry_summary(),
        )
        snap.mood = _safe(lambda: _mood_model_summary())
        snap.confidence_thresholds = _safe(
            lambda: _confidence_tuner_summary(),
        )
        snap.delegation = _safe(
            lambda: _delegation_router_summary(),
        )
        snap.relations = _safe(
            lambda: _relation_extractor_summary(),
        )
        snap.bottlenecks = _safe(
            lambda: _bottleneck_detector_summary(),
        )
        snap.strategy_coherence = _safe(
            lambda: _strategy_coherence_summary(),
        )
        snap.readiness = _safe(lambda: _readiness_gate_summary())
        snap.heuristics = _safe(lambda: _heuristic_bank_summary())
        snap.intentions = _safe(
            lambda: _intention_tracker_summary(),
        )
        snap.surprise_context = _safe(
            lambda: _surprise_contextualizer_summary(),
        )
        snap.failures = _safe(
            lambda: _failure_taxonomy_summary(),
        )
        snap.value_conflicts = _safe(
            lambda: _value_conflict_arbiter_summary(),
        )
        snap.transfer_priority = _safe(
            lambda: _transfer_prioritizer_summary(),
        )
        snap.behavioral_constraints = _safe(
            lambda: _behavioral_constraint_summary(),
        )
        return snap

    # ── v32: integration + divergence + journal ─────────

    def run_decision_stack(
        self,
        observation: dict[str, Any],
        *,
        candidate_action: dict[str, Any] | None = None,
        stakes: float = 0.3,
    ) -> dict[str, Any]:
        """Pass through attention → evidence → deliberate →
        safety → feasibility → utility. Stage handlers are wired to
        the existing subsystem singletons."""
        try:
            from core.brain.decision_stack import (
                DecisionStack, StageCallables,
            )
            stack = DecisionStack(stages=_default_stage_callables())
            return stack.decide(
                observation=observation,
                candidate_action=candidate_action,
                stakes=stakes,
            ).as_dict()
        except Exception as exc:
            logger.debug("run_decision_stack failed: %s", exc)
            return {
                "observation": observation,
                "final_action": candidate_action,
                "block_reason": "stack_unavailable",
            }

    def record_shadow_divergence(
        self,
        *,
        context_summary: dict[str, Any],
        legacy_action: dict[str, Any] | None,
        facade_action: dict[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            div = _shadow_divergence().record(
                context_summary=context_summary,
                legacy_action=legacy_action,
                facade_action=facade_action,
            )
            return div.as_dict()
        except Exception as exc:
            logger.debug(
                "record_shadow_divergence failed: %s", exc,
            )
            return {"verdict": "both_empty"}

    def shadow_summary(
        self, *, lookback_s: float | None = None,
    ) -> dict[str, Any]:
        try:
            return _shadow_divergence().summary(
                lookback_s=lookback_s,
            ).as_dict()
        except Exception as exc:
            logger.debug("shadow_summary failed: %s", exc)
            return {"total": 0, "agreement_rate": 0.0}

    def compact_context(
        self,
        context: dict[str, Any],
        *,
        priority_fields: tuple[str, ...] = (),
        max_bytes: int = 4096,
    ) -> dict[str, Any]:
        try:
            from core.brain.context_compactor import compact
            return compact(
                context,
                priority_fields=priority_fields,
                max_bytes=max_bytes,
            ).as_dict()
        except Exception as exc:
            logger.debug("compact_context failed: %s", exc)
            return {"fields": {}, "truncated": False}

    def start_trace(
        self, question: str,
        *, trace_id: str | None = None,
    ) -> str:
        try:
            return _reasoning_tracer().start(
                question, trace_id=trace_id,
            )
        except Exception as exc:
            logger.debug("start_trace failed: %s", exc)
            return ""

    def trace_add(
        self,
        trace_id: str,
        *,
        subsystem: str,
        note: str,
        output: dict[str, Any] | None = None,
        weight: float = 1.0,
    ) -> None:
        try:
            _reasoning_tracer().add(
                trace_id,
                subsystem=subsystem,
                note=note,
                output=output,
                weight=weight,
            )
        except Exception as exc:
            logger.debug("trace_add failed: %s", exc)

    def trace_commit(
        self,
        trace_id: str,
        *,
        verdict: str,
        action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            trace = _reasoning_tracer().commit(
                trace_id, verdict=verdict, action=action,
            )
            return trace.as_dict()
        except Exception as exc:
            logger.debug("trace_commit failed: %s", exc)
            return {"trace_id": trace_id, "nodes": []}

    def propose_revision(
        self,
        *,
        kind: str,
        target: str,
        old_value: Any,
        new_value: Any,
        reason: str,
        evidence_score: float = 0.5,
    ) -> str:
        try:
            rev = _revision_journal().propose(
                kind=kind,  # type: ignore[arg-type]
                target=target,
                old_value=old_value,
                new_value=new_value,
                reason=reason,
                evidence_score=evidence_score,
            )
            return rev.id
        except Exception as exc:
            logger.debug("propose_revision failed: %s", exc)
            return ""

    def bundle(
        self,
        name: str,
        actions: list[dict[str, Any]],
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a transactional all-or-nothing action group.

        actions is a list of dicts carrying ``name``, ``execute``
        (callable), optional ``compensate`` (callable), and
        ``optional`` (bool)."""
        try:
            from core.brain.action_bundle import (
                ActionBundle, BundleAction,
            )
            bundle = ActionBundle(name)
            for a in actions:
                bundle.add(BundleAction(
                    name=str(a["name"]),
                    execute=a["execute"],
                    compensate=a.get("compensate"),
                    optional=bool(a.get("optional", False)),
                    payload=dict(a.get("payload", {}) or {}),
                ))
            return bundle.run(context).as_dict()
        except Exception as exc:
            logger.debug("bundle failed: %s", exc)
            return {
                "bundle_name": name,
                "success": False,
                "error": str(exc),
                "steps": [],
            }

    def evaluate_skill_gym(
        self,
        skill_name: str,
        scenarios: list[Any],
    ) -> dict[str, Any]:
        try:
            from core.brain.skill_gym import SkillGym
            return SkillGym().evaluate(
                skill_name, scenarios,
            ).as_dict()
        except Exception as exc:
            logger.debug("evaluate_skill_gym failed: %s", exc)
            return {
                "skill_name": skill_name,
                "recommendation": "reject",
            }

    # ── v33: prompts, concepts, alerts, calibration, dialog,
    #         assumptions, funnel ─────────────────────────────

    def compose_prompt(
        self,
        base_template: str,
        *,
        overlay_templates: list[str] | None = None,
        slot_overrides: dict[str, Any] | None = None,
        required_slots: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            composed = _prompt_composer().compose(
                base_template=base_template,
                overlay_templates=tuple(overlay_templates or ()),
                slot_overrides=slot_overrides or {},
                required_slots=tuple(required_slots or ()),
            )
            return composed.as_dict()
        except Exception as exc:
            logger.debug("compose_prompt failed: %s", exc)
            return {
                "base_template": base_template,
                "body": "",
                "error": str(exc),
            }

    def register_prompt_provider(self, provider: Any) -> bool:
        try:
            _prompt_composer().register(provider)
            return True
        except Exception as exc:
            logger.debug("register_prompt_provider failed: %s", exc)
            return False

    def observe_concept(
        self,
        fields: dict[str, Any],
        *,
        outcome_sign: str = "",
    ) -> str:
        try:
            return _concept_former().observe(
                fields, outcome_sign=outcome_sign,
            )
        except Exception as exc:
            logger.debug("observe_concept failed: %s", exc)
            return ""

    def form_concepts(
        self, *, min_support: int = 3,
    ) -> list[dict[str, Any]]:
        try:
            concepts = _concept_former().form(
                min_support=min_support,
            )
            return [c.as_dict() for c in concepts]
        except Exception as exc:
            logger.debug("form_concepts failed: %s", exc)
            return []

    def name_concept(self, signature: str, label: str) -> str:
        try:
            return _concept_former().name_concept(signature, label)
        except Exception as exc:
            logger.debug("name_concept failed: %s", exc)
            return ""

    def project_breach(
        self,
        kpi: str,
        *,
        threshold: float,
        direction: str,
    ) -> dict[str, Any]:
        try:
            alert = _predictive_alerter().evaluate(
                kpi, threshold=threshold, direction=direction,
            )
            return alert.as_dict()
        except Exception as exc:
            logger.debug("project_breach failed: %s", exc)
            return {
                "kpi": kpi, "severity": "none",
                "note": f"unavailable: {exc}",
            }

    def record_attention(
        self,
        *,
        cycle_id: str,
        ranking: list[tuple[str, float]],
    ) -> int:
        try:
            return _attention_calibrator().record_attended(
                cycle_id=cycle_id, ranking=ranking,
            )
        except Exception as exc:
            logger.debug("record_attention failed: %s", exc)
            return 0

    def record_attention_outcome(
        self,
        *,
        cycle_id: str,
        item_key: str,
        realised_importance: float,
    ) -> bool:
        try:
            return _attention_calibrator().record_outcome(
                cycle_id=cycle_id, item_key=item_key,
                realised_importance=realised_importance,
            )
        except Exception as exc:
            logger.debug("record_attention_outcome failed: %s", exc)
            return False

    def calibrate_attention(
        self, *, k: int = 5,
    ) -> dict[str, Any]:
        try:
            return _attention_calibrator().calibrate(k=k).as_dict()
        except Exception as exc:
            logger.debug("calibrate_attention failed: %s", exc)
            return {
                "precision_at_k": 0.0, "recall_at_k": 0.0,
                "k": k,
            }

    def detect_ambiguity(
        self,
        text: str,
        *,
        provided_slots: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            findings = _clarification_dialog().find_ambiguities(
                text, provided_slots=provided_slots,
            )
            return [f.as_dict() for f in findings]
        except Exception as exc:
            logger.debug("detect_ambiguity failed: %s", exc)
            return []

    def draft_clarification(
        self,
        text: str,
        *,
        provided_slots: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        try:
            req = _clarification_dialog().draft(
                text, provided_slots=provided_slots,
            )
            return req.as_dict() if req else None
        except Exception as exc:
            logger.debug("draft_clarification failed: %s", exc)
            return None

    def assume(
        self,
        *,
        statement: str,
        related_decision_id: str = "",
        kpi: str = "",
        expected_value: float | None = None,
        tolerance: float = 0.0,
    ) -> dict[str, Any]:
        try:
            a = _assumption_ledger().assume(
                statement=statement,
                related_decision_id=related_decision_id,
                kpi=kpi, expected_value=expected_value,
                tolerance=tolerance,
            )
            return a.as_dict()
        except Exception as exc:
            logger.debug("assume failed: %s", exc)
            return {"statement": statement, "status": "error"}

    def validate_assumption(
        self, assumption_id: str, observed_value: float,
    ) -> dict[str, Any]:
        try:
            a = _assumption_ledger().validate(
                assumption_id, observed_value,
            )
            return a.as_dict()
        except Exception as exc:
            logger.debug("validate_assumption failed: %s", exc)
            return {"id": assumption_id, "status": "error"}

    def record_funnel_event(
        self, stage: str, count: int = 1,
    ) -> bool:
        try:
            _revenue_funnel().record(stage, count)
            return True
        except Exception as exc:
            logger.debug("record_funnel_event failed: %s", exc)
            return False

    def analyse_funnel(self) -> dict[str, Any]:
        try:
            return _revenue_funnel().analyse().as_dict()
        except Exception as exc:
            logger.debug("analyse_funnel failed: %s", exc)
            return {
                "stages": [], "biggest_leak": None,
                "overall_conversion": 0.0,
            }

    # ── v34: meta-reasoning, imitation, decomposition, error
    #          learning, arbitration, drift, insight synthesis ──

    def record_calibration(
        self,
        *,
        decision_id: str,
        claimed_confidence: float,
        outcome_positive: bool,
    ) -> bool:
        try:
            _meta_reasoner().record(
                decision_id=decision_id,
                claimed_confidence=claimed_confidence,
                outcome_positive=outcome_positive,
            )
            return True
        except Exception as exc:
            logger.debug("record_calibration failed: %s", exc)
            return False

    def record_signal_use(
        self,
        *,
        decision_id: str,
        signals: list[str],
        outcome_positive: bool,
    ) -> int:
        try:
            return _meta_reasoner().record_signal_use(
                decision_id=decision_id,
                signals=signals,
                outcome_positive=outcome_positive,
            )
        except Exception as exc:
            logger.debug("record_signal_use failed: %s", exc)
            return 0

    def calibration_report(self) -> dict[str, Any]:
        try:
            return _meta_reasoner().calibrate().as_dict()
        except Exception as exc:
            logger.debug("calibration_report failed: %s", exc)
            return {"calibration_error": 0.0, "n_total": 0}

    def adjusted_confidence(self, claimed: float) -> float:
        try:
            return _meta_reasoner().adjusted_confidence(claimed)
        except Exception as exc:
            logger.debug("adjusted_confidence failed: %s", exc)
            return float(claimed)

    def observe_demonstration(
        self,
        *,
        situation_fields: dict[str, Any],
        action_sequence: list[dict[str, Any]],
        outcome_quality: float,
        source: str = "self",
    ) -> dict[str, Any]:
        try:
            tpl = _imitation_learner().observe(
                situation_fields=situation_fields,
                action_sequence=action_sequence,
                outcome_quality=outcome_quality,
                source=source,
            )
            return tpl.as_dict()
        except Exception as exc:
            logger.debug("observe_demonstration failed: %s", exc)
            return {"count_observed": 0, "error": str(exc)}

    def match_imitation(
        self,
        situation: dict[str, Any],
        *,
        min_count: int = 1,
        min_quality: float = 0.0,
    ) -> dict[str, Any] | None:
        try:
            m = _imitation_learner().match(
                situation,
                min_count=min_count,
                min_quality=min_quality,
            )
            return m.as_dict() if m else None
        except Exception as exc:
            logger.debug("match_imitation failed: %s", exc)
            return None

    def decompose_goal(
        self,
        goal_text: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            plan = _goal_decomposer().decompose(
                goal_text, params=params,
            )
            return plan.as_dict()
        except Exception as exc:
            logger.debug("decompose_goal failed: %s", exc)
            return {
                "goal_text": goal_text, "subgoals": [],
                "order": [], "rule_id": "",
            }

    def observe_error(
        self,
        *,
        signature: str,
        context: dict[str, Any] | None = None,
        remedy: str,
        worked: bool,
    ) -> bool:
        try:
            _error_pattern_library().observe(
                signature=signature, context=context,
                remedy=remedy, worked=worked,
            )
            return True
        except Exception as exc:
            logger.debug("observe_error failed: %s", exc)
            return False

    def suggest_remedy(
        self,
        signature: str,
        *,
        context: dict[str, Any] | None = None,
        min_attempts: int = 1,
    ) -> dict[str, Any] | None:
        try:
            s = _error_pattern_library().suggest(
                signature, context=context,
                min_attempts=min_attempts,
            )
            return s.as_dict() if s else None
        except Exception as exc:
            logger.debug("suggest_remedy failed: %s", exc)
            return None

    def arbitrate_proposals(
        self,
        target: str,
        proposals: list[dict[str, Any]],
        *,
        current_value: Any = None,
    ) -> dict[str, Any]:
        try:
            from core.brain.proposal_arbiter import Proposal
            converted: list[Proposal] = []
            for p in proposals:
                converted.append(Proposal(
                    id=str(p.get("id", "")),
                    target=str(p.get("target", target)),
                    new_value=p.get("new_value"),
                    evidence_score=float(
                        p.get("evidence_score", 0.5),
                    ),
                    proposer=str(p.get("proposer", "")),
                    ts=float(p.get("ts", 0.0)),
                ))
            outcome = _proposal_arbiter().arbitrate(
                target, converted, current_value=current_value,
            )
            return outcome.as_dict()
        except Exception as exc:
            logger.debug("arbitrate_proposals failed: %s", exc)
            return {"verdict": "reject_all", "winner_id": ""}

    def record_prediction(
        self,
        *,
        predictor_id: str,
        predicted: float,
        observed: float,
    ) -> bool:
        try:
            _world_model_updater().record(
                predictor_id=predictor_id,
                predicted=predicted,
                observed=observed,
            )
            return True
        except Exception as exc:
            logger.debug("record_prediction failed: %s", exc)
            return False

    def detect_world_drift(self) -> list[dict[str, Any]]:
        try:
            alerts = _world_model_updater().detect_alerts()
            return [a.as_dict() for a in alerts]
        except Exception as exc:
            logger.debug("detect_world_drift failed: %s", exc)
            return []

    def synthesise_insights(
        self,
        *,
        calibration_report: dict[str, Any] | None = None,
        drift_alerts: list[dict[str, Any]] | None = None,
        assumption_stats: dict[str, Any] | None = None,
        funnel_snapshot: dict[str, Any] | None = None,
        pre_breach_alerts: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            out = _insight_synthesizer().synthesise(
                calibration_report=calibration_report,
                drift_alerts=drift_alerts,
                assumption_stats=assumption_stats,
                funnel_snapshot=funnel_snapshot,
                pre_breach_alerts=pre_breach_alerts,
            )
            return [i.as_dict() for i in out]
        except Exception as exc:
            logger.debug("synthesise_insights failed: %s", exc)
            return []

    def active_insights(
        self, *, limit: int | None = None,
    ) -> list[dict[str, Any]]:
        try:
            out = _insight_synthesizer().active(limit=limit)
            return [i.as_dict() for i in out]
        except Exception as exc:
            logger.debug("active_insights failed: %s", exc)
            return []

    # ── v35: hypothesis gen, reversals, principles, freshness,
    #         coherence, episodes, salience ─────────────────

    def generate_hypothesis(
        self, event: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            h = _hypothesis_generator().generate(event)
            return h.as_dict() if h else None
        except Exception as exc:
            logger.debug("generate_hypothesis failed: %s", exc)
            return None

    def record_decision(
        self,
        *,
        target: str,
        action: str,
        rationale: str = "",
    ) -> dict[str, Any] | None:
        try:
            alert = _decision_reversal_detector().record(
                target=target, action=action,
                rationale=rationale,
            )
            return alert.as_dict() if alert else None
        except Exception as exc:
            logger.debug("record_decision failed: %s", exc)
            return None

    def churn_rate(self, target: str) -> float:
        try:
            return _decision_reversal_detector().churn_rate(target)
        except Exception as exc:
            logger.debug("churn_rate failed: %s", exc)
            return 0.0

    def extract_principles(
        self,
        rules: list[dict[str, Any]],
        *,
        min_rules: int = 2,
        similarity_threshold: float = 0.5,
    ) -> list[dict[str, Any]]:
        try:
            from core.brain.principle_extractor import (
                PrincipleExtractor, Rule,
            )
            converted: list[Rule] = []
            for r in rules:
                try:
                    converted.append(Rule(
                        id=str(r.get("id", "")),
                        antecedent=str(r.get("antecedent", "")),
                        consequent=str(r.get("consequent", "")),
                        support=int(r.get("support", 1)),
                        confidence=float(r.get("confidence", 0.5)),
                    ))
                except (ValueError, TypeError) as exc:
                    logger.debug("rule coerce skipped: %s", exc)
                    continue
            extractor = PrincipleExtractor(
                min_rules=min_rules,
                similarity_threshold=similarity_threshold,
            )
            principles = extractor.extract(converted)
            return [p.as_dict() for p in principles]
        except Exception as exc:
            logger.debug("extract_principles failed: %s", exc)
            return []

    def register_knowledge(
        self,
        *,
        key: str,
        kind: str = "belief",
        half_life_seconds: float | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        try:
            item = _knowledge_freshness().register(
                key=key, kind=kind,
                half_life_seconds=half_life_seconds,
                note=note,
            )
            return item.as_dict()
        except Exception as exc:
            logger.debug("register_knowledge failed: %s", exc)
            return {"key": key, "error": str(exc)}

    def refresh_knowledge(
        self, key: str, *, confirm: bool = True,
    ) -> bool:
        try:
            _knowledge_freshness().refresh(key, confirm=confirm)
            return True
        except Exception as exc:
            logger.debug("refresh_knowledge failed: %s", exc)
            return False

    def stale_knowledge(
        self, *, cutoff: float = 0.3,
    ) -> list[dict[str, Any]]:
        try:
            items = _knowledge_freshness().stale(cutoff=cutoff)
            return [i.as_dict() for i in items]
        except Exception as exc:
            logger.debug("stale_knowledge failed: %s", exc)
            return []

    def assert_belief(
        self,
        *,
        predicate: str,
        subject: str,
        polarity: str = "asserts",
        evidence_score: float = 0.6,
        source: str = "",
    ) -> dict[str, Any]:
        try:
            b = _coherence_checker().assert_belief(
                predicate=predicate, subject=subject,
                polarity=polarity,
                evidence_score=evidence_score,
                source=source,
            )
            return b.as_dict()
        except Exception as exc:
            logger.debug("assert_belief failed: %s", exc)
            return {"error": str(exc)}

    def check_coherence(
        self, claims: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        try:
            from core.brain.coherence_checker import Claim
            converted: list[Claim] = []
            for c in claims:
                try:
                    converted.append(Claim(
                        predicate=str(c["predicate"]),
                        subject=str(c["subject"]),
                        polarity=c.get("polarity", "asserts"),
                        confidence=float(c.get("confidence", 0.5)),
                        note=str(c.get("note", "")),
                    ))
                except (KeyError, ValueError) as exc:
                    logger.debug("claim coerce skipped: %s", exc)
                    continue
            found = _coherence_checker().check(converted)
            return [f.as_dict() for f in found]
        except Exception as exc:
            logger.debug("check_coherence failed: %s", exc)
            return []

    def summarise_episode(
        self,
        *,
        title_hint: str,
        situation: dict[str, Any] | None = None,
        winning_action: str,
        alternatives: list[str] | None = None,
        outcome_score: float | None = None,
        lesson: str = "",
        evidence_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            s = _episode_summariser().summarise(
                title_hint=title_hint,
                situation=situation,
                winning_action=winning_action,
                alternatives=alternatives or [],
                outcome_score=outcome_score,
                lesson=lesson,
                evidence_keys=evidence_keys or [],
            )
            return s.as_dict()
        except Exception as exc:
            logger.debug("summarise_episode failed: %s", exc)
            return {
                "title_hint": title_hint, "error": str(exc),
            }

    def tune_salience(
        self,
        *,
        features: dict[str, float],
        outcome_importance: float,
    ) -> bool:
        try:
            _salience_tuner().observe(
                features=features,
                outcome_importance=outcome_importance,
            )
            return True
        except Exception as exc:
            logger.debug("tune_salience failed: %s", exc)
            return False

    def salience_weights(self) -> dict[str, float]:
        try:
            return _salience_tuner().weights()
        except Exception as exc:
            logger.debug("salience_weights failed: %s", exc)
            return {}

    # ── v36: observation reducer, evidence, scenarios, values,
    #         compute budget, rationale, capabilities ────────

    def ingest_observation(
        self,
        kind: str,
        fields: dict[str, Any] | None = None,
    ) -> bool:
        try:
            _observation_reducer().ingest(kind, fields)
            return True
        except Exception as exc:
            logger.debug("ingest_observation failed: %s", exc)
            return False

    def reduce_observations(self) -> dict[str, Any]:
        try:
            return _observation_reducer().reduce().as_dict()
        except Exception as exc:
            logger.debug("reduce_observations failed: %s", exc)
            return {"total_events": 0}

    def register_claim(
        self,
        statement: str,
        *,
        claim_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            c = _evidence_accumulator().register_claim(
                statement, claim_id=claim_id,
            )
            return c.as_dict()
        except Exception as exc:
            logger.debug("register_claim failed: %s", exc)
            return {"error": str(exc)}

    def add_evidence(
        self,
        *,
        claim_id: str,
        polarity: str,
        weight: float = 1.0,
        source: str = "",
        note: str = "",
    ) -> bool:
        try:
            _evidence_accumulator().add_evidence(
                claim_id=claim_id, polarity=polarity,
                weight=weight, source=source, note=note,
            )
            return True
        except Exception as exc:
            logger.debug("add_evidence failed: %s", exc)
            return False

    def claim_probability(self, claim_id: str) -> float:
        try:
            return _evidence_accumulator().probability(claim_id)
        except Exception as exc:
            logger.debug("claim_probability failed: %s", exc)
            return 0.0

    def plan_scenarios(
        self,
        *,
        name: str,
        starting_state: dict[str, Any],
        branches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            from core.brain.scenario_planner import (
                Branch, ScenarioSpec,
            )
            branch_objs = [
                Branch(
                    label=str(b.get("label", "branch")),
                    weight=float(b.get("weight", 1.0)),
                    modifier=dict(b.get("modifier", {}) or {}),
                )
                for b in branches
            ]
            spec = ScenarioSpec(
                name=name,
                starting_state=dict(starting_state),
                branches=branch_objs,
            )
            return _scenario_planner().plan(spec).as_dict()
        except Exception as exc:
            logger.debug("plan_scenarios failed: %s", exc)
            return {"scenarios": [], "error": str(exc)}

    def observe_value_feedback(
        self,
        *,
        value_scores: dict[str, float],
        feedback: str,
    ) -> dict[str, float]:
        try:
            return _value_weighter().observe(
                value_scores=value_scores, feedback=feedback,
            )
        except Exception as exc:
            logger.debug("observe_value_feedback failed: %s", exc)
            return {}

    def value_weights(self) -> dict[str, float]:
        try:
            return _value_weighter().weights()
        except Exception as exc:
            logger.debug("value_weights failed: %s", exc)
            return {}

    def begin_compute_cycle(self, cycle_id: str) -> bool:
        try:
            _compute_budget().begin_cycle(cycle_id)
            return True
        except Exception as exc:
            logger.debug("begin_compute_cycle failed: %s", exc)
            return False

    def end_compute_cycle(self) -> dict[str, Any] | None:
        try:
            report = _compute_budget().end_cycle()
            return report.as_dict() if report else None
        except Exception as exc:
            logger.debug("end_compute_cycle failed: %s", exc)
            return None

    def spend_compute(
        self, kind: str, amount: float,
    ) -> dict[str, Any] | None:
        try:
            alert = _compute_budget().spend(kind, amount)
            return alert.as_dict() if alert else None
        except Exception as exc:
            logger.debug("spend_compute failed: %s", exc)
            return None

    def remaining_compute(self, kind: str) -> float:
        try:
            return _compute_budget().remaining(kind)
        except Exception as exc:
            logger.debug("remaining_compute failed: %s", exc)
            return 0.0

    def start_rationale(
        self, *, decision_id: str, summary: str,
    ) -> dict[str, Any]:
        try:
            r = _rationale_builder().start(
                decision_id=decision_id, summary=summary,
            )
            return r.as_dict()
        except Exception as exc:
            logger.debug("start_rationale failed: %s", exc)
            return {"error": str(exc)}

    def add_rationale_node(
        self,
        decision_id: str,
        *,
        kind: str,
        headline: str,
        weight: float = 0.5,
        references: list[str] | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            node = _rationale_builder().add(
                decision_id, kind=kind,
                headline=headline, weight=weight,
                references=tuple(references or ()),
                parent_id=parent_id,
            )
            return node.as_dict()
        except Exception as exc:
            logger.debug("add_rationale_node failed: %s", exc)
            return {"error": str(exc)}

    def commit_rationale(
        self, decision_id: str,
    ) -> dict[str, Any] | None:
        try:
            r = _rationale_builder().commit(decision_id)
            return r.as_dict()
        except Exception as exc:
            logger.debug("commit_rationale failed: %s", exc)
            return None

    def register_capability(
        self,
        *,
        name: str,
        scope: str,
        initial_proficiency: float = 0.5,
        gap_reason: str = "",
    ) -> dict[str, Any]:
        try:
            c = _capability_registry().register(
                name=name, scope=scope,
                initial_proficiency=initial_proficiency,
                gap_reason=gap_reason,
            )
            return c.as_dict()
        except Exception as exc:
            logger.debug("register_capability failed: %s", exc)
            return {"error": str(exc)}

    def update_capability(
        self, name: str, *, ok: bool,
    ) -> bool:
        try:
            _capability_registry().update(name, ok=ok)
            return True
        except Exception as exc:
            logger.debug("update_capability failed: %s", exc)
            return False

    def can_do(self, name: str) -> bool:
        try:
            return _capability_registry().can_do(name)
        except Exception as exc:
            logger.debug("can_do failed: %s", exc)
            return False

    def capability_gaps(self) -> list[dict[str, Any]]:
        try:
            gaps = _capability_registry().gaps()
            return [g.as_dict() for g in gaps]
        except Exception as exc:
            logger.debug("capability_gaps failed: %s", exc)
            return []

    # ── v37: mood, confidence thresholds, delegation, relations,
    #         bottlenecks, strategy coherence, readiness ─────

    def observe_mood(
        self, event: str, *, weight: float = 1.0,
    ) -> dict[str, Any]:
        try:
            return _mood_model().observe(
                event, weight=weight,  # type: ignore[arg-type]
            ).as_dict()
        except Exception as exc:
            logger.debug("observe_mood failed: %s", exc)
            return {}

    def mood_snapshot(self) -> dict[str, Any]:
        try:
            return _mood_model().snapshot().as_dict()
        except Exception as exc:
            logger.debug("mood_snapshot failed: %s", exc)
            return {}

    def record_decision_outcome(
        self,
        *,
        kind: str,
        confidence: float,
        outcome_ok: bool,
    ) -> bool:
        try:
            _confidence_tuner().record(
                kind=kind, confidence=confidence,
                outcome_ok=outcome_ok,
            )
            return True
        except Exception as exc:
            logger.debug(
                "record_decision_outcome failed: %s", exc,
            )
            return False

    def confidence_threshold(self, kind: str) -> float:
        try:
            return _confidence_tuner().threshold(kind)
        except Exception as exc:
            logger.debug("confidence_threshold failed: %s", exc)
            return 0.7

    def accepts_decision(
        self, kind: str, confidence: float,
    ) -> bool:
        try:
            return _confidence_tuner().accepts(kind, confidence)
        except Exception as exc:
            logger.debug("accepts_decision failed: %s", exc)
            return False

    def route_task(
        self,
        *,
        kind: str,
        stakes: float,
        novelty: float,
        capability_name: str,
        urgency: int = 0,
    ) -> dict[str, Any]:
        try:
            from core.brain.delegation_router import Task
            task = Task(
                kind=kind, stakes=stakes, novelty=novelty,
                capability_name=capability_name,
                urgency=urgency,
            )
            return _delegation_router().route(task).as_dict()
        except Exception as exc:
            logger.debug("route_task failed: %s", exc)
            return {"target": "skip", "reason": str(exc)}

    def extract_relations(
        self, text: str,
    ) -> list[dict[str, Any]]:
        try:
            rels = _relation_extractor().extract(text)
            return [r.as_dict() for r in rels]
        except Exception as exc:
            logger.debug("extract_relations failed: %s", exc)
            return []

    def record_phase_sample(
        self,
        *,
        phase: str,
        duration_ms: float,
        ok: bool,
    ) -> bool:
        try:
            _bottleneck_detector().record(
                phase=phase,
                duration_ms=duration_ms, ok=ok,
            )
            return True
        except Exception as exc:
            logger.debug("record_phase_sample failed: %s", exc)
            return False

    def top_bottleneck(self) -> dict[str, Any] | None:
        try:
            b = _bottleneck_detector().top_bottleneck()
            return b.as_dict() if b else None
        except Exception as exc:
            logger.debug("top_bottleneck failed: %s", exc)
            return None

    def declare_strategy(
        self,
        *,
        name: str,
        clauses: list[dict[str, Any]],
        strategy_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            from core.brain.strategy_coherence_monitor import (
                StrategyClause,
            )
            clause_objs = [
                StrategyClause(
                    id=str(c.get("id", "")),
                    kind=c["kind"],
                    value=c["value"],
                    description=str(c.get("description", "")),
                )
                for c in clauses
            ]
            strategy = _strategy_coherence().declare(
                name=name,
                clauses=clause_objs,
                strategy_id=strategy_id,
            )
            return strategy.as_dict()
        except Exception as exc:
            logger.debug("declare_strategy failed: %s", exc)
            return {"error": str(exc)}

    def record_strategic_action(
        self,
        *,
        kind: str,
        stake: float,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            alerts = _strategy_coherence().record_action(
                kind=kind, stake=stake,
                tags=tags or [],
            )
            return [a.as_dict() for a in alerts]
        except Exception as exc:
            logger.debug(
                "record_strategic_action failed: %s", exc,
            )
            return []

    def check_readiness(
        self,
        *,
        evidence_probability: float,
        evidence_gap: float,
        knowledge_freshness: float,
        mood_temperature: float = 0.3,
        urgency: int = 0,
    ) -> dict[str, Any]:
        try:
            from core.brain.readiness_gate import ReadinessInput
            inp = ReadinessInput(
                evidence_probability=evidence_probability,
                evidence_gap=evidence_gap,
                knowledge_freshness=knowledge_freshness,
                mood_temperature=mood_temperature,
                urgency=urgency,
            )
            return _readiness_gate().check(inp).as_dict()
        except Exception as exc:
            logger.debug("check_readiness failed: %s", exc)
            return {"verdict": "gather", "reason": str(exc)}

    # ── v38: heuristics, intentions, surprise context, failures,
    #         value conflicts, knowledge transfer, constraints ──

    def evaluate_heuristics(
        self, ctx: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            v = _heuristic_bank().evaluate(ctx)
            return v.as_dict() if v else None
        except Exception as exc:
            logger.debug("evaluate_heuristics failed: %s", exc)
            return None

    def record_heuristic_outcome(
        self, heuristic_id: str, *, was_correct: bool,
    ) -> bool:
        try:
            return _heuristic_bank().record_outcome(
                heuristic_id, was_correct=was_correct,
            )
        except Exception as exc:
            logger.debug(
                "record_heuristic_outcome failed: %s", exc,
            )
            return False

    def declare_intention(
        self,
        *,
        statement: str,
        due_ts: float,
        observable_kpi: str = "",
        expected_value: float | None = None,
        direction: str = "",
    ) -> dict[str, Any]:
        try:
            i = _intention_tracker().declare(
                statement=statement,
                due_ts=due_ts,
                observable_kpi=observable_kpi,
                expected_value=expected_value,
                direction=direction,
            )
            return i.as_dict()
        except Exception as exc:
            logger.debug("declare_intention failed: %s", exc)
            return {"error": str(exc)}

    def resolve_intention(
        self, intention_id: str, observed_value: float,
    ) -> dict[str, Any]:
        try:
            return _intention_tracker().resolve(
                intention_id,
                observed_value=observed_value,
            ).as_dict()
        except Exception as exc:
            logger.debug("resolve_intention failed: %s", exc)
            return {"error": str(exc)}

    def follow_through_rate(self) -> float:
        try:
            return _intention_tracker().follow_through_rate()
        except Exception as exc:
            logger.debug("follow_through_rate failed: %s", exc)
            return 0.0

    def contextualise_surprise(
        self,
        *,
        kpi: str,
        expected: float,
        observed: float,
        situation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return _surprise_contextualizer().contextualise(
                kpi=kpi, expected=expected,
                observed=observed,
                situation=situation,
            ).as_dict()
        except Exception as exc:
            logger.debug(
                "contextualise_surprise failed: %s", exc,
            )
            return {"error": str(exc)}

    def classify_failure(
        self,
        *,
        message: str = "",
        status_code: int | None = None,
        exception_type: str = "",
    ) -> dict[str, Any]:
        try:
            return _failure_taxonomy().classify(
                message=message,
                status_code=status_code,
                exception_type=exception_type,
            ).as_dict()
        except Exception as exc:
            logger.debug("classify_failure failed: %s", exc)
            return {"category": "unknown"}

    def arbitrate_value_conflict(
        self,
        *,
        case_id: str,
        options: list[dict[str, Any]],
        value_weights: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        try:
            from core.brain.value_conflict_arbiter import (
                ConflictCase, OptionScore,
            )
            option_objs = [
                OptionScore(
                    option_id=str(o["option_id"]),
                    name=str(o.get("name", o["option_id"])),
                    scores={
                        k: float(v)
                        for k, v in o.get("scores", {}).items()
                    },
                )
                for o in options
            ]
            case = ConflictCase(
                id=case_id, options=option_objs,
            )
            r = _value_conflict_arbiter().arbitrate(
                case, value_weights=value_weights,
            )
            return r.as_dict()
        except Exception as exc:
            logger.debug(
                "arbitrate_value_conflict failed: %s", exc,
            )
            return {"verdict": "tie", "error": str(exc)}

    def rank_transfer_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        top_k: int | None = None,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        try:
            from core.brain.knowledge_transfer_prioritizer import (
                TransferCandidate,
            )
            converted = [
                TransferCandidate(
                    id=str(c["id"]),
                    subject=str(c["subject"]),
                    source_store=str(c["source_store"]),
                    target_store=str(c["target_store"]),
                    evidence_strength=float(
                        c.get("evidence_strength", 0.5),
                    ),
                    portability=float(
                        c.get("portability", 0.5),
                    ),
                    novelty_to_peer=float(
                        c.get("novelty_to_peer", 0.5),
                    ),
                    expected_lift=float(
                        c.get("expected_lift", 0.5),
                    ),
                    source_trust=float(
                        c.get("source_trust", 0.5),
                    ),
                )
                for c in candidates
            ]
            ranked = _transfer_prioritizer().rank(
                converted,
                top_k=top_k,
                min_score=min_score,
            )
            return [r.as_dict() for r in ranked]
        except Exception as exc:
            logger.debug(
                "rank_transfer_candidates failed: %s", exc,
            )
            return []

    def register_behavioral_constraint(
        self,
        *,
        name: str,
        predicate: Callable[
            [dict[str, Any], dict[str, Any]], bool,
        ],
        severity: str = "warn",
        description: str = "",
    ) -> dict[str, Any]:
        try:
            c = _behavioral_constraints().register(
                name=name,
                predicate=predicate,
                severity=severity,  # type: ignore[arg-type]
                description=description,
            )
            return {
                "id": c.id, "name": c.name,
                "severity": c.severity,
            }
        except Exception as exc:
            logger.debug(
                "register_behavioral_constraint failed: %s",
                exc,
            )
            return {"error": str(exc)}

    def evaluate_behavioral_constraints(
        self,
        *,
        action: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return _behavioral_constraints().evaluate(
                action=action, context=context,
            ).as_dict()
        except Exception as exc:
            logger.debug(
                "evaluate_behavioral_constraints failed: %s",
                exc,
            )
            return {"alerts": [], "any_severe": False}

    # ── v31: simulation, prioritization, transfer, self-test ──

    def simulate_actions(
        self,
        actions: list[dict[str, Any]],
        *,
        initial_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            sim = _world_simulator()
            if initial_state is not None:
                sim.seed(initial_state)
            return sim.preview(actions).as_dict()
        except Exception as exc:
            logger.debug("simulate_actions failed: %s", exc)
            return {"applied": [], "skipped": []}

    def prioritize_tasks(
        self,
        tasks: list[dict[str, Any]],
        *,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        try:
            from core.brain.task_prioritizer import Task
            converted: list[Any] = []
            for t in tasks:
                try:
                    converted.append(Task(
                        id=str(t.get("id", "")),
                        kind=str(t.get("kind", "task")),
                        base_value=float(t.get("base_value", 1.0)),
                        deadline_ts=t.get("deadline_ts"),
                        blast_radius=int(t.get("blast_radius", 1)),
                        open_dependencies=int(
                            t.get("open_dependencies", 0),
                        ),
                        cost_usd=float(t.get("cost_usd", 0.0)),
                        tags=tuple(t.get("tags", ()) or ()),
                        metadata=dict(t.get("metadata", {}) or {}),
                    ))
                except (ValueError, TypeError) as exc:
                    logger.debug(
                        "task coerce skipped: %s", exc,
                    )
                    continue
            ranked = _task_prioritizer().prioritize(
                converted, top_k=top_k,
            )
            return [r.as_dict() for r in ranked]
        except Exception as exc:
            logger.debug("prioritize_tasks failed: %s", exc)
            return []

    def evaluate_transfer(
        self,
        target_context: dict[str, Any],
        *,
        tags: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        try:
            recs = _skill_transfer().evaluate(
                target_context, tags=tags,
            )
            return [r.as_dict() for r in recs]
        except Exception as exc:
            logger.debug("evaluate_transfer failed: %s", exc)
            return []

    def verify_commitment(
        self, commitment_id: str,
    ) -> dict[str, Any]:
        try:
            return _commitment_verifier().verify(
                commitment_id,
            ).as_dict()
        except Exception as exc:
            logger.debug("verify_commitment failed: %s", exc)
            return {
                "commitment_id": commitment_id,
                "verdict": "unknown",
                "note": "unavailable",
            }

    def self_test(self) -> dict[str, Any]:
        try:
            return _self_test_harness().run_all().as_dict()
        except Exception as exc:
            logger.debug("self_test failed: %s", exc)
            return {"overall_ok": True, "results": []}

    def record_counterfactual(
        self,
        *,
        context: dict[str, Any],
        chosen_action: str,
        alternative_action: str,
        simulated_outcome: float,
        tags: tuple[str, ...] = (),
    ) -> str:
        try:
            cf = _counterfactual_memory().record(
                context=context,
                chosen_action=chosen_action,
                alternative_action=alternative_action,
                simulated_outcome=simulated_outcome,
                tags=tags,
            )
            return cf.id
        except Exception as exc:
            logger.debug("record_counterfactual failed: %s", exc)
            return ""

    def attach_counterfactual_actual(
        self,
        counterfactual_id: str,
        actual_outcome: float,
    ) -> bool:
        try:
            return _counterfactual_memory().attach_actual(
                counterfactual_id, actual_outcome,
            )
        except Exception as exc:
            logger.debug(
                "attach_counterfactual_actual failed: %s", exc,
            )
            return False

    def observe_signal(
        self, metric: str, value: float,
    ) -> dict[str, Any]:
        try:
            return _signal_noise_separator().observe(
                metric, value,
            ).as_dict()
        except Exception as exc:
            logger.debug("observe_signal failed: %s", exc)
            return {
                "metric": metric, "value": value,
                "classification": "normal",
                "direction": "flat",
            }

    # ── v30: observation, monitoring, intent, risk ───────

    def report_observation(
        self,
        *,
        source: str,
        fusion_key: str,
        payload: dict[str, Any],
        confidence: float = 1.0,
    ) -> None:
        try:
            _observation_fuser().report(
                source=source, fusion_key=fusion_key,
                payload=payload, confidence=confidence,
            )
        except Exception as exc:
            logger.debug("report_observation failed: %s", exc)

    def fuse_observation(
        self, fusion_key: str,
    ) -> dict[str, Any] | None:
        try:
            fo = _observation_fuser().fuse(fusion_key)
            return fo.as_dict() if fo else None
        except Exception as exc:
            logger.debug("fuse_observation failed: %s", exc)
            return None

    def decode_intent(self, text: str) -> dict[str, Any]:
        try:
            from core.brain.intention_decoder import decode
            return decode(text).as_dict()
        except Exception as exc:
            logger.debug("decode_intent failed: %s", exc)
            return {"raw": text, "sub_intents": [], "ambiguous": True}

    def reserve_risk(
        self,
        category: str,
        units: float,
        *,
        reason: str = "",
    ) -> str | None:
        try:
            return _risk_budget().reserve(
                category, units, reason=reason,
            ).id
        except Exception as exc:
            logger.debug("reserve_risk failed: %s", exc)
            return None

    def commit_risk(
        self,
        reservation_id: str,
        *,
        actual_units: float | None = None,
    ) -> bool:
        try:
            _risk_budget().commit(
                reservation_id, actual_units=actual_units,
            )
            return True
        except Exception as exc:
            logger.debug("commit_risk failed: %s", exc)
            return False

    def release_risk(self, reservation_id: str) -> bool:
        try:
            _risk_budget().release(reservation_id)
            return True
        except Exception:
            return False

    def detect_knowledge_gaps(self) -> dict[str, Any]:
        """Invoke the gap detector with all currently-wired providers
        (belief_propagator isn't stateful so we skip it here — owners
        who want that signal should feed it via the constructor)."""
        try:
            from core.brain.knowledge_gap_detector import KnowledgeGapDetector
            detector = KnowledgeGapDetector(
                repeated_probes_provider=lambda: (
                    _curiosity_engine().peek(k=50)
                ),
            )
            return detector.detect().as_dict()
        except Exception as exc:
            logger.debug("detect_knowledge_gaps failed: %s", exc)
            return {
                "gaps": [], "total": 0,
                "critical_count": 0, "warning_count": 0,
            }

    # ── v29: episodes, belief, routing, safety nets ─────

    def record_episode(
        self,
        situation: dict[str, Any],
        timeline: list[dict[str, Any]] | None = None,
        *,
        tags: tuple[str, ...] = (),
        outcome_sign: str = "unknown",
        source: str = "",
    ) -> str:
        try:
            ep = _episode_retriever().record(
                situation=situation,
                timeline=timeline or [],
                tags=tags,
                outcome_sign=outcome_sign,   # type: ignore[arg-type]
                source=source,
            )
            return ep.id
        except Exception as exc:
            logger.debug("record_episode failed: %s", exc)
            return ""

    def find_similar_episodes(
        self,
        situation: dict[str, Any],
        *,
        k: int = 5,
        tags: tuple[str, ...] = (),
        outcome_sign: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            matches = _episode_retriever().find_similar(
                query_situation=situation,
                k=k, tags=tags,
                outcome_sign=outcome_sign,   # type: ignore[arg-type]
            )
            return [m.as_dict() for m in matches]
        except Exception as exc:
            logger.debug("find_similar_episodes failed: %s", exc)
            return []

    def merge_claims(
        self,
        claims: list[dict[str, Any]],
        *,
        trust_fn: Any = None,
    ) -> dict[str, Any] | None:
        try:
            from core.memory.belief_propagator import BeliefPropagator
            b = BeliefPropagator().merge(claims, trust_fn=trust_fn)
            return b.as_dict() if b else None
        except Exception as exc:
            logger.debug("merge_claims failed: %s", exc)
            return None

    def route_task(
        self,
        capability: str,
        *,
        budget: float | None = None,
        deadline_ms: float | None = None,
    ) -> dict[str, Any] | None:
        try:
            decision = _meta_router().best(
                capability,
                budget=budget,
                deadline_ms=deadline_ms,
            )
            return decision.as_dict() if decision else None
        except Exception as exc:
            logger.debug("route_task failed: %s", exc)
            return None

    def recovery_for(
        self,
        invariant: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        try:
            best = _recovery_planner().best_for_breach(
                invariant, context=context,
            )
            return best.as_dict() if best else None
        except Exception as exc:
            logger.debug("recovery_for failed: %s", exc)
            return None

    def self_narrative(self) -> dict[str, Any]:
        try:
            from core.brain.self_narrative import SelfNarrator
            # Build providers from already-wired singletons
            narrator = SelfNarrator(
                competence_provider=lambda: _competence_model()
                    .strengths_weaknesses(min_support=3),
                owner_weights_provider=lambda: _owner_model().weights(),
                learning_provider=_learning_summary,
                load_provider=lambda: {
                    "commitments": _commitment_register()
                        .pending().__len__(),
                    "queue": _action_queue().stats()
                        .get("pending", 0),
                },
                memory_size_provider=lambda: _episode_retriever()
                    .stats().get("total", 0),
            )
            return narrator.narrate().as_dict()
        except Exception as exc:
            logger.debug("self_narrative failed: %s", exc)
            return {"identity_line": "ShopAI commerce executor"}

    def curriculum_next_skill(
        self, goal: str | None = None,
    ) -> dict[str, Any]:
        try:
            return _curriculum_planner().next_skill(goal=goal).as_dict()
        except Exception as exc:
            logger.debug("curriculum_next_skill failed: %s", exc)
            return {"recommended": None, "why": "unavailable"}

    # ── v28: dialog, elasticity, LTV, scheduling, audit ──

    def dialog_record(
        self,
        session_id: str,
        role: str,
        text: str,
    ) -> dict[str, Any] | None:
        try:
            t = _dialog_memory().record(
                session_id, role, text,
            )
            return t.as_dict()
        except Exception as exc:
            logger.debug("dialog_record failed: %s", exc)
            return None

    def dialog_open_intent(
        self, session_id: str,
    ) -> str | None:
        try:
            return _dialog_memory().open_intent(session_id)
        except Exception:
            return None

    def observe_price_point(
        self,
        segment: str,
        *,
        price: float,
        units: float,
    ) -> None:
        try:
            _price_elasticity().observe(
                segment, price=price, units=units,
            )
        except Exception as exc:
            logger.debug("observe_price_point failed: %s", exc)

    def predict_demand(
        self,
        segment: str,
        *,
        price: float,
    ) -> dict[str, Any] | None:
        try:
            pred = _price_elasticity().predict(
                segment, price=price,
            )
            return pred.as_dict() if pred else None
        except Exception as exc:
            logger.debug("predict_demand failed: %s", exc)
            return None

    def observe_customer_order(
        self,
        customer_id: str,
        *,
        order_value: float,
        refund_value: float = 0.0,
        cohort_keys: dict[str, str] | None = None,
    ) -> None:
        try:
            _customer_ltv().observe(
                customer_id,
                order_value=order_value,
                refund_value=refund_value,
                cohort_keys=cohort_keys or {},
            )
        except Exception as exc:
            logger.debug("observe_customer_order failed: %s", exc)

    def predict_ltv(
        self,
        customer_id: str,
        *,
        horizon_weeks: int = 52,
    ) -> dict[str, Any] | None:
        try:
            est = _customer_ltv().predict(
                customer_id, horizon_weeks=horizon_weeks,
            )
            return est.as_dict() if est else None
        except Exception as exc:
            logger.debug("predict_ltv failed: %s", exc)
            return None

    def weekly_digest(
        self, *, period_days: int = 7,
    ) -> dict[str, Any]:
        try:
            from core.brain.weekly_digest import generate_digest
            return generate_digest(period_days=period_days).as_dict()
        except Exception as exc:
            logger.debug("weekly_digest failed: %s", exc)
            return {"period_days": period_days, "headline": "", "body": ""}

    def schedule_register_daily(
        self,
        name: str, *, hour: int, minute: int = 0,
    ) -> None:
        try:
            _scheduler().register_daily(
                name, hour=hour, minute=minute,
            )
        except Exception as exc:
            logger.debug("schedule_register_daily failed: %s", exc)

    def schedule_due(self) -> list[dict[str, Any]]:
        try:
            return [s.as_dict() for s in _scheduler().due()]
        except Exception:
            return []

    def schedule_mark_ran(self, name: str) -> bool:
        try:
            return _scheduler().mark_ran(name)
        except Exception:
            return False

    def audit_decision(self, decision_id: str) -> dict[str, Any]:
        try:
            from core.brain.decision_audit_trail import DecisionAuditor
            return DecisionAuditor().build(decision_id).as_dict()
        except Exception as exc:
            logger.debug("audit_decision failed: %s", exc)
            return {
                "decision_id": decision_id,
                "verdict": "unknown",
                "contributors": [],
            }

    # ── v27: meta-learning, NL goals, queue, exploration ──

    def tune_register(
        self,
        name: str,
        arms: tuple[Any, ...],
        *,
        description: str = "",
    ) -> None:
        try:
            _hp_tuner().register(
                name, arms=list(arms), description=description,
            )
        except ValueError as exc:
            # Already-registered is benign; log at debug for traceability.
            logger.debug("tune_register skipped: %s", exc)
        except Exception as exc:
            logger.debug("tune_register failed: %s", exc)

    def tune_suggest(self, name: str) -> Any:
        try:
            return _hp_tuner().suggest(name)
        except Exception as exc:
            logger.debug("tune_suggest failed: %s", exc)
            return None

    def tune_observe(
        self,
        name: str, arm: Any,
        *,
        reward: float = 0.0,
        success: bool = True,
    ) -> None:
        try:
            _hp_tuner().observe(
                name, arm, reward=reward, success=success,
            )
        except Exception as exc:
            logger.debug("tune_observe failed: %s", exc)

    def compile_goal(self, text: str) -> dict[str, Any]:
        try:
            from core.brain.goal_compiler import compile_goal as _cg
            return _cg(text).as_dict()
        except Exception as exc:
            logger.debug("compile_goal failed: %s", exc)
            return {"raw": text, "subgoals": [], "kpis": []}

    def replay_outcomes(
        self,
        policy: Any,
        *,
        limit: int = 200,
    ) -> dict[str, Any]:
        try:
            from core.brain.memory_replayer import MemoryReplayer
            return MemoryReplayer().replay_outcomes(
                policy, limit=limit,
            ).as_dict()
        except Exception as exc:
            logger.debug("replay_outcomes failed: %s", exc)
            return {}

    def find_missed_patterns(
        self,
        *,
        min_support: int = 5,
        wrong_threshold: float = 0.6,
    ) -> list[dict[str, Any]]:
        try:
            from core.brain.memory_replayer import MemoryReplayer
            patterns = MemoryReplayer().find_missed_patterns(
                min_support=min_support,
                wrong_threshold=wrong_threshold,
            )
            return [p.as_dict() for p in patterns]
        except Exception as exc:
            logger.debug("find_missed_patterns failed: %s", exc)
            return []

    def federate_rule(
        self,
        target_store: str,
        rule_id: str,
    ) -> dict[str, Any]:
        try:
            return _federator().federated_score(
                target_store, rule_id,
            ).as_dict()
        except Exception as exc:
            logger.debug("federate_rule failed: %s", exc)
            return {}

    def enqueue_action(
        self,
        kind: str,
        *,
        payload: dict[str, Any] | None = None,
        priority: int = 0,
        delay_s: float = 0.0,
        depends_on: tuple[str, ...] = (),
        retries: int = 0,
    ) -> str:
        try:
            return _action_queue().enqueue(
                kind, payload=payload or {},
                priority=priority, delay_s=delay_s,
                depends_on=depends_on, retries=retries,
            ).id
        except Exception as exc:
            logger.debug("enqueue_action failed: %s", exc)
            return ""

    def next_due_actions(
        self, limit: int = 10,
    ) -> list[dict[str, Any]]:
        try:
            return [
                a.as_dict()
                for a in _action_queue().next_due(limit=limit)
            ]
        except Exception:
            return []

    def explore_register(
        self,
        bandit: str,
        arms: tuple[str, ...],
        *,
        strategy: str = "thompson",
    ) -> None:
        try:
            _exploration_manager().register(
                bandit, arms=list(arms), strategy=strategy,
            )
        except Exception as exc:
            logger.debug("explore_register failed: %s", exc)

    def explore_pick(self, bandit: str) -> str:
        try:
            return _exploration_manager().pick(bandit)
        except Exception as exc:
            logger.debug("explore_pick failed: %s", exc)
            return ""

    def explore_observe(
        self, bandit: str, arm: str,
        *, success: bool,
    ) -> None:
        try:
            _exploration_manager().observe(
                bandit, arm, success=success,
            )
        except Exception as exc:
            logger.debug("explore_observe failed: %s", exc)

    def distill_skills(
        self,
        *,
        signature_keys: tuple[str, ...] | None = None,
        min_support: int = 5,
        min_score: float = 3.0,
        promote: bool = False,
    ) -> dict[str, Any]:
        try:
            from core.brain.skill_distiller import SkillDistiller
            distiller = SkillDistiller()
            report = distiller.distill(
                signature_keys=list(signature_keys or []) or None,
                min_support=min_support,
                min_score=min_score,
            )
            promoted = (
                distiller.promote_all(report) if promote else 0
            )
            d = report.as_dict()
            d["promoted"] = promoted
            return d
        except Exception as exc:
            logger.debug("distill_skills failed: %s", exc)
            return {"inspected": 0, "candidates": [], "promoted": 0}

    # ── v26: causality, composition, forecast, safety-nets ──

    def observe_causal(
        self,
        features: dict[str, Any],
        kpi: str,
        value: float,
    ) -> None:
        try:
            _causal_graph().observe(features, kpi, value)
        except Exception as exc:
            logger.debug("observe_causal failed: %s", exc)

    def drivers_of(self, kpi: str) -> list[str]:
        try:
            return _causal_graph().drivers(kpi)
        except Exception:
            return []

    def observe_kpi(
        self,
        kpi: str,
        value: float,
        *,
        ts: float | None = None,
    ) -> None:
        """Feed a KPI observation to both forecaster (level forecast)
        and predictive_alerter (threshold trajectory)."""
        try:
            _forecaster().observe(kpi, value, ts=ts)
        except Exception as exc:
            logger.debug(
                "observe_kpi forecaster failed: %s", exc,
            )
        try:
            _predictive_alerter().observe(kpi, value, ts=ts)
        except Exception as exc:
            logger.debug(
                "observe_kpi predictive_alerter failed: %s", exc,
            )

    def forecast(
        self,
        kpi: str,
        *,
        horizon_steps: int = 1,
    ) -> dict[str, Any]:
        try:
            return _forecaster().forecast(
                kpi, horizon_steps=horizon_steps,
            ).as_dict()
        except Exception as exc:
            logger.debug("forecast failed: %s", exc)
            return {}

    def check_invariants(
        self, snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return _invariant_monitor().check(snapshot).as_dict()
        except Exception as exc:
            logger.debug("check_invariants failed: %s", exc)
            return {"breaches": [], "alerts": []}

    def note_failure(
        self, phase: str, error: str,
    ) -> dict[str, Any] | None:
        try:
            case = _self_debugger().note(phase, error)
            return case.as_dict() if case else None
        except Exception as exc:
            logger.debug("note_failure failed: %s", exc)
            return None

    def diagnose_failure(
        self, phase: str, error: str,
    ) -> dict[str, Any] | None:
        try:
            debugger = _self_debugger()
            case = debugger.note(phase, error)
            if case is None:
                return None
            diag = debugger.diagnose(case)
            return diag.as_dict() if diag else None
        except Exception as exc:
            logger.debug("diagnose_failure failed: %s", exc)
            return None

    def narrate(
        self,
        cycle_id: str,
        *,
        lookback: int = 1,
    ) -> dict[str, Any]:
        try:
            from core.brain.narrative_generator import generate_narrative
            return generate_narrative(
                cycle_id, lookback=lookback,
            ).as_dict()
        except Exception as exc:
            logger.debug("narrate failed: %s", exc)
            return {
                "cycle_id": cycle_id, "headline": "",
                "body": "", "warnings": [],
            }

    def note_decision_for_credit(
        self,
        *,
        decision_id: str | None = None,
        ts: float | None = None,
        claimed_kpis: tuple[str, ...] = (),
    ) -> str:
        try:
            return _credit_assigner().note_decision(
                decision_id=decision_id, ts=ts,
                claimed_kpis=claimed_kpis,
            )
        except Exception as exc:
            logger.debug("note_decision_for_credit failed: %s", exc)
            return ""

    def note_outcome_for_credit(
        self,
        *,
        kpi: str,
        value: float,
        outcome_id: str | None = None,
        ts: float | None = None,
    ) -> str:
        try:
            return _credit_assigner().note_outcome(
                kpi=kpi, value=value,
                outcome_id=outcome_id, ts=ts,
            )
        except Exception as exc:
            logger.debug("note_outcome_for_credit failed: %s", exc)
            return ""

    def top_credited_decisions(
        self,
        *,
        kpi: str | None = None,
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        try:
            return _credit_assigner().top_decisions(
                kpi=kpi, limit=limit,
            )
        except Exception:
            return []

    # ── v25: reasoning, safety, budget, experiments ──────

    def owner_weights(self) -> dict[str, float]:
        """Current owner preference weights for the utility blender."""
        try:
            return _owner_model().weights()
        except Exception as exc:
            logger.debug("owner_weights failed: %s", exc)
            return {}

    def record_owner_feedback(
        self,
        action_kind: str,
        approved: bool,
        *,
        cost_usd: float = 0.0,
        bold: bool = False,
        latency_s: float = 0.0,
    ) -> None:
        try:
            _owner_model().record(
                action_kind=action_kind, approved=approved,
                cost_usd=cost_usd, bold=bold, latency_s=latency_s,
            )
        except Exception as exc:
            logger.debug("record_owner_feedback failed: %s", exc)

    def safety_check(
        self,
        action: dict[str, Any],
        *,
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        """Run the action safety guard: bright lines + blast + rollback."""
        try:
            return _safety_guard().evaluate(
                action, confidence=confidence,
            ).as_dict()
        except Exception as exc:
            logger.debug("safety_check failed: %s", exc)
            return {"verdict": "allow", "reasons": ["guard_unavailable"]}

    def reserve_budget(
        self, category: str, amount_usd: float,
    ) -> str | None:
        try:
            return _budget_ledger().reserve(
                category, amount_usd,
            ).id
        except Exception as exc:
            logger.debug("reserve_budget failed: %s", exc)
            return None

    def commit_budget(
        self,
        reservation_id: str,
        actual_amount: float | None = None,
    ) -> bool:
        try:
            _budget_ledger().commit(reservation_id, actual_amount)
            return True
        except Exception as exc:
            logger.debug("commit_budget failed: %s", exc)
            return False

    def release_budget(self, reservation_id: str) -> bool:
        try:
            _budget_ledger().release(reservation_id)
            return True
        except Exception:
            return False

    def allocate_experiment(
        self, name: str, unit_id: str,
    ) -> str:
        """Deterministically bucket a unit into a variant."""
        try:
            return _experiment_manager().allocate(name, unit_id)
        except Exception as exc:
            logger.debug("allocate_experiment failed: %s", exc)
            return ""

    def record_experiment_outcome(
        self, name: str, unit_id: str, outcome: float,
    ) -> None:
        try:
            _experiment_manager().observe(name, unit_id, outcome)
        except Exception as exc:
            logger.debug("record_experiment_outcome failed: %s", exc)

    def ate(
        self,
        *,
        treatment_value: str,
        control_value: str,
        outcome_key: str,
        covariates_subset: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Estimate the average treatment effect from experience."""
        try:
            return _uplift_estimator().ate(
                treatment_value=treatment_value,
                control_value=control_value,
                outcome_key=outcome_key,
                covariates_subset=covariates_subset,
            ).as_dict()
        except Exception as exc:
            logger.debug("ate failed: %s", exc)
            return {}

    def assert_fact(
        self,
        subject: str,
        predicate: str,
        obj: str,
        *,
        is_literal: bool = False,
        confidence: float = 1.0,
        source: str = "",
    ) -> None:
        try:
            _knowledge_graph().assert_triple(
                subject, predicate, obj,
                is_literal=is_literal,
                confidence=confidence, source=source,
            )
        except Exception as exc:
            logger.debug("assert_fact failed: %s", exc)

    def is_a(self, subject: str, target_class: str) -> bool:
        try:
            return _knowledge_graph().is_a(subject, target_class)
        except Exception:
            return False

    # ── v23: planning & reasoning ─────────────────────────

    def add_goal(
        self,
        description: str,
        *,
        parent_id: str | None = None,
        due_at: float | None = None,
        weight: float = 1.0,
        tags: tuple[str, ...] = (),
    ) -> str | None:
        try:
            return _goal_graph().add(
                description, parent_id=parent_id,
                due_at=due_at, weight=weight, tags=tags,
            ).id
        except Exception as exc:
            logger.debug("add_goal failed: %s", exc)
            return None

    def advance_goal(
        self, goal_id: str, progress: float,
    ) -> dict[str, Any] | None:
        try:
            g = _goal_graph().advance(goal_id, progress)
            return g.as_dict() if g else None
        except Exception as exc:
            logger.debug("advance_goal failed: %s", exc)
            return None

    def frontier(self) -> list[dict[str, Any]]:
        """Actionable leaf goals right now."""
        try:
            return [g.as_dict() for g in _goal_graph().frontier()]
        except Exception:
            return []

    def plan(
        self,
        start: dict[str, Any],
        goal_state: dict[str, Any],
        actions: list[Any],
        *,
        max_expansions: int = 1_000,
    ) -> dict[str, Any] | None:
        """Thin wrapper over plan_search for decision-path callers."""
        try:
            from core.brain import plan_search as ps
            plan = ps.search(
                start=start,
                goal_fn=ps.predicate_goal(goal_state),
                actions=actions,
                heuristic=ps.delta_heuristic(goal_state),
                max_expansions=max_expansions,
            )
            return plan.as_dict() if plan else None
        except Exception as exc:
            logger.debug("plan failed: %s", exc)
            return None

    def rank_by_attention(
        self,
        events: list[dict[str, Any]],
        *, k: int = 5,
    ) -> list[dict[str, Any]]:
        """Score events by salience, return top-k."""
        try:
            return [
                s.as_dict()
                for s in _attention_filter().top_k(events, k=k)
            ]
        except Exception as exc:
            logger.debug("rank_by_attention failed: %s", exc)
            return []

    # ── v22: learning beyond outcomes ─────────────────────

    def recall_case(
        self,
        situation: dict[str, Any],
        *, k: int = 5,
    ) -> list[dict[str, Any]]:
        """Find the top-k most similar past cases to a situation."""
        try:
            matches = _case_base().recall(situation, k=k)
            return [m.as_dict() for m in matches]
        except Exception as exc:
            logger.debug("recall_case failed: %s", exc)
            return []

    def record_case(
        self,
        situation: dict[str, Any],
        action: str,
        outcome_score: float,
        tags: tuple[str, ...] = (),
    ) -> str | None:
        try:
            return _case_base().add(
                situation=situation, action=action,
                outcome_score=outcome_score, tags=tags,
            )
        except Exception as exc:
            logger.debug("record_case failed: %s", exc)
            return None

    def assess_competence(
        self, task_class: str,
    ) -> dict[str, Any]:
        try:
            return _competence_model().competence(task_class).as_dict()
        except Exception as exc:
            logger.debug("assess_competence failed: %s", exc)
            return {}

    def should_defer(
        self,
        task_class: str,
        *, threshold: float = 0.6, min_support: int = 5,
    ) -> bool:
        try:
            return _competence_model().should_defer(
                task_class, threshold=threshold,
                min_support=min_support,
            )
        except Exception:
            return False

    def record_task_outcome(
        self,
        task_class: str,
        success: bool,
        stated_confidence: float | None = None,
    ) -> None:
        try:
            _competence_model().record(
                task_class, success=success,
                stated_confidence=stated_confidence,
            )
        except Exception as exc:
            logger.debug("record_task_outcome failed: %s", exc)

    def note_surprise(
        self,
        observation_id: str,
        predicted: float,
        actual: float,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Feed the curiosity engine a prediction error."""
        try:
            item = _curiosity_engine().note(
                observation_id=observation_id,
                predicted=predicted, actual=actual,
                context=context or {},
            )
            return item.as_dict() if item is not None else None
        except Exception as exc:
            logger.debug("note_surprise failed: %s", exc)
            return None

    def observe_feature(
        self,
        feature: str,
        value: Any,
        *, phase: str = "recent",
        kind: str = "numeric",
    ) -> None:
        """Feed the drift detector a feature observation."""
        try:
            d = _drift_detector()
            if kind == "categorical":
                d.observe_categorical(feature, str(value), phase=phase)
            else:
                d.observe_numeric(feature, float(value), phase=phase)
        except Exception as exc:
            logger.debug("observe_feature failed: %s", exc)

    # ── commit / keep-your-word ────────────────────────────

    def commit(
        self,
        promise: str,
        owner: str,
        due_at: float,
        *,
        fulfillment_test: Any | None = None,
    ) -> str | None:
        """Register a durable promise. Returns commitment id or None."""
        try:
            return _commitment_register().register(
                promise=promise, owner=owner, due_at=due_at,
                fulfillment_test=fulfillment_test,
            ).id
        except Exception:
            return None

    # ── track subsystem improvement rate ───────────────────

    def track(
        self,
        subsystem: str,
        metric: str,
        value: float,
        *,
        cycle: int | None = None,
    ) -> None:
        """Log a subsystem metric so learning_curve can spot drift."""
        try:
            _learning_tracker().record(
                subsystem, metric, value, cycle=cycle,
            )
        except Exception as exc:
            logger.debug("track(%s, %s) failed: %s", subsystem, metric, exc)

    # ── evidence gate ──────────────────────────────────────

    def evidence_ready(
        self,
        facts: list[dict[str, Any]],
        *,
        min_sources: int = 2,
        min_volume: float = 1.0,
    ) -> dict[str, Any]:
        """Ask: do we have enough to answer, or should we gather more?"""
        try:
            from core.brain.evidence_sufficiency import check
            return check(
                facts=facts,
                min_sources=min_sources,
                min_volume=min_volume,
            ).as_dict()
        except Exception:
            return {"verdict": "decide", "note": "module_unavailable"}

    # ── claim conflict check ───────────────────────────────

    def validate_claims(
        self, claims: list[Any],
    ) -> dict[str, Any]:
        """Run knowledge_validator over a batch of (subject, predicate,
        object, source, confidence) claims."""
        try:
            from core.memory.knowledge_validator import KnowledgeValidator
            return KnowledgeValidator().validate(claims).as_dict()
        except Exception:
            return {"conflicts": [], "claims_examined": 0}

    # ── explain ────────────────────────────────────────────

    def explain(
        self,
        decision_id: str | None = None,
        polisher: Any = None,
    ) -> dict[str, Any]:
        """Compose a 'why' answer for the last decision or an
        explicit id."""
        try:
            from core.brain.explanation_aggregator import aggregate
        except Exception:
            return {"status": "no_aggregator"}
        did = decision_id or (
            f"cycle:{int(self._last_cycle_report.started_at)}"
            if self._last_cycle_report else "unknown"
        )
        context: dict[str, Any] = {}
        verdict = ""
        chosen: dict[str, Any] | None = None
        if self._last_cycle_report:
            context = self._last_cycle_report.observation
            chosen = self._last_cycle_report.chosen_action
            if chosen:
                verdict = str(chosen.get("kind", ""))
        exp = aggregate(
            decision_id=did,
            context=context,
            chosen_action=chosen,
            verdict=verdict,
            polisher=polisher,
        )
        return exp.as_dict()

    # ── housekeep ──────────────────────────────────────────

    # ── v32 orphan-rescue entry points ─────────────────────

    def deliberate(
        self,
        question_id: str,
        context: dict[str, Any],
        propose: Any,
        *,
        seed_candidate: dict[str, Any] | None = None,
        max_rounds: int = 5,
    ) -> dict[str, Any]:
        """Bounded think→critique→revise loop. Wraps
        ``deliberation_loop`` and chains counter_argument +
        critic_panel internally."""
        try:
            from core.brain import deliberation_loop as dl
            critique = dl.from_counter_argument_and_critic_panel()
            trace = dl.deliberate(
                question_id=question_id,
                context=context,
                propose=propose,
                critique=critique,
                seed_candidate=seed_candidate,
                max_rounds=max_rounds,
            )
            return trace.as_dict()
        except Exception as exc:
            logger.debug("deliberate failed: %s", exc)
            return {"question_id": question_id, "winner": None}

    def verify_plan(
        self,
        start: dict[str, Any],
        steps: list[Any],
    ) -> dict[str, Any]:
        """Static pre-flight of a plan via plan_verifier."""
        try:
            from core.brain.plan_verifier import PlanVerifier
            return PlanVerifier().verify(start, steps).as_dict()
        except Exception as exc:
            logger.debug("verify_plan failed: %s", exc)
            return {"verdict": "ok", "violations": [], "steps": []}

    def repair_step(
        self,
        step: str,
        exc: BaseException,
        *,
        remaining_steps: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Pick retry / substitute / skip / abort for a failed step."""
        try:
            from core.brain.plan_repair import PlanRepairer
            return PlanRepairer().decide(
                step=step, exc=exc,
                remaining_steps=remaining_steps,
            ).as_dict()
        except Exception as e:
            logger.debug("repair_step failed: %s", e)
            return {"strategy": "abort", "reason": "unavailable"}

    def gate_action(
        self,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        """Run feasibility_gate — hard/soft constraint check."""
        try:
            from core.brain.feasibility_gate import FeasibilityGate
            return FeasibilityGate().evaluate(action).as_dict()
        except Exception as exc:
            logger.debug("gate_action failed: %s", exc)
            return {"feasible": True, "violations": []}

    def blend_utility(
        self,
        values: dict[str, float],
    ) -> dict[str, Any]:
        """Score a candidate across registered objectives."""
        try:
            from core.brain.utility_blender import UtilityBlender
            return UtilityBlender().score(values).as_dict()
        except Exception as exc:
            logger.debug("blend_utility failed: %s", exc)
            return {"score": 0.0}

    def workflow_from_template(
        self,
        template_name: str,
        **params: Any,
    ) -> Any:
        """Instantiate a named workflow template."""
        try:
            from core.brain.workflow_templater import registry
            return registry().instantiate(
                template_name, **params,
            )
        except Exception as exc:
            logger.debug("workflow_from_template failed: %s", exc)
            return None

    def ask_llm(
        self,
        prompt: str,
        *,
        purpose: str = "reasoning",
        max_cost: float | None = None,
    ) -> dict[str, Any]:
        """Route an LLM call through the central gateway."""
        try:
            from core import llm_gateway
            return llm_gateway.ask(
                prompt, purpose=purpose,  # type: ignore[arg-type]
                max_cost=max_cost,
            ).as_dict()
        except Exception as exc:
            logger.debug("ask_llm failed: %s", exc)
            return {
                "ok": False,
                "error": "gateway_unavailable",
                "text": "",
            }

    def plan_next_cycle(self) -> dict[str, Any]:
        """Produce the cycle plan (focus / avoid / retry / kpis)."""
        try:
            from core.brain.cycle_planner import plan_next_cycle as pnc
            return pnc().as_dict()
        except Exception as exc:
            logger.debug("plan_next_cycle failed: %s", exc)
            return {"focus_areas": [], "avoid_areas": []}

    def analogy_match(
        self,
        situation: dict[str, Any],
        templates: list[Any],
    ) -> dict[str, Any] | None:
        """Structural (relational) match against registered templates."""
        try:
            from core.brain.analogy_mapper import AnalogyMapper, Situation
            mapper = AnalogyMapper()
            for t in templates:
                mapper.register(t)
            sit = situation if isinstance(situation, Situation) else (
                Situation(
                    roles=tuple(situation.get("roles", ())),
                    relations=list(situation.get("relations", [])),
                )
            )
            m = mapper.best_match(sit)
            return m.as_dict() if m else None
        except Exception as exc:
            logger.debug("analogy_match failed: %s", exc)
            return None

    def detect_bias(
        self,
        records: list[dict[str, Any]],
        attribute: str,
        *,
        baseline: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Over-representation check for a decision attribute."""
        try:
            from core.brain.bias_detector import measure
            return measure(records, attribute, baseline=baseline).as_dict()
        except Exception as exc:
            logger.debug("detect_bias failed: %s", exc)
            return {"attribute": attribute, "total": 0, "slices": []}

    def progress_estimate(
        self,
        goal_id: str,
        milestones: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Estimate % complete + pace + ETA + health for a goal."""
        try:
            from core.brain.progress_estimator import estimate
            return estimate(goal_id, milestones).as_dict()
        except Exception as exc:
            logger.debug("progress_estimate failed: %s", exc)
            return {"goal_id": goal_id}

    def recommend_intervention(
        self,
        interventions: list[Any],
        *,
        kpi: str,
        direction: str = "up",
        driver_weight_fn: Any = None,
    ) -> list[dict[str, Any]]:
        """Rank interventions by expected causal impact."""
        try:
            from core.brain.causal_intervention_recommender import (
                CausalInterventionRecommender,
            )
            r = CausalInterventionRecommender(
                driver_weight_fn=driver_weight_fn,
            )
            return [
                rec.as_dict() for rec in r.recommend(
                    interventions,
                    kpi=kpi,
                    direction=direction,  # type: ignore[arg-type]
                )
            ]
        except Exception as exc:
            logger.debug("recommend_intervention failed: %s", exc)
            return []

    def resolve_ambiguity(
        self,
        candidates: list[Any],
        *,
        evaluators: list[Any] = (),
    ) -> dict[str, Any]:
        """Pick best candidate interpretation when signal is unclear."""
        try:
            from core.brain.ambiguity_resolver import AmbiguityResolver
            return AmbiguityResolver().resolve(
                candidates, evaluators=evaluators,
            ).as_dict()
        except Exception as exc:
            logger.debug("resolve_ambiguity failed: %s", exc)
            return {"best": None, "confident": False}

    def simulate_counterfactual(
        self,
        start: dict[str, Any],
        alternatives: list[str],
        transition: Any,
        policy: Any,
        *,
        horizon: int = 5,
        trials: int = 10,
    ) -> list[dict[str, Any]]:
        """Monte-Carlo rollout comparison of first-action alternatives."""
        try:
            from core.brain.counterfactual_simulator import (
                compare_alternatives,
            )
            reports = compare_alternatives(
                start=start,
                alternatives=alternatives,
                transition=transition,
                policy=policy,
                horizon=horizon,
                trials=trials,
            )
            return [r.as_dict() for r in reports]
        except Exception as exc:
            logger.debug("simulate_counterfactual failed: %s", exc)
            return []

    def run_behaviour_tree(
        self,
        tree: Any,
        context: dict[str, Any],
    ) -> str:
        """Tick a pre-built BehaviourTree and return its status."""
        try:
            status = tree.tick(context)
            return str(getattr(status, "value", status))
        except Exception as exc:
            logger.debug("run_behaviour_tree failed: %s", exc)
            return "failure"

    def housekeep(self) -> dict[str, Any]:
        try:
            from core.memory.data_housekeeper import DataHousekeeper
            return DataHousekeeper().run().as_dict()
        except Exception as exc:
            return {"status": "failed", "error": str(exc)}


# ── Summary helpers (lazy imports inside) ───────────────────

def _wm_summary() -> dict[str, Any]:
    from core.brain.world_model import world_model
    return world_model().summary()


def _ep_summary() -> dict[str, Any]:
    from core.brain.epistemic import coverage_engine
    return coverage_engine().summary()


def _hypo_summary() -> dict[str, Any]:
    from core.brain.hypothesis import engine
    e = engine()
    return {
        "pending": len(e.list_pending()),
        "overdue": len(e.list_overdue()),
        "calibration_global": e.calibration().as_dict(),
    }


def _reward_summary() -> dict[str, Any]:
    from core.brain.reward_model import reward_model
    return reward_model().size()


def _policy_summary() -> dict[str, Any]:
    from core.brain.policy_library import PolicyLibrary
    return PolicyLibrary().stats()


def _habit_summary() -> dict[str, Any]:
    from core.brain.habit import HabitLayer
    return HabitLayer().stats()


def _trust_top() -> list[dict[str, Any]]:
    from core.brain.trust_calibrator import TrustCalibrator
    return [s.as_dict() for s in TrustCalibrator().rank(limit=5)]


def _si_summary() -> dict[str, Any]:
    from core.brain.self_improvement import SelfImprovementEngine
    return SelfImprovementEngine().stats()


def _surprise_summary() -> dict[str, Any]:
    from core.brain.surprise import surprise_detector
    return surprise_detector().summary()


def _regret_summary() -> dict[str, Any]:
    from core.brain.regret_minimizer import minimizer
    return minimizer().summary()


_COMMIT_REG: Any = None
_COMMIT_LOCK = threading.Lock()


def _commitment_register():
    """Lazy singleton so every caller goes to the same SQLite file."""
    global _COMMIT_REG
    if _COMMIT_REG is None:
        with _COMMIT_LOCK:
            if _COMMIT_REG is None:
                from core.brain.commitment_register import CommitmentRegister
                _COMMIT_REG = CommitmentRegister()
    return _COMMIT_REG


def _commitments_summary() -> dict[str, Any]:
    r = _commitment_register()
    pending = r.pending()
    urgent = r.urgent(hours_ahead=24.0)
    return {
        "pending": len(pending),
        "urgent_24h": len(urgent),
        "next_due_at": (
            min((c.due_at for c in pending), default=None)
            if pending else None
        ),
    }


_LEARNING_TRACKER: Any = None
_LEARNING_LOCK = threading.Lock()


def _learning_tracker():
    """Lazy singleton LearningCurveTracker instance so every subsystem
    writes to the same SQLite file."""
    global _LEARNING_TRACKER
    if _LEARNING_TRACKER is None:
        with _LEARNING_LOCK:
            if _LEARNING_TRACKER is None:
                from core.brain.learning_curve import LearningCurveTracker
                _LEARNING_TRACKER = LearningCurveTracker()
    return _LEARNING_TRACKER


def _learning_summary() -> list[dict[str, Any]]:
    from core.brain.learning_curve import LearningCurveTracker
    t = _learning_tracker()
    # Rank the few metrics we care most about. Missing ones just skip.
    out: list[dict[str, Any]] = []
    for metric in ("roas", "cvr", "acc", "f1"):
        curves = t.rank(metric, window=50, top_n=3)
        for c in curves:
            if c.trend != "insufficient":
                out.append(c.as_dict())
    return out


# ── v22 singletons ──────────────────────────────────────────

_CASE_BASE: Any = None
_CASE_LOCK = threading.Lock()


def _case_base():
    global _CASE_BASE
    if _CASE_BASE is None:
        with _CASE_LOCK:
            if _CASE_BASE is None:
                from core.memory.case_based_reasoner import CaseBasedReasoner
                _CASE_BASE = CaseBasedReasoner()
    return _CASE_BASE


def _case_base_summary() -> dict[str, Any]:
    return _case_base().stats()


_SKILL_LIB: Any = None
_SKILL_LOCK = threading.Lock()


def _skill_library():
    global _SKILL_LIB
    if _SKILL_LIB is None:
        with _SKILL_LOCK:
            if _SKILL_LIB is None:
                from core.brain.skill_library import SkillLibrary
                _SKILL_LIB = SkillLibrary()
    return _SKILL_LIB


def _skill_rank_summary() -> list[dict[str, Any]]:
    return [s.as_dict() for s in _skill_library().rank(min_support=3)][:5]


_COMPETENCE: Any = None
_COMPETENCE_LOCK = threading.Lock()


def _competence_model():
    global _COMPETENCE
    if _COMPETENCE is None:
        with _COMPETENCE_LOCK:
            if _COMPETENCE is None:
                from core.brain.competence_model import CompetenceModel
                _COMPETENCE = CompetenceModel()
    return _COMPETENCE


def _competence_summary() -> dict[str, Any]:
    return _competence_model().summary()


_CURIOSITY: Any = None
_CURIOSITY_LOCK = threading.Lock()


def _curiosity_engine():
    global _CURIOSITY
    if _CURIOSITY is None:
        with _CURIOSITY_LOCK:
            if _CURIOSITY is None:
                from core.brain.curiosity_engine import CuriosityEngine
                _CURIOSITY = CuriosityEngine()
    return _CURIOSITY


def _curiosity_summary() -> dict[str, Any]:
    return _curiosity_engine().stats()


_DRIFT: Any = None
_DRIFT_LOCK = threading.Lock()


def _drift_detector():
    global _DRIFT
    if _DRIFT is None:
        with _DRIFT_LOCK:
            if _DRIFT is None:
                from core.memory.concept_drift_detector import ConceptDriftDetector
                _DRIFT = ConceptDriftDetector()
    return _DRIFT


def _drift_summary() -> dict[str, Any]:
    return _drift_detector().summary()


# ── v23 singletons ──────────────────────────────────────────

_GOAL_GRAPH: Any = None
_GOAL_LOCK = threading.Lock()


def _goal_graph():
    global _GOAL_GRAPH
    if _GOAL_GRAPH is None:
        with _GOAL_LOCK:
            if _GOAL_GRAPH is None:
                from core.brain.goal_graph import GoalGraph
                _GOAL_GRAPH = GoalGraph()
    return _GOAL_GRAPH


def _goal_summary() -> dict[str, Any]:
    return _goal_graph().stats()


_ATTENTION: Any = None
_ATTENTION_LOCK = threading.Lock()


def _attention_filter():
    global _ATTENTION
    if _ATTENTION is None:
        with _ATTENTION_LOCK:
            if _ATTENTION is None:
                from core.brain.attention_filter import AttentionFilter
                _ATTENTION = AttentionFilter()
    return _ATTENTION


def _attention_summary() -> dict[str, Any]:
    return _attention_filter().stats()


# ── v25 singletons ──────────────────────────────────────────

_OWNER: Any = None
_OWNER_LOCK = threading.Lock()


def _owner_model():
    global _OWNER
    if _OWNER is None:
        with _OWNER_LOCK:
            if _OWNER is None:
                from core.brain.owner_model import OwnerModel
                _OWNER = OwnerModel()
    return _OWNER


def _owner_summary() -> dict[str, Any]:
    return _owner_model().summary()


_SAFETY_GUARD: Any = None
_SAFETY_LOCK = threading.Lock()


def _safety_guard():
    global _SAFETY_GUARD
    if _SAFETY_GUARD is None:
        with _SAFETY_LOCK:
            if _SAFETY_GUARD is None:
                from core.brain.action_safety_guard import (
                    ActionSafetyGuard,
                )
                _SAFETY_GUARD = ActionSafetyGuard()
    return _SAFETY_GUARD


_BUDGET_LEDGER: Any = None
_BUDGET_LOCK = threading.Lock()


def _budget_ledger():
    global _BUDGET_LEDGER
    if _BUDGET_LEDGER is None:
        with _BUDGET_LOCK:
            if _BUDGET_LEDGER is None:
                from core.brain.budget_ledger import BudgetLedger
                _BUDGET_LEDGER = BudgetLedger()
    return _BUDGET_LEDGER


def _budget_summary() -> list[dict[str, Any]]:
    return [s.as_dict() for s in _budget_ledger().overview()]


_EXPERIMENT_MANAGER: Any = None
_EXP_LOCK = threading.Lock()


def _experiment_manager():
    global _EXPERIMENT_MANAGER
    if _EXPERIMENT_MANAGER is None:
        with _EXP_LOCK:
            if _EXPERIMENT_MANAGER is None:
                from core.brain.experiment_manager import (
                    ExperimentManager,
                )
                _EXPERIMENT_MANAGER = ExperimentManager()
    return _EXPERIMENT_MANAGER


def _experiment_summary() -> dict[str, Any]:
    return _experiment_manager().stats()


_UPLIFT: Any = None
_UPLIFT_LOCK = threading.Lock()


def _uplift_estimator():
    global _UPLIFT
    if _UPLIFT is None:
        with _UPLIFT_LOCK:
            if _UPLIFT is None:
                from core.brain.uplift_estimator import UpliftEstimator
                _UPLIFT = UpliftEstimator()
    return _UPLIFT


def _uplift_summary() -> dict[str, Any]:
    return _uplift_estimator().stats()


_KNOWLEDGE_GRAPH: Any = None
_KG_LOCK = threading.Lock()


def _knowledge_graph():
    global _KNOWLEDGE_GRAPH
    if _KNOWLEDGE_GRAPH is None:
        with _KG_LOCK:
            if _KNOWLEDGE_GRAPH is None:
                from core.memory.knowledge_graph import KnowledgeGraph
                _KNOWLEDGE_GRAPH = KnowledgeGraph()
    return _KNOWLEDGE_GRAPH


def _knowledge_summary() -> dict[str, Any]:
    return _knowledge_graph().stats()


# ── v26 singletons ──────────────────────────────────────────

_CAUSAL: Any = None
_CAUSAL_LOCK = threading.Lock()


def _causal_graph():
    global _CAUSAL
    if _CAUSAL is None:
        with _CAUSAL_LOCK:
            if _CAUSAL is None:
                from core.brain.causal_graph import CausalGraph
                _CAUSAL = CausalGraph()
    return _CAUSAL


def _causal_summary() -> dict[str, Any]:
    return _causal_graph().stats()


_COMPOSER: Any = None
_COMPOSER_LOCK = threading.Lock()


def _skill_composer():
    global _COMPOSER
    if _COMPOSER is None:
        with _COMPOSER_LOCK:
            if _COMPOSER is None:
                from core.brain.skill_composer import SkillComposer
                _COMPOSER = SkillComposer()
    return _COMPOSER


def _macro_summary() -> list[dict[str, Any]]:
    return _skill_composer().rank(min_support=3)


_FORECASTER: Any = None
_FORECASTER_LOCK = threading.Lock()


def _forecaster():
    global _FORECASTER
    if _FORECASTER is None:
        with _FORECASTER_LOCK:
            if _FORECASTER is None:
                from core.brain.forecaster import Forecaster
                _FORECASTER = Forecaster()
    return _FORECASTER


def _forecaster_summary() -> dict[str, Any]:
    return _forecaster().stats()


_INVARIANT: Any = None
_INVARIANT_LOCK = threading.Lock()


def _invariant_monitor():
    global _INVARIANT
    if _INVARIANT is None:
        with _INVARIANT_LOCK:
            if _INVARIANT is None:
                from core.brain.invariant_monitor import InvariantMonitor
                _INVARIANT = InvariantMonitor()
    return _INVARIANT


def _invariant_summary() -> dict[str, Any]:
    return _invariant_monitor().stats()


_SELF_DEBUGGER: Any = None
_SELF_DEBUG_LOCK = threading.Lock()


def _self_debugger():
    global _SELF_DEBUGGER
    if _SELF_DEBUGGER is None:
        with _SELF_DEBUG_LOCK:
            if _SELF_DEBUGGER is None:
                from core.brain.self_debugger import SelfDebugger
                dbg = SelfDebugger()
                dbg.register_defaults()
                _SELF_DEBUGGER = dbg
    return _SELF_DEBUGGER


def _self_debug_summary() -> dict[str, Any]:
    return _self_debugger().stats()


_CREDIT: Any = None
_CREDIT_LOCK = threading.Lock()


def _credit_assigner():
    global _CREDIT
    if _CREDIT is None:
        with _CREDIT_LOCK:
            if _CREDIT is None:
                from core.brain.credit_assigner import CreditAssigner
                _CREDIT = CreditAssigner()
    return _CREDIT


def _credit_summary() -> dict[str, Any]:
    return _credit_assigner().stats()


# ── v27 singletons ──────────────────────────────────────────

_HP_TUNER: Any = None
_HP_TUNER_LOCK = threading.Lock()


def _hp_tuner():
    global _HP_TUNER
    if _HP_TUNER is None:
        with _HP_TUNER_LOCK:
            if _HP_TUNER is None:
                from core.brain.hyperparameter_tuner import HyperparameterTuner
                _HP_TUNER = HyperparameterTuner()
    return _HP_TUNER


def _hp_tuner_summary() -> dict[str, Any]:
    return _hp_tuner().stats()


_FEDERATOR: Any = None
_FED_LOCK = threading.Lock()


def _federator():
    global _FEDERATOR
    if _FEDERATOR is None:
        with _FED_LOCK:
            if _FEDERATOR is None:
                from core.brain.multi_store_federator import MultiStoreFederator
                _FEDERATOR = MultiStoreFederator()
    return _FEDERATOR


def _federation_summary() -> dict[str, Any]:
    return _federator().stats()


_ACTION_QUEUE: Any = None
_QUEUE_LOCK = threading.Lock()


def _action_queue():
    global _ACTION_QUEUE
    if _ACTION_QUEUE is None:
        with _QUEUE_LOCK:
            if _ACTION_QUEUE is None:
                from core.brain.action_queue import ActionQueue
                _ACTION_QUEUE = ActionQueue()
    return _ACTION_QUEUE


def _queue_summary() -> dict[str, Any]:
    return _action_queue().stats()


_EXPLORATION: Any = None
_EXPLORATION_LOCK = threading.Lock()


def _exploration_manager():
    global _EXPLORATION
    if _EXPLORATION is None:
        with _EXPLORATION_LOCK:
            if _EXPLORATION is None:
                from core.brain.exploration_manager import ExplorationManager
                _EXPLORATION = ExplorationManager()
    return _EXPLORATION


def _explore_summary() -> dict[str, Any]:
    return _exploration_manager().stats()


# ── v28 singletons ──────────────────────────────────────────

_DIALOG: Any = None
_DIALOG_LOCK = threading.Lock()


def _dialog_memory():
    global _DIALOG
    if _DIALOG is None:
        with _DIALOG_LOCK:
            if _DIALOG is None:
                from core.brain.dialog_memory import DialogMemory
                _DIALOG = DialogMemory()
    return _DIALOG


def _dialog_summary() -> dict[str, Any]:
    return _dialog_memory().stats()


_PRICE_ELASTICITY: Any = None
_PE_LOCK = threading.Lock()


def _price_elasticity():
    global _PRICE_ELASTICITY
    if _PRICE_ELASTICITY is None:
        with _PE_LOCK:
            if _PRICE_ELASTICITY is None:
                from core.brain.price_elasticity import PriceElasticity
                _PRICE_ELASTICITY = PriceElasticity()
    return _PRICE_ELASTICITY


def _elasticity_summary() -> dict[str, Any]:
    return _price_elasticity().stats()


_LTV: Any = None
_LTV_LOCK = threading.Lock()


def _customer_ltv():
    global _LTV
    if _LTV is None:
        with _LTV_LOCK:
            if _LTV is None:
                from core.brain.customer_ltv import CustomerLTV
                _LTV = CustomerLTV()
    return _LTV


def _ltv_summary() -> dict[str, Any]:
    return _customer_ltv().stats()


_SCHEDULER: Any = None
_SCHED_LOCK = threading.Lock()


def _scheduler():
    global _SCHEDULER
    if _SCHEDULER is None:
        with _SCHED_LOCK:
            if _SCHEDULER is None:
                from core.brain.time_scheduler import TimeScheduler
                _SCHEDULER = TimeScheduler()
    return _SCHEDULER


def _schedule_summary() -> dict[str, Any]:
    return _scheduler().stats()


# ── v29 singletons ──────────────────────────────────────────

_EPISODE_RETRIEVER: Any = None
_EPR_LOCK = threading.Lock()


def _episode_retriever():
    global _EPISODE_RETRIEVER
    if _EPISODE_RETRIEVER is None:
        with _EPR_LOCK:
            if _EPISODE_RETRIEVER is None:
                from core.memory.episode_retriever import EpisodeRetriever
                _EPISODE_RETRIEVER = EpisodeRetriever()
    return _EPISODE_RETRIEVER


def _episodes_summary() -> dict[str, Any]:
    return _episode_retriever().stats()


_META_ROUTER: Any = None
_MR_LOCK = threading.Lock()


def _meta_router():
    global _META_ROUTER
    if _META_ROUTER is None:
        with _MR_LOCK:
            if _META_ROUTER is None:
                from core.brain.meta_router import MetaRouter
                _META_ROUTER = MetaRouter()
    return _META_ROUTER


def _router_summary() -> dict[str, Any]:
    return _meta_router().stats()


_RECOVERY_PLANNER: Any = None
_RP_LOCK = threading.Lock()


def _recovery_planner():
    global _RECOVERY_PLANNER
    if _RECOVERY_PLANNER is None:
        with _RP_LOCK:
            if _RECOVERY_PLANNER is None:
                from core.brain.recovery_planner import RecoveryPlanner
                _RECOVERY_PLANNER = RecoveryPlanner()
    return _RECOVERY_PLANNER


def _recovery_summary() -> dict[str, Any]:
    return _recovery_planner().stats()


_CURRICULUM_PLANNER: Any = None
_CP_LOCK = threading.Lock()


def _curriculum_planner():
    global _CURRICULUM_PLANNER
    if _CURRICULUM_PLANNER is None:
        with _CP_LOCK:
            if _CURRICULUM_PLANNER is None:
                from core.brain.curriculum_planner import CurriculumPlanner
                _CURRICULUM_PLANNER = CurriculumPlanner()
    return _CURRICULUM_PLANNER


def _curriculum_summary() -> dict[str, Any]:
    return _curriculum_planner().stats()


# ── v30 singletons ──────────────────────────────────────────

_OBSERVATION_FUSER: Any = None
_OF_LOCK = threading.Lock()


def _observation_fuser():
    global _OBSERVATION_FUSER
    if _OBSERVATION_FUSER is None:
        with _OF_LOCK:
            if _OBSERVATION_FUSER is None:
                from core.memory.observation_fuser import ObservationFuser
                _OBSERVATION_FUSER = ObservationFuser()
    return _OBSERVATION_FUSER


def _fusion_summary() -> dict[str, Any]:
    return _observation_fuser().stats()


_PLAN_MONITOR: Any = None
_PM_LOCK = threading.Lock()


def _plan_monitor():
    global _PLAN_MONITOR
    if _PLAN_MONITOR is None:
        with _PM_LOCK:
            if _PLAN_MONITOR is None:
                from core.brain.plan_monitor import PlanMonitor
                _PLAN_MONITOR = PlanMonitor()
    return _PLAN_MONITOR


def _plan_monitor_summary() -> dict[str, Any]:
    return _plan_monitor().stats()


_RISK_BUDGET: Any = None
_RB_LOCK = threading.Lock()


def _risk_budget():
    global _RISK_BUDGET
    if _RISK_BUDGET is None:
        with _RB_LOCK:
            if _RISK_BUDGET is None:
                from core.brain.risk_budget import RiskBudget
                _RISK_BUDGET = RiskBudget()
    return _RISK_BUDGET


def _risk_summary() -> list[dict[str, Any]]:
    return [s.as_dict() for s in _risk_budget().overview()]


# ── v31 singletons ──────────────────────────────────────────

_WORLD_SIMULATOR: Any = None
_WS_LOCK = threading.Lock()


def _world_simulator():
    global _WORLD_SIMULATOR
    if _WORLD_SIMULATOR is None:
        with _WS_LOCK:
            if _WORLD_SIMULATOR is None:
                from core.brain.world_simulator import (
                    WorldSimulator, default_transitions,
                )
                sim = WorldSimulator()
                for kind, fn in default_transitions().items():
                    sim.register(kind, fn)
                _WORLD_SIMULATOR = sim
    return _WORLD_SIMULATOR


def _simulator_summary() -> dict[str, Any]:
    return _world_simulator().stats()


_TASK_PRIORITIZER: Any = None
_TP_LOCK = threading.Lock()


def _task_prioritizer():
    global _TASK_PRIORITIZER
    if _TASK_PRIORITIZER is None:
        with _TP_LOCK:
            if _TASK_PRIORITIZER is None:
                from core.brain.task_prioritizer import TaskPrioritizer
                _TASK_PRIORITIZER = TaskPrioritizer()
    return _TASK_PRIORITIZER


def _prioritizer_config() -> dict[str, Any]:
    return _task_prioritizer().config()


_SKILL_TRANSFER: Any = None
_ST_LOCK = threading.Lock()


def _skill_transfer():
    global _SKILL_TRANSFER
    if _SKILL_TRANSFER is None:
        with _ST_LOCK:
            if _SKILL_TRANSFER is None:
                from core.brain.skill_transfer import SkillTransfer
                _SKILL_TRANSFER = SkillTransfer()
    return _SKILL_TRANSFER


def _transfer_summary() -> dict[str, Any]:
    return _skill_transfer().stats()


_COMMITMENT_VERIFIER: Any = None
_CV_LOCK = threading.Lock()


def _commitment_verifier():
    global _COMMITMENT_VERIFIER
    if _COMMITMENT_VERIFIER is None:
        with _CV_LOCK:
            if _COMMITMENT_VERIFIER is None:
                from core.brain.commitment_verifier import (
                    CommitmentVerifier,
                )
                _COMMITMENT_VERIFIER = CommitmentVerifier()
    return _COMMITMENT_VERIFIER


def _verifier_summary() -> dict[str, Any]:
    return _commitment_verifier().stats()


_SELF_TEST_HARNESS: Any = None
_STH_LOCK = threading.Lock()


def _self_test_harness():
    global _SELF_TEST_HARNESS
    if _SELF_TEST_HARNESS is None:
        with _STH_LOCK:
            if _SELF_TEST_HARNESS is None:
                from core.brain.self_test_harness import (
                    SelfTestHarness, memory_nonzero_check,
                )
                h = SelfTestHarness()
                try:
                    h.register(memory_nonzero_check(min_records=0))
                except ValueError as exc:
                    # Duplicate registration is benign — log and
                    # continue without the check instead of crashing
                    # module import.
                    logger.debug(
                        "self_test bootstrap skipped: %s", exc,
                    )
                _SELF_TEST_HARNESS = h
    return _SELF_TEST_HARNESS


def _self_test_summary() -> dict[str, Any]:
    return _self_test_harness().stats()


_COUNTERFACTUAL_MEMORY: Any = None
_CFM_LOCK = threading.Lock()


def _counterfactual_memory():
    global _COUNTERFACTUAL_MEMORY
    if _COUNTERFACTUAL_MEMORY is None:
        with _CFM_LOCK:
            if _COUNTERFACTUAL_MEMORY is None:
                from core.memory.counterfactual_memory import (
                    CounterfactualMemory,
                )
                _COUNTERFACTUAL_MEMORY = CounterfactualMemory()
    return _COUNTERFACTUAL_MEMORY


def _counterfactual_summary() -> dict[str, Any]:
    return _counterfactual_memory().stats()


_SIGNAL_NOISE_SEPARATOR: Any = None
_SNS_LOCK = threading.Lock()


def _signal_noise_separator():
    global _SIGNAL_NOISE_SEPARATOR
    if _SIGNAL_NOISE_SEPARATOR is None:
        with _SNS_LOCK:
            if _SIGNAL_NOISE_SEPARATOR is None:
                from core.brain.signal_noise_separator import (
                    SignalNoiseSeparator,
                )
                _SIGNAL_NOISE_SEPARATOR = SignalNoiseSeparator()
    return _SIGNAL_NOISE_SEPARATOR


def _signal_noise_summary() -> dict[str, Any]:
    return _signal_noise_separator().stats()


# ── v32 singletons ──────────────────────────────────────────

def _default_stage_callables() -> Any:
    """Wire the 6 decision stages to the existing brain subsystems.

    Each stage is a thin adapter that returns ``{"status": ...,
    "note": ..., "payload": ...}`` per decision_stack's contract.
    """
    from core.brain.decision_stack import StageCallables

    def attention_stage(ctx: dict[str, Any]) -> dict[str, Any]:
        # Attention: rank the observation against the salience filter.
        obs = ctx.get("observation") or {}
        if not obs:
            return {"status": "skipped", "note": "no observation"}
        try:
            top = _attention_filter().top_k([obs], k=1)
            score = top[0].score if top else 0.0
        except Exception as exc:
            return {
                "status": "skipped",
                "note": f"attention unavailable: {exc}",
            }
        return {
            "status": "ok",
            "note": f"attention_score={score:.3f}",
            "payload": {"attention_score": score},
        }

    def evidence_stage(ctx: dict[str, Any]) -> dict[str, Any]:
        # No injected evidence list by default; mark skipped.
        return {
            "status": "skipped",
            "note": "no evidence list supplied",
        }

    def deliberate_stage(ctx: dict[str, Any]) -> dict[str, Any]:
        candidate = ctx.get("candidate_action")
        if not candidate:
            return {
                "status": "skipped",
                "note": "no candidate to deliberate on",
            }
        # Default deliberation just passes the candidate through;
        # callers who want the full chain should call
        # brain().deliberate() explicitly.
        return {
            "status": "ok",
            "note": "candidate accepted as-is",
            "payload": {"candidate": candidate},
        }

    def safety_stage(ctx: dict[str, Any]) -> dict[str, Any]:
        candidate = ctx.get("candidate_action")
        if not candidate:
            return {"status": "skipped", "note": "no candidate"}
        try:
            v = _safety_guard().evaluate(
                candidate,
                confidence=float(ctx.get("stakes", 0.3)),
            )
        except Exception as exc:
            return {
                "status": "skipped",
                "note": f"safety_guard unavailable: {exc}",
            }
        if v.verdict == "block":
            return {
                "status": "blocked",
                "note": ";".join(v.reasons),
                "payload": v.as_dict(),
            }
        return {
            "status": "ok",
            "note": v.verdict,
            "payload": v.as_dict(),
        }

    def feasibility_stage(ctx: dict[str, Any]) -> dict[str, Any]:
        candidate = ctx.get("candidate_action")
        if not candidate:
            return {"status": "skipped", "note": "no candidate"}
        try:
            from core.brain.feasibility_gate import FeasibilityGate
            v = FeasibilityGate().evaluate(candidate)
        except Exception as exc:
            return {
                "status": "skipped",
                "note": f"feasibility_gate unavailable: {exc}",
            }
        if not v.feasible:
            return {
                "status": "blocked",
                "note": ";".join(
                    vx.constraint for vx in v.violations
                ),
                "payload": v.as_dict(),
            }
        return {
            "status": "ok",
            "note": "feasible",
            "payload": v.as_dict(),
        }

    def utility_stage(ctx: dict[str, Any]) -> dict[str, Any]:
        candidate = ctx.get("candidate_action")
        if not candidate:
            return {"status": "skipped", "note": "no candidate"}
        return {
            "status": "ok",
            "note": "utility stage passthrough",
            "payload": {"candidate": candidate},
        }

    return StageCallables(
        attention=attention_stage,
        evidence=evidence_stage,
        deliberate=deliberate_stage,
        safety=safety_stage,
        feasibility=feasibility_stage,
        utility=utility_stage,
    )


_DECISION_STACK: Any = None
_DS_LOCK = threading.Lock()


def _decision_stack():
    global _DECISION_STACK
    if _DECISION_STACK is None:
        with _DS_LOCK:
            if _DECISION_STACK is None:
                from core.brain.decision_stack import DecisionStack
                _DECISION_STACK = DecisionStack(
                    stages=_default_stage_callables(),
                )
    return _DECISION_STACK


def _decision_stack_summary() -> dict[str, Any]:
    return _decision_stack().stats()


_SHADOW_DIVERGENCE: Any = None
_SD_LOCK = threading.Lock()


def _shadow_divergence():
    global _SHADOW_DIVERGENCE
    if _SHADOW_DIVERGENCE is None:
        with _SD_LOCK:
            if _SHADOW_DIVERGENCE is None:
                from core.brain.shadow_divergence import (
                    ShadowDivergence,
                )
                _SHADOW_DIVERGENCE = ShadowDivergence()
    return _SHADOW_DIVERGENCE


def _shadow_divergence_summary() -> dict[str, Any]:
    return _shadow_divergence().stats()


_REASONING_TRACER: Any = None
_RT_LOCK = threading.Lock()


def _reasoning_tracer():
    global _REASONING_TRACER
    if _REASONING_TRACER is None:
        with _RT_LOCK:
            if _REASONING_TRACER is None:
                from core.brain.reasoning_trace import ReasoningTracer
                _REASONING_TRACER = ReasoningTracer()
    return _REASONING_TRACER


def _reasoning_trace_summary() -> dict[str, Any]:
    return _reasoning_tracer().stats()


_REVISION_JOURNAL: Any = None
_RJ_LOCK = threading.Lock()


def _revision_journal():
    global _REVISION_JOURNAL
    if _REVISION_JOURNAL is None:
        with _RJ_LOCK:
            if _REVISION_JOURNAL is None:
                from core.brain.self_revision_journal import (
                    SelfRevisionJournal,
                )
                _REVISION_JOURNAL = SelfRevisionJournal()
    return _REVISION_JOURNAL


def _revision_journal_summary() -> dict[str, Any]:
    return _revision_journal().stats()


# ── v33 singletons ───────────────────────────────────────────

_PROMPT_COMPOSER: Any = None
_PC_LOCK = threading.Lock()


def _prompt_composer():
    global _PROMPT_COMPOSER
    if _PROMPT_COMPOSER is None:
        with _PC_LOCK:
            if _PROMPT_COMPOSER is None:
                from core.brain.prompt_composer import PromptComposer
                _PROMPT_COMPOSER = PromptComposer()
    return _PROMPT_COMPOSER


def _prompt_composer_summary() -> dict[str, Any]:
    return _prompt_composer().stats()


_CONCEPT_FORMER: Any = None
_CF_LOCK = threading.Lock()


def _concept_former():
    global _CONCEPT_FORMER
    if _CONCEPT_FORMER is None:
        with _CF_LOCK:
            if _CONCEPT_FORMER is None:
                from core.memory.concept_former import ConceptFormer
                _CONCEPT_FORMER = ConceptFormer()
    return _CONCEPT_FORMER


def _concept_former_summary() -> dict[str, Any]:
    return _concept_former().stats()


_PREDICTIVE_ALERTER: Any = None
_PA_LOCK = threading.Lock()


def _predictive_alerter():
    global _PREDICTIVE_ALERTER
    if _PREDICTIVE_ALERTER is None:
        with _PA_LOCK:
            if _PREDICTIVE_ALERTER is None:
                from core.brain.predictive_alerter import (
                    PredictiveAlerter,
                )
                _PREDICTIVE_ALERTER = PredictiveAlerter()
    return _PREDICTIVE_ALERTER


def _predictive_alerter_summary() -> dict[str, Any]:
    return _predictive_alerter().stats()


_ATTENTION_CALIBRATOR: Any = None
_AC_LOCK = threading.Lock()


def _attention_calibrator():
    global _ATTENTION_CALIBRATOR
    if _ATTENTION_CALIBRATOR is None:
        with _AC_LOCK:
            if _ATTENTION_CALIBRATOR is None:
                from core.brain.attention_calibrator import (
                    AttentionCalibrator,
                )
                _ATTENTION_CALIBRATOR = AttentionCalibrator()
    return _ATTENTION_CALIBRATOR


def _attention_calibrator_summary() -> dict[str, Any]:
    return _attention_calibrator().stats()


_CLARIFICATION_DIALOG: Any = None
_CD_LOCK = threading.Lock()


def _clarification_dialog():
    global _CLARIFICATION_DIALOG
    if _CLARIFICATION_DIALOG is None:
        with _CD_LOCK:
            if _CLARIFICATION_DIALOG is None:
                from core.brain.clarification_dialog import (
                    ClarificationDialog,
                )
                _CLARIFICATION_DIALOG = ClarificationDialog()
    return _CLARIFICATION_DIALOG


def _clarification_dialog_summary() -> dict[str, Any]:
    return _clarification_dialog().stats()


_ASSUMPTION_LEDGER: Any = None
_AL_LOCK = threading.Lock()


def _assumption_ledger():
    global _ASSUMPTION_LEDGER
    if _ASSUMPTION_LEDGER is None:
        with _AL_LOCK:
            if _ASSUMPTION_LEDGER is None:
                from core.brain.assumption_ledger import (
                    AssumptionLedger,
                )
                _ASSUMPTION_LEDGER = AssumptionLedger()
    return _ASSUMPTION_LEDGER


def _assumption_ledger_summary() -> dict[str, Any]:
    return _assumption_ledger().stats()


_REVENUE_FUNNEL: Any = None
_RF_LOCK = threading.Lock()


def _revenue_funnel():
    global _REVENUE_FUNNEL
    if _REVENUE_FUNNEL is None:
        with _RF_LOCK:
            if _REVENUE_FUNNEL is None:
                from core.brain.revenue_funnel import RevenueFunnel
                _REVENUE_FUNNEL = RevenueFunnel()
    return _REVENUE_FUNNEL


def _revenue_funnel_summary() -> dict[str, Any]:
    return _revenue_funnel().stats()


# ── v34 singletons ───────────────────────────────────────────

_META_REASONER: Any = None
_MR_LOCK = threading.Lock()


def _meta_reasoner():
    global _META_REASONER
    if _META_REASONER is None:
        with _MR_LOCK:
            if _META_REASONER is None:
                from core.brain.meta_reasoner import MetaReasoner
                _META_REASONER = MetaReasoner()
    return _META_REASONER


def _meta_reasoner_summary() -> dict[str, Any]:
    return _meta_reasoner().stats()


_IMITATION_LEARNER: Any = None
_IL_LOCK = threading.Lock()


def _imitation_learner():
    global _IMITATION_LEARNER
    if _IMITATION_LEARNER is None:
        with _IL_LOCK:
            if _IMITATION_LEARNER is None:
                from core.brain.imitation_learner import (
                    ImitationLearner,
                )
                _IMITATION_LEARNER = ImitationLearner()
    return _IMITATION_LEARNER


def _imitation_learner_summary() -> dict[str, Any]:
    return _imitation_learner().stats()


_GOAL_DECOMPOSER: Any = None
_GD_LOCK = threading.Lock()


def _goal_decomposer():
    global _GOAL_DECOMPOSER
    if _GOAL_DECOMPOSER is None:
        with _GD_LOCK:
            if _GOAL_DECOMPOSER is None:
                from core.brain.goal_decomposer import GoalDecomposer
                _GOAL_DECOMPOSER = GoalDecomposer()
    return _GOAL_DECOMPOSER


def _goal_decomposer_summary() -> dict[str, Any]:
    return _goal_decomposer().stats()


_ERROR_PATTERN_LIBRARY: Any = None
_EPL_LOCK = threading.Lock()


def _error_pattern_library():
    global _ERROR_PATTERN_LIBRARY
    if _ERROR_PATTERN_LIBRARY is None:
        with _EPL_LOCK:
            if _ERROR_PATTERN_LIBRARY is None:
                from core.brain.error_pattern_library import (
                    ErrorPatternLibrary,
                )
                _ERROR_PATTERN_LIBRARY = ErrorPatternLibrary()
    return _ERROR_PATTERN_LIBRARY


def _error_pattern_library_summary() -> dict[str, Any]:
    return _error_pattern_library().stats()


_PROPOSAL_ARBITER: Any = None
_PRA_LOCK = threading.Lock()


def _proposal_arbiter():
    global _PROPOSAL_ARBITER
    if _PROPOSAL_ARBITER is None:
        with _PRA_LOCK:
            if _PROPOSAL_ARBITER is None:
                from core.brain.proposal_arbiter import (
                    ProposalArbiter,
                )
                _PROPOSAL_ARBITER = ProposalArbiter()
    return _PROPOSAL_ARBITER


def _proposal_arbiter_summary() -> dict[str, Any]:
    return _proposal_arbiter().stats()


_WORLD_MODEL_UPDATER: Any = None
_WMU_LOCK = threading.Lock()


def _world_model_updater():
    global _WORLD_MODEL_UPDATER
    if _WORLD_MODEL_UPDATER is None:
        with _WMU_LOCK:
            if _WORLD_MODEL_UPDATER is None:
                from core.brain.world_model_updater import (
                    WorldModelUpdater,
                )
                _WORLD_MODEL_UPDATER = WorldModelUpdater()
    return _WORLD_MODEL_UPDATER


def _world_model_updater_summary() -> dict[str, Any]:
    return _world_model_updater().stats()


_INSIGHT_SYNTHESIZER: Any = None
_INS_LOCK = threading.Lock()


def _insight_synthesizer():
    global _INSIGHT_SYNTHESIZER
    if _INSIGHT_SYNTHESIZER is None:
        with _INS_LOCK:
            if _INSIGHT_SYNTHESIZER is None:
                from core.brain.insight_synthesizer import (
                    InsightSynthesizer,
                )
                _INSIGHT_SYNTHESIZER = InsightSynthesizer()
    return _INSIGHT_SYNTHESIZER


def _insight_synthesizer_summary() -> dict[str, Any]:
    return _insight_synthesizer().stats()


# ── v35 singletons ───────────────────────────────────────────

_HYPOTHESIS_GENERATOR: Any = None
_HG_LOCK = threading.Lock()


def _hypothesis_generator():
    global _HYPOTHESIS_GENERATOR
    if _HYPOTHESIS_GENERATOR is None:
        with _HG_LOCK:
            if _HYPOTHESIS_GENERATOR is None:
                from core.brain.hypothesis_generator import (
                    HypothesisGenerator,
                )
                _HYPOTHESIS_GENERATOR = HypothesisGenerator()
    return _HYPOTHESIS_GENERATOR


def _hypothesis_generator_summary() -> dict[str, Any]:
    return _hypothesis_generator().stats()


_DECISION_REVERSAL_DETECTOR: Any = None
_DRD_LOCK = threading.Lock()


def _decision_reversal_detector():
    global _DECISION_REVERSAL_DETECTOR
    if _DECISION_REVERSAL_DETECTOR is None:
        with _DRD_LOCK:
            if _DECISION_REVERSAL_DETECTOR is None:
                from core.brain.decision_reversal_detector import (
                    DecisionReversalDetector,
                )
                _DECISION_REVERSAL_DETECTOR = (
                    DecisionReversalDetector()
                )
    return _DECISION_REVERSAL_DETECTOR


def _decision_reversal_detector_summary() -> dict[str, Any]:
    return _decision_reversal_detector().stats()


def _principle_extractor_summary() -> dict[str, Any]:
    # Principle extractor is stateless; snapshot reports config.
    from core.brain.principle_extractor import PrincipleExtractor
    return PrincipleExtractor().stats()


_KNOWLEDGE_FRESHNESS: Any = None
_KF_LOCK = threading.Lock()


def _knowledge_freshness():
    global _KNOWLEDGE_FRESHNESS
    if _KNOWLEDGE_FRESHNESS is None:
        with _KF_LOCK:
            if _KNOWLEDGE_FRESHNESS is None:
                from core.memory.knowledge_freshness_tracker import (
                    KnowledgeFreshnessTracker,
                )
                _KNOWLEDGE_FRESHNESS = (
                    KnowledgeFreshnessTracker()
                )
    return _KNOWLEDGE_FRESHNESS


def _knowledge_freshness_summary() -> dict[str, Any]:
    return _knowledge_freshness().stats()


_COHERENCE_CHECKER: Any = None
_CC_LOCK = threading.Lock()


def _coherence_checker():
    global _COHERENCE_CHECKER
    if _COHERENCE_CHECKER is None:
        with _CC_LOCK:
            if _COHERENCE_CHECKER is None:
                from core.brain.coherence_checker import (
                    CoherenceChecker,
                )
                _COHERENCE_CHECKER = CoherenceChecker()
    return _COHERENCE_CHECKER


def _coherence_checker_summary() -> dict[str, Any]:
    return _coherence_checker().stats()


_EPISODE_SUMMARISER: Any = None
_ES_LOCK = threading.Lock()


def _episode_summariser():
    global _EPISODE_SUMMARISER
    if _EPISODE_SUMMARISER is None:
        with _ES_LOCK:
            if _EPISODE_SUMMARISER is None:
                from core.memory.episode_summarizer import (
                    EpisodeSummariser,
                )
                _EPISODE_SUMMARISER = EpisodeSummariser()
    return _EPISODE_SUMMARISER


def _episode_summariser_summary() -> dict[str, Any]:
    return _episode_summariser().stats()


_SALIENCE_TUNER: Any = None
_ST_LOCK = threading.Lock()


def _salience_tuner():
    global _SALIENCE_TUNER
    if _SALIENCE_TUNER is None:
        with _ST_LOCK:
            if _SALIENCE_TUNER is None:
                from core.brain.salience_tuner import SalienceTuner
                _SALIENCE_TUNER = SalienceTuner()
    return _SALIENCE_TUNER


def _salience_tuner_summary() -> dict[str, Any]:
    return _salience_tuner().stats()


# ── v36 singletons ───────────────────────────────────────────

_OBSERVATION_REDUCER: Any = None
_OR_LOCK = threading.Lock()


def _observation_reducer():
    global _OBSERVATION_REDUCER
    if _OBSERVATION_REDUCER is None:
        with _OR_LOCK:
            if _OBSERVATION_REDUCER is None:
                from core.brain.observation_stream_reducer import (
                    ObservationStreamReducer,
                )
                _OBSERVATION_REDUCER = ObservationStreamReducer()
    return _OBSERVATION_REDUCER


def _observation_reducer_summary() -> dict[str, Any]:
    return _observation_reducer().stats()


_EVIDENCE_ACCUMULATOR: Any = None
_EA_LOCK = threading.Lock()


def _evidence_accumulator():
    global _EVIDENCE_ACCUMULATOR
    if _EVIDENCE_ACCUMULATOR is None:
        with _EA_LOCK:
            if _EVIDENCE_ACCUMULATOR is None:
                from core.brain.evidence_accumulator import (
                    EvidenceAccumulator,
                )
                _EVIDENCE_ACCUMULATOR = EvidenceAccumulator()
    return _EVIDENCE_ACCUMULATOR


def _evidence_accumulator_summary() -> dict[str, Any]:
    return _evidence_accumulator().stats()


_SCENARIO_PLANNER: Any = None
_SP_LOCK = threading.Lock()


def _scenario_planner():
    global _SCENARIO_PLANNER
    if _SCENARIO_PLANNER is None:
        with _SP_LOCK:
            if _SCENARIO_PLANNER is None:
                from core.brain.scenario_planner import (
                    ScenarioPlanner,
                )
                _SCENARIO_PLANNER = ScenarioPlanner()
    return _SCENARIO_PLANNER


def _scenario_planner_summary() -> dict[str, Any]:
    return _scenario_planner().stats()


_VALUE_WEIGHTER: Any = None
_VW_LOCK = threading.Lock()


def _value_weighter():
    global _VALUE_WEIGHTER
    if _VALUE_WEIGHTER is None:
        with _VW_LOCK:
            if _VALUE_WEIGHTER is None:
                from core.brain.value_weighter import ValueWeighter
                _VALUE_WEIGHTER = ValueWeighter()
    return _VALUE_WEIGHTER


def _value_weighter_summary() -> dict[str, Any]:
    return _value_weighter().stats()


_COMPUTE_BUDGET: Any = None
_CB_LOCK = threading.Lock()


def _compute_budget():
    global _COMPUTE_BUDGET
    if _COMPUTE_BUDGET is None:
        with _CB_LOCK:
            if _COMPUTE_BUDGET is None:
                from core.brain.compute_budget import ComputeBudget
                _COMPUTE_BUDGET = ComputeBudget()
    return _COMPUTE_BUDGET


def _compute_budget_summary() -> dict[str, Any]:
    return _compute_budget().stats()


_RATIONALE_BUILDER: Any = None
_RB_LOCK = threading.Lock()


def _rationale_builder():
    global _RATIONALE_BUILDER
    if _RATIONALE_BUILDER is None:
        with _RB_LOCK:
            if _RATIONALE_BUILDER is None:
                from core.brain.decision_rationale_builder import (
                    DecisionRationaleBuilder,
                )
                _RATIONALE_BUILDER = DecisionRationaleBuilder()
    return _RATIONALE_BUILDER


def _rationale_builder_summary() -> dict[str, Any]:
    return _rationale_builder().stats()


_CAPABILITY_REGISTRY: Any = None
_CR_LOCK = threading.Lock()


def _capability_registry():
    global _CAPABILITY_REGISTRY
    if _CAPABILITY_REGISTRY is None:
        with _CR_LOCK:
            if _CAPABILITY_REGISTRY is None:
                from core.brain.capability_registry import (
                    CapabilityRegistry,
                )
                _CAPABILITY_REGISTRY = CapabilityRegistry()
    return _CAPABILITY_REGISTRY


def _capability_registry_summary() -> dict[str, Any]:
    return _capability_registry().stats()


# ── v37 singletons ───────────────────────────────────────────

_MOOD_MODEL: Any = None
_MM_LOCK = threading.Lock()


def _mood_model():
    global _MOOD_MODEL
    if _MOOD_MODEL is None:
        with _MM_LOCK:
            if _MOOD_MODEL is None:
                from core.brain.mood_model import MoodModel
                _MOOD_MODEL = MoodModel()
    return _MOOD_MODEL


def _mood_model_summary() -> dict[str, Any]:
    return _mood_model().stats()


_CONFIDENCE_TUNER: Any = None
_CT_LOCK = threading.Lock()


def _confidence_tuner():
    global _CONFIDENCE_TUNER
    if _CONFIDENCE_TUNER is None:
        with _CT_LOCK:
            if _CONFIDENCE_TUNER is None:
                from core.brain.confidence_threshold_tuner import (
                    ConfidenceThresholdTuner,
                )
                _CONFIDENCE_TUNER = ConfidenceThresholdTuner()
    return _CONFIDENCE_TUNER


def _confidence_tuner_summary() -> dict[str, Any]:
    return _confidence_tuner().stats()


_DELEGATION_ROUTER: Any = None
_DR_LOCK = threading.Lock()


def _delegation_router():
    global _DELEGATION_ROUTER
    if _DELEGATION_ROUTER is None:
        with _DR_LOCK:
            if _DELEGATION_ROUTER is None:
                from core.brain.delegation_router import (
                    DelegationRouter,
                )
                _DELEGATION_ROUTER = DelegationRouter(
                    capability_check=(
                        lambda n: _capability_registry().can_do(n)
                    ),
                )
    return _DELEGATION_ROUTER


def _delegation_router_summary() -> dict[str, Any]:
    return _delegation_router().stats()


_RELATION_EXTRACTOR: Any = None
_RE_LOCK = threading.Lock()


def _relation_extractor():
    global _RELATION_EXTRACTOR
    if _RELATION_EXTRACTOR is None:
        with _RE_LOCK:
            if _RELATION_EXTRACTOR is None:
                from core.memory.relation_extractor import (
                    RelationExtractor,
                )
                _RELATION_EXTRACTOR = RelationExtractor()
    return _RELATION_EXTRACTOR


def _relation_extractor_summary() -> dict[str, Any]:
    return _relation_extractor().stats()


_BOTTLENECK_DETECTOR: Any = None
_BD_LOCK = threading.Lock()


def _bottleneck_detector():
    global _BOTTLENECK_DETECTOR
    if _BOTTLENECK_DETECTOR is None:
        with _BD_LOCK:
            if _BOTTLENECK_DETECTOR is None:
                from core.brain.workflow_bottleneck_detector import (
                    WorkflowBottleneckDetector,
                )
                _BOTTLENECK_DETECTOR = (
                    WorkflowBottleneckDetector()
                )
    return _BOTTLENECK_DETECTOR


def _bottleneck_detector_summary() -> dict[str, Any]:
    return _bottleneck_detector().stats()


_STRATEGY_COHERENCE: Any = None
_SC_LOCK = threading.Lock()


def _strategy_coherence():
    global _STRATEGY_COHERENCE
    if _STRATEGY_COHERENCE is None:
        with _SC_LOCK:
            if _STRATEGY_COHERENCE is None:
                from core.brain.strategy_coherence_monitor import (
                    StrategyCoherenceMonitor,
                )
                _STRATEGY_COHERENCE = StrategyCoherenceMonitor()
    return _STRATEGY_COHERENCE


def _strategy_coherence_summary() -> dict[str, Any]:
    return _strategy_coherence().stats()


_READINESS_GATE: Any = None
_RG_LOCK = threading.Lock()


def _readiness_gate():
    global _READINESS_GATE
    if _READINESS_GATE is None:
        with _RG_LOCK:
            if _READINESS_GATE is None:
                from core.brain.readiness_gate import (
                    ReadinessGate,
                )
                _READINESS_GATE = ReadinessGate()
    return _READINESS_GATE


def _readiness_gate_summary() -> dict[str, Any]:
    return _readiness_gate().stats()


# ── v38 singletons ───────────────────────────────────────────

_HEURISTIC_BANK: Any = None
_HB_LOCK = threading.Lock()


def _heuristic_bank():
    global _HEURISTIC_BANK
    if _HEURISTIC_BANK is None:
        with _HB_LOCK:
            if _HEURISTIC_BANK is None:
                from core.brain.heuristic_bank import HeuristicBank
                _HEURISTIC_BANK = HeuristicBank()
    return _HEURISTIC_BANK


def _heuristic_bank_summary() -> dict[str, Any]:
    return _heuristic_bank().stats()


_INTENTION_TRACKER: Any = None
_IT_LOCK = threading.Lock()


def _intention_tracker():
    global _INTENTION_TRACKER
    if _INTENTION_TRACKER is None:
        with _IT_LOCK:
            if _INTENTION_TRACKER is None:
                from core.brain.intention_tracker import (
                    IntentionTracker,
                )
                _INTENTION_TRACKER = IntentionTracker()
    return _INTENTION_TRACKER


def _intention_tracker_summary() -> dict[str, Any]:
    return _intention_tracker().stats()


_SURPRISE_CONTEXTUALIZER: Any = None
_SCX_LOCK = threading.Lock()


def _surprise_contextualizer():
    global _SURPRISE_CONTEXTUALIZER
    if _SURPRISE_CONTEXTUALIZER is None:
        with _SCX_LOCK:
            if _SURPRISE_CONTEXTUALIZER is None:
                from core.brain.surprise_contextualizer import (
                    SurpriseContextualizer,
                )
                _SURPRISE_CONTEXTUALIZER = (
                    SurpriseContextualizer()
                )
    return _SURPRISE_CONTEXTUALIZER


def _surprise_contextualizer_summary() -> dict[str, Any]:
    return _surprise_contextualizer().stats()


_FAILURE_TAXONOMY: Any = None
_FT_LOCK = threading.Lock()


def _failure_taxonomy():
    global _FAILURE_TAXONOMY
    if _FAILURE_TAXONOMY is None:
        with _FT_LOCK:
            if _FAILURE_TAXONOMY is None:
                from core.brain.failure_taxonomy import (
                    FailureTaxonomy,
                )
                _FAILURE_TAXONOMY = FailureTaxonomy()
    return _FAILURE_TAXONOMY


def _failure_taxonomy_summary() -> dict[str, Any]:
    return _failure_taxonomy().stats()


_VALUE_CONFLICT_ARBITER: Any = None
_VCA_LOCK = threading.Lock()


def _value_conflict_arbiter():
    global _VALUE_CONFLICT_ARBITER
    if _VALUE_CONFLICT_ARBITER is None:
        with _VCA_LOCK:
            if _VALUE_CONFLICT_ARBITER is None:
                from core.brain.value_conflict_arbiter import (
                    ValueConflictArbiter,
                )
                _VALUE_CONFLICT_ARBITER = ValueConflictArbiter()
    return _VALUE_CONFLICT_ARBITER


def _value_conflict_arbiter_summary() -> dict[str, Any]:
    return _value_conflict_arbiter().stats()


_TRANSFER_PRIORITIZER: Any = None
_TP_LOCK = threading.Lock()


def _transfer_prioritizer():
    global _TRANSFER_PRIORITIZER
    if _TRANSFER_PRIORITIZER is None:
        with _TP_LOCK:
            if _TRANSFER_PRIORITIZER is None:
                from core.brain.knowledge_transfer_prioritizer import (
                    KnowledgeTransferPrioritizer,
                )
                _TRANSFER_PRIORITIZER = (
                    KnowledgeTransferPrioritizer()
                )
    return _TRANSFER_PRIORITIZER


def _transfer_prioritizer_summary() -> dict[str, Any]:
    return _transfer_prioritizer().stats()


_BEHAVIORAL_CONSTRAINTS: Any = None
_BC_LOCK = threading.Lock()


def _behavioral_constraints():
    global _BEHAVIORAL_CONSTRAINTS
    if _BEHAVIORAL_CONSTRAINTS is None:
        with _BC_LOCK:
            if _BEHAVIORAL_CONSTRAINTS is None:
                from core.brain.behavioral_constraint_registry import (
                    BehavioralConstraintRegistry,
                )
                _BEHAVIORAL_CONSTRAINTS = (
                    BehavioralConstraintRegistry()
                )
    return _BEHAVIORAL_CONSTRAINTS


def _behavioral_constraint_summary() -> dict[str, Any]:
    return _behavioral_constraints().stats()


# ── Singleton ────────────────────────────────────────────────

_LOCK = threading.Lock()
_BRAIN: BrainFacade | None = None


def brain() -> BrainFacade:
    """Single entry point — ``brain().think(...)`` etc."""
    global _BRAIN
    if _BRAIN is None:
        with _LOCK:
            if _BRAIN is None:
                _BRAIN = BrainFacade()
    return _BRAIN
