# Codex Research Memo: Shopify + ShopAI

Last verified: 2026-04-27
Prepared for: Codex + Claude Code shared context
Language: English so this file can be reused directly by coding agents
Constraint: Research only. No code was changed while preparing this file.

## Executive read

- Shopify's 2026 direction is clearly AI-native commerce, not just classic ecommerce tooling.
- The real control plane is becoming `Markets -> Catalogs -> Shop surfaces -> Checkout/Shop Pay -> Agent tooling`.
- ShopAI already has many strong building blocks, but most of them still look like generic ecommerce automation rather than Shopify-native 2026 automation.
- The best next move is not "more features everywhere". It is aligning ShopAI to Shopify's own newest primitives first.

## Operating thesis

If we want ShopAI to feel first-class on Shopify in 2026, the system should think in this order:

`Market -> Product/Catalog -> Ads/Content -> Funnel -> Retention -> Agent loop`

That matches both Shopify's current platform direction and the way your repo is already organized.

## 1. Market

### Shopify now

- On February 11, 2026, Shopify reported FY2025 revenue of `$11.556B`, GMV of `$378.441B`, free cash flow of `$2.007B`, `>14%` US ecommerce market share, `36%` international revenue growth, `96%` B2B GMV growth, and `62%` Shop Pay GMV growth. Shopify also says it serves millions of businesses in `175+` countries.  
  Sources: [FY2025 results](https://www.shopify.com/investors/press-releases/shopifys-standout-2025-the-launchpad-for-a-new-era-of-commerce-in-2026), [financial PDF](https://s27.q4cdn.com/572064924/files/doc_financials/2025/q4/Shopify_Investor_Press_Release_Q4-25_FINAL.pdf)
- Shopify Markets is no longer just "countries/regions". Shopify now models markets as customer sets with parent markets and submarkets, inheritance, and market-specific catalogs, currencies, themes, duties, taxes, domains, and languages.  
  Source: [Markets overview](https://help.shopify.com/en/manual/markets-new/overview)
- In the new Markets model, all plans can customize product catalogs, currencies, domains/languages, and duties/taxes per market. Theme customization and checkout/account customization are more plan-dependent.  
  Source: [Markets overview](https://help.shopify.com/en/manual/markets-new/overview)
- Market catalogs are now operationally important: merchants can set per-catalog currency, percentage price adjustments, and direct `Price` plus `Compare-at price` values inside the Shopify admin.  
  Source: [Creating catalogs to use with Markets](https://help.shopify.com/en/manual/markets-new/catalogs)
- Retail markets matter too. Shopify POS can run different catalogs and pricing rules by location/market, with plan and POS version constraints.  
  Sources: [Retail markets overview](https://help.shopify.com/en/manual/sell-in-person/markets/overview), [Winter '26 Editions](https://www.shopify.com/editions/winter2026)

### ShopAI today

- `core/adapters/shopify/markets.py` already reads Shopify markets and locales.
- `engines/market_research/flow.py` already thinks in market size, gaps, trends, and verdicts.
- `engines/international_expansion/flow.py` already thinks in market scoring, currency pricing, localization gaps, shipping, and recommended markets.
- `engines/international_expansion/market_evaluator.py` already has an expansion scoring layer.

### Biggest gap

- ShopAI already understands "market research", but Shopify's real 2026 market abstraction is now much closer to `commercial operating context` than simple geography.
- The missing bridge is a market operating model that joins Shopify Markets data with margin, catalog visibility, pricing, taxes, shipping, localization, and campaign readiness.
- In other words: ShopAI can reason about expansion, but it still needs to reason with Shopify's live market and catalog objects as first-class inputs.

### Recommended Claude Code backlog

1. Build a market scorecard that merges Shopify Markets data with ShopAI's TAM/gap/trend outputs.
2. Add per-market profitability simulation: price, compare-at price, shipping, duties, taxes, and gross margin.
3. Add market readiness scoring that checks localization, catalog completeness, policies, payments, and logistics before expansion.
4. Treat market inheritance and catalog assignment as deployable configuration, not just research output.

## 2. Products

### Shopify now

- Sidekick is no longer just Q&A. It can guide merchants, generate content, build admin apps, handle tasks like data analysis, order management, and product editing, and save repeated prompts as reusable skills.  
  Sources: [Sidekick overview](https://help.shopify.com/en/manual/shopify-admin/productivity-tools/sidekick), [Generating content with Sidekick](https://help.shopify.com/en/manual/shopify-admin/productivity-tools/sidekick/generate-content)
- Sidekick app generation is available on Grow, Advanced, and Plus. Basic stores only had temporary access through April 2026. Generated apps are admin-only and cannot reach themes, checkout, or customer account apps.  
  Source: [Generating apps with Sidekick](https://help.shopify.com/en/manual/shopify-admin/productivity-tools/sidekick/generate-apps)
- Winter '26 pushes product operations further toward AI assistance: Sidekick Pulse, custom app generation, workflow generation, analytics report generation, theme edits, and product/SEO-oriented prompt flows.  
  Source: [Winter '26 Editions](https://www.shopify.com/editions/winter2026)
- Product structure is getting broader: Shopify highlights `2048 variants per product`, unlisted products, compare-at prices in catalogs, and improved bundles.  
  Source: [Winter '26 Editions](https://www.shopify.com/editions/winter2026)
- Unlisted products are strategically important. They stay sellable by direct URL but are hidden from Shopify Catalog, search, recommendations, and sitemaps. Shopify explicitly positions them for things like warranty add-ons, bundle-only items, and early-access products.  
  Source: [Product details page](https://help.shopify.com/en/manual/products/details/product-details-page)
- Shopify Bundles is free and available on all plans, but it still has practical constraints such as component and variant limits.  
  Source: [Shopify Bundles](https://help.shopify.com/en/manual/products/bundles/shopify-bundles)
- Shopify's Standard Product Taxonomy is now core infrastructure. Shopify says all products should be assigned a standard category because it affects tax accuracy, channel readiness, metafields, and discoverability.  
  Source: [Shopify's Standard Product Taxonomy](https://help.shopify.com/en/manual/products/details/product-category)
- On the agent side, Shopify now exposes a `Catalog API` for cross-merchant product discovery and a `Storefront MCP` surface for store-specific product, cart, and policy interactions.  
  Sources: [Catalog API](https://shopify.dev/docs/api/catalog-api), [Storefront MCP server](https://shopify.dev/docs/apps/build/storefront-mcp/servers/storefront), [Winter '26 Editions](https://www.shopify.com/editions/winter2026)

### ShopAI today

- `core/system/shopify_manager.py` already covers store, products, collections, pages, themes, menus, orders, customers, inventory, and audit functions.
- `data_pipeline/pipelines/product_pipeline.py` already normalizes and enriches Shopify product data.
- `models/ml/product_scorer.py` already scores products by margin, demand potential, imagery, and description quality.
- `execution/shopify/product_creator.py` and `execution/shopify/product_updater.py` already cover product CRUD operations.
- `core/ai/product_finder.py` already does product discovery from web-search style inputs.
- `engines/product_selection/flow.py`, `engines/product_optimization/flow.py`, and `engines/product_variant/flow.py` already provide selection, optimization, and variant-generation pipelines.

### Biggest gap

- ShopAI's product stack is still centered on classic CRUD, scoring, and optimization. Shopify is moving toward catalog-aware merchandising, taxonomy-aware data quality, market-aware pricing, and agent-assisted product operations.
- There is no obvious first-class layer yet for:
  - unlisted/private-offer product strategy
  - market-specific catalog merchandising
  - category/taxonomy completion as a prerequisite for ads and discovery
  - agentic product discovery using Shopify-native catalog tools

### Recommended Claude Code backlog

1. Add a taxonomy-completion layer so every product has usable Shopify category and category-metafield coverage.
2. Build market-aware catalog operations: publish, exclude, price, and compare-at price by market.
3. Add explicit support for unlisted products, bundle-only add-ons, and early-access/private-offer products.
4. Replace generic product discovery where useful with Shopify-native `Catalog API` or store-specific `Storefront MCP` search flows.

## 3. Ads and content

### Shopify now

- Shop Campaigns is a Shopify-native customer acquisition program. Merchants target new or lapsed customers in the US or Canada and pay acquisition fees only when conversion happens.  
  Source: [Shop Campaigns](https://help.shopify.com/en/manual/online-sales-channels/shop/shop-campaigns)
- Shop Campaigns ad inventory now spans three surfaces: ads on Shop, ads on Shopify Product Network, and ads on other platforms.  
  Source: [Understanding Shop Campaigns](https://help.shopify.com/en/manual/online-sales-channels/shop/shop-campaigns/understanding-campaigns)
- Shopify explicitly lists third-party Shop Campaign placements across `Bing`, `ChatGPT`, `Facebook`, `Google`, `Instagram`, `Microsoft Monetize`, `Pinterest`, `Snapchat`, and `X`. Campaign economics are framed around `CAC` and `ROAS`, not generic impression-buying.  
  Source: [Understanding Shop Campaigns](https://help.shopify.com/en/manual/online-sales-channels/shop/shop-campaigns/understanding-campaigns)
- Shopify Product Network is becoming a real merchandising and acquisition surface. Merchants can place third-party seller products into search, collections, thank-you pages, order-status pages, and Shopify Messaging emails.  
  Source: [Shopify Product Network customer experience](https://help.shopify.com/en/manual/promoting-marketing/shopify-product-network/customer-experience)
- Product Network has hard constraints that matter for implementation: US-only visibility, English-only seller products, policy-link dependence, shipping-only fulfillment, and limitations around checkout customizations and unsupported product types.  
  Sources: [Understanding Shop Campaigns](https://help.shopify.com/en/manual/online-sales-channels/shop/shop-campaigns/understanding-campaigns), [Shopify Product Network customer experience](https://help.shopify.com/en/manual/promoting-marketing/shopify-product-network/customer-experience)
- Shopify Messaging now covers both email and SMS marketing directly in admin, plus automations.  
  Source: [Email and SMS marketing with Shopify Messaging](https://help.shopify.com/en/manual/promoting-marketing/create-marketing/shopify-messaging)
- Shopify Forms is not just lead capture. It can trigger automations, create customer segments, collect marketing consent, and hand subscribers into Shopify Messaging.  
  Source: [Shopify Forms app](https://help.shopify.com/en/manual/promoting-marketing/create-marketing/forms-app)
- Customer segments are dynamic, rule-based, and ShopifyQL-backed. This is important because Shopify-native acquisition and lifecycle tools increasingly expect segment-aware targeting.  
  Source: [Customer segmentation](https://help.shopify.com/en/manual/customers/customer-segmentation?locale=en-US)
- Winter '26 reinforces the same direction: Product Network, Shop Campaigns expansion to the online store, Messaging SMS, better segmentation flows, and Forms auto-translation.  
  Source: [Winter '26 Editions](https://www.shopify.com/editions/winter2026)

### ShopAI today

- `execution/content/ai_writer.py` already generates descriptions, titles, ad copy, email subjects, and meta descriptions.
- `core/intelligence/content_generator.py` already generates product descriptions, ad copy, email content, urgency, and social proof.
- `core/intelligence/visual_content_ai.py` and `execution/content/social_content.py` already produce visual and platform-specific social content specs.
- `execution/content/publisher.py` and `execution/content/distributor.py` already handle publishing/distribution to Shopify and social channels.
- `data_pipeline/ingestion/api/ads_api.py` already fetches campaign data from Meta, Google Ads, and TikTok.
- `execution/marketing/campaign_manager.py` already handles campaign status, pause/resume, budget updates, and metrics.
- `execution/marketing/auto_campaign.py` already generates campaign templates and estimated revenue.
- `core/adapters/ads/*` and `core/adapters/ads_spy/*` already give you external ad and creative intelligence building blocks.

### Biggest gap

- ShopAI is already strong at external ad ops and copy generation, but Shopify itself is increasingly turning owned surfaces into acquisition surfaces.
- The repo currently looks more prepared for `Meta/Google/TikTok + content generation` than for `Shop Campaigns + Product Network + Messaging + Forms + Segments`.
- `CampaignManager` is mostly an external campaign operations layer, and `MarketingAutomation` is a template generator. The missing piece is a Shopify-native acquisition orchestrator.

### Recommended Claude Code backlog

1. Add a Shop-native acquisition layer for Shop Campaign setup, CAC strategy, eligibility checks, and reporting.
2. Add Product Network readiness checks: policies, supported product types, payout/commission expectations, and placement strategy.
3. Build a segment-aware messaging layer that connects Forms, Segments, Messaging, and campaign content.
4. Create a content system that is aware of `market`, `segment`, `product category`, and `funnel stage`, not just platform.

## 4. Funnel

### Shopify now

- Shop Pay remains one of Shopify's strongest funnel assets. Shopify claims up to `50%` better conversion versus guest checkout, at least `10%` better performance than other accelerated checkouts, a `5%` lift from simple presence, access to `150M+` global shoppers, and a `9%` higher repurchase rate for buyers using the Shop app.  
  Source: [Shop Pay](https://www.shopify.com/shop-pay)
- Shop Pay Installments is available for eligible stores in the US, Canada, and the UK, and Shopify positions it as a conversion-rate and AOV lever.  
  Source: [Shop Pay Installments](https://help.shopify.com/en/manual/payments/shop-pay-installments)
- Shopify's abandoned checkout flow is moving into Shopify Messaging. The new automation gives more flexibility and design control, but opting in is a one-way move. It applies only to Online Store and Buy Button channels, not POS, Shop, or third-party sales channels.  
  Source: [Opt in to the new abandoned checkout automation](https://help.shopify.com/en/manual/promoting-marketing/create-marketing/migrate-abandoned-checkout)
- Shopify Flow is now a practical orchestration layer across plans, and `Send HTTP Request` is available on Grow, Advanced, and Plus. That makes native workflow-driven funnel automation more realistic than before.  
  Source: [Shopify Flow](https://help.shopify.com/en/manual/shopify-flow)
- Storefront MCP makes customer-facing shopping agents more concrete. Shopify provides store-specific catalog, cart, and policy access via per-store MCP endpoints, and standard Storefront MCP requests do not require authentication.  
  Source: [Storefront MCP server](https://shopify.dev/docs/apps/build/storefront-mcp/servers/storefront)
- Winter '26 also makes the agentic funnel story clearer: Shopify explicitly says merchants can bring shopping into AI conversations via Catalog API, Checkout MCP, and Checkout Kit for web.  
  Source: [Winter '26 Editions](https://www.shopify.com/editions/winter2026)
- Product Network introduces funnel constraints you must respect: only Shopify Payments or Shop Pay are supported there, while Apple Pay, Google Pay, manual methods, Shop Pay Installments, and Shop Cash are not supported in those flows.  
  Source: [Shopify Product Network customer experience](https://help.shopify.com/en/manual/promoting-marketing/shopify-product-network/customer-experience)

### ShopAI today

- `core/intelligence/customer_journey.py` already handles lifecycle segmentation, journey mapping, winback, landing pages, and post-purchase planning.
- `engines/conversion_tracking/funnel_analyzer.py` already analyzes funnel progression and overall conversion.
- `core/intelligence/analytics_intelligence.py` already highlights worst drop-off points and funnel recommendations.
- `engines/checkout_optimizer/flow.py` and its supporting modules already think about friction, step count, guest checkout, and field reduction.
- `engines/cart_recovery/flow.py` already models cart analysis, abandonment reasons, strategy, timing, messaging, and value estimation.
- `core/intelligence/email_intelligence.py` already has abandoned cart, post-purchase, win-back, and browse-abandonment flows.

### Biggest gap

- ShopAI already understands funnel logic conceptually, but it is not yet obviously anchored to Shopify's newest native funnel surfaces: Shop Pay, Shop, Messaging automations, Storefront MCP, Checkout MCP, and Product Network constraints.
- The repo is strong on analysis and recommendations; it is weaker on Shopify-native execution paths inside the modern Shopify funnel.

### Recommended Claude Code backlog

1. Build a native funnel scorecard that maps `awareness -> consideration -> purchase -> retention` onto Shopify events, Shop surfaces, and Shop Pay behavior.
2. Add native abandoned checkout and win-back execution paths that target Shopify Messaging and Flow, not only custom email logic.
3. Add explicit Shop Pay and Installments recommendations based on cart value, market, and device/channel context.
4. Prototype a customer-facing shopping assistant on top of `Storefront MCP` plus checkout handoff.

## Agent setup for Codex + Claude Code

### Why this matters

- Shopify now officially supports AI-tooling workflows instead of treating them as side experiments.
- Shopify's AI Toolkit is meant to help agents use docs, schemas, validation, and store operations correctly instead of guessing.
- This is the cleanest bridge between your research workflow and Claude Code implementation workflow.

### Practical setup

- Shopify says its AI Toolkit can help AI tools build with Shopify docs/API schemas/code validation and manage the store through CLI `store execute` capabilities.  
  Source: [Shopify AI Toolkit](https://shopify.dev/docs/apps/build/ai-toolkit)
- For Claude Code, Shopify's official setup command is:

```bash
claude mcp add --transport stdio shopify-dev-mcp -- npx -y @shopify/dev-mcp@latest
```

- For Codex, Shopify's official config is:

```toml
[mcp_servers.shopify-dev-mcp]
command = "npx"
args = ["-y", "@shopify/dev-mcp@latest"]
```

- For store-specific shopping agents, Shopify's Storefront MCP endpoint is:

```text
https://{shop}.myshopify.com/api/mcp
```

- For UCP catalog tools on a specific store, Shopify also exposes:

```text
https://{shop}.myshopify.com/api/ucp/mcp
```

- For cross-merchant discovery, Shopify's Catalog API requires a bearer token minted from Dev Dashboard credentials.  
  Sources: [Storefront MCP server](https://shopify.dev/docs/apps/build/storefront-mcp/servers/storefront), [Catalog API](https://shopify.dev/docs/api/catalog-api), [Shopify AI Toolkit](https://shopify.dev/docs/apps/build/ai-toolkit)

## Constraints that should stay visible

- A lot of the newest Shopify-native growth surfaces are still geography-limited, especially US-first.
- Some of the most powerful workflow and app-generation features are plan-limited.
- Product Network and Shop Campaigns have checkout and product-type limitations that can break naive automation.
- Sidekick-generated apps are admin-only, so customer-facing funnel work still needs dedicated implementation.

## Highest-leverage build order

1. Make `Markets + Catalogs + Taxonomy` the core data model.
2. Make `Shop-native acquisition` a first-class capability beside Meta/Google/TikTok.
3. Make `Shop Pay + Messaging + Flow` the primary funnel execution layer.
4. Add `Storefront MCP / Catalog API / Dev MCP` as the agent interface layer for Codex and Claude Code.

## Local repo signal map

- Market: `core/adapters/shopify/markets.py`, `engines/market_research/flow.py`, `engines/international_expansion/flow.py`
- Products: `core/system/shopify_manager.py`, `data_pipeline/pipelines/product_pipeline.py`, `models/ml/product_scorer.py`, `execution/shopify/product_creator.py`, `execution/shopify/product_updater.py`, `core/ai/product_finder.py`, `engines/product_selection/flow.py`, `engines/product_optimization/flow.py`, `engines/product_variant/flow.py`
- Ads and content: `execution/content/ai_writer.py`, `core/intelligence/content_generator.py`, `core/intelligence/visual_content_ai.py`, `execution/content/social_content.py`, `execution/content/publisher.py`, `execution/content/distributor.py`, `data_pipeline/ingestion/api/ads_api.py`, `execution/marketing/campaign_manager.py`, `execution/marketing/auto_campaign.py`, `core/adapters/ads/*`, `core/adapters/ads_spy/*`
- Funnel: `core/intelligence/customer_journey.py`, `core/intelligence/analytics_intelligence.py`, `engines/conversion_tracking/funnel_analyzer.py`, `engines/customer_journey/flow.py`, `engines/checkout_optimizer/flow.py`, `engines/cart_recovery/flow.py`, `core/intelligence/email_intelligence.py`

## 5. n8n

### Snapshot as of 2026-04-27

- n8n positions itself as a fair-code workflow automation platform that combines AI capabilities with business process automation.  
  Source: [n8n docs home](https://docs.n8n.io/)
- On the n8n release-notes page retrieved on April 27, 2026, the docs list current `stable` as `2.17.7` and current `beta` as `2.18.3`.  
  Source: [n8n release notes](https://docs.n8n.io/release-notes/)
- n8n's `queue mode` is the scale path: the docs explicitly say queue mode provides the best scalability, with Redis as the broker and separate worker processes executing workflows.  
  Source: [Queue mode](https://docs.n8n.io/hosting/scaling/queue-mode/)

### What matters most

- n8n now has a real AI-native surface, not just classic automation:
  - `AI Workflow Builder` can create, refine, and debug workflows from natural-language prompts.
  - `Chat Hub` is a centralized AI chat interface with custom agents and workflow-backed agents.
  - `Evaluations` and `human-in-the-loop` tooling are first-class features for productionizing AI workflows.  
  Sources: [AI Workflow Builder](https://docs.n8n.io/advanced-ai/ai-workflow-builder/), [Chat Hub](https://docs.n8n.io/advanced-ai/chat-hub/), [Evaluations](https://docs.n8n.io/advanced-ai/evaluations/overview/), [Human-in-the-loop](https://docs.n8n.io/advanced-ai/human-in-the-loop-tools/)
- n8n now has both sides of MCP:
  - instance-level MCP access so Claude/Codex-like clients can connect to an n8n instance
  - MCP Server Trigger for workflow-specific MCP exposure
  - MCP Client node so n8n workflows can call external MCP servers  
  Sources: [Instance-level MCP server](https://docs.n8n.io/advanced-ai/mcp/accessing-n8n-mcp-server/), [MCP Server Trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger/), [MCP Client node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcpClient/)
- n8n already has a built-in Shopify node for orders and products, and can fall back to generic HTTP requests when the built-in node is not enough.  
  Source: [Shopify node](https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.shopify/)
- For self-hosted AI proof-of-concepts, n8n ships a documented starter kit that combines self-hosted n8n with `Ollama`, `Qdrant`, and `PostgreSQL`.  
  Source: [Self-hosted AI Starter Kit](https://docs.n8n.io/hosting/starter-kits/ai-starter-kit/)

### Why n8n is relevant to ShopAI

- n8n is strongest as an orchestration shell around ShopAI, not as a replacement for ShopAI's domain logic.
- Good fits for this repo:
  - operator-facing workflows for approvals, escalations, and notifications
  - cross-system glue between Shopify, ads, CRM, email, spreadsheets, and internal tools
  - scheduled or event-driven execution around ShopAI decisions
  - exposing safe ShopAI operations to MCP clients through n8n, or calling external MCP tools from n8n
- A pragmatic architecture would let ShopAI stay the decision engine while n8n handles:
  - trigger fan-in
  - human approval gates
  - long-tail integrations
  - simple operational dashboards and workflow distribution

### Important constraints

- Instance-level MCP access is not blanket exposure. Workflows must be explicitly enabled, and connected clients see the workflows you expose.  
  Source: [Instance-level MCP server](https://docs.n8n.io/advanced-ai/mcp/accessing-n8n-mcp-server/)
- MCP on n8n is now more powerful than simple triggering: docs say it supports running existing workflows and, from `v2.13` onward, building or editing workflows. That is powerful, so access scope matters.  
  Source: [Instance-level MCP server](https://docs.n8n.io/advanced-ai/mcp/accessing-n8n-mcp-server/)
- Queue mode needs real infra discipline:
  - Redis is required
  - workers must be started separately
  - filesystem-backed binary storage is not supported in queue mode
  - distributed use expects a real database and usually Postgres  
  Source: [Queue mode](https://docs.n8n.io/hosting/scaling/queue-mode/)
- `Human-in-the-loop` is available, but you still have to decide which tools need approval and which channels are allowed to approve them.  
  Source: [Human-in-the-loop](https://docs.n8n.io/advanced-ai/human-in-the-loop-tools/)
- `Chat Hub` has real limits today: simple personal agents have limited tool selection, no file knowledge, and workflow agents require a Chat Trigger plus a streaming-enabled AI Agent node.  
  Source: [Chat Hub](https://docs.n8n.io/advanced-ai/chat-hub/)

### Best use of n8n for this repo

1. Treat n8n as the execution fabric for low-risk and cross-tool workflows.
2. Keep high-value Shopify reasoning, pricing, market logic, and funnel intelligence inside ShopAI.
3. Use n8n approvals and workflow UX to operationalize ShopAI decisions.
4. Use n8n MCP where you want an external agent to discover and run approved workflows, not to give broad raw infrastructure access.

## 6. OpenClaw (openclaw.ai)

### Snapshot as of 2026-04-27

- OpenClaw is a self-hosted gateway for AI agents that can route conversations across many chat surfaces and local control interfaces.  
  Sources: [OpenClaw docs home](https://docs.openclaw.ai/), [OpenClaw GitHub](https://github.com/openclaw/openclaw)
- The official getting-started docs currently recommend `Node 24`, support `Node 22.14+`, and use `openclaw onboard --install-daemon` as the preferred setup path.  
  Sources: [Getting started](https://docs.openclaw.ai/start/getting-started), [OpenClaw GitHub](https://github.com/openclaw/openclaw)
- On the GitHub repo page retrieved on April 27, 2026, OpenClaw showed `365k` stars and latest release `openclaw 2026.4.24` published on April 25, 2026.  
  Source: [OpenClaw GitHub](https://github.com/openclaw/openclaw)

### What matters most

- OpenClaw is a channel/gateway product first:
  - one Gateway
  - many channels
  - many agents
  - one operator control plane  
  Sources: [OpenClaw docs home](https://docs.openclaw.ai/), [Chat channels](https://docs.openclaw.ai/channels/index)
- It already supports a broad messaging surface, including `Discord`, `Google Chat`, `iMessage`/`BlueBubbles`, `Matrix`, `Microsoft Teams`, `Signal`, `Slack`, `Telegram`, `WhatsApp`, `WeChat`, `Zalo`, and more.  
  Source: [Chat channels](https://docs.openclaw.ai/channels/index)
- OpenClaw also has strong agent-runtime primitives:
  - `skills` based on AgentSkills-compatible `SKILL.md` folders
  - `mcp` mode where OpenClaw acts as an MCP server
  - `acp` mode where OpenClaw acts as an ACP server
  - `Lobster` for deterministic multi-step tool pipelines with approvals
  - `Task Flow` for durable multi-step flow orchestration
  - `doctor` and `security audit` for ops hardening  
  Sources: [Skills](https://docs.openclaw.ai/skills), [MCP](https://docs.openclaw.ai/cli/mcp), [ACP](https://docs.openclaw.ai/cli/acp), [Lobster](https://docs.openclaw.ai/tools/lobster), [Task Flow](https://docs.openclaw.ai/automation/taskflow), [Doctor](https://docs.openclaw.ai/doctor), [Security](https://docs.openclaw.ai/security)

### Why OpenClaw is relevant to ShopAI

- OpenClaw is a strong candidate for the `human/operator control surface` around ShopAI.
- Good fits for this repo:
  - route ShopAI alerts and approvals to Telegram/Slack/WhatsApp
  - let an operator query store state conversationally
  - run bounded workflows through chat instead of building custom dashboards first
  - keep a live "ops inbox" for failed automations, risky actions, and store events
- The cleanest mental model is:
  - ShopAI = commerce intelligence and action logic
  - OpenClaw = conversational gateway, approvals, routing, operator experience

### OpenClaw features that matter specifically

- `openclaw mcp serve` lets Codex, Claude Code, or another MCP client talk to OpenClaw-backed channel conversations through a single MCP server.  
  Source: [MCP](https://docs.openclaw.ai/cli/mcp)
- `openclaw acp` is different: OpenClaw acts as an ACP server and forwards work into a Gateway session. Docs explicitly distinguish this from ACP harness sessions where OpenClaw runs an external harness like Codex or Claude Code through `acpx`.  
  Source: [ACP](https://docs.openclaw.ai/cli/acp)
- `Lobster` is not just "yet another workflow file". Docs position it as a deterministic workflow shell with explicit approval checkpoints for multi-step tool sequences.  
  Source: [Lobster](https://docs.openclaw.ai/tools/lobster)
- `Task Flow` sits above detached background tasks and gives durable state, revision tracking, and multi-step flow semantics across restarts.  
  Source: [Task Flow](https://docs.openclaw.ai/automation/taskflow)
- Skills have a real precedence model, with workspace-level skills overriding broader shared or bundled ones. That makes OpenClaw usable as a customizable operator environment rather than a fixed assistant.  
  Source: [Skills](https://docs.openclaw.ai/skills)

### Important constraints

- OpenClaw's own security docs are explicit: it is a `personal assistant` trust model and `not a hostile multi-tenant security boundary`. If multiple adversarial users share one gateway, the recommended answer is separate trust boundaries.  
  Source: [Security](https://docs.openclaw.ai/security)
- Prompt injection is a first-class concern in OpenClaw's docs, and the recommended hard controls are tool policy, allowlists, approvals, and sandboxing rather than prompt-only guardrails.  
  Source: [Security](https://docs.openclaw.ai/security)
- Sandboxing is optional, not automatic. If sandboxing is off, tools run on the host. When enabled, sandboxing reduces blast radius but is not presented as a perfect boundary.  
  Source: [Sandboxing](https://docs.openclaw.ai/sandboxing)
- Third-party skills should be treated as untrusted. Docs explicitly tell operators to read them before enabling and prefer sandboxed runs for risky tools and untrusted inputs.  
  Source: [Skills](https://docs.openclaw.ai/skills)
- Pairing is important operationally: OpenClaw uses explicit owner approval for DM access and device/node joining.  
  Source: [Pairing](https://docs.openclaw.ai/pairing)

### Best use of OpenClaw for this repo

1. Use OpenClaw as the chat-native operator shell for ShopAI.
2. Put risky actions behind approvals and pair-only access.
3. Use sandboxing for any tool-enabled flows that touch untrusted content.
4. Use `MCP` when Codex/Claude should talk to OpenClaw-backed conversations.
5. Use `ACP` when OpenClaw should host or route coding-runtime sessions.

## 7. n8n vs OpenClaw for ShopAI

### Short answer

- `n8n` is better as an automation fabric and integration/orchestration layer.
- `OpenClaw` is better as an agent gateway, operator messaging layer, and approval surface.

### Clean split

- Use `n8n` for:
  - event triggers
  - workflow branching
  - app integrations
  - scheduled jobs
  - approval workflows
  - simple MCP-exposed operational workflows
- Use `OpenClaw` for:
  - Telegram/Slack/WhatsApp operator interface
  - routed agent sessions
  - conversational command surface
  - human approval at the chat edge
  - multi-agent messaging and inbox-style control
- Use `ShopAI` for:
  - Shopify-native reasoning
  - store analytics
  - pricing/product/funnel decisions
  - commerce-specific execution logic

### Recommended combined architecture

1. ShopAI computes what should happen.
2. n8n handles cross-system workflow glue and low-risk automation.
3. OpenClaw handles operator interaction, approvals, escalation, and live messaging.
4. MCP is the connective tissue when Codex/Claude need controlled access to either n8n or OpenClaw surfaces.

## Source pack

- Shopify FY2025 results, February 11, 2026: https://www.shopify.com/investors/press-releases/shopifys-standout-2025-the-launchpad-for-a-new-era-of-commerce-in-2026
- Shopify FY2025 financial PDF: https://s27.q4cdn.com/572064924/files/doc_financials/2025/q4/Shopify_Investor_Press_Release_Q4-25_FINAL.pdf
- Shopify Editions Winter '26: https://www.shopify.com/editions/winter2026
- Sidekick overview: https://help.shopify.com/en/manual/shopify-admin/productivity-tools/sidekick
- Sidekick content generation: https://help.shopify.com/en/manual/shopify-admin/productivity-tools/sidekick/generate-content
- Sidekick app generation: https://help.shopify.com/en/manual/shopify-admin/productivity-tools/sidekick/generate-apps
- Markets overview: https://help.shopify.com/en/manual/markets-new/overview
- Markets catalogs: https://help.shopify.com/en/manual/markets-new/catalogs
- Retail markets overview: https://help.shopify.com/en/manual/sell-in-person/markets/overview
- Product details page and unlisted products: https://help.shopify.com/en/manual/products/details/product-details-page
- Shopify Bundles: https://help.shopify.com/en/manual/products/bundles/shopify-bundles
- Standard Product Taxonomy: https://help.shopify.com/en/manual/products/details/product-category
- Shop Campaigns: https://help.shopify.com/en/manual/online-sales-channels/shop/shop-campaigns
- Understanding Shop Campaigns: https://help.shopify.com/en/manual/online-sales-channels/shop/shop-campaigns/understanding-campaigns
- Shopify Product Network customer experience: https://help.shopify.com/en/manual/promoting-marketing/shopify-product-network/customer-experience
- Shopify Messaging: https://help.shopify.com/en/manual/promoting-marketing/create-marketing/shopify-messaging
- Shopify Forms: https://help.shopify.com/en/manual/promoting-marketing/create-marketing/forms-app
- Customer segmentation: https://help.shopify.com/en/manual/customers/customer-segmentation?locale=en-US
- Shop Pay: https://www.shopify.com/shop-pay
- Shop Pay Installments: https://help.shopify.com/en/manual/payments/shop-pay-installments
- New abandoned checkout automation: https://help.shopify.com/en/manual/promoting-marketing/create-marketing/migrate-abandoned-checkout
- Shopify Flow: https://help.shopify.com/en/manual/shopify-flow
- Shopify AI Toolkit: https://shopify.dev/docs/apps/build/ai-toolkit
- Catalog API: https://shopify.dev/docs/api/catalog-api
- Storefront MCP server: https://shopify.dev/docs/apps/build/storefront-mcp/servers/storefront
- n8n docs home: https://docs.n8n.io/
- n8n release notes: https://docs.n8n.io/release-notes/
- n8n AI Workflow Builder: https://docs.n8n.io/advanced-ai/ai-workflow-builder/
- n8n Chat Hub: https://docs.n8n.io/advanced-ai/chat-hub/
- n8n evaluations overview: https://docs.n8n.io/advanced-ai/evaluations/overview/
- n8n human-in-the-loop: https://docs.n8n.io/advanced-ai/human-in-the-loop-tools/
- n8n instance-level MCP server: https://docs.n8n.io/advanced-ai/mcp/accessing-n8n-mcp-server/
- n8n MCP Server Trigger: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger/
- n8n MCP Client node: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcpClient/
- n8n queue mode: https://docs.n8n.io/hosting/scaling/queue-mode/
- n8n Self-hosted AI Starter Kit: https://docs.n8n.io/hosting/starter-kits/ai-starter-kit/
- n8n Shopify node: https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.shopify/
- OpenClaw GitHub: https://github.com/openclaw/openclaw
- OpenClaw docs home: https://docs.openclaw.ai/
- OpenClaw getting started: https://docs.openclaw.ai/start/getting-started
- OpenClaw chat channels: https://docs.openclaw.ai/channels/index
- OpenClaw skills: https://docs.openclaw.ai/skills
- OpenClaw pairing: https://docs.openclaw.ai/pairing
- OpenClaw MCP: https://docs.openclaw.ai/cli/mcp
- OpenClaw ACP: https://docs.openclaw.ai/cli/acp
- OpenClaw Lobster: https://docs.openclaw.ai/tools/lobster
- OpenClaw Task Flow: https://docs.openclaw.ai/automation/taskflow
- OpenClaw security: https://docs.openclaw.ai/security
- OpenClaw sandboxing: https://docs.openclaw.ai/sandboxing
- OpenClaw doctor: https://docs.openclaw.ai/doctor
