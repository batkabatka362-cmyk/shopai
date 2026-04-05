# ShopAI — Autonomous E-Commerce Intelligence System

## ЗОРИЛГО

ShopAI бол **бүрэн бие даасан e-commerce AI систем** — хүний оролцоогүйгээр дэлгүүр ажиллуулж, ашиг олж, суралцаж, өсдөг.

### ЭЦСИЙН ЗОРИЛГО (Vision)

```
ShopAI = Хүнээс илүү ухаалаг e-commerce оператор

Хүн 1 дэлгүүр ажиллуулна      → ShopAI 100 дэлгүүр зэрэг ажиллуулна
Хүн өдөрт 8 цаг ажиллана       → ShopAI 24/7 зогсолтгүй ажиллана
Хүн 5 бүтээгдэхүүн шинжилнэ    → ShopAI 10,000 бүтээгдэхүүн шинжилнэ
Хүн алдаагаа мартна             → ShopAI НЭГ Ч алдаагаа мартахгүй
Хүн туршлагаа хуваалцахгүй      → ShopAI 100 дэлгүүрийн мэдлэг нэгтгэнэ
```

### ТОДОРХОЙ ЗОРИЛГУУД

```
Z1: АВТОНОМ АЖИЛЛАГАА
    → Хүн унтаж байхад AI дэлгүүр ажиллуулна
    → Бүтээгдэхүүн олох, нэмэх, үнэлэх, сурталчлах
    → Захиалга боловсруулах, хүргэлт хянах
    → Асуудал гарвал өөрөө шийднэ

Z2: СУРАЛЦАХ ЧАДВАР
    → Цикл бүрт ухаалаг болно
    → Амжилтыг давтана, алдааг дахиж давтахгүй
    → Pattern → Rule → Strategy автомат үүсгэнэ
    → 1000 шийдвэрийн дараа хүнээс илүү зөв шийднэ

Z3: ОЛОН ДЭЛГҮҮР
    → 1 AI = 100 дэлгүүр удирдана
    → Store A-д сурсан зүйлийг Store B-д ашиглана
    → Niche бүрт тохирсон стратеги автомат тохируулна
    → Нэг store-ийн алдааг бүх store-д түгээнэ (давтахгүй)

Z4: БОДИТ МӨНГӨ ОЛОХ
    → Зөв бүтээгдэхүүн = зарагдах бүтээгдэхүүн
    → Зөв үнэ = хамгийн их ашиг
    → Зөв маркетинг = хамгийн бага зардал, хамгийн их борлуулалт
    → Зөв inventory = мөнгө гацахгүй, дуусахгүй

Z5: БҮРЭН ХЯНАЛТ
    → Shopify store-ийн бүх тохиргоо удирдана
    → Бүтээгдэхүүн CRUD (үүсгэх, засах, устгах)
    → Үнэ автомат тохируулах
    → Collection, page, navigation удирдах
    → Theme, shipping, payment мэдээлэл хянах
    → Webhook-ээр real-time хариу үйлдэл

Z6: INTELLIGENCE ТҮВШИН
    → Data ойлгоно (зүгээр хадгалахгүй — боловсруулна)
    → Memory ашиглана (шийдвэр бүрт өмнөх туршлага хайна)
    → Pattern олно (3+ давтагдсан → дүрэм)
    → Rule үүсгэнэ (дүрэм → автомат шийдвэр)
    → Strategy бүтээнэ (олон дүрэм → стратеги)
    → Simulation хийнэ (бодит store-д нөлөөлөхгүй)
    → 4 model зэрэг ажиллана (analyze + work + create + learn)

Z7: ӨРСӨЛДӨӨНИЙ ДАВУУ ТАЛ
    → Өрсөлдөгчийг автомат хянана
    → Тэдний үнэ, бүтээгдэхүүн, стратегийг мэднэ
    → Тэднээс түрүүлж хариу үйлдэл хийнэ
    → Зах зээлийн trend-ийг бусдаас өмнө олно
```

### CORE PRINCIPLE

```
AI Intelligence = Data + Memory + Decision + Learning + Execution
Model alone = хангалтгүй
System = жинхэнэ ухаан
Зорилго = хүнээс илүү сайн бизнес ажиллуулах AI
```

---

## СИСТЕМИЙН БҮТЭЦ

```
shopai/
├── core/                            ← СИСТЕМИЙН ЦӨМ
│   ├── brain/                       ← AI ТАРХИ (шийдвэр гаргах цөм)
│   │   ├── decision_brain.py        → 7 алхамт бодох процесс + intelligence integration
│   │   ├── decision_engine.py       → Memory-backed decisions (2 memory systems)
│   │   ├── memory.py                → 6-layer intelligent memory (L0→L5)
│   │   ├── learning_loop.py         → Execution→Result→Evaluate→Learn (3 systems)
│   │   ├── learning_model.py        → 4th model: patterns + rules + simulation
│   │   └── model_coordinator.py     → 3 worker + 1 learner model удирдлага
│   │
│   ├── data/                        ← 12 DOMAIN DATA ARCHITECTURE ← ШИНЭ
│   │   └── architecture.py          → 12 domain store: product, marketing, action,
│   │                                   result, decision, feedback, experiment,
│   │                                   feature, knowledge, system, tool_usage,
│   │                                   simulation. Feature extraction, scoring,
│   │                                   auto-tagging, action→result tracking
│   │
│   ├── memory/                      ← НЭГДСЭН САНАХ ОЙ
│   │   ├── unified_memory.py        → 8 memory backend = 1 interface
│   │   └── intelligence.py          → 4-LEVEL MEMORY HIERARCHY ← ШИНЭ
│   │                                   Event(L0)→Pattern(L1)→Rule(L2)→Strategy(L3)
│   │                                   Auto-promotion, failure intelligence,
│   │                                   meta memory, memory pruning
│   │
│   ├── intelligence_cycle.py        ← 10-STAGE AI LOOP ← ШИНЭ
│   │                                   Data→Filter→Feature→Memory→Decision→
│   │                                   Execution→Result→Evaluation→Learning→Update
│   │
│   ├── autonomous/                  ← АВТОНОМ УДИРДЛАГА
│   │   ├── controller.py            → 15+ phase autonomous cycle
│   │   ├── layer_dispatcher.py      → 12 layer → autonomous cycle руу холбосон
│   │   └── agent_dispatcher.py      → 7 agent → brain decisions руу холбосон
│   │
│   ├── system/                      ← СИСТЕМ ДЭМЖЛЭГ
│   │   ├── llm_adapter.py           → Ollama/OpenAI/Anthropic нэгдсэн
│   │   ├── task_queue.py            → Dependency graph execution
│   │   ├── shared_memory.py         → Live namespace store (TTL)
│   │   ├── adaptive_skills.py       → 22 skill, Bayesian scoring
│   │   ├── shopify_manager.py       → Shopify store бүрэн API
│   │   └── realtime_monitor.py      → Live store хяналт
│   │
│   ├── ai/                          ← AI ЧАДВАРУУД
│   │   ├── reasoning.py             → LLM direct reasoning
│   │   ├── experience.py            → Permanent knowledge DB
│   │   ├── external_tools.py        → Web search, scraping, research
│   │   ├── competitor_monitor.py    → Real competitor price scanning
│   │   └── self_improver.py         → Self-analysis, mistake detection
│   │
├── execution/                       ← ГҮЙЦЭТГЭЛ
│   ├── action_executor.py           → Shopify API actions (CRUD, pricing)
│   └── smart_executor.py            → УХААЛАГ ГҮЙЦЭТГЭЛ ← ШИНЭ
│                                       3 mode: simulate/dry_run/live
│                                       Risk-based mode selection
│                                       Simulation → Score → Memory → Learn
│   │
│   ├── auth/                        → Shopify OAuth (24h auto-refresh)
│   ├── intelligence/                → 39 intelligence module
│   ├── orchestrator/                → MainOrchestrator (legacy, 10 files)
│   ├── learning/                    → Learning engine + outcome tracker
│   └── [30+ legacy modules]         → Bridge, chaining, events, etc.
│
├── data_pipeline/                   ← DATA УРСГАЛ
│   ├── store/                       → SQLite DB, multi-store, sync, data provider
│   ├── ingestion/api/               → GraphQL (шинэ) + REST (fallback) API clients
│   └── tracking/                    → Event collector (ML training data)
│
├── engines/                         ← 131 ENGINE (ажлын нэгжүүд)
│   ├── pricing/                     → Үнийн бодлого
│   ├── inventory/                   → Нөөцийн удирдлага
│   ├── product_research/            → Winning product хайлт
│   ├── customer_segmentation/       → Хэрэглэгч ангилал
│   └── [127 more engines]           → Бүгд registry-д бүртгэлтэй
│
├── layers/                          ← 12 LAYER (engines бүлэглэсэн)
│   ├── data_layer/                  → Data collection engines
│   ├── analysis_layer/              → Analysis engines
│   ├── product_layer/               → Product engines
│   ├── pricing_layer/               → Pricing engines
│   ├── customer_layer/              → Customer engines
│   ├── marketing_layer/             → Marketing engines
│   ├── sales_layer/                 → Sales engines
│   ├── operations_layer/            → Operations engines
│   ├── financial_layer/             → Financial engines
│   ├── intelligence_layer/          → Intelligence engines
│   ├── execution_layer/             → Execution engines
│   └── scaling_layer/               → Scaling engines
│
├── agents/                          ← 7 AGENT (plan→execute→evaluate)
│   ├── product/                     → Product sourcing + optimization
│   ├── marketing/                   → Campaign planning + execution
│   ├── content/                     → Content + image management
│   ├── finance/                     → Pricing + profitability
│   ├── operations/                  → Inventory + fulfillment
│   ├── customer/                    → Segmentation + retention
│   └── research/                    → Market + competitor research
│
├── execution/                       ← ГҮЙЦЭТГЭЛ
│   ├── action_executor.py           → propose → approve → execute
│   ├── content/ai_writer.py         → AI content generation
│   └── shopify/                     → Product creator, updater
│
├── models/                          ← LLM WRAPPERS
│   ├── mistral/                     → Analyzer role
│   ├── qwen/                        → Worker role
│   ├── llama/                       → Creative role
│   └── inference/                   → Ollama backend
│
├── tools/                           ← TOOL ADAPTERS (13)
│   ├── adapters/shopify.py          → Shopify commerce
│   ├── adapters/google_ads.py       → Google Ads
│   └── [11 more adapters]           → Email, SMS, Analytics, etc.
│
├── api/server.py                    ← HTTP + Webhook server
├── cli.py                           ← CLI tool
└── tests/                           ← 530+ tests
```

---

## DATA УРСГАЛ (Бүтэн Pipeline)

```
                    SHOPIFY STORE
                         │
                         ▼ GraphQL API (costs included)
                    ┌─────────┐
                    │ SQLite   │ ← products, orders, customers
                    │ Database │ ← sync history, analytics snapshots
                    └────┬────┘
                         │
                         ▼ SyncService
                ┌────────────────────┐
                │  UNIFIED MEMORY    │ ← 8 backends, 1 interface
                │                    │
                │  SharedMemory ──── │ → live namespace data (TTL)
                │  BrainMemory ───── │ → 6-layer (L0→L5)
                │  Experience ────── │ → permanent knowledge DB
                │  CrossCache ────── │ → engine-to-engine sharing
                │  Persistent ────── │ → long-term key-value
                │  DataArchitecture  │ → 12 domain data store ← ШИНЭ
                │  MemoryIntel ───── │ → 4-level hierarchy ← ШИНЭ
                │  IntelCycle ────── │ → 10-stage AI loop ← ШИНЭ
                └────────┬──────────┘
                         │
            ┌────────────▼────────────┐
            │     DECISION BRAIN      │
            │                         │
            │  1. OBSERVE  → state    │
            │  2. DIAGNOSE → problems │
            │  3. OPPORTUNITIES       │
            │  4. CONSULT MEMORY      │
            │     └→ retrieve best    │
            │     └→ retrieve fails   │
            │     └→ retrieve rules   │
            │  5. DECIDE              │
            │     └→ DecisionEngine   │
            │     └→ ModelCoordinator │
            │  6. VALIDATE            │
            │  7. ACTION PLAN         │
            └────────────┬────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   ┌─────────┐    ┌───────────┐    ┌───────────┐
   │ 5 Core  │    │ 12 Layers │    │ AI        │
   │ Engines │    │ 131 Engines│    │ Reasoning │
   └────┬────┘    └─────┬─────┘    └─────┬─────┘
        └───────────────┼────────────────┘
                        ▼
               ┌────────────────┐
               │ ACTION EXECUTOR │
               │ propose→approve │
               │ →execute        │
               └───────┬────────┘
                       │
               ┌───────▼────────┐
               │ 7 AGENTS       │
               │ plan→execute   │
               │ →evaluate      │
               └───────┬────────┘
                       │
               ┌───────▼────────┐
               │ LEARNING LOOP  │
               │                │
               │ evaluate (1-5) │
               │ success → reinforce │
               │ failure → rule      │
               │ memory update       │
               └───────┬────────┘
                       │
                       ▼
                 NEXT CYCLE
                (илүү ухаалаг)
```

---

## AUTONOMOUS CYCLE (15+ Phase)

```
Phase 1:    DATA            → Shopify sync → SQLite → UnifiedMemory
Phase 1a:   DATA QUALITY    → validate, score, clean (100/100)
Phase 1b:   BRAIN           → observe → diagnose → decide → plan
Phase 1c:   COMPETITOR      → scan 5 products → price comparison
Phase 2:    ANALYZE         → 5 core engines (77 insights)
Phase 2b:   LAYERS          → 12 layers, 131 engines (5,300+ insights)
Phase 3:    DECIDE          → brain decisions + engine results → actions
Phase 3b:   AGENTS          → 7 agents dispatched by domain
Phase 4:    EXECUTE         → ActionExecutor (pending)
Phase 4a:   SMART EXEC      → SmartExecutor: simulate → score → learn (3/cycle)
Phase 4b:   INTEL CYCLE     → 10-stage loop × 3 categories
Phase 5:    LEARN           → evaluate → memory update → rules
Phase 5b:   DOMAIN CAPTURE  → fill all 12 data domains
Phase 6:    IMPROVE         → self-analysis → strategy adjust

Duration: ~0.54 seconds per cycle
```

---

## 4 MODEL ARCHITECTURE

```
WORKERS (зэрэг, real-time):
  Mistral   → ANALYZER  (evaluate, score, decide)
  Qwen      → WORKER    (calculate, process)
  LLaMA     → CREATIVE  (content, descriptions)

LEARNER (background, тусад):
  Learning Model → pattern detection, rule generation, simulation
  → ХЭЗЭЭ Ч execution хийхгүй
  → Зөвхөн system сайжруулна
```

---

## MEMORY SYSTEM (2 Systems, 4+6 Layers)

### IntelligentMemory (6 Layer — brain/memory.py)
```
L0: Raw buffer     → шүүгдээгүй data орно
L1: Filtered       → чанар муу → bad_data руу (устгахгүй!)
L2: Features       → margin, price_tier, has_images extract
L3: Scored         → 1-5 оноо + auto-tag
L4: Patterns       → 3+ давтагдсан → pattern
L5: Rules          → pattern → actionable rule (prefer/avoid)
```

### MemoryIntelligence (4 Level — memory/intelligence.py) ← ШИНЭ
```
Event(L0)     → raw observations with features+action+result+score
Pattern(L1)   → 3+ similar events auto-grouped (coarse feature matching)
Rule(L2)      → 5+ evidence patterns → prefer/avoid rules
Strategy(L3)  → 10+ uses + 70% success → decision strategies

Promotion: automatic after each memory creation
Success tracking: decisions that score >= 3.5 credit used rules
Failure intelligence: 3+ similar failures → avoidance rule auto-generated
Meta memory: use_count, success_count, last_used tracking
Pruning: unused events older than 30 days auto-deleted
```

### DataArchitecture (12 Domains — data/architecture.py) ← ШИНЭ
```
product      → product attributes, margins, performance
marketing    → campaigns, channels, content performance
action       → things the system DID (price changes, launches)
result       → what HAPPENED after an action
decision     → choices made with context + reasoning
feedback     → external signals (quality issues, alerts)
experiment   → smart execution simulations with hypotheses
feature      → extracted AI signals from each cycle
knowledge    → learned rules stored as domain knowledge
system       → cycle performance metrics (latency, insights)
tool_usage   → which engines used, success rates
simulation   → predictions vs actuals tracking
```

---

## INTELLIGENCE CYCLE (10 Stage — intelligence_cycle.py) ← ШИНЭ

```
Stage 1:  DATA        → raw input enters
Stage 2:  FILTER      → noise removed
Stage 3:  FEATURE     → raw → AI signals
Stage 4:  MEMORY      → consult past experience (REQUIRED)
Stage 5:  DECISION    → choose action based on memory (REQUIRED)
Stage 6:  EXECUTION   → do it (simulate/dry_run/live)
Stage 7:  RESULT      → capture what happened
Stage 8:  EVALUATION  → score the outcome (1-5)
Stage 9:  LEARNING    → extract patterns/insights
Stage 10: UPDATE      → update memory for next cycle

Rules:
  data → decision directly    = FORBIDDEN
  features → REQUIRED before memory
  memory → REQUIRED before decision
  evaluation → REQUIRED after execution
  learning → REQUIRED after evaluation
```

---

## SMART EXECUTOR (execution/smart_executor.py) ← ШИНЭ

```
3 MODES:
  SIMULATE  → estimate outcome, no real action (default)
  DRY_RUN   → validate everything, stop before API
  LIVE      → execute on real Shopify

MODE SELECTION (risk-based):
  Low confidence (< 0.4)     → always simulate
  No past data               → always simulate
  High risk action            → need 3+ past successes for dry_run
  Past failures for action    → always simulate
  Proven low-risk             → can promote to dry_run

Every execution (even simulated):
  → Memory: record in MemoryIntelligence
  → Data: record in DataArchitecture (action→result)
  → Learning: feed to LearningLoop
  → Failure: auto-record for avoidance rule generation
```

---

## LEARNING SYSTEM

```
CYCLE БҮРТ:
  Execution → Result → Evaluate (score 1-5)
  
  Score >= 4: SUCCESS
    → pattern reinforce
    → rule success_count ↑
    → strategy promotion check
    → "do more of this"
  
  Score <= 2: FAILURE  
    → root cause analysis
    → MemoryIntelligence.record_failure()
    → repeated 3+? auto-avoidance rule
    → decision engine penalty
  
  Memory update → Next cycle: rules + strategies ашиглана
  
  3 SYSTEMS ЗЭРЭГ СУРНА:
    IntelligentMemory  → L3 scored decisions, pattern detection
    MemoryIntelligence → 4-level promotion, failure intelligence
    DataArchitecture   → action→result tracking (96% attach rate)
```

---

## ОДООГИЙН ТООН ҮЗҮҮЛЭЛТ

```
Engines:            131 registered, 0 failures
Layers:             12/12 (all running)
Agents:             7/7 (all dispatching)
LLM Models:         3 installed (Mistral + Qwen + LLaMA)
Memory backends:    8 unified
  - IntelligentMemory:  456+ memories (430E → 15P → 10R → 1S)
  - DataArchitecture:   1,796+ records across 12 domains
  - Result attach rate: 96%
Skills:             22 adaptive
Tests:              530+
Store:              deguar (15 products, 100/100 data quality)
Cycle time:         0.54 seconds
Insights:           5,321 per cycle
Smart executions:   3 per cycle (simulated)
Competitor scans:   5 products per cycle
Intelligence cycles: 3 per cycle (all memory-informed)
Auto-generated:     10 rules, 1 strategy, 58 promotions
Avg memory score:   3.31 (climbing with each cycle)
```
