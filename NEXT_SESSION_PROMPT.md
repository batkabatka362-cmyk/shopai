# Next Session — Starter Prompt

Copy-paste the block below into the next chat session.

---

## PROMPT START

I'm continuing work on ShopAI. The core audit is complete — 20 fixes landed
(B through U) across 3 waves, core score went from ~7.5/10 to 9.85/10, and
3076 tests pass. Branch: `claude/setup-core-orchestrator-kpaIP`.

Read these two files first for full context:
- `CORE_AUDIT_REPORT.md` — what's been done to the core
- `NEXT_PHASE_PLAN.md` — the direction for this session

**Core principle for this phase:** The core (brain, memory, learning, decisions,
goals) is done. It's at 9.85/10 and every loop is closed. DO NOT write new
engines, new brain logic, new memory backends, or new business features.

Instead: **find working external apps/tools/AIs and connect them to ShopAI
via thin adapters.** The core already decides WHAT to do via DecisionBrain.
What it needs is HANDS — production-grade external systems to actually execute.
Each adapter is ~100-200 lines; zero changes to core.

The core already has:
- `SmartRouter` that routes by capability + weight + availability (adapter-aware)
- `ActionWeightStore` that learns each adapter's success rate via EMA
- `ExplorationBoost` that will try new adapters periodically
- `JudgmentAdvisor` safety gate before live calls
- `LearningLoop` that captures outcomes + generates rules

The moment I register a new adapter, all six of those systems pick it up
automatically. My job is just to wrap external APIs in the `BaseAdapter`
interface — nothing more.

### Wave 1 target (start here)

Pick ONE of these and build the adapter + register it + write a regression
test that proves the core can route to it via SmartRouter:

1. **Stripe adapter** — payment + refund + dispute handling
2. **SendGrid or Postmark adapter** — 2nd email provider (Brevo + Resend
   already exist in Phase 5); test router fallback behavior
3. **DALL-E 3 adapter** — product image generation; wire it as the
   execution handler for the `refresh_images` action (Fix S added the
   decision option, the execution is still TODO)
4. **Playwright adapter** — browser automation for tasks Shopify API can't do

Please start by asking me which one you should build first. While you wait,
read `NEXT_PHASE_PLAN.md` to see the full Wave 1-5 target list.

### Rules for this phase
- ONE adapter at a time
- Each adapter: AdapterFile + register in router + regression test (~3 files)
- Test must prove SmartRouter can route a core decision to the new adapter
- Test must prove ActionWeightStore captures the outcome
- NO changes to core files (core/brain, core/memory, core/goals, core/judgment,
  core/autonomous/controller.py) unless they're pure additions for adapter support
- Follow the commit style from Fix B-U: clear message, test file, regression guard
- Run full suite after each adapter; it should stay at 3076 passing (any new
  tests added only)

### What to AVOID
- Writing new business logic inside the adapter — it's a thin wrapper
- Storing state in the adapter — the core owns state via UnifiedMemory
- Building "utilities" or "helpers" — use existing ones in `utils/`
- Creating new SmartRouter patterns — the router is already adapter-aware
- Touching the 49 stub engines, 12 layer stubs, 6 missing agents — those are
  NOT the goal of this phase

### Success test
At the end of this session I should be able to run:
```
python cli.py auto --store deguar
```
...and see the autonomous cycle route a decision to a NEW external system that
wasn't connected before, with the outcome captured in ActionWeightStore and
visible in the cycle's attribution trail.

Ask me which adapter to build first, then proceed.

## PROMPT END
