# CLAUDE.md

Энэ файл нь Claude Code (болон бусад code agent)-д ShopAI repo дээр ажиллахад
өгөх заавар юм. Agent шинэ session эхлүүлэх бүрт эхлээд үүнийг унш.

---

## 1. ЗОРИЛГО (Mission)

ShopAI бол **Goal-Driven Full-Cycle E-Commerce Executor** — өмчлөгч
(owner) зорилго тавина, AI бүх pipeline-ийг хүнээс хурдан, 100%
найдвартай гүйцэтгэнэ.

```
  Owner role:                 AI role:
  ───────────                 ─────────────────────────────────
  • Winner сонгох             • 1 product → Shopify live → Ads running 15 мин
  • Goal тавих (budget, niche) • 20 алхамыг determinate execute
  • Kill/Scale шийдэх          • Order webhook → ROAS track → pattern learn
  • Хүний зөн совин           • LLM дэндэж ухаантай байхаа оролдохгүй
```

Owner жишээ goal: *"Энэ Alibaba URL-д байгаа бүтээгдэхүүн-г avtods-аар
sync хийж, Shopify-д тавьж, видео хийж, Meta ads-д $20/өдөр launch
хийж, 3 өдрийн дараа ROAS<1.5 байвал auto-kill хийгээрэй."* — AI-ийн
ажил бол энэ 12 алхамыг нэг товчлуурт оруулах.

### ЯАЖ Энэ нь Revenue өгөх вэ

- **Z-money:** owner-гийн таамаглалаар winner сонгогдож, AI execution-ийн
  хурдаар олон SKU долоо хоногт launch хийгдэнэ
- **Reward signal = Shopify order webhook** — AI ROAS/CVR reading-тэй
  шийдвэр бүрийн outcome-ийг memory-д тэмдэглэнэ
- **AGI-ийн зам:** 100 SKU × 10 хэв маяг launch хийгдсний дараа
  pattern/rule/strategy pipeline автоматаар "winner looks like X" гэж
  сурна. Үүнээс өмнө "AGI" гэж бодох хэрэггүй

### Тодорхой зорилгууд (Z1-Z7)

- **Z1 — Autonomous loop:** owner goal-гүйгээр ч 24/7 daemon cycle
  хийнэ (monitoring, retention, churn prediction)
- **Z2 — Learning:** Event → Pattern → Rule → Strategy pipeline нь
  order webhook-аас ирсэн outcome-д үндэслэн promote хийнэ
- **Z3 — Multi-store:** 1 store-д сурсан rule бусдад автомат түгээнэ
- **Z4 — Revenue:** code change бүрийн асуулт: *"Энэ ROAS эсвэл CVR-ыг
  нэмэх үү, ads зардлыг багасгах уу, AOV өсгөх үү?"* Үгүй бол хийхгүй
- **Z5 — Shopify full control:** Product/price/collection/content/
  discount/webhook бүхнийг API-р
- **Z6 — Multi-platform:** Amazon, TikTok Shop руу scale (сар 5-6)
- **Z7 — Competitive edge:** ads spy + winning products automation

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

### Research First — Build Second

Шинэ feature хэрэгтэй болоход дараах эрэмбээр хай, **эцсийн сонголт л
code бичих**:

1. **Одоо байгаа adapter** — `core/adapters/` дотор хайх (~30 adapter)
2. **Public API-тай SaaS** — Stripe, Klaviyo, Meta Ads, Shopify, Twilio —
   эдгээр нь тогтсон, well-maintained
3. **Open-source Python SDK** — `pip install`-ээр шийдэгдэх бол шийд
4. **AI tools API** — Replicate, Groq, Higgsfield, Pexels — creative
   generation-д бэлэн
5. **No-code hook (Zapier/Make)** — 1-2 алхамт workflow-д ашиглаж болно
6. **Playwright browser automation** — API байхгүй үед л ашигла
7. **Scratch-аас бичих** — зөвхөн өмнөх сонголт ажиллахгүй үед

ShopAI-ийн зорилго: *orchestrate существующие tools*, reinvent биш. Нэг
adapter нэмэхэд 50 мөр, scratch бичихэд 5000 мөр — боломжтой үед
орчим орчим байгаа байгаа API ашигла.

---

## 4b. SENIOR ENGINEER DISCIPLINE

ShopAI бол хобби биш — бодит мөнгө хөдөлгөдөг автоном систем. Доорх
дүрмүүд senior AI engineer-ийн стандарт:

### A. Determinism over intelligence (95/5 rule)

LLM call хийхээсээ өмнө асуу: *"Энэ шийдвэрийг pure function болгож
чадах уу?"* Боломжтой бол LLM хэрэглэхгүй.

```
✓ Determinism:  "ROAS < 1.5 after 3 days → kill"   (1 line, 0 token)
✗ Intelligence: "Should we kill? Let me think..."   (LLM call, $0.001, 1.5s)
```

LLM-ийн зөвлөмж тохиолдохгүй газрууд: scoring, ranking, threshold check,
arithmetic, аль ч state transition. LLM зөвхөн:
- Free-form content generation (description, ad copy, email body)
- Multimodal interpretation (image → tags)
- Fuzzy classification (review sentiment) — мөн эхлээд keyword/rule-base туршиж үз

### B. Closed-loop telemetry (хамгийн чухал)

Шинэ шийдвэр гаргадаг хэсэг нэмбэл **outcome event-гүй deploy
хийхгүй**. Хэв маяг:

```python
decision = brain.decide(...)
action_id = executor.execute(decision)
# ↓ заавал ↓
memory.record_outcome(action_id, kpi="roas", value=measured_roas, source="meta_pixel")
```

Outcome event эргэн ирэхгүй бол learning pipeline статик. Code-review-ийн
гол асуулт: *"Шинэ ROAS/CVR/conversion data энд хаашаа холбогдох вэ?"*

### C. Cost / latency budget

LLM-ийн дуудлага бүрт зориулсан **cost & latency cap** байх ёстой:

| Хэрэглээ | Max cost/call | Max latency | Provider preset |
|---|---|---|---|
| Bulk classification | $0.0005 | 2s | Groq Llama 3.3 |
| Product description | $0.005 | 8s | Gemini Flash |
| Strategic reasoning | $0.05 | 30s | DeepSeek V3 |
| Cycle-blocking call | **0** | **0** | LLM-гүйгээр шийд |

Cycle бүрийн нийт LLM cost: **$0.10-аас бага** (өдөрт $14, сард $420
хүчирхэг). Үүнээс хэтэрвэл архитектурыг эргэн харах.

### D. Idempotency + Retry safety

Shopify/Meta Ads/AutoDS-руу бичсэн ямар ч action нь дахин гүйцэтгэхэд
**duplicate state үүсгэхгүй** байх ёстой:

```
✓ "Set product 12345 price to $29.99"     (idempotent — same end state)
✗ "Increment campaign budget by $10"      (NOT idempotent — runs N times)
```

Counter / increment / decrement-ийг external API дээр **бүү ашигла**.
Үргэлж "set X to absolute value Y" хэлбэрийг ашигла.

### E. Failure isolation (cycle never dies)

Adapter / phase / engine-ийн сэлэн бүхэнд:
- `try/except` орчим, exception-ийг log + record + continue
- Тэр нэг adapter-ийн алдаа cycle-ийг зогсоохгүй
- Pattern: `core/autonomous/controller.py` дахь `_record(phase, exc)` хэлбэр
- Circuit-breaker rate (3 алдаа дараалсан → 5 мин үл оролдох)

### F. Schema-first data exchange

Engine ↔ engine, adapter ↔ adapter дамжих data **dict шиддэг
free-form биш**. Ашигла:
- TypedDict эсвэл pydantic BaseModel `core/contracts/`-д
- Контракт өөрчлөгдвөл version bump (`v1`, `v2`)
- Test нь contract-ыг шалгана, implementation-ыг биш

### G. Money-on-the-line code path: paranoid mode

`enable_live_execution=true` тохиолдолд бичигдэх ямар ч action:
1. Pre-flight check — credentials valid, store reachable
2. Dry-run — request body log хийгдэх (бодит API дуудалгүй)
3. Confirm — `auto_approve` эсвэл human approval
4. Backup — `backup_before_shopify_changes` дуудна (current state snapshot)
5. Execute — actual write
6. Verify — post-write read-back, баталгаажуулна
7. Record — outcome event memory-д

Алхам алгасах нь = production алдаа. Жишээ pattern: `execution/smart_executor.py`.

### H. Observability: every action explainable

Cycle бүрт `result.narrative` гарах ёстой — хүний унших боломжтой:
- Аль option сонгосон, яагаад
- Аль memory-ийг ашигласан (rule_id-ийг trace-д)
- Outcome score хэрхэн тооцсон

`logger.info("Decision: X (because Y, score=Z, sources=[A,B])")` хэлбэрийг
дагана. "Magic" decision гарахгүй — бүх шийдвэр replayable.

### I. Test discipline

- **Contract test**: adapter-ийн public API-ыг шалгах, implementation бус
- **Property test**: invariant-ыг шалгах (`hypothesis` library)
- **Integration test**: бодит pipeline run, mock-toi external API
- **Snapshot test**: AI prompt + response-ийг snapshot-д хадгал, regression
- **Smoke test**: `python main.py` 1 cycle алдаагүй гүйх

Test mock-чилбал тэр mock жинхэнэ adapter-ийн contract-тэй үргэлж тэнцэх
ёстой — fake-ыг бодит code-той sync-д барих.

### J. PR / commit стандарт

Commit message: *яагаад* (1 sentence) + *яаж* (1-2 sentence). Жишээ:

```
Auto-connect ShopifyBridge on first fetch so data actually loads

CoreOrchestrator instantiated ShopifyBridge with credentials but never
called connect(), so fetch_products always raised ShopifyBridgeUnavailable
even with valid SHOPAI_SHOPIFY_URL/KEY. Lazily connect in fetch methods.
```

PR-д:
- Test green-Эй
- 200+ мөр change-д design note (workflow doc)
- "Money-on-the-line" path-д extra reviewer

---



## 4c. AUTONOMOUS MASTER PROMPT

*Энэ хэсэг нь owner "hiij ehel" / "continue" / "uhaalag bolgo"
гэх мэт ерөнхий даалгавар өгөхөд код-агент ямар горимоор ажиллахыг
тодорхойлно. MVP/demo биш, бодит ажлын стандарт.*

### Цөм зарчим

1. **Never stop.** "Дууссан уу?" гэж асуухын оронд дараагийн roadmap
   зүйл рүү шуудан шилж. Дууссан гэдэг = code commit, тест green,
   push хийгдэж, owner-т статус илгээсэн.
2. **Real work.** Stub файл биш — contract-тай, тесттэй, brain-facade-
   руу холбогдсон, pre-existing pipeline-аас ч холбогдсон ажил.
3. **Honest status.** Overclaim хориотой. "Wiring ready but no
   revenue yet" гэх шиг үнэн хэл.

### Гол ажлын loop (iteration бүрд давтана)

```
observe   → snapshot: git status, recent commits, open todos,
             pytest collect-only count, "what might be rotten"
plan      → highest-leverage unit from docs/AGI_ROADMAP.md,
             эсвэл өмнөх iteration-ий discovered gap
execute   → build / fix / wire. Small, testable increments.
verify    → targeted pytest, then broader, then smoke-test on real
             code path (e.g. SHOPAI_BRAIN_HOOKS=1 cycle run)
commit    → descriptive message: WHY first paragraph, WHAT second,
             HOW / TESTS / INVARIANTS third
push      → git push -u origin <branch>
report    → ≤100 words status to owner
```

### Priority order (аль ажлыг эхлэх)

1. **P0 bugs** гол pipeline-ийг breaks хийдэг алдаанууд →
   тэр дороо fix (commit нь reason-ыг captured хийнэ)
2. **Unfinished commits** previous session-аас → бүрэн гүйцэд
3. **Roadmap P0 items** (`docs/AGI_ROADMAP.md`)
4. **Audit findings** — dead code, missing tests, pre-existing
   bugs батал олсон → batch-fix
5. **New features** roadmap-ийн P1–P4

### Audit habits (iteration эхэнд заавал ажиллуул)

Commit эхлэхээс өмнө эдгээрийг систем даяар шалгах:

- `grep -rn "TODO\|FIXME\|XXX"` шинэ оруулгыг triage
- **Duplicate class / function names** — `observe_kpi` давхар
  тодорхойлогдоод шадов хийгдсэн шиг алдаа байнга хайх
- **Lock misuse** — `Lock` ашиглаж байгаад ижил instance-аас дахин
  lock авах код (deadlock) → `RLock`-той солих
- **Bare `except Exception: pass`** — CI guard wave11 хориотой;
  `logger.debug(exc)`-тэй солих
- **New module in `/core/brain/` not wired to `brain_facade`** →
  singleton + snapshot + facade method нэмэх
- **New module in `/agents/` эсвэл `/execution/` not invoked** от
  orchestrator руу → wiring нэмэх
- **Module without test** → write one эсвэл delete

### Bug-finding discipline

- **Pre-existing bugs discovered** other work-ийн дунд → commit
  message-д тэмдэгл АМД если risk нь бага бол тэр даруй зас.
  Risk өндөр (production write path) → unit-test бичиж reproduce
  хий, дараа fix, дараа extend test.
- **Silently bypass a broken thing огт хориотой** — note, decide
  fix-now or defer, don't ignore.
- **Rabbit hole?** Time-box: 30 минут fix-on-sight; нэмэх бол
  `docs/AUDIT_LOG.md`-д бичээд дараагийн iteration хойш шилж.

### Search agent pattern (когда мэдээ дутмаг)

Өгөгдсөн ажил clear биш бол доорх тusage дагаж мэдээлэл цуглуул:

```
1. `grep`, `find`, `ls` — codebase map
2. Read related tests — invariant-ийг captured
3. Read adjacent modules — naming / structure дагаж мөрдөх
4. `git log --oneline | head -20` — дурдагдсан өөрчлөлтийн
   шалтгаан хайх
5. `pytest tests/<related>.py -v` — одоогийн behavior баталгаа
```

LLM-ийг зөвхөн ambiguous natural-language дээр дуудах; determinism
эсвэл rule-based аргаар шийдэх боломжтой үед **битгий дуудна**.

### Self-improvement triggers

- 200+ мөр change-д дараах шалгалт автомат:
  - Одоо байгаа модультай duplicate болж байна уу?
  - Edge case тест бүгдийг covered уу?
  - Module docstring-д WHY-ийг тайлбарласан уу?
- 5 commit тутам mini-audit:
  - `brain_facade` дотор хэдэн method? Snapshot section-тай тулгана
  - Unreachable modules, slow tests, flakes
- 20 commit тутам full-suite regression ажиллуулж archive

### "Real work vs MVP" цагаан хар жагсаалт

**Real работа:**
- Бүх write path нь idempotent + retry-hardened (`_client_request_id`,
  exponential backoff)
- Action бүрт outcome event `outcome_recorder`-оор brain-руу очдог
- Шинэ module нь `brain_facade` дотор thing эсвэл тодорхой reason-тай
  шалтгаантайгаар тусад нь
- Test suite нь зөвхөн happy path биш, failure mode-уудыг шалгана
- Commit message нь *owner pain*-ийг шийдсэн зүйлсийг тусгана

**MVP / demo:**
- Stub функц, "TODO: implement"
- Happy-path only test
- Module хаана ч холбогдоогүй
- Commit "let me try X" эсвэл "WIP"
- External API call рeтry-гүй

### Status format (owner руу илгээх ≤100 үг)

```
Shipped: <commit_hash1> <short title>
         <commit_hash2> <short title>
Wired into: <pipeline / facade / orchestrator>
Tests: <N/N green>; regression across <scope>
Next: <next roadmap item>
Blockers: <if any>
```

### Roadmap дагаж явах

- `docs/AGI_ROADMAP.md` нь таамаглалын цахим бус, бодит
  track list.
- Ажил ship хийгдэх бүрт тухайн track M-ийн статусыг дэвшүүлж,
  шинэ unknown (pre-existing bug, missing wiring) олдвол Notes
  section-д нэмнэ.
- Roadmap дуусахад шинэ хэрэгцээг brain-ийн snapshot statistics-
  аас ухааж гарга: hooks = off module-ууд, low coverage test-
  үүд, unreachable engines.

### Cycle-ийн cost budget

- LLM cost **cycle-д $0.10-аас доогуур** байлгана
  (`compute_budget` caps дагаж).
- `_http_request` retry loops нь кумулятив latency 30s-аас
  хэтрэх ёсгүй.
- Хэтэрвэл `insight_synthesizer` warning гарч, owner-руу
  escalate хийнэ.

### K. Self-check discipline (wrong-loop detector)

Agent нь infrastructure-аа илүүтэйгээр plumb-дэн, бодит хэрэглэгчийн
орлого руу орох замыг алдаж болзошгүй. Буруу loop-оос гарахын тулд
*3 commit тутам* дараах 4 асуултыг ассесcмент хийнэ:

1. **Mission-ийн дагуу уу?** Сүүлийн 3 commit нь дараах аль нэгийг
   шууд урагшлуулсан уу? — (a) dropshipping revenue, (b) content/ads
   production, (c) brand/social channel өсөлт, (d) autonomy (брэйн
   өөрөө шийд гаргах), (e) self-improvement (алдааны сургамж).
   Хариу *none* бол буруу loop.
2. **Plumbing vs Capability?** Сүүлийн 3 commit нь "observe /
   record / surface" хийсэн үү, эсвэл "spend / earn / reach a
   buyer" хийсэн үү? Харьцаа 2:1 plumbing-capability байвал OK,
   түүнээс их бол **pivot**.
3. **Month-tomorrow test.** "Хэрэв би энэ ажлыг сар хийсэн бол
   Shopify store дээр үүнээс хамаарч one real order байх байсан уу?"
   Хариу *no* бол зогсоод AGI_MISSION_PLAN-аа дахин унш.
4. **Dollar distance.** Өнөөдрийн ажилаас real $ event-тэй хүрэх
   хамгийн богино зам хэд хэдэн commit вэ? 5+ бол plan нь буруу.

Хариу нь *wrong loop* гэвэл:

```
STOP → re-read docs/AGI_MISSION_PLAN.md →
  pick highest-P item that ENDS in a $ event →
  restart loop
```

### Cross-check (double-verification before commit)

Commit хийхээсээ өмнө дараах хоёр шалгалтыг **хоёулаа** гүйцэтгэ:

1. **Technical cross-check:**
   - `pytest <changed>.py` — өөрчилсөн module-ийн тест
   - `pytest <dependent>.py` — нэмэлтээр хамааралтай хэсэг
   - Smoke-run if the cycle / webhook / adapter path is touched
2. **Strategic cross-check (§4c.K):**
   - Mission-ийн дагуу уу?
   - Plumbing vs Capability харьцаа зөв үү?
   - Dollar distance 4-өөс доошоо уу?

Хоёр шалгалт pass хийсний дараа л commit. Commit message нь заавал
сүүлийн 2 асуултын хариуг дурдна (1-2 өгүүлбэрийн хүрээнд).

---

## 4d. ЧАНАРТАЙ БОДОХ + ӨӨРИЙГӨӨ ШҮҮМЖЛЭХ ЦИКЛ

*Энэ хэсэг нь бидний цар хүрээний зорилго (AGI tier autonomous
business operator) ба ажил хийх стандартыг гарын авлага
болгож тогтоосон. Claude (агент)-д хамаатай, мөн ШопAI-ийн
runtime AI-д хамаатай. Гол зарчим: их код биш — чанартай
код. Жижиг хэсэг бүр **амьд + сайн + алдаагүй**. Тугс
хувилбар шуурхай хийх боломжтой бол нэн даруй хий.
100%-ийн боломж байвал зогсолтгүйгээр ахиулсаар бай.*

### A. Цар хүрээ (mission scope)

ШопAI-ийн зорилго нь **AGI түвшний биеэ даасан AI бизнес
оператор бас драйвер** болох. Энэ түвшинд хүрэхэд:

- 400k мөр код байлаа гэж чадваргүй бол их тоо л үлдэнэ.
- Том зорилго → маш олон жижиг сайжруулалт. Хэсэг бүр
  өөрөө сайн.
- Зорилго бол төгс биш, харин **амьд + сайн + алдаагүй**.
- Гэхдээ төгс болгох боломж шууд гарвал шуурхай хий.
  100% хүртэл боломжтой бол хийсээр л бай.
- Алдаагаа олоод сайжруул → шинэ түвшинд гарга → дараагийн
  төгс хувилбарыг бод → одоо дээрээ сайжруул.

Hostni салгах бус, **хэсэг бүрийг холбоо нэмэгдсэн, ажилладаг,
сайжирсан** болго. CLAUDE.md §4c-ийн "сул талыг устгахгүй,
сайжруулна" зарчмыг үргэлжлүүл.

### B. 6 өөрийгөө асуух асуулт (өмнө бодох)

Code commit, design сонголт, эсвэл owner-ы хариу гаргахын
өмнө дараах 6-г бодох:

1. **Яаж ажиллах вэ?** — workflow + sequencing
2. **Яаж бодох вэ?** — framing + alternatives
3. **Юу хийж байна вэ?** — current state honest read
4. **Юу хийх вэ?** — next concrete unit
5. **Ямар алдаа үүсэж байна вэ?** — error scan
6. **Яаж сайжруулж болох вэ?** — refine path

Энэ 6 нь Claude-д хамаатай, ШопAI-ийн runtime AI-д хамаатай,
бас 5-тулгуурын `core/brain/structured_decision.py`
framework-ын footprint-ийг яг тогтоодог.

### C. 5 тулгуурын чанартай шийдэл (5 pillars)

Аливаа значительны шийдвэр (commit, runtime decision, owner
reply) дараах 5 пиллараар дамжина:

| # | Тулгуур | Утга | Кодон дахь дүрс |
|---|---|---|---|
| 1 | **Outcome** | Ямар үр хэрэгтэй вэ? Яагаад? Хэрхэн хэмжих вэ? | `OutcomeSpec(what, why, measurable, value_usd)` |
| 2 | **Thinking directions** | Олон чиглэл бод. Зөвхөн анхных биш. | `ThinkingDirection(label, action, reasoning)` |
| 3 | **Constraints** | Юу барьмталах ёстой? Hard vs soft. | `Constraint(name, kind, evaluator)` |
| 4 | **Refine + learn loop** | Score, iterate, record. Сэргэх. | `RefineStep(score, hard_violations, note)` |
| 5 | **Free thinking + self-awareness** | Meta-check: буруу гогцоо уу? Plumbing vs capability? Dollar distance? | `SelfAwareness(loop_check, dollar_distance, plumbing_vs_capability)` |

Бодит wire-up: `core/brain/structured_decision.py`. Бодит
runtime use: `CampaignActivator._record_structured_decision`,
`PublisherBundle._record_structured_decision`. Owner Claude
Desktop-аас инспекц: MCP `recent_deliberations`.

### D. Өөрийгөө шүүмжлэх + сайжруулах цикл

Гарсан зүйлээ өөрөө шүүмж шүү:

```
   гаргасан зүйлээ өөрөө шүү
   → сул талыг ол
   → сайжруулсан 2 дахь хувилбар гарга
   → хамгийн сайн хувилбараа сонго
```

Нэг код блок, нэг алхам, нэг шийдвэр гаргаснаас хойш:

1. **Өөрөө уншиж шалга** — энэ үнэхээр мисс-г шийдэж байна
   уу? Style, naming, error handling, edge case дотор сул
   тал юу вэ?
2. **2 дахь хувилбар бод** — энэ кодыг арай өөрөөр (more
   defensive, more concise, simpler dependencies, etc.)
   яаж бичих вэ? Хэн ямар алдаа гаргах вэ? Үргэлж
   1 alternative хувилбарыг бичсэнтэй адил бод.
3. **Сонгох** — хоёрын алийн нь сайн нь? Хэрэв 2-р хувилбар
   нь онцгой бол одоог нь шинэчил.
4. **Тестээр баталгаажуул** — сонгосон хувилбарыг тест
   нэмж бүрхэгдсэн, edge case-уудыг ч сэтгэх.

Энэ цикл нь Claude (агент)-ы commit бүрт хамаатай, мөн
ШопAI-ийн `structured_decision.refine` алхамд хамаатай.

### E. Юу үлдэх вэ? Quality vs Quantity

Нэмэх нь сайн биш — **сайжруулах нь сайн**. Code shed-ийг
жигдрүүлэх (DRY, де-дупликация, contract drift засах) нь
шинэ feature нэмэхтэй адил үнэ цэнэтэй. Үнэн цэнтэй
хариулт болохгүй commit-ыг ship хийхгүй. Жижиг улам сайжруулсан
хэсгүүд → том чанартай систем.

Жишээ зарчим (audit pass-аас):
- 3 хуулбар бүхий live-execution gate → 1 канон функц + 3
  delegating wrapper. Кодын тоо бараг өөрчлөгдөөгүй;
  drift боломж 0 болсон.
- ToolResult 5 талбар → 10 талбар + factory; existing
  callers зүгээр хэвээр; шинэ adapter callers cost track
  хийх боломжтой.

### F. Cross-check pre-commit (extension of §4c)

§4c-ын technical + strategic шалгалтууд + энэ §4d-ийн 6
асуулт + 5 пилларыг нэг хүснэгт:

1. Tests pass — тиймээ
2. Mission aligned — тиймээ
3. Plumbing/capability ratio зөв уу
4. Dollar distance ≤ 4 уу
5. Outcome тодорхой бичигдсэн үү (commit message-д)
6. Self-critique хийгдсэн үү — 2-р хувилбарыг бодсон
   эсэхийг шалгасан уу
7. 5 пилларын аль нь алгасагдсан бол яагаад

Хариу бүгд "тиймээ" эсвэл "ухамсартай үгүй" → commit.
Эс бөгөөс refine.

---

## 5. LLM / MODEL ТОХИРГОО (3-Agent Architecture)

ShopAI-ийн brain нь 3 тусдаа LLM-ыг чиг үүрэгтэй:

| Агент | Role | Санал болгож буй model | Яагаад |
|---|---|---|---|
| **Model 1** | Automation (execute) | Groq (Llama 3.3 70B) | хурд — 30 req/min free |
| **Model 2** | Data/Memory (analyze) | Gemini 1.5 Flash | long context, multimodal |
| **Model 3** | Research (reason) | DeepSeek V3 | deep reasoning, хямд |
| Fallback | Local | Ollama (Mistral/Qwen/Llama) | offline, privacy |

Remote chain `.env`-д:
```
GROQ_API_KEY=gsk_...          # Model 1
GOOGLE_API_KEY=...            # Model 2 (Gemini)
DEEPSEEK_API_KEY=sk-...       # Model 3
OPENROUTER_API_KEY=...        # optional overflow
HUGGINGFACE_API_TOKEN=hf_...  # optional
```

(ANTHROPIC_API_KEY, OPENAI_API_KEY ашиглахгүй — бусад 6 адаптертай
хангалттай.)

Ollama байхгүй үед `SmartExecutor` дотор real business algorithm-ууд
(Thompson Sampling, moving average, Jaccard...) fallback болж ажиллана —
систем LLM-гүйгээр ч mathematical intelligence-тэй үлдэнэ.

### Memory — Obsidian Vault Bridge

ShopAI-ийн memory-г Obsidian knowledge graph-тэй синхронжуулдаг:

- `core/adapters/obsidian/vault.py` — note read/write
- `core/adapters/obsidian/memory_bridge.py` — memory ↔ vault sync
- `vault/` folder-т: `Concepts/`, `Decisions/`, `Errors/`, `Knowledge/`,
  `Templates/`, `Wins/` гэсэн 6 категори
- `.env`-д `OBSIDIAN_VAULT_PATH=./vault` (эсвэл өөрийн vault path)

Pattern detect хийгдмэгц Obsidian-д markdown болж бичигддэг, хожим тэр
note-ийг down-rate хийвэл `feedback_learner` авсансан байна.

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

---

## 8. SESSION TRACKER (одоо ажиллаж байгаа branch)

Энэ хэсэг fresh agent-д "хаана яваа вэ" гэдгийг өгнө. Бүрэн detail
docs/IMPLEMENTATION_PLAN_2026.md дотор. Branch:
`claude/update-shop-ai-docs-dVyQc`.

### 8a. Аль хэдийн ship хийсэн (2026-04-20→21 wave)

| Wave | Гол commit | Ажил |
|---|---|---|
| A1 EU AI Act | (in-tree) | Article 50 C2PA gate `execution/compliance/eu_ai_act_gate.py`; PublisherBundle-д wire |
| A2 Landed cost | (in-tree) | `LaunchCandidate.from_landed_cost()` — de-minimis aware COGS |
| A3 Schema stack | (in-tree) | JSON-LD @graph metafield in `_step_create_product` |
| A4 Agentic webhook | `bb85e22` | OrderWebhookHandler classifies chatgpt/perplexity/copilot/gemini |
| A5 MCP stdio | `fbd9ae8` | JSON-RPC 2.0 transport + `python -m mcp_server.server` |
| A6 fal.ai videos | `b43bf82` | PublisherBundle._step_generate_videos |
| A7 Moby comparator | `c154a11` | Vote-disagreement log + auto-resolve on outcome |
| B nav docs | `663a97b` | 12 per-concept `docs/nav_*.md` |
| C1+C2 dead scaffolds | `d53a9a1` | brain/, integrations/, testing/ deleted (~1400 LOC) |
| C3 memory consolidation | `97c4d8a` | core.memory re-export of 4 legacy primitives |
| C4+C5 docs-only deferral | `33ff98f` | scripts/ + cli.py split documented; physical move deferred |
| D1 OAuth | `f56bc84` + `63a4c57` | `core/auth/token_resolver.py` + daemon wire |
| D2 Post-write verifier | `a777a60` | ProductUpdater.update_product/update_price `verify=True` default |
| Owner CLI surfaces | `7fe79a8` | `shopai moby/fal/oauth/cycles` commands |
| Owner MCP brain tools | `9d8436d` | trust_status / memory_ladder / recent_decisions / predict_outcome |
| Knowledge boundary doc | `0b95dfd` | knowledge/ vs core/memory/ vs vault/Knowledge/ |
| Meta v25 + attribution | `7c7b57c` | v21→v25 + 7dv→1dv translation |
| Autopilot smoke test | `6d18aeb` | Real publisher+activator E2E |
| Dashboard panels | `fdf0449` + `a5a2dfc` | agentic / moby / fal / autopilot daemon panels |
| Cycles CLI+MCP | `fbe6e44` | `shopai cycles` autopilot log tail |
| Moby cache | `f5e6f95` | 5-min TTL on recommendations |
| Video opt-in gate | `340713d` | SHOPAI_VIDEO_GENERATE=1 (money safety) |
| Engine bus emit | `1ac5fd6` | activator → engine_outcome_bus |
| Doctor probe MCP | `887a848` | core.readiness.doctor + 5 probes |
| GEO quote-sandwich | `03bcfd9` + `325168f` | Princeton +40% LLM citation pattern + opt-in wire |
| llms.txt serving | `d710cec` | CLI build + API serve routes |
| Brain snapshot rollup | `a02ef7c` | agentic/moby/fal fields on BrainState |
| Pidfile + autopilot-status | `80221e8` | Daemon liveness CLI + MCP |
| notify-errors digest | `25a0888` | Telegram cycle-error digest |
| TikTok Shop foundation | `12f5ac5` | HMAC signer + read-only Z6 adapter |
| Webhook HMAC audit | `9d1100d` | env fallback + fail-closed gate (security) |
| Tracker + rationale + wave11 | `3aa62c3` | CLAUDE.md §8 + moby gate stamp + tiktok wave11 fix |
| Webhook rate limiter | `ddeb627` | per-IP token bucket (P0.2 security defence) |
| Owner tool dispatcher | `dccbfa1` | Telegram phrase → MCP tool with confirm-gate (P1.3) |
| Dashboard live fresh | `a21fbb4` | `--live` passes force=True so cached agentic status refreshes each cycle (P1.5) |
| fal video pre-gen cache | `2770975` | prompt-hash cache dedupes identical prompts across SKUs (P2.7) |
| llms.txt daemon rebuild | `fbcd05b` | Autopilot cycle every N rebuilds llms.txt/mirrors from live Shopify |
| GEO citation store | `9424313` | Niche-keyed `data/citations/<niche>.json` auto-injects into content_generator quote-sandwich |
| Quality audit pass | `4c23d23` `73d30f5` `048e621` `5b79338` | Live-execution centralised, ToolResult telemetry, AgentManager facade, BrainFacade.register_module |
| 5-pillar structured decision | `f0a603a` | `core/brain/structured_decision.py` — Outcome / Directions / Constraints / Refines / SelfAwareness for every significant decision; MCP `recent_deliberations` |
| Activator → deliberation wire | `c7d1293` | Every activation records a 5-pillar Deliberation visible via MCP `recent_deliberations`; verdict unchanged |
| Publisher → deliberation wire | `658ed6f` | Every product launch records a 5-pillar Deliberation symmetric to the activator wire; budget-commit point captured |
| §4d quality + self-critique | `20e2ac1` | Mission scope + 6 self-questions + 5 pillars + self-critique cycle codified in CLAUDE.md |
| Refine+learn loop wire | `5936015` | Order webhook back-fills the matching Deliberation with measured revenue; predicted-vs-observed visible via MCP |
| Pillar mirror → rationale ledger | `03f6b1f` | Activator + Publisher push 5-pillar entries into rationale.add so `shopai explain <decision_id>` shows structured reasoning alongside gate-level entries |
| Replay orders tool + T2 plan | `384edb6` | `agents/replay/order_replay.py` + `shopai replay-orders` CLI + MCP tool (write-gated) — feeds historical/synthetic orders through the live webhook pipeline so Deliberation back-fill + engine outcome bus + pattern miner get real signal without waiting for real traffic. `docs/PATH_TO_T2.md` codifies T0→T2 path + integrates Explore-agent weak-parts audit (money-path silent-Nones, 41 brain orphans, 12+ happy-path-only test suites) |
| P1-A batch 1 (audit money-path) | `5510fe4` | Marketing LLM copy silent-None → `warning` log with reason (adapter, error, empty-text). `core.system.live_execution.check_gate_drift()` — defensive invariant called at the ad-budget commit point in publisher + activator; mid-launch env flip stays with caller's intent but gets logged. |
| Replay synthesize | `fff0ea1` | `agents/replay/synthesize.py` generates deterministic Shopify-shaped order payloads; `shopai replay-orders --synthesize N [--seed S] [--attach-decision-rate R]` unblocks T1 validation without needing a live store export. 17 new tests lock Shopify shape + determinism. |
| Store builder Phase 1b — Menus | `6cfa860` | `_setup_menus` updates both default Shopify menus (main-menu + footer) via GraphQL `menuUpdate`. Niche-aware main-menu (fashion → "New Arrivals", tech → "Gadgets", home → "Shop Home"); footer always carries the 4 legal policy links + About/Contact/FAQ. Idempotent (find by handle, update). 11 new tests. |
| Store builder Phase 1f — Policies + GraphQL helper | `3e26dba` | `ShopifyClient.graphql(query, variables)` shared helper — same rate-limit + retry + auth pipeline REST uses. `StoreConfigurator._setup_policies` writes all four legally-required policies (Privacy / Refund / ToS / Shipping) via `shopPolicyUpdate` mutation. Hard-coded safe templates (no LLM fabrication); owner reviews before publishing. Unlocks Phase 1b-1e menus + notifications + markets + store details on the same helper. 9 new policy tests + 4 new graphql tests. |
| Knowledge ingest CLI + MCP | `28c1f06` | Audit batch 3 final — `core/memory/knowledge_ingest.py` (orphan) gets owner-facing handles: `shopai ingest-knowledge --url|--file [--subject S]` CLI + `ingest_knowledge` MCP tool (write-gated). Owner pushes brand docs / changelogs / supplier FAQs into the KB manually. 6 tests. |
| RCA owner-facing wire | `f493ef9` | `core/learning/root_cause_analyzer.py` got a singleton; MCP tool `analyze_failure` lets the owner query RCA from Claude Desktop with a `failed_episode` dict and get contributing factors + lesson + prevention rule. Pipeline auto-wire (on publisher failure) deferred until an episodic memory adapter ships. 5 tests. |
| Live-health rolling digest | `6e317a3` | P1-C — `core/readiness/health_trend.py` fuses doctor probes + recent autopilot cycles + per-engine feedback trends into a single verdict (healthy / degrading / needs_attention / unknown) with plain-English reasons. `shopai live-health` CLI + `live_health` MCP tool. Deterministic rules, no LLM. 18 tests. |
| Store builder Phase 1a — Pages | `c687086` | `StoreConfigurator._setup_pages` auto-creates trust-signal pages (About / Contact / FAQ) on fresh Shopify stores via REST `pages.json`. Niche-aware tone (beauty → "caring / sensorial", fashion → "confident / trend-aware", etc.). Idempotent on handle, dry-run previews, per-page error isolation. `docs/STORE_BUILDER_EXPANSION.md` codifies the 10-feature Phase 1-3 plan (policies + menus + notifications + metafields + theme + markets + locations + checkout). 11 new tests + 3 updated. |
| Brain module catalog | `1471b13` | Audit batch 4 — `core/brain/module_catalog.py` honest-label registry (active / experimental / archived / unknown). Bootstrap declarations for 5 experimental + 3 active modules. `brain_module_catalog` MCP tool. Owner now sees which brain capabilities are live vs parked without trawling the 225-file tree. 11 tests. |
| Learning orphan wire-up | `84b0511` | Audit batch 3 — `core/learning/feedback_store.py` gets a module singleton + plugged in as 5th `EngineOutcomeBus` sink. Order webhook now emits a wider `order_webhook` engine outcome on every paid order (not only agentic) so feedback_store + pattern miner + freshness tracker see organic signal too. MCP tools `engine_feedback_stats` + `improvements_summary` expose the learning ledger to Claude Desktop. Previously-dead modules now participate in the live loop. 10 wire tests + 2 updated attribution tests. |
| P0-C RuleBook quality gate | `cd9de52` | `core/learning/rule_quality.py` — lift-based true-positive measurement across the RuleBook. Baseline = weighted-mean win_rate across applied rules; per-rule verdict = true_positive (lift ≥ 1.20) / false_positive (lift < 0.80) / uncertain / insufficient_data. `shopai rule-quality` CLI + `rule_quality` MCP tool so owner can measure the T2 KPI ("PatternMiner true-positive rate ≥ 60%") from Claude Desktop. 19 new tests incl. end-to-end against real sqlite RuleBook. |

**Tests added:** ~295+ new pytest (21 replay + 6 P1-A batch 1 + 19
rule-quality). **Full-suite checkpoint:** `9664+ passed`. **MCP
tools:** 26 (эхэнд 12).

### 8b. Дараагийн ажил (priority queue)

P0 — money/security path:
1. **TikTok Shop write-path** — ProductCreator + OrderListener
   (Z6 mission, dollar distance 5; high-risk because it's live
   money on a new platform).
2. ✅ **Webhook rate limiter** — done. Per-IP token bucket in
   `core/webhooks/rate_limiter.py`; api/server.py 429s
   abusive callers ahead of the HMAC compare.

P1 — owner experience:
3. ✅ **Owner dialog → MCP tool dispatcher** — done.
   `agents/owner_dialog/tool_dispatcher.py` parses 17
   intents → MCP tools. Write tools require "confirm"
   suffix (paranoid mode). Reachable via
   `shopai owner-ask "<phrase>"`.
4. **Brain rationale ledger trace for Moby step** — every
   activation's `explain_decision` shows whether Moby agreed.
5. ✅ **Dashboard live mode auto-refresh of A-D panels** —
   done. `show_live()` calls `show(force_fresh=True)`;
   agentic panel passes `force=True` to bypass the 5-min
   bridge cache.

P2 — capability extensions:
6. ✅ **GEO quote-sandwich citation store** — done.
   Owner curates `data/citations/<niche>.json` once per
   niche; every SKU in the niche auto-inherits when
   `use_geo_sandwich=True`. No fabrication; explicit
   product-level citations still win.  CLI `shopai
   citations list|show` + MCP `citations_show`.
7. ✅ **fal.ai video pre-generation cache** — done.
   Prompt-hash-keyed SQLite cache in FalVideoRouter; generic
   prompts reuse the cached URL across SKUs at $0. TTL
   configurable via `SHOPAI_VIDEO_CACHE_TTL_DAYS` (default
   30d).

P3 — research wave:
8. **Q3 2026 market research refresh** — Sora successor,
   Shopify Spring '26 edition, Meta Andromeda v2.

### 8c. Wrong-loop detector (§4c.K) — checkpoint

- Mission: Z1 autonomy + Z4 revenue + Z6 multi-platform —
  ALIGNED.
- Plumbing/capability ratio (last 5 commits): 1:4 capability —
  HEALTHY.
- Dollar distance (last 5 commits): 0-3 — HEALTHY.
- Month-tomorrow test: shipping doctor + cycle-errors +
  pidfile + HMAC fix means a fresh deploy has live-money
  safety gates → real orders can land safely. PASS.
