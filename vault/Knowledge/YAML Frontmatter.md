---
title: "YAML Frontmatter"
tags: [knowledge, obsidian, yaml, notes]
created: "2026-04-13"
related:
  - "[[Obsidian Integration]]"
  - "[[Graph View Tips]]"
---

# YAML Frontmatter

## Summary

Every note in this vault starts with a YAML block. ShopAI's
parser reads this block; Obsidian reads it too for graph colour,
filters, and dataview queries. Consistent frontmatter is how notes
become machine-readable *and* human-readable.

## Schema

```yaml
---
title: "My Note"            # required; auto-set on write
tags: [concept, example]    # list or comma-separated
created: "2026-04-13"       # auto-set on write if missing
aliases: ["Alt Name"]       # optional; Obsidian accepts as [[Alt Name]]
related:                    # optional; explicit wikilink manifest
  - "[[Other Note]]"
---
```

## Category-specific fields

Beyond the core schema, some categories add extras:

| Folder | Extra fields |
|--------|--------------|
| `Wins/` | `cycle_id`, `store_id`, `phase_error_count`, `date` |
| `Errors/` | `cycle_id`, `store_id`, `phase_error_count`, `date` |
| `Decisions/` | `cycle_id`, `store_id`, `action`, `status`, `date` |
| `ShopAI/Learned/` | `source: "shopai"`, `confidence`, `exported_at` |

## Tips

- Quote every string value — YAML `title: Foo: Bar` breaks on the colon
- Use the array form for tags: `tags: [a, b]` not `tags: a, b`
- `created` is ISO-8601 date; `exported_at` is ISO-8601 datetime
- Avoid special characters in `title` — they become the filename

## Related

- [[Obsidian Integration]] — the parser
- [[Graph View Tips]] — how frontmatter drives colour groups
