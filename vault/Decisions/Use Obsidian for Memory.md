---
title: "Use Obsidian for Memory"
tags: [decision, memory, obsidian]
created: "2026-04-13"
status: "accepted"
outcome: "successful"
related:
  - "[[ShopAI Architecture]]"
  - "[[Obsidian Integration]]"
  - "[[Obsidian Integration Complete]]"
---

# Use Obsidian for Memory

## Context

ShopAI needed a knowledge base that operators could visualize and explore. The existing JSON-based memory worked but was invisible - no one could see what ShopAI had learned or how concepts connected.

## Options Considered

1. **Obsidian (local vault)** - Markdown files with YAML frontmatter, graph view, free, no server needed
   - Pros: Visual graph, operator-friendly, zero ops, versioned in git
   - Cons: Not a real database, no concurrent writes
2. **Notion API** - Cloud-based wiki with API
   - Pros: Collaborative, rich formatting
   - Cons: API rate limits, vendor dependency, cost
3. **Custom database** - Build a knowledge graph from scratch
   - Pros: Full control
   - Cons: Violates "don't build new features" principle, massive effort

## Decision

**Obsidian** - It follows the core principle: use existing, battle-tested tools. Obsidian's graph view is exactly what we need for visualizing ShopAI's knowledge. Files on disk means zero infrastructure.

## Consequences

- Operators can open the vault in Obsidian and explore ShopAI's knowledge visually
- Auto-export from learning loop means the vault grows automatically
- Templates ensure consistent note structure
- Graph view shows connections between concepts, errors, wins, and decisions

## Outcome

Successfully implemented. See [[Obsidian Integration Complete]].

## Related

- [[Obsidian Integration]] - Technical details
- [[ShopAI Architecture]] - Where it fits
