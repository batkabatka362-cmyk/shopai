---
title: Use Obsidian for Memory
tags:
  - decision
  - obsidian
  - memory
status: active
date: 2026-04-13
outcome: success
---
# Use Obsidian for Memory

## Контекст

ShopAI-д хүний уншиж, засварлаж, хянаж болох мэдлэгийн сан
хэрэгтэй байсан. Систем юу сурсан, юун дээр алдсан, юу мэддэг
болохыг нүдээр харах боломжтой байх ёстой.

## Сонголтууд

1. **Obsidian** — Локал markdown, graph view, wikilinks, plugin ecosystem
2. **Notion** — Cloud-based, API хэрэгтэй, rate limit-тэй
3. **Plain JSON/SQLite** — Хүнд уншигдахуйц биш, visual view байхгүй

## Шийдвэр

**Obsidian** сонгосон, учир нь:
- **Graph view** — бүх холболтыг визуал харуулна
- **Локал** — API key шаардлагагүй, хурдан, бүрэн хяналттай
- **Markdown** — git-д хадгалж болно, хүн уншиж болно
- **Wikilinks** — `[[note]]` ашиглаж мэдлэгийг холбоно
- **Plugin ecosystem** — Dataview, Templater зэргийг дараа нэмж болно

## Үр дагавар

- `core/adapters/obsidian/` package бүтсэн
- `KNOWLEDGE_BASE` adapter категори нэмэгдсэн
- Хоёр чиглэлтэй sync: vault ↔ UnifiedMemory
- Хүн (оператор) ба AI (ShopAI) хоёулаа нэг мэдлэгийн санд ажиллана

## Холбоотой

- [[Obsidian Integration]] — техникийн хэрэгжүүлэлт
- [[ShopAI Architecture]] — ерөнхий архитектур
- [[Adapter Pattern]] — adapter бүтэц
- [[Obsidian Integration Complete]] — амжилтын бичлэг
