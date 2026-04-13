---
title: Adapter Pattern
tags:
  - concept
  - adapter
  - architecture
related:
  - ShopAI Architecture
  - Shopify API Basics
created: 2026-04-13
---
# Adapter Pattern

## Тодорхойлолт

ShopAI-ийн бүх гадаад сервис (LLM, email, SMS, хайлт, төлбөр...)
нэг стандарт interface-ээр ажилладаг. `BaseAdapter` → `_execute()` →
`AdapterResult` гэсэн гинж.

## Бүтэц

```
BaseAdapter (abstract)
├── name: str              — "twilio", "obsidian" гэх мэт
├── category: AdapterCategory — SMS, KNOWLEDGE_BASE, LLM...
├── capabilities: set      — юу хийж чадах вэ
├── is_configured() → bool — API key/config байгаа эсэх
└── _execute(capability, params) → AdapterResult
```

## 14 Категори

LLM, Shopify, Search, Email, SMS, Image, Translation, Payment,
Shipping, Scraper, Reviews, Image CDN, Analytics, **Knowledge Base**

## SmartRouter

`AdapterRegistry` бүх adapter-уудыг хадгална. `SmartRouter` нь
capability-аар хайж, `is_configured()` шалгаж, priority/cost-оор
эрэмбэлж, хамгийн тохиромжтойг сонгоно.

## Холбоотой

- [[ShopAI Architecture]] — ерөнхий архитектур
- [[Shopify API Basics]] — Shopify adapter-ийн API
- [[Obsidian Integration]] — Knowledge Base категорийн adapter
- [[Use Obsidian for Memory]] — яагаад Obsidian сонгосон
