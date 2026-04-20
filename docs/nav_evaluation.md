# nav: evaluation

Pre-flight, offline, and regression verification.

## Physical source

- `simulation/launch_simulator.py` — Monte Carlo profit
  projection per candidate SKU (1000 trials default).
  `LaunchCandidate.from_landed_cost()` wires in A2.
- `simulation/` — portfolio (economic_simulator) and
  adoption-curve (market_simulator) scenarios.
- `execution/verify/post_write_verifier.py` — read-back
  after Shopify write (D2 wire pending).
- `core/brain/world_model_calibration.py` — predicted
  vs. actual drift.
- `tests/` — pytest suite (223+ green at last count).

## Facade

`evaluation/__init__.py` re-exports
`LaunchCandidate`, `LaunchProjection`,
`simulate_launch`, plus the verify helpers.

## CLI

```
python cli.py simulate --cost 5 --price 30 \
    --daily-budget 20 --days 3
```

Returns p25/p50/p75 profit + break-even probability +
verdict ∈ {go, caution, stand_down}.

## MCP

`launch_simulate` tool in the default registry.

## Rules

- Every live-write path needs a simulate step (the
  PublisherBundle does `dry_run=True` by default).
- Add a regression test when you change a decision
  threshold. `tests/` uses pytest; run
  `PYTHONPATH=. pytest tests/ -q`.
- Snapshot-test AI prompts if you change a prompt.
