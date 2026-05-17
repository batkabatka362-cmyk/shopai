# Empire-AGI cross-store workflow

ShopAI's empire-AGI surface lets one operator manage many Shopify
stores by harvesting decisions that worked on one store and
porting them to another. This doc is the runbook: every command,
in order, with expected output and troubleshooting notes.

## The 7-step loop

```bash
shopai transfer sources --to B           # 1. pick best source A
shopai transfer suggest --from A --to B  # 2. see candidates
shopai transfer apply ... --dry-run      # 3. preview
shopai transfer apply ...                # 4. enqueue PENDING on B
shopai approvals show <id>               # 5. operator review
# (approve → execute → outcome capture)
shopai transfer history                  # 6. audit what shipped
shopai transfer outcomes                 # 7. did it pay off?
```

Each step is read-only or single-action; nothing runs against
Shopify without explicit approval.

## Step 1 — Pick the best source store

```bash
shopai transfer sources --to store-b
```

For every other store in the fleet, count unique (engine,
action_type) tuples that executed on that store and were NOT
tried on the target. Output ranks stores by transferable
surface area:

```text
Transfer sources for target 'store-b' (top 3 of 5 candidates):

  [1] store-a  transferable=8  (of 12 unique actions, 24 total executed)
      sample: cart_recovery/mint_cart_recovery_code, ...
  [2] store-c  transferable=3  (of 5 unique actions, 9 total executed)
      sample: loyalty/mint_loyalty_code, ...
  [3] store-d  transferable=0  (of 2 unique actions, 5 total executed)

  Next step:  shopai transfer suggest --from store-a --to store-b
```

Pick the top source and use it in step 2. If every store ranks
0, none of your fleet members have a track record of actions
that target-B hasn't already considered — either run the loop
on more stores first or wait for activity to accumulate.

## Step 2 — Get specific recommendations

```bash
shopai transfer suggest --from store-a --to store-b
```

Returns the ranked (engine, action_type) tuples worth porting,
joined with outcome aggregates from the source store:

```text
Transfer suggestions: store-a → store-b (3 candidates)

  [1] loyalty/mint_loyalty_code
      capability=SHOPIFY_CREATE_DISCOUNT  runs=5  positive=4 negative=0  rev=$425.00
      sample params: customer_id, percentage, ttl_days

  [2] cart_recovery/mint_cart_recovery_code
      capability=SHOPIFY_CREATE_DISCOUNT  runs=3  positive=3 negative=0  rev=$180.00
```

Higher positive outcomes → higher rank.

## Step 3 — Preview before enqueueing

```bash
shopai transfer apply \
    --from store-a --to store-b \
    --engine loyalty \
    --action-type mint_loyalty_code \
    --dry-run
```

Shows the source-template id, the params that would carry
forward (with any operator overrides), and the auto-generated
narrative. Nothing is written to the queue.

If you need to override params (e.g. swap a customer_id):

```bash
shopai transfer apply ... \
    --params-json '{"customer_id": "gid://shopify/Customer/NEW"}' \
    --dry-run
```

## Step 4 — Enqueue PENDING on the target

Drop `--dry-run` and rerun:

```bash
shopai transfer apply \
    --from store-a --to store-b \
    --engine loyalty --action-type mint_loyalty_code
```

The action lands on the target store's queue with status PENDING.
No Shopify mutation runs. Operator approval (step 5) gates that.

If you want to add a note for the reviewer:

```bash
shopai transfer apply ... \
    --narrative "Black Friday parity"
```

The note is prepended to the auto-narrative with a `  ||  `
separator.

## Step 5 — Review + approve

Use the action_id printed by step 4:

```bash
shopai approvals show <action_id> --with-context
```

`--with-context` joins similar past decisions (across the fleet)
so the reviewer sees outcomes from the source store's runs.
Then approve / reject through the normal approval flow.

Once approved, the action executes through the standard Phase
6/7 writer → Shopify mutation path.

## Step 6 — Audit what's been transferred

```bash
shopai transfer history --to store-b
```

Lists every transfer-applied action targeting store-b, with
its current status (pending / executed / failed) and age.
Filter by `--from <store>`, `--engine <name>`, `--limit N`.

## Step 7 — Did the transfer pay off?

```bash
shopai transfer outcomes --to store-b
```

For every EXECUTED transfer on store-b, pulls the recorded
outcomes (orders/created webhooks, refunds, etc.) and rolls
polarity + revenue. The rollup distinguishes
`actions_with_outcomes` from `actions_without_outcomes` — the
second is the "applied but feedback lag" signal.

## Where transfer activity shows up elsewhere

- **`shopai daily-brief`** — morning rollup includes a transfer
  activity block (count applied / executed / pending + polarity
  badges) when there's activity in the window.
- **`shopai world-model show <store>`** — per-store snapshot
  has a `transfers` section with incoming + outgoing buckets.
- **`shopai engine fleet <engine>`** — see how one engine
  performs across stores; useful for diagnosing whether a
  transfer-worthy engine is consistent.
- **`shopai engine compare <a> <b>`** — head-to-head if you're
  choosing between two engines to roll out fleet-wide.
- **`shopai engine ranking`** — fleet-wide leaderboard.

## Live verification on a dev environment

`scripts/transfer_demo_seed.py` seeds synthetic per-store
actions so the workflow has something to demo against on a
fresh install:

```bash
python scripts/transfer_demo_seed.py --from demo-a --to demo-b --n 2
# Seeded 8 action(s).

shopai transfer sources --to demo-b
shopai transfer suggest --from demo-a --to demo-b
shopai transfer apply --from demo-a --to demo-b \
    --engine loyalty --action-type DEMO_mint_loyalty_code --dry-run

# When done, clean up:
python scripts/transfer_demo_seed.py --from demo-a --to demo-b --clean
```

Rows are prefixed `DEMO_` so the `--clean` flag can grep + wipe
without touching real data.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `transfer sources` returns nothing | No fleet stores have EXECUTED actions yet. Run `shopai auto --once` on a few stores or use the demo seed. |
| `transfer suggest` returns nothing | The `--from` store has activity but every (engine, action_type) is already on `--to`. Try another source via `transfer sources`. |
| `transfer apply` errors "no successful X found on source" | Either the action_type spelling is off, or no row on source has status EXECUTED. Check `shopai engine summary <engine>`. |
| `transfer apply` errors "already exists on target store" | The (engine, action_type) is present on target in some status (incl. PENDING/REJECTED). Operator already considered it. Look at `transfer history --to <target>`. |
| `transfer outcomes` rollup shows `actions_without_outcomes` high | Feedback lag — outcomes arrive via Shopify webhooks (orders, refunds) which can take days. Not a bug; that's the signal. |
| Pre-PR-#239 queue: `--store` flag errors | The queue predates the store_id column. Run `shopai db migrate`. |

## Architecture notes

- Transfer detection is **narrative-based**, not schema-based.
  Every `transfer apply` writes a marker into the action's
  narrative; the four read paths (history, outcomes, daily-brief,
  world-model) all filter on `Transfer suggestion:%` SQL LIKE.
  The format is centralized in `core/transfer_narrative.py`.
- Per-store filtering depends on `pending_actions.store_id`
  (PR #239). Pre-migration rows have `store_id=NULL` and don't
  participate in transfers.
- Active-store thread-local (PR #243) means autonomous-loop
  iterations auto-tag enqueued actions. `transfer apply` sets
  it explicitly via the `store_id=` kwarg.
- The v2 AGI guardrail (PRs #245/#247/#250) is independent of
  transfers: it refuses mints fleet-wide when the AGI signal
  is unambiguously negative, regardless of source.
