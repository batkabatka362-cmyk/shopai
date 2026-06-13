# ShopAI Operator Quick Start

You have ShopAI's autonomous earning loop substrate complete (PR
#503, W963-115..178, 97 commits ahead of main). This guide walks
you from "code shipped" to "real revenue earning".

**Estimated time: 30-60 minutes** (most of it is API-key acquisition
from third-party dashboards; ShopAI commands run in seconds).

## 0. Pre-flight check

```powershell
shopai go-live
```

Expected output: `[OK ] VERDICT: ready_to_go_live` with a list of
warnings under "fix:". The warnings are NOT blockers (the verdict
is OK); they're the configuration gaps this guide closes.

## 1. Merge PR #503 to main

PR: https://github.com/batkabatka362-cmyk/shopai/pull/503
(97 commits ahead of main)

```bash
# CI must be green first. Once Tests (py3.11) + Tests (py3.12) pass:
gh pr merge 503 --squash --delete-branch
# or merge via GitHub web UI
```

After merge, switch your local clone to main:

```powershell
git fetch origin
git checkout main
git pull origin main
```

## 2. Configure required API keys

ShopAI reads credentials from `.env` in the repo root. Copy
`.env.example` as your starting point:

```powershell
cp .env.example .env
```

Then add the keys below. **Required for revenue activation**:

### Shopify (you have this)
Per-store, set inside `.env`:
```
SHOPAI_STORE_<SID>_SHOPIFY_URL=<store>.myshopify.com
SHOPAI_STORE_<SID>_SHOPIFY_API_KEY=shpat_xxx
```
Where `<SID>` is the store_id (e.g. `MAIN`, `FKCQ1I-0S`). Verify:
```powershell
shopai store list
shopai store verify <SID>
```

### Ad channels (PICK AT LEAST ONE for revenue)

Without an ad channel, ShopAI's ad_launcher / ad_creative_generator
emit plans only -- no real campaigns. Pick the highest-ROI starter
for your niche:

**Meta Ads (Facebook + Instagram) -- recommended starter**
```
META_ADS_ACCESS_TOKEN=<long-lived token from Meta Business Suite>
META_ADS_ACCOUNT_ID=<15-digit account ID>
```
Get keys: https://developers.facebook.com/ -> Create app ->
Marketing API -> long-lived token. ROAS-optimised by default;
warm-audience retargeting is the cheapest activation.

**Google Ads (search intent)**
```
GOOGLE_ADS_CLIENT_ID=<OAuth client>
GOOGLE_ADS_CLIENT_SECRET=<secret>
GOOGLE_ADS_CUSTOMER_ID=<10-digit ID>
GOOGLE_ADS_DEVELOPER_TOKEN=<dev token>
GOOGLE_ADS_REFRESH_TOKEN=<refresh from OAuth playground>
```
Get keys: https://console.cloud.google.com/ -> OAuth 2.0 +
https://ads.google.com/aw/apicenter -> Developer token.

### Email automation (optional but high-ROI)

**Klaviyo (recommended)** -- needed for re-engagement + cart
recovery:
```
KLAVIYO_API_KEY=pk_xxx
KLAVIYO_WEBHOOK_SECRET=<HMAC secret you set on Klaviyo's webhook
                       subscription page>
```

Or Brevo (you already have BREVO_API_KEY in `.env`).

### Vendor webhook secrets (optional, surface real-time signals)

Each vendor's HMAC secret enables ShopAI to consume their webhook
events. Set only the ones you actively use:

```
GORGIAS_API_KEY=<api key>     GORGIAS_USERNAME=<email>
GORGIAS_SUBDOMAIN=<acme>      (helpdesk tickets)

AFTERSHIP_API_KEY=<api key>   AFTERSHIP_WEBHOOK_SECRET=<hmac>
                              (order tracking)

STRIPE_WEBHOOK_SECRET=<wh secret>  (chargebacks + disputes)
PAYPAL_WEBHOOK_ID=<webhook id>     (alt-gateway payments)
KLARNA_WEBHOOK_SECRET=<secret>     (buy-now-pay-later events)
LOOX_WEBHOOK_SECRET=<secret>       (photo review feedback)
```

### Notify webhook (recommended)

Slack / Discord webhook URL so cycle alerts (auto-pause, revenue
regression, stale cycle, spend cap breach) reach you:

```
SHOPAI_NOTIFY_WEBHOOK_URL=https://hooks.slack.com/services/...
```

Verify post-config:
```powershell
shopai notify check --dry-run
```

## 3. Tag store niches

Untagged stores fall back to generic cluster prioritisation. Tag
each store with its niche (`beauty` / `fashion` / `home` / `tech`
/ `food`):

```powershell
shopai niche --by-store           # see current state
shopai niche --set <SID> beauty   # tag one store
```

## 4. Install cron (autonomous loop activation)

The cycle won't fire automatically until cron is installed. Emit
the platform-appropriate command:

```powershell
shopai cycle schedule
```

On **Windows**: copy the printed `schtasks` line into PowerShell
(run as Administrator).

On **Linux / macOS**: append the printed cron line to your crontab
(`crontab -e`).

Also schedule the notify-check companion (every 15 minutes):

```powershell
shopai notify check --schedule
```

## 5. Enable autonomous launches (optional but recommended)

By default ShopAI proposes products + requires operator approval
per product. To activate single-step launches (operator approves
once; ShopAI creates + prices + images + publishes in one chain):

```
SHOPAI_PRODUCT_SOURCER_AUTO_PUBLISH=1
SHOPAI_CYCLE_RUN_CONFIRM=1
```

To enable autopause bridges (auto-disarm spend domains when caps
breach):
```
SHOPAI_AUTO_PAUSE_ON_OVERSPEND=1
SHOPAI_SPEND_CAP_DAILY_USD=50
SHOPAI_AUTO_QUARANTINE_FROM_ALERTS=1
```

## 6. First autonomous cycle (sanity check)

```powershell
SHOPAI_CYCLE_RUN_CONFIRM=1 shopai cycle run --yes
```

Expected: 20+ engines invoked, 20+ ok, 0 err, several proposals
land in the approval queue. Inspect:

```powershell
shopai approvals digest                  # top-10 priority + AI pre-vet
shopai approvals batch-review --auto-approve-ok --yes
                                          # bulk-approve consensus
shopai store fleet                       # storefront state
```

## 7. Daily operator routine (5 minutes)

```powershell
shopai empire --summarize                # one-paragraph empire status
shopai approvals digest                  # what needs review
shopai approvals batch-review --auto-approve-ok --yes
                                          # auto-handle consensus
shopai engine alerts                     # degraded engines?
shopai cycle status                      # last cycle health
```

If anything degrades:
```powershell
shopai autonomy-doctor                   # 4-axis health rollup
shopai engine guardrail                  # v2 guardrail state
shopai approvals quarantine --revenue-streaks  # auto-quarantined?
```

## 8. Empire scale (when you're ready)

```powershell
shopai store add <SID> <url> --api-key shpat_xxx --niche <niche>
shopai onboard <SID> <url> --api-key shpat_xxx --niche <niche>
                                          # 9-stage wizard
shopai transfer scan                     # cross-store opportunities
shopai engine ranking                    # fleet-wide leaderboard
```

## Where to drill when things go wrong

| Symptom | Drill |
|---|---|
| Cycle errored | `shopai cycle history --store <SID>` |
| Engine alert | `shopai engine alerts` |
| Revenue regression | `shopai cycle attribution-delta` |
| Spend cap breached | `shopai approvals quarantine --spend-status` |
| Auto-pause fired | `shopai autonomy-disarm-history` |
| Product create silent fail | check `result['price_set'] / images_attached / published` |

## Substrate reference

- `CLAUDE.md` -- architectural reference (W963-115..178 ramp documented end of file)
- `docs/EMPIRE_AGI_WORKFLOW.md` -- empire-AGI loop overview
- `shopai capabilities list` -- machine-readable substrate catalog
