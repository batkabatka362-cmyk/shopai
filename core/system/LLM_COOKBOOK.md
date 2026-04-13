# ShopAI LLM Cookbook

ShopAI is built **on top of** AI models, not as one. Local Ollama
models (Mistral / Qwen / LLaMA) and remote APIs (OpenAI Chat
Completions, Anthropic Messages) are the system's reasoning
substrate. Every cognitive module that needs reasoning calls them
through one of three layers documented here.

## The 3 layers

```
┌──────────────────────────────────────────────────────────────┐
│  Cognitive modules (reflection, imagination, theory_of_mind, │
│  curiosity, planner) and intelligence modules (pricing, …)   │
└──────────────────────────────┬───────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
       ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
       │ TaskRouter  │  │  LLMCache   │  │PromptLibrary│
       │ task-aware  │  │  TTL+LRU    │  │  versioned  │
       │  adaptive   │  │   prompt →  │  │  templates  │
       │   routing   │  │  response   │  │             │
       └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
              │                │                │
              └────────────────┼────────────────┘
                               ▼
                       ┌───────────────┐
                       │  LLMAdapter   │
                       │ retry, fall-  │
                       │ back chain,   │
                       │ structured    │
                       │ output        │
                       └───────┬───────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        ┌──────────┐    ┌──────────┐     ┌──────────┐
        │  Ollama  │    │  OpenAI  │     │Anthropic │
        │ (local)  │    │   API    │     │   API    │
        └──────────┘    └──────────┘     └──────────┘
```

| Module | File | Purpose |
|---|---|---|
| `LLMAdapter` | `llm_adapter.py` | Talk to providers; retry; fallback chain |
| `PromptLibrary` | `prompt_library.py` | Versioned prompt templates |
| `LLMCache` | `llm_cache.py` | TTL+LRU cache for repeated calls |
| `TaskRouter` | `task_router.py` | Task-type aware adaptive routing |

## Configuration

Set any of these env vars to enable a provider. Mix and match — the
adapter walks them in fallback-chain order.

```bash
# Local Ollama (free, no key needed)
export SHOPAI_OLLAMA_URL=http://localhost:11434

# OpenAI
export OPENAI_API_KEY=sk-...
export SHOPAI_OPENAI_MODEL=gpt-4o-mini   # default

# Anthropic
export ANTHROPIC_API_KEY=sk-ant-...
export SHOPAI_ANTHROPIC_MODEL=claude-haiku-4-5-20251001   # default
```

Verify the stack from the CLI:

```bash
shopai mind llm-status
```

## Recipe 1: simple text query

```python
from core.system.llm_adapter import get_llm

llm = get_llm()
resp = llm.ask(
    role="analyzer",
    prompt="Summarize this product: Cozy Wool Blanket, $79, 4.7★",
)
if resp.success:
    print(resp.text)
```

`role` is one of `analyzer | reasoner | worker | creative | validator | general`.
The adapter maps it to a model based on what's actually available.

## Recipe 2: structured (JSON) output

```python
from core.system.llm_adapter import get_llm

result = get_llm().ask_structured(
    role="reasoner",
    prompt="What's the optimal price for a $50-cost product in fashion?",
    schema_hint='{"price": float, "reasoning": str, "confidence": float}',
)
if result.ok:
    print(result.data["price"], result.data["reasoning"])
else:
    print("Failed:", result.error)
    # Fall back to heuristic here
```

`ask_structured` injects a JSON-only system prompt and parses the
response strictly. On any failure (no providers, parse error,
exception), `result.ok` is False — the caller falls back to
deterministic logic.

## Recipe 3: use a centralized prompt template

```python
from core.system.llm_adapter import get_llm
from core.system.prompt_library import render_prompt, get_prompt

template = get_prompt("decision.pricing_recommendation")
rendered = template.render(
    product_name="Cozy Lamp",
    price=29.99,
    cost=12.50,
    margin_pct=58.3,
    recent_sales=15,
    competitor_prices="$26.99, $32.50",
)
result = get_llm().ask_structured(
    role=template.role,
    prompt=rendered.user,
    system_prompt=rendered.system,
    schema_hint=template.schema_hint,
)
```

Templates are versioned. If you tweak a prompt, **bump its version
number** so the library archives the old one and reflection can
compare A/B variants.

Built-in templates:

| Name | Used by |
|---|---|
| `planner.decompose_goal` | Planner LLM backend |
| `reflection.summarize_episodes` | Reflection LLM lessons |
| `imagination.evaluate_step` | Imagination LLM evaluator |
| `theory_of_mind.predict_response` | TheoryOfMind LLM predictor |
| `curiosity.pick_target` | Curiosity LLM target picker |
| `decision.pricing_recommendation` | PricingIntelligence |
| `mind.think` | `shopai mind think` |

## Recipe 4: cached LLM call (skip duplicates)

```python
from core.system.llm_cache import cached_ask
from core.system.llm_adapter import get_llm

resp = cached_ask(
    get_llm(),
    role="analyzer",
    prompt="Should I lower prices on slow movers?",
    context={"slow_count": 12, "avg_age_days": 60},
)
```

The first call hits the LLM. The second identical call returns
the cached response in microseconds. Different `context` dicts
produce different cache entries (the context is hashed into the
key but still passed unchanged to the adapter).

Default TTL is 1 hour, cache size 256. Tune via:

```python
from core.system.llm_cache import LLMCache
custom = LLMCache(max_entries=1000, ttl_s=3600 * 24)
```

## Recipe 5: task-aware adaptive routing

```python
from core.system.task_router import get_task_router

router = get_task_router()
decision = router.route(
    task_type="extract_keywords",
    prompt="Extract 5 keywords from: ...",
    budget="local_only",     # Ollama only — keep it free
)
print(decision.model)         # which model the router picked
print(decision.reason)        # static or adaptive choice
print(decision.response.text) # the LLM response
```

After 5+ observations of a task type, the router picks the
best-performing model based on success rate + latency. Before
that it uses static role mapping. Stats persist if you pass
`state_path="..."`.

Budget tiers:

- `local_only` — Ollama only (no API costs)
- `cheap` — local first, fall back to OpenAI mini / Claude Haiku
- `premium` — all providers, best wins regardless of cost

## Recipe 6: enable LLM mode in a cognitive module

Every Phase B cognitive module accepts an optional `llm`
parameter. Wire one in and it stacks the LLM layer on top of its
heuristic layer:

```python
from core.cognitive.reflection import Reflection
from core.cognitive.imagination import Imagination
from core.cognitive.theory_of_mind import TheoryOfMind
from core.cognitive.curiosity import Curiosity
from core.system.llm_adapter import get_llm

llm = get_llm()
reflection = Reflection(memory=mem, self_model=sm,
                        goal_manager=gm, llm=llm)
imagination = Imagination(self_model=sm, memory=mem, llm=llm)
tom = TheoryOfMind(llm=llm)
curiosity = Curiosity(self_model=sm, goal_manager=gm, llm=llm)
```

Or pass `use_llm=False` to a single instance to opt out without
removing the wiring.

## Recipe 7: ad-hoc reasoning from the CLI

```bash
shopai mind think should I lower prices on slow movers?
shopai mind think --role analyzer what's our biggest weakness?
shopai mind think --no-context what is 2+2?
```

`shopai mind think` builds a self-context block from the
SelfModel narrative + active goals, renders the `mind.think`
template, and asks the LLM. Use `--no-context` for abstract
questions and `--role` to pick a specific role (analyzer,
reasoner, creative, worker).

## Recipe 8: graceful fallback when no LLM is available

Every layer above is **opt-in**. The system runs to completion
with zero LLM providers configured — cognitive modules fall back
to their statistical / rule-based logic. To detect this in your
own code:

```python
from core.system.llm_adapter import get_llm

llm = get_llm()
if llm.is_available():
    # Use LLM-backed path
    result = llm.ask(...)
else:
    # Fall back to heuristic
    result = my_heuristic(...)
```

Or just call `ask()` and check `response.success` — failures are
returned as data, never raised.

## Recipe 9: track LLM usage and costs

```python
from core.system.llm_adapter import get_llm

stats = get_llm().get_stats()
for model, s in stats["models"].items():
    print(f"{model}: {s['calls']} calls, {s['tokens']} tokens")
```

Or from the CLI:

```bash
shopai mind llm-status
```

The stats include calls, tokens, errors, total time, and how
many calls hit the fallback chain (a sign that the preferred
provider is down).

## Recipe 10: switch the default OpenAI / Anthropic model

```bash
export SHOPAI_OPENAI_MODEL=gpt-4o            # full-fat instead of mini
export SHOPAI_ANTHROPIC_MODEL=claude-sonnet-4-6   # bigger Claude
```

Or programmatically per role:

```python
get_llm().set_role_model("reasoner", "gpt-4o")
```

## Design principles

1. **Heuristic + LLM hybrid.** Every cognitive module has both
   layers. The LLM enriches; the heuristic guarantees a result.
2. **Cheap defaults.** Default OpenAI model is `gpt-4o-mini`,
   default Anthropic is `claude-haiku-4-5`. Override if you want
   premium reasoning.
3. **Local first.** The fallback chain puts Ollama models before
   API providers so daily operation doesn't cost real money.
4. **Versioned prompts.** Inline string literals are forbidden;
   register every prompt in `PromptLibrary` so changes are
   trackable.
5. **Structured output.** Use `ask_structured` over `ask_json`
   for new code — the StructuredResponse dataclass tells you
   ok / data / error explicitly.
6. **Cache aggressively.** Token costs add up. The default 1-hour
   TTL is safe for most reflective queries.
7. **Adaptive routing.** Let TaskRouter learn which model is best
   for which task. Don't hardcode.
8. **Tests mock urllib.** Every test in this stack mocks
   `urllib.request.urlopen` so no real Ollama / API calls happen
   during CI. Real Ollama is for production.

## Tests

```bash
pytest tests/test_llm_adapter.py        # 40 tests
pytest tests/test_prompt_library.py     # 27 tests
pytest tests/test_llm_cache.py          # 24 tests
pytest tests/test_task_router.py        # 25 tests
pytest tests/test_reflection.py         # 40 tests (+10 LLM)
pytest tests/test_imagination.py        # 44 tests (+10 LLM)
pytest tests/test_theory_of_mind.py     # 47 tests (+11 LLM)
pytest tests/test_curiosity.py          # 37 tests (+9 LLM)
pytest tests/test_mind_cli.py           # 18 tests (+6 think/llm-status)
pytest tests/test_pricing_intelligence_llm.py  # 13 tests
```

Total LLM stack coverage: ~190 tests.
