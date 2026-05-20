---
description: Run the full ShopAI autonomous launch on a Shopify store
allowed-tools: ["mcp__shopai__list_niches", "mcp__shopai__recommend_full_launch_pack", "mcp__shopai__apply_policies", "mcp__shopai__apply_pages", "mcp__shopai__apply_starter_collections", "mcp__shopai__apply_homepage_hero", "mcp__shopai__apply_theme_palette", "mcp__shopai__apply_announcement_bar", "mcp__shopai__apply_email_templates", "mcp__shopai__apply_customer_segments", "mcp__shopai__apply_support_kb", "mcp__shopai__apply_structured_data", "mcp__shopai__apply_blog_starter", "mcp__shopai__audit_launch_readiness"]
---

# /shopai-launch <niche> [store_name] [region]

Run the full ShopAI autonomous launch on the connected
Shopify store.

## Arguments

`<niche>` is required. One of: beauty / fashion / tech /
home / food / pets / fitness / jewelry / outdoor / baby /
general. Use `/shopai-niches` if unsure.

`[store_name]` optional. Defaults to the Shopify store's
existing display name.

`[region]` optional. Defaults to `us`.

## Steps

1. Confirm the niche is valid via `list_niches`.
2. Call `recommend_full_launch_pack(store_name=$store_name, niche=$niche, region=$region)`.
3. Show the operator a structured summary of what will
   be applied (collection count, page titles, policy
   types, etc.) and confirm.
4. On confirm, apply in this order (so dependencies
   line up correctly):

   a. `apply_policies` (legal bedrock)
   b. `apply_pages` (storefront pages)
   c. `apply_starter_collections` (catalog scaffolding)
   d. `apply_theme_palette` (brand visuals)
   e. `apply_homepage_hero` (above-the-fold)
   f. `apply_announcement_bar`
   g. `apply_support_kb`
   h. `apply_email_templates`
   i. `apply_customer_segments`
   j. `apply_structured_data` (SEO)
   k. `apply_blog_starter`

5. After every step, surface the result's `applied_count`
   + any per-step errors. Skip the rest only if a critical
   step (policies / pages) fails.
6. Finish with `audit_launch_readiness` -- summarise the
   completion_pct + remaining gaps.

## Output format

Final summary as a single message:

```
Autonomous launch -- $store_name ($niche)

 a. policies        -> applied X / 5
 b. pages           -> applied X / 4
 c. collections     -> applied X
 d. theme palette   -> applied: yes
 e. homepage hero   -> applied: yes
 ...
 audit completion   -> X%
 ready to launch    -> yes/no
 next steps         -> [list of gaps]
```

Never silently skip a failure; surface every error to
the operator.
