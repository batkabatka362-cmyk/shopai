# ShopAI Business Model × Channel Matrix

**Date:** 2026-04-23
**Status:** Design note + implementation roadmap (owner-approved framing)

Owner framed the Shopify landscape as a **4×4 matrix** — 4 business
models × 4 traffic channels = 16 cells. Each cell is a distinct
playbook with its own economics, risk profile, and automation
surface. This document maps ShopAI's current coverage of each cell,
identifies shared blockers, and proposes a phased implementation
plan.

---

## The 4×4 matrix

|                        | Paid Ads (Meta/Google/TikTok) | Organic Content (video/photo/post) | SEO / Search | Community (Discord/TG/email/FB) |
|---|---|---|---|---|
| **Dropshipping**       | ✅ **Deguar's current cell** (full loop) | 🟡 fragments | 🟡 SEO metafields wired | 🟡 Telegram inbox only |
| **Own products**       | 🟡 | 🟡 | 🟡 | 🟡 |
| **Digital products**   | 🔴 blocked by supplier.py | 🔴 | 🟡 legal templates only | 🔴 |
| **Partnership / affiliate** | 🔴 blocked by supplier.py | 🔴 | 🔴 | 🔴 |

Legend: ✅ full autonomous loop · 🟡 fragments / partial · 🔴 missing

**The only cell with a complete autonomous loop is
`(Dropshipping, Paid Ads)`.** Every other cell has fragments or
blockers. Deguar is parked in the green cell and still hasn't
closed its first $1 — scaling to 16 cells before validating 1 is
"architecture astronaut" mode per CLAUDE.md §4.

---

## Coverage audit (detail)

### Business models

| Model | Coverage | Critical gap |
|---|---|---|
| **Dropshipping** | ~70% | Only CJ adapter wired (`core/adapters/sourcing/cj_dropshipping.py`). AutoDS roadmap, Spocket/Doba/Zendrop missing. |
| **Own products** | ~40% | Inventory tracking ok (`engines/order_management/inventory_checker.py`). WMS adapters (NetSuite/ShipStation), PO workflow, forecasting, multi-warehouse routing all missing. |
| **Digital products** | ~15% | Legal templates only (`engines/legal_document/content_generator.py:digital_content_license`). No file/CDN hosting, no license key gen, no access control, no course platform integrations. |
| **Partnership / affiliate** | ~20% | Partner scoring only (`engines/affiliate/partner_evaluator.py`). No network adapters (ShareASale, CJ Affiliate, Impact, Amazon Associates), no commission calc, no payout orchestration. |

**Shared bottleneck:** `workflows/launch/steps/supplier.py` + `core/webhooks/order_handler.py` both hard-code CJ fulfillment as the only order path. All three non-dropshipping models are blocked here.

### Channels

| Channel | Full loop? | What's live | What's missing |
|---|---|---|---|
| **Paid ads** | Meta only | `core/adapters/ads/meta_ads.py`, `execution/launch/publisher_bundle.py`, outcome recording → brain | Google Ads + TikTok Ads exist as MCP stubs in `/tools/adapters/` but NOT as core adapters. No platform-routing in publisher. |
| **Content** | No | Generator (`execution/content/ai_writer.py`), publisher (`publisher.py`), video (`core/adapters/fal/video_router.py`), cycle hook | Generated content doesn't flow into publish step. No TikTok Shop product create (read-only adapter). No video distribution to Reels/TikTok/YouTube. |
| **SEO** | Read-only | Schema.org JSON-LD (`execution/seo/schema_stack.py`), llms.txt (`execution/seo/llms_txt.py`), SEO analyzer in cycle | Analysis reports grades but doesn't trigger rewrites. No sitemap gen. No theme-deploy hooks (JSON-LD generated but not auto-embedded). |
| **Community** | Owner inbox only | Telegram bot (owner commands), email adapters (brevo/resend) | Telegram is 1:1 with owner, not community broadcast. No Discord adapter. No Facebook Group adapter. Email is transactional-only (no newsletter/drip). |

---

## The one cell we actually close today

`(Dropshipping, Paid Ads)` — Deguar's config:

```
Supplier:  CJ Dropshipping (or AutoDS when ADAPTER lands)
Product:   imported via source.py → shopify_create.py
Ad:        Meta Ads via MetaAdsAdapter (publisher_bundle.py:235)
Attribution: Meta Pixel + order webhook → OutcomeRecorder → brain
Learning:  Deliberation back-fill on paid orders
```

Every other cell either lacks an adapter, lacks an outcome-loop, or
is blocked by `supplier.py`'s CJ assumption.

---

## Risk classification (for future per-action approval)

Owner's stated vision: **"full autonomous AGI, but high-risk/high-impact
→ human approve"**. This requires a 4-level risk classification on every
write action. Proposed taxonomy:

| Level | Examples | Gate |
|---|---|---|
| **LOW** | metafield write, tag add, page update, collection membership change | auto-approve (current behaviour) |
| **MEDIUM** | price change < 10%, product draft/publish, image upload, blog post publish | auto-approve with `auto_approve=True`, queue if `False` |
| **HIGH** | new ad campaign creation, ad budget increase, discount code creation, supplier order | **queue → Telegram → owner confirm** |
| **CRITICAL** | live_execution flip, delete action, policy rewrite, checkout config change, >$100 ad spend/day, new store connect | **queue → Telegram → double-confirm** |

Current state: binary `auto_approve=True/False` at the controller
level + "confirm" suffix pattern for MCP write tools
(`agents/owner_dialog/tool_dispatcher.py`). The 4-level queue
doesn't exist yet — Phase 2 work.

---

## Implementation phases (proposed)

### Phase 1 — Abstraction scaffolding (THIS SESSION, 1-2 hours)

Goal: make "business model" and "channel" first-class concepts in
`LaunchGoal` without changing any runtime behaviour. Deguar's
current launch still works identically.

Ships:
  * `core/contracts/business_model.py` — `BusinessModel` enum
    (`DROPSHIPPING | OWN_PRODUCTS | DIGITAL | PARTNERSHIP`) +
    `Channel` enum (`PAID_ADS | CONTENT | SEO | COMMUNITY`) +
    `RiskLevel` enum (`LOW | MEDIUM | HIGH | CRITICAL`).
  * Extend `LaunchGoal` (`workflows/launch/context.py`): add
    `business_model: BusinessModel = DROPSHIPPING` +
    `channel: Channel = PAID_ADS`. Defaults preserve Deguar's
    current cell.
  * Swap the two hard-coded "dropshipping" LLM prompt strings
    (`core/brain/decision_brain.py:1112`,
    `core/brain/model_coordinator.py:153`) to interpolate the
    business model from goal.
  * Tests: backward-compat (existing LaunchGoal() calls still
    work), enum round-trip, LLM prompt contains the named model.

**Zero runtime impact** — no new behaviour activated, just
abstraction hooks in place for later phases.

### Phase 2 — Risk-classified approval gate (AFTER Deguar's first order)

Goal: implement the 4-level risk taxonomy + Telegram-mediated
approval queue.

Ships:
  * `core/system/risk_gate.py` — `classify(action) → RiskLevel`
    + `is_auto_approved(risk)` based on per-level policy.
  * `core/system/approval_queue.py` — SQLite-backed queue for
    HIGH/CRITICAL pending actions. Each row: action_id, level,
    payload, expires_at, status (pending/approved/denied/expired).
  * Telegram integration: when HIGH arrives, broadcast to owner
    with inline `approve` / `deny` buttons. 30-min expiry.
  * Existing `auto_approve` flag + `confirm` suffix become thin
    wrappers over the new gate (backwards compatible).

Effort: ~2-3 days.

### Phase 3 — Cell-specific automation (AFTER repeatable revenue)

One cell at a time, based on what Deguar's learnings suggest is
the next highest-leverage addition. Likely order:

  1. Fill `(Dropshipping, Paid Ads)` second row — Google Ads +
     TikTok Ads core adapters (promote MCP stubs) + platform
     routing in `publisher_bundle`.
  2. Fill `(Dropshipping, Content)` — wire organic video
     distribution from `fal/video_router.py` to Reels/TikTok
     posting via existing `publisher.py`.
  3. Fill `(Dropshipping, SEO)` — auto-deploy Schema.org JSON-LD
     to theme; wire analyzer → rewriter feedback.
  4. Only then consider crossing into `Own Products` or `Digital`
     models.

Effort: 1-2 weeks per cell.

### Phase 4 — Non-dropshipping models (FAR future)

Fork when Deguar's dropshipping is a repeatable $10k/month
business. Not before.

  1. Unblock `supplier.py` + `order_handler.py` to allow
     `business_model != DROPSHIPPING`.
  2. Add digital fulfillment (file hosting, license keys).
  3. Add affiliate network adapter + commission tracking.

---

## What this means for the current sprint

**Do now (Phase 1):** enum + LaunchGoal extension + 2-prompt update.
Zero risk, sets the stage. 1-2 hours.

**Don't do now:**
  * Don't build Google Ads / TikTok Ads core adapters (no Deguar
    traffic proves the playbook yet).
  * Don't build digital delivery or affiliate networks.
  * Don't build the risk gate — Phase 2 work.

**Owner's external blockers stay the same:**
  * Shopify Payments activate
  * Missing scopes grant
  * Product images (21/21 have only 1)
  * Supplier mapping

---

## Decision log

| Decision | Rationale |
|---|---|
| Phase 1 now, not all phases | Validate the `(Dropshipping, Paid Ads)` cell before abstracting for cells that may never ship |
| Default `LaunchGoal.business_model = DROPSHIPPING` | Backwards-compat for every existing Deguar call site |
| Don't build `RiskLevel` enforcement yet | Enforcement = Phase 2. Phase 1 just declares the enum so contracts can reference it. |
| Swap LLM prompt strings to use named model | Two places hard-code "dropshipping" in prompts — trivial to make model-aware now |
| Defer AutoDS / Spocket / Doba | CJ is enough to validate the model. 2nd supplier = Phase 3 cell work. |

---

## Appendix: file-level map

### Business model adapter points
  * `workflows/launch/steps/supplier.py:30` — CJ credential gate (blocker for 3 other models)
  * `workflows/launch/steps/source.py:70` — sourcing normalisation (assumes physical shipping)
  * `core/webhooks/order_handler.py:_dispatch_cj_fulfillment` — routes every order to CJ
  * `core/brain/decision_brain.py:1112` — LLM prompt hard-codes "dropshipping"
  * `core/brain/model_coordinator.py:153` — "Evaluate this product for dropshipping"

### Channel adapter points
  * `execution/launch/publisher_bundle.py:235` — hard-codes MetaAdsAdapter
  * `core/adapters/ads/meta_ads.py` — full Meta Ads adapter
  * `/tools/adapters/google_ads.py` — MCP stub (no core adapter)
  * `/tools/adapters/tiktok_ads.py` — MCP stub (no core adapter)
  * `execution/content/ai_writer.py` — content generator (disconnected from publisher)
  * `execution/seo/schema_stack.py` — Schema.org generator (no theme deploy)
  * `core/adapters/telegram_bot/bot.py` — owner inbox only (no community broadcast)

### Risk gate points (current)
  * `core/system/live_execution.py:30` — global on/off
  * `core/autonomous/controller.py:130` — per-cycle `auto_approve`
  * `agents/owner_dialog/tool_dispatcher.py:218` — "confirm" regex for MCP writes
