# CLAUDE.md — Working Notes for the ShopAI Shopify Integration

This file describes how to operate inside this codebase as a senior software
engineer. It is written for *me* — the assistant working on the Shopify
adapter layer — so that future sessions pick up the same standards
without rediscovery.

## The mission (overriding direction, 2026-05-19)

**ShopAI is the autonomous AGI merchant on Shopify.** End goal: a
single command (or autonomous cycle) takes a fresh Shopify store
from "credentials configured" to "launchable + earning revenue"
with no operator hand-holding.

**Code is the primary work.** Planning, discussion, and audits
are subordinate to shipping working code that actually moves the
needle. When in doubt, ship a small substantive PR — don't write a
plan first.

**Measurable outcomes are the bar, not "it runs".** Every change
must produce a measurable result that a future audit can verify:
revenue impact, conversion lift, time-to-launch, error rate
reduction. A feature that "works" in the sense of not crashing
but produces no measurable improvement is dead weight. Wire every
applier through ``record_writeback`` so its outcomes flow into the
Phase 8 learning loop and ``daily-brief`` / ``engine summary``
surfaces.

**Build for ecosystem mastery, not free-tool mediocrity.** The
delta between "it works" and "it's excellent" is what makes this
an AGI merchant rather than another middleware toolkit. Concretely:

- Every adapter validates inputs at the boundary, returns
  structured errors, and follows the existing 130+ adapter
  patterns documented below.
- Every engine output flows through ``record_writeback`` so
  outcomes are joinable to revenue.
- Every operator surface (CLI / world-model / digest) renders
  the same signal so context never has to be re-derived from
  another command.
- Every new capability is paired with a real-world consumer
  (applier + generator + test + Pattern Z recording).
  Capabilities without consumers are unfinished work.

When picking the next PR, ask: "Does this move the autonomous
merchant closer to launching + earning, with measurable
outcomes, in a way that compounds with the rest of the
ecosystem?" If yes, ship it. If no, pick something else.

## Who I am, what I'm building

I'm a senior software engineer extending **ShopAI's Shopify adapter
layer** under `core/adapters/shopify/`. ShopAI is an autonomous
Shopify operator: engines (pricing, ROAS guardrails, creative,
fulfillment, analytics, …) decide what to do, the adapter layer
translates those decisions into vendor-specific API calls. Every
adapter I add unlocks a class of engine action that previously had to
be done manually.

The architecture has four layers:

```
engines/*  →  Capability enum  →  AdapterRouter  →  Shopify*Adapter  →  Shopify GraphQL
                                                       (this is me)
```

The router resolves an abstract `Capability` to whichever adapter
declares support for it. Adding a capability without an adapter is
dead weight; adding an adapter without a capability is unreachable.

## How I work

### 1. Audit before code

Before adding anything I:
- Read at least one similar adapter (`metafield.py`, `risk.py`,
  `inventory.py`) to match the prevailing pattern.
- Grep for the capability name in the enum to see if it already exists
  (`grep "SHOPIFY_" core/adapters/base.py`).
- Skim the relevant Shopify GraphQL doc page to see whether the
  operation is one mutation or a multi-step dance (e.g. fulfillment is
  two-step, files can be one-step URL or three-step staged).

### 2. One adapter per commit

Each Phase 1/2/3 deliverable lands as a single commit on the feature
branch. Commits bundle: enum entry → adapter → bootstrap registration
→ tests → router-test extension → bootstrap-count bump. Live
verification goes in the commit message under "Live verification".
This makes review and rollback simple.

### 3. Friendly shapes hide GraphQL

Engines speak in business terms ("create a 10% recovery discount valid
for 7 days"); Shopify speaks in `DiscountCodeBasicInput.customerGets.
value.percentage = 0.10`. The adapter is the translator. Callers must
NEVER have to write GraphQL or know that `percentage` is a 0-1 fraction
on Shopify's side. Convention:

| ShopAI input                       | Shopify GraphQL              |
| ---                                | ---                          |
| snake_case keys                    | camelCase keys               |
| 0-100 percentages                  | 0-1 fractions                |
| `2026-06-01T00:00:00Z` ISO strings | `DateTime` scalars           |
| `gid://shopify/X/123`              | same (always pass GIDs raw)  |

### 4. Validate at the boundary

A bad input should raise `AdapterValidationError` BEFORE the GraphQL
call. The reasoning:

- Network round-trip is slow; validation is free.
- Shopify's `userErrors` envelope often comes back with
  `"Generic error"` for malformed inputs — useless for debugging.
- The router falls back on `AdapterError` (vendor failure) but NOT on
  `AdapterValidationError` (caller bug). Fail-fast keeps falls
  honest.

Validation lives in a `_build_X_input` static method or inline in
`_execute`. Required-field checks raise immediately; optional fields
default silently. Numeric strings are coerced (`int("2") == 2`); types
that can't be coerced (`"many"`) raise.

### 5. No silent mock fallbacks

If credentials are missing or the live API fails, return an empty
list (reads) or `{"status": "error", ...}` (writes) — NEVER fabricate
data. This matches the policy enforced in
`core/bridge/shopify_bridge.py` (the `ShopifyBridgeUnavailable`
exception was added specifically because pre-cleanup mock fallbacks
let broken creds masquerade as "successful empty reads" and quietly
corrupted engine decisions).

### 6. Live verify before declaring done

A test pass is necessary but not sufficient. Every adapter goes through
a `python -c "..."` smoke test against the dev store
(`ts0efe-ih.myshopify.com`) before I claim it's done. The smoke test:

- Hits a list/read first (cheap, no side effects, validates auth).
- Hits a create/write second (proves the wire format is right and the
  scopes cover it).
- Verifies the response shape matches what the adapter normalised.

The output of the smoke test goes into the commit message under "Live
verification" so reviewers see proof, not a promise.

### 7. Test conventions

Patch `_gql` at the adapter boundary, not the underlying HTTP. Cover:

- **Metadata** — name, capabilities set.
- **Every validation branch** — one test per failure mode.
- **Happy path** — full GraphQL response, including nested money
  sets and edge/node envelopes.
- **userErrors propagation** — `result.ok is False` (not raise — the
  base class catches and returns failure).
- **Response edge cases** — empty pages, null fulfillment_status, list
  vs string tags, missing variants, etc.

For each new adapter: bump `TestShopifyBootstrap.test_register_all_adds_N_adapters`
to N+1 with the new name in the expected set, and extend
`TestShopifyBootstrap.test_router_picks_shopify_for_each_capability`
with assertions for the new capabilities.

## How I think and decide

### Pick the path that maps to actual engines

When two paths exist (e.g. URL upload vs staged upload, full GraphQL
vs REST), pick the one that matches what ShopAI's engines actually
output today. Files: creative pipeline emits URLs → URL upload wins.
Discounts: pricing engine wants code-based, time-bounded → that's
`discountCodeBasicCreate`, not `discountAutomaticBasicCreate`.

Speculative paths get deferred to a Phase 2/3 plan, not built. The
codebase is already 4000+ test cases; adding stubs without consumers
is debt.

### Trade-off analysis is part of the commit message

Every non-obvious decision goes in the "Why" section of the commit
message:
- "Local-file uploads (staged) are out of scope; every consumer has a
  URL because the upstream generators are HTTP services."
- "client_credentials only available for apps in the same org as the
  store; OAuth authorization_code flow is the fallback when managed
  install fails."
- "alt is truncated to 512 chars rather than failing the whole batch
  on one long caption."

Future-me reads commit messages, not Slack threads.

### Capability enum is the contract

Adding `SHOPIFY_X` to the enum is a public commitment that the
adapter layer will eventually support it. I add the enum entry only
when I'm about to implement it (or in the same commit as the adapter).
I do NOT pre-populate the enum with capabilities I might build later.

### Phase work, don't sprawl

Tier 1 = adapters that match an existing engine. Tier 2 = nice-to-have
where the engine doesn't exist yet but the surface area is well-known
(Marketing Events, Returns, Metaobjects). Tier 3 = long tail (Themes,
Translations, Publications, Order Edits, Payment/Delivery
Customizations) — only built when an engine demands them.

I finish Tier 1 entirely before starting Tier 2.

## Workflow checklist

For each new adapter:

- [ ] Confirm or add `Capability` enum entry in `core/adapters/base.py`.
- [ ] Create `core/adapters/shopify/<name>.py` extending `ShopifyBaseAdapter`.
- [ ] Implement `_execute(capability, params)` with per-capability dispatch.
- [ ] Friendly call shape with `_build_<noun>_input` static helper if non-trivial.
- [ ] `_normalise_<noun>` helper that flattens nested response shapes.
- [ ] Register class in `core/adapters/shopify/bootstrap.py`.
- [ ] Add test class `TestShopify<Name>Adapter` in `tests/test_shopify_adapters.py`.
- [ ] Bump `test_register_all_adds_N_adapters` count + expected set.
- [ ] Extend `test_router_picks_shopify_for_each_capability`.
- [ ] `python -m pytest tests/test_shopify_adapters.py` — all green.
- [ ] Live smoke test against dev store; capture output.
- [ ] Commit with structured message (Why / What changed / Tests /
      Live verification).
- [ ] Push to feature branch.
- [ ] Update todo list.

## What I don't do

- **Don't bundle adapters in one commit.** Review and revert get hard
  fast.
- **Don't paper over Shopify rejections.** Surface them as
  `AdapterValidationError` (caller bug) or `AdapterError` (vendor
  failure) — never log-and-return-fake-success.
- **Don't pre-build capabilities for hypothetical engines.** Tier 3
  features wait until something asks for them.
- **Don't bypass `ShopifyBaseAdapter`.** The base does auth, GraphQL,
  error mapping, and result assembly. Re-implementing those at the
  leaf is duplication waiting to drift.
- **Don't write multi-paragraph code comments.** One terse line max,
  and only when the WHY is non-obvious.
- **Don't claim "done" without live verification.** Smoke test or it
  doesn't ship.

## Schema discoveries — patterns I've already paid for

Phase 1-3 surfaced a set of recurring schema oddities that the docs
underspecified. Anyone adding the next adapter should expect to hit
at least one of these — it's faster to encode the patterns here than
re-derive them live.

### Pattern A: identifier outside the input dict

Shopify's *external* mutations consistently put the resource id at
the GraphQL field level, NOT inside the *Input dict. Caught live on:

- ``marketingActivityUpdateExternal`` (id is `marketingActivityId` arg)
- ``marketingEngagementCreate`` (id is `marketingActivityId` arg,
  input is `marketingEngagement`)
- ``orderEditCommit`` and friends (id is top-level `id` arg)
- ``themeFilesUpsert`` (id is top-level `themeId` arg)
- ``publishablePublish`` (id is top-level `id` arg)

If a mutation rejects with "Field is not defined on …Input", check
whether the id should live as a top-level argument instead.

### Pattern B: `Query.X` does not exist for some entities

Some resources only paginate through their parent. Caught live on:

- ``Query.returns`` does NOT exist; use ``orders → returns``.
- Returns are reachable per-order via ``order(id:).returns``.
- ``ReturnSortKeys`` enum likewise undefined at the top level.

When a list capability doesn't have a top-level connection, traverse
through the parent and flatten on the adapter side.

Additional Pattern B cases:

- ``Query.companyContactRoles`` does NOT exist; roles hang off
  ``company(id:).contactRoles``. The adapter takes a company_id
  param and traverses through the company node.

### Pattern C: required-but-undocumented fields

Mutations regularly require fields the docs gloss over. The pattern:
a happy-path call rejects with `"Field X expected to not be null"`,
then a subsequent call rejects on the next missing field, and so on.

Confirmed on `marketingActivityCreateExternal`:
- ``tactic`` required (default to AD for paid campaigns)
- ``budget`` required (auto-default from ad_spend)
- ``remoteUrl`` required (third-party dashboard link)
- ``utm.source/medium/campaign`` required for sales attribution

Also `MarketingEngagementInput.utcOffset` required (default `+00:00`).

When a mutation throws "expected to not be null", add the field as
required in the friendly call shape; fail-fast at the validator
beats burning a GraphQL hop on every missing field.

### Pattern D: response field names that drift

Schema versioning sometimes flips return-shape fields. Adapter must
tolerate both forms when the cost is low:

- `shopifyqlQuery.tableData.rows` (current) vs `rowData` (legacy)
- `Return.declineReason` doesn't exist on the Return type at all —
  echo the value the caller sent rather than reading from the
  response.
- `ShopFeatures.multiLocation` and `ShopFeatures.onlineStore` were
  removed in the 2024-01 schema. Stable subset only:
  branding/captcha/giftCards/harmonizedSystemCode/
  internationalDomains/internationalPriceOverrides/
  internationalPriceRules/legacySubscriptionGatewayEnabled/
  reports/sellsSubscriptions/showMetrics/storefront.
- `Article.authorV2 { name email }` was renamed to a simpler
  `author { name }` in 2024-01. The legacy selection no longer
  compiles; query `author.name` and there's no email sub-field.
- `shopifyPaymentsAccount.disputes` does NOT accept
  `sortKey`/`query`/`reverse` arguments (unlike most connections).
  Pagination only — engines that need ordering / filtering have to
  do it client-side after fetch. Also: `ShopifyPaymentsDisputeSortKeys`
  enum is not defined at all, so a query that declares it as an
  unused variable still fails at validation.
- `Collection.productsCount` returns a `Count` wrapper
  (`{ count: N }`) in 2024-01+, not a scalar. Same shape as
  `Company.ordersCount`. Tolerate both forms in normalisation.
- `priceLists` connection does NOT accept a `query` filter argument
  (unlike most connections). Pagination only — same restriction as
  `disputes`. Adapter silently drops the param.
- `AutomaticDiscountSortKeys` is a NARROW enum — only `CREATED_AT`
  and `ID`. The broader keys that other connections accept (TITLE,
  STARTS_AT, RELEVANCE, ...) all reject. The much wider
  `CodeDiscountSortKeys` for the code-based discount connection is
  unrelated.
- `MarketWebPresence.defaultLocale` and `.alternateLocales` return
  `ShopLocale` objects in 2024-01, NOT bare locale-code strings.
  Add a `{ locale name primary published }` selection or the query
  rejects with selectionMismatch. Adapter normaliser accepts both
  the dict (current) and string (legacy) forms.
- `CustomerMergePreview` lost `resultingCustomer` entirely — the
  post-merge customer is reachable only via a follow-up
  `customer(id:)` query after the merge runs. Its `blockingFields`
  /`alternateFields`/`defaultFields` are typed objects (each
  per-conflict-class), and `customerMergeErrors` is a list of typed
  CustomerMergeError nodes — no flat `fields: [String]` selection
  works. Cheapest correct selection is `{ __typename }` on each so
  engines get a presence/absence signal; detailed inspection comes
  from the merge mutation's userErrors path.
- `discountCodeBxgyCreate` rejects `{ all: true }` for both
  `customerBuys.items` and `customerGets.items` — they MUST be
  scoped to specific products or collections (Shopify's BXGY engine
  needs scoped sides for the rule to evaluate). Also `customerSelection`
  is silently REQUIRED — omitting it returns "Customer selection
  can't be blank". Adapter defaults customerSelection to `{ all: true }`
  so engines that don't pass it still get the standard public-facing
  discount.
- `ShopifyPaymentsPayoutSummary` per-bucket fields (chargesGrossAmount,
  chargesFeeAmount, refundsGrossAmount, ...) DON'T EXIST in the
  2024-01 schema — the summary type was restructured. Likewise
  `ShopifyPaymentsBankAccount.last4` and `.accountType` were
  removed. Stable subset: payout id/status/issuedAt/gross/net plus
  bankAccount.id/.bankName. Engines that need fee-bucket detail
  use the bulk-query path or the third-party Shopify Payments
  REST API.
- **Markets API rework (2026 schema).** Whole surface area moved:
  - `MarketCreateInput.enabled` → removed; replaced with
    `status: MarketStatus` enum (`DRAFT` / `ACTIVE`).
  - `MarketCreateInput.regions` → removed; replaced with
    `conditions: MarketConditionsInput` containing
    `regionsCondition.regions[].countryCode`.
  - `Market.enabled` / `Market.primary` / `Market.regions` → all
    removed from the response type; use `status`, `type`, and
    `conditions.regionsCondition.regions` respectively.
  - `marketRegionsCreate` and `marketRegionDelete` mutations →
    DELETED. Region add/remove now happens through `marketUpdate`
    with `input.conditions.conditionsToAdd.regionsCondition.regions`
    or `input.conditions.conditionsToDelete.regionsCondition.regionIds`.
  - `MarketConditionsRegionsInput` is a `@oneOf` union — exactly
    ONE of `{regionIds, regions, applicationLevel}` may be present.
    Sending `regions` AND `applicationLevel` together fails with
    `'MarketConditionsRegionsInput' requires exactly one argument,
    but 2 were provided`. `applicationLevel` is for the all-countries
    policy; specific-country lists drop it.
- `customerAddressCreate`/`customerAddressUpdate` payloads return
  `address: MailingAddress` — NOT `customerAddress`. Likewise
  `customerAddressDelete` returns `deletedAddressId`, NOT
  `deletedCustomerAddressId`. Older REST/legacy field names don't
  carry over to the GraphQL Admin API.
- `customerAddress*` mutations also use the typed `UserError`
  variant (no `code` field) — same Pattern F as draft-order /
  order-edit family. Drop `code` from those userErrors selections.
- `giftCardUpdate` userErrors are typed `UserError` (no `code`),
  but `giftCardCreate` (`GiftCardUserError`) and `giftCardCredit`
  / `giftCardDebit` (`GiftCardTransactionUserError`) all DO have
  `code`. Pattern F applies per-mutation, not per-resource.
- `productDelete` and `productDuplicate` userErrors are typed
  `UserError` (no `code`) — same Pattern F. Most product
  mutations DO use `UserErrors` (with code), so check per-mutation.
- `orderCancel` returns `orderCancelUserErrors` (NOT the
  standard `userErrors` key) of type `OrderCancelUserError`
  (has `code`). The base `_check_user_errors` helper looks for
  the literal key `userErrors`, so adapters using
  `orderCancel` must pull `orderCancelUserErrors` manually
  rather than relying on the helper.
- `orderClose` / `orderOpen` / `orderMarkAsPaid` use the typed
  `UserError` (no `code`) — Pattern F applies. Drop `code`
  from those userErrors selections.
- `collectionCreate` / `collectionUpdate` / `collectionDelete`
  all use the typed `UserError` (no `code`) — Pattern F.
- `collectionReorderProducts` requires the target collection to
  have `sortOrder=MANUAL`. Calling it on a collection sorted by
  best-selling / alphabetical / etc. fails with
  `"Can't reorder products unless collection is manually sorted"`.
  Adapter surfaces the userError verbatim — pre-checking would
  add a read round-trip on every call.
- `inventorySetQuantities` requires either per-quantity
  `compareQuantity` (optimistic concurrency check) OR a
  top-level `ignoreCompareQuantity: true`. Omitting both fails
  with `"compareQuantity argument must be given to each
  quantity or ignored"`. Pattern C — adapter defaults to
  `ignoreCompareQuantity=true` when the caller doesn't supply
  per-quantity compare values.
- `fulfillmentTrackingInfoUpdate` and `fulfillmentCancel` both
  use the typed `UserError` (no `code`) — Pattern F. Drop
  `code` from those userErrors selections.
- `productReorderMedia` returns `mediaUserErrors` (NOT the
  standard `userErrors` key) of type `MediaUserError` (has
  `code`). Same shape as `orderCancel`'s `orderCancelUserErrors`
  — the base `_check_user_errors` helper looks for the literal
  `userErrors` key and misses this one. Adapters using
  `productReorderMedia` extract the custom key manually.
- `InventoryTransfer.origin` and `.destination` are
  `LocationSnapshot` (a value-typed snapshot at transfer-creation
  time), NOT `Location`. The snapshot has `name` directly but
  the underlying `id` lives under `.location.id`. Selecting
  `origin { id }` fails with "Field 'id' doesn't exist on
  LocationSnapshot". Use `origin { name location { id name } }`.
- `InventoryTransferEditInput` uses `originId` /
  `destinationId`, but `InventoryTransferCreateInput` uses
  `originLocationId` / `destinationLocationId`. Pattern D —
  same logical field, different camelCase names per mutation.
  Adapter routes friendly snake_case (`origin_location_id`)
  to the right field per call site.
- `discountAutomaticBulkDelete` / `discountCodeBulkDelete`
  treat **null GraphQL variables as "set"**. Sending
  `{ids: [...], search: null, savedSearchId: null}` fails
  with "Only one of IDs, search argument or saved search ID
  is allowed" even though only `ids` is non-null. Pattern C
  / D: emit ONLY the chosen selector key; route to one of
  three pre-built mutation variants per selector. The same
  trap applies to any "exactly one of" mutation arg set.

### Pattern D-prime: oneOf input objects

Newer Shopify input types are tagged with the GraphQL `@oneOf`
directive — only one of their fields may be set per call.
Introspection still lists them as nullable, so the constraint is
invisible until the API rejects the call with `INVALID_VARIABLE`
plus `'X' requires exactly one argument, but N were provided`.

Confirmed on:

- `MarketConditionsRegionsInput` — pick exactly one of
  `regionIds` / `regions` / `applicationLevel`.

When introspection shows multiple optional fields on an *Input
type, default to sending only one and only add a second one
after the API confirms it.

### Pattern E: schema-gated fields

Some fields live behind approval gates beyond OAuth scopes. The
field is *hidden from the schema entirely* until the gate clears,
producing a "Field doesn't exist on type" error even when the scope
is present.

- `Query.shopifyqlQuery` requires Level 2 protected-customer-data
  declaration on top of `read_reports`.

When the schema gate is the merchant's paperwork (not code), document
it loudly in the adapter docstring and ship the wire format that
will work after the gate clears.

### Pattern F: UserError type variants

Two related types in the schema, one with `code` and one without:

- `UserError` (used by `orderEdit*`, `draftOrderCalculate`,
  `draftOrderInvoicePreview`, and `draftOrderInvoiceSend`) → no
  `code` field.
- `UserErrors` (used by everything else) → has `code`.

If a mutation rejects with "Field 'code' doesn't exist on type
'UserError'", drop the `code` selection from that mutation only.

### Pattern G: money input shape coercion is per-adapter

Multiple adapters (marketing, order_edits, draft_orders) accept
money inputs. Each has its own `_money_input` helper inlined rather
than imported from a shared utils module. The recurring tension —
share-it-or-inline-it — resolved toward inline because:

- The error messages reference the adapter ("shopify_marketing_events:
  ad_spend amount must be numeric") which is more useful at the
  call site than a generic "money: ...".
- A shared utils module would need its own test surface; per-adapter
  inlines stay covered by each adapter's tests.

If a fourth adapter adds money handling, reconsider — but two or
three is the wrong threshold.

### Pattern H: hint-level diagnostics in tests are convention

`fake_gql(q, v)` test stubs leave `q` (and sometimes `v`) unused on
purpose so signatures match the patched call site. The IDE flags
these as "unused-parameter" hints — they are not errors, do not
silence them with `_`-prefix renames, the existing 60+ test stubs
all use the unprefixed form.

### Pattern I: capability-name parity between engine and adapter is silent if broken

The router resolves `Capability.X` to whichever adapter declares
support for `X`. When an engine call site references a capability
name that exists in the enum but is not claimed by any adapter,
the failure mode is silent: the router has no route, the
hydrator's exception/`ok=False` path returns `[]`, and the engine
falls through to its standard "X list is required" guard — exactly
the failure mode auto-hydration was meant to prevent.

Caught live on `SHOPIFY_FETCH_ORDERS` (PR #40): 14+ engine flows
called the `FETCH_` form (matching `SHOPIFY_FETCH_CUSTOMERS` and
`SHOPIFY_FETCH_PRODUCTS` precedent) but the orders adapter only
declared `SHOPIFY_LIST_ORDERS`. The Phase 5 hydrator roll-out
appeared to work in unit tests (mocked routers) but was a no-op
in production for every order-consuming engine.

Discovered via this audit, in case it's useful for the next pass:

```bash
# Find every capability used by engine hydrators...
grep -rh 'capability_name="SHOPIFY_' engines/ |
  grep -oE "SHOPIFY_[A-Z_]+" | sort -u

# ...and confirm each has at least one adapter claiming it.
for cap in $(...); do
  grep -l "Capability\.$cap" core/adapters/shopify/*.py | wc -l
done
```

Naming inconsistency to be aware of: `customers.py` uses
`SHOPIFY_FETCH_CUSTOMERS` (no `LIST_` form in the enum), `orders.py`
now claims both `LIST_ORDERS` and `FETCH_ORDERS`, `products.py`
uses `SHOPIFY_LIST_PRODUCTS` (with `inventory.py` separately
claiming `SHOPIFY_FETCH_PRODUCTS`). Engines should match whatever
the adapter actually declares; the audit above is the cheapest
verification.

### Pattern J: feedback systems must short-circuit under pytest

`engines/_writeback_recorder.py` (Phase 8) fans every writeback into
three persistent stores — MemoryIntelligence, DataArchitecture,
LearningLoop — all of which back to **on-disk SQLite**. When a unit
test exercises an applier that calls `record_writeback`, those
three stores receive the synthetic test payload exactly as if it
were a production action. The data lingers in the dev DB, and the
failure-intelligence pipeline (auto-generates avoidance rules at
3+ similar failures) starts emitting rules derived from test
fixtures.

Caught live on Phase 6/7 appliers: `failure_analysis` table held
entries like `[dynamic_pricing] adapter_failed: scope_missing: 3`
and `[loyalty] network blip` that came straight out of the test
suite's fail-path mocks. Engines making real-world decisions could
have started avoiding `scope_missing` as if it were a recurring
production class.

The bug class is general — any module that lazy-imports a global
singleton and writes to it during normal operation will get hit
the moment a test runs that module's code path. Mocking the
fan-out targets in *every* test that touches an applier is brittle;
the right cut is at the recorder boundary.

Fix (PR #54):

```python
import os

def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))

def record_writeback(*, ...):
    if _is_test_environment():
        return
    # ... fan out to MemoryIntelligence + DataArchitecture + LearningLoop
```

Tests that need to verify recorder behaviour install an autouse
fixture that patches `_is_test_environment` to return `False`,
turning the guard back off for that test only:

```python
@pytest.fixture(autouse=True)
def _disable_test_env_guard():
    with patch(
        "engines._writeback_recorder._is_test_environment",
        return_value=False,
    ):
        yield
```

Anything new that calls a real persistent store from inside an
adapter or engine (analytics, audit log, telemetry sink) needs the
same gate — assume the test suite WILL exercise that path and
WILL leave residue otherwise.

### Pattern Z: writer modules must call ``record_writeback``

Mirrors Pattern J but for the OUTGOING side. Every writer module
(file matching ``*_applier.py`` / ``*_minter.py`` / ``*_payer.py``)
that calls a Shopify mutation must ALSO call ``record_writeback``
so Phase 8 (MemoryIntelligence + DataArchitecture + LearningLoop)
sees the outcome.

Caught live on PR #205: four discount-code minters
(``browse_recovery``, ``cart_recovery``, ``email_marketing``,
``wholesale_b2b``) minted real codes via the shared
``mint_recovery_code`` helper but skipped ``record_writeback``.
The minted codes were live on Shopify, but the autonomous loop
never saw the mint events. Recommender + EMA undercount these
engines.

The CI gate (``shopai pattern-z-audit``, PR #206) AST-scans
writer modules for any of (``execute``, ``_router_call``,
``mint_recovery_code``, ``_mint``) calls and verifies there's
a ``record_writeback`` call in the same file. Writers that only
enqueue (no direct mutation) are legitimately skipped — the
queue path's recording is the executor's responsibility (closed
by PR #207).

The fix template, mirroring ``engines/loyalty/discount_minter.py``:

```python
from engines._writeback_recorder import record_writeback

def my_writer(...):
    result = router.execute(capability, params)
    record_writeback(
        engine="my_engine",
        action_type="apply_my_thing",
        capability="SHOPIFY_X",
        params={...},
        success=result.ok,
        error=None if result.ok else result.error,
    )
    return result
```

### Pattern Q: engines must return the canonical envelope

Every engine's ``run()`` method must return a dict with the four
canonical keys: ``{status, data, meta, error}``. ``status`` must
be one of ``{"success", "error", "fail"}``. Implicit contract
documented in every engine's docstring but never enforced until
PR #213.

The envelope is consumed by:
  - The approval queue narrative (reads ``data`` + ``meta.engine``).
  - The Phase 8 recorder (uses ``status`` for the success flag).
  - The recommender's ``record_outcome`` hook.
  - The autonomous-loop dashboard.

A refactor that drops one of the four keys ships silently — the
envelope dict is computed dynamically and an AST walk can't
verify it. The CI gate (``shopai pattern-q-audit``) is a
RUNTIME audit: it actually calls each engine's ``run()`` with
an empty input envelope, then checks the result has all four
keys + a valid status value.

Four violation classes:
  - ``missing_keys``: one of {status, data, meta, error} absent.
  - ``not_a_dict``: ``run()`` returned a non-dict (None, str, list).
  - ``bad_status``: status not in the accepted literal set.
  - ``raised``: ``run()`` threw on empty input.

Engines that need real data return ``status="error"`` cleanly;
they still emit the four-key envelope (engines/loyalty/flow.py
is the canonical reference).

## The eight institutional audits

The repo gates every PR on eight AST + runtime audits (each is a
standalone CLI command + a CI step + a section in
``shopai doctor`` + an entry in the consolidated ``shopai audit``):

| Audit | What it catches | Type |
|---|---|---|
| Pattern K | enqueued action_type has a dispatcher | AST |
| OAuth | every adapter declares ``required_scopes`` | runtime |
| Pattern Y | every ``Capability.SHOPIFY_*`` enum has 1+ adapter | runtime |
| Pattern I | every engine's ``capability_name=`` references a real enum + adapter | AST |
| Pattern J | writes to learning singletons are test-guarded | AST |
| Pattern Z | every writer module calls ``record_writeback`` | AST |
| Pattern Q | every engine's ``run()`` returns the canonical envelope | runtime |
| Wireup resolve | every Phase-7 wired engine has a resolvable ``apply_*`` flag (621f9f26) | runtime |

When adding a new pattern, the convention is:

1. New module under ``engines/`` or ``core/adapters/`` named
   ``_pattern_<letter>_audit.py`` (lowercase letter; pick the
   next unused).
2. Returns a dataclass ``Pattern<Letter>Report`` with a
   ``has_violations: bool`` property.
3. CLI command ``shopai pattern-<letter>-audit`` with ``--json``.
4. Wire into the consolidated ``shopai audit`` (label in
   ``_AUDIT_LABELS``, entry in ``_AUDIT_ORDER``, branch in
   ``_run_one_audit``).
5. CI gate in ``.github/workflows/ci.yml``.
6. Tests under ``tests/test_pattern_<letter>_audit.py``.
7. Update this section + add a "### Pattern <Letter>:" subsection.

## Current branch state

Branch: `claude/shopify-api-integration-oQzce` → PR #22.

Phase 1 (Tier 1) — **complete, all live-verified**:
- `774ecaf` ShopifyDiscountAdapter
- `a106efb` ShopifyFilesAdapter
- `f2511f8` ShopifyDraftOrdersAdapter

Phase 2 (Tier 2) — **complete, all live-verified**:
- `466b128` ShopifyMarketingEventsAdapter (+ this CLAUDE.md)
- `ae8e090` ShopifyReturnsAdapter
- `52d7a2e` ShopifyMetaobjectsAdapter

Phase 3 (Tier 3) — **complete**:
- `1bf1a51` ShopifyPublicationsAdapter (live-verified)
- `8be093f` ShopifyOrderEditsAdapter (schema-verified)
- `e0b264c` ShopifyThemesAdapter (live-verified)
- `c05d890` ShopifyAnalyticsAdapter (schema-correct, gated by
  protected-data approval)

Phase 4 (long tail) — **complete**:

- ShopifyTranslationsAdapter (`translations.py`)
- ShopifyCustomerSegmentsAdapter (`segments.py` +
  `customer_segment_write.py` — covers `SHOPIFY_QUERY_SEGMENT`,
  `SHOPIFY_CREATE_SEGMENT`, `SHOPIFY_UPDATE_CUSTOMER_SEGMENT`,
  `SHOPIFY_DELETE_CUSTOMER_SEGMENT`)
- ShopifyRefundsAdapter (`refunds.py`)
- ShopifyPaymentCustomizationsAdapter (`customizations.py`)
- ShopifyDeliveryCustomizationsAdapter (`customizations.py`)

Adapter coverage is now ~99.2% of the enum (379/382 capabilities
wired). Stragglers: `SHOPIFY_APP`, `SHOPIFY_NATIVE` (placeholders).

Phase 5 (engine-side hydrators) — **complete**:
Systematic roll-out of `engines._shopify_hydrator.hydrate()` across
the engine layer. 51 engines now auto-fetch their primary input
list from Shopify when the caller leaves it empty, instead of
failing with the standard "X list is required" guard. PR #29
extracted the shared core; PRs #30–#39 wired engines in 10 batches:
batch1 (5), batch2 (5), batch3 (5), batch4 (5), batch5 (5),
batch6 (5), batch7 (5), batch8 (5), batch9 (3), batch10 (3 +
`hydrate_one` variant for singular-dict inputs). PR #40 fixed a
critical capability-name parity bug (see Pattern I below). Plus
6 engines wired pre-batch1: `bundle`, `browse_recovery`, `catalog`,
`churn_prediction`, `cohort_analysis`, `cart_recovery`. Only
`product_research` remains unwired — function-based pipeline,
intentional skip.

The engine-layer pattern lives at
`engines/_shopify_hydrator.py` with `hydrate()` (list-shape) and
`hydrate_one()` (singular-dict). Per-engine wrappers are now thin
— they just pick the right `capability_name` and `list_field`.

Phase 6 (engine-side writebacks) — **complete**:
Phase 5 closed the *read* loop (engines auto-fetch input data).
Phase 6 closes the *write* loop — recommender engines now
perform actual Shopify mutations when explicitly opted in. Five
engines, five PRs:

- PR #43 — `loyalty` mints per-customer discount codes from
  tier rewards. Wraps `engines._recovery_codes.mint_recovery_code`
  in `engines/loyalty/discount_minter.py`. Opt-in via
  `data.apply_rewards = True`.
- PR #44 — `discount_strategy` mints storewide promo codes
  (multi-use, customer-reusable). This required extending
  `mint_recovery_code` with `usage_limit` / `applies_once_per_customer`
  params (defaults preserved → all earlier minters unchanged).
  Wraps in `engines/discount_strategy/discount_minter.py`. Opt-in
  via `data.apply_discount = True`. Three safety guardrails:
  type must be `percentage_off`, `cannibalization_risk != "high"`,
  configurable confidence floor.
- PR #45 — `tag_management` applies auto-generated tags via
  `SHOPIFY_UPDATE_PRODUCT` with a MERGED tag list (existing +
  new, dedup case-insensitive). Critical because productUpdate
  REPLACES tags — passing only new would wipe existing.
  `engines/tag_management/tag_applier.py`. Opt-in via
  `data.apply_tags = True`.
- PR #46 — `dynamic_pricing` applies approved price adjustments
  via `SHOPIFY_UPDATE_VARIANTS`. The change_validator stage
  already gates each adjustment's `approved` flag; the writer
  re-checks it. Required adding `approved` to the engine's
  per-product output. `engines/dynamic_pricing/price_applier.py`.
  Known limitation: hydrator-fetched products from
  `SHOPIFY_LIST_PRODUCTS` don't include variants — callers
  wanting writeback need to pre-fetch via `SHOPIFY_GET_PRODUCT`.
- PR #47 — `affiliate` pays commissions as Shopify gift cards
  (different shape — gift cards, not discount codes — since
  affiliate output is a payment OWED). Joins commissions to
  the partners list for email / customer_id lookup, calls
  `SHOPIFY_CREATE_GIFT_CARD` with `initial_value=commission_amount`.
  `engines/affiliate/commission_payer.py`. Opt-in via
  `data.apply_commissions = True`.

The pattern stabilised across the five wireups:

- Default OFF — `data.apply_X = True` opts in. Existing
  callers keep their pure-recommendation behavior.
- Output gains a results field (`minted_codes` / `apply_results`
  / `payout_results`) — empty list when not opted in.
- Each writer documents 5+ skip modes (router unavailable,
  validation gate, no variants in input, partner not in input,
  adapter rejection, adapter raise) so the engine output
  explains what was written and what was skipped, not just
  a top-level success/failure.
- Per-engine helpers stay thin (~150-250 lines); shared logic
  (mint helpers, token derivation) lives in
  `engines/_recovery_codes.py`.

Phase 7 (more engine writebacks) — **active, 26 wired
engines**:
Same pattern as Phase 6 applied to additional recommender
engines. Verified each turn by
``engines._writeback_audit.audit_writeback_coverage`` --
the runtime check that scans engines/ for ``*_applier.py``,
``*_minter.py``, ``*_payer.py`` writer files + ``data.get
("apply_*")`` opt-in flags in flow.py.

Currently wired (26 / 135 = 19%):
  affiliate, browse_recovery, bundle, cart_recovery,
  catalog, churn_prediction, content_generation,
  customer_segmentation, discount_strategy, dynamic_pricing,
  email_marketing, fraud_detection, inventory,
  landing_page, legal_document, loyalty, pricing,
  product_lifecycle, product_optimization,
  product_research, returns_management,
  search_optimization, shipping_optimization, store_design,
  tag_management, wholesale_b2b

Notable wireups beyond Phase 6's original 5:
- ``product_lifecycle`` archives declining products via
  ``SHOPIFY_UPDATE_PRODUCT`` (status=ARCHIVED). First
  destructive writeback; needed stricter safety gates
  (stage + velocity + confidence floor).
- ``store_design`` integrates ``design_applier`` as opt-in
  Phase 7 via ``data.apply_design + data.theme_id`` so
  cycle/fleet-plan integration is possible (5b029d82).
- ``churn_prediction`` mints retention codes for high-risk
  customers when retention_action == win_back_offer. AGI
  guardrail integrated; cost-tier -> percentage mapping
  (10/15/20%). Added to GUARDRAIL_ENGINES roster
  (c58ec58d + a6c3be2b).
- ``product_research`` tags research-validated SKUs with
  ``research:winner`` + ``research:<verdict>`` via
  ``SHOPIFY_UPDATE_PRODUCT``. Pure tag-write -- no
  guardrail integration since financial impact is zero
  (afc31024).

The next-candidate question: pick advisory engines with
clear single-mutation outputs. Don't wire engines whose
recommendations need operator review (e.g. personal_outreach
in churn_prediction's retention_action set was skipped --
not a discount, not auto-mintable).

Phase 8 (autonomous-loop integration) — **complete**:
Closes the gap that Phase 6 / 7 exposed. Engine writebacks
were calling `router.execute(...)` directly, bypassing the
autonomous loop's feedback systems (`MemoryIntelligence`,
`DataArchitecture`, `LearningLoop`). System could mint a 10%
loyalty code but never learned whether that code drove
redemptions.

The bridge lives at `engines/_writeback_recorder.py` —
`record_writeback(engine, action_type, capability, params,
success, error, metrics)`. Each writer calls it AFTER its
`router.execute` so the action+result fans out to:

- `MemoryIntelligence.create_from_decision` — categorized
  decision memory with success/failure tags + auto-pruning.
- `DataArchitecture.record_action` + `attach_result` — fills
  the action→result domain (96% target attach rate).
- `MemoryIntelligence.record_failure` — auto-fires when score
  ≤ 2.0; the failure-intelligence pipeline auto-generates
  avoidance rules after 3+ similar failures.
- `LearningLoop.learn` — pattern detection feed.

Score computation mirrors `SmartExecutor._score_outcome` for
consistency: base 3.0, +1.0 success, -1.5 error, ±0.5 revenue
impact, +0.3 profitable, clamped [1.0, 5.0].

Wired into all 6 existing writers (loyalty, discount_strategy,
dynamic_pricing, tag_management, affiliate, product_lifecycle).
Graceful degradation: if any of the three systems is
unavailable / raises, the recorder no-ops silently. The
writeback already happened on Shopify; recording must not
propagate failures.

**Pattern for new Phase 7 / 8 wireups.** Call
`record_writeback(...)` immediately after each successful or
failed `router.execute`. The recorder takes care of routing
to the right learning system.

Phase 9 (AGI orchestration stack) — **shipped, modules + wiring**:

Three orchestration layers that turn the autonomous loop from
"execute capability X" into "decide what to do today across N
stores cost-effectively". The layers are independent — engines
can adopt one without the others — but they're designed to
compose at decision time.

### Layer 1 — Per-store world model (`core/world_model/`)

Single dict snapshot that captures everything an AI orchestrator
needs to know about a store at decision time. Read-only.

```python
from core.world_model import WorldModel

snap = WorldModel().snapshot("store-id", skip_live=False)
# → {store_id, fetched_at, store, stats, sync, connection,
#    config (drift), design, approvals, decisions}
```

Each section carries a `checked: bool` so callers can distinguish
"checked and empty" from "skipped". Live probes (connection +
config drift) opt out via `skip_live=True`. Approvals + decisions
are GLOBAL (no per-store column on `pending_actions` yet — see
v1 limitation note in the module docstring).

CLI: `shopai world-model show <store_id> [--json] [--skip-live]`.

### Layer 2 — Decision-time retrieval (`core/decision_retrieval/`)

Top-k retrieval of past similar decisions, joined with their
measured outcomes.

```python
from core.decision_retrieval import DecisionRetrieval

similar = DecisionRetrieval().retrieve(
    engine="loyalty",
    action_type="mint_loyalty_code",
    capability="SHOPIFY_CREATE_DISCOUNT",
    params={"discount_pct": 10},
    k=5,
)
# → [{action_id, engine, action_type, capability, params, status,
#     decided_at, outcomes, outcome_summary, relevance,
#     score_components}, ...]
```

Deterministic scoring (no embeddings, no network):

- action_type match: 40%
- capability match: 20%
- params overlap (key Jaccard + value equality): 25%
- recency decay (7-day half-life): 15%

The retrieval contract is stable; a future revision can swap to
embeddings without breaking callers.

CLI: `shopai memory-recall --engine X [--action-type Y]
[--capability Z] [--params-json '{...}'] [-k N]`.

### Layer 3 — Cost-aware model router (`core/model_router/`)

Policy layer that classifies each AI call as local (cheap, fast)
or cloud (deep reasoning) based on prompt complexity. Doesn't
execute models — caller still runs the chosen model and
`record_usage` afterwards. Tracks daily cloud-token budget; cap
exhaustion downgrades cloud → local with `downgraded=True` flag.

```python
from core.model_router import ModelRouter, ModelHint

decision = ModelRouter().classify(prompt, hint=ModelHint.AUTO)
# → RoutingDecision(tier, reason, estimated_tokens,
#                   complexity_score, downgraded, components)
```

CLI: `shopai model-router {classify|budget}`.

### Engine wiring: two patterns

**Auto-capture (zero-touch).** `engines/_writeback_recorder.py`
auto-captures the decision-retrieval context whenever a writer
calls `record_writeback` without explicit `metrics=`. The
captured signal (similar_count, recent_positive, recent_negative,
avg_relevance) flows into MemoryIntel + DataArch + LearningLoop
automatically. **No per-writer code change needed** — every
existing writer benefits.

**Explicit capture (opt-in for decision-time use).** Engines that
want to USE the captured signal at decision time (not just
observe it) call `engines._agi_context.capture_decision_context`
directly. The returned dict carries the snapshot + similar list,
and the engine passes `metrics=ctx["metrics"]` to
`record_writeback` to preempt the auto-capture. See
`engines/loyalty/discount_minter.py` for the reference
implementation.

**Pattern J guard.** Both `capture_decision_context` and
`record_writeback`'s auto-capture short-circuit under pytest
(same `PYTEST_CURRENT_TEST` guard as the writeback recorder).
Test fixtures don't pollute the AGI databases.

### Patterns introduced in Phase 9

- **Pattern K-prime: ASCII conflict markers in CLAUDE.md** —
  unrelated to GraphQL, but worth noting: when stacking parallel
  PRs that all modify `cli.py`, rebasing each on the new main
  after the previous merges is required. GitHub's "merge in web
  editor" loses semantic context; rebase locally, run the
  branch's tests, then push --force-with-lease.
- **Pattern J (test-environment guard) extends to AGI helpers**
  — `engines._agi_context.capture_decision_context` and the
  `_writeback_recorder._auto_capture_context` wrapper both
  short-circuit under pytest. Without these guards, every unit
  test that exercises an applier would write a synthetic row to
  the world-model / decision-retrieval databases.

Phase 10 (empire-AGI: cross-store + v2 guardrail) — **shipped**:

Phase 9 gave the system a captured AGI signal per writer. Phase
10 makes that signal **per-store** and **actionable** — the
empire-AGI realization where one store's wins suggest moves
for another, and engines refuse on unambiguous-negative history.

### Per-store data + retrieval

- **`pending_actions.store_id`** column (PR #239) — idempotent
  ALTER TABLE migration; rows without store_id (pre-migration)
  resolve to NULL and are excluded from filtered reads.
- **`ApprovalQueue.enqueue(..., store_id=...)`** and
  per-store filters on `list_pending`, `list_by_status`.
- **`DecisionRetrieval.retrieve(..., store_id=...)`** — fleet-
  wide when omitted (cross-store transfer use case),
  per-store when supplied.
- **`WorldModel._section_approvals/_section_decisions`** —
  per-store scope when `snapshot(store_id=...)` is called
  (PR #241). `scope="per_store"` in the section dict.

### Active-store thread-local context

`core/context/active_store.py`:

```python
from core.context import active_store, get_active_store_id

with active_store(sid):
    engine.run(input_data)
    # every enqueue inside auto-tags store_id=sid
```

Per-thread (concurrent loop iterations are safe). Restored on
exit. `ApprovalQueue.enqueue` reads it as a fallback when
caller doesn't pass `store_id`. **Single integration point**:
the autonomous controller's `run_cycle` wraps its body in
`active_store(sid)` (PR #244). ~50 engines stay store-agnostic.

### Cross-store transfer recommender

`shopai transfer suggest --from <A> --to <B>` (PR #242):

- Pulls EXECUTED actions tagged with store-A
- Aggregates by (engine, action_type, capability) with outcome
  rollups (positive_count, total_revenue, sample_params)
- Excludes anything already tried on store-B (any status)
- Ranks: positive_outcomes desc → revenue desc → success_count
- Returns top-k transferable actions

End-to-end verified via `scripts/transfer_demo_seed.py`
(PR #246).

### v2 guardrail (engines act on the signal)

`engines._agi_context` exposes (PR #247):

- `guardrail_enabled(engine_name)` — env-var opt-in:
  `SHOPAI_<ENGINE>_AGI_GUARDRAIL=1`. Per-engine, default OFF.
- `should_block_unambiguous_negative(metrics)` — strict block:
  similar_count ≥ 3 AND recent_negative AND NOT recent_positive.
- `explain_guardrail_block(metrics)` — audit reason.

Wired across all 6 Phase 6/7 minters (PR #245 loyalty
reference + PR #250 the other 5). The pattern:

```python
agi_context = capture_decision_context(engine="...", ...)
agi_metrics = agi_context.get("metrics") or {}
if guardrail_enabled("<engine>") and \
        should_block_unambiguous_negative(agi_metrics):
    record_writeback(
        ..., success=False,
        error=explain_guardrail_block(agi_metrics),
        metrics=agi_metrics,
    )
    return None
```

Conservative on purpose: false negatives (allow-when-should-
block) are cheaper than false positives (refuse a legitimate
mint = lost revenue).

### Empire-AGI operator surface

| Command | Scope | PR |
|---|---|---|
| `shopai world-model show <store>` | Per-store snapshot (incl. transfers section) | #230, #241, #266 |
| `shopai world-model fleet` | All stores, side by side | #251 |
| `shopai store fleet` | Fleet stats summary | #233 |
| `shopai daily-brief` | Cron-able activity rollup (incl. transfer activity) | #238, #258 |
| `shopai transfer sources --to B` | Rank fleet stores by transferable surface area | #260 |
| `shopai transfer suggest --from A --to B` | Cross-store recommender | #242 |
| `shopai transfer apply --dry-run` | Preview a transfer before enqueueing | #262 |
| `shopai transfer apply` | Enqueue a transfer as PENDING on target | #254 |
| `shopai transfer history` | Audit trail of past transfers | #265 |
| `shopai transfer outcomes` | Did transferred actions pay off on the target? | #257 |
| `shopai engine summary <engine>` | Single-engine drilldown | #234 |
| `shopai engine guardrail` | v2 guardrail state + recent blocks | #249, #253 |
| `shopai engine fleet <engine>` | One engine × all stores (where's it winning?) | #259 |
| `shopai engine compare <a> <b>` | Head-to-head fleet comparison | #263 |
| `shopai engine ranking` | Fleet-wide engine leaderboard by outcome score | #264 |
| `shopai engine alerts` | Flag engines whose recent score has dropped | #276 |
| `shopai approvals show <id> --with-context` | Action + similar past | #237 |
| `shopai approvals outcome <id> --polarity ...` | Manually record an outcome | #277 |
| `shopai memory-recall --engine X [--store S] [--since-hours N]` | RAG retrieval inspector | #231, #261, #278 |
| `shopai model-router classify` | Local-vs-cloud tier inspector | #232 |

Plus standalone scripts (under `scripts/`, opted into explicitly because they write directly to the queue):

| Script | Scope | PR |
|---|---|---|
| `python scripts/transfer_demo_seed.py --from A --to B [--realism]` | Synthetic per-store actions for demo | #246, #273 |
| `python scripts/batch_record_outcomes.py path/to/outcomes.csv` | Bulk outcome backfill from CSV | #279 |

The full cross-store empire-AGI workflow chains these commands:

```bash
shopai transfer sources --to B           # 1. pick best source A
shopai transfer suggest --from A --to B  # 2. see candidates
shopai transfer apply ... --dry-run      # 3. preview
shopai transfer apply ...                # 4. enqueue PENDING
shopai approvals show <id>               # 5. operator review
# (approval → execution → outcome capture via webhooks)
# Optional: if webhooks missed an event, record it manually:
shopai approvals outcome <id> --polarity positive [--revenue N]
# Or in bulk: python scripts/batch_record_outcomes.py file.csv
shopai transfer history                  # 6. audit
shopai transfer outcomes                 # 7. measure payoff
# Watch for engine degradation across the loop:
shopai engine alerts                     # 8. degradation detector
```

### Shared utilities

Three consolidation modules back the operator surface. New code
that touches these patterns should import from them, not
re-implement inline:

- ``core.transfer_narrative`` (PR #268) — transfer-apply narrative
  format + parsers + ``SQL_LIKE_CLAUSE``.
- ``core.approval.outcome_aggregator`` (PR #271) — polarity +
  revenue rollup over ``get_outcomes()`` results, returns
  ``OutcomeStats`` dataclass.
- ``engines._agi_context.GUARDRAIL_ENGINES`` + ``guardrail_state()``
  (PR #272) — canonical roster of v2-wired engines.
- ``core.approval.outcome_trends`` (PR #282) —
  ``compute_engine_alerts(queue, ...)`` for engine-degradation
  detection. CLI ``engine alerts`` + ``daily-brief`` are the
  consumers; world-model can adopt without re-implementing.
- ``core.approval.alert_history`` (PR #292) — persistent log of
  ``EngineAlert`` firings + ``consecutive_runs_per_engine`` for
  multi-day streak detection. JSON-backed at
  ``data/alert_history.json``.
- ``core.approval.alert_quarantine`` (PR #294) — env-gated bridge
  that auto-pauses engines on N consecutive days of alerts.
  Writes to ``QuarantineState.alert_paused``; the standard
  enqueue path's ``evaluate()`` short-circuits on it.

### Auto-quarantine chain (PRs #292 – #298)

The full degradation-response loop. Each layer reuses the
existing infrastructure rather than building its own:

```text
EngineAlert (compute_engine_alerts)             ← detect
       │
       ▼
alert_history.record_alerts()                   ← record
       │  data/alert_history.json
       ▼
alert_history.consecutive_runs_per_engine()     ← streak count
       │
       ▼
alert_quarantine.maybe_auto_quarantine_from_alerts()  ← bridge
       │  (env-gated; default OFF)
       ▼
quarantine.add_alert_pause(engine)              ← persist
       │  quarantine_state.alert_paused
       ▼
ApprovalQueue.enqueue → maybe_quarantine →
  quarantine.evaluate() → REJECTED              ← enforce
       │
       ▼
shopai approvals quarantine --release-alert     ← operator unlocks
```

Env-var contract (all opt-in):

- ``SHOPAI_AUTO_QUARANTINE_FROM_ALERTS=1`` — enable the bridge.
  Default OFF; daily-brief still SHOWS the consecutive-day
  count but doesn't act.
- ``SHOPAI_AUTO_QUARANTINE_DAYS=3`` — streak threshold.
- ``SHOPAI_AUTO_QUARANTINE_WINDOW_DAYS=7`` — detection window.

Operator surface:

- ``daily-brief`` records each firing + surfaces both
  ``consecutive_days`` per alert AND a separate
  ``kind="auto_alert_quarantined"`` entry when the bridge
  triggers (PR #300).
- ``shopai approvals quarantine`` (text + JSON) shows the
  ``alert_paused`` list + bridge config block (PR #295);
  ``--release-alert ENGINE`` clears one entry;
  ``--apply-bridge`` manually triggers the bridge between
  daily-brief runs (PR #305).
- ``shopai approvals alert-history`` (PR #297) inspects the
  persistent firing log; ``--clear`` is the nuclear escape
  hatch; ``--prune-older-than-days N`` is the precision
  scalpel for routine ops hygiene (PR #304).
- ``shopai approvals alert-release-candidates`` (PR #302) and
  ``shopai approvals alert-pause-candidates`` (PR #303) are
  the alert-based analogues of ``quarantine-release-candidates``.
  The first finds alert-paused engines whose alerts have gone
  quiet (safe to release); the second is a dry-run preview
  of what the bridge would pause if it ran now (works even
  when the env-var gate is off).
- ``shopai approvals doctor`` (PR #301) includes an
  ``alert_history`` section that warns when any engine has
  fired on 3+ distinct days -- the threshold the bridge
  would auto-pause at.
- ``shopai world-model show`` includes a fleet-wide
  ``quarantine`` section showing all three lists + bridge
  config (PR #296).

Test architecture:

- Each layer's unit tests mock the next.
- ``tests/test_alert_quarantine_e2e.py`` (PR #298) is the
  trust anchor: REAL SQLite + REAL state files + REAL
  evaluator. If any layer regresses, this test breaks first.

Decision-log forensics: actions rejected via the bridge carry
``decided_by="auto_quarantine"`` and reason
``"auto_quarantine_from_alerts"`` (distinct from the outcome-
based path's ``"auto_quarantine: negative_ratio=..."`` so
post-hoc audits can tell them apart).

Pattern J extends to alert_history + alert_quarantine: both
have their own ``_is_test_environment()`` guard that returns 0
under pytest. Three concurrent guards must be lifted to
exercise the full chain in tests (the E2E test does this).

### Per-store empire-AGI extension (PRs #319–#326)

The fleet-wide auto-quarantine system above evolved into a
per-store model so that an engine misbehaving on ONE store
doesn't false-trigger fleet-wide rejections (and conversely,
a store-specific issue can be quarantined without affecting
other stores).

**Data layer (#319):**

- ``AlertEvent.store_id: str | None`` — alert firings now
  carry the store scope. ``None`` means fleet-wide (legacy /
  cross-store-aggregate events).
- ``record_alerts(alerts, *, store_id=...)`` auto-resolves
  from the ``active_store`` thread-local when not supplied.
- ``recent_history(..., store_id=...)`` strict-filters.
- ``consecutive_runs_per_engine(..., store_id=...)`` filters
  to that store; without filter, aggregates across stores
  (backward compat).
- NEW ``consecutive_runs_per_engine_store()`` returns
  ``{(engine, store_id): bucket_count}`` for empire-AGI
  pivots.

**State layer (#320):**

- ``QuarantineState.alert_paused: frozenset[tuple[str, str |
  None]]`` — entries are ``(engine, store_id)``. ``store_id =
  None`` = fleet-wide pause.
- ``is_alert_paused(engine, store_id=...)`` matches either
  the fleet-wide tuple OR the exact store tuple.
- ``add_alert_pause(engine, store_id=None)`` /
  ``clear_alert_pause(engine, store_id=None)`` /
  ``clear_all_alert_pauses_for_engine(engine)``.
- JSON format: ``[[engine, store_id], ...]`` pairs. Legacy
  string entries auto-migrate to ``(engine, None)``.

**Evaluator (#320 + #325):**

- ``evaluate(engine, queue, store_id=...)`` — when ``store_id``
  is supplied: matches alert-pauses ``(engine, None) OR
  (engine, store_id)``; ALSO consults per-store
  ``engine_outcome_stats(engine, store_id=...)`` if fleet-
  wide ratio is healthy. Per-store stats can trigger a
  per-store quarantine while fleet is OK (empire-AGI's
  whole point).
- Decision reason carries scope qualifier:
  ``auto_quarantine_from_alerts (fleet)`` /
  ``... (store=store_a)`` / ``auto_quarantine:
  negative_ratio=... (fleet)`` / ``... (store=store_a)``.
- ``ApprovalQueue.enqueue`` forwards the action's
  ``store_id`` to the evaluator.

**Bridge (#321):**

- ``SHOPAI_AUTO_QUARANTINE_PER_STORE=1`` — env-gated opt-in
  for per-store auto-pause. Default OFF.
- When enabled, ``engines_to_pause`` counts ONLY truly
  fleet-scoped events (``store_id=None``) — per-store
  streaks are handled separately by ``pairs_to_pause``. This
  eliminates the false-positive of "single-store
  degradation triggers a fleet pause".
- ``maybe_auto_quarantine_from_alerts_full()`` returns
  ``{fleet_paused, store_paused}``.

**Operator surface (#322, #323, #326):**

- ``shopai world-model show <store>`` — quarantine section
  now scope=per_store, with ``for_this_store`` sub-block
  showing engines blocked for THAT store (fleet pauses +
  per-store pauses combined).
- ``shopai approvals alert-history --store STORE_ID
  [--include-fleet]`` — store-scoped firing log.
- ``shopai approvals quarantine --release-alert ENGINE
  --release-alert-store STORE_ID`` — selective release.
- ``shopai approvals quarantine --release-alert ENGINE
  --release-alert-all`` — drop every pause for an engine.
- ``shopai approvals quarantine-simulate ENGINE [--store
  STORE_ID]`` — dry-run "would this be paused?".

**Backward-compat:**

- Existing ``alert_history.json`` (no store_id field) loads
  with ``store_id=None``.
- Existing ``quarantine_state.json`` (string entries) loads
  as ``(engine, None)`` fleet-wide pauses.
- Callers passing no ``store_id`` keep working unchanged.
- Per-store env-var is opt-in; the default fleet behaviour
  is unchanged.

### Schema migration patterns

- **Idempotent ALTER TABLE** (PR #239): when adding a column,
  do the CREATE TABLE in `executescript` but the ALTER inside a
  separate transaction guarded by `PRAGMA table_info` so the
  migration is no-op on a fresh DB and a one-time add on an old
  one.
- **Backward-compat row reads** (PR #239): when the schema
  gains a column, wrap the row-to-object mapper's column read in
  `try: row["new_col"] except (IndexError, KeyError):` so older
  rows (or test fakes) without the column still load.

### v1 contracts that stay (observational still ships)

Phase 9's auto-capture in `record_writeback` is unchanged --
every Phase 6/7 writer gets the AGI signal flowing into
MemoryIntelligence + DataArchitecture + LearningLoop regardless
of v2 guardrail status. v2 is purely additive: when enabled,
engines also refuse on unambiguous-negative; when disabled, v1
behaviour preserved.

## Reading order for a fresh session

1. This file.
2. `ARCHITECTURE.md` (top-level layered design).
3. `core/adapters/shopify/_base.py` (the parent every adapter extends).
4. `core/adapters/shopify/metafield.py` (the cleanest existing
   example to copy from).
5. `tests/test_shopify_adapters.py` (test conventions).
6. The enum at `core/adapters/base.py:102-115`.
7. Whatever specific Shopify doc page covers the GraphQL operation
   I'm about to wrap.

## Ant-colony architecture (Wave 1-5, 2026-05-25)

Tier 1-2b substrate built on top of the existing engine +
adapter layers. The user's framing: "queen rules but doesn't
micromanage workers." Single-step delegation only.

```text
Owner (CLI)
   ↓
Tier 1  Orchestrator     engines/_orchestrator.py
   ↓
Tier 2a Store Supervisor engines/_store_supervisor.py
   ↓
Tier 2b Cluster Captain  engines/_cluster_captain.py
   ↓
Tier 3  Engines (135)    engines/<name>/flow.py
   ↓
Tier 4  Adapters (130+)  core/adapters/shopify/<name>.py
```

Substrate modules:

- `engines/_clusters.py` -- 10 concern clusters, 100 engines
- `engines/_writeback_risk.py` -- additive/modification/destructive
- `engines/_captain_signals.py` -- HeuristicSignalCollector
- `engines/_cluster_memory.py` -- per-cluster outcome rollup
- `engines/_outcome_window.py` -- time-windowed outcomes
- `engines/_cluster_bus.py` -- horizontal event bus
- `engines/_ai_strategies.py` -- AI plug-ins (opt-in via env-var)
- `engines/_cluster_audit.py` -- 9th institutional gate

CLI surfaces (operator end-to-end):

```text
shopai cycle verify              -- preflight check
shopai cycle run [--yes]         -- empire entry point
shopai cycle schedule            -- cron / systemd config
shopai orchestrator plan         -- Tier 1 view
shopai store supervise <id>      -- Tier 2a view
shopai cluster list/show/plan    -- Tier 2b ops
shopai cluster fire <name> --yes -- live captain dispatch
shopai cluster bus               -- horizontal event inspector
shopai cluster bus --emit X:Y    -- manual event injection
shopai cluster-outcomes          -- time-windowed rollup
```

### Risk taxonomy (enforced at multiple layers)

51 writers classified by `engines/_writeback_risk.py`:

- **additive** (45): tags, mint codes, create entities. Auto-fire.
- **modification** (6): pricing, dynamic_pricing, product_lifecycle,
  product_optimization, content_generation, store_setup policy.
  Invoked with `require_approval=True`; engine internally enqueues
  to ApprovalQueue.
- **destructive** (0): operator-only escalation. Never auto-fired.

CI invariants:

- additive >= 5x modification (architectural floor)
- destructive <= 3 (hard ceiling)
- every wired engine has a known risk class
- every domain engine is mapped to a cluster

### Strategy plug-ins (substrate-first proof)

All decision logic is pluggable via Protocol-based strategies:

- `OrchestratorStrategy`: Deterministic, AI
- `CaptainStrategy`: Deterministic, SignalDriven, MemoryAware, AI
- `SignalCollectorStrategy`: Heuristic (real Phase 8 data later)
- `ClusterMemoryStrategy`: QueueOutcomeRollup (DataArch later)

AI strategies (opt-in via `SHOPAI_AI_STRATEGY=1`):

- Default deterministic baseline runs FIRST
- LLM asked to REVIEW / REFINE (not author)
- Validated against wired_members + risk taxonomy
- Falls back to deterministic if LLM unavailable / invalid

### Safety env-var gates (live-mode blast radius)

- `SHOPAI_CYCLE_RUN_CONFIRM=1` for `cycle run --yes`
- `SHOPAI_CLUSTER_FIRE_CONFIRM=1` for `cluster fire --yes`
- `SHOPAI_TRY_WIREUP_ALL_CONFIRM=1` for `engine try-wireup --all --yes`
- `SHOPAI_CLUSTER_BUS_CLEAR_CONFIRM=1` for `cluster bus --clear`

### Horizontal collaboration

`engines/_cluster_bus.py` provides:

- `emit_event(emitter, topic, payload, store_id)` -- captain
  auto-emits on non-zero signals
- `subscribe_events(...)` -- filter by topic / emitter / store / window
- `cross_cluster_signals(store_id, window_hours)` -- convert
  recent events into next-cycle signals dict

Topic -> consumer-cluster signal:

```text
high_roas_product   -> merchandising:high_roas_product_count
churn_risk_detected -> retention:at_risk_count
thin_margin_flagged -> pricing:thin_margin_count
stockout_warning    -> fulfillment:stockout_imminent_count
negative_review     -> quality:negative_review_count
undercut_detected   -> pricing:undercut_count
```

Bus is observational + advisory. Captain CAN consume events
via mapped signals, but doesn't HAVE to. Vertical authority
unchanged.

## Attribution AGI substrate (Waves 7-28, 2026-05-25 to 2026-05-26)

Closes the autonomous loop's feedback cycle: Shopify orders
-> per-cluster + per-engine revenue -> decision-time signal
-> persistence -> regression detection -> bus feedback ->
auto-quarantine -> release detection. 22 commits on top of
the ant-colony foundation (a5559a0c -> c1cc42ae).

### Substrate modules

- ``engines/_revenue_attribution.py`` -- Wave 7+9. Joins
  Shopify orders to clusters/engines via the tag catalog.
  ``SharedCreditStrategy`` splits each order's revenue equally
  across matched clusters/engines. ``AttributionReport``
  carries per_cluster + per_engine. ``EngineAttribution``
  + ``ClusterAttribution`` dataclasses with ``confidence``
  buckets (none / low / medium / high based on
  attributed_orders).

- ``engines/_revenue_aware_orchestrator.py`` -- Wave 8.
  ``RevenueAwareOrchestratorStrategy`` wraps any base strategy
  and re-ranks cluster_focus by attributed revenue desc.
  Threshold-gated ($10 default) to filter noise. Env-gated
  via ``SHOPAI_REVENUE_AWARE_ORCHESTRATOR=1``.

- ``engines/_revenue_aware_captain.py`` -- Wave 10. Same
  pattern but for member selection within a cluster.
  Optional drop-zero pruning when other members are earning
  (with cold-start safety net). Env-gated via
  ``SHOPAI_REVENUE_AWARE_CAPTAIN=1``.

- ``engines/_attribution_snapshot.py`` -- Wave 11+14. JSON
  persistence at ``data/attribution_snapshots.json`` (bounded
  to 200 entries). Per-cycle + per-store. Pattern J guard for
  tests. ``record_snapshot``, ``recent_snapshots``,
  ``last_snapshot``, ``attribution_trend``,
  ``stores_with_snapshots``, ``fleet_attribution_rollup``.

- ``engines/_attribution_delta.py`` -- Wave 12+13. Diffs two
  snapshots. ``ClusterDelta`` + ``EngineDelta`` with direction
  property (up/down/new/dropped/flat). ``RegressionAlert``
  fires when revenue drops >= 25% AND both sides had >= 3
  attributed_orders. ``propagate_alerts_to_bus`` emits one
  ``revenue_regression`` event per alert -- next cycle's
  captain consumes via the bus's standard
  ``cross_cluster_signals`` pipeline.

- ``engines/_revenue_quarantine.py`` -- Wave 21+27. When an
  engine appears in regression alerts across N consecutive
  cycles, auto-add to ``quarantine.alert_paused`` (env-gated
  ``SHOPAI_AUTO_QUARANTINE_FROM_REVENUE=1``). Symmetric
  ``find_revenue_release_candidates()`` lists paused engines
  that have been quiet long enough to safely release.

### CLI surfaces added

- ``shopai cycle attribution [--by cluster|engine]
  [--window-hours N] [--store X]`` -- current snapshot view.
- ``shopai cycle attribution-history [--store X] [--limit N]``
  -- trend across recent cycles.
- ``shopai cycle attribution-delta [--store X]
  [--regression-pct N] [--min-orders N]`` -- cycle-over-
  cycle diff with regression alerts.
- ``shopai cycle revenue-fleet`` -- cross-store empire
  rollup, sorted by attributed revenue desc.
- ``shopai cluster list --with-attribution`` -- adds ATTR$
  + revenue_verdict columns to the cluster overview.
- ``shopai cluster show <name>`` -- now includes
  ``Revenue (7d)`` section with top-5 earning engines.
- ``shopai engine pulse <name>`` -- shows per-engine
  attribution + cluster.
- ``shopai approvals quarantine --revenue-streaks`` --
  per-engine consecutive-cycle regression streaks.
- ``shopai approvals quarantine --apply-revenue-bridge`` --
  manually fire the auto-quarantine bridge.
- ``shopai approvals quarantine --revenue-release-candidates``
  -- engines safe to unpause.
- ``shopai cycle status`` -- new ``Cycle-over-cycle delta``
  block surfaces regressions inline.
- ``shopai daily-brief`` -- new ``Revenue attribution (AGI,
  7d)`` block surfaces the AGI-loop earnings rollup.
- ``shopai world-model show <store>`` -- new
  ``Revenue attribution:`` section per store.
- ``shopai world-model fleet`` -- new ``ATTR$`` column.
- ``shopai ai-strategy status`` -- surfaces revenue-aware
  orchestrator + captain env state.

### Wiring into ``cycle run --yes``

Every live cycle now:

  1. Fetches recent orders + builds attribution report.
  2. Records a fleet-wide snapshot + one per active store.
  3. Computes the latest delta (fleet + per-store).
  4. Propagates regression alerts onto the cluster bus (fleet
     + per-store).
  5. Invokes ``maybe_auto_quarantine_from_revenue`` (fleet +
     per-store).

All steps best-effort -- failure logs at debug but does not
break the cycle. Pattern J guards mean unit tests don't
pollute snapshots / state.

### AI strategy integration

- ``AICaptainStrategy`` prompt context now includes per-engine
  attribution scoped to wired_members (Wave 17).
- ``AIOrchestratorStrategy`` prompt context includes per-store
  top_clusters with attribution (Wave 24).

Both fall back to deterministic behaviour when attribution
data is unavailable -- LLM still works, just less informed.

### New ClusterHealth signal (Wave 18)

``ClusterHealth.revenue_verdict`` returns one of:
  - ``earning`` -- attributed_revenue >= $10
  - ``flat`` -- attributed but below threshold
  - ``declining`` -- recent delta carries an alert against this
    cluster (set via ``_force_declining`` flag from
    ``enrich_with_attribution``)
  - ``unknown`` -- no attribution_orders yet

``MemoryAwareCaptainStrategy`` escalates verdict by one tier
when ``revenue_verdict == "declining"`` (parallel to the
``recent_regression_count`` bus signal path; never
double-stacks).

### Patterns introduced

- **Pattern Z' (revenue substrate)**: every layer that
  consumes attribution data falls back to deterministic
  behaviour when snapshots/deltas are unavailable. Cold-start
  empires don't crash; they just operate without the
  revenue-driven heuristics until data accumulates.

- **Pattern J extends to attribution snapshots**:
  ``engines/_attribution_snapshot.record_snapshot`` and
  ``engines/_revenue_quarantine.maybe_auto_quarantine_from_revenue``
  short-circuit under pytest. Tests exercising the write
  paths install ``_is_test_environment`` patches to lift the
  guard.

### Cycle-history determinism fix (Wave 19)

``engines/_cycle_history.record_cycle_run`` adds a
process-monotonic ``_next_seq()`` to ``run_id`` after the ns
timestamp. On Windows ``time.time_ns()`` granularity is ~15ms
so back-to-back records share timestamps; the sequence breaks
the tie deterministically. Test ``test_last_run`` was flaky
before this fix.

### Tests

355 tests across the attribution + ant-colony + AI + world-
model + daily-brief suites. All deterministic on Windows
(verified by running the full suite twice back-to-back).

## Operational readiness substrate (Waves 47-57, 2026-05-26+)

After the attribution stack (Wave 7-36) and end-to-end
validation (Wave 37-46), Wave 47-57 ships the layer ShopAI
needs to actually go LIVE with real-money operation. 11 more
substrate pieces:

### Wave 47 -- per-store spend cap + auto-pause bridge
- ``engines/_spend_cap.py``: SpendRollup aggregates
  ``metrics.cost`` / ``metrics.ad_spend`` /
  ``metrics.discount_value`` from approval-queue outcomes.
  Per-store + fleet. Daily + weekly caps via env
  (``SHOPAI_SPEND_CAP_DAILY_USD`` /
  ``SHOPAI_SPEND_CAP_WEEKLY_USD``).
- Auto-pause bridge (``SHOPAI_AUTO_PAUSE_ON_OVERSPEND=1``)
  adds 13 spend-class engines to
  ``quarantine.alert_paused`` when a cap is breached. Pattern
  J guard preserved.
- ``cycle run --yes`` fires the bridge post-cycle (alongside
  the revenue-quarantine bridge from Wave 21+22).
- CLI: ``shopai approvals quarantine --spend-status``.

### Wave 48 -- ``shopai empire`` unified dashboard
- One-screen aggregator: last cycle, revenue (7d + delta),
  spend vs cap, approvals, cluster health, engine alerts.
- Marker badges + drill-down hints. Operator goes from
  ``daily-brief`` + ``cycle status`` + ``cycle revenue-fleet``
  + ``cycle attribution-delta`` + ``approvals quarantine
  --spend-status`` + ``engine pulse --fleet`` (6 commands)
  to ``shopai empire`` (1 command).

### Wave 49 -- AI approval pre-vet (LLM consultant)
- ``engines/_approval_prevet.py``: deterministic heuristic
  (always) + LLM consultation (opt-in via
  ``SHOPAI_AI_PREVET=1``). Same consultant pattern as Wave
  17+34+35 (deterministic baseline -> LLM may REFINE ->
  fallback on invalid response).
- Heuristic rules: destructive=hold; additive + >=80% pos
  history (n>=3) -> approve; <=30% pos history -> reject.
- CLI: ``shopai approvals prevet [--engine X]``. Pairs with
  the existing ``approve-all --min-confidence``.

### Wave 50 -- per-engine ROAS report
- ``engines/_roas_report.py``: substrate join. Spend from
  Wave 47 + per-engine attribution from Wave 9 ->
  ``attributed_revenue / total_spend`` per engine. Verdict
  bands: strong (>=2x), break_even (>=1x), negative,
  no_data (spend exists but attribution lags).
- CLI: ``shopai roas [--window-hours N] [--store X]``.
- Honest scope note: full ad-spend write-optimizer needs
  Meta/Google Ads adapter capability-wireup. Wave 50 ships
  the READ side; Wave 51 fixes adapter registration.

### Wave 51 -- ads adapter bootstrap (Meta Ads now routable)
- ``core/adapters/ads/bootstrap.py``: was missing. Meta Ads
  adapter had capability dispatch + HTTP plumbing, but no
  bootstrap.py meant SmartRouter never registered it.
- Generalized ``_maybe_bootstrap_secondary_adapters()`` in
  cli.py main() calls ads / email / search / shipping / llm
  bootstraps once at startup.
- Defensive bug fix: ``registry or get_registry()`` falls
  back to singleton when an empty registry is passed
  (empty registry is falsy). Wave 51 fixed it in ads/
  bootstrap.py; Wave 56 propagated to all 17 other
  bootstrap files + router.py.

### Wave 52 -- ``shopai webhook receive`` CLI surface
- ``core/feedback/webhook_bridge.WebhookFeedbackBridge``
  already existed. Wave 52 added the CLI receiver:
  ``shopai webhook receive [--topic X --payload-json JSON]
  [--from-stdin]``. Bridge consumes the event, tags it to
  the engine that triggered it, feeds LearningLoop.

### Wave 53 -- ``shopai notify check`` external fan-out
- ``engines/_notify.py``: scans 4 alert classes (stale_cycle,
  revenue_regression, spend_breach, engine_paused) + POSTs
  to ``SHOPAI_NOTIFY_WEBHOOK_URL``. Per-kind cooldown
  (default 1h). Dry-run mode for testing.

### Wave 54 -- cycle schedule emits notify-check companion
- ``shopai cycle schedule`` now prints a 15-min cron line
  for ``notify check`` alongside the hourly cycle. Operator
  scheduling cycle gets push alerts automatically.

### Wave 55 -- ``shopai go-live`` pre-flight gate
- ``engines/_go_live_check.py``: 8 checks
  (shopify_credentials, wired_engines,
  institutional_audits, cycle_history, spend_cap,
  revenue_quarantine, notify_webhook, ai_strategy).
- Returns ``ready_to_go_live`` verdict when no fails. Warns
  are advisory.
- Operator's single command for "am I ready to flip cron
  on?".

### Wave 56 -- registry-truthy bug fix (defensive cleanup)
- 18 files: 17 bootstraps + router.py. ``registry or
  get_registry()`` -> ``registry if registry is not None
  else get_registry()``. Behaviour-equivalent in production
  (callers pass None); test isolation now works correctly.

### Wave 57 -- webhook HMAC verification (security gate)
- ``core/feedback/webhook_security.py``: HMAC-SHA256 base64
  verify with constant-time compare. Spoofed events get
  rejected at the CLI layer.
- ``shopai webhook receive --hmac-header X --require-hmac``
  + ``SHOPAI_WEBHOOK_SECRET`` env. Production posture.

### Going-live operator flow

After Wave 47-57 the operator's path from "credentials
configured" to "earning" is:

```bash
shopai go-live                          # see the punch list
export SHOPAI_NOTIFY_WEBHOOK_URL=...    # close warns
export SHOPAI_WEBHOOK_SECRET=...
export SHOPAI_SPEND_CAP_DAILY_USD=50
export SHOPAI_AUTO_PAUSE_ON_OVERSPEND=1
shopai cycle schedule                    # install cron + notify-check
                                          # AGI merchant runs
```

## Empire-scale throughput substrate (Waves 60-69, 2026-05-27)

At 20 stores × 12 engines/cycle × 24 cycles/day = 5,760
approvable actions/day. Operator drowns without
prioritization. Wave 60-69 ships the throughput layer that
makes empire scale tractable.

### Wave 60 -- approval priority score
- ``engines/_approval_priority.py``: PriorityScore with 5
  weighted components: risk_class (30%), spend stake (25%),
  inverse ROAS (20%), regression flag (15%), inverse
  confidence (10%). Recommendation bands urgent (>=0.7) /
  normal (0.4-0.7) / auto-ok (<0.4).

### Wave 61 -- approvals pending --sort priority
- ``shopai approvals pending --sort priority`` reorders the
  list by score desc + renders marker badge + top-2
  components inline.

### Wave 62 -- approvals digest
- ``shopai approvals digest [--top N]``: top-N priority
  pending + AI pre-vet (Wave 49) inline. Replaces 5+
  morning commands.

### Wave 63 -- SLA tracking
- ``engines/_approval_sla.py``: SLA bands (on_time / aging
  / breached) configurable via SHOPAI_APPROVAL_SLA_*_HOURS.
- ``shopai approvals sla`` operator view.

### Wave 64 -- per-engine velocity
- ``engines/_approval_velocity.py``: per-engine proposed /
  approved / rejected / latency / rejection rate. Identifies
  bottlenecks (one engine flooding queue) + distrust signals
  (>= 30% rejection rate gets [BAD] marker).
- ``shopai approvals velocity [--window-hours N]``.

### Wave 65 -- batch-review with AI consensus
- ``shopai approvals batch-review [--auto-approve-ok]
  [--yes]``: top N + AI pre-vet, identifies actions where
  priority=auto-ok AND AI rec=approve as auto-approve
  candidates. --yes commits in bulk with
  decided_by=batch_review. Cron-friendly.

### Wave 66 -- consolidation + tests
- 47 new tests across the 3 substrate modules. 139 tests
  green across operational + empire-scale + attribution.

### Wave 67 -- empire summarizer
- ``engines/_empire_summarizer.py``: one-paragraph empire
  summary. Deterministic baseline ALWAYS runs; LLM may
  REFINE when SHOPAI_AI_STRATEGY=1. Same consultant pattern
  as Wave 17/24/34/35/49.
- ``shopai empire --summarize [--json]``.

### Wave 68 -- notify includes summary
- ``SHOPAI_NOTIFY_INCLUDE_SUMMARY=1`` attaches the empire
  summary paragraph to the notify webhook payload. Slack
  message becomes one-shot: alerts + 1-paragraph context.

### Wave 69 -- per-store summary
- ``summarize_empire(store_id=...)`` scopes per-store
  attribution / spend / alerts / cycle history.
- ``shopai empire --summarize --store X``.

### Operator's empire-scale workflow

```bash
# Morning (5-min standup)
shopai empire --summarize             # one paragraph, 5s scan
# If "Issues needing attention" surfaces:
shopai empire                          # full dashboard
shopai approvals digest                # top-10 + AI pre-vet
shopai approvals batch-review --auto-approve-ok --yes
                                      # bulk approve consensus
shopai approvals sla                   # aging/breached?
shopai approvals velocity              # bottleneck engine?

# Drill per-store
shopai empire --summarize --store store-7
shopai world-model show store-7
```

5 commands replace what was 15+. Linear operator effort
even as stores grow linearly.

### Tests

200+ tests across operational + empire-scale + attribution +
ant-colony stacks. All deterministic on Windows.

## Niche-aware substrate (Waves 71-77, 2026-05-27)

Wave 47-70 shipped operational readiness + empire-scale
throughput. Wave 71-77 makes the substrate AWARE: cross-store
opportunities surface automatically + each store's orchestration
adapts to its niche.

### Wave 71 -- ``shopai transfer scan``

- ``engines/_transfer_scanner.py``: walks every store pair,
  finds (engine, action_type, capability) tuples that
  succeeded on source AND haven't been tried on target.
- Score: ``positive_outcomes * log10(revenue + 10)``. Min
  positive threshold = 2 (configurable). Top-k limit.
- ``shopai transfer scan [--top N] [--min-positive N]``.
- Replaces 380 manual ``transfer suggest`` calls for 20-store
  empire (n*(n-1) pairs at 20 stores).
- Two-pass algorithm: aggregate per-tuple WITHOUT min filter
  first, then filter on tuple totals. (Initial single-pass
  bug filtered per-action; 3 actions of 1 outcome each had
  tuple total = 3 but each failed min=2.)

### Wave 72 -- transfer candidates in empire dashboard

- ``shopai empire`` shows transfer candidate count inline +
  drill hint. JSON envelope gains "transfers" key.
- Empire summarizer's deterministic text appends
  "N cross-store transfer candidate(s) (top: ENGINE) --
  run shopai transfer scan to drill" when count > 0.

### Wave 73 -- niche-aware orchestrator

- ``engines/_niche_priority.py``: 5 niches (beauty / fashion
  / home / tech / food) each map to ordered cluster
  preference. ``merge_with_base(base_focus, niche)`` puts
  niche clusters FIRST then base, dedupe-preserving.
- ``DeterministicOrchestratorStrategy`` reads
  ``world_model.store.niche`` + applies ``_merge_niche()``
  to every lifecycle priority (launching / growing / mature
  / at_risk). Signals carry ``"niche": niche`` for
  downstream consumers.
- Per-niche cluster preferences:
  - beauty: merchandising -> content -> retention
  - fashion: merchandising -> content -> acquisition
  - home: quality -> merchandising -> retention
  - tech: quality -> pricing -> merchandising
  - food: fulfillment -> retention -> pricing
  - general / empty: no preference (use base unchanged)

### Wave 74 -- ``shopai niche`` discovery CLI

- ``shopai niche`` -- list 5 supported niches + top-3 clusters
- ``shopai niche --show beauty`` -- full priority for one
- ``shopai niche --by-store`` -- which stores tagged with what

### Wave 75 -- AI prompts include niche

- ``AICaptainStrategy``: reads niche from ``signals["niche"]``
  (orchestrator threads it). System prompt nudge: "Niche
  affects engine preference -- beauty stores favour loyalty
  over generic outreach; tech stores favour
  review_management".
- ``AIOrchestratorStrategy``: reads via
  ``_store_niche(store_id)``. System prompt nudge: "Niche
  affects pacing -- beauty/fashion stores ramp faster than
  tech/home".

### Wave 76 -- go-live warns on untagged niches

- ``engines/_go_live_check._check_store_niches()`` flags
  stores with empty or "general" niche. Warn (not fail) --
  niche is optional but recommended.
- Brings ``run_go_live_check()`` to 9 checks (was 8).
- Operator sees ``[WRN] store_niches  2 store(s) untagged:
  test, ts0efe-ih`` with fix hint inline.

### Wave 77 -- ``shopai niche --set STORE NICHE`` in-place update

- ``StoreManager.update_store_niche(store_id, niche)`` --
  raw SQL UPDATE; preserves credentials + history. Previously
  the operator had to remove + re-add, losing OAuth state.
- CLI validates niche against the supported set + "general";
  rejects with friendly error listing allowed values.
- Confirms with new top-3 cluster priority preview.

### Operator's niche-aware workflow

```bash
# Discovery + tagging
shopai niche                       # see 5 niches
shopai niche --show beauty         # drill one niche
shopai niche --by-store            # current tags
shopai niche --set store-7 beauty  # retag a store
shopai go-live                     # warns if any untagged

# Empire view (niche-aware downstream)
shopai empire --summarize --store store-7
shopai cycle run                   # orchestrator + captain
                                    # AI prompts include niche
shopai transfer scan               # cross-store winners
```

### Why this compounds with prior waves

Wave 7-36 captured per-cluster + per-engine revenue. Wave 73
makes the orchestrator USE niche-bias on top of revenue-bias
(Wave 8): a beauty store's cluster_focus is ``[merchandising,
content, retention, acquisition, pricing, quality]`` -- niche
first, then base. Wave 8's revenue-aware wrapper can still
re-rank within this list if attribution data exists. Same
deterministic ant-colony substrate; smarter input.

### Tests

- ``test_niche_priority.py`` -- 14 tests covering
  niche_cluster_focus + merge_with_base semantics
- ``test_transfer_scanner.py`` -- 10 tests on scoring +
  scan algorithm
- ``test_go_live_check.py`` -- 2 new tests for niche check

77 substrate waves total. 463 commits ahead of main.

## Onboarding wizard (Waves 92-96, 2026-05-27)

ShopAI's North Star: "single command from credentials
configured to launchable + earning." Substrate had been in
place for months (Wave 47-91: launch_orchestrator, niche
detector, go-live, cycle schedule) but no SINGLE command
chained them. Operator adding a new store still ran 6+
commands manually. Wave 92-96 closes the gap.

### Module

``engines/store_setup/onboarding_wizard.py`` -- thin
orchestrator that delegates each stage to existing
substrate. Each stage carries
``{name, status, detail, data}`` so the CLI text + JSON
surfaces stay machine-readable.

### 9-stage chain

```text
1. register        -- StoreManager.add_store
2. verify_creds    -- sm.test_connection probe (Wave 93)
3. sync            -- SyncService.sync_store first pull
4. niche_detect    -- Wave 83 keyword classifier; auto-applies
                       HIGH confidence only
5. launch          -- launch_orchestrator.launch_store
                       (policies + pages + discount + collections)
6. verify_launch   -- launch_audit.audit_store (Wave 94)
                       read-only 11-gate audit
7. relaunch_retry  -- auto-rerun launch + re-audit when
                       launch_closeable_gaps > 0 (Wave 95)
8. go_live         -- _go_live_check.run_go_live_check
9. schedule        -- platform-aware cron / schtasks (Wave 96)
```

### Failure semantics

- ``register fail`` -> chain aborts, verdict=failed
- ``verify_creds fail`` -> network-dependent stages SKIP
  (sync / niche_detect / launch / verify_launch /
  relaunch_retry); go_live + schedule still run; verdict=failed
- everything else is best-effort -- stages mark warn, chain
  continues to surface a complete punch list

### Verdicts

- ``ready``                -- every stage success
- ``ready_with_warnings``  -- some warns; operator review
- ``failed``               -- chain aborted on register
- ``dry_run``              -- preview only (no writes)

### Retry semantics (Wave 95)

When verify_launch warned AND launch_closeable_gaps > 0,
``relaunch_retry`` runs ``launch_store`` once + re-audits.
On full closure, the upstream verify_launch stage is
**upgraded** from warn -> success since post-retry state
is clean. Bounded retry; no infinite loop. Manual_admin
gaps are operator-only so retry skips when only those
remain.

### Platform schedule (Wave 96)

``_platform_schedule_template()`` returns the right
template per ``sys.platform``:

  - ``win32``         -> windows-task (schtasks ONHOURLY)
  - posix (linux/
    darwin/bsd)       -> cron hourly line

Schedule stage data carries both ``platform`` +
``schedule_line``. ``cron_line`` retained as Wave 92
backward-compat alias.

### CLI

```bash
shopai onboard test_store test.myshopify.com --api-key X
shopai onboard test_store test.myshopify.com --client-id A --client-secret B
shopai onboard test_store test.myshopify.com --api-key X --niche beauty
shopai onboard test_store test.myshopify.com --api-key X --dry-run
shopai onboard test_store test.myshopify.com --api-key X --json
```

### Tests

``tests/test_onboarding_wizard.py`` -- 29 tests covering
validation / dry-run / per-stage success+failure paths +
retry closure semantics + platform detection. Most tests
mock downstream chain; a few exercise the real path which
makes the suite ~2min.

### Why this compounds

The wizard is meta-substrate -- it doesn't add new
capabilities, it CHAINS existing ones into a single user-
facing flow. Every wave of substrate that came before
(W7-91) becomes more valuable because the operator now has
ONE entry point that exercises it all. The North Star
mission ships.

96 substrate waves total.

## Customer support automation (Waves 101-105, 2026-05-27)

Wave 47-100 covered launch + ops + niche + onboarding. Wave
101-105 ships customer support autonomy: refund issuance +
activity log + auto-pause bridge + ticket-tag applier +
empire surface.

### Wave 101: refund_applier
``engines/returns_management/refund_applier.py``
Autonomous ``SHOPIFY_CREATE_REFUND`` behind 5 safety gates:

  1. status=approved (engine-approved)
  2. refund_amount > 0
  3. refund_amount <= SHOPAI_REFUND_MAX_AMOUNT_USD (default $500)
  4. fraud_risk < SHOPAI_REFUND_MAX_FRAUD_RISK (default 0.5)
  5. parent_transaction found (looks up via SHOPIFY_GET_ORDER)

8 typed skip reasons + record_writeback on success/failure.
Opt-in via ``data.apply_refunds=True``.

### Wave 102: refund-status

``engines/returns_management/refund_log.py`` -- JSON-backed
append log at ``data/refund_log.json`` (bounded 1000 entries).
Pattern J guard.

``engines/returns_management/refund_status.py`` -- aggregator
(by_status / by_store / sample_skips).

CLI: ``shopai refund-status [--window-hours N] [--store ID]``.

### Wave 103: refund auto-pause bridge

``engines/returns_management/refund_state.py`` -- JSON state
file with paused/reason/auto_resume_after.

``engines/returns_management/refund_health.py`` -- analyzer +
bridge. analyze_refund_health returns healthy/degraded/critical
verdict based on adapter_failed ratio.

Env: ``SHOPAI_AUTO_PAUSE_REFUNDS_ON_FAILURE=1`` enables the
bridge. ``SHOPAI_REFUND_PAUSE_FAILURE_RATIO`` (default 0.30)
sets the critical threshold.

CLI: ``shopai refund-health [--apply-bridge]``,
``shopai refund-pause``, ``shopai refund-resume``.

### Wave 104: customer_support engine wireup

``engines/customer_support/ticket_tag_applier.py`` -- pushes
classification-derived tags via SHOPIFY_TAG_CUSTOMER. Tag
taxonomy:

  - Priority high/urgent -> shopai-support-priority-{class}
  - Sentiment negative -> shopai-support-sentiment-negative
  - Category billing/product -> shopai-support-{class}

Multi-ticket merge per customer; deterministic-sorted tag
sets. Opt-in via ``data.apply_ticket_tags=True``.

customer_support engine: advisory -> WIRED.

### Wave 105: shopai support-status

``engines/customer_support/support_status.py`` -- empire-wide
aggregator combining refund + ticket-tag activity into a
single verdict (healthy / quiet / degraded / paused).

CLI: ``shopai support-status [--window-hours N] [--store ID]``.

### Phase 11.A: Production wiring (Waves 106-109)

W106 cycle hook for refund_health bridge.
W107 daily-brief support block (one-liner when active or
paused).
W108 notify webhook adds refund_paused + refund_health_critical
alert kinds.
W109 this docs entry.

109 substrate waves total. Customer support autonomy is now
production-wired.

## Marketing automation (Waves 110-116, 2026-05-28)

Phase 11.B mirrors the customer-support pattern for ad-budget
autonomy. Substrate: ad_spend_log (110) + budget_state +
budget_health (111) + budget_applier (112) + marketing_status
(113) + cycle hook + notify (114-115) + docs (116).

### Wave 110: ``engines/roas_guardrails/ad_spend_log.py``
JSON log at ``data/ad_spend_log.json`` bounded 1000 entries.
Records every autonomous budget mutation: campaign_id /
store_id / action / prior_budget / new_budget / reason /
applied / status / error. Pattern J guard.

### Wave 111: budget_state + budget_health

``budget_state.py`` mirrors refund_state.py: JSON pause flag
at ``data/budget_state.json``. APIs: pause/resume/is_paused/
get_state with auto_resume_after deadline support.

``budget_health.py`` analyzer + bridge. Env knobs:

  SHOPAI_AUTO_PAUSE_BUDGET_ON_FAILURE=1
  SHOPAI_BUDGET_WARN_FAILURE_RATIO=0.15
  SHOPAI_BUDGET_PAUSE_FAILURE_RATIO=0.30
  SHOPAI_BUDGET_HEALTH_MIN_SAMPLE=5
  SHOPAI_BUDGET_AUTO_RESUME_HOURS=1.0

### Wave 112: ``budget_applier.py``

Autonomous ``ADS_UPDATE_BUDGET`` (action=cut) +
``ADS_PAUSE_CAMPAIGN`` (action=pause) behind:

  - budget pause flag (Wave 111)
  - SHOPAI_BUDGET_MAX_DELTA_USD (default $200 max delta per
    mutation)
  - actionable check (only cut / pause)

Opt-in via ``data.apply_budget_changes=True``. Dual recording:
record_writeback (Pattern Z) + record_ad_spend_event
(Wave 110 log).

### Wave 113: ``shopai marketing-status``

``marketing_status.py`` aggregates 110 + 111 into one verdict
(healthy / quiet / degraded / paused). Same shape as
support-status.

CLI: ``shopai marketing-status [--window-hours N] [--store ID]``.

### Wave 114: cycle hook

``cycle run --yes`` now also fires
``maybe_auto_pause_budget(window_hours=24)`` post-cycle. Same
env-gating + best-effort pattern as the refund bridge.

### Wave 115: notify integration

``_notify.collect_alerts`` adds:

  - ``budget_paused`` (critical) when budget_state.paused
  - ``budget_health_critical`` (critical) when verdict=critical
    and not paused

### CLI surfaces (Wave 113 family)

  shopai marketing-status     # aggregator
  shopai marketing-health     # verdict + --apply-bridge
  shopai marketing-pause      # manual flag set
  shopai marketing-resume     # clear flag

### Pattern reusability

Phase 11.A (refund) + Phase 11.B (budget) now share an
identical substrate template:

  *_log.py        -- bounded JSON activity log
  *_state.py      -- JSON pause flag + auto_resume
  *_health.py     -- analyzer (failure_ratio verdict) + bridge
  *_applier.py    -- gated writer + dual recording
  *_status.py     -- empire-wide aggregator + verdict + next_action

Phase 11.C (Waves 117-120) will extract this into reusable
``core/autonomy/*`` substrate so future autonomous loops
(returns, fulfillment, customer outreach) don't re-implement
the boilerplate.

116 substrate waves total. Two autonomy domains
(customer-support + marketing) production-wired in parallel.

## Phase 11.C: Reusable autonomy substrate (Waves 117-120)

Phase 11.A (refund) + Phase 11.B (budget) share an identical
5-piece template. Phase 11.C extracts the boilerplate into
``core/automation/*``:

  - ``action_log.py`` (W117): generic JSON log
  - ``pause_state.py`` (W118): generic pause flag + auto_resume
  - ``health_analyzer.py`` (W119): generic analyzer + bridge
    parameterized on env_prefix + DI'd recent_events_fn /
    is_paused_fn / pause_fn

W120: 19 tests prove the substrate behaves identically to
the inlined refund/budget versions.

Refund + budget modules NOT YET refactored. The generic
pieces are the TEMPLATE for future domains (fulfillment /
customer outreach / inventory restocking).

## Phase 11.D: Defensive audits (Waves 121-122)

Two new institutional audits join the roster (bringing it
to 10):

### Pattern N (W121) -- niche-merge preservation

Wave 89 found AIOrchestratorStrategy dropped the niche merge
silently. ``engines/_pattern_n_audit.py`` probes every
OrchestratorStrategy with a beauty-niche store + asserts
``cluster_focus[0:3]`` retains a beauty top cluster.

CLI: ``shopai pattern-n-audit``.

### Pattern O (W122) -- opt-in gate verification

AST-scan asserting every wired engine's writer modules have
a ``data.get("apply_X")`` reference in flow.py OR the writer
itself. Caught a real Wave 112 gap (budget_applier ungated)
which the W122 commit fixed.

Exemption list for legitimate non-gated writers
(launch_orchestrator family).

CLI: ``shopai pattern-o-audit``.

### Updated audit roster (10)

K / OAuth / Y / I / J / Z / Q / Wireup-resolve / N / O

### Phase 11 totals

Substrate: 20 waves (W106-125)
Tests: 134 new
Commits: 472+ ahead of main
Audits: 8 -> 10
Autonomy domains: customer-support + marketing parallel

125 substrate waves total. Phase 11 complete.
