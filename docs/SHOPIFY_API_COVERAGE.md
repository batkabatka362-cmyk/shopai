# Shopify Admin API — coverage audit

**Last audited:** 2026-04-23
**Target:** 100% of every owner-usable Shopify Admin endpoint
reachable from one canonical client
(`core/adapters/shopify_admin/`).

**Legend:**
  * ✅ Full coverage in `core/adapters/shopify_admin/`
  * 🟡 Partial — covered elsewhere (store_configurator, bridge,
    scripts) but not through the unified client
  * ❌ Missing entirely

**Priority:**
  * P0 — revenue-direct, must ship
  * P1 — ops efficiency, ship within session
  * P2 — nice to have, backlog
  * P3 — advanced / rarely needed

---

## Products & catalog

| Resource | Endpoints | Status | Priority | Current location |
|---|---|---|---|---|
| Products | list / get / create / update / delete / count | 🟡 | P0 | `execution/shopify/product_creator.py` + `product_updater.py` — NOT in shopify_admin |
| Variants | update / delete + price / inventory_item_id | 🟡 | P0 | scattered in execution/ |
| Product images | list / create / update / delete (URL or base64) | 🟡 | P0 | `execution/shopify_automation.py:add_product_image_url` |
| Product metafields | list / create / update / delete (per product) | 🟡 | P1 | `execution/store_configurator.py:_setup_metafield_definitions` via GraphQL |
| Metafield definitions (typed schemas) | list / create / update / delete | 🟡 | P1 | store_configurator GraphQL |

## Collections

| Resource | Endpoints | Status | Priority | Current location |
|---|---|---|---|---|
| Smart collections | list / create / update / delete / order | 🟡 | P1 | `store_configurator._setup_collections` |
| Custom collections | list / create / update / delete | 🟡 | P1 | store_configurator |
| Collects (product ↔ collection) | list / create / delete | 🟡 | P1 | store_configurator (partial) |

## Inventory

| Resource | Endpoints | Status | Priority | Current location |
|---|---|---|---|---|
| **Inventory levels** — list / set / adjust / connect | ✅ | P0 | `shopify_admin/inventory.py` |
| **Inventory items** — get / update (cost) | ✅ | P0 | `shopify_admin/inventory.py` |
| **Locations** — list / get | ✅ | P1 | `shopify_admin/inventory.py` |

## Orders & fulfillment

| Resource | Endpoints | Status | Priority | Current location |
|---|---|---|---|---|
| Orders | list / get / create / update / close / open / cancel / count | 🟡 | P0 | webhook read only |
| Line items | embedded in order — read | 🟡 | P0 | `_normalize_order` in handlers |
| **Refunds** | list / get / calculate / create (per order) | ❌ | **P0** | — |
| **Transactions** | list / get / create (per order) | ❌ | **P0** | — |
| **Fulfillment orders** | list / get / move / close / cancel / accept / reject | ❌ | **P0** | — |
| **Fulfillments** | list / get / create / update_tracking / cancel | ❌ | **P0** | — |
| **Fulfillment services** | list / create / update / destroy | ❌ | P1 | — |
| Fulfillment events (tracking updates) | list / create / delete | ❌ | P1 | — |
| Order risks | list / get / create / update / delete | ❌ | P2 | — |
| Dispute / chargebacks | list / get | ❌ | P2 | — |
| **Draft orders** | ✅ — full lifecycle | ✅ | P0 | `shopify_admin/draft_orders.py` |
| Abandoned checkouts | list / get (read-only webhook) | 🟡 | P1 | `core/webhooks/checkout_handler.py` — webhook only, no poll |

## Customers

| Resource | Endpoints | Status | Priority | Current location |
|---|---|---|---|---|
| **Customers** | list / get / create / update / delete / search / count | 🟡 | **P0** | webhook read only |
| **Customer addresses** | list / get / create / update / delete / default | ❌ | P0 | — |
| Customer saved searches | list / get / create / update / delete | ❌ | P2 | — |
| Customer segments (GraphQL) | list / create / delete | ❌ | P1 | — |
| Customer metafields | list / create / update / delete | ❌ | P1 | — |
| Customer tags (via update) | read / write | 🟡 | P1 | — |

## Discounts & promotions

| Resource | Endpoints | Status | Priority | Current location |
|---|---|---|---|---|
| **Price rules** | list / get / create / update / delete / count | ✅ | P0 | `shopify_admin/discounts.py` |
| **Discount codes** | list / get / create / update / delete / lookup / batch | ✅ | P0 | `shopify_admin/discounts.py` |
| Automatic discounts (GraphQL) | create / update / delete | ❌ | P1 | — |
| Gift cards | list / create / update / disable | ❌ | P1 | — |
| Gift card codes | search / get by LAST_CHARACTERS | ❌ | P2 | — |

## Content / storefront

| Resource | Endpoints | Status | Priority | Current location |
|---|---|---|---|---|
| Pages | list / get / create / update / delete | 🟡 | P1 | `store_configurator._setup_pages` |
| Blogs | list / get / create / update / delete | 🟡 | P1 | store_configurator._setup_blog |
| Articles (per blog) | list / get / create / update / delete | 🟡 | P1 | store_configurator |
| Article comments | list / approve / spam / restore | ❌ | P2 | — |
| **Themes** | list / get / publish / create / destroy | ❌ | **P0** | — (owner needs this for theme auto-deploy) |
| **Theme assets** | list / get / create_or_update / destroy | ❌ | **P0** | — |
| Script tags | list / get / create / update / delete | 🟡 | P1 | `store_configurator._setup_script_tags` |
| Redirects | list / get / create / update / delete | 🟡 | P1 | `store_configurator._setup_redirects` |
| Navigation (menus — GraphQL) | list / update | 🟡 | P1 | `store_configurator._setup_menus` |
| Locales (GraphQL) | list / publish / unpublish | ❌ | P2 | — |
| llms.txt (custom, not native) | build / serve | ✅ | n/a | `execution/seo/llms_txt.py` |

## Shop & settings

| Resource | Endpoints | Status | Priority | Current location |
|---|---|---|---|---|
| Shop | get | 🟡 | P1 | various |
| Shop metafields | list / create / update / delete | 🟡 | P1 | store_configurator._setup_brand |
| **Policies** (privacy / refund / TOS / shipping) | update via GraphQL | ✅ | P1 | store_configurator._setup_policies + graphql helper |
| Countries / provinces | list | ❌ | P3 | — |
| Currencies (GraphQL `currencySettings`) | list | ❌ | P2 | — |
| Users (staff) | list / get / current | ❌ | P3 | — |

## Shipping & markets

| Resource | Endpoints | Status | Priority | Current location |
|---|---|---|---|---|
| **Shipping zones** | list / get | 🟡 | P0 | `scripts/deguar_checkout_check.py` read only |
| **Shipping zone rates** (price / weight / carrier) | create / update / delete | ❌ | **P0** | — |
| Carrier services (custom rates) | list / create / update / delete | ❌ | P2 | — |
| **Markets** (GraphQL) | list / get / create / update / delete | ❌ | **P1** | — (international) |
| Market web presences (GraphQL) | list / create / update / delete | ❌ | P1 | — |

## Webhooks & apps

| Resource | Endpoints | Status | Priority | Current location |
|---|---|---|---|---|
| Webhooks | list / get / create / update / delete / count | ✅ | P0 | `core/webhooks/register.py` + GraphQL in store_configurator |
| Access scopes (introspection) | list | 🟡 | P1 | `scripts/deguar_scope_audit.py` |
| Application charges | list / create / activate | ❌ | P3 | — |
| App subscriptions / usage | list / create / cancel | ❌ | P3 | — |
| Bulk operations (GraphQL) | run / poll / cancel | ❌ | P2 | — |

## Financial & reporting

| Resource | Endpoints | Status | Priority | Current location |
|---|---|---|---|---|
| Payments (`payments.json`) | list (gateways) | 🟡 | P0 | `scripts/deguar_checkout_check.py` read only |
| Payout / balance | list (Shopify Payments only) | ❌ | P2 | — |
| Tax rates / engine | read | ❌ | P2 | — |
| Reports (analytics) | list / get | ❌ | P3 | — |

## Marketing events & activities

| Resource | Endpoints | Status | Priority | Current location |
|---|---|---|---|---|
| Marketing events | list / get / create / update / delete | ❌ | P1 | — |
| Marketing activities (app-scoped) | list / create / update / delete | ❌ | P2 | — |
| Customer events (GraphQL) | read | ❌ | P2 | — |

## Summary

**Total resources tracked:** 58
**Coverage status:**
  * ✅ Full: **11** (19%)
  * 🟡 Partial: **20** (34%)
  * ❌ Missing: **27** (47%)

**P0 (revenue-critical) resources still missing/partial:** 10
  * refunds ❌
  * transactions ❌
  * fulfillment_orders ❌
  * fulfillments ❌
  * customers 🟡 (webhook only)
  * customer_addresses ❌
  * themes ❌
  * theme_assets ❌
  * shipping_zone_rates ❌
  * products 🟡 (not unified)

**P1 resources missing:** ~12 incl. gift cards, customer
segments, markets, marketing events, collections unification,
access scopes unification.

---

## Planned ship order (by commit)

### Wave 1 (SHIPPED — commit `33bd37b`)
  * ✅ Unified client (`client.py`)
  * ✅ Discounts
  * ✅ Inventory
  * ✅ Draft orders

### Wave 2 (NEXT commit)
  * ✅ Fulfillments + fulfillment_orders
  * ✅ Refunds + transactions
  * ✅ Customers (full CRUD + addresses + search)

### Wave 3
  * Orders (full CRUD + cancel / close / tag update)
  * Products (unified — pull from execution/shopify/ into
    shopify_admin)
  * Themes + theme_assets (creative auto-deploy)

### Wave 4
  * Shipping zones + rates (wired via Markets GraphQL for
    international)
  * Gift cards
  * Marketing events

### Wave 5 (backlog)
  * Bulk operations (GraphQL) — big catalog imports
  * Customer segments (GraphQL) — ad targeting
  * Reports, payouts, disputes — analytics
  * Users / staff — multi-operator stores
  * Locales + currencies — multi-language

Every wave follows the same pattern:
  * Module under `core/adapters/shopify_admin/<resource>.py`
  * `@staticmethod`-style API taking `ShopifyAdminClient`
  * Mock-HTTP unit tests (`test_shopify_admin_<resource>.py`)
  * One commit per wave or sub-wave, bounded at ~2,000 LOC

---

## Non-goals (explicitly NOT in scope)

  * **Storefront API** — public-facing GraphQL surface for
    headless carts. Different auth (public token), not what
    owner needs for admin automation.
  * **Partners API** — app publisher management. We're not
    publishing an app (yet).
  * **Payment Apps API** — we consume payment providers, not
    create them.
  * **Checkout UI extensions** — Shopify Functions territory;
    outside the automation envelope.

These stay out so we don't accidentally build surface owner
never asked for.
