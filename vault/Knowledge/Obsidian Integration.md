---
title: "Obsidian Integration"
tags: [knowledge, reference, obsidian, memory]
created: "2026-04-13"
source: "core/adapters/obsidian/"
related:
  - "[[ShopAI Architecture]]"
  - "[[Use Obsidian for Memory]]"
---

# Obsidian Integration

## Overview

ShopAI uses an Obsidian vault as its knowledge base. The graph view creates visual connections between concepts, errors, wins, and learned patterns - giving operators a visual map of everything ShopAI knows.

## How It Works

### VaultMemoryBridge
- Reads/writes Markdown notes to the vault directory
- Parses YAML frontmatter for metadata
- Supports wikilinks `[[like this]]` for graph connections

### Adapter Capabilities
- `VAULT_READ_NOTES` - Read notes from the vault
- `VAULT_SEARCH_NOTES` - Full-text search across notes
- `VAULT_WRITE_NOTE` - Create/update notes

### Auto-Export
After each autonomous cycle, the controller's reflection hook exports promoted patterns to `ShopAI/Learned/`. This means the vault grows automatically as ShopAI learns.

## Vault Structure

```
vault/
  Concepts/       - Core knowledge and architecture docs
  Knowledge/      - Reference information and API docs
  Errors/         - Failure patterns and postmortems
  Wins/           - Success patterns and what worked
  Decisions/      - Decision records with rationale
  ShopAI/Learned/ - Auto-exported learned patterns
  Templates/      - Note templates for each category
```

## Configuration

Set `OBSIDIAN_VAULT_PATH=./vault` in your environment to enable the integration.

## Graph View

Open the vault in Obsidian to see the graph. Color groups:
- **Blue** - Concepts
- **Red** - Errors
- **Green** - Wins
- **Purple** - Decisions
- **Orange** - ShopAI auto-learned patterns

## Related

- [[ShopAI Architecture]] - Where Obsidian fits
- [[Use Obsidian for Memory]] - Why we chose Obsidian
