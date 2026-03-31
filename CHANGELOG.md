# Changelog

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
