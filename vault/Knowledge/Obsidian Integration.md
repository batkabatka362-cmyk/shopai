---
title: Obsidian Integration
tags:
  - knowledge
  - obsidian
  - memory
source: ShopAI codebase
created: 2026-04-13
---
# Obsidian Integration

## Гол мэдээлэл

ShopAI нь Obsidian vault-ыг мэдлэгийн сан болгон ашигладаг.
Хоёр чиглэлтэй:

### Import (Vault → ShopAI)
- `VaultMemoryBridge.import_vault()` — бүх `.md` файлуудыг уншина
- QualityEngine-ээр ангилна (KNOWLEDGE / SIGNAL / NOISE)
- UnifiedMemory-руу хадгална
- Content hash-аар idempotent — өөрчлөгдөөгүй note-ийг алгасна

### Export (ShopAI → Vault)
- `VaultMemoryBridge.export_knowledge()` — сурсан зүйлсийг бичнэ
- `ShopAI/Learned/` folder-руу markdown болгон бичнэ
- Frontmatter: source, confidence, tags
- Controller-ийн reflection hook-оос автоматаар дуудагдана

### Search
- `VAULT_SEARCH_NOTES` — бүтэн текстээр хайлт
- Title match → өндөр оноо, body match → бага оноо
- Tag, folder-оор шүүх боломжтой

## Тохиргоо

```bash
export OBSIDIAN_VAULT_PATH="./vault"
```

## Файлууд

- `core/adapters/obsidian/parser.py` — Markdown задлагч
- `core/adapters/obsidian/vault.py` — Adapter
- `core/adapters/obsidian/memory_bridge.py` — Хоёр чиглэлтэй sync
- `core/adapters/obsidian/bootstrap.py` — Registry бүртгэл

## Холбоотой

- [[ShopAI Architecture]] — бүтэц
- [[Adapter Pattern]] — adapter pattern
- [[Use Obsidian for Memory]] — шийдвэрийн бичлэг
