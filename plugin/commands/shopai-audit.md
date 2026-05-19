---
description: Audit a Shopify store's launch readiness
allowed-tools: ["mcp__shopai__audit_launch_readiness"]
---

# /shopai-audit [store_id]

Run the read-only launch-readiness audit on the connected
Shopify store.

## Arguments

`[store_id]` optional. Defaults to the active store from
the ShopAI configuration.

## Steps

1. Call `audit_launch_readiness(store_id=$store_id)`.
2. Format the response as a human-readable summary:

   ```
   Launch readiness -- store: $store_id

   completion: NN%
   ready to launch: yes/no

   Check        | Status | Detail
   -------------|--------|---------------------------
   legal_policies | OK    | 5/5 policies present
   standard_pages | FAIL  | missing: faq
   active_discounts | OK  | 1 code (WELCOME15)
   curated_collections | OK | 4 collections
   design_tokens   | OK   | theme tokens present
   brand_assets    | FAIL | missing: favicon
   product_descriptions | OK | 12/12 enriched
   product_seo     | OK   | 12/12 populated
   ```

3. If `ready_to_launch=False`, list the specific missing
   items + suggested next commands (e.g. "run
   `/shopai-recommend brand` then apply").

4. If `ready_to_launch=True`, congratulate + suggest
   monitoring next steps (cron the audit, watch the
   completion_pct over time).

## Notes

This command is read-only. It never writes to Shopify.
Safe to run on production.
