# ShopAI — AI-Powered Shopify Operator

ShopAI is an autonomous AI system that operates Shopify stores using local AI models (Mistral, Qwen, LLaMA) through a modular engine architecture.

## System Overview

| Metric | Count |
|--------|-------|
| Engines | 2,498 |
| Core Modules | 24 |
| Intelligence Modules | 7 |
| Domain Logic | 10 |
| Agents | 6 |
| Workflows | 6 |
| API Endpoints | 12 |
| Tests | 102 (100% pass) |

## Architecture

```
User → CLI / API / Dashboard / Webhooks
  │
  ├── Orchestrator
  │     ├── Agents (6) → decide which engine to run
  │     ├── Task Router → direct engine execution
  │     └── Workflows (6) → multi-engine business flows
  │
  ├── Engines (2,498) — each runs 4-step pipeline:
  │     Analyze (Mistral) → Execute (Qwen) → Enhance (LLaMA) → Validate (Mistral)
  │
  ├── Intelligence (7 modules):
  │     Pricing · Recommendations · Email · SEO · Content · Forecasting · Shopify
  │
  ├── Bridges (5):
  │     Agent-Engine · Pipeline · Execution · Workflow · Shopify
  │
  └── Infrastructure:
        Events · Telemetry · Cache · Rate Limiter · Scheduler · Plugins
```

## Quick Start

```bash
# Clone and setup
git clone https://github.com/batkabatka362-cmyk/shopai.git
cd shopai

# Install dependencies
pip install -r requirements.txt

# Run
PYTHONPATH=. python main.py

# Dashboard
PYTHONPATH=. python dashboard.py --live

# API server
PYTHONPATH=. python -c "from api import ShopAIServer; ShopAIServer().start()"

# Tests
PYTHONPATH=. python tests/run_tests.py
```

## Docker

```bash
# Start ShopAI + Ollama
docker-compose up -d

# Pull AI models
docker exec -it shopai-ollama-1 ollama pull mistral
docker exec -it shopai-ollama-1 ollama pull qwen2.5
docker exec -it shopai-ollama-1 ollama pull llama3.1
```

## Configuration

Copy `.env.example` to `.env` and configure:

```env
SHOPAI_SHOPIFY_URL=your-store.myshopify.com
SHOPAI_SHOPIFY_KEY=shpat_xxxxxxxxxxxx
SHOPAI_OLLAMA_URL=http://localhost:11434
```

## API Endpoints

```
GET  /api/health          System health check
GET  /api/engines         List all 2498 engines
POST /api/task            Run engine: {"task_type": "pricing", "params": {...}}
POST /api/agent           Run via agent: {"agent": "product_agent", "task": "pricing", "data": {...}}
POST /api/workflow        Run workflow: {"workflow": "product_launch", "data": {...}}
POST /api/webhook/shopify Receive Shopify webhooks (13 event types)
POST /api/batch           Batch process multiple items
POST /api/analyze         Learning analysis
```

## Intelligence Modules

### Pricing Intelligence
- Demand curve estimation from sales history (log-linear regression)
- Competitor response strategy (price index, position, undercut analysis)
- A/B price test analysis with statistical significance
- Price elasticity estimation

### Product Recommendations
- Collaborative filtering (Jaccard similarity)
- Content-based filtering (category, price, tags)
- Frequently bought together (association rules)
- Cart cross-sell (complementary categories)

### Email Intelligence
- Subject line scoring (0-100) with power word detection
- 6 automated flows: welcome, abandoned cart, post-purchase, win-back, browse abandonment, VIP
- Send time optimization per customer timezone

### SEO Intelligence
- Page-level audit (0-100) with specific fixes
- Keyword difficulty estimation (0-100)
- Content gap analysis vs competitors

### Content Generator
- Product descriptions with headline, body, bullets, meta
- Platform-specific ad copy (Facebook, Google, Instagram, TikTok)
- Email content with subject options and body sections
- SEO blog post outlines

### Forecasting
- 5 algorithms: SMA, WMA, exponential smoothing, linear trend, seasonal
- Auto method selection
- 95% confidence intervals
- Revenue and demand specific forecasts

### Shopify Formatter
- Product JSON for Shopify Admin API
- Liquid template snippets
- Responsive email HTML
- Metafield formatting

## Shopify Webhooks

13 event types auto-trigger engines:

| Event | Engines Triggered |
|-------|------------------|
| orders/create | analytics, inventory, customer_analytics |
| orders/cancelled | inventory, refund_processing |
| products/create | product_selection, seo, product_description |
| products/update | pricing, inventory |
| customers/create | customer_segmentation, email_marketing |
| checkouts/update | cart_recovery |

## Workflows

| Workflow | Steps | Description |
|----------|-------|-------------|
| product_launch | 6 | select → price → content → seo → email → social |
| customer_retention | 4 | segment → churn predict → personalize → email |
| inventory_restock | 4 | forecast → check stock → predict → procure |
| marketing_campaign | 6 | audience → target → content → ads → campaign → track |
| seo_optimization | 5 | research → audit → optimize → content → links |
| pricing_optimization | 4 | analyze → review → dynamic price → discount |

## AI Models

| Role | Model | Purpose |
|------|-------|---------|
| Analyzer | Mistral | Data analysis, scoring, decisions |
| Worker | Qwen | Task execution, structured output |
| Creative | LLaMA | Content enhancement, creative copy |
| Validator | Mistral | Quality assurance, output validation |

Models connect automatically via Ollama when available. Without Ollama, SmartExecutor provides computed results using real business algorithms.

## Project Structure

```
shopai/
├── engines/          # 2,498 modular engines
├── core/             # 24 core modules
│   ├── orchestrator/ # Main orchestrator + routers
│   ├── intelligence/ # 7 intelligence modules
│   ├── step_logic/   # SmartExecutor + 10 domain logics
│   ├── bridge/       # 5 bridges (agent, pipeline, execution, workflow, shopify)
│   ├── events/       # Event bus (22 event types)
│   ├── telemetry/    # Distributed tracing + metrics
│   ├── learning/     # Feedback store + learning engine
│   └── ...           # config, plugins, scheduler, rate_limiter, etc.
├── models/           # AI model wrappers + inference backends
├── data_pipeline/    # Ingestion, processing, feature engineering
├── api/              # REST API server (12 endpoints)
├── tests/            # 102 tests (unit + integration + intelligence)
├── dashboard.py      # Terminal dashboard
├── Dockerfile        # Docker deployment
└── docker-compose.yml
```

## License

MIT
