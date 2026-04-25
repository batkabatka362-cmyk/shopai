# ShopAI Market Research — 2026 Q2 Synthesis

> Compiled from 12 parallel research agents (6 for 2024-2025
> baseline + 6 for Q1-Q2 2026 deltas). Purpose: single reference
> for why `IMPLEMENTATION_PLAN_2026.md` prioritizes what it does.

## Executive summary

**The thesis:** AI agents (ChatGPT, Gemini, Perplexity, Copilot)
are becoming the top of the shopping funnel. The search engine
lost its monopoly. Shopify responded in March 2026 by making
"Agentic Storefronts" default-on across 5.6M stores — a store
that doesn't show up in AI chat is invisible to the fastest-
growing buyer segment.

Three open protocols consolidated Q3-Q4 2025:
* **ACP** (OpenAI + Stripe, Sept 2025) — ChatGPT checkout
* **AP2** (Google + 60 partners, Sept 2025) — agent payment
* **UCP** (Google NRF, Jan 11 2026) — end-to-end agent commerce
* **MCP** (Anthropic Nov 2024) — universal tool protocol

These stack: MCP for tool discovery, ACP for checkout init,
AP2 for payment authorization, UCP as wrapper.

---

## Part 1 · 2024-2025 baseline (Wave 1 research)

### Shopify platform
* REST deprecated Oct 2024; GraphQL-only for new public apps Apr 1 2025
* `productSet` (2025-01) — upsert with external ID, idempotent
* `bulkOperationRunMutation` — 5 concurrent / 100 MB / 24h
* Shopify Functions replaced Scripts (cut-off Jun 30 2026)
* Sidekick App Extensions (Winter '26 dev preview): 1s latency, 4k token, 20 tools/app
* Storefront MCP server — Python MCP client compatible

### Supplier stack
* CJ v2 API stable; TikTok Shop + Walmart outbound
* AutoDS no public API (browser-only)
* Alibaba Accio Dec 2024 (GenAI sourcing agent)
* Printify MCP server open-source, POD fallback excellent
* Temu / Shein no public API

### Ad platforms
* Meta Advantage+ unified (v24.0 Oct 2025, v25.0 Q1 2026 — legacy API dead)
* TikTok Smart+ + Symphony + Dreamina video GA
* Google Power Pack = Demand Gen + AI Max + PMax (+25-35% conv)
* AppLovin AXON self-serve Oct 2025 (referral-only, $1B run-rate)
* Sora 2 SHUT DOWN March 24 2026 — use Veo 3.1 / Kling 2.6 / Runway Gen-4
* fal.ai cheapest (30-50% vs Replicate)

### SEO / GEO
* AI Overviews 14% shopping queries (+5.6× in 4 months)
* Organic CTR −61%, paid −68% on AI-Overview SERP
* Cited brand in AI Overview = +35% clicks
* Feb 2026 Discover core update + March 2026 spam update
  (fastest ever 19.5h) + March 2026 core update emphasizing
  "information gain"
* Schema ≥3 types → +13% LLM citation
* Princeton GEO paper — authoritative quote in intro = +40%
* Perplexity Feb 2026 dropped ads; 46.5% of citations = Reddit

### Marketplaces
* Amazon Rufus (250M users), Project Amelia (seller AI), COSMO
* TikTok Shop: Tarte 6.6K affiliates, $45M / 6 months
* Walmart: 300 calls/hr Items API, underexploited channel
* Alibaba Accio: UI only; Open Platform ISV-gated

### Practitioner pain
1. Attribution broken (Meta vs Shopify vs GA4)
2. App stack bloat (15-20% of revenue)
3. Supplier price drift → oversell margin collapse
4. Creative fatigue — 50-80 creative/week now baseline
5. Amazon suspension with zero notice
6. TikTok Shop compliance chaos
7. Inventory forecasting (stockouts on winners)
8. Klaviyo flow decay

---

## Part 2 · 2026 Q1-Q2 deltas (Wave 2 research)

### Hard deadlines (non-negotiable)
| Deadline | Platform | Change |
|----------|----------|--------|
| Jan 12 2026 (past) | Meta | 7dv + 28dv attribution windows removed |
| March 31 2026 (past) | TikTok | Legacy Smart+ Campaign API sunset |
| April 1 2026 (past) | Shopify | Expiring OAuth 60min + 90d refresh required |
| April 15 2026 | Shopify | Scripts — no new development |
| June 30 2026 | Shopify | Scripts — execution stops |
| June 30 2026 | Google | Merchant Center unique MPN/SKU (no compound) |
| August 2 2026 | EU | AI Act Article 50 enforceable |
| September 2026 | Google | AI Max replaces DSA |

### Agentic commerce (highest-ROI opportunity)
* **March 24 2026** — Shopify Agentic Storefronts default-on
* 5.6M stores indexed into ChatGPT + Perplexity + Copilot
* Gemini via UCP rolling out
* Claude NOT a surface yet (Anthropic B2B-focused)
* Attribution: `orders.source_name = chatgpt | perplexity | copilot | gemini`
* Merchant needs zero code — toggle in admin
* But needs FEED HYGIENE + CHANNEL ATTRIBUTION to benefit

### AI citation data (Cory Maki, ALM Corp, NeuronWriter 2026)
* AI Overview citation share: Reddit 21%, YouTube 19%, Quora 14%
* Perplexity citation share: Reddit 46.5% (2× AI Overview rate)
* Reddit visibility +73% Oct 2025 → Jan 2026
* ChatGPT Search citation concentration: top-30 domain = 67%
* First 30% of body = 44.2% of citations lifted
* Domains with >32k referring domains 3.5× more likely cited

### Practitioner playbooks Q1-Q2 2026
* **Pilothouse Andromeda-first** (DTC Pod Feb 20 2026) — drop
  ad-set sprawl, consolidate to 1 ASC, feed creative diversity
* **Pilothouse NPV retention math** (DTC Pod Feb 6 2026) —
  cohort × survival × discount rate → CAC ceiling
* **Tarte TikTok Shop OS** — 6.6K affiliates, 23K videos/month,
  88% creator-driven GMV
* **Physicians Choice** — 2K creators / $2.4M / 28 days
* **Ridge** — 7-staff in-house desk, ~5K creator deals/year
* **Hybrid creator deal** — $250 flat + 15% commission beats
  commission-only in beauty/wellness
* **Creative velocity 1.5-3.0 per $10K weekly spend** (Flighted,
  Anchour, Admetrics 2026 benchmarks) — Andromeda rewards volume

### Tool ecosystem Q1-Q2 2026
* **Triple Whale Moby Agents** (April 2, 2026) — $82B GMV
  trained, budget reallocation + creative brief, will act
  autonomously "soon"
* **Klaviyo Composer + Customer Agent** (Spring '26) —
  full campaign from prompt; WhatsApp tier added
* **Hydrogen 2026.1** — React Router v7 + Oxygen + `/api/mcp`
* **Polar Causal Lift** — warehouse-native GeoLift
  incrementality; determinist "no scale without p<0.05"
* **Tinker** (Mar 26 2026) — Shopify's mobile AI creative
  app; consumer toy

### Killed playbooks (don't build)
1. Sora 2 integrations (shut down)
2. Keyword-stuffed Amazon listings (COSMO devalued)
3. Pure-commission TikTok creator tier (quality decline)
4. Unlabeled AI UGC on TikTok (ban +340% 2025)
5. Micro ad-set targeting on Meta (Andromeda obsoleted)
6. 30-tool all-in-one (stay composable)

### Emerging (monitor, don't build yet)
* Temu/Shein public API — no signal
* AppLovin AXON GA — still referral-only
* TikTok Shop US legal resolution — pending
* Alibaba Accio API — gated on ISV status

---

## Part 3 · Protocol cheat-sheet

### ACP (Agentic Commerce Protocol)
* Owner: OpenAI + Stripe (Sept 2025)
* Role: agent → merchant checkout
* Merchant endpoints:
  * `POST /checkout_sessions`
  * `POST /checkout_sessions/{id}/complete`
* Auth: signed Stripe `delegated_payment_token`
* Spec: github.com/stripe/agentic-commerce-protocol
* Status: live ChatGPT (Etsy, Shopify rolling)

### AP2 (Agent Payments Protocol)
* Owner: Google + 60 PSPs (Sept 2025)
* Role: payment authorization with VDCs
* Mandates: Intent, Cart, Payment (cryptographic)
* Spec: github.com/google-agentic-commerce/ap2
* Status: spec stage; PSPs implementing

### UCP (Universal Commerce Protocol)
* Owner: Google (NRF Jan 11 2026)
* Role: end-to-end agent commerce wrapper
* Stack: REST + JSON-RPC over MCP / A2A / AP2
* Spec: ucp.dev
* Status: live Etsy, Wayfair; Shopify + Target + Walmart "soon"

### MCP (Model Context Protocol)
* Owner: Anthropic (Nov 2024), now open standard
* Role: universal tool protocol
* Shopify ships `@shopify/mcp-server-storefront`
* ShopAI target: expose ourselves as MCP server

---

## Part 4 · Sources (representative; full citations in agent reports)

**Shopify:**
* shopify.com/editions/winter2026
* shopify.dev/docs/apps/build/sidekick
* shopify.dev/docs/agents/catalog
* shopify.com/news/winter-26-edition-agentic-storefronts
* shopify.dev/changelog

**Agentic commerce:**
* github.com/stripe/agentic-commerce-protocol
* github.com/google-agentic-commerce/ap2
* ucp.dev
* blog.google/products/ads-commerce/digital-advertising-commerce-2026

**Ad platforms:**
* developers.facebook.com/blog/post/2025/10/08/upcoming-asc-and-aac-mapi-deprecation-migration-options-to-advantage-plus
* conversios.io/blog/meta-attribution-window-changes-2026-fix-your-tracking
* ads.tiktok.com/business/en-US/blog/symphony-automation
* smarter-ecommerce.com/blog/en/google-ads/the-ultimate-guide-to-ai-max-for-google-search
* fal.ai/pricing
* nerdleveltech.com/openai-sora-shutdown-lessons-from-ais-most-expensive-failure

**SEO / GEO:**
* arxiv.org/html/2311.09735v3 (Princeton GEO paper)
* convertmate.io/research/geo-benchmark-2026
* ppc.land/google-ai-overviews-reduce-organic-ctr-61-paid-traffic-68
* ppc.land/googles-march-2026-core-update-is-here-and-it-follows-spam-by-just-3-days
* searchenginejournal.com/google-is-not-diminishing-the-use-of-structured-data-in-2026

**Practitioner:**
* DTC Pod episodes Feb 6 + Feb 20 2026
* triplewhale.com/blog/product-event (Moby launch)
* klaviyo.com/whats-new Spring 2026
* shortformnation.com/blog/tiktok-shop-affiliate-marketing-the-complete-2026-guide
* anchour.com/meta-ads-2026-playbook

**Regulatory:**
* artificialintelligenceact.eu/article/50
* digital-strategy.ec.europa.eu/en/news/commission-publishes-first-draft-code-practice-marking-and-labelling-ai-generated-content

---

## Part 5 · Research methodology + limits

* 6 Wave-1 agents covered 2024-2025 baseline
* 6 Wave-2 agents covered Q1-Q2 2026 deltas
* Some agents ran without live web access (knowledge-cutoff
  synthesis) — flagged "VERIFIED-BASELINE" vs "UNVERIFIED-2026"
* Any item marked UNVERIFIED must be re-checked before code
* Full agent transcripts preserved in git history

This doc is the **single source of truth** for why
`IMPLEMENTATION_PLAN_2026.md` targets what it targets.

Updated: 2026-04-20.
