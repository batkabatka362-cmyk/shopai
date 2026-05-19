# ShopAI MCP Server — Install + Wire to Claude

The ShopAI MCP server exposes 40+ autonomous-merchant
tools to Claude Desktop / Claude.ai users. Once wired,
you can drive the full autonomous launch directly from a
Claude conversation:

> *Claude, set up my "Acme Beauty" store with the full
> launch pack and audit readiness when done.*

## Install

### Option A — Local clone (dev / pre-publish)

```bash
git clone https://github.com/batkabatka362-cmyk/shopai
cd shopai
pip install -e ".[mcp]"
```

`-e` installs in editable mode so changes to the ShopAI
source flow through immediately. `[mcp]` pulls in the
`mcp` Python SDK (the protocol implementation).

### Option B — From PyPI (when published)

```bash
pip install "shopai[mcp]"
```

The base `shopai` package gives you the engine layer +
CLI. The `[mcp]` extra adds the MCP protocol server.

## Verify the install

After install, two binaries are on PATH:

```bash
shopai-mcp --help    # MCP server (stdio default)
shopai --help        # The full CLI
```

Smoke-test the MCP server:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
    | shopai-mcp
```

You should see a JSON array of 40+ tools.

## Wire to Claude Desktop

Edit Claude Desktop's config file:

* **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
* **Linux:** `~/.config/Claude/claude_desktop_config.json`

Add the `shopai` entry under `mcpServers`:

```json
{
  "mcpServers": {
    "shopai": {
      "command": "shopai-mcp",
      "args": [],
      "env": {
        "SHOPIFY_STORE_DOMAIN": "your-store.myshopify.com",
        "SHOPIFY_ADMIN_TOKEN": "shpat_xxxxx"
      }
    }
  }
}
```

Restart Claude Desktop. The 40+ ShopAI tools appear in
the model's tool list automatically.

## What you can ask Claude

Once connected, Claude can call any ShopAI tool. Useful
prompts:

* "List the niches ShopAI supports."
  → `list_niches()`

* "Show me what ShopAI would set up for a beauty store
  called Acme."
  → `recommend_full_launch_pack(store_name="Acme",
  niche="beauty")`

* "Apply the full launch pack to my store."
  → `apply_policies(...)` + `apply_pages(...)` +
  `apply_starter_collections(...)` etc.

* "Audit my store's launch readiness."
  → `audit_launch_readiness(store_id="...")`

* "Recommend a niche-appropriate theme palette and
  show me the contrast ratios."
  → `recommend_theme_palette(niche="beauty")`

* "Generate a 3-step win-back email sequence for
  lapsed customers."
  → `recommend_winback_email(store_name="Acme",
  niche="beauty")`

## Coexistence with Anthropic's official Shopify connector

Anthropic ships a Shopify connector that's primarily
READ-oriented (`search_products`, `get_order`,
`list_customers`). It turns the Shopify admin into a
chat interface.

ShopAI's MCP server is **WRITE-oriented**: launch a
store, generate niche-aware content, audit readiness,
apply changes via 130+ adapters.

The two **don't compete** — install both. Anthropic's
handles read questions; ShopAI handles autonomous
write + launch. One Claude conversation, two MCP
servers cooperating.

```json
{
  "mcpServers": {
    "shopify": {
      "command": "...anthropic shopify connector..."
    },
    "shopai": {
      "command": "shopai-mcp"
    }
  }
}
```

## Wire to Claude.ai (web)

Claude.ai supports **Custom Connectors** for MCP servers
exposed over SSE (HTTP). Local stdio servers like the
default `shopai-mcp` aren't directly reachable from the
web; run the SSE flavour instead:

```bash
shopai-mcp --sse --host 0.0.0.0 --port 8765
```

Then add a Custom Connector in Claude.ai pointing at
`http://your-host:8765/`. (Recommended: front this with
a reverse proxy + auth for any production deployment.)

## Available tools

See `core/mcp_server/tools.py` + `extended_tools.py` for
the canonical list. Quick summary:

**Core (10):**
`list_niches`, `health`, `recommend_starter_collections`,
`recommend_pages`, `recommend_policies`,
`recommend_full_launch_pack`, `audit_launch_readiness`,
`apply_starter_collections`, `apply_pages`,
`apply_policies`.

**Extended (~34, ship as niche-aware PRs merge):**

* Content: `recommend_homepage_hero`,
  `recommend_theme_palette`, `recommend_support_kb`,
  `recommend_email_templates`, `recommend_blog_starter`,
  `recommend_coupon_playbook`,
  `recommend_structured_data`,
  `recommend_customer_segments`,
  `recommend_loyalty_tiers`,
  `recommend_announcement_bar`,
  `recommend_metaobject_definitions`,
  `recommend_review_email`, `recommend_winback_email`,
  `recommend_homepage_sections`,
  `recommend_newsletter_popup`,
  `recommend_cross_sell_rules`,
  `recommend_welcome_discount`,
  `recommend_tag_library`,
  `recommend_smart_collections`.

* Apply: `apply_homepage_hero`, `apply_theme_palette`,
  `apply_support_kb`, `apply_email_templates`,
  `apply_blog_starter`, `apply_structured_data`,
  `apply_customer_segments`,
  `apply_announcement_bar`,
  `apply_metaobject_definitions`,
  `apply_review_email`, `apply_winback_email`,
  `apply_homepage_sections`, `apply_newsletter_popup`,
  `apply_cross_sell_rules`, `apply_smart_collections`.

Lazy imports mean tools whose base PR hasn't merged
yet return a clean `engine_unavailable` envelope
rather than crashing. As each base PR lands, the
corresponding tool flips to working with no MCP
server redeploy.

## Troubleshooting

**`mcp` import error on `shopai-mcp` startup.**
The `mcp` Python SDK isn't installed. Re-run with the
extra:

```bash
pip install "shopai[mcp]"
```

**Tool returns `engine_unavailable: ...`.**
The base PR for that tool's underlying engine module
hasn't merged yet. Check the merge readiness report
(`docs/MERGE_READINESS.md`) for the queue.

**Tool returns `router_unavailable`.**
Shopify credentials aren't configured. Set
`SHOPIFY_STORE_DOMAIN` + `SHOPIFY_ADMIN_TOKEN` env vars
in the Claude Desktop config under the `shopai` server's
`env` key.

**Claude Desktop doesn't see the tools.**
Restart Claude Desktop after editing the config.
Verify the `command` resolves on PATH: run
`which shopai-mcp` (mac/Linux) or `where shopai-mcp`
(Windows) -- if it doesn't resolve, the install didn't
expose the entry point. Re-run `pip install -e .`.
