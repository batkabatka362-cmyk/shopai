# ShopAI AGI Roadmap

> Бодит AGI түвшинд — MVP биш. Mission-ийн дагуу (CLAUDE.md): owner нь
> зорилго тавина, AI-г 100 SKU × 10 хэв маяг долоо хоногт launch
> хийгдтэл автоматаар эзэмших. Доорхи модулиуд байгаа brain-ийн дээр
> *revenue-driver* давхаргаа угсарна.

---

## Зарчмууд

1. **Determinism-first.** 95/5 дүрэм. Эхлээд `heuristic_bank` +
   deterministic adapter туршиж үз, LLM сүүлчийнх.
2. **Idempotent actions.** "Set X to absolute Y" — increment/decrement
   гадуур API-руу огт бичиж болохгүй.
3. **Closed-loop.** Execute хийсэн бүх action нь outcome event-тэй.
   Outcome event үгүй бол deploy хийхгүй.
4. **Live gate.** `enable_live_execution=true` үед paranoid pipeline
   (`execution/smart_executor.py §G`) бүх алхмыг дамжих ёстой.
5. **Budget capped.** Cycle бүрт `compute_budget` нээгдэж, $0.10 / 30s
   caps-тай, алдагдсан тохиолдолд owner-т escalate.

---

## Track 1 — Ad platforms (Meta + TikTok + Google)

Одоо: `engines/ads_spy_competitive.py`, `core/intelligence/ads_intelligence.py`
(эдгээр scoring only). Meta/TikTok Ads руу **бичих** чадвар байхгүй.

### M1.1 `adapters/meta_ads/` — production-grade Graph API adapter
- Auth: long-lived access token + app secret (env-gate `META_ACCESS_TOKEN`).
- Endpoints: `campaign.create`, `adset.create`, `ad.create`,
  `insights.read`, `set_status({PAUSED|ACTIVE})`, `set_budget(absolute)`.
- Idempotency: каждый action нь `client_request_id` дамжуулна.
- Rate limiting: 200 calls/hour default, exponential backoff.
- Test: contract tests vs Meta sandbox + snapshot tests.

### M1.2 `adapters/tiktok_ads/` — TikTok Ads API
- ByteDance Developer Portal app + OAuth tokens.
- Similar shape: campaign / adgroup / ad / reporting / status / budget.
- Идэвхигүй бусдаар (M2 cycle).

### M1.3 `adapters/google_ads/` — Google Ads (Performance Max focus)
- OAuth 2.0 + developer_token.
- PMax campaign create from product feed.
- Retrieval: same Shopify product catalog → Google merchant feed.

### M1.4 Connector abstraction — `core/ad_platforms/registry.py`
- All adapters register into one interface: `launch()`, `pause()`,
  `set_budget()`, `kpi_snapshot()`.
- `campaign_optimizer` сонгохгүй платформоос үл хамаарах.
- Cross-platform budget routing: если ROAS 5.0 on Meta vs 3.0 on TikTok,
  reallocate budget via `revenue_strategy`.

### Brain integration
- `predictive_alerter` → cross-platform ROAS trajectories.
- `knowledge_transfer_prioritizer` → what worked on Meta pushed to TikTok.
- `behavioral_constraint_registry` → "don't raise budget on Fridays".

---

## Track 2 — Content factory (searcher → copy → video → publish)

Одоо: `core/intelligence/content_generator.py` бий ч winning-product search,
video generation байхгүй.

### M2.1 `agents/winner_searcher/` — autonomous winning-product discovery
- Sources: AliExpress dropshipper trending, Amazon BSR, TikTok product spy
  (via Apify or similar), Meta ad library.
- Pipeline: fetch → dedupe → score (margin × demand × saturation) → write
  to `core/memory/knowledge_base.py`.
- Уу: `relation_extractor` prose-оос "p1 is winner" гэхэд triple extract.
- Output: ranked list → `goal_decomposer.decompose("launch new SKU")`.

### M2.2 `agents/copywriter/` — structured ad-copy pipeline
- Input: product dict + buyer_segment profile.
- Prompt templates via `prompt_composer`.
- Two-stage: generate 5 hooks cheaply (Groq Llama 3.3) → score via
  `critic_panel` → pick winner.
- Cost cap: $0.005 per product via `compute_budget.spend("usd", ...)`.

### M2.3 `agents/video_generator/` — creative asset pipeline
- Replicate / Higgsfield / SDXL pipeline.
- Input: product image + hook text.
- Output: 9:16 + 1:1 variants uploaded to Shopify file storage.
- Cost cap: $0.05 per video.

### M2.4 `agents/publisher/` — orchestrate the stages
- Bundle via `action_bundle.bundle()`:
  1. create product on Shopify
  2. upload images/video
  3. set price + compare-at
  4. add to collection + publish
  5. launch $20/day ad on M1 adapter (default platform from ownership prefs)
- Bundle rollback: on any failure, reverse-order compensation.

### Brain integration
- `imitation_learner` — наблюдать 100 successful launches → шаблон болгох.
- `workflow_bottleneck_detector` — тус бүрийн stage latency.
- `intention_tracker` — "I will publish X by end of day" declared,
  resolved by actual publish event.

---

## Track 3 — Outcome loops & attribution

Одоо: `core/brain/attribution.py` бий (last_click / linear / shapley).
Харин loop хаалттай байхгүй — action_id → outcome_event mapping огт
бичигддэггүй.

### M3.1 `core/attribution/outcome_recorder.py`
- Every executed action returns a deterministic `action_id`.
- Shopify order webhook carries `attribution_source={action_id}`.
- On order event, `record_outcome(action_id, kpi='revenue', value=...)`.
- Брэйн side effects:
  - `meta_reasoner.record(decision_id=action_id, confidence=..., outcome_positive=...)`
  - `world_model_updater.record(predictor_id='campaign.roas', predicted=..., observed=...)`
  - `capability_registry.update(name='launch_sku', ok=...)`
- `funnel` event: purchase → `revenue_funnel.record('purchase')`.

### M3.2 Webhook subscriber — `execution/webhooks/`
- Shopify webhook registration on store_configurator setup.
- Handlers for `orders/create`, `orders/paid`, `refunds/create`,
  `products/update`, `customers/create`.
- Each handler normalizes + hands off to `outcome_recorder`.

### M3.3 Closed-loop report — `core/intelligence/outcome_report.py`
- Weekly digest built from last 7 days of (action, outcome) pairs.
- Top wins, top losses, Shapley-weighted channel credit.
- Feeds `self_revision_journal` with proposals: "kill at ROAS<1.3 would
  have saved $X based on N historical cases".

### Brain integration
- `evidence_accumulator` — each claim's (α,β) posterior updated from
  outcomes.
- `principle_extractor` — after N confirmations, distil common rules.
- `knowledge_freshness_tracker` — refresh relevant facts on every outcome.

---

## Track 4 — Multi-store federation

Одоо: `core/multi_store/`, `multi_store_brain.py`, `multi_store_federator.py`
бий, but idle — хоёрдох store нэмэхэд тохиргоо хийхгүй.

### M4.1 Store onboarding workflow
- CLI command: `shopai store add <alias> --url=<shop> --token=<token>`.
- Creates isolated per-store memory layer but shared brain facade.
- Broadcasts capability_registry + value_weighter to new store.

### M4.2 Knowledge bus
- When a rule/pattern is validated on store A,
  `knowledge_transfer_prioritizer.rank()` selects top-N to push.
- Message schema: `{subject, rule_body, source_store, evidence_score}`.
- Target store runs `coherence_checker.check()` before adopting.

### M4.3 Collective decision_reversal_detector
- Aggregate across stores: if 3 stores all flip-flop on the same decision
  within a week, promote to owner-attention.

---

## Track 5 — Owner dialog & autonomy

Одоо: `dashboard.py` static metrics, no bidirectional channel.

### M5.1 Weekly digest → owner chat (Telegram/Slack/WhatsApp adapter)
- `agents/digest_sender/` formats `weekly_digest` + `active_insights`
  into one chat message.
- Buttons: ✅ Apply proposed revisions, 🛑 Pause store, 📊 Show details.

### M5.2 Chat → brain actions
- `core/intent_parser.py` on the owner's response.
- `clarification_dialog` when ambiguous.
- `behavioral_constraint_registry.register(...)` when owner declares
  "don't touch pricing before 9am".

### M5.3 Emergency escalation
- If `mood_model.is_stressed` AND `compute_budget over` AND
  `follow_through_rate < 0.5`, escalate to owner with
  `readiness_gate.stand_down`.

---

## Track 6 — Long-horizon strategic planning

Одоо: `goal_compiler`, `goal_decomposer` plan execution. Худалдаа
эрхлэх гэх мэт 3-month horizon байхгүй.

### M6.1 Quarterly goal compiler
- Owner goal: "hit $50k/month by Q3".
- `scenario_planner` produces 3 scenarios (aggressive / balanced /
  conservative) with weekly milestones.
- Each milestone → `intention_tracker.declare(...)`.

### M6.2 Milestone monitor
- Daily cycle checks milestone progress.
- `principle_extractor` once per week distils learnings into quarterly
  notes.
- `episode_summariser` archives each milestone to vault.

### M6.3 Quarterly review workflow
- `insight_synthesizer.synthesise` with 90-day windows.
- `proposal_arbiter` winnows ~20 rule proposals down to the top ~5.
- `self_revision_journal.accept` applied en masse after owner approval.

---

## Track 7 — Safety & economics

### M7.1 Live-execution paranoid mode finalisation
- `execution/smart_executor.py` — verify steps 1-7 (pre-flight, dry-run,
  confirm, backup, execute, verify, record) всё wired.
- `action_safety_guard` + `readiness_gate` + `behavioral_constraint_registry`
  all consulted before any live write.

### M7.2 Kill switch
- One env var `SHOPAI_HARD_STOP=1` halts all writes immediately.
- `self_test_harness` runs on cycle start; any failure → hard stop.

### M7.3 Financial tripwire
- `compute_budget` tracks USD spent on LLM + ads combined.
- Over cap → all writes blocked, owner paged.

---

## Priority ordering

| Дараалал | Track | Тайлбар |
|---|---|---|
| **P0** (this week) | Track 1 M1.1 | Meta Ads adapter — real ad-write capability unlocks revenue trials |
| P0 | Track 3 M3.1 | outcome_recorder — closes loop on current phase hooks |
| P1 | Track 2 M2.1 | winner_searcher — identifies SKUs worth launching |
| P1 | Track 3 M3.2 | Shopify webhooks — real outcome events |
| P2 | Track 2 M2.4 | publisher bundle — 20-step launch one-click |
| P2 | Track 5 M5.1 | weekly digest → chat |
| P3 | Track 4 M4.1 | multi-store onboarding |
| P3 | Track 6 M6.1 | quarterly goal compiler |
| P4 | Track 7 M7.3 | financial tripwire |

---

## Success criteria

ShopAI бол "AGI түвшинд" гэж хэлэхдээ:

1. **Owner 1 мөр goal өгөөд 20 алхмыг бие даан хийнэ** (current gap:
   Meta Ads adapter + publisher bundle).
2. **Outcome bvrt tsaashaa rule болно** — 100 SKU × 10 launch дараа
   "winner looks like X" гэсэн rule автоматаар үүсэж, нэмэлт хөрөнгө
   оруулалтгүйгээр шинэ SKU-гийн ROAS-ийг дундажаар эсвэл түүнээс их
   байлгана.
3. **Cycle cost < $0.10** — `compute_budget`-аар баталгаажуулагдсан.
4. **7-day WoW revenue хэвийн өсөлттэй** — бэлэн `revenue_strategy`
   module-ийн тайланг тулгуурлан хянана.
5. **Өөрийгөө засах чадвар** — `self_revision_journal.applied` count
   > 10/month бөгөөд owner зөвшөөрөлтэй хэрэглэгдэж байх ёстой.

---

_Last updated: v39 cycle start. Owner has brain infrastructure; next
push is revenue-facing adapters._
