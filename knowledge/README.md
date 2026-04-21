# knowledge/ — static knowledge base

This folder holds **hand-curated, author-owned knowledge** —
artefacts the owner writes and ShopAI reads. Distinct from
`core/memory/`, which holds **learned data** that ShopAI
writes from runtime outcomes.

## Contents

- `rules/rule_engine.py` — declarative if-condition → action
  business rules (e.g. "if ROAS < 1.5 for 3 days → pause").
  These are *authored* rules. Contrast with
  `core/learning/rulebook.py`, which holds *learned* rules
  promoted from observed outcomes.
- `prompts/prompt_manager.py` — named LLM prompt templates
  the owner maintains (ad copy, product description, email).
- `schemas/schema_registry.py` — JSON schema definitions for
  data contracts between engines. Contrast with
  `execution/seo/schema_stack.py`, which emits SEO JSON-LD.
- `strategies/strategy_store.py` — persistence for strategy
  definitions. Contrast with `core/brain/strategy_planner.py`,
  which *generates* strategies from goals.

## When to edit knowledge/ vs core/memory/

| Source of truth   | Edited by | Lives in          |
|-------------------|-----------|-------------------|
| Business rules    | Owner     | `knowledge/rules` |
| Learned patterns  | Runtime   | `core/learning/rulebook.py` |
| Product metadata  | Owner     | `knowledge/`      |
| Observed events   | Runtime   | `core/memory/`    |
| LLM prompts       | Owner     | `knowledge/prompts` |
| Rationale records | Runtime   | `core/decision/rationale_ledger.py` |

Rule of thumb: if a human types it, it lives here. If the
system derives it, it lives in `core/memory/` or
`core/learning/`.

## Import sites (current)

- `core/full_system_loop.py` — RuleEngine
- `core/orchestrator/main_orchestrator.py` — RuleEngine +
  PromptManager

## Naming audit (2026-04-20)

The docs/REPO_STRUCTURE_AUDIT.md cleanup item 3 flagged
`knowledge/` as a possible conflict with `core/memory/` and
`vault/Knowledge/`. After inspection the three are
complementary, not overlapping:

- `knowledge/` — author-owned, code-level
- `core/memory/` — system-learned, runtime data
- `vault/Knowledge/` — owner notes in Obsidian markdown

No rename or migration required. This README codifies the
boundary so future agents don't re-open the question.
