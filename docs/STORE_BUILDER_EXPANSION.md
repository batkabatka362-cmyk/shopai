# Store Builder Expansion Plan

**Scope:** бүх Shopify admin-ийн configuration menu-г `execution/store_configurator.py`-аар автомат үүсгэх хамрах хүрээ.

**Branch:** `claude/update-shop-ai-docs-dVyQc`
**Дүрэм:** §4d — амьд + сайн + алдаагүй. Phase 1 хуульзүйн + conversion-критик.

---

## 1. Одоо байгаа байдал (11 feature)

`ALL_FEATURES = ("collections", "discounts", "shipping", "content", "product_tags", "ai_config", "gifts", "loyalty", "referral", "emails", "payments")`

Бүгд REST API дамждаг, dry_run дэмждэг, niche-aware. 1346 мөр, бүрэн тесттэй.

---

## 2. Дутуу 10 feature (Phase 1-3-ээр эрэмбэлсэн)

### Phase 1 — хууль + conversion critical (sprint 1)

| # | Feature | API | Endpoint | Яагаад |
|---|---|---|---|---|
| 1a | **Policies** | REST | `POST /admin/api/2024-10/policies.json` | GDPR/CCPA required, Shopify хуулийн reminder enabled |
| 1b | **Navigation menus** | GraphQL | `menuCreate`, `menuItemsCreate` | Conversion — reactor browsing + footer links |
| 1c | **Pages** (About, Contact, FAQ) | REST | `POST /admin/api/2024-10/pages.json` | Trust signals — зөвлөмж-гэрэл |
| 1d | **Store details** (name, currency, timezone, address) | REST | `PUT /admin/api/2024-10/shop.json` | Shopify API base — бусад feature-ийн prereq |
| 1e | **Notifications** (order conf, shipping update, refund) | GraphQL | `emailTemplateUpdate` | UX — customer communication branded |

### Phase 2 — brand + SEO (sprint 2)

| # | Feature | API | Endpoint | Яагаад |
|---|---|---|---|---|
| 2a | **Metafields** (brand, SEO defaults) | REST | `POST /admin/api/2024-10/metafields.json` | Structured data, AI agent discovery |
| 2b | **Theme customization** (colors, logo, favicon) | Assets API | `PUT /admin/api/2024-10/themes/:id/assets.json` | Brand identity |

### Phase 3 — scale (sprint 3)

| # | Feature | API | Endpoint | Яагаад |
|---|---|---|---|---|
| 3a | **Markets** (multi-currency, multi-region) | GraphQL | `marketCreate`, `marketRegionCreate` | Z3 multi-store — cross-market sales |
| 3b | **Locations** (warehouse) | REST | `POST /admin/api/2024-10/locations.json` | Inventory routing |
| 3c | **Checkout** (abandoned cart recovery, express) | GraphQL | `checkoutBrandingUpsert` | Conversion recovery |

---

## 3. API vs direct: бүгд API

Shopify admin menu бүрт public API бий (REST + GraphQL). Browser automation (Playwright) шаардахгүй. Энэ нь:

- **Idempotent** — `set X to absolute value` хэв маягыг барина (§4b.D)
- **Testable** — ShopifyClient existing fake-with помощью mock хийнэ
- **Rate-limited centrally** — `max_shopify_calls_per_second=2` гинжиэр дамждаг
- **Retry-hardened** — existing `_client_request_id` + exponential backoff шүүхэлттэй

`ShopifyClient` nь одоо REST (.rest()) + GraphQL (.graphql()) аль алиныг дэмждэг. Phase 1a дан REST, Phase 1b + 1e GraphQL.

---

## 4. Feature бүрийн тасалгаа (template)

Шинэ feature нэмэх бүрт:

1. `_setup_<name>(self, shop_url, access_token, niche, ...)` method `execution/store_configurator.py`-д
2. `ALL_FEATURES` tuple-д нэмэх
3. `configure()` doorh dispatch block нэмэх
4. `dry_run=True` эхний үнэлгээ log хийж return
5. `verify=True` post-write read-back (§4b.G step 6)
6. Idempotent хэв маяг — `set X to absolute value` (§4b.D)
7. Test: real fake ShopifyClient + expected REST/GraphQL calls
8. Result dict-д entry: `{"status": "success|skipped|dry_run|error", "details": {...}}`

---

## 5. Phase 1a Policies — concrete сэтгэлгээ

**Required policies (GDPR/CCPA + Shopify default):**
- `privacy_policy` — personal data handling
- `refund_policy` — return/refund terms
- `terms_of_service` — user agreement
- `shipping_policy` — shipping methods + timelines
- `contact_information` (subject of shop setting)

**Template content:** niche-aware LLM generation with sandbox gate (§4b.G paranoid mode — owner approval before live policy published). First version uses hard-coded safe templates + placeholder for store address; later version LLM-augments.

**API call:** REST `PUT /admin/api/2024-10/policies.json` with shape:
```json
{"policy": {"title": "Privacy Policy", "body": "<html>...</html>"}}
```

**Shape choice:** hard-coded templates first (zero LLM cost per store), LLM augmentation in Phase 1a+1.

---

## 6. Timeline

- **Phase 1:** 1a → 1e, 5 commits, 1 sprint. Хамгаалалт: GDPR-compliant storefront.
- **Phase 2:** 2a → 2b, 2 commits. Brand identity.
- **Phase 3:** 3a → 3c, 3 commits. Scale.

Нийт 10 commit, store_configurator-ыг 11 feature-аас 21 feature-т хүргэнэ.

---

## 7. §4c.K self-check

- Mission: Z5 (Shopify full control) — direct. T1 prerequisite мөн (legal policies байхгүй store бол launch-д эрсдэл).
- Plumbing/capability: бүх 10 commit capability, 0 plumbing.
- Dollar distance: 2-3 (store → trust → conversion).
