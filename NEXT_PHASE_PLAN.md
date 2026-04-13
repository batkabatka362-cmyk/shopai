# ShopAI — Next Phase Plan

**Direction set by project owner:**
> "Core бол маш чухал. Гэхдээ хийхдээ шинэ feature эсвэл шинэ program code бичихгүй.
> Ажилладаг App, tools, AI олоод ShopAI-тай холбох. ShopAI-н гол цөм нь core —
> бодох, шийдвэр гаргах, сайжрах, суралцах."

Translation: **Don't build new features. Find working apps/tools/AIs and connect them
to ShopAI. The core is what thinks, decides, improves, learns — that's what matters.
Everything else is external muscle the core should command.**

---

## The Principle

ShopAI's core (brain, memory, learning, decisions, goals) is at 9.85/10 after 20
fixes. That's the "mind." What it needs is **hands** — external working systems to
actually DO things. Writing those from scratch is wasted effort when production-grade
tools already exist.

**Goal of next phase:** Connect ShopAI to existing, battle-tested tools via adapters.
The core decides WHAT to do; the adapters execute it. No new business logic.

## Adapter-First Connection Strategy

### Principle
Each external system is wrapped in a thin adapter that:
1. Exposes a single `run(input) -> output` interface to the core
2. Handles the external system's auth, retry, rate limits
3. Translates ShopAI's internal decision schema into the tool's input format
4. Translates the tool's output back into ShopAI's memory/learning schema
5. Reports success/failure/score so ActionWeightStore can learn

The core already has an adapter-aware SmartRouter (from Phase 1-6 migration).
New adapters plug into that router.

### Shape of a new adapter
```python
# tools/<category>/<provider>.py
class XAdapter(BaseAdapter):
    capabilities = ["email_send", "email_template"]

    def run(self, payload: dict) -> dict:
        # call external API, return {"status", "score", "result"}
        ...
```

### Router already knows how to choose
`SmartRouter` routes by capability + weight + availability + cost. The core says
"I need `email_send`"; the router picks the best-scoring adapter, with fallback
to others on failure. ActionWeightStore then adjusts weights by observed outcome.

---

## Candidate External Systems to Connect

### Email Delivery
- **Resend** / **Brevo** — already adapter-wired (Phase 5)
- **SendGrid** — add adapter
- **Postmark** — add adapter

### SMS
- **Twilio** — SMS adapter
- **MessageBird** — SMS adapter

### Payment
- **Stripe** — create product, handle refund, dispute
- **PayPal** — dispute + refund

### Image Generation
- **DALL-E 3** (OpenAI API) — product photography
- **Stability AI** — background removal, upscale
- **Remove.bg** — background removal specifically

### Cloud LLMs (for when Ollama local is slow/down)
- **Claude API** — adapter already exists for routing, extend coverage
- **OpenAI GPT-4o** — fallback adapter
- **Groq** — fast inference adapter

### CRM / Marketing Automation
- **Klaviyo** — email flows, audience segmentation
- **HubSpot** — CRM, lead tracking
- **Omnisend** — email + SMS unified

### Workflow / Automation
- **n8n** — self-hosted workflow engine
- **Zapier** / **Make** — SaaS workflow
- **Temporal** — durable workflow (overkill?)

### Browser Automation (for tasks Shopify API can't do)
- **Playwright** — already-mature Python library
- **browserbase** — hosted Playwright

### Vector Search / RAG
- **Weaviate** / **Pinecone** — real vector DB (replace JSON similarity)
- **Qdrant** — self-hosted alternative

### Analytics / BI
- **Mixpanel** — already has adapter, extend
- **PostHog** — product analytics
- **Metabase** — dashboarding

### Customer Service
- **Intercom** — chat + ticketing
- **Crisp** — lighter alternative
- **Zendesk** — enterprise ticketing

### Competitor Intelligence
- **SimilarWeb API** — traffic + engagement data
- **Apify** — pre-built scrapers
- **Bright Data** — proxy network + scraping

### AI-Powered Tools (leverage existing AI)
- **Perplexity API** — research questions
- **Tavily** — AI search for market research
- **Exa** — neural search

---

## Priority Order (lowest-effort-highest-value first)

### Wave 1 — Core Hands (execution muscle)
1. **Stripe adapter** — payment/refund actions the core can already decide on
2. **SendGrid or Postmark adapter** — add 2nd email provider, test router fallback
3. **DALL-E 3 adapter** — product image generation for `refresh_images` action (Fix S added the decision option, now wire the execution)
4. **Playwright adapter** — browser automation for Shopify admin tasks not in API

### Wave 2 — Brain Upgrades (better thinking)
5. **OpenAI GPT-4o adapter** — cloud LLM fallback when Ollama is down/slow
6. **Claude API adapter extension** — already partially wired, complete it
7. **Weaviate adapter** — replace JSON vector storage in BrainMemory

### Wave 3 — Customer-Facing
8. **Klaviyo adapter** — real email marketing (replacing current campaign plan-only)
9. **Intercom adapter** — chat + ticket management
10. **Twilio adapter** — SMS notifications + recovery campaigns

### Wave 4 — Intelligence Layer
11. **Perplexity API adapter** — market research questions the brain already generates
12. **Tavily adapter** — real-time competitor intelligence
13. **SimilarWeb adapter** — competitor traffic/engagement

### Wave 5 — Workflow / Long-running
14. **n8n adapter** — delegate multi-step workflows to a proven engine
15. **Temporal adapter** (optional) — durable workflows for critical paths

---

## What the Core Does With New Adapters

The moment an adapter is registered:
1. **SmartRouter** auto-discovers it via the capability list
2. **ActionWeightStore** starts learning its success rate from first call
3. **DecisionBrain** can recommend actions that call its capability
4. **ExplorationBoost** will try it periodically to gather data
5. **GoalManager** will factor its success into goal effectiveness
6. **JudgmentAdvisor** will apply safety checks before first live call
7. **LearningLoop** will record outcomes + generate rules from patterns

The core is already built to handle this. **The core doesn't need more code — it
needs more hands.** Each adapter is ~100-200 lines; zero changes to core.

---

## Explicit NON-Goals

* **DO NOT** build new engines from scratch (49 stubs can stay stubs)
* **DO NOT** build new agents — 1 agent is enough for the core to prove itself
* **DO NOT** write new brain logic — the core is at 9.85/10, diminishing returns
* **DO NOT** write new memory backends — UnifiedMemory is the single entry point
* **DO NOT** replace UnifiedMemory — every fix from Fix D → Fix U routed through it
* **DO NOT** reorganize the folder structure — it works

## What "Done" Looks Like for Next Phase

Not: "We built N new engines."
Instead: "The core can now decide to send email/SMS/push, generate product images,
answer customer questions, and run competitive research — and each of those actions
is executed by a production-grade external tool, not our own code."

The test: **can ShopAI run a full autonomous cycle without any new business logic
being written by us?** The core decides, the adapters execute, the learning loop
captures the outcome. That's the bar.

---

## Concrete Next Session Kickoff

See `NEXT_SESSION_PROMPT.md` for the prompt to start the next chat.
