# nav: feedback

The closed-loop learning wire. Every real-world signal
flows in here.

## Physical source

- `core/attribution/outcome_recorder.py` — normalised
  purchase / return / cancel events → brain learners.
- `core/webhooks/order_handler.py` — Shopify order.paid
  entrypoint. Records OutcomeTracker + KPITracker +
  RevenueTracker + brain + engine outcome bus.
- `core/bridge/agentic_storefront.py` — ChatGPT /
  Perplexity / Copilot / Gemini channel classification.
- `core/integration/engine_outcome_bus.py` — fan-out
  from any engine to RuleBook + WorldModelCalibration +
  SourceTrustCalibrator + FreshnessTracker +
  PatternMiner.

## Facade

`feedback/__init__.py` re-exports `OutcomeEvent`,
`OutcomeRecorder`, `AgenticStorefrontBridge`,
`EngineOutcome`, `get_engine_outcome_bus`, and the
Moby vote comparator.

## Flow (paid order → brain)

```
Shopify order.paid webhook
  → OrderWebhookHandler.handle_order_paid()
  → OutcomeRecorder.record(OutcomeEvent(kind=purchase))
  → brain.record_calibration / record_funnel_event
  → agentic bridge classify → engine_outcome_bus report
  → MobyVoteComparator.resolve_outcome (A7)
```

## Rules

- Any new action that could drive revenue must end with
  `OutcomeRecorder.record()` or `engine_outcome_bus
  .report()`. An action without an outcome is dead code.
- Never bypass the recorder — even internal decisions
  (plan_quarter, federation ops) record so rules can
  learn which actions work.
