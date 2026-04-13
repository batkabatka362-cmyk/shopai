# ShopAI — Autonomous E-Commerce Intelligence System

## Quick Start

```bash
python scripts/start_shopai.py
```

This starts:
- AI system (36 phases, 12 layers, 5,357 insights per cycle)
- Shopify sync (live store data)
- Dashboard API at http://localhost:8080
- Dashboard UI at http://localhost:8082

## System Overview

**ShopAI** is a fully autonomous AI system that manages Shopify stores. It observes, thinks, decides, executes, learns, and improves — every cycle.

### Numbers
- **1,600 files** | **64K+ lines of code**
- **36 phases** per autonomous cycle
- **12/12 intelligence layers** running
- **2,100+ AI memories** (events → patterns → rules → strategies)
- **6,900+ data records** across 12 domains
- **22/28 features** fully implemented
- **42 integration tests** passing
- **41 Shopify API scopes**

## Architecture

```
BRAIN (14 modules):
  DecisionBrain → CognitiveModule(6) → DecisionEngine
  StrategyPlanner → CompetitiveIntel → ChainOfThought
  LearningLoop → RuleHealthChecker → RevenueStrategy
  StrategyExpander → MultiStoreBrain

MEMORY (3 systems, 8 backends):
  IntelligentMemory (6-layer L0→L5)
  MemoryIntelligence (4-level Event→Pattern→Rule→Strategy)
  DataArchitecture (12 domains)

ML MODELS (4):
  RL PricingAgent (Thompson Sampling)
  CustomerSegmentation (VIP/regular/new/at-risk)
  DemandForecaster (moving avg + exponential smoothing)
  ProductScorer (A/B/C/D grades)

EXECUTION (8 modules):
  SmartExecutor (simulate → dry_run → live)
  LiveExecutor (safe Shopify API calls)
  ShopifyAutomation (images, discounts, tags, content)
  MarketingAutomation (5 campaign types)
  FulfillmentAuto + ImageSourcer + StoreOptimizer
  ContinuousOptimizer (auto-fix each cycle)

ANALYTICS (8 modules):
  SEOAnalyzer + ProfitCalculator + TrendAnalyzer
  AlertSystem + HealthMonitor + Benchmarks
  ProductPerformance + ContentCalendar

INFRASTRUCTURE:
  ModelWorkerSystem (4 roles, 8 task templates)
  ToolOrchestrator (13 tools, 48 capabilities)
  DataFirstMiddleware (auto read/write)
  AutoScheduler + WebhookHandler + Notifications
  DashboardAPI + DashboardUI
  ConfigManager + RateLimiter + ErrorRecovery
  BackupSystem + AuditTrail
```

## Autonomous Cycle (36 phases)

```
data → quality → skills → competitor → brain → cognitive →
rl_pricing → segmentation → forecast → image_sourcing →
analysis → layers(12) → decisions → agents → smart_exec →
execution → intel_cycle → learning → marketing → strategy →
domain_capture → self_improvement → rule_health →
exec_promotion → strategy_expansion → continuous_optimization →
revenue_strategy → seo_analysis → profit_analysis →
social_content → email_sequences → model_workers →
tool_discovery → product_scoring → competitive_intel →
alerts → chain_of_thought → fulfillment → multi_store →
dashboard → trends → notifications → report
```

## AI Learning

```
Cycle 1:  New data → extract features → score → store as Event
Cycle 3:  3+ similar events → auto-promote to Pattern
Cycle 5:  5+ evidence patterns → auto-promote to Rule
Cycle 10: 10+ uses + 70% success → auto-promote to Strategy

Failures: 3+ similar failures → auto-generate Avoidance Rule
Every decision: memory consulted BEFORE, result recorded AFTER
```

## Shopify Store Management

All executed on real Shopify via API:
- Product descriptions (AI-generated)
- SEO tags + meta tags
- Product images
- Compare-at prices (strikethrough)
- SKU generation
- Discount codes (SHOPAI10, WELCOME15, FREESHIP50)
- Blog posts + pages (FAQ, Reviews, Offers)
- Smart collections with descriptions
- URL redirects
- Customer AI-tagging
- AI scores as metafields

## Configuration

Edit `config/settings.json`:
```json
{
  "store_id": "deguar",
  "cycle_interval_seconds": 600,
  "auto_approve": false,
  "enable_live_execution": false,
  "max_shopify_calls_per_second": 2,
  "dashboard_port": 8080
}
```

## API Endpoints

```
GET  /api/status     — system status + memory stats
GET  /api/dashboard  — full dashboard data
GET  /api/cycle      — run cycle and return results
GET  /api/alerts     — recent alerts
GET  /api/report     — human-readable report
GET  /api/memory     — rules, strategies, meta
POST /api/webhook    — Shopify webhook receiver
```

## Tests

```bash
python -m pytest tests/test_intelligence_systems.py -v
# 42 tests, ~3 seconds
```

## External Services (optional)

Connect these for full capability:
- **Ollama** — local LLM models (Mistral + Qwen + LLaMA)
- **Google Ads** — paid advertising
- **Meta Ads** — Facebook/Instagram ads
- **Email service** — SMTP or Mailchimp
- **Google Analytics** — traffic analytics

## Multi-Store

```python
from core.brain.multi_store_brain import get_multi_store
ms = get_multi_store()
ms.register_store("store_1")
ms.register_store("store_2")
shared = ms.share_learning("store_1")  # Extract rules
ms.apply_learning("store_2", shared)    # Transfer knowledge
```

## Scripts

```bash
python scripts/start_shopai.py        # Start full system
python scripts/publish_content.py     # Publish content to Shopify
python scripts/optimize_store.py      # Run store optimizations
python scripts/advanced_store_setup.py # Redirects, FAQ, reviews
```
