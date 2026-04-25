# ShopAI docs — navigation index

## 1. Architecture + mission

- **[CLAUDE.md](../CLAUDE.md)** — agent operating rules
  (mission, §4c autonomous master prompt, §4b senior-engineer
  discipline).
- **[ARCHITECTURE.md](../ARCHITECTURE.md)** — high-level vision.
- **[AGI_STACK.md](./AGI_STACK.md)** — 10-layer stack +
  6 extension layers.

## 2. Active plans

- **[IMPLEMENTATION_PLAN_2026.md](./IMPLEMENTATION_PLAN_2026.md)**
  — 8 Wave items, all shipped.
- **[FOLDER_REORG_PLAN.md](./FOLDER_REORG_PLAN.md)** — 12-folder
  concept mapping. Phase 1 + 2 shipped.
- **[REPO_STRUCTURE_AUDIT.md](./REPO_STRUCTURE_AUDIT.md)** —
  per-folder audit with findings + 5 cleanup items.

## 3. Historical plans

- [AGI_MISSION_PLAN.md](./AGI_MISSION_PLAN.md)
- [AGI_HARDENING_PLAN.md](./AGI_HARDENING_PLAN.md)
- [AGI_ROADMAP.md](./AGI_ROADMAP.md) (if present)

## 4. Research

- **[MARKET_RESEARCH_2026.md](./MARKET_RESEARCH_2026.md)** —
  12-agent synthesis (Wave 1 baseline 2024-2025 + Wave 2 Q1-Q2
  2026 deltas).

## 5. 12-concept folder map

The repo is organized into 12 conceptual groups surfaced by
facades. Physical files live in legacy paths for backward
compat; facades re-export them.

| Concept | Nav doc | Physical source | Facade |
|---|---|---|---|
| core | [nav_core.md](./nav_core.md) | `core/` | n/a (already top-level) |
| orchestrator | [nav_orchestrator.md](./nav_orchestrator.md) | `core/core_orchestrator.py`, `scripts/autopilot_loop.py`, `scripts/owner_loop.py`, `execution/launch/*` | `orchestrator/` |
| interface | [nav_interface.md](./nav_interface.md) | `cli.py`, `api/`, `mcp_server/`, `agents/owner_dialog/` | `interface/` |
| feedback | [nav_feedback.md](./nav_feedback.md) | `core/attribution/`, `core/bridge/agentic_storefront.py`, `core/integration/engine_outcome_bus.py` | `feedback/` |
| evaluation | [nav_evaluation.md](./nav_evaluation.md) | `simulation/`, `execution/verify/`, `core/brain/world_model_calibration.py`, `tests/` | `evaluation/` |
| modules | [nav_modules.md](./nav_modules.md) | `core/risk`, `core/crisis`, `core/legal`, `core/planning`, `core/federation`, `execution/compliance`, `execution/fulfillment`, `execution/seo` | `modules/` |
| flow | [nav_flow.md](./nav_flow.md) | `agents/learning/`, `core/memory/consolidator.py`, `core/learning/rulebook.py`, `core/learning/pattern_miner.py`, `core/learning/llm_pattern_miner.py`, `workflows/` | `flow/` |
| agents | [nav_agents.md](./nav_agents.md) | `agents/` | n/a |
| layers | [nav_layers.md](./nav_layers.md) | `layers/` | n/a |
| engines | [nav_engines.md](./nav_engines.md) | `engines/` (~2,500 files) | n/a |
| tools | [nav_tools.md](./nav_tools.md) | `tools/`, `scripts/` | n/a |
| adapters | [nav_adapters.md](./nav_adapters.md) | `core/adapters/` | `adapters/` |

## 6. CLI surface

Run `python cli.py --help` for the full list. Key commands
shipped in this branch:

- `risk status / limits / recent` — L7 tripwire
- `crisis status / halt / resume / events` — LX.4
- `simulate` — L8 Monte Carlo projection
- `brain` — holistic BrainState snapshot
- `predict` — world-model what-if
- `brain-learned` — RuleBook + promoted patterns
- `memory` — episodic → concept → procedure ladder
- `trust` — source-trust calibrator
- `explain` / `explains` — rationale ledger
- `vault-sweep` — Obsidian constraint import
- `plan-quarter` / `plan-checkin` — L4 quarterly planner
- `ask-support` — LX.1 customer chatbot preview
- `notify` — push launch digest to Telegram
- `owner-poll` — one-shot Telegram command dispatcher
- `federation status / register / observe / score / best` —
  LX.5 multi-store
- `niches` — niche discovery with trend scorer
- `agentic status / metrics` — Wave B-1 AI channels
- `landed-cost` — Wave F-1 de-minimis aware cost

## 7. Tests

`PYTHONPATH=. pytest tests/ -q` — 223+ green in this branch.
Key test files map 1:1 to modules (test_risk_tripwire.py,
test_landed_cost.py, etc.).

## 8. Daemons

- `scripts/autopilot_loop.py` — 24/7 winner → publish →
  activate cycle
- `scripts/owner_loop.py` — Telegram poll + digest push

systemd units in `scripts/shopai-*.service`.
