# ShopAI audit log

> Per CLAUDE.md §4c — rabbit-hole discipline. When a bug / gap is
> discovered during other work and fixing it is out of scope for
> the current commit, note it here with:
>
>   * date + commit that surfaced it
>   * severity (P0 → P4)
>   * reproduction steps / commands
>   * proposed fix
>   * status (open / fixed / wontfix)
>
> Closed items stay in the log as a history of audit passes.

---

## Open

### 2026-04-20 · pre-existing · P2 · `event_processing` type error

Surfaced while smoke-testing SHOPAI_BRAIN_HOOKS=1 with real
campaigns (commit 87f3a65 / 440367d). Warning:

```
shopai.core_orchestrator: Event processing failed:
'list' object has no attribute 'get'
```

Origin unknown — `_phase_events` or one of its downstream modules
expects a dict but receives a list. Does not crash the cycle
because the phase is wrapped in try/except + logger.warning,
but it does mean the events phase produces zero output on real
campaign input.

**Repro:** any `run_cycle` call that supplies non-empty campaigns.
**Next:** grep for `event_result.get`-style coercions, add
defensive isinstance() shields. Batch with other
"list vs dict" audit sweeps.

---

### 2026-04-20 · pre-existing · P3 · engines/ dead code sweep

~2500 engines in `engines/` per CLAUDE.md §2. Many are
likely stubs, half-finished, or unreferenced. Audit pass needed:

  * `grep -rL "def " engines/ --include="*.py"` empty modules
  * `find engines/ -name "*.py" -not -newer <N months ago>`
    stale entries
  * test coverage report for engines/ directory
  * `brain_facade` reachability — which engines are actually
    invoked

**Next:** dedicated audit session once P0/P1 roadmap items clear.

---

### 2026-04-20 · pre-existing · P2 · missing decision_id on webhook

`OrderWebhookHandler.handle_order_paid` reads
`shopai_decision_id` + `shopai_campaign_id` from
`order.note_attributes`, and `shopai_confidence` from a flat
field. But no current execution code path **writes** those
annotations when launching a campaign. So the outcome_recorder
calibration loop never actually records a decision→outcome link
on real orders — it falls through to the "no decision_id" branch.

**Fix direction:** when Meta Ads adapter creates a campaign (or
the publisher bundle launches a product), attach
`shopai_decision_id = <cycle_id>:<decision_trace_id>` to the
Shopify checkout URL via discount/UTM so Shopify orders carry
it through `note_attributes`. This is the actual closed-loop
wiring the outcome recorder was built for.

**Next:** expand publisher bundle (M2.4) with Shopify
attribution injection.

---

## Fixed

### 2026-04-20 · `store_snapshot.update_marketing` list crash

Fixed in commit 440367d. Accepts both list (real campaigns) and
dict (no-campaigns path). Test coverage via
`tests/test_core_orchestrator.py`.

### 2026-04-20 · `observe_kpi` duplicate method shadow

Fixed in commit 87f3a65. Merged the two `observe_kpi` methods on
`BrainFacade` — previously the forecaster-routed one silently
overrode the predictive_alerter one. Single method now forwards
to both learners.

### 2026-04-20 · compute_budget floating-point warn threshold

Fixed in commit fe2926a. `0.10 * 0.8 = 0.08000000000000002 > 0.08`
made the warn line unreachable by equality. Added 1e-9 tolerance.

### 2026-04-20 · value_weighter Lock → RLock deadlock

Fixed during v36 sprint. `observe` held `Lock` then called
`weights()` which re-acquired. Swapped to `RLock`.

### 2026-04-20 · failure_taxonomy Lock → RLock deadlock

Fixed during v38 sprint. `stats()` held `Lock` then called
`dominant_category()` which re-acquired. Swapped to `RLock`.
