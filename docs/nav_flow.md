# nav: flow

The learning ladder: Event → Pattern → Rule → Strategy.

## Physical source

- `agents/learning/pattern_promoter.py` — promotes
  patterns to rules after evidence threshold.
- `agents/learning/pattern_decay.py` — demotes rules
  that stop working.
- `core/memory/consolidator.py` — episode ➝ concept
  promotion (60s sweep).
- `core/learning/rulebook.py` — SQLite-backed rule
  store with thread-safe RLock.
- `core/learning/pattern_miner.py` — deterministic
  k-occurrence detector.
- `core/learning/llm_pattern_miner.py` — LLM-assisted
  pattern detection (budgeted).
- `workflows/` — reusable workflow recipes.

## Facade

`flow/__init__.py` re-exports `RuleBook`, `PatternMiner`,
`PatternPromoter`, `Consolidator`.

## Thresholds (from CLAUDE.md §2)

```
Cycle  1: Event created
Cycle  3: 3+ similar events  → Pattern
Cycle  5: 5+ evidence Pattern → Rule
Cycle 10: 10+ uses + 70% ok  → Strategy
Failures: 3+ identical errors → Avoidance rule
```

## CLI

```
python cli.py brain-learned     # top rules
python cli.py memory            # ladder snapshot
```

## Rules

- Don't promote a rule by hand — the promoter sweeps
  every cycle. Just emit events.
- If a new decision surface needs to learn, hook it to
  `engine_outcome_bus.report()` and walk away.
- PatternMiner is deterministic; LLM miner is budgeted
  to $0.02 / cycle.
