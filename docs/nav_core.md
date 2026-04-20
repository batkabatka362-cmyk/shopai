# nav: core

The brain. Every decision, every memory write, every
learning signal goes through here.

## Entry points

- `core/core_orchestrator.py` — 14-phase cycle. `run_cycle()`
  is the single call per autonomous tick.
- `core/brain/decision_brain.py` — one-shot decisions.
- `core/brain/brain_facade.py` — singleton access to the 6
  learners (v33-v38: calibration, world-model, capability,
  funnel, predictive, mood).
- `core/brain/brain_state_synthesizer.py` — holistic
  `BrainState` snapshot exposed by `cli.py brain` and the
  MCP `brain_snapshot` tool.

## Memory ladder

- `core/memory/intelligent_memory.py` — L0-L5 storage.
- `core/memory/consolidator.py` — episode → concept
  promotion.
- `core/memory/memory_intelligence.py` — write-once API.

## Learning pipeline (Event → Pattern → Rule → Strategy)

- `core/learning/pattern_miner.py`
- `core/learning/llm_pattern_miner.py`
- `core/learning/rulebook.py`
- `core/learning/outcome_tracker.py`

## Rules for new work

- Never create a new brain / memory / orchestrator.
  Extend an existing one or wire into the facade.
- Every new decision site must emit an outcome via
  `core/attribution/outcome_recorder.py`.
- Closed-loop: outcome must reach a learner, or the code
  is dead.
