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

### 2026-04-20 · pre-existing · P2 · duplicate test name, order-flaky

`test_fetch_products_raises_when_unavailable` is defined in **three
separate test files**:

  * tests/test_core.py
  * tests/test_integration.py
  * tests/test_stub_cleanup.py

Runs clean in isolation; fails in full-suite sweep because an
earlier cycle run leaves ShopifyBridge in a state where the
``unavailable`` assertion no longer holds. Likely module-level
cache pollution; not introduced by §4c iterations.

**Repro:** `pytest tests/ --ignore=tests/test_intelligence_systems.py`

**Fix direction:** dedupe the three copies, or gate the assertion
on a fresh bridge instance with explicit env reset. Defer — does
not block mission work.

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

### 2026-04-20 · `_phase_events` list crash on real campaigns

Fixed in the autonomous-loop iteration following
bb47f61. `_phase_events` called
`campaigns["optimization"].get("actions", [])` but
`optimization` is a **list** of action dicts when real campaigns
ran through the optimizer (same list-vs-dict shape as
update_marketing). Defensive isinstance() shield added; pause
actions now fire `campaign.underperform` events correctly.
Regression locked by
`tests/test_core_orchestrator.py::test_events_phase_survives_list_optimization`.

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
