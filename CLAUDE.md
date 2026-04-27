# CLAUDE.md — Working Notes for the ShopAI Shopify Integration

This file describes how to operate inside this codebase as a senior software
engineer. It is written for *me* — the assistant working on the Shopify
adapter layer — so that future sessions pick up the same standards
without rediscovery.

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

Phase 7 (more engine writebacks) — **in progress**:
Same pattern as Phase 6 applied to additional recommender
engines. So far:

- PR #49 — `product_lifecycle` archives declining products
  via `SHOPIFY_UPDATE_PRODUCT` (status=ARCHIVED). First
  destructive writeback; needed stricter safety gates
  (stage + velocity + confidence). Engine output now also
  carries `confidence: float` so the writer can gate on it
  without re-running the classifier.

Future Phase 7 candidates: `inventory` (INVENTORY_ADJUST),
`wholesale_b2b` (CREATE_DISCOUNT B2B-scoped),
`product_optimization` (multi-modal UPDATE_PRODUCT),
`search_optimization` (UPDATE_PRODUCT seo fields — needs the
products adapter extended first).

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
