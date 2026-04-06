# Cognitive Core

This package adds the missing pieces that turn ShopAI's reactive
engine pipeline into a self-directed cognitive system. It does
**not** replace `core/brain/`, `core/memory/`, or
`core/intelligence/` — it sits on top of them and orchestrates the
modules already there into a richer cycle.

## The 9 modules

Each module is independently importable and testable. The `mind`
module at the top ties them together into the main loop.

### Phase 1 — Foundation (introspection)

| Module | Purpose | Key API |
|---|---|---|
| `self_model.py`  | What can I do? Where am I weak? What don't I know? | `assess()`, `capabilities()`, `strengths()`, `weaknesses()`, `knowledge_gaps()`, `narrative()` |
| `goals.py`       | Self-directed goal generation + lifecycle              | `propose()`, `propose_from_self_model()`, `pick_next()`, `revise()`, `complete()` |
| `reflection.py`  | Meta-cognition over past decisions                     | `reflect(apply=True)` → `ReflectionReport(lessons=[...])` |

### Phase 2 — Active reasoning

| Module | Purpose | Key API |
|---|---|---|
| `planner.py`     | Decompose a goal into executable steps                 | `plan(goal)` → `Plan` (LLM backend with heuristic fallback) |
| `imagination.py` | Counterfactual simulation of hypothetical outcomes     | `imagine_step()`, `imagine_plan()`, `compare([plans])` |
| `curiosity.py`   | Knowledge-gap-driven exploration drive                 | `recommend()` → explore vs exploit, `propose_exploration_goal()` |

### Phase 3 — Deep learning

| Module | Purpose | Key API |
|---|---|---|
| `consolidation.py`  | Memory "sleep" phase: dedup, prune, rescore, extract  | `run()` → `ConsolidationReport` |
| `skill_registry.py` | Runtime skill acquisition + composition               | `propose()`, `validate()`, `invoke()`, `compose()` |
| `theory_of_mind.py` | Beliefs about external agents (customers, competitors) | `register_agent()`, `observe()`, `predict_response()` |

### Phase 4 — Integration

| Module | Purpose | Key API |
|---|---|---|
| `mind.py` | The unified 9-phase cognitive cycle | `run_cycle()` → `CycleReport` |

## The cognitive cycle

`Mind.run_cycle()` runs the 9 phases in this order:

```
PERCEIVE  → REFLECT → SET_GOALS → PLAN → IMAGINE
   → PREDICT → ACT → LEARN → CONSOLIDATE (every Nth cycle)
```

Each phase reads from the modules in earlier phases and writes
to the `CycleContext` and `CycleReport`. Missing modules degrade
gracefully — Mind detects them and skips the dependent phases.

```
   ┌─────────────┐
   │  PERCEIVE   │  pull recent data + SelfModel snapshot
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │   REFLECT   │  Reflection over recent memory episodes
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │  SET_GOALS  │  GoalManager.propose_from_self_model
   │             │  + Curiosity.propose_exploration_goal
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │    PLAN     │  Planner.plan(top_goal)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │   IMAGINE   │  Imagination.imagine_plan(plan)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │   PREDICT   │  TheoryOfMind.predict_response per agent
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │     ACT     │  SkillRegistry.invoke matching skill,
   │             │  else emit recommendation
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │    LEARN    │  SelfModel.assess cycle outcomes
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │ CONSOLIDATE │  every Nth cycle: dedup, prune, extract
   └─────────────┘
```

## Quick start

```python
from core.cognitive.mind import build_default_mind

mind = build_default_mind()
report = mind.run_cycle()
print(report.headline())
print(report.to_dict())
```

CLI:

```bash
shopai mind status              # self-narrative + active goals
shopai mind cycle               # run one cognitive cycle
shopai mind reflect             # force a reflection pass
shopai mind goals               # list active goals
shopai mind skills              # list registered skills
shopai mind explain <goal_id>   # show plan + imagined outcome
```

## Database registration

Each cognitive module that needs persistence registers itself with
the migration framework so `shopai db status` lists it:

| DB | Schema |
|---|---|
| `self_model`     | capabilities + assessments audit + snapshots |
| `goals`          | goals + goal_events audit |
| `theory_of_mind` | agents + observations |

`SkillRegistry` is in-memory (skills are code, not data).
`Reflection`, `Planner`, `Imagination`, `Curiosity`, `Consolidation`,
and `Mind` are stateless wrappers around the others.

## Design principles

1. **Each module does one thing.** SelfModel knows only about
   capabilities; Reflection knows only about lesson extraction;
   Planner knows only about decomposition. Mind is the only place
   that wires them together.

2. **Heuristic + LLM hybrid.** Every module that could call an LLM
   has a deterministic heuristic fallback. The system runs to
   completion even with no LLM configured. When Ollama is
   available, the LLM-backed paths take over without code changes.

3. **Confidence is a first-class axis.** A capability can have a
   high score with low confidence (small sample) or vice versa.
   Beliefs in TheoryOfMind are clamped to `[0.05, 0.95]` so the AI
   is never absolutely certain or absolutely sure.

4. **Dedup at the source.** GoalManager dedupes practice goals,
   Curiosity dedupes exploration goals, Consolidation dedupes
   memory episodes. This keeps state small even after thousands of
   cycles.

5. **Audit logs everywhere.** Every assess(), every observation,
   every state transition is appended to a log table so the
   Reflection module can trace exactly why a number changed.

6. **Tests as documentation.** Each module has a unit test file
   covering every public method. `tests/test_cognitive_integration.py`
   contains end-to-end "stories" that drive multi-cycle scenarios
   through real instances. If you change a public API, the tests
   describe what callers expect.

## What's NOT here

- **Consciousness.** This is a cognitive architecture, not a
  conscious agent. The modules track their own state and reason
  about their own actions, but there's no claim of subjective
  experience.

- **AGI.** The Planner is template-based or LLM-backed; it does
  not generalize across truly novel situations. The TheoryOfMind
  predictor is rule-driven.

- **Real-time learning of new neural weights.** Skills are
  Python callables, not learned models. SkillRegistry provides
  the *interface* for runtime skill acquisition; the actual
  learning of new behaviors needs an LLM or a separate ML stack.

## Tests

```bash
# Unit tests per module
pytest tests/test_self_model.py tests/test_goals.py \
       tests/test_reflection.py tests/test_planner.py \
       tests/test_imagination.py tests/test_curiosity.py \
       tests/test_consolidation.py tests/test_skill_registry.py \
       tests/test_theory_of_mind.py tests/test_mind.py \
       tests/test_mind_cli.py

# End-to-end integration
pytest tests/test_cognitive_integration.py
```

Total: ~340 tests across the cognitive package.
