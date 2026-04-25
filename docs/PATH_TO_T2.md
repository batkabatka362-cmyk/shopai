# PATH_TO_T2 — бидний дараагийн чиглэл

**Branch:** `claude/update-shop-ai-docs-dVyQc`
**Хэмжээс:** одоо Т0 (Built), зорилго Т2 (Self-sustaining)
**Дүрэм:** §4d — амьд + сайн + алдаагүй; тест ногоон ≠ амьд.

Энэ доkүмент нь scaffolding-аас бодит revenue-дриверт шилжүүлэх
тодорхой зам. Хийх ажил, барьмталбал зохих constraint-ууд,
хэмжүүр, asuух асуултууд.

---

## 0. Сэтгэлгээний 5 тулгуур (Outcome → ... → Awareness)

Энэ plan өөрөө structured_decision.py-н 5 пиллараар
бичигдэнэ — оператор ба operated нэг бодлогоор явна.

**Outcome**: Т0→Т1→Т2-д шилжих. Т2 = нэг store, сард 30+ ord,
owner touch <2/долоо хоног, ROAS≥1.5. Нэг сарын дотор
measurable evidence олох.

**Why**: Scaffolding бүрэн болсон. Learning loop бэлэн.
Гэвч 0 ord → 0 evidence → 0 сургамж. Runtime-гүй бол AGI биш.

**Measurable**: `data/autopilot_loop.log` нь `mode:live`-тэй
7 хоног + `recent_deliberations` нь `.observation.revenue_usd > 0`
талбар бүхий бичлэгтэй.

---

## 1. Тавусан 4 түвшин (tier map)

| Tier | Гол шалгуур | Status |
|---|---|---|
| Т0 Built | Tests green, code compile хийгдэж, daemon import хийгдэнэ | ✅ 2026-04-21 |
| Т1 Deployed | Нэг store SHOPAI_ENABLE_LIVE_EXECUTION=1, 7 өдөр live run | ❌ |
| Т2 Self-sustaining | 30+ ord/сар, owner touch <2/wk, ROAS≥1.5 | ❌ |
| Т3 Compounding | Real-shape pattern → auto rule promote, used on new SKU | ❌ |
| Т4 Multi-store fed | 1 store-д сурсан rule бусдад тарж measurable lift | ❌ |

Энэ plan Т1→Т2-ийг target болгоно. Т3, Т4 өдий болтол early.

---

## 2. Priority queue (нэг сарын хоризонт)

| № | Chain | Prerequisite | Dollar distance |
|---|---|---|---|
| P0-A | ✅ `docs/T1_GO_LIVE.md` shipped — 11-step checklist + §4d cross-check | None | 3 (setup → launch → ord) |
| P0-B | `shopai replay-orders <jsonl>` — historical/synthetic ord-г webhook pipeline-д feed | None | 2 (replay → learn → next launch better) |
| P0-C | RuleBook lift-based quality gate — `core/learning/rule_quality.py` + `shopai rule-quality` CLI + MCP tool | ✅ done | 3 (quality gate → compounding) |
| P1-A | Audit batch 1 (A1+A2+A3: money-path logging + dry_run assertion) | Audit done | 2 |
| P1-A' | Audit batch 2 (tripwire + scratchpad silent-None → contract) | Audit done | 3 |
| P1-B | Deliberation-ийн observation-аас ROAS predict — `predict_outcome` MCP-д wire | Audit | 2 |
| P1-C | `shopai live-health` — цаг бүр live cycle-н health check | T1 started | 1 |

Эрэмблэсэн: **P0-А → P0-B → P1-А (audit fixes) → P0-C → P1-B → P1-C**.

---

## 3. Барьмталбал зохих constraint-ууд (§4c.K барьсан)

1. **Commit бүр Т2 шалгуурын нэгний distance-ийг багасгаж байх ёстой.** Мэдэгдэхгүй бол commit хийхгүй.
2. **Mock-only test-ийг бодит integration-ээр нэмэх ёстой**. T0-д магадлагдлаа, T1-д **бодит staging** шаардлагатай.
3. **Plumbing/capability ratio 1:3 capability-д сайн.** 3-4 plumbing commit → 1 capability commit нь acceptable; илүү plumbing бол stop.
4. **Dollar distance ≤4**. Тэгэхгүй бол wrong loop.
5. **§4d self-critique EVERY commit.** 2-р хувилбар бодоогүй бол ship хийхгүй.
6. **Silent delete огт үгүй.** Сул хэсэг → reconnect, не remove.

---

## 4. Refine + learn дарааллын хэмжүүр (30/60/90)

**30 хоног:**
- P0-A + P0-B + P1-A (audit fix-ээс дээд 3) shipped
- Т1 шалгуур: 1 store, 1 live cycle, 1 replay run
- KPI: `recent_deliberations` дотор нэг бичлэг `.observation` populated

**60 хоног:**
- P0-C quality bar shipped
- 7 өдрийн live daemon log (`mode:live`)
- 10+ replay cycle дамжуулсан
- KPI: PatternMiner-н true-positive rate measured ≥ 60%

**90 хоног:**
- Т2 шалгуур: сар 30+ ord нэг store
- owner intervention cadence ≤ 2/wk
- Rule promotion evidence (sanity test-ээр)
- KPI: ROAS≥1.5 тайлан

---

## 5. Self-awareness (honest read)

- **Mock гамшиг:** бидний 9943 тест нь 95% MagicMock. Т1 live-ээр ирэхэд real-shape дата (Shopify JSON, Meta insight response) шинэ bug surface болгоно.
- **Deferred P0.1 TikTok write-path:** яагаад deferred? Live-money-new-platform = 2 эрсдэл нэгтгэгдэнэ. T1 шалгагдсаны дараа бол tackle.
- **Owner зogsolt:** plan ch хүн оролцоотой (.env setup, store register). Бид хүнгүй автономи байж чадахгүй, энэ **Т1 эргэлзээ**. Т2 — хүн шаардлагыг автомат болгох.
- **Wrong-loop risk:** audit-аас олдох findings → fix нь дахиад plumbing бол wrong loop. Audit findings-г Т1/Т2 шалгуурт холбож шийдэх.

---

## 6. Audit findings (2026-04-21, Explore agent)

### A. Money-path бодит эрсдэл (эхлээд засах)

| № | Файл | Симптом | Fix |
|---|---|---|---|
| A1 | `agents/marketing/agent.py:85,109,121,135` | `_augment_with_llm_copy()` 4 fallback branch-д `return None`, log-гүй | warning level log — owner degradation харна |
| A2 | `execution/launch/publisher_bundle.py:278` | `dry_run` flag entry-д 1 удаа тооцогдож цааш passed — nested adapter drift болох эрсдэлтэй | nested call-уудад `dry_run` assert нэмэх |
| A3 | `execution/launch/campaign_activator.py:296` | mirror issue — gate нь entry дээр l тооцогдсон | `_step_execute()`-д assertion |
| A4 | `workflows/launch/steps/supplier.py:33` | TODO: CJ adapter sourcing unresolved | adapter дуусгаж `brain_facade.register_module("cj_sourcing", ...)` |
| A5 | `workflows/launch/steps/ads_launch.py:39` | TODO: Meta adapter stub incomplete | stub-г `MetaAdsAdapter.execute()` биеэр солих, эсвэл workflow disable |

**Priority:** A1 эхлээд (pure logging), A2+A3 нэг commit (dry_run assertion), A4+A5 хойшлуулах (TikTok P0.1-тэй хамтдаа wave).

### B. Learning path orphan-ууд (capability сэргээх)

| Файл | Caller | Одоогийн статус | Action |
|---|---|---|---|
| `core/learning/feedback_store.py` | 0 (test-ээс л) | Бүрэн implemented | orchestration loop-д wire |
| `core/learning/improvement_tracker.py` | 0 | Implemented | feedback_store-той хамт wire |
| `core/learning/root_cause_analyzer.py` | 0 | Implemented | feedback_store integration-ийн дараа |
| `core/memory/knowledge_ingest.py` | 0 | HTTP + file ingest ажилладаг | optional module болгож `SHOPAI_KNOWLEDGE_INGEST=1` env toggle |
| `core/memory/scratchpad.py:99-105` | уншигдаж буй | `_write_memo()` 3 fail branch-д silent None | structured log + retry path |
| `core/memory/memory_walker.py:215,221` | тодорхой | None on miss | `{steps: []}` буцаах |
| `core/memory/memory_compressor.py:204` | тодорхой | None on decompress fail | оригинал chunk + status flag |
| `core/risk/tripwire.py:296,318,325,331,350,360,380,390,426` | money path | 9 silent-None branch | `{allowed, reason}` contract |
| `core/memory/knowledge_validator.py:266,269,274` | тодорхой | Silent None | validation result dict |
| `core/memory/ontology.py:161` | тодорхой | None on miss | empty result set |
| `core/memory/observation_fuser.py:214` | тодорхой | None on error | оригинал observation + status |

### C. Brain module 41 orphan (categorise)

`core/brain/` доторх 41 module 0 caller-тэй (ab_bandit, abstraction_ladder, anomaly_triage, model_coordinator, ...). Sprint-ийн шийдвэр:

- **Wire (5-7 модуль):** decision flow-д directly хэрэглэгдэх — model_coordinator (voting), ab_bandit (action select).
- **`@experimental` tag (20+):** brain_facade-д register хийж, `SHOPAI_EXPERIMENTAL_BRAIN=1` env-аар л ачаалах.
- **Archive (15+):** `core/brain/_archive/` руу шилжүүл — git history-д үлдэнэ, import-оос гарна.

### D. Test чанар (mock гамшиг зассан жагсаалт)

| Файл | Symptom | Fix |
|---|---|---|
| `tests/test_store_configurator.py` | 71 happy-path function | error injection — invalid shop_url, malformed response, API timeout |
| `tests/test_reflection.py` | 49 happy-path | raise case нэмэх |
| `tests/test_wave14c_input_validation.py` | 46 function, no failure injection | Edge + invalid input суваг |
| `tests/test_data_quality_audit.py` | 42 function | bad-data path |
| `tests/test_intelligence_systems.py` | 42 function | exception path |
| `tests/test_curiosity.py` | 37 function | blocked scenarios |
| `tests/test_moby_cache.py` | 100% MagicMock — адаптер drift captured хийхгүй | tolerant real-HTTP mock нэмэх |

### E. Duplication

- `engines/product_filter/modules/shipping_feasibility/code.py:19` + `logic.py:15` — `_billable_weight()` давхар. → `utils/shipping.py`-д extract.

### F. Сул тал байхгүй зүйл (auditor цайвар жагсаалт)

- `core/system/live_execution.py` live-gate canonically centralised — OK.
- Secrets / SQL / path-traversal audit — clean.
- `threading.Lock` ашиглалт зөв — async safety OK.

### G. P1-A ажлын batch (дараагийн commit-үүд)

**Batch 1 (money-path log):** A1 + A2 + A3 — 3 file, logging + assertion. Ship single commit.

**Batch 2 (silent-None → contract):** `core/risk/tripwire.py` + `core/memory/scratchpad.py` — 2 file, `{allowed, reason}` contract. Caller нь None check-ийн оронд structured read.

**Batch 3 (learning orphan wire):** `feedback_store` + `improvement_tracker` — orchestrator цикл-д callsite нэмэх.

**Batch 4 (brain category):** `@experimental` decorator + brain_facade gate + `SHOPAI_EXPERIMENTAL_BRAIN` env.

---

## 6b. T1 validation recipe (live-env-гүй)

Живэ store энвирон-гүйгээр learning loop-г бодитоор туршдаг богино skript. Live deploy хийхээс өмнө энэ дарааллыг ажлуулж зорилтот үр дүн гарвал Т1-т шилжинэ.

```bash
# 1. Бүх тест ногоон
PYTHONPATH=. pytest tests/test_order_replay.py \
    tests/test_replay_synthesize.py \
    tests/test_rule_quality.py \
    tests/test_live_execution_gate.py -q

# 2. 100 synthetic order-ийг жинхэнэ webhook pipeline-руу нэвтрүүл
PYTHONPATH=. python cli.py replay-orders --synthesize 100 --seed 42
# Expected: "Replayed 100 orders (100 ok, 0 failed, 0 skipped)"
# Revenue ≈ $8,000 (deterministic under seed=42)

# 3. RuleBook-ыг судал — PatternMiner rule санал болгосон эсэх
PYTHONPATH=. python cli.py rule-quality
# Expected: total_rules ≥ 1 (PatternMiner replay signature-ээс
# rule proposed), баtalgаа нь insufficient_data (applied_count=0)

# 4. Recent deliberations + observations
PYTHONPATH=. python cli.py ask "recent deliberations"
# Эсвэл Claude Desktop-аас:
#   use tool recent_deliberations

# 5. Live health
PYTHONPATH=. python cli.py autopilot-status
PYTHONPATH=. python cli.py doctor
```

Зорилтот үр дүн:
- 100/100 орд амжилттай орж хэвэл webhook pipeline OK
- RuleBook > 0 rule санал → PatternMiner ажиллаж байна
- Doctor "ready" гэж хариулах → T1-д орох нөхцөл бэлэн

Хэрвээ дээрх 5 алхамын аль нь failed болвол T1 live-deploy хийхгүй.

---

## 7. Нэг асуулт (owner-д)

**Та одоо тестийн Shopify store + Meta Ads sandbox account-той юу?**

- Хэрэв **тийм** → P0-A (`docs/T1_GO_LIVE.md`) бид одоо хийнэ, та setup хийх бол Т1-ийн цаг хэдхэн өдөр.
- Хэрэв **үгүй** → эхлээд бэлтгэл (Shopify Partner dashboard-аас development store 10 минут, Meta developer account / sandbox ad account 20 минут). Тэгэхгүй бол P0-A-ийг бичих ч бодит ашиг гарахгүй.

Хариугаа өгөх хүртэл би P0-B (`shopai replay-orders`) + P1-A (audit fixes)-г ажиллуулна — эдгээр нь live env шаардахгүй.

---

## 8. Status tracking

CLAUDE.md §8-ийн tracker энэ plan-ийн item бүр shipped болмогц
commit hash-тай шинэчлэгдэнэ. Plan өөрөө нэг документ биш —
амьд checklist. Commit ship хийх бүр энэ plan-ийн хариулсан
Т-шалгуурыг тэмдэглэх хэрэгтэй.
