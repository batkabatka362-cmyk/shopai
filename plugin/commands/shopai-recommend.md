---
description: Get niche-aware recommendations for a specific ShopAI module
allowed-tools: ["mcp__shopai__list_niches", "mcp__shopai__recommend_starter_collections", "mcp__shopai__recommend_pages", "mcp__shopai__recommend_policies", "mcp__shopai__recommend_homepage_hero", "mcp__shopai__recommend_theme_palette", "mcp__shopai__recommend_support_kb", "mcp__shopai__recommend_email_templates", "mcp__shopai__recommend_blog_starter", "mcp__shopai__recommend_coupon_playbook", "mcp__shopai__recommend_structured_data", "mcp__shopai__recommend_customer_segments", "mcp__shopai__recommend_loyalty_tiers", "mcp__shopai__recommend_announcement_bar", "mcp__shopai__recommend_metaobject_definitions", "mcp__shopai__recommend_review_email", "mcp__shopai__recommend_winback_email", "mcp__shopai__recommend_homepage_sections", "mcp__shopai__recommend_newsletter_popup", "mcp__shopai__recommend_cross_sell_rules", "mcp__shopai__recommend_welcome_discount", "mcp__shopai__recommend_tag_library", "mcp__shopai__recommend_smart_collections", "mcp__shopai__recommend_full_launch_pack"]
---

# /shopai-recommend <module> <store_name> [niche]

Get a niche-aware recommendation from a specific ShopAI
module WITHOUT applying it to the store.

## Arguments

`<module>` is required. One of:

  Page content:
    pages, policies, homepage_hero, theme_palette,
    support_kb, email_templates, blog_starter,
    announcement_bar, homepage_sections,
    newsletter_popup, review_email, winback_email,
    structured_data

  Catalog:
    starter_collections, smart_collections,
    tag_library, metaobject_definitions, cross_sell_rules

  Customer + commerce:
    customer_segments, loyalty_tiers,
    coupon_playbook, welcome_discount

  Composite:
    full_launch_pack -> bundles everything

`<store_name>` is required for all content tools
(blog_starter needs a store name in author bylines, etc.).
Some niche-only tools (theme_palette, tag_library,
smart_collections) ignore it.

`[niche]` optional. Defaults to `general`.

## Steps

1. Validate `<module>` is on the supported list. If not,
   suggest the closest match.
2. Call `recommend_<module>(store_name=..., niche=...)`.
3. Render the structured spec in a readable format:

   * For page-style modules (homepage_hero / support_kb /
     etc.) -- show the key text fields + section count.
   * For lists (collections / segments / blog posts) --
     show titles + first sentence of each.
   * For numeric specs (loyalty_tiers / inventory) --
     show the threshold table.

4. End with: "Apply this with `/shopai-recommend` `apply_<module>`."

## Notes

This command is read-only. No Shopify writes happen.
Useful for previewing what ShopAI would set up BEFORE
the operator commits.
