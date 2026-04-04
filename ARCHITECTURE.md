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
│   │   ├── decision_brain.py        → 7 алхамт бодох процесс
│   │   ├── decision_engine.py       → Memory-backed structured decisions
│   │   ├── memory.py                → 6-layer intelligent memory (L0→L5)
│   │   ├── learning_loop.py         → Execution→Result→Evaluate→Learn
│   │   ├── learning_model.py        → 4th model: patterns + rules + simulation
│   │   └── model_coordinator.py     → 3 worker + 1 learner model удирдлага
│   │
│   ├── memory/                      ← НЭГДСЭН САНАХ ОЙ
│   │   └── unified_memory.py        → 5 memory backend = 1 interface
│   │
│   ├── autonomous/                  ← АВТОНОМ УДИРДЛАГА
│   │   ├── controller.py            → 7 phase autonomous cycle
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
│   │   └── self_improver.py         → Self-analysis, mistake detection
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
                │  UNIFIED MEMORY    │ ← 5 backends, 1 interface
                │                    │
                │  SharedMemory ──── │ → live namespace data (TTL)
                │  BrainMemory ───── │ → 6-layer (L0→L5)
                │  Experience ────── │ → permanent knowledge DB
                │  CrossCache ────── │ → engine-to-engine sharing
                │  Persistent ────── │ → long-term key-value
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

## AUTONOMOUS CYCLE (7 Phase)

```
Phase 1:   DATA        → Shopify sync → SQLite → UnifiedMemory
Phase 1b:  BRAIN       → observe → diagnose → decide → plan
Phase 2:   ANALYZE     → 5 core engines (77 insights)
Phase 2b:  LAYERS      → 12 layers, 131 engines (207+ insights)
Phase 3:   DECIDE      → brain decisions + engine results → actions
Phase 3b:  AGENTS      → 7 agents dispatched by domain
Phase 4:   EXECUTE     → ActionExecutor → Shopify API
Phase 5:   LEARN       → evaluate → memory update → rules
Phase 6:   IMPROVE     → self-analysis → strategy adjust

Duration: ~1.7 seconds per cycle
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

## MEMORY SYSTEM (6 Layer)

```
L0: Raw buffer     → шүүгдээгүй data орно
L1: Filtered       → чанар муу → bad_data руу (устгахгүй!)
L2: Features       → margin, price_tier, has_images extract
L3: Scored         → 1-5 оноо + auto-tag
L4: Patterns       → 3+ давтагдсан → pattern
L5: Rules          → pattern → actionable rule (prefer/avoid)

Bad data: устгагдахгүй → тусад нь хадгалагдана → analyze хийгдэнэ
```

---

## LEARNING SYSTEM

```
CYCLE БҮРТ:
  Execution → Result → Evaluate (score 1-5)
  
  Score >= 4: SUCCESS
    → pattern reinforce
    → strategy weight ↑
    → "do more of this"
  
  Score <= 2: FAILURE  
    → root cause analysis
    → repeated 3+? "STOP this approach"
    → rule generate
    → decision engine update
  
  Memory update → Next cycle: rules ашиглана → илүү сайн шийдвэр
```

---

## ОДООГИЙН ТООН ҮЗҮҮЛЭЛТ

```
Engines:        131 registered
Layers:         12 (all loaded, 2 running)
Agents:         7 (all loaded, 2 dispatching)
LLM Models:     3 installed (Mistral + Qwen + LLaMA)
Memory:         5 backends unified
Skills:         22 adaptive
Tests:          530+
Store:          deguar (15 products, 90/100 health)
Cycle time:     1.7 seconds
Insights:       284 per cycle
```
