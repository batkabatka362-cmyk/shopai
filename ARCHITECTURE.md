# ShopAI Architecture — Тодорхой Зорилго, Тодорхой Бүтэц

## ЗОРИЛГО

ShopAI = Бие даасан e-commerce AI.
Хүн биш. Tool биш. Бодож, шийдэж, хийж, суралцдаг систем.

## ТОДОРХОЙ ЗОРИЛГО (Priority)

```
P0: AI бодит data ойлгоно → зөв шийдвэр гаргана
P1: AI алдаанаасаа суралцана → дахиж давтахгүй
P2: AI бие даан ажиллана → хүн оролцохгүй
P3: AI олон store удирдана → мэдлэг хуваалцана
```

## БҮТЭЦ (Тодорхой)

```
shopai/
│
├── core/                        ← СИСТЕМИЙН ЦӨМ (бүгдийг удирдана)
│   ├── brain/                   ← AI ТАРХИ (нэг газар!)
│   │   ├── memory.py            → 6-layer intelligent memory
│   │   ├── decision_engine.py   → Structured decisions (memory-backed)
│   │   ├── decision_brain.py    → High-level thinking (observe→decide→plan)
│   │   ├── learning_loop.py     → Execution→Result→Evaluate→Learn
│   │   ├── learning_model.py    → 4th model: patterns, rules, simulation
│   │   └── model_coordinator.py → 3 workers + 1 learner
│   │
│   ├── system/                  ← СИСТЕМ УДИРДЛАГА
│   │   ├── orchestrator.py      → Бүх task удирдах
│   │   ├── task_queue.py        → Dependency graph execution
│   │   ├── shared_memory.py     → Бүх component хуваалцах data
│   │   ├── llm_adapter.py       → Бүх LLM нэг interface
│   │   ├── adaptive_skills.py   → Skills scoring
│   │   ├── shopify_manager.py   → Shopify бүрэн удирдлага
│   │   └── realtime_monitor.py  → Live хяналт
│   │
│   ├── ai/                      ← AI ЧАДВАРУУД
│   │   ├── reasoning.py         → LLM reasoning
│   │   ├── experience.py        → Permanent knowledge DB
│   │   ├── external_tools.py    → Web search, scraping
│   │   └── self_improver.py     → Self-analysis
│   │
│   ├── auth/                    → OAuth tokens
│   └── autonomous/              → Автоном cycle controller
│
├── data_pipeline/               ← DATA УРСГАЛ
│   ├── store/                   → SQLite DB, sync, data provider
│   ├── ingestion/api/           → GraphQL + REST API clients
│   └── tracking/                → Event collector (ML training data)
│
├── engines/                     ← 131 ENGINE (ажлын нэгжүүд)
├── layers/                      ← 12 LAYER (engines бүлэглэсэн)
├── agents/                      ← 7 AGENT (plan→execute→evaluate)
├── execution/                   ← ГҮЙЦЭТГЭЛ (Shopify дээр action хийх)
├── models/                      ← LLM WRAPPERS (Mistral/Qwen/LLaMA)
├── tools/                       ← TOOL ADAPTERS (Shopify, email, ads)
├── memory/                      ← LEGACY MEMORY (vector, long-term)
├── brain/                       ← LEGACY BRAIN (strategy, quality)
└── tests/                       ← ТЕСТҮҮД
```

## DATA УРСГАЛ (Тодорхой)

```
ОРОЛТ (Input):
  Shopify → GraphQL API → SQLite DB
  Webhooks → Event Collector
  Web Search → Market Intel

БОЛОВСРУУЛАЛТ (Processing):
  SQLite → DataProvider → SharedMemory
  SharedMemory → Brain.IntelligentMemory (L0→L5)
  IntelligentMemory → DecisionEngine.retrieve()

ШИЙДВЭР (Decision):
  DecisionEngine:
    1. Memory-оос context авна (best cases, failures, rules)
    2. Options үүсгэнэ (keep/raise/lower)
    3. Score тооцно (profit × risk × memory × rules)
    4. Best option сонгоно
    5. Memory-д бичнэ

ГҮЙЦЭТГЭЛ (Execution):
  Decision → ActionExecutor → propose → [approve] → Shopify API

СУРАЛЦАХ (Learning):
  Result → LearningLoop.learn()
    → Evaluate (score 1-5)
    → Success? reinforce pattern
    → Failure? root cause → rule generate
    → Memory update
    → Next cycle: илүү ухаалаг
```

## LOCAL AI MODELS (Тодорхой)

```
┌─────────────────────────────────────────────┐
│            MODEL COORDINATOR                 │
│                                              │
│  EXECUTION (real-time, зэрэг):              │
│    Mistral  → ANALYZER                       │
│      input: data + question                  │
│      output: score(1-10) + decision + reason │
│      when: evaluate product, check price,    │
│            validate quality                  │
│                                              │
│    Qwen → WORKER                             │
│      input: data + task                      │
│      output: calculation result              │
│      when: margin calc, demand forecast,     │
│            data processing                   │
│                                              │
│    LLaMA → CREATIVE                          │
│      input: product info + style             │
│      output: text content                    │
│      when: descriptions, ad copy, emails,    │
│            SEO titles                        │
│                                              │
│  LEARNING (background, тусад):              │
│    Learning Model (Mistral)                  │
│      input: historical aggregated data       │
│      output: patterns, rules, simulations    │
│      when: after every N cycles              │
│      ХЭЗЭЭ Ч execution хийхгүй              │
└─────────────────────────────────────────────┘
```

## MEMORY SYSTEM (Тодорхой)

```
INTELLIGENT MEMORY (brain/memory.py):
  L0: Raw data орно
  L1: Filter (quality < 2 → bad_data руу)
  L2: Features extract (margin, tier, has_images, etc.)
  L3: Scored (1-5) + tagged (high_margin, premium, etc.)
  L4: Patterns (3+ давтагдсан → pattern)
  L5: Rules (pattern → actionable rule)

  Bad data: устгагдахгүй → тусад нь → analyze хийгдэнэ

SHARED MEMORY (system/shared_memory.py):
  Namespaced: products, orders, customers, decisions, state
  TTL-based: хуучирсан data автомат устгагдана
  Context builder: task бүрт тохирсон data цуглуулна

EXPERIENCE DB (ai/experience.py):
  Product knowledge: юу зардаг, яагаад
  Decision outcomes: юу амжилттай, юу амжилтгүй
  Strategy knowledge: ямар стратеги ажилладаг
  Mistake log: юу хийхгүй байх
  Tool knowledge: ямар tool хэзээ сайн
  Market intel: зах зээлийн мэдээлэл
```

## LEARNING SYSTEM (Тодорхой)

```
CYCLE БҮРТ:
  1. Execution хийнэ
  2. Result авна
  3. Evaluate хийнэ (score 1-5)
     - profit > 0? + 1
     - conversion > 0? + 0.5
     - status = error? - 1.5
  4. Score >= 4: SUCCESS
     → pattern reinforce
     → strategy weight нэмэгдэнэ
  5. Score <= 2: FAILURE
     → root cause: missing_resource / performance / unprofitable
     → repeated 3+? "STOP using this approach"
     → rule generate → decision engine update
  6. Memory update
  7. Next cycle: rules ашиглана → илүү сайн шийдвэр

LEARNING MODEL (background):
  Historical data → analyze
  → patterns (price_tier_margin, category_concentration, etc.)
  → rules (KEEP mid pricing, DIVERSIFY categories, RESTOCK)
  → simulation (raise 10%? lower 10%? focus top5?)
  → system update (execution-г зогсоохгүй)
```

## ОДООГИЙН ДУТАГДАЛ

1. Legacy код (brain/, memory/) шинэтэй холбогдоогүй
2. Layers, Agents шинэ system-тэй integrate хийгдээгүй
3. Бодит борлуулалт 0 — AI суралцах data хязгаарлагдмал
4. Image, marketing execution дутуу
5. Зарим engine зөв data авахгүй (input format тохирохгүй)
