# AGI Mission Plan — ShopAI

> Бодит AGI-ийн түвшинд — MVP/demo биш, бодит орлого гаргадаг, өөрөө
> сурдаг, өөрөө засдаг, өөрөө brand + company болж хөгждөг autonomous AI.
>
> Энэ баримт бичиг нь **бодит статус** + **хэдэн сарын төлөвлөгөө** —
> §4c.K self-check дүрмийг дагах үед stop хийж энд буцаж орж ирнэ.

---

## Part A — Шударга одоогийн үнэлгээ

### Юу бодитой болсон бэ

1. **Brain infrastructure — 42 module** (v33-v38)
   - Calibration, drift, funnel, predictive alerts, mood, budget,
     heuristics, intentions, coherence, capability registry, ...
   - 840+ тест, бүгд `brain_facade`-аар reachable
   - `core_orchestrator.run_cycle`-д hook-ууд холбогдсон
2. **Outcome closed loop (хэсэгчилсэн)**
   - `OutcomeRecorder` + Shopify order webhook → brain learners
   - Calibration / prediction / capability / funnel / mood fed on
     every paid/canceled order
   - **BUT**: decision_id захиалгад хэр бодитоор очихгүй байгаа
     (AUDIT_LOG P2) — learners "decision_id: nil" гэж авдаг
3. **Meta Ads adapter production-hardening**
   - Retry/backoff, idempotency (`_client_request_id`), brain hook
   - Capabilities: create_campaign / update_budget / pause / resume
     / get_performance
   - **BUT**: adset + ad creation байхгүй, эцэст нь зөвхөн "хоосон
     campaign үүсгэх" боломжтой
4. **Winner searcher skeleton**
   - Framework, `WinnerSource` ABC, `StaticWinnerSource`, scoring
   - **BUT**: бодит source 0 — AliExpress / Amazon / TikTok spy
     crawler байхгүй

### Юу хараахан бодитой биш вэ

| Цоорхой | Одоогийн төлөв | Бодитоор хэрэгтэй |
|---|---|---|
| **Real ad spend loop** | adapter бэлэн, strategy нь call хийхгүй | автомат budget allocation + scaling |
| **Content factory** | copywriter, video, image огт байхгүй | AliExpress image → hook копия + 9:16 видео → Shopify |
| **Peer learning** | модуль 0 | top Shopify store-уудыг observation-р ажиглаж суралцах |
| **Social / brand** | 0 | Instagram / TikTok / FB Page post + DM |
| **Customer dialog** | dialog_memory бий, каналл 0 | owner ↔ AI chat (Telegram), customer ↔ AI (чат widget) |
| **Company layer** | per-store only | LLC setup, multi-store aggregation, тайлан |
| **Self-observation of public web** | 0 | brain нь meta ad library, TT Creator Center шалгадаг байх |
| **Long-horizon strategy** | goal_decomposer бий, одоог тавьдаггүй | quarterly goals milestone-той |

### §4c.K self-check (энэ sprint дуусах дээр)

1. **Mission fit?** Сүүлийн 7 commit (outcome_recorder → iter 3
   summary-surface) — *infrastructure-plumbing*. **Revenue-facing NO**.
2. **Plumbing vs capability?** ~6:1 plumbing. **Pivot шаардлагатай.**
3. **Month-tomorrow test?** Энэ plumbing нэг сар нэмэлт хийсэн ч
   Shopify order нэг ч нэмэгдэхгүй. Шалгаж тэнцэхгүй.
4. **Dollar distance?** Одоогийн ажлаас $ event-тэй хүрэх хамгийн
   богино зам — **6+ commit** (strategy hook adapter → winner
   source → ad launch → Shopify attribution → checkout URL → order
   webhook). 4-өөс хэтэрч байна. **Plan буруу.**

**Верд:** Infrastructure-ийг хангалттай tune хийсэн. Одоо зөвхөн
revenue-facing капабилити барих цаг.

---

## Part B — Үнэ цэнэ гаргах эрэмбэ: "dollar distance" минимум

Дараах шалгуур дагана:
- Commit бүр dollar-distance-ыг багасгасан байх
- Шинэ infrastructure module одоо НЭМЭХГҮЙ — байгаа 42 модулийг
  revenue-path руу залгана

### Trunk track: winner → content → ad → order → learn

Энэ нь нэг хурдан замтай, дараалсан 7 commit-ын хэлхээ. Бүр commit
дуусахад dollar-distance багасна.

```
[winner_source] → winner_searcher populates knowledge_base
     ↓
[copywriter]   → takes winner dict, outputs hook + body + CTA
     ↓
[creative_gen] → takes winner image + hook, outputs 9:16 video
     ↓
[publisher]    → creates Shopify product + uploads media + sets price
     ↓
[ad_launcher]  → MetaAdsAdapter.create_campaign with UTM = decision_id
     ↓
[attribution]  → Shopify order note_attributes[shopai_decision_id]
     ↓
[learner]      → OutcomeRecorder → all v33-v38 brain learners
```

- Эхний **winner_source**-ыг барихад `winner_searcher` гуравдагч
  эх үүсвэрт ашиглагдана (өнөөдрийг хүртэл static зөвхөн).
- **attribution leg** бол одоо байгаа AUDIT_LOG P2 — checkout URL-д
  UTM parameter нэмэх + Shopify liquid snippet өгөх.

### Parallel tracks (trunk-аас ангид урагшлана)

**T2 — Peer learning:**
- `agents/research/peer_store_observer.py`: top 100 Shopify dropshipper
  store-уудыг хэлбэрийн зан төлөвтэй scrape (theme style, price
  bands, collection layout, homepage copy hook)
- `concept_former`-д feed → "high-AOV pet niche is trending gray tones
  + single-hero layout" гэх patterns autoматаар формат

**T3 — Social / brand:**
- `adapters/instagram_posting/` + `adapters/tiktok_posting/`
- Post timing via `time_scheduler` + template via `prompt_composer`
- Brand voice registry (`core/brain/brand_persona.py`) — tone /
  vocabulary / hashtag список

**T4 — Owner dialog:**
- `adapters/telegram_bot/` + `adapters/slack_bot/`
- Weekly digest via `weekly_digest.compose` + buttons (✅ apply,
  🛑 pause, 📊 details)
- `clarification_dialog` + `intent_parser` on owner replies
- `behavioral_constraint_registry.register(...)` via chat

**T5 — Customer dialog:**
- Shopify chat widget webhook → `dialog_memory`
- Answer FAQ via `knowledge_base.recall`
- Escalate to owner when `coherence_checker` flags uncertainty

**T6 — Company layer:**
- `core/multi_store/federator.py` бий, gate-гүй
- Onboarding CLI: `shopai store add`, `shopai company bind <llc>`
- Per-company P&L roll-up, quarterly goals

---

## Part C — Хагас сарын sprint plan

### Sprint 1 (week 1-2) — "First real $ event"

Trunk track хамгийн их нөлөөтэй 5 commit:

| # | Commit | Dollar-distance эффект |
|---|---|---|
| 1 | `adapters/aliexpress/winner_scraper.py` — `WinnerSource` impl | winner_searcher бодит product-уудыг discover хийж эхэлнэ |
| 2 | `agents/content/copywriter.py` (Groq Llama 3.3 route) | winner → ad hook + product description |
| 3 | `adapters/replicate/video_generator.py` | copy + image → 9:16 video |
| 4 | `execution/publisher_bundle.py` (action_bundle) | Shopify product go-live |
| 5 | Shopify liquid snippet + Meta Ads UTM injection | decision_id захиалгад хүрэх |

Дуусахад: **bootstrap-ийн хамгийн том хэсэг** — нэг товчлуураар
AliExpress → Shopify → Meta Ads → Shopify order хаалттай loop.

### Sprint 2 (week 3-4) — "Self-improvement from outcomes"

Одоо данс гаргаж, learning loop-ийг идэвхтэй болгоно:

- Sprint 1-ийн хэдэн SKU launch дараа `principle_extractor` run
- `proposal_arbiter` нь auto-generated rules-г approve workflow-оор
  → `self_revision_journal.applied`
- Owner weekly digest (Telegram) буттон-тай

### Sprint 3 (month 2) — "Peer learning + brand voice"

- `peer_store_observer` top 100 scraper (Sprint 1-д basic нь бий;
  Sprint 3-д top 100 seed + trend-aware pattern mining)
- `brand_persona` тохиргоо (tone / palette / hashtag)
- Instagram posting adapter (basic)

### Sprint 4 (month 3) — "Multi-channel + company"

- TikTok posting + ads
- Customer dialog widget + escalation
- Company onboarding CLI
- Quarterly goal compiler

---

## Sprint 1 — бодит төлөв (2026-04-20)

14 commit-ийн дараа:

**Ship хийгдсэн (bodit):**
- M3.1 `outcome_recorder` — Shopify order → brain loop closed
- M1.1 Meta Ads adapter hardening — retry + idempotency + brain hook
- `publisher_bundle` — transactional winner → Shopify + PAUSED Meta
- `campaign_activator` — readiness + constraints + approval gate
- `shopify_attribution` snippet + `ensure_attribution` webhook reg
- `health_check` + `shopai doctor` — actionable readiness diagnostic
- `ManualSeedSource` — file-based winner seed
- `PeerStoreObserverSource` — public `/products.json` observer
- `autopilot` — winner → publish → activate full chain
- CLI: `doctor`, `publish`, `activate`, `publications`, `activations`,
  `autopilot`

**Dollar-distance verdict:** 0 commits from $. Owner needs:
  * Shopify Admin API token + store URL
  * Meta Ads access_token + ad_account_id
  * Одоогоос `shopai autopilot --live` → бодит order-д хүрнэ

**Хадгалагдсан гап-ууд (Sprint 2-т орно):**
- CJDropshipping API source (API key хэрэгтэй)
- AliExpress scraper (fragile, experimental)
- `niche_discoverer` — trend data → niche clustering (owner #5)
- Shopify webhook daemon (webhook эвент ирэх endpoint-ыг host-ожа)
- Meta Ads AdSet + Ad creation (одоо зөвхөн campaign)
- Content factory B-trend (image/video generation)

## Sprint 2 plan (хамгийн ойрын)

**Гол зорилго:** Sprint 1-ийн pipeline автономыг **outcome-driven
self-correction**-оор хаах. Өмнөх launch-уудын outcome-оор дараах
launch-уудыг автомат засдаг болох.

**Зорилго:** Trend-driven niche discovery + closed-loop rule
promotion.

### S2-1: `niche_discoverer` module
- Input: WinnerSource-уудаас ирсэн N candidate-ын pool
- Process: title keyword clustering → niche labels
  (pet / kitchen / fitness / beauty / gadget / style)
- Output: per-niche rollup (avg_margin, count, saturation,
  demand-band, trend direction)
- Brain hook: `concept_former.observe` per niche signature
- CLI: `shopai niches` — top 10 niches by current trend score

### S2-2: Outcome-driven launch-pattern extraction
- After N launches via `autopilot`, run `principle_extractor` on
  `episode_summariser`-ийн Wins vs Losses
- Validated rules go through `proposal_arbiter` → owner approval
  list → `self_revision_journal.applied`
- CLI: `shopai principles` — top distilled launch-rules

### S2-3: Weekly digest → dialog
- `agents/digest_sender/` — `weekly_digest.compose` + top insights
- Simple stdout mode first (Sprint 2); Telegram/Slack Sprint 3
- Fields: Wins, Losses, Active insights, Pending proposals,
  Dollar-this-week

### S2-4: Autopilot loop daemon
- `scripts/autopilot_loop.py` — calls `shopai autopilot` on a
  `--interval` cadence
- Respects `compute_budget` daily caps
- Writes one summary per run to `data/autopilot_loop.log`

### S2-5: AliExpress + CJ sources (real 3rd-party supply)
- `CJDropshippingSource` — real API (CJ_API_KEY env)
- `AliExpressScraperSource` — experimental (best-effort scraping)

### S2-6: ACTIVE flip owner dialog (reversible)
- If `CampaignActivator` returns verdict=pending, write to
  `data/pending_activations.json` with a `shopai approve <id>` /
  `shopai reject <id>` CLI

Sprint 2 criteria: 5+ launches via autopilot → 1+ distilled rule
applied via self_revision_journal → 1 niche flagged by
niche_discoverer as "trend direction=rising".

---

## Part D — AGI-ийн тодорхойлолт (success criteria)

Эдгээр criteria бүгд биелэгдвэл "AGI түвшинд" гэж нэрлэж болно:

1. **Autonomous $ event.** Owner нь 1 URL + $200 budget өгнө; 15
   минут дотор Shopify store дээр live product + Meta Ads live
   campaign + first view impression. 7 хоногийн дотор first
   Shopify order. *(Measurement: run a cycle and point at it.)*
2. **Self-correcting.** 3 өдрийн дараа ROAS < 1.5 нь автомат
   kill → `self_revision_journal` дэх rule + `episode_summariser`
   дэх lesson хоёул үүссэн байна. *(Measurement: vault file
   existence.)*
3. **Cross-store knowledge transfer.** Store A-д validated rule,
   store B-д 1 week-ийн доторх adoption via
   `knowledge_transfer_prioritizer`. *(Measurement: federation log.)*
4. **Brand evolution.** 30 хоногийн дараа Instagram/TikTok
   accounts-аас follower+post growth, tone consistency > 0.8 per
   `coherence_checker`. *(Measurement: post metrics + tone score.)*
5. **Cost discipline.** Cycle бүрт LLM spend < $0.10, ad spend +
   profit нь owner-ийн goal-той тохирч байна. *(Measurement:
   `compute_budget` archive.)*
6. **Owner dialog.** Weekly digest автомат илгээгдэнэ, owner
   хариулт 24 цагийн дотор action-д хувирна. *(Measurement:
   digest→response→applied chain.)*
7. **Self-observation.** `peer_store_observer` нь 7 хоног тутам
   top 100 stores-ийг шинэчилдэг, brain нь тэдгээрийг observing
   хийснээр 3+ шинэ pattern үүсгэдэг. *(Measurement:
   `concept_former.stats`.)*

---

## Part E — Бодит Rabbit-hole хориглол

Дараах зүйлсийг **хийхгүй** (бусад нийт sprint-ийн хүртэл):

- Шинэ brain module нэмэх (42 module хангалттай, тэднийг энгийн
  wire хийхээс өмнө 42+ болгох нь plumbing-capability харьцаа
  буруу болно)
- `engines/` дотор ~2500 модульуудаар sweep хийх (худалдан авагчийн
  зам тэр модуль нараас ирэхгүй)
- LLM прагмент чанарыг сайжруулах оролдлого (Groq + Gemini + DeepSeek
  хангалттай)
- Түр зуурын infrastructure (new DB backend, custom HTTP client,
  etc.)

**Exception:** pre-existing pipeline bug олдсон + revenue-path-
ыг хааж байвал §4c discipline дагаж дориуд fix.

---

## Part F — Иж бүрэн дуусах хүртэл

Sprint 1–4 амжилттай дуусахад:

- Owner 1 URL өгсөн 15 минут дараа live store + live ads + тохиргоо
- 7 хоногийн дотор first order, 30 хоногт first 10 orders
- 3 сарын дараа first $10k/month (агрессив target, success metric-
  мон 50% biz-мон өсөлт)
- ShopAI нь өөрөө Telegram-аар owner-тай chatлана, Instagram-д
  автомат пост, TikTok-д autopost, "ROAS<1.3 auto-kill rule should
  relax after 5 days" гэх мэт санал болгодог

**Энэ бол realistic нэг сар** — MVP биш, бодит ажил.

---

_Энэ plan нь §4c.K self-check-ээс гарах замыг зааж өгч байна._
_Одоогийн commit дараа sprint 1 commit #1 эхэлнэ: aliexpress_
_winner_scraper. Дэвтэрт хүрэх алхам 3-т буурна._
