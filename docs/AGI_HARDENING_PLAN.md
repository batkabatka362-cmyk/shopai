# AGI Hardening Plan — post-Sprint 3

> Sprint 3 дууссан (19 commit + 5 wire-in). Бүх LX extension + safety
> triad ажиллаж байна. Энэ plan нь "MVP-аас бодит AGI" хүрэх дараагийн
> 10 track-ийг тодорхойлно.
>
> Owner-ийн нөхцөл: US + EU, яаралтай + бага зардал, нэг удаад нэг
> track, бодит бизнес-үр дүн шаардана.

---

## Зорилго

Sprint 3-ын ажил нь capability breadth-ийг хаасан. Одоо **depth** —
тус бүр module цогц ажиллаж, хоорондоо холбогдож, өөрсдөө сурч,
өөрсдийгөө шалгадаг болох үе.

CLAUDE.md §4c.K дүрмээр — track бүр ажил дуусахад §4c.K self-check
тавьж, commit бүрт `mission fit · plumbing:capability · dollar distance`
мөрдөнө.

---

## Одоогийн сул цэгүүд (аудит)

Sprint 3 дууссаны дараа иймэрхүү "туслах тэгш байдал" үлдэж байна:

| Layer | Байгаа | Дутуу |
|-------|--------|-------|
| L2 Perception | 5 source (CJ/Ali/peer/manual/meta-ads) | source trust calibrator, cross-source dedup, staleness |
| L3 Memory | IntelligentMemory L0-L5 + MemoryIntelligence | episodic→semantic auto-consolidation, staleness decay |
| L4 Reasoning | goal_decomposer, readiness_gate, heuristic_bank | world_model-ийг outcome-д holboh, causal chain reasoning |
| L6 Skills | capability_registry + 2500 engine | decision rationale chain (яагаад энэ skill?) |
| L5 Execution | smart_executor + adapter-ууд | post-write verify, compensate on drift |
| L9 Learning | launch_learner + outcome_recorder | cross-learner synthesis, principle extraction auto-apply |
| L10 Autonomy | autopilot + owner_loop | Brain-facade зорилгын хавтгай дахь холбоо |
| Knowledge | knowledge_base + concept_former | Obsidian 2-way sync (odoo 1-way) |
| Searching | winner_searcher | Deep research (review + sentiment + competitor) |
| Feedback | outcome_recorder routes | Causal attribution (ямар rule ямар outcome үүсгэв?) |

---

## 10 Track — эрэмбээр

### Track 1 · Learning-loop synthesis (revenue-critical)

**Зорилго:** 3+ ижил failure → avoidance rule, 5+ validated pattern
→ rulebook entry. Launch_learner + outcome_recorder + principle_
extractor хоорондын гүүр барина.

**Deliverables:**
- `core/learning/rulebook.py` — unified RuleBook (rules + origin +
  confidence + applied_count + outcome_ema)
- `core/learning/pattern_miner.py` — episode miner that turns 3+
  similar events into a proposal
- `shopai brain-learned` CLI
- Тест: 15+

### Track 2 · Memory consolidation (knowledge growth)

**Зорилго:** Memory нь өөрөө дэвшинэ. Episodic event дахин давтагдвал
semantic concept, concept их хэрэглэгдвэл procedural skill.

**Deliverables:**
- `core/memory/consolidator.py` — Episode→Concept→Procedure ladder
- Staleness decay: 90 хоног хэрэглэгдээгүй concept → cold storage
- `shopai memory status` CLI
- Тест: 12+

### Track 3 · Data quality + source fusion

**Зорилго:** Source trust хурцжих. Өөр source-аас ирсэн ижил product
→ нэг merged candidate, higher confidence.

**Deliverables:**
- `core/data/source_trust_calibrator.py` — per-source hit-rate EMA
- `agents/research/candidate_fusion.py` — cross-source dedup + merge
- WinnerSearcher-д шинэ хэрэглээ
- Тест: 10+

### Track 4 · Decision rationale ledger

**Зорилго:** Бүх шийдвэр auditable. Owner "яагаад product X launch
хийсэн бэ?" гэхэд бүрэн гинжин хэлхээг хариулна.

**Deliverables:**
- `core/decision/rationale_ledger.py` — input → rules → verdict trace
- Replay function: `ledger.replay(decision_id) → explanation`
- Activator + publisher + autopilot hook-ууд
- `shopai why <decision_id>` CLI
- Тест: 12+

### Track 5 · Execution verification (post-write drift catcher)

**Зорилго:** Shopify / Meta руу бичсэний дараа read-back шалгана.
Drift байгаа бол compensate эсвэл alert.

**Deliverables:**
- `execution/verify/post_write_verifier.py` — after create/update,
  read the resource and diff vs expected
- Drift → outcome event with kind="execution_drift"
- SmartExecutor hook нэмнэ
- Тест: 10+

### Track 6 · Obsidian bidirectional

**Зорилго:** Vault 2-way sync. Owner vault-д `Decisions/avoid_plastic.md`
бичвэл → behavioral_constraint_registry picks up; brain insight →
vault-д Markdown ноут үүсгэнэ.

**Deliverables:**
- `core/adapters/obsidian/read_back.py` — vault note → constraint
- Note schema: frontmatter `{kind, scope, active}`
- Тест: 10+

### Track 7 · Deep research agent (searching breadth)

**Зорилго:** Product-ын эргэн тойрон дан catalogue-оор биш, review
+ sentiment + competitor-оор мэдээлнэ.

**Deliverables:**
- `agents/research/deep_research.py` — review scrape + sentiment
  + competitor matrix
- Free sources эхэлж: Amazon review API (public RSS), DuckDuckGo
  text search
- Тест: 12+

### Track 8 · Source staleness + freshness tracker

**Зорилго:** Brain мэдэж байна: энэ concept 35 хоногийн өмнөх, энэ
3 өдөр. Шийдвэрт freshness жинлэнэ.

**Deliverables:**
- `core/memory/freshness_tracker.py` — last_seen + access_count per
  memory row
- Шийдвэрүүд freshness-оор жинлэгдэнэ (шинэ data = илүү итгэл)
- Тест: 10+

### Track 9 · Brain cross-module synthesizer

**Зорилго:** 42 module-ийн snapshot-ыг нэг "Brain State" болгоно.
Mood + bottleneck + insights + risk + crisis зэрэг синкретик тайлан.

**Deliverables:**
- `core/brain/brain_state_synthesizer.py` — `snapshot()` → holistic
  BrainState with priorities
- `shopai brain status` CLI
- Тест: 10+

### Track 10 · World model outcome calibration

**Зорилго:** World model нь prediction-ийг outcome-той харьцуулж
давхар саатал дүгнэнэ.

**Deliverables:**
- `core/brain/world_model_updater.py` (бий) дээр calibration hook
- Prediction error → drift alert
- `shopai predict <action>` CLI (what-if preview)
- Тест: 10+

---

## Эрэмбийн үндэслэл

| Track | Dollar-distance | Risk | Effort |
|-------|-----------------|------|--------|
| 1 Learning synth | ↓↓ (прогноз сайжрах) | low | medium |
| 2 Memory consolidate | ↓ | low | medium |
| 3 Data fusion | ↓↓ | low | medium |
| 4 Rationale ledger | (observability) | low | medium |
| 5 Exec verify | ↓↓↓ (bug catch) | low | medium |
| 6 Obsidian 2-way | ↓ | low | small |
| 7 Deep research | ↓↓ | medium | medium |
| 8 Freshness | ↓ | low | small |
| 9 Brain synth | (observability) | low | small |
| 10 World calib | ↓↓ | medium | medium |

Хамгийн дээд ROI: **Track 1 → Track 5 → Track 3 → Track 4**. Эхний
2 track revenue-facing шийдвэрийн чанарыг шууд ахиулна; Track 5
нь production safety; Track 3 winner breadth + trust.

---

## Commit cadence + §4c.K

- Track бүр 1-3 commit-т багтана (module + wire + CLI).
- Track бүрийн төгсгөлд §4c.K self-check дурдаж commit message-д
  оруулна.
- Dollar-distance: 1 commit-т хүрсэн хэвээр үлдэнэ (credentials
  заагдахад live). Track-ууд нь хөгжлийн depth, breadth-ийг
  нэмэх.

---

## Хэрхэн явах вэ

1. Ship энэ docs/AGI_HARDENING_PLAN.md.
2. Track 1-ээс эхэл.
3. Track бүр: plan → build → test → wire → commit → push → status
   report.
4. §4c.K fail бол stop → re-read plan.

_Энэ нь живо баримт бичиг — track дуусахад статус энд шинэчилнэ._
