---
title: "Graph View Tips"
tags: [knowledge, obsidian, graph, operator]
created: "2026-04-13"
related:
  - "[[Obsidian Integration]]"
  - "[[YAML Frontmatter]]"
  - "[[00 Home]]"
---

# Graph View Tips

## Summary

The whole point of choosing Obsidian was the **graph view**. Tips
here are for operators opening this vault for the first time —
how to read what ShopAI has learned at a glance.

## Opening the graph

- `Ctrl/Cmd + G` opens the graph panel
- `Ctrl/Cmd + Shift + G` opens the **local graph** (current note + neighbours)

## Colour groups

Set once in `.obsidian/graph.json` — every folder gets a colour:

| Folder | Colour | Meaning |
|--------|--------|---------|
| `Concepts/` | **blue** | Durable knowledge |
| `Knowledge/` | **cyan** | Reference / how-to |
| `Errors/` | **red** | Things that broke |
| `Wins/` | **green** | Things that worked |
| `Decisions/` | **purple** | ADRs + auto-logged cycle decisions |
| `ShopAI/Learned/` | **orange** | Auto-exported patterns |

Orange nodes growing = the system is learning. Red clusters = a
repeating error pattern — look at the wikilinks to see which
concepts are implicated.

## Navigating

- Start at [[00 Home]]
- [[_Concepts MOC]] → mental model
- [[_Adapters Catalog]] → every vendor
- [[_Capabilities MOC]] → capability to adapter mapping

## Reading the graph

- **Hub nodes** (MOCs, Architecture) sit in the centre with many
  spokes
- **Cluster nodes** (category adapter pages) sit between hubs and
  leaves
- **Leaf nodes** (individual wins/errors/decisions) are the
  periphery and grow over time
- **Orphans** (0-link notes) usually mean a broken wikilink or a
  stub that needs fleshing out

## Related

- [[Obsidian Integration]]
- [[YAML Frontmatter]]
- [[00 Home]]
