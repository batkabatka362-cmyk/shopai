---
title: ShopAI Architecture
tags:
  - concept
  - architecture
  - core
related:
  - Adapter Pattern
  - Obsidian Integration
created: 2026-04-13
---
# ShopAI Architecture

## Тодорхойлолт

ShopAI бол Shopify дэлгүүрүүдэд зориулсан автономит AI систем.
9 үе шаттай сэтгэлгээний цикл, 14+ adapter категори, олон давхар
санах ойн архитектуртай.

## Гол бүрэлдэхүүн хэсгүүд

### Brain (Тархи)
- `core/brain/` — шийдвэр гаргалт, debate, cognitive функцүүд
- 5 persona debate систем (Analyzer, Planner, Executor, Critic, MemoryManager)
- [[Adapter Pattern]]-ээр гадаад сервисүүдтэй холбогдоно

### Memory (Санах ой)
- `core/memory/unified_memory.py` — UnifiedMemory (7+ backend)
- SharedMemory, BrainMemory, Experience, DataArchitecture
- Satellite layers: Vector, Graph, Signal
- [[Obsidian Integration]] — vault-аар дамжуулсан мэдлэгийн сан

### Safety (Аюулгүй байдал)
- `core/safety/policy_checker.py` — HARD/MEDIUM/SOFT policy tiering
- Аудит лог: `.shopai/policy_audit.jsonl`

### Adapters (Адаптерууд)
- [[Adapter Pattern]] — 14 категори, 30 capability
- SmartRouter — хамгийн тохиромжтой adapter автоматаар сонгоно
- [[Shopify API Basics]] — Shopify-тэй холбогдох адаптер

### Autonomous Controller
- `core/autonomous/controller.py` — автономит ажиллагааны удирдлага
- Reflection hook — сурсан зүйлсийг [[Obsidian Integration]]-руу бичнэ

## Яагаад чухал вэ

Энэ бол ShopAI-ийн бүхэл бүтэн системийн газрын зураг. Шинэ feature
нэмэхдээ эндээс эхэлж, холбогдох бүрэлдэхүүнийг олно.
