# Changelog

## v3.0.0 (2026-05-17)

### Empire-AGI: Cross-store learning + full operator surface

**AGI orchestration stack (Phase 9 + 10)**
- 3-layer AGI: per-store world model, decision-time RAG retrieval, cost-aware model router (PRs #230/#231/#232)
- `pending_actions.store_id` column + idempotent ALTER TABLE migration (PR #239)
- Thread-local `active_store` context + enqueue auto-fill (PR #243); autonomous loop wraps `run_cycle` (PR #244)
- v2 AGI guardrail — engines REFUSE on unambiguous-negative signal (PRs #245, #247, #250); env-var opt-in per engine

**Cross-store transfer workflow (end-to-end)**
- `shopai transfer sources --to B` — rank fleet stores by transferable surface area (PR #260)
- `shopai transfer suggest --from A --to B` — cross-store recommender (PR #242)
- `shopai transfer apply --dry-run` — preview transfer before enqueueing (PR #262)
- `shopai transfer apply` — enqueue PENDING action on target store, closes suggest→action loop (PR #254)
- `shopai transfer history` — audit trail of past transfers (PR #265)
- `shopai transfer outcomes` — measure whether transfers paid off on target (PR #257)
- `scripts/transfer_demo_seed.py` — synthetic seed for end-to-end live verification (PR #246)

**Engine-level fleet diagnostics**
- `shopai engine summary <engine>` — per-engine drilldown (PR #234)
- `shopai engine guardrail [--recent N]` — v2 state + block events (PRs #249, #253)
- `shopai engine fleet <engine>` — one engine × all stores (PR #259)
- `shopai engine compare <a> <b>` — head-to-head fleet comparison (PR #263)
- `shopai engine ranking` — fleet-wide leaderboard by outcome score (PR #264)

**Operator situational awareness**
- `shopai world-model show <store>` — per-store snapshot incl. transfers section (PRs #230, #241, #266)
- `shopai world-model fleet` — multi-store snapshot view (PR #251)
- `shopai store fleet` — fleet stats summary (PR #233)
- `shopai daily-brief` — cron-able morning rollup incl. transfer activity (PRs #238, #258)
- `shopai approvals show <id> --with-context` — action + similar past decisions (PR #237)
- `shopai memory-recall --engine X [--store S]` — RAG retrieval inspector (PRs #231, #261)

**Architecture**
- `core/transfer_narrative.py` — single source of truth for transfer narrative format/parse/SQL pattern (PR #268)
- `core.world_model._section_transfers` — narrative-based transfer detection per store
- Empire-AGI workflow: `sources → suggest → dry-run → apply → review → history → outcomes`

**Stats**
- 23+ PRs in the empire-AGI rollup
- Full cross-store learning loop: discover → preview → execute → audit → measure outcomes

## v2.0.0 (2026-03-31)

### Full Autonomous Mode

**New Intelligence Modules**
- AdsIntelligence: campaign ROAS, budget optimization, creative scoring, targeting
- AnalyticsIntelligence: funnel analysis, traffic sources, sessions, attribution
- ABFramework: statistical A/B testing with auto-winner declaration
- ChatAI: 10-intent customer chat (order status, FAQ, recommendations)
- MultiChannel: Google Merchant + Meta + TikTok product sync
- AutomationLoop: closed-loop event → analyze → decide → execute → track
- AutonomousOperator: one command runs entire store operation

**System Improvements**
- 7-factor product scoring (margin, demand, competition, shipping, rating, reviews, price_point)
- OutcomeTracker: decision → outcome → winning patterns → learning
- RevenueTracker: action → revenue → ROI tracking
- DataIntegrity: strict product/customer validation, flow integrity
- AlertSystem: 8 default e-commerce rules with cooldown
- ResultHistory: persistent run tracking with trend detection
- AutoPilot: daily automated store cycle
- Performance Benchmark suite

**Stats**
- 2,498 engines, 15 intelligence modules, 116 tests (100% pass)
- 300/300 stress test, 0 crashes, 0 import errors
- Autonomous cycle: 0.017s, Quick check: 0.045s

## v1.0.0 (2026-03-31)

### Initial Release

**Core System**
- 2,498 modular engines with 4-step pipeline (Analyze → Execute → Enhance → Validate)
- 24 core modules fully wired into orchestrator
- 6 domain agents (product, marketing, customer, operations, analytics, content)
- 6 business workflows (product launch, retention, restock, campaign, SEO, pricing)
- 5 bridges (agent-engine, pipeline, execution, workflow, Shopify)

**Intelligence (11 modules)**
- Pricing: demand curves, A/B testing, competitor response, elasticity
- Recommendations: collaborative filtering, cross-sell, frequently bought together
- Email: subject scoring (0-100), 6 automation flows, send time optimization
- SEO: page audit (0-100), keyword difficulty, content gap analysis
- Content: product descriptions, ad copy, email content, blog outlines
- Forecasting: 5 algorithms (SMA, EMA, linear, seasonal), confidence intervals
- Shopify Formatter: API JSON, Liquid templates, email HTML, metafields
- AutoDS: dropship scoring, supplier selection, price monitoring
- Visual Content: product photography briefs, social media specs, banner designs
- Financial: unit economics, LTV/CAC analysis, break-even, profit waterfall
- Competitor: price tracking, threat assessment, opportunity detection

**Infrastructure**
- REST API (12 endpoints) with Shopify webhook support (13 event types)
- Web dashboard (browser-based, real-time)
- Interactive CLI (conversational interface)
- Terminal dashboard (live mode)
- Report generator (daily/weekly)
- Docker + docker-compose with Ollama GPU support
- GitHub Actions CI (Python 3.11 + 3.12)

**Quality**
- 102 tests (unit + integration + intelligence), 100% pass
- 1,500 stress test runs, 0 crashes
- Configurable logging (SHOPAI_LOG_LEVEL)
- Error intelligence with auto-diagnosis
- System health monitoring with auto-recovery

**AI Models**
- Mistral (analyzer), Qwen (worker), LLaMA (creative)
- Auto-connect to Ollama when available
- SmartExecutor computed fallback with real business algorithms
- 10 domain logic modules covering 100% of engines
