# ShopAI 2026 Implementation Plan

> Owner-plan shape: top 8 items first (~6-8 weeks), others queued.
> Markets: US + EU + UK. Budget: wide (see §Budget).
> Adapter-over-build wherever a SaaS is mature.

Research source: `docs/MARKET_RESEARCH_2026.md` (12-agent synthesis).

---

## Priority queue — build order

| # | Item | Wave | Deadline | Why now |
|---|------|------|----------|---------|
| 1 | Shopify OAuth 60min + refresh harden | A | Apr 1 2026 (past) | Public apps silently breaking |
| 2 | Agentic Storefront status + attribution | B | None (opportunity) | March 24 default-on; 5.6M store unlocked |
| 3 | Landed-cost calculator + de-minimis router | F | None (margin-critical) | Section 321 US volatility |
| 4 | EU AI Act Art.50 C2PA creative gate | A | Aug 2 2026 | 3% global turnover fine |
| 5 | ShopAI MCP server | B | None (strategic) | Owner controls from Claude |
| 6 | Schema stack + llms.txt + markdown mirror | E | None (compounds) | +13% LLM citation |
| 7 | Triple Whale Moby adapter + RL disagreement | C | None | Adapter-over-rebuild |
| 8 | fal.ai video router | D | None | Cheapest creative volume |

---

## Wave A — Hard deadlines

### A-1 · Shopify OAuth refresh
* **Module:** `core/auth/shopify_auth.py` (extend)
* **Do:** Detect `invalid_grant`; auto-exchange refresh token; persist rotated tokens per store.
* **Accept:** unit-tested OAuth flow survives server-forced re-auth without owner action.
* **Effort:** 1 day.

### A-4 · EU AI Act Article 50 compliance gate
* **Module:** `execution/compliance/eu_ai_act_gate.py` (new)
* **Do:** Gate every AI-generated creative (image/video) before ad upload; require (1) C2PA metadata, (2) visible "AI" disclosure tag, (3) `vault/Decisions/` audit entry.
* **Accept:** creative missing C2PA fails publish; EU-targeted campaign blocked hard.
* **Effort:** 2 days.

## Wave B — Agentic channel unlocks

### B-1 · Agentic Storefront bridge
* **Module:** `core/bridge/agentic_storefront.py` (new) + `shopai agentic status` CLI
* **Do:** Query Shopify admin sales-channel API for agentic enrollment; surface per-channel attribution from `orders.source_name`; add `channel=chatgpt/perplexity/copilot/gemini` KPI to memory.
* **Accept:** `shopai agentic status` shows which AI channels are on + 7d GMV per channel.
* **Effort:** 2-3 days.

### B-2 · ShopAI MCP server
* **Module:** `mcp_server/` (new)
* **Do:** MCP server exposing `brain_snapshot`, `kill_campaign`, `scale_campaign`, `list_winners`, `explain_decision` tools. Anthropic MCP SDK.
* **Accept:** Claude Desktop / Claude Code can call each tool; audit event recorded per call.
* **Effort:** 2 days.

## Wave C — Adapter-over-build

### C-1 · Triple Whale Moby adapter
* **Module:** `core/adapters/triplewhale/moby.py` (new)
* **Do:** Wrap Moby Agents API; record Moby recommendation alongside ShopAI RL vote; on each ad decision log `(moby_vote, shopai_vote, actual_outcome)` — learn which source wins.
* **Accept:** after 30 days of data, `shopai brain-learned list --origin moby_vs_shopai` shows win-rate per source.
* **Effort:** 3 days.

## Wave D — Creative factory

### D-1 · fal.ai video router
* **Module:** `core/adapters/fal/video_router.py` (new)
* **Do:** Route creative requests by budget × quality: Kling 2.6 Turbo ($0.07/s) for social volume, Veo 3.1 ($0.20/s) for hero. Cost cap $10/SKU/week default.
* **Accept:** 1 SKU generates 10 video variants under $5 test; reject over-budget calls.
* **Effort:** 2 days.

## Wave E — GEO hardening

### E-1 · Schema stack + llms.txt
* **Module:** `execution/seo/schema_stack.py` + `execution/seo/llms_txt.py` (both new)
* **Do:** Emit `Product` + `Offer` + `AggregateRating` + `FAQPage` + `HowTo` + `VideoObject` + `BreadcrumbList` + `Organization` with `author.@id`. Separate `llms.txt` + markdown mirror per product at `/products/{slug}.md`.
* **Accept:** Rich Results Test passes all types; Anthropic/Perplexity crawler fetches the mirror.
* **Effort:** 3 days.

## Wave F — Learning loop enrichment

### F-1 · Landed-cost calculator
* **Module:** `execution/fulfillment/landed_cost.py` (new)
* **Do:** Pure function `landed_cost(origin, fob, hts_code, destination, weight_g) → dict`. Includes current US Section 321 / EU OSS / UK duty rules as a configurable table. Feeds `rl_pricing`.
* **Accept:** unit-tested for CN→US, CN→EU, CN→UK; de-minimis toggle honored.
* **Effort:** 2 days.

---

## Budget defaults

| Resource | Cap | Owner override |
|----------|-----|-----------------|
| LLM / cycle | $0.20 (2× prior) | `SHOPAI_LLM_BUDGET_USD_PER_CYCLE` |
| Video creative / SKU / week | $10 | `SHOPAI_VIDEO_BUDGET_SKU_WEEK_USD` |
| Ad spend daily | Owner-set | `SHOPAI_RISK_DAILY_CAP_USD` |

Creative video math: $0.07/s × ~140s = $10 / SKU / week.
10 active SKUs → $100/week creative budget.

---

## §4c.K self-check per item

Each item explicitly scores:
* **Mission fit:** ends in $ event OR blocks revenue-facing risk
* **Plumbing:capability:** 1:2 or better (capability-heavy)
* **Dollar-distance:** item → $ event within 3 commits
* **Month-tomorrow test:** YES — each contributes directly to owner's P&L

All 8 items pass.

---

## What we explicitly will NOT build (from research)

1. Keyword-stuffed Amazon listings — COSMO devalued.
2. Pure-commission-only TikTok creator tier — quality creators decline.
3. Unlabeled AI UGC for TikTok — bans +340% 2025, demonetization.
4. Micro ad-set targeting on Meta — Andromeda obsoleted.
5. 30-tool "all-in-one" replacement — stay composable.
6. Any Sora 2 integration — shut down March 24 2026.

---

## Ship cadence

- Every 3 commits → §4c.K 4-question audit
- Every commit → wide pytest regression + wave11 guard
- Every wave item → CLI surface where owner-facing
- Every adapter → offline-testable with MagicMock (dependency injection)

Next: Wave A-1 `shopify_auth` OAuth refresh harden.
