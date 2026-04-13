---
title: Shopify API Basics
tags:
  - knowledge
  - shopify
  - api
source: Shopify Developer Docs
created: 2026-04-13
---
# Shopify API Basics

## Гол мэдээлэл

### Authentication
- `SHOPAI_SHOPIFY_URL` — дэлгүүрийн URL (`mystore.myshopify.com`)
- `SHOPAI_SHOPIFY_KEY` — Admin API access token
- GraphQL Admin API ашигладаг (REST биш)

### Rate Limits
- GraphQL: cost-based throttling (1000 cost point / sec)
- REST: 40 req / sec (bucket, leaky bucket algorithm)
- Rate limit-д орвол 429 буцааж, `Retry-After` header-тэй

### Гол endpoint-ууд
- Products — `SHOPIFY_FETCH_PRODUCTS`
- Orders — `SHOPIFY_FETCH_ORDERS`
- Customers — `SHOPIFY_FETCH_CUSTOMERS`
- Inventory — `SHOPIFY_UPDATE_INVENTORY`
- Fulfillment — `SHOPIFY_CREATE_FULFILLMENT`

## Хэрэглээ

[[Adapter Pattern]]-ийн Shopify категорийн adapter-ууд эдгээр
endpoint-уудыг ашиглана. [[ShopAI Architecture]]-ийн autonomous
controller дамжуулж дууддаг.

## Лавлагаа

- Shopify Admin API docs
- GraphQL Storefront API docs

## Холбоотой

- [[Adapter Pattern]] — adapter бүтэц
- [[ShopAI Architecture]] — системийн бүтэц
