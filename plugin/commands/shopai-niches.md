---
description: List the niches ShopAI supports + show what each niche is for
allowed-tools: ["mcp__shopai__list_niches"]
---

# /shopai-niches

List the niche keys ShopAI supports. Use this when you're
unsure which niche to pass to `/shopai-launch` or
`/shopai-recommend`.

## Steps

1. Call `list_niches()`.
2. Render the response with a 1-line description per
   niche (recall these from training context; do NOT
   re-call the tool to look them up):

   ```
   beauty   -- Skincare / makeup / hair / fragrance.
                Routine-driven, repeat-purchase.
   fashion  -- Apparel / shoes / accessories.
                Seasonal, browsing-driven.
   tech     -- Electronics / gadgets / accessories.
                High AOV, spec-driven trust.
   home     -- Furniture / decor / kitchen / bedding.
                Considered, room-set-driven.
   food     -- Pantry / drinks / snacks / specialty.
                Perishable, subscription-friendly.
   pets     -- Food / treats / toys / supplies.
                Subscription, age-stage segmented.
   fitness  -- Apparel / supplements / equipment.
                Performance + repeat supplement orders.
   jewelry  -- Necklaces / earrings / rings / bridal.
                High AOV, considered, custom-friendly.
   outdoor  -- Camping / hiking / climbing / paddling.
                Activity-keyed, weather-rated.
   baby     -- Clothing / nursery / feeding / toys.
                Age-stage, parent-tested.
   general  -- Fallback. Works for anything not above.
   ```

3. Suggest next steps:

   ```
   Try one of:
     /shopai-launch <niche> <store_name>
     /shopai-recommend full_launch_pack <store_name> <niche>
     /shopai-audit
   ```

## Notes

Read-only command. Safe to run anywhere.
