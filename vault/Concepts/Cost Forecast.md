---
title: "Cost Forecast"
tags: [concept, cost, forecast, trajectory, reliability]
created: "2026-04-14"
related:
  - "[[Memory]]"
  - "[[Reflection Hook]]"
  - "[[Capability Routing]]"
---

# Cost Forecast

## Summary

A per-caller cost-trajectory forecaster. The cost ledger tells
operators **what** was spent; this module answers **"at the
current burn rate, will this caller blow past its monthly
budget before the billing cycle ends?"** — before the answer is
"too late".

## Why a separate module

The cost ledger sits on the hot router path and must stay cheap.
Forecasting involves a ring buffer of samples, window slicing,
and a linear regression — all of which belong on the telemetry
side, not the per-call write side. Forecasting also needs a
configurable horizon (1h, 24h, 30d), which a ledger bundled to
one fixed horizon can't serve.

## How it works

- **Ring buffer** — the last N samples (default 120) of
  per-caller ledger totals, timestamped.
- **Short window** — recent slice (default 1h) used to compute
  the burn rate in `usd / hour`.
- **Long window** — the caller's *first appearance* in the
  sample history to the latest sample; serves as the baseline
  for spike detection.
- **Spike detection** — when `short_burn / long_burn` exceeds
  a configurable ratio (default 2.0) **and** the long window
  has at least 2× the coverage of the short window, the caller
  is flagged `is_spike`. The coverage guard prevents
  warm-up samples from firing false positives.
- **Projection** — `projected_usd = current_usd + short_burn * horizon_hours`,
  clamped at zero for negative burn (ledger reset, bucket
  folding, etc.).

## Why new callers don't always look like spikes

A caller that joined mid-stream used to trip every spike rule
because the first absolute sample had them at `$0` by
definition. The long-burn anchor now resolves to the caller's
*first appearance* in the sample history, and the coverage
guard requires long-window span ≥ 2× short-window before any
spike can fire — so warmup noise stays silent.

## Related

- [[Memory]]
- [[Reflection Hook]]
- [[Capability Routing]]
