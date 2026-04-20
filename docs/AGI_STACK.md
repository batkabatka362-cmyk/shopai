# ShopAI AGI stack — 10 layers

> Archived architecture document. Updated when a new layer is added
> or an existing one changes scope. Reading order: bottom-up.
>
> Companion docs:
>   * `docs/AGI_MISSION_PLAN.md` — dated sprint plan
>   * `docs/AUDIT_LOG.md` — pre-existing bugs / rabbit-hole deferrals
>   * `CLAUDE.md §4c` — autonomous operation rules

---

## Зорилго (owner-defined)

Бодит AGI түвшинд — MVP биш. Дропшиппинг store + ads + content +
brand + autonomy + self-improvement. Owner нь зорилго тавина, AI
нь автомат:

  * winner discover → launch → ads → monitor → kill/scale
  * learn from outcomes → self-revise rules
  * adapt niche per quarter from trend data
  * operate with owner-approved limits + legal/tax compliance

Markets бодит туршилт: **US + EU**. Зардал зарчим: **маш яралтай,
бага зардлаар эхлэх**.

---

## Owner's 12 original pillars → 10 layer stack

Owner сонгосон 12 pillar:

1. learning data loop - data memory knowledge
2. searching - web and deep and research
3. ads and content
4. shopify setup бүхэл зүйл
5. products brand and niche
6. brain intelligence
7. risk and money management - legal and tax
8. rule and flow and limit
9. test simulation
10. skills - decision execution - input and output
11. marketing SEO
12. planning and strategy

After reorganisation (3 overlaps collapsed, 6 missing added), 10
capability layers + 6 extended layers emerge.

**Collapsed overlaps:**
  * `learning loop` + `brain intelligence` → L3 (memory, state) +
    L9 (loop, process)
  * `rule + flow + limit` + `risk + money` → L7 (both live under
    governance, separated by hardness)
  * `planning + strategy` = `brain intelligence` → L4

**Added layers (not in owner's 12):**
  * **Customer** layer (support / reviews / retention)
  * **Fulfillment** layer (orders → shipping → tracking)
  * **Social presence** layer (posts / community — beyond SEO)
  * **Crisis response** layer (fraud / ban / chargeback spike)
  * **Multi-store federation** (1 brain → N stores)
  * **Owner dialog** layer (bidirectional chat channel)

---

## The 10 layers (bottom-up)

```
┌────────────────────────────────────────────────────────────┐
│  L10. AUTONOMY & SELF-GOVERNANCE                            │
│       §4c.K self-check · dollar-distance · digest cadence  │
│       cycle orchestrator · daemon loop · emergency halt    │
├────────────────────────────────────────────────────────────┤
│   L9. LEARNING LOOP                                         │
│       outcome → episode → rule → journal → applied         │
│       drift detection · principle extraction · arbiter     │
├────────────────────────────────────────────────────────────┤
│   L8. TEST & SIMULATION                                     │
│       dry-run · what-if · A/B · backtest · canary          │
│       pre-flight checks · counterfactual                   │
├────────────────────────────────────────────────────────────┤
│   L7. GOVERNANCE & COMPLIANCE                               │
│       [rules]  behavioral_constraint_registry (soft)       │
│       [risk]   risk_tripwire (hard $ + margin caps)        │
│       [legal]  tax + VAT + disclaimers + ToS               │
│       [ethics] ethics_gate (moral/policy)                  │
├────────────────────────────────────────────────────────────┤
│   L6. SKILLS (capability registry)                          │
│       discover · create · publish · promote · monitor      │
│       interact · decide · niche adapt                      │
├────────────────────────────────────────────────────────────┤
│   L5. ACTION EXECUTION (effectors)                          │
│       Shopify · Meta · TikTok · Google · Instagram         │
│       email · content-gen · fulfillment · customer-chat    │
├────────────────────────────────────────────────────────────┤
│   L4. REASONING & INTELLIGENCE                              │
│       world_model · hypothesis · causal · counterfactual   │
│       goal_decomposer · planning · strategy                │
├────────────────────────────────────────────────────────────┤
│   L3. MEMORY & KNOWLEDGE                                    │
│       episodic · semantic · procedural · meta · graph      │
│       freshness tracker · concept former · principle       │
├────────────────────────────────────────────────────────────┤
│   L2. PERCEPTION (inputs)                                   │
│       Shopify feed · peers · ads · search · trends         │
│       customer · competitor · financial · legal            │
├────────────────────────────────────────────────────────────┤
│   L1. INFRA & ADAPTERS                                      │
│       HTTP · SQLite · brain_facade · retry · idempotency   │
│       auth · rate-limit · observability                    │
└────────────────────────────────────────────────────────────┘
```

---

## The 6 extended layers (cross-cutting)

Зарим нь стакаас гадуур, бусад layer-ийг зүсдэг:

### LX.1 Customer experience (cuts L2 + L5 + L6)

Бусад layer-уудаас хараат. L2-оос reviews + tickets ирнэ; L5-аар
chatbot + refund executor; L6 дээр support skills бий.

Modules:
  * `customer_intelligence` (reviews, NPS)
  * `support_chatbot` (FAQ, escalation)
  * `refund_handler` (auto-process policy-matching refunds)
  * `retention_scheduler` (winback emails)

### LX.2 Fulfillment / supply chain (cuts L5 + L7)

  * `autods_adapter` / `cj_fulfill_adapter`
  * `tracking_webhook` (carrier updates → customer comms)
  * `supplier_selector` (price × reliability)
  * `inventory_planner` (re-order points)

### LX.3 Social presence / brand (cuts L5 + L6)

SEO-аас дэвшилт: бие даасан content calendar + community.
  * `instagram_scheduler` + `tiktok_scheduler`
  * `brand_persona_registry` (tone / palette / hashtags)
  * `content_calendar` (posts per week × niche)
  * `community_responder` (comments / DMs)

### LX.4 Crisis response (cuts L7 + L10)

Fraud / ban / chargeback spike-д 5-минутын response:
  * `fraud_detector` (IP / velocity / BIN rules)
  * `chargeback_spike_alert`
  * `platform_ban_recovery` (backup store activation)
  * `emergency_halt` (one-env-var full stop)

### LX.5 Multi-store federation (cuts all layers)

1 brain, N store:
  * `multi_store_federator` (aleady exists — activate)
  * `cross_store_rule_transfer` via `knowledge_transfer_prioritizer`
  * `per_company_pnl_rollup`
  * `company_onboarding_cli`

### LX.6 Owner dialog (cuts L10)

Telegram/Slack 2-way channel — хамгийн ойрын ship-д:
  * `telegram_bot_adapter`
  * `digest_to_chat` (launch_digest → message)
  * `chat_command_parser` (approve / reject / pause / scale)
  * `owner_mood_tracker`

---

## Current state mapping — owner's 12 + 6 extensions

| Owner's pillar | Layer | Sprint 1-2 status | Sprint 3+ gap |
|---|---|---|---|
| learning data loop | L3 + L9 | ✅ v33-v38 brain + launch_learner | Semantic graph growth |
| search (web/deep/research) | L2 | 🟡 4 winner sources | Google Trends, TikTok trending, ad library, review scrape |
| ads and content | L5 + L6 | 🟡 Meta adapter + ContentGenerator | TikTok/Google ads write, video + image gen |
| shopify setup full | L5 | 🟡 ProductCreator + publisher_bundle | Collections, pages, metafields, theme, app install |
| products brand niche | L4 + L6 | 🟡 niche_discoverer | brand_persona_registry, pricing strategy |
| brain intelligence | L4 | ✅ strong | Deep causal chains, long-horizon planning |
| risk/money/legal/tax | L7 | 🔴 empty | **risk_tripwire (P0)**, tax adapter, chargeback monitor |
| rule + flow + limit | L7 | ✅ behavioral_constraint_registry | Soft rule templates per niche |
| test simulation | L8 | 🟡 dry-run | Real simulator (price × ROAS × revenue) |
| skills (I/O) | L6 | ✅ capability_registry | skill_gym expansion, skill composition |
| marketing SEO | L5 + L6 | 🔴 empty | Meta tags, schema.org, Google Merchant feed |
| planning + strategy | L4 | 🟡 goal_decomposer | Quarterly strategy, multi-channel budget |
| **customer** (added) | LX.1 | 🔴 empty | reviews, FAQ chatbot, refund auto-handler |
| **fulfillment** (added) | LX.2 | 🔴 empty | AutoDS/CJ fulfill, tracking webhook |
| **social presence** (added) | LX.3 | 🔴 empty | IG/TT scheduler, brand persona |
| **crisis response** (added) | LX.4 | 🟡 mood/failure bits | fraud detector, chargeback spike |
| **multi-store** (added) | LX.5 | 🟡 federator idle | onboarding CLI, rule transfer |
| **owner dialog** (added) | LX.6 | 🔴 empty | Telegram bot, digest-to-chat |

---

## Dependency rules

Higher layers MUST NOT skip lower layers. Concrete implications:

  * L5 (action) always goes through L7 (governance) — no direct
    Shopify / Meta write without passing risk_tripwire + behavioral
    constraints + budget check.
  * L9 (learning) always writes to L3 (memory), never direct-to-L7
    rules. Proposal → arbiter → journal → owner approve.
  * L10 (autonomy) reads from L9 (digest) and writes to L7
    (constraints adjust). Never directly to L4 or L5.
  * LX extensions plug into specific layers, never bypass them.

Violation of any of these = §4c.K fail, pivot.

---

## "Real work vs MVP" black/white per layer

| Layer | Real | MVP / demo only |
|---|---|---|
| L1 Infra | retry + idempotency + brain_hook | unwrapped HTTP |
| L2 Perception | multi-source + dedup + trust_calibrator | single stub source |
| L3 Memory | SQLite-persisted + hot-reload + schema | in-memory dict |
| L4 Reasoning | deterministic first + LLM only on fuzzy | "let me ask an LLM" pattern |
| L5 Action | dual-gate live + compensate | live-by-default |
| L6 Skills | capability_registry + proficiency EMA | hard-coded if/else |
| L7 Governance | hard caps + escalation + audit trail | print + hope |
| L8 Simulation | real backtest on cached data | "we'll test in prod" |
| L9 Learning | outcome → rule → journal → apply | log to file |
| L10 Autonomy | §4c.K self-check every 3 commits | "just run forever" |

---

## Cycle cost budget (per CLAUDE.md §4b/C)

| Resource | Cap per cycle | Governance |
|---|---|---|
| LLM cost (USD) | < $0.10 | `compute_budget.spend("usd", ...)` |
| Latency | < 30s | `compute_budget.spend("latency_ms", ...)` |
| API calls | < 500 | `compute_budget.spend("api_calls", ...)` |
| Ad spend (NEW, L7) | < $X/day, owner-set | `risk_tripwire.budget_check` |
| Margin floor (NEW, L7) | > 10% | `risk_tripwire.margin_check` |

---

## Stack-level contract summary

Any new module asks itself:

1. Which layer does this belong to?
2. Does it respect the layer-above → layer-below rule?
3. Does it plug into the capability_registry (L6)?
4. Does it have dry-run (L8) before live (L5)?
5. Is it gated through governance (L7)?
6. Does its output feed the learning loop (L9)?
7. Is it reachable via brain_facade or CLI (L10)?

If any answer is "no" or "unclear", STOP, re-read this doc, redesign.
