# CLAUDE.md

Энэ файл нь Claude Code (болон бусад code agent)-д ShopAI repo дээр ажиллахад
өгөх заавар юм. Agent шинэ session эхлүүлэх бүрт эхлээд үүнийг унш.

---

## 1. ЗОРИЛГО (Mission)

ShopAI бол **бүрэн бие даасан (autonomous) e-commerce AI** — Shopify дэлгүүрийг
хүний оролцоогүйгээр ажиллуулж, суралцаж, **бодит мөнгө олно**.

Агентын хувьд энэ нь дараах зүйлүүдийг хийх ёстой гэсэн үг:

- **Z4 — Бодит мөнгө олох** хамгийн чухал. Code change бүр дараах асуултад
  хариулах ёстой: *энэ өөрчлөлт борлуулалт нэмэх үү, ашиг нэмэх үү, зардал
  бууруулах уу, эсвэл эдгээрийг боломжтой болгох уу?* Хэрэв "үгүй" бол
  хийхгүй.
- **Z1 — Autonomous loop.** Cycle 24/7 зогсолтгүй ажиллана. Хүн зөвшөөрөл
  өгөхийг хүлээхгүй (`config/settings.json` дотор `auto_approve`, `enable_live_execution`
  тохиргоо байгаа).
- **Z2 — Суралцах.** Event → Pattern → Rule → Strategy pipeline нь memory-д
  үргэлж бичигдэх ёстой. Шийдвэр гаргахаас өмнө memory-г заавал асууна.
- **Z3 — Multi-store.** Нэг store-д сурсан rule-ийг бусдад автоматаар
  түгээнэ (`core/multi_store/`).
- **Z5 — Бүрэн Shopify хяналт.** Product / price / collection / content /
  discount / webhook бүхнийг API-р удирдана (`execution/shopify/`,
  `data_pipeline/ingestion/api/`).

Дэлгэрэнгүй vision-ийг `ARCHITECTURE.md` дахь *ЗОРИЛГО* хэсгээс харна уу.

---

## 2. АРХИТЕКТУР (шинээр орсон agent-д)

```
main.py                 → CoreOrchestrator().run_cycle()
cli.py                  → shopai store add / configure / sync / run
dashboard.py            → Terminal dashboard (--live for watch mode)
api/server.py           → HTTP API (port 8080)
scripts/start_shopai.py → Full stack: daemon + API + dashboard
scripts/run_daemon.py   → 24/7 autonomous loop

core/
  core_orchestrator.py      ← central brain, 14-phase cycle
  brain/                    ← DecisionBrain, StrategyPlanner, LearningLoop
  memory/                   ← IntelligentMemory (L0-L5) + MemoryIntelligence
  intelligence/             ← 7 domain modules (pricing, email, seo, …)
  orchestrator/             ← engine routing, agent→engine bridge
  bridge/                   ← shopify_bridge, shopify_connector
  auth/shopify_auth.py      ← OAuth 2026+ with auto-refresh
  multi_store/              ← cross-store rule sharing
  autonomous/controller.py  ← decides when to act vs wait

execution/
  shopify/product_creator.py, product_updater.py
  store_configurator.py     ← one-shot store setup (collections, discounts, email…)
  content/publisher.py      ← blog posts, pages

engines/                    ← ~2,500 modular engines (domain-specific skills)
data_pipeline/              ← Shopify REST + GraphQL ingestion, feature eng.
models/                     ← Ollama wrappers (Mistral/Qwen/Llama) + fallbacks
tests/                      ← pytest — 100+ tests, must stay green
```

### Autonomous cycle (36 phase)
`data → quality → brain → cognitive → rl_pricing → segmentation → forecast →
layers(12) → decisions → smart_exec → learning → marketing → strategy →
revenue_strategy → seo_analysis → profit_analysis → dashboard → report`

Мөнгө олох гинжин хэлхээ нь: `rl_pricing` + `revenue_strategy` +
`profit_analysis` + `marketing` хэсгүүд дээр төвлөрсөн — эндээс эхлэн
шалга.

### Learning pipeline
```
Cycle  1: Event үүснэ
Cycle  3: 3+ адил Event → Pattern
Cycle  5: 5+ evidence Pattern → Rule
Cycle 10: 10+ хэрэглэгдсэн + 70% success → Strategy
Failures: 3+ адил алдаа → Avoidance Rule (автомат)
```

---

## 3. ЯАЖ АЖИЛЛУУЛАХ ВЭ

### Анхны setup

```bash
pip install -r requirements.txt
cp .env.example .env
# .env дотор SHOPAI_SHOPIFY_URL, SHOPAI_SHOPIFY_CLIENT_ID,
# SHOPAI_SHOPIFY_CLIENT_SECRET (эсвэл SHOPAI_SHOPIFY_KEY) бөглөнө

python cli.py config check   # бүх орчны хувьсагчийг шалгана
```

### Ганц cycle

```bash
PYTHONPATH=. python main.py
```

### 24/7 autonomous

```bash
python scripts/start_shopai.py        # daemon + API + dashboard хамтдаа
python scripts/run_daemon.py          # зөвхөн loop
```

### Dashboard

```bash
PYTHONPATH=. python dashboard.py --live
# HTTP UI:   http://localhost:8082
# HTTP API:  http://localhost:8080
```

### Docker

```bash
docker compose up -d
docker compose logs -f shopai-daemon
```

### Test

```bash
PYTHONPATH=. pytest tests/ -x
PYTHONPATH=. python tests/run_tests.py             # бүгдийг
PYTHONPATH=. pytest tests/test_intelligence_systems.py -v
```

---

## 4. АГЕНТЫН АЖЛЫН ДҮРМҮҮД

Шинэ өөрчлөлт оруулах бүрт:

1. **Зорилгод нийцэж байна уу шалга.** Шинэ feature нь Z1–Z7 (дээрх)-ийн
   аль нэгийг гүйцэтгэж байгаа эсэхийг өөрөөсөө асуу. Үгүй бол хийхгүй.
2. **Одоо байгаа module-ийг эхлээд уншина.** `engines/`, `core/`,
   `execution/` дотор адилхан зорилготой ~2,500 engine/module бий.
   Шинэ файл үүсгэхээс өмнө `grep` + `glob`-оор хайлт хий.
3. **Test заавал бичнэ.** `tests/` folder дээр pytest convention ашиглана
   (файл нэр `test_*.py`). Өөрчлөлт хийсэн module-т test нэм, эсвэл
   одоо байгаа test-ийг шинэчил.
4. **Shopify API дуудлагын rate limit-ийг баримтал.**
   `max_shopify_calls_per_second=2` (`config/settings.json`). Шинэ дуудлага
   `core/bridge/shopify_connector.py`-ээр л дамжуул.
5. **Мөнгө шууд нөлөөлөх үйлдлийг хамгаал.** `enable_live_execution=false`
   үед бүх Shopify write нь dry-run байх ёстой. SmartExecutor-ийн
   `simulate → dry_run → live` үе шатыг алгасаж болохгүй.
6. **Secrets хадгалахгүй.** `.env`, `vault/`, `data/*.db` git-д орохгүй
   (`.gitignore`-оор хаасан). Shopify token, OAuth secret-ийг config/settings.json
   эсвэл repo-д hard-code хийхгүй.
7. **Learning pipeline-г алгасахгүй.** Шинэ шийдвэр гаргадаг хэсэг нэмбэл
   үр дүнг `core/memory/memory_intelligence.py`-р event болгож бичиж,
   цаашдын learning-д ашиглана.

### Git workflow

- Branch: `claude/<slug>`  (одоогийн session: `claude/update-shop-ai-docs-dVyQc`)
- Commit message: "why"-д төвлөрсөн 1-2 өгүүлбэр.
- PR гаргахаас өмнө хэрэглэгчээс асуу (автоматаар гаргахгүй).

---

## 5. LLM / MODEL ТОХИРГОО

Орон нутгийн Ollama-г эхэлж үзнэ, амжилтгүй бол remote провайдерт шилжинэ:

```
analyze   → Mistral       (data analysis, scoring)
work      → Qwen 2.5      (structured output, execution)
create    → Llama 3.x     (creative content)
validate  → Mistral       (QA, output validation)
```

Ollama байхгүй үед `SmartExecutor` дотор real business algorithm-ууд
(Thompson Sampling, moving average, Jaccard...) fallback болж ажиллана —
систем LLM-гүйгээр ч mathematical intelligence-тэй үлдэнэ.

Remote fallback chain:
```
OPENAI_API_KEY      → gpt-4o-mini
ANTHROPIC_API_KEY   → claude-haiku-4-5-20251001
```

---

## 6. МАШ ЧУХАЛ ФАЙЛУУД

| Файл | Учир |
|------|------|
| `config/settings.json` | Runtime toggle-ууд (auto_approve, enable_live_execution, cycle interval) |
| `.env.example` | Хэрэгтэй orchestration хувьсагчид |
| `core/core_orchestrator.py` | Үндсэн brain, 14 phase-ийг энд тодорхойлдог |
| `core/brain/decision_brain.py` | Шийдвэр гаргах central entry point |
| `core/memory/` | Бүх learning → зөвхөн энд л хадгална |
| `core/bridge/shopify_connector.py` | Shopify API дуудлагын нэг цэг |
| `scripts/start_shopai.py` | Prod-style бүх төрлийн launcher |
| `ARCHITECTURE.md` | Дэлгэрэнгүй vision + phase үе шат |

---

## 7. БАЙХГҮЙ БОЛГОХ ЗҮЙЛҮҮД (Don't)

- Шинэ orchestrator / brain / memory үүсгэхгүй — одоо байгааг өргөтгө.
- Shopify API-г engine/execution дотроос шууд дуудахгүй — `shopify_connector`-ээр.
- Production Shopify store дээр `enable_live_execution=true`-г зөвшөөрөлгүй асаахгүй.
- Test-ийг `--no-verify` эсвэл skip-ээр алгасахгүй.
- Mongolian + English доктентуудыг задалж алдалахгүй — одоо байгаа
  стиль (ARCHITECTURE.md, README_SHOPAI.md)-ийг үргэлжлүүл.
