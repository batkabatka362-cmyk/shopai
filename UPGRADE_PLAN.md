# ShopAI Upgrade Plan — Roadmap to Autonomous Intelligence

## Одоогийн байдал (2026-04-04)

```
Codebase:       2,158+ files | 264K+ LOC
Engines:        131 registered, 5 core + 12 layers running
Layers:         12 loaded, connected to autonomous cycle
Agents:         7 loaded, connected via AgentDispatcher
Models:         3 LLM (Mistral + Qwen + LLaMA via Ollama)
Memory:         5 backends unified (UnifiedMemory)
Brain:          6-layer memory, DecisionEngine, LearningLoop, ModelCoordinator
Store:          deguar (15 products, 90/100 health, 0 orders)
Cycle:          1.7s, 284 insights per cycle
Tests:          530+
Auth:           OAuth 24h auto-refresh
API:            GraphQL (primary) + REST (fallback)
```

---

## ХИЙГДСЭН АЖЛУУД ✅

### Phase A: Data Foundation
| # | Ажил | Статус | Файл |
|---|------|--------|------|
| A1 | GraphQL API migration | ✅ DONE | `data_pipeline/ingestion/api/shopify_graphql.py` |
| A2 | Event tracking system | ✅ DONE | `data_pipeline/tracking/event_collector.py` |
| A3 | Data quality pipeline | ⬜ TODO | — |
| A4 | Historical data collection | ⬜ TODO | — |

### System Consolidation
| # | Ажил | Статус | Файл |
|---|------|--------|------|
| S1 | UnifiedMemory (5→1) | ✅ DONE | `core/memory/unified_memory.py` |
| S2 | LayerDispatcher (12 layers) | ✅ DONE | `core/autonomous/layer_dispatcher.py` |
| S3 | AgentDispatcher (7 agents) | ✅ DONE | `core/autonomous/agent_dispatcher.py` |
| S4 | ModelCoordinator wired | ✅ DONE | `core/brain/model_coordinator.py` → `decision_brain.py` |

### Brain Intelligence
| # | Ажил | Статус | Файл |
|---|------|--------|------|
| B1 | 6-layer IntelligentMemory | ✅ DONE | `core/brain/memory.py` |
| B2 | DecisionEngine (memory-backed) | ✅ DONE | `core/brain/decision_engine.py` |
| B3 | LearningLoop (failure intel) | ✅ DONE | `core/brain/learning_loop.py` |
| B4 | LearningModel (4th model) | ✅ DONE | `core/brain/learning_model.py` |
| B5 | DecisionBrain (7-step think) | ✅ DONE | `core/brain/decision_brain.py` |
| B6 | AdaptiveSkills (22 skills) | ✅ DONE | `core/system/adaptive_skills.py` |
| B7 | SelfImprover | ✅ DONE | `core/ai/self_improver.py` |
| B8 | ExperienceAccumulator | ✅ DONE | `core/ai/experience.py` |

### Execution
| # | Ажил | Статус | Файл |
|---|------|--------|------|
| E1 | ActionExecutor (propose→exec) | ✅ DONE | `execution/action_executor.py` |
| E2 | AI Writer (descriptions) | ✅ DONE | `execution/content/ai_writer.py` |
| E3 | Shopify OAuth | ✅ DONE | `core/auth/shopify_auth.py` |
| E4 | Webhook server | ✅ DONE | `api/server.py` |
| E5 | CLI tool | ✅ DONE | `cli.py` |
| E6 | External tools (web search) | ✅ DONE | `core/ai/external_tools.py` |

---

## ДАРААГИЙН АЖЛУУД (Priority Order)

### P1: БОДИТ DATA ЦУГЛУУЛАХ (Яаралтай)
**AI суралцахад бодит data хэрэгтэй. 0 захиалга = 0 суралцах боломж.**

| # | Ажил | Impact | Файл |
|---|------|--------|------|
| P1.1 | Data quality pipeline | HIGH | `data_pipeline/quality/validator.py` |
| P1.2 | Competitor price scraping | HIGH | `core/ai/competitor_monitor.py` |
| P1.3 | Price history tracking | MED | `data_pipeline/tracking/` (exists) |
| P1.4 | Store analytics dashboard data | MED | `data_pipeline/analytics/` |

### P2: REAL ML MODELS (Формул → Бодит ML)
**Одоогийн engines формул ашигладаг. Бодит ML model-д шилжүүлэх.**

| # | Ажил | Impact | Файл |
|---|------|--------|------|
| P2.1 | RL pricing agent | CRITICAL | `models/rl/pricing_agent.py` |
| P2.2 | Customer segmentation ML | HIGH | `models/ml/customer_segmentation.py` |
| P2.3 | Demand forecasting | HIGH | `models/ml/demand_forecast.py` |
| P2.4 | Product scoring (learned) | MED | `models/ml/product_scorer.py` |

### P3: EXECUTION EXCELLENCE
**AI шинжлэхээс гадна ХИЙХ ёстой.**

| # | Ажил | Impact | Файл |
|---|------|--------|------|
| P3.1 | A/B testing framework | HIGH | `core/system/ab_testing.py` |
| P3.2 | Marketing automation | HIGH | `execution/marketing/auto_campaign.py` |
| P3.3 | Order fulfillment auto | MED | `execution/fulfillment/auto_fulfill.py` |
| P3.4 | Product image sourcing | HIGH | `execution/content/image_sourcer.py` |

### P4: BRAIN UPGRADE
**AI тархийг гүнзгий болгох.**

| # | Ажил | Impact | Файл |
|---|------|--------|------|
| P4.1 | Long-term strategy planner | HIGH | `core/brain/strategy_planner.py` |
| P4.2 | Multi-store intelligence | CRITICAL | `core/brain/multi_store_brain.py` |
| P4.3 | Competitive intelligence | HIGH | `core/brain/competitive_intel.py` |
| P4.4 | Chain of thought reasoning | MED | `core/brain/reasoning_chain.py` |

### P5: LAYER + ENGINE САЙЖРУУЛАЛТ
**12 layer-аас 2 л ажиллаж байна. Бүгдийг ажиллуулах.**

| # | Ажил | Impact | Файл |
|---|------|--------|------|
| P5.1 | Fix engine input formats | CRITICAL | `core/autonomous/controller.py` |
| P5.2 | Layer error handling | HIGH | `core/autonomous/layer_dispatcher.py` |
| P5.3 | All 131 engines real data | HIGH | Engine-үүдийн input mapping |
| P5.4 | Tool auto-registration | MED | `tools/registry.py` |

---

## ЯАРАЛТАЙ ДАРААЛАЛ

```
ОДОО:
├── P5.1  Fix engine input formats (12 layer → 12 ажиллана)
├── P1.1  Data quality pipeline
└── P3.4  Product image sourcing

ДАРАА:
├── P2.1  RL pricing agent
├── P3.1  A/B testing framework
└── P1.2  Competitor monitoring

УДАХГҮЙ:
├── P4.1  Strategy planner
├── P2.2  Customer segmentation ML
├── P3.2  Marketing automation
└── P2.3  Demand forecasting

ИРЭЭДҮЙ:
├── P4.2  Multi-store intelligence
├── P4.3  Competitive intelligence
├── P2.4  Product scoring
└── P4.4  Reasoning chain
```

---

## KEY PRINCIPLE

```
Data → Learn → Decide → Act → Measure → Learn More

AI цикл бүрт ухаалаг болно.
Бодит data байхгүй бол ML ажиллахгүй.
Алдаа = хамгийн сайн багш.
Хүнээс илүү AI = system, model биш.
```
