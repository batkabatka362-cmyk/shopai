# nav: engines

The "verb" layer. ~2,500 modular engines that each
perform one domain-specific skill.

## Physical source

`engines/` — grouped by domain. Examples:

- `engines/pricing/` — RL pricer (Thompson Sampling).
- `engines/marketing/` — ad variant generator,
  creative ranker, audience targeter.
- `engines/fulfillment/` — supplier router, SLA monitor.
- `engines/analytics/` — cohort, funnel, retention.
- `engines/content/` — blog / email / landing-page
  writers.

## Contract

Every engine:
- Single file, single class, single public method.
- Injectable deps (http, db, llm) so tests run offline.
- Emits outcome via `engine_outcome_bus.report()` when
  the result drives a decision.

## Discovery

```
python cli.py engines --list
python cli.py engines --run pricing.rl_pricer --sku ...
```

## Rules

- Before creating a new engine, grep for existing work:
  `grep -rln "def <verb>" engines/`.
- Engines MUST NOT import from `core/brain/` (one-way
  dependency: brain uses engines, not the reverse).
- If an engine needs new data, add it to `data_pipeline/`
  and let the engine read from the cache.
- Failing engines should return a neutral no-op, not
  raise — the cycle keeps running.
