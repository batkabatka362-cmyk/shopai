# Deguar — Pre-T1 Launch Playbook

Single runbook that takes the Deguar store from **"configured but
can't earn"** to **"ready for Meta Ads launch"**. Run top-to-bottom
on your own machine. Every step has a success criterion and an
exit gate.

Total time: **60-90 min active work** + ~2 days for Shopify Payments
verification + ~1-2 hrs for image curation.

---

## Pre-flight

```bash
cd ~/path/to/shopai
git checkout claude/update-shop-ai-docs-dVyQc
git pull
pip install -r requirements.txt

# .env must have SHOPAI_SHOPIFY_URL + SHOPAI_SHOPIFY_KEY (already done)
PYTHONPATH=. python cli.py doctor
# Expect: ≥3 ok, shopify.credentials ✓
```

---

## Step 1 — Audit current state (5 min)

**Goal:** know what's actually live vs what the tracker thinks.

```bash
# 1a. Live store state — images, duplicates, status, pricing
PYTHONPATH=. python scripts/deguar_live_audit.py

# 1b. OAuth scopes — what's granted vs what ShopAI needs
PYTHONPATH=. python scripts/deguar_scope_audit.py
```

**Success:** two plain-text reports. Save the stdout to
`audit-$(date +%F).txt` for reference.

**Blockers surface here:**

| Symptom | Fix |
|---|---|
| `0 images` count > 0 | Step 3 below |
| Product count > 20 | Step 2 (duplicate cleanup) |
| `drafts = 0, active = 21` | Step 2 (re-draft off-niche) |
| `✗ write_price_rules` / `write_themes` / etc. missing | Step 4 |

---

## Step 2 — Clean up duplicates + re-verify drafts (10 min)

**Goal:** 20 products total, 14 active (11 Calm & Cozy hero + 3
neutral), 6 drafted.

Per the audit log, there are **2 Magnetic Phone products**:

  - `Magnetic Phone Mount for Car` — $12.99 — **KEEP** (has cost
    data)
  - `Car Accessories: Magnetic Phone Holder` — $24.99 (cost $0)
    — **DELETE**

Open Shopify Admin → Products → search "phone" → delete the second
one (1 click).

**Drafts (6 products):** verify these show "Draft" status in admin.
If any still say "Active", change them:
  - Magnetic Phone Mount for Car *(wait — this one stays active
    but as budget item? decide based on whether phone mounts fit
    "Calm & Cozy". Best to draft it too.)*
  - Desktop Wireless Charging Pad LED
  - Smart Water Bottle Temperature Display
  - Portable Neck Fan Bladeless
  - Smart LED Strip Lights RGB
  - Portable Mini Projector HD

**Success:** admin shows 14 active, 6 draft. Total 20. Re-run
`scripts/deguar_live_audit.py --only drafts` to confirm.

---

## Step 3 — Add 3-4 images per product (30-60 min)

**Goal:** every active product has ≥3 images — lifts CVR ~35%.

### 3a. Curate image URLs

Copy `docs/deguar_images_template.json` → `deguar_images.json`
and replace the unsplash placeholders with real product shots:

```bash
cp docs/deguar_images_template.json deguar_images.json
```

For each of the **11 hero products**, get 2-3 extra image URLs
from:

  * **AliExpress supplier page** — right-click gallery → copy
    image URL. 2-3 angle shots per product.
  * **Pexels / Unsplash** (free) — search "bedroom lamp",
    "aromatherapy spa", "cozy home" for lifestyle shots.
  * **Pinterest** — same search. Use "Copy link" on image.

Paste into `deguar_images.json`, matching each product *handle*
(not title). Get handles from Step 1's audit output.

### 3b. Pilot upload (1 product)

```bash
PYTHONPATH=. python scripts/deguar_bulk_images.py \
    --config deguar_images.json \
    --min-images 3 \
    --only galaxy-star-projector-night-light \
    --dry-run
```

Review the dry-run output. If the URLs look right, drop `--dry-run`:

```bash
PYTHONPATH=. python scripts/deguar_bulk_images.py \
    --config deguar_images.json \
    --min-images 3 \
    --only galaxy-star-projector-night-light
```

Check the product in admin. Images should appear within 30
seconds (Shopify downloads them server-side).

### 3c. Full sweep

```bash
PYTHONPATH=. python scripts/deguar_bulk_images.py \
    --config deguar_images.json \
    --min-images 3
```

**Success:** re-run `deguar_live_audit.py --only images`. Line
"0 images" + "1 image" should both be 0.

---

## Step 4 — Grant missing Shopify scopes (5 min)

**Goal:** all 18 required scopes granted so menus + discounts +
policies + theme writes no longer silently skip.

The scope audit from Step 1 lists missing scopes. If the list is
non-empty:

```
Shopify Admin → Settings → Apps and sales channels
→ Develop apps → [your ShopAI app]
→ Configuration → Admin API integration
→ "Edit" → tick the missing scopes → Save
→ "Install app" (or Reinstall) → confirm
→ Copy the new Admin API access token
→ Update SHOPAI_SHOPIFY_KEY in .env
```

```bash
# Verify
PYTHONPATH=. python scripts/deguar_scope_audit.py
# Expect: "✓ All required scopes granted — no action needed"
```

**Success:** script exit code 0.

---

## Step 5 — Activate Shopify Payments (10 min + 1-2 days)

**Goal:** checkout works. Without this, **zero orders will land** —
ads clicks hit a dead checkout.

```
Shopify Admin → Settings → Payments
→ "Activate Shopify Payments" → fill bank + tax info
→ submit
```

Mongolia is not in Shopify Payments' supported country list (as
of 2026). Fallbacks that *do* work for Mongolia:

  * **PayPal** — Settings → Payments → alternative providers
    → PayPal Express Checkout. 2-day setup.
  * **Stripe** via Atlas — requires US LLC. Slower path.
  * **Paddle** — merchant-of-record, handles tax for you. 1-2 day
    setup, ~5% fee.

Pick one. **This step blocks every dollar** — don't skip.

**Success:** in admin → Orders → "Create order" → test-buy yourself
with a real card. Order lands. Refund it. Checkout confirmed live.

---

## Step 6 — Connect supplier (15-30 min)

**Goal:** when an order lands, there's an actual path to fulfil it.

Two options, roughly equal:

### CJ Dropshipping (recommended for first run)

```
1. Sign up at cjdropshipping.com
2. API key → Personal Center → Settings → API Key
3. Add to .env:
   SHOPAI_CJ_API_KEY=...
   SHOPAI_CJ_EMAIL=...
4. Find each hero product on CJ (search by title or image).
5. Map Shopify product handle → CJ sourcing_id.
```

(A mapping CSV export helper isn't shipped yet — will add if you
want it.)

### AutoDS (alternative)

```
1. Sign up at autods.com ($27.90/mo for 200 SKU plan)
2. Connect Shopify store via OAuth
3. AutoDS auto-imports SKUs; you confirm supplier mapping in UI
```

**Success:** at least 3 hero products have a confirmed
supplier_sku you can manually trigger an order against.

---

## Step 7 — Competitor baseline scrape (10 min)

**Goal:** establish a Monday-morning reference for prices / SKUs /
app stacks you'll diff against weekly.

```bash
# All 10 Calm & Cozy watchlist brands in one run
PYTHONPATH=. python cli.py competitor-intel \
    byloftie.com hatch.co bearaby.com vitruvi.com pura.com \
    thecozyshop.co brooklinen.com bloomscape.com
```

Review the strategic takes. Note 2-3 things Deguar should copy
(app stack, pricing anchor, ad angle).

**Success:** `data/competitor_intel/*.jsonl` has ≥8 files, each
with one line.

---

## Step 8 — Verify readiness (2 min)

```bash
PYTHONPATH=. python cli.py ready-for-live
```

Expected output: `READY` or a tight list of remaining blockers.
If BLOCKED, read the "fix" lines — each is actionable.

**Success:** `READY` verdict.

---

## Step 9 — Pre-ads checklist

Before Meta Ads go live (which you're doing manually):

- [ ] Images: 3+ per product on all 11 hero products
- [ ] Checkout: tested with real card, refunded cleanly
- [ ] Supplier: mapped for ≥3 hero products
- [ ] Tracking: Meta Pixel installed (Settings → Customer events)
- [ ] Returns: refund policy published (Settings → Policies)
- [ ] Shipping: at least one shipping zone covering your target
      country (US? UK? MN?) with a real rate
- [ ] Store name: decide if it stays "Deguar" or rebrands to
      "Calm & Cozy"
- [ ] Legal pages live: About Us, FAQ (already done per tracker),
      Privacy, ToS, Refund Policy

All 8 ticked → safe to run a $20/day PAUSED → ACTIVE Meta ad.

---

## Rollback

Every script in this playbook is **read-plus-append**, not
read-plus-replace. Nothing deletes existing data. If something
goes wrong:

  * Image uploads too many → Shopify admin, Products, uncheck
    and delete per product. 1 min per product.
  * Wrong image uploaded → admin → Product → Images → delete.
  * Scope change feels wrong → reinstall app with previous scope
    set. Token rotates, update .env.

---

## Scripts reference

| Script | Purpose | When to run |
|---|---|---|
| `cli.py doctor` | Config health | Every session start |
| `scripts/deguar_live_audit.py` | Store state check | Before + after bulk ops |
| `scripts/deguar_scope_audit.py` | OAuth scope diff | When something silently doesn't write |
| `scripts/deguar_bulk_images.py` | URL-driven image upload | Once to fix CVR |
| `cli.py competitor-intel <stores>` | Scrape + diff competitors | Weekly Monday |
| `cli.py ready-for-live` | Pre-T1 go/no-go gate | Before switching live_execution on |

---

## What this playbook does NOT do

- **Does not launch Meta Ads** — owner handles ads manually per
  explicit preference
- **Does not write product descriptions** — owner handles content
  manually per explicit preference
- **Does not touch pricing** — Step 2 leaves prices as-is; pricing
  optimisation lives in `core/brain/revenue_strategy.py` and needs
  order data to learn from
- **Does not enable `SHOPAI_BRAIN_HOOKS=1`** — do this only after
  real orders start flowing (learning loop fires on actual outcome
  events, no point before)

Once 5+ real orders land, you can enable brain hooks, flip
`SHOPAI_ENABLE_LIVE_EXECUTION=1`, and start the autonomous cycle.
