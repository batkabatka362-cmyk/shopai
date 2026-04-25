# Folder reorganization plan — 12-folder target

> Owner request: reorganize repo into 12 top-level concept
> folders WITHOUT changing architecture, contracts, or import
> paths. This doc is the mapping — migration happens
> incrementally so imports never break.

## Target top-level (per owner)

1. **core** — foundational infrastructure (auth, bridge, adapters)
2. **orchestrator** — main orchestration + autopilot loop
3. **interface** — outside-world surfaces (CLI, API, MCP, CLI)
4. **feedback** — outcome / attribution / closed-loop telemetry
5. **evaluation** — testing, metrics, benchmarks, judgments
6. **modules** — reusable capability modules (risk, crisis, legal, planning)
7. **flow** — workflow definitions (sprint plans, wave plans, flows)
8. **agents** — autonomous agent ensembles (research, learning, dialog)
9. **layers** — 10-layer stack modules (L1..L10)
10. **engines** — ~2,500 domain engines (unchanged folder — already exists)
11. **tools** — pluggable tools (scripts, CLI extensions)
12. **adapters** — external adapters (physically under core/adapters today)

## Current repo state (as of 2026-04-20)

```
agents/           14 subdirs — research, learning, owner_dialog, customer…
api/              HTTP API server
brain/            empty or residual
config/           settings
core/             58 subdirs — adapters, auth, bridge, brain, memory,
                               risk, crisis, learning, decision, data,
                               planning, legal, federation, integration…
data/             SQLite dbs + caches
data_pipeline/    Shopify REST/GraphQL ingestion + feature eng.
docs/             architecture + research docs
engines/          137 subdirs — ~2,500 engines
execution/        10 subdirs — launch, shopify, content, seo, fulfillment,
                               compliance, verify
infrastructure/   infra glue
integrations/     3rd-party integrations
knowledge/        knowledge base
layers/           13 subdirs — L-layer modules
logs/             runtime logs
mcp_server/       NEW (this session) — MCP server
memory/           semantic / episodic memory
models/           LLM wrappers
monitoring/       system observability
platforms/        Amazon / cross-platform
scripts/          autopilot_loop, owner_loop, operational scripts
simulation/       launch_simulator
testing/          existing testing infra
tests/            pytest suite (200+ tests green)
tools/            2 subdirs — owner-facing tooling
utils/            shared utils (logger)
vault/            Obsidian vault mirror
workflows/        5 subdirs — workflow definitions
```

## Proposed mapping (reorg target)

Rather than physically moving 2,500 engines (breaks 1000+ import
paths + tests + docs + CLI), apply the 12-folder logic as a
**namespace map** + **documentation navigation** without touching
existing folder physical layout on disk.

| Concept folder | Current physical folders | Action |
|---|---|---|
| **core**       | `core/auth`, `core/bridge`, `core/memory`, `core/learning`, `core/decision`, `core/risk`, `core/crisis`, `core/legal`, `core/federation`, `core/planning`, `core/integration`, `core/data`, `core/brain`, `core/system` | Already organized. Add `docs/core.md` table-of-contents. |
| **orchestrator** | `core/core_orchestrator.py`, `core/autonomous`, `core/autopilot`, `scripts/autopilot_loop.py`, `scripts/owner_loop.py` | Create `orchestrator/` facade re-exporting existing modules. |
| **interface**  | `api/`, `cli.py`, `mcp_server/`, `agents/owner_dialog/` | Facade `interface/` re-exports + nav doc. |
| **feedback**   | `core/attribution`, `core/learning/outcome_tracker`, `core/bridge/agentic_storefront` (attribution half), `core/adapters/triplewhale/moby.py` (RL disagreement) | Nav doc + import facade. |
| **evaluation** | `tests/`, `testing/`, `execution/verify`, `simulation/launch_simulator` | Nav doc only. |
| **modules**    | `core/risk`, `core/crisis`, `core/legal`, `core/planning`, `core/federation`, `execution/compliance`, `execution/fulfillment`, `execution/seo` | Nav doc + facade re-exports. |
| **flow**       | `workflows/`, `docs/AGI_*`, `docs/IMPLEMENTATION_PLAN_2026.md` | Nav doc + symbolic grouping. |
| **agents**     | `agents/` (already exists) | Untouched. Add nav doc. |
| **layers**     | `layers/` (already exists) | Untouched. Add nav doc. |
| **engines**    | `engines/` (already exists) | Untouched. |
| **tools**      | `tools/` (already exists) + `scripts/` (operational) | Nav doc. |
| **adapters**   | `core/adapters/` (already exists) | Add `adapters/` facade re-exporting from `core/adapters`. |

## Migration strategy

**Phase 1 — Navigation docs (safe).**
For each of the 12 concept folders write `docs/nav_{name}.md`
explaining which physical folders map there. Commit this first.
Zero import-path risk.

**Phase 2 — Facade packages (soft reorg).**
Create thin `orchestrator/`, `interface/`, `feedback/`,
`evaluation/`, `modules/`, `flow/`, `adapters/` top-level
packages that each do:

```python
# orchestrator/__init__.py
from core.core_orchestrator import CoreOrchestrator  # noqa: F401
from scripts.autopilot_loop import AutopilotLoop      # noqa: F401
# ...
```

External callers (documentation, new code) can `import
orchestrator.CoreOrchestrator`; old callers still work via
original path. Zero import break.

**Phase 3 — Gradual rehoming (optional, post-audit).**
Only if owner wants literal files moved. Each move:
1. Move file to new location
2. Keep old path as a `from new_location import *` shim
3. Update tests + callers one at a time
4. Delete shim after 1 week of green CI

## Recommendation

Go with **Phase 1 + Phase 2** now. Phase 3 costs weeks of
churn for cosmetic gain. The 12-folder structure becomes
visible + navigable via docs + facades without any file
physically moving. All 250+ tests stay green.

## Secondary audit findings (quality work to pair with reorg)

Before or alongside reorg, sweep these:

1. **`brain/` folder vs `core/brain/`** — the top-level `brain/`
   appears duplicate/empty. Verify, then remove if dead.
2. **`scripts/` mixes operational daemons with one-off utilities**
   — could split into `scripts/daemons/` (autopilot_loop,
   owner_loop) vs `scripts/utils/` (one-off).
3. **Engine count (137 subdirs / ~2500 files)** — surface the
   most-invoked 50 per quarter into `engines/_registry.py` for
   fast navigation.
4. **`infrastructure/` vs `core/system/`** — look for overlap;
   consolidate if both exist for same concern.
5. **Many `*.db` files in `data/` without a cleanup cadence** —
   add a `scripts/db_rotate.py` that archives > 90-day DBs.
6. **Several unused adapter scaffolds** — wave11 guard catches
   bare excepts but not unreachable modules; run
   `python -m unimport` or equivalent.
7. **CLI (`cli.py`) is ~3800 lines** — split by command family
   into `interface/cli/*.py` with registry pattern.

## Deliverables

- Phase 1: 12 `docs/nav_*.md` files (this commit + next)
- Phase 2: facade packages shipped over 2-3 commits
- Phase 3 audit items tackled one per commit

No architectural change, no test regression, no CLI breakage.
