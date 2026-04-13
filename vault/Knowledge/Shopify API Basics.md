---
title: "Shopify API Basics"
tags: [knowledge, reference, shopify]
created: "2026-04-13"
source: "https://shopify.dev/docs/api"
related:
  - "[[ShopAI Architecture]]"
  - "[[Adapter Pattern]]"
---

# Shopify API Basics

## Overview

Shopify provides two main APIs that ShopAI uses to manage stores: the Admin REST API and the GraphQL Admin API.

## Key Endpoints

### Products
- `GET /admin/api/2024-01/products.json` - List products
- `POST /admin/api/2024-01/products.json` - Create product
- `PUT /admin/api/2024-01/products/{id}.json` - Update product

### Orders
- `GET /admin/api/2024-01/orders.json` - List orders
- `POST /admin/api/2024-01/orders/{id}/fulfillments.json` - Create fulfillment

### Customers
- `GET /admin/api/2024-01/customers.json` - List customers
- Customer segmentation via GraphQL

### Inventory
- `POST /admin/api/2024-01/inventory_levels/set.json` - Set inventory level

## Authentication

ShopAI uses a private app access token:
- `X-Shopify-Access-Token` header
- Configured via `SHOPAI_SHOPIFY_KEY` env var

## Rate Limits

- REST API: 2 requests/second per app
- GraphQL: 1,000 cost points per second
- ShopAI's adapter handles retry + backoff automatically

## ShopAI Capabilities

| Capability | What it does |
|-----------|-------------|
| `shopify_fetch_products` | Read product catalog |
| `shopify_fetch_orders` | Read order history |
| `shopify_create_fulfillment` | Ship an order |
| `shopify_assess_risk` | Check order fraud risk |
| `shopify_update_inventory` | Adjust stock levels |
| `shopify_create_discount` | Create discount codes |

## Related

- [[ShopAI Architecture]] - How Shopify fits in
- [[Adapter Pattern]] - How the Shopify adapter is built
