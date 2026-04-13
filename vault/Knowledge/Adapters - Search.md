---
title: "Adapters - Search"
tags: [knowledge, adapters, search, intelligence]
created: "2026-04-13"
related:
  - "[[_Adapters Catalog]]"
  - "[[_Capabilities MOC]]"
---

# Adapters - Search

## Summary

Search adapters give ShopAI a view outside the store — competitor
research, market intelligence, news monitoring. Five vendors cover
keyword search, semantic search, and traffic estimation.

## Adapters

| Adapter | Priority | Auth | Specialty |
|---------|----------|------|-----------|
| **Brave** | 85 | `BRAVE_SEARCH_API_KEY` | Independent web index |
| **Serper** | 80 | `SERPER_API_KEY` | Google SERP scraper |
| **Exa** | 75 | `EXA_API_KEY` | Neural / semantic search |
| **DDGS** | 60 | none | DuckDuckGo HTML; free fallback |
| **SimilarWeb** | 50 | `SIMILARWEB_API_KEY` | Traffic + competitor intel |

## Capabilities

- `SEARCH_WEB` — keyword search
- `SEARCH_SEMANTIC` — neural / embedding-based (Exa)
- `TRAFFIC_ESTIMATE` — monthly visitors etc. (SimilarWeb)

## When each wins

- Breaking news / product discovery → **Brave**
- SERP ranking for a keyword → **Serper**
- "Similar to …" discovery → **Exa**
- No API key available → **DDGS** (rate-limit risk)
- Competitor traffic audit → **SimilarWeb**

## Related

- [[_Capabilities MOC]]
- [[_Adapters Catalog]]
