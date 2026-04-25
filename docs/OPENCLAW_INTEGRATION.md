# OpenClaw Integration Plan

**Target:** OpenClaw (TypeScript/Node.js autonomous AI agent)-ыг
ShopAI-гийн helper agent болгож нэвтрүүлэх. Local Ollama-аар
эхлэж, cloud AI (Anthropic / OpenAI) руу scale хийх сонголттой.

**Branch:** `claude/update-shop-ai-docs-dVyQc`
**Дүрэм:** §4b/G paranoid mode + §4c.K wrong-loop detector.

---

## 1. Яагаад

ShopAI-д аль хэдийн байгаа:

- **Domain brain** (`core/brain/` 225 module) — pricing, ROAS, pattern detection
- **LLM gateway** (`core/llm_gateway.py`) — Groq / Gemini / DeepSeek chain
- **MCP server** — 33 tool Claude Desktop-аас нэвтрэгдэнэ

Дутагдалтай байгаа:

- Telegram / WhatsApp / Discord-аас **ШопAI-г native-аар удирдах** түвшинд `agents/owner_dialog/tool_dispatcher.py` нь 22 intent regex-тэй — хязгаарлагдмал. Owner-ийн free-text commands-ыг parse хийж, зөв MCP tool-оор дуудах ажилд boundary бий.

- Owner-ийн **persistent memory** (таны preferences, "дуртай niche", "kill rule-ын түвшин") ShopAI-д байхгүй. Owner бүр нэг session-д ижил context-ыг дахин тайлбарлана.

- ShopAI-ын cycle-ын хоорондоо **meta-reasoning** ("өнгөрсөн 7 хоногт яагаад ROAS унасан вэ?") хомс. Brain domain-specific учир cross-domain causal reasoning-д тохирохгүй.

OpenClaw нь эдгээр гурвыг бөхөөнө:

- Telegram/WhatsApp nativeагент + persistent memory + free-text reasoning
- MCP client-ээр ShopAI-ын 33 tool ашиглана
- Local Ollama эсвэл cloud AI-г ашиглаж cost гаргадаг

---

## 2. Архитектур

```
┌───────────────────────────────────────────────┐
│  OWNER                                        │
│  (Telegram / WhatsApp / Discord / CLI)        │
└─────────────────┬─────────────────────────────┘
                  │ free-text command
                  ▼
┌───────────────────────────────────────────────┐
│  OpenClaw (Node.js, sibling process)          │
│  ├── Chat UX                                  │
│  ├── Persistent memory (owner prefs)          │
│  ├── LLM (Ollama local / Claude / OpenAI)     │
│  └── MCP client  ─────────┐                   │
└───────────────────────────┼───────────────────┘
                            │ MCP protocol
                            ▼
┌───────────────────────────────────────────────┐
│  ShopAI MCP server (Python, stdio/HTTP)       │
│  33 tools: replay_orders, rule_quality,       │
│  live_health, store_configure, ...            │
└─────────────────┬─────────────────────────────┘
                  │ invokes
                  ▼
┌───────────────────────────────────────────────┐
│  ShopAI brain + engines + Shopify / Meta      │
└───────────────────────────────────────────────┘
```

**Чухал зарчим:**

- OpenClaw нь ShopAI-ын brain-ийг **ДАВАХГҮЙ** — domain-specific decision-г brain-д үлдээнэ. OpenClaw бол reasoning + tool-using agent, ShopAI-ын tool-уудыг ашиглах client.
- OpenClaw ↔ ShopAI-гийн сонголт нь ихэвчлэн **ШопAI-ын MCP protocol** (33 tool аль хэдийн байна).
- ShopAI-гийн Python code-ыг OpenClaw шууд мэдэхгүй. Зөвхөн MCP tool-уудаар дамжина.

---

## 3. Integration pattern сонголт

| Pattern | Pros | Cons | Verdict |
|---|---|---|---|
| **Vendor source** (TS in Python repo) | Version-locked, offline | 500MB node_modules, CI burden, license attribution | ❌ |
| **Git submodule** (`vendor/openclaw/`) | Source in repo (pointer), sync easy | Still need Node runner in CI | 🟡 acceptable |
| **Sibling install** (`~/projects/openclaw`) | Clean separation | Owner setup 1 extra step | ✅ chosen |
| **Docker service** | Production-grade, multi-arch | Heavier local dev | ✅ prod path |

**Session's bootstrap:** Sibling install (simplest), upgraded to Docker service when production-ready.

---

## 4. Phased ship plan

### Phase 0 — Pilot (owner local, 1 цаг)

Ажил:
- `scripts/setup_openclaw.sh` ажиллуулж OpenClaw-ыг sibling clone хийнэ (`~/projects/openclaw` эсвэл `$SHOPAI_OPENCLAW_HOME`)
- Ollama local нээж сонгосон model (жишээ `llama3.2`) татна
- OpenClaw-д Ollama endpoint зааж, chat туршина
- "hello" → OpenClaw хариу өгнө үү? шалгах

**Гарц:** OpenClaw ажиллаж байгаа local instance.

### Phase 1 — Subprocess adapter (2-3 өдөр)

ShopAI дотор:

```
core/adapters/ai_agents/
├── __init__.py
├── _base.py                 # BaseAIAgentAdapter
└── openclaw_adapter.py      # subprocess wrapper
```

`OpenClawAdapter.run_task(prompt, timeout, working_dir)`:
- Reads `SHOPAI_OPENCLAW_HOME` env
- `subprocess.run(["node", ".../cli.js", "--prompt", prompt], timeout=N, capture_output=True)`
- JSON parse stdout
- Returns `AdapterResult` (ok=True + text, OR ok=False + error)

Safety:
- `SHOPAI_ENABLE_LIVE_EXECUTION` check before file-mutation prompts
- Max 60s timeout by default
- `subprocess.PIPE` (no shell=True → command injection closed)

MCP tool `invoke_openclaw` (write=True) + CLI `shopai ai-agent "<task>"`.

Tests:
- Subprocess mock happy-path
- Timeout error
- Non-zero exit error
- Missing env-var skip

### Phase 2 — MCP bridge (2-3 өдөр)

ShopAI-ын MCP server нь одоогоор stdio-only. OpenClaw MCP client нь stdio эсвэл HTTP аль алинтай таарна. Хэрэв stdio OK бол:

```
OpenClaw config:
  mcp_servers:
    - name: shopai
      command: python
      args: ["-m", "mcp_server.server"]
      cwd: /path/to/shopai
      env: { PYTHONPATH: /path/to/shopai }
```

OpenClaw startup-д ShopAI-ын 33 tool-ыг discover хийгээд chat-д нэвтрэнэ.

Owner:

> Telegram: "launch новой beauty SKU, kill rule ROAS < 1.3"

OpenClaw:
1. Parse intent
2. Owner memory-оос preference read
3. ShopAI MCP `invoke` хэд хэдэн tool:
   - `rule_quality` — одоогийн rule state
   - `predict_outcome` — ROAS forecast
   - Then instruct owner "ready to launch? confirm" (§4b.G)

### Phase 3 — Docker production (3-5 өдөр)

```yaml
# docker-compose.yml
services:
  shopai:
    build: .
    ports: [ "8080:8080" ]
    volumes: [ "./data:/app/data" ]

  openclaw:
    image: openclaw/openclaw:latest     # эсвэл build: docker/openclaw.Dockerfile
    ports: [ "3000:3000" ]              # chat UI
    environment:
      - OLLAMA_BASE_URL=http://ollama:11434
      - SHOPAI_MCP_HOST=shopai:8080
    depends_on: [ shopai, ollama ]

  ollama:
    image: ollama/ollama:latest
    ports: [ "11434:11434" ]
    volumes: [ "ollama:/root/.ollama" ]
```

`docker-compose up` → гурван service зэрэг. Owner Telegram-оос Shop*AI-г controll хийх боломжтой.

### Phase 4 (optional, high-risk) — Cycle auto-invocation

`feedback_store.get_stats()` нь `trend="declining"` engine илрүүлбэл:
- `shopai daemon` → OpenClaw task queue нэмнэ
- OpenClaw reasoning → proposed fix (code change / config tweak)
- Owner Telegram-оор "approve / reject" товч дарна
- Approve бол OpenClaw Claude Code-оор code change хийнэ

`SHOPAI_ENABLE_OPENCLAW_AUTO=1` env-гэйд л идэвхждэг. §4b.G paranoid mode — approval гэрчилсэн гараар.

---

## 5. LLM backend сонголт

| Backend | Cost | Quality | Privacy | Зориулалт |
|---|---|---|---|---|
| Ollama `llama3.2` local | 0 | Medium | Full | Pilot, dev, privacy-sensitive |
| Ollama `mixtral` local | 0 | Medium-high | Full | Сонин deep-reasoning задав |
| Anthropic Claude Sonnet | ~$3/M in, $15/M out | Highest | Cloud | Production critical decisions |
| OpenAI GPT-4o | ~$2.50/M in, $10/M out | High | Cloud | Backup |
| DeepSeek V3 | ~$0.27/M in, $1.10/M out | High | Cloud | Cost-optimized prod |

**Pilot:** Ollama `llama3.2` (local, free).
**Prod:** Claude Sonnet + DeepSeek fallback (§5 CLAUDE.md chain-тэй нийцэнэ).

Config (OpenClaw-ын өөрийн `.env`):

```bash
# Local pilot
OPENCLAW_LLM_PROVIDER=ollama
OPENCLAW_OLLAMA_URL=http://localhost:11434
OPENCLAW_OLLAMA_MODEL=llama3.2

# Prod (example)
# OPENCLAW_LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=sk-ant-xxx
```

---

## 6. Safety & boundaries

Per CLAUDE.md §4b.G paranoid mode:

- **OpenClaw-ын write-capable actions** (Shopify API call, Meta Ads budget change, code edit) бүгд **`SHOPAI_ENABLE_LIVE_EXECUTION=1`**-ыг шаардана.
- Owner approval — Telegram reply "confirm" эсвэл Claude Desktop-оос `confirm` suffix.
- Audit log — OpenClaw dispatch бүр `agents/owner_dialog/` дотор logged.
- Subprocess timeout — 60s default; long task-уудыг queue-д өгнө.
- No `shell=True` in subprocess — argv only (command injection closed).

---

## 7. §4c.K self-check

**Mission alignment:**

- **Z1 (autonomy):** owner-agent interface native болно → Telegram-оос шууд жолоодноо.
- **Z4 (revenue):** cycle meta-reasoning + cross-domain pattern catch → rule quality өсөх дэлгэрэнгүй.

**Plumbing vs capability:** Phase 0-3 нь 1:3 (plumbing: subprocess adapter; capability: real owner-facing meta-agent).

**Dollar distance:**
- Phase 0-1: 3 (adapter → tool access)
- Phase 2: 2 (Telegram dispatch → realtime owner commands)
- Phase 3: 1 (production docker → 24/7 operation)
- Phase 4: 2 (auto-fix cycle → faster recovery)

**Month-tomorrow test:** Phase 2 дуусах үед owner Telegram-оос "launch X" бичиж real order авах магадлал бодитой.

---

## 8. Шууд ажлын дараалал (бид + owner)

### Оюутан session (today)

- ✅ `scripts/setup_openclaw.sh` — shipped (энэ commit)
- ✅ `docs/OPENCLAW_INTEGRATION.md` — энэ документ
- 🔜 Owner: `bash scripts/setup_openclaw.sh` → OpenClaw clone + npm install
- 🔜 Owner: Ollama-р chat туршина

### Дараа session (Phase 1)

- `core/adapters/ai_agents/openclaw_adapter.py` — subprocess wrapper
- `mcp_server/tools.py` — `invoke_openclaw` tool
- `cli.py` — `shopai ai-agent "<task>"`
- Tests + regression

### Дараах session (Phase 2)

- OpenClaw-ын MCP client config-т ShopAI server заах
- Telegram → OpenClaw → ShopAI MCP dispatch туршилт
- `owner_dialog/tool_dispatcher.py`-тэй сонголттой байх
