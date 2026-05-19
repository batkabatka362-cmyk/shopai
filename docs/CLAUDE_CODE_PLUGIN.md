# ShopAI as a Claude Code Plugin

ShopAI ships a Claude Code plugin bundle that combines:

  - The MCP server (40+ autonomous-merchant tools)
  - 4 slash commands wrapping common workflows
  - A manifest file (`plugin/plugin.json`) listing them

After install, you can drive the full autonomous launch
from Claude Code with one-liners:

```
/shopai-launch beauty "Acme Beauty"
/shopai-audit
/shopai-recommend homepage_hero "Acme Beauty" beauty
/shopai-niches
```

## Install

### 1. Clone + install the Python package

```bash
git clone https://github.com/batkabatka362-cmyk/shopai
cd shopai
pip install -e ".[mcp]"
```

This makes the `shopai-mcp` binary available on PATH.

### 2. Register the MCP server with Claude Code

```bash
claude mcp add shopai shopai-mcp \
    --env SHOPAI_SHOPIFY_URL=your-store.myshopify.com \
    --env SHOPAI_SHOPIFY_KEY=shpat_xxxxx
```

Or set the env vars globally + skip the `--env` flags.

Confirm registration:

```bash
claude mcp list
```

You should see `shopai` listed with the 40+ tools.

### 3. Install the slash commands

```bash
# Copy the plugin's commands into Claude Code's
# commands directory.
mkdir -p ~/.claude/commands
cp -r plugin/commands/*.md ~/.claude/commands/
```

Verify:

```bash
ls ~/.claude/commands/shopai-*.md
```

Should list: `shopai-launch.md`, `shopai-audit.md`,
`shopai-recommend.md`, `shopai-niches.md`.

### 4. Restart Claude Code

```bash
# Exit the current session, then:
claude
```

The 4 slash commands + 40+ MCP tools are now available.

## Usage

### `/shopai-niches`

Lists the niches ShopAI supports. Use first if you're
unsure which niche fits your store.

```
> /shopai-niches

ShopAI supports 11 niches:
  beauty, fashion, tech, home, food, pets, fitness,
  jewelry, outdoor, baby, general

Next: /shopai-launch <niche> <store_name>
```

### `/shopai-recommend <module> <store_name> [niche]`

Preview what ShopAI would recommend WITHOUT applying.
Read-only. Safe to run on production.

```
> /shopai-recommend homepage_hero "Acme Beauty" beauty

[ShopAI calls recommend_homepage_hero(...)]

Acme Beauty homepage hero
  headline: "Beauty that earns the bathroom shelf."
  subhead:  "Acme Beauty: clean formulas, honest..."
  primary CTA: "Shop Best Sellers" -> /collections/skincare
  secondary CTA: "Read Our Story" -> /pages/about

Apply with: /shopai-recommend apply_homepage_hero ...
```

### `/shopai-launch <niche> <store_name> [region]`

End-to-end autonomous launch. Confirms before writing,
then applies in dependency order, then runs the audit.

```
> /shopai-launch beauty "Acme Beauty"

[recommend_full_launch_pack -> 5 policies + 4 pages +
 4 collections + hero + palette + KB + ...]

Apply this 13-step launch? [y/N] y

  a. policies        -> 5/5 applied
  b. pages           -> 4/4 applied
  c. collections     -> 4 created
  d. theme palette   -> applied
  e. homepage hero   -> applied
  f. announcement    -> applied
  g. support KB      -> applied
  h. email templates -> applied
  i. segments        -> 9 created
  j. structured data -> applied
  k. blog starter    -> 3 articles published

  audit completion   -> 100%
  ready to launch    -> yes
```

### `/shopai-audit`

Read-only launch-readiness check. Cron-friendly.

```
> /shopai-audit

Launch readiness -- store: deguar.myshopify.com

completion: 88%
ready to launch: no

  legal_policies   | OK    | 5/5 present
  standard_pages   | OK    | 4/4 present
  active_discounts | OK    | 1 code (WELCOME15)
  collections      | OK    | 4 collections
  design_tokens    | OK    | theme tokens present
  brand_assets     | FAIL  | missing: favicon
  product_descs    | OK    | 12/12 enriched
  product_seo      | OK    | 12/12 populated

Next: /shopai-recommend brand_uploader "Acme Beauty"
      to fill the gap.
```

## How it works under the hood

The plugin manifest (`plugin/plugin.json`) declares:

* **MCP server**: `shopai-mcp` -- the stdio MCP server
  that exposes 40+ tools. Claude Code starts this as a
  child process; tool calls round-trip via JSON-RPC.

* **Slash commands**: 4 markdown files in
  `plugin/commands/` that combine multiple MCP tool
  calls into a single operator command. Each command's
  YAML frontmatter declares which MCP tools it's
  allowed to call.

The MCP server itself is the existing
`core/mcp_server/server.py` -- no plugin-specific code.
The plugin layer is pure configuration + workflow
templates.

## Coexistence with Anthropic's Claude × Shopify connector

You can install BOTH plugins:

```bash
# Anthropic's read-oriented connector
claude mcp add shopify ...anthropic-connector...

# ShopAI's write/autonomous connector
claude mcp add shopai shopai-mcp
```

Anthropic's connector handles read questions
(search_products, get_order, list_customers). ShopAI
handles autonomous-write + launch
(recommend_full_launch_pack, apply_*,
audit_launch_readiness). One conversation, two MCP
servers cooperating.

```
> /shopai-niches
[lists niches via ShopAI]

> what's selling well this week?
[Anthropic's connector: search_orders + get_metrics]

> set up a homepage hero for that top category
[ShopAI: recommend_homepage_hero + apply_homepage_hero]
```

## Troubleshooting

**`claude mcp list` doesn't show `shopai`.**
Check: `which shopai-mcp` resolves. If not, re-run
`pip install -e ".[mcp]"`.

**Slash command not found.**
Check: `ls ~/.claude/commands/shopai-*.md`. If empty,
re-run the copy step. Restart Claude Code after copying.

**Tool returns `router_unavailable`.**
Shopify credentials aren't set. Re-add the MCP server
with `--env SHOPAI_SHOPIFY_URL=... --env SHOPAI_SHOPIFY_KEY=...`
or export the env vars in your shell.

**Tool returns `engine_unavailable: <module>`.**
The base PR for that module hasn't merged to main yet.
Check `docs/MERGE_READINESS.md` for the queue.

## Uninstall

```bash
claude mcp remove shopai
rm ~/.claude/commands/shopai-*.md
pip uninstall shopai
```
