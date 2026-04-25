# nav: orchestrator

Turns a goal into 20 deterministic steps.

## Physical source

- `core/core_orchestrator.py` — 14-phase synchronous cycle.
- `scripts/autopilot_loop.py` — 24/7 winner → publish →
  activate daemon.
- `scripts/owner_loop.py` — Telegram poll + digest push.
- `execution/launch/publisher_bundle.py` — transactional
  winner → Shopify → Meta Ads pipeline.

## Facade

`orchestrator/__init__.py` re-exports the stable surface:
`CoreOrchestrator`, `PublisherBundle`, `LaunchRequest`,
`LaunchResult`. Prefer importing from the facade.

## Cycle phases (in order)

```
data → quality → brain → cognitive → rl_pricing →
segmentation → forecast → layers(12) → decisions →
smart_exec → learning → marketing → strategy →
revenue_strategy → seo_analysis → profit_analysis →
dashboard → report
```

## Launch pipeline (PublisherBundle.launch)

```
1. copy (ContentGenerator)
2. product_creation (Shopify REST)
2.4 video_generate (fal.ai) ← A6
2.5 eu_ai_compliance (EUAIActGate) ← A1
3. campaign_launch (Meta Ads)
4. outcome fingerprint (OutcomeRecorder)
5. rationale commit (RationaleLedger)
```

## When to edit

- New orchestrator method? Prefer hooking into an existing
  phase or adding a `_step_<name>` to the launch pipeline.
- Daemons — extend `autopilot_loop` / `owner_loop`; do
  not fork.
