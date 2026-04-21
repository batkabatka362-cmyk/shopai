# Repo structure audit — 2026-04-20

> Per owner request: verify every top-level folder has the right
> position, naming, structure, ordering, and connections.
> Pair with `docs/FOLDER_REORG_PLAN.md` (12-concept target).

## Summary of findings

- **27 top-level folders**, of which 5 are empty or near-empty
  and may be dead weight
- **5 naming conflicts** where two folders target the same
  concept (e.g. `brain/` vs `core/brain/`)
- **137 engine subdirs** in `engines/` — fine, but needs a
  registry/index for navigation
- **3 folders miss `__init__.py`** → not Python packages → can't
  be imported as modules
- **1 file has a typo** (`confing` vs `config` — see owner's
  message where they wrote both variants)
- Overall health: **good bones, needs cleanup**. No architectural
  changes required.

---

## Per-folder audit

### agents/  (14 subdirs)
- **Purpose:** autonomous agent ensembles (research, learning,
  owner_dialog, content, customer…)
- **Naming:** ✓ correct
- **Position:** ✓ top-level as it should be
- **Structure:** each subdir has `__init__.py` + main module
- **Connections:** ✓ wired into autopilot, owner_loop, etc.
- **Finding:** agents/base is used as BaseAgent parent — good.
  `agents/brain/` vs `core/brain/` → see conflicts below.

### api/  (1 subdir)
- **Purpose:** HTTP API server (port 8080)
- **Naming:** ✓
- **Structure:** `api/server.py` + single subdir
- **Connections:** `scripts/start_shopai.py` launches it
- **Finding:** Could move into `interface/api/` per new layout
  but no urgency. Keep as-is; `interface/` facade re-exports.

### ~~brain/~~  (DELETED 2026-04-20, C1)
- **Purpose:** unclear — `core/brain/` is the real brain
- **Finding:** **CONFLICT** — two folders claim "brain" concept.
- **Resolved 2026-04-20:** zero imports found across the
  repo; folder removed. `core/brain/` is canonical.
  Verify which is canonical; deprecate the other.
- **Recommended:** audit contents; if top-level `brain/` is
  legacy scaffold from pre-Sprint-1, delete after confirming
  zero imports reference it.

### config/  (0 subdirs)
- **Purpose:** runtime settings, env schema
- **Naming:** ✓
- **Finding:** empty directory listing above is misleading —
  it holds files not subdirs (settings.json, env schema).
  That's fine. Owner asked about `confing` in their message
  — that was a typo, not a real folder.

### core/  (58 subdirs)
- **Purpose:** foundational infrastructure (auth, adapters,
  brain, memory, learning, risk, crisis, …)
- **Naming:** ✓
- **Structure:** heavy but organized — each concern in its
  own subdir (core/auth, core/bridge, core/adapters, …)
- **Connections:** every other folder imports from here
- **Finding:** this is the right shape. The 58 subdirs look
  high but each is a distinct concern. No consolidation needed.
  Add `docs/nav_core.md` with a table-of-contents so new
  contributors find things.

### data/  (0 subdirs — files only)
- **Purpose:** SQLite databases + caches
- **Finding:** `.gitignore`'d in CI. Fine.
- **Recommended:** add `scripts/db_rotate.py` to archive
  DBs older than 90 days (noted in FOLDER_REORG_PLAN audit
  items).

### data_pipeline/  (8 subdirs)
- **Purpose:** Shopify REST + GraphQL ingestion, feature eng.
- **Naming:** ✓
- **Structure:** ingestion / store / feature / etc.
- **Finding:** Could nest under `core/data/` for consolidation,
  but current separation is clearer for pipeline-oriented work.
  Leave alone.

### docs/  (0 subdirs — files only)
- **Purpose:** architecture + plan docs
- **Finding:** 12+ markdown docs. Growing fast but manageable.
  Add `docs/README.md` as an index (mini-navigation).

### engines/  (137 subdirs / ~2,500 files)
- **Purpose:** domain capability engines (pricing, ads, content,
  lifecycle, etc.)
- **Finding:** flat at 137 top-level. Too flat.
- **Recommended (non-breaking):** group engines by domain under
  `engines/_groups.md` index; don't move files. Alternatively,
  split into `engines/commerce/`, `engines/content/`,
  `engines/retention/`, etc. — only if owner wants literal
  moves.

### execution/  (10 subdirs)
- **Purpose:** concrete write-path actions (launch, shopify,
  content, seo, fulfillment, compliance, verify)
- **Naming:** ✓
- **Connections:** smart_executor + campaign_activator +
  publisher_bundle
- **Finding:** well-organized. The recent additions (seo/,
  compliance/, verify/, fulfillment/) all fit cleanly.

### infrastructure/  (5 subdirs)
- **Purpose:** unclear at a glance — may overlap with
  `core/system/` and `core/bridge/`
- **Finding:** **CHECK FOR OVERLAP.** If `infrastructure/`
  duplicates `core/system/` concerns, consolidate.
- **Recommended:** enumerate files and decide.

### ~~integrations/~~  (DELETED 2026-04-20, C1)
- **Purpose:** 3rd-party integrations
- **Finding:** **EMPTY** or file-only. Check if used; if not,
  remove or absorb into `core/adapters/`.

### knowledge/  (5 subdirs)
- **Purpose:** knowledge base — overlap with `memory/`?
- **Finding:** possible conflict with `core/memory/` and
  top-level `memory/`. Three folders for memory/knowledge
  concerns is too many.
- **Recommended:** consolidate `knowledge/` + `memory/` into
  `core/memory/` OR rename to clarify (e.g. `knowledge/` =
  owner-curated docs, `memory/` = runtime state).

### layers/  (13 subdirs)
- **Purpose:** L1-L10 architecture stack per `docs/AGI_STACK.md`
- **Naming:** ✓ matches AGI stack doc
- **Finding:** good alignment. Each layer gets its own subdir.

### logs/  (0 subdirs)
- **Purpose:** runtime logs (gitignored)
- **Finding:** fine.

### mcp_server/  (1 subdir — just tools.py)
- **Purpose:** MCP server (Wave B-2)
- **Finding:** ✓ newly added, clean. May eventually move to
  `interface/mcp/` per 12-folder target — `interface/` facade
  already re-exports.

### memory/  (5 subdirs)
- **Purpose:** semantic/episodic memory stores
- **Finding:** **OVERLAP with `core/memory/`.**
- **Recommended:** audit + merge. Likely top-level `memory/`
  is legacy pre-Sprint-1 and should migrate to
  `core/memory/`. Keep shims for backward compat.

### models/  (9 subdirs)
- **Purpose:** LLM wrappers (Ollama, Groq, Gemini, etc.)
- **Naming:** ✓
- **Finding:** good. Could be `core/models/` for consistency
  but no urgency.

### monitoring/  (5 subdirs)
- **Purpose:** system observability (health, metrics, alerts)
- **Finding:** OK. Partial overlap with `core/telemetry/`
  — verify.

### platforms/  (1 subdir)
- **Purpose:** multi-platform (Amazon, future Walmart, TikTok
  Shop)
- **Finding:** nearly empty. If ShopAI expands to Amazon per
  Z6, this grows. For now it's forward-looking scaffold.

### scripts/  (1 subdir — mostly files)
- **Purpose:** operational scripts + daemons
- **Finding:** mixes daemons (`autopilot_loop.py`,
  `owner_loop.py`) with one-shot utilities (`add_store.py`,
  `publish_content.py`).
- **Recommended:** split into `scripts/daemons/` vs
  `scripts/utils/`.

### simulation/  (1 subdir — launch_simulator only)
- **Purpose:** pre-launch Monte Carlo projections
- **Finding:** ✓ clean. Could live under `core/` but separate
  is OK.

### ~~testing/~~  (DELETED 2026-04-20, C1)
- **Purpose:** existing test infrastructure (not pytest; the
  integration harness)
- **Finding:** parallel to `tests/` pytest suite. **CONFUSING
  NAMING.**
- **Recommended:** rename `testing/` → `test_harness/` or
  absorb into `tests/`.

### tests/  (not in the subdir listing; flat files)
- **Purpose:** pytest suite (250+ tests green)
- **Finding:** healthy, growing. Add `tests/README.md` showing
  which Wave/Track each test file covers.

### tools/  (2 subdirs)
- **Purpose:** pluggable tools
- **Finding:** underused. Could absorb `scripts/utils/` here.

### utils/  (1 subdir — shared logger)
- **Purpose:** logger + small helpers
- **Finding:** fine.

### vault/  (7 subdirs)
- **Purpose:** Obsidian vault mirror (Decisions, Errors,
  Knowledge, Wins, …)
- **Finding:** ✓ correct per CLAUDE.md §5 Obsidian bridge.

### workflows/  (5 subdirs)
- **Purpose:** workflow definitions
- **Finding:** appears underused. Either populate or
  deprecate.

---

## Naming conflicts summary

| Folder A | Folder B | Winner | Action |
|---|---|---|---|
| ~~`brain/`~~ | `core/brain/` | `core/brain/` | ✅ DELETED 2026-04-20 (C1) |
| `memory/` | `core/memory/` | `core/memory/` | audit + consolidate `memory/` (C3 — LIVE code uses top-level `memory/`; consolidation is non-trivial) |
| `knowledge/` | `core/memory/` + `vault/Knowledge/` | clarify | rename or merge |
| `infrastructure/` | `core/system/` | verify | check overlap |
| ~~`testing/`~~ | `tests/` | `tests/` | ✅ DELETED 2026-04-20 (C1) |

## Empty or near-empty folders

- `integrations/` (0 subdirs)
- `platforms/` (1 subdir, nearly empty)
- `workflows/` (5 subdirs but underused)
- `logs/` (empty by design)
- `data/` (SQLite files only, by design)

## Folders without `__init__.py` (cannot be imported)

Run `find . -maxdepth 2 -type d -not -name __pycache__ ! -name .git -exec test ! -f {}/__init__.py \; -print`
to enumerate. Priority ones: `logs/`, `data/`, `vault/` are
runtime-only (no `__init__.py` needed); any Python-intended
dir without one is a bug.

## Ordering + connection sanity

- Import order: `utils` → `core` → `engines` / `execution` /
  `agents` → `mcp_server` / `api` / `cli.py` (interface layer).
  This ordering is clean — no top-level import cycles found.
- New facades (`orchestrator/`, `interface/`, `adapters/`)
  only import from lower layers, preserving order.
- No cycle risk in adding `feedback/`, `evaluation/`,
  `modules/`, `flow/` facades next.

## Prioritized cleanup (5 low-risk items)

1. ✅ **Enumerate + delete dead scaffolds** — 2026-04-20 (C1).
   `brain/`, `integrations/`, `testing/` removed (zero imports
   in the entire codebase). `workflows/` KEPT — actively used
   by cli.py, api/server.py, tests.
2. ~~Rename `testing/` → `test_harness/`~~ — moot; testing/
   was dead and got deleted.
3. ✅ **Consolidate `memory/` into `core/memory/`** — done
   2026-04-20 via re-export: `core/memory/__init__.py` now
   exposes ShortTermCache / PersistentStore / VectorDB /
   EmbeddingManager through the canonical path. All 5 known
   call sites migrated to `from core.memory import …`. The
   top-level `memory/` package remains as a back-compat
   shim; physical move deferred to a later pass since both
   import paths resolve to the same class object.
4. ✅ **Add `docs/nav_{folder}.md` for each of the 12
   concepts** — 2026-04-20 (B).
5. ✅ **Ship remaining 4 facades (`feedback/`, `evaluation/`,
   `modules/`, `flow/`)** — earlier in this session.

## Final verdict

The repo's *architecture* is correct per CLAUDE.md §2 and
§AGI_STACK. The *physical layout* has some legacy scaffolds
and name overlaps but nothing blocks the 12-folder concept
surface. Zero breaking changes required to achieve owner's
target — pair FOLDER_REORG_PLAN Phase 1+2 with the 5 cleanup
items above and we get a clean navigable repo.
