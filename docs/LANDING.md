# ShopAI

**The autonomous AGI merchant for Shopify.** One command
takes a fresh store from "credentials configured" to
"launchable + earning revenue" — no operator hand-holding.

Available as a CLI, an engine layer, or an **MCP server**
that plugs into Claude Desktop and Claude.ai.

---

## What it does

ShopAI is the **autonomous-write layer** for Shopify.
It ships with:

* **130+ Shopify adapters** covering the GraphQL Admin API
  surface — products, orders, customers, discounts, files,
  themes, marketing events, payouts, returns, segments,
  metaobjects, fulfillment, and the long tail.

* **24+ niche-aware launch modules** that generate
  store-ready content for 11 niches (beauty, fashion,
  tech, home, food, pets, fitness, jewelry, outdoor,
  baby, general):

  | Module | What it ships |
  | --- | --- |
  | Legal policies | 5 essentials + EU Impressum + subscription |
  | Storefront pages | About / Contact / FAQ / Shipping & Returns |
  | Homepage hero | Headline + subhead + CTAs |
  | Theme palette | WCAG AA-compliant 6-token palette |
  | Announcement bar | 2-3 niche-aware banner options |
  | Homepage sections | Niche-tuned section ordering |
  | Newsletter popup | First-visit + exit-intent variants |
  | Email content | Welcome + abandoned-cart + review-request + win-back |
  | Customer support KB | 10-12 Q&A entries |
  | Blog starter | 3 SEO-optimised drafts |
  | Schema.org JSON-LD | Organization + WebSite + FAQPage + BreadcrumbList |
  | Coupon playbook | 6 evergreen discount specs |
  | Welcome discount | Niche-tuned WELCOME{N} code |
  | Customer segments | 7+ universal + niche-specific |
  | Loyalty tiers | Niche-tuned thresholds + earn rates |
  | Cross-sell rules | Niche-aware recommendation rules |
  | Tag taxonomy | Family:value Shopify-native tag library |
  | Smart collections | Rule-driven auto-populating |
  | Manual collections | 4-5 starter buckets per niche |
  | Product enrichment | Descriptions + SEO meta |
  | Brand assets | Logo / favicon / hero / og-image |
  | Metaobject definitions | Ingredient / Material / Recipe / Stone / Stage |

* **Autonomous orchestrator** that fans these out in
  one CLI call:
  ```bash
  shopai store launch --niche beauty
  ```

* **Pattern Z + Pattern Q + Pattern J + Pattern Y +
  Pattern I + OAuth-scope audits.** Every write records
  outcome; every engine emits canonical envelopes; every
  capability is wired to an adapter; every test path is
  guarded against polluting learning databases.

* **MCP server** that exposes 40+ tools to Claude
  Desktop / Claude.ai, so the autonomous merchant runs
  from inside a Claude conversation.

---

## ShopAI vs Anthropic's official Claude × Shopify connector

| | Anthropic Shopify connector | ShopAI |
| --- | --- | --- |
| **Verb** | Read | Write |
| **Tools** | `search_products`, `get_order`, `list_customers`, `get_shop_info` | `recommend_full_launch_pack`, `apply_policies`, `apply_pages`, `apply_homepage_hero`, `audit_launch_readiness`, ... 40+ |
| **Use case** | Ask the Shopify dashboard questions | Drive autonomous launch + edits |
| **Coverage** | Read-mostly Q&A | 130+ adapters across the full Admin API |
| **Niche awareness** | Generic | 11 niches × 24+ modules |
| **Outcome layer** | No | Pattern Z + Q + J + Y audits + learning loop |

**They don't compete — install both.**

Anthropic's connector handles read questions; ShopAI
handles autonomous-write + launch. One Claude
conversation, two MCP servers cooperating:

```
> What's selling well at Acme Beauty this week?
  [Anthropic connector: search_products + get_orders]

> Set up our autumn collection with niche-appropriate
  pages, hero, theme palette, segments, and a welcome
  discount.
  [ShopAI: recommend_full_launch_pack + apply_*]
```

---

## Why "autonomous AGI merchant" — not "Shopify integration"

The bar isn't "the code runs." The bar is **measurable
outcome that a future audit can verify**.

Every applier ShopAI ships goes through:

* **`record_writeback`** (Pattern Z) — outcome flows into
  the Phase 8 learning loop. Decisions made today inform
  decisions next month.

* **Canonical envelope** (Pattern Q) — every engine's
  `run()` returns `{status, data, meta, error}`.
  Auto-detected by CI; engines that drift get flagged.

* **OAuth scope registry** — every adapter declares its
  required scopes; the aggregator surfaces total scope
  surface for a given store config.

* **Per-store empire-AGI** — actions are tagged with
  `store_id`, segments are joinable cross-store, and
  the recommender learns "what worked in store A might
  work in store B."

This is what makes it AGI-grade, not free-tool-grade:

* A free Shopify tool runs and stops. Outcomes don't
  feed back.
* ShopAI runs, records, learns, and recommends. The
  loop closes.

---

## Install

### CLI + engine layer

```bash
git clone https://github.com/batkabatka362-cmyk/shopai
cd shopai
pip install -e .
shopai --help
```

### MCP server for Claude Desktop / Claude.ai

```bash
pip install -e ".[mcp]"
```

Add to Claude Desktop's config:

```json
{
  "mcpServers": {
    "shopai": {
      "command": "shopai-mcp",
      "env": {
        "SHOPIFY_STORE_DOMAIN": "your-store.myshopify.com",
        "SHOPIFY_ADMIN_TOKEN": "shpat_xxxxx"
      }
    }
  }
}
```

Restart Claude Desktop. ShopAI's 40+ tools appear in the
model's tool list. See [`docs/MCP_INSTALL.md`](MCP_INSTALL.md)
for the full setup + troubleshooting.

---

## Example session

```
> claude, set up Acme Beauty for launch -- niche beauty,
  region us, founder Jane Doe.

Claude calls:
  - recommend_full_launch_pack(...)
    → returns 5 policies + 4 pages + 4 collections
      + homepage hero spec + palette spec + ...

> looks good, apply it.

Claude calls:
  - apply_policies(...)
  - apply_pages(...)
  - apply_starter_collections(...)
  - apply_homepage_hero(...)
  - apply_theme_palette(...)
  - apply_announcement_bar(...)
  - apply_email_templates(...)
  - apply_customer_segments(...)
  ... (13+ Shopify writes)

> audit readiness.

Claude calls:
  - audit_launch_readiness(store_id="...")
    → ready_to_launch=True, completion_pct=100,
      8/8 checks passed.
```

That's the **autonomous merchant** — not a Q&A wrapper
over the admin.

---

## Status

* **27 PRs in flight** as of 2026-05-20, covering the
  full niche-aware launch chain + MCP server +
  packaging.
* **CI green** on all session-PRs that have results.
* **Pattern Z / Q / J / Y / I audits** in CI on every
  PR.

See [`docs/MERGE_READINESS.md`](MERGE_READINESS.md) for
the current merge queue + recommended order.

---

## License

MIT.
