# Competitor Intelligence — Operator Guide

Study the public surface of any Shopify store — catalog,
pricing, installed apps, theme, announcement bars — and track
how it changes week-over-week. Feeds niche + pricing + ad
decisions for Deguar's **Calm & Cozy** positioning
(`docs/NICHE_STRATEGY.md`).

No auth. No Shopify token. No account needed on the target
store. Everything scraped is already public to Google.

---

## 1. Quick start

```bash
# One-shot scrape + LLM strategic take
shopai competitor-intel loftie.com

# Multiple stores in one pass
shopai competitor-intel loftie.com hatch.co bearaby.com

# Raw scrape only (no LLM — zero cost)
shopai competitor-intel loftie.com --no-llm

# Machine-readable
shopai competitor-intel loftie.com --json > loftie-snapshot.json
```

Every run **auto-persists** to
`data/competitor_intel/<store-slug>.jsonl` (one line per
scrape). Repeat runs surface a **diff** against the previous
scrape: new SKUs, median-price move, newly-installed apps.

Disable persistence with `--no-persist` (don't do this on the
first weekly run — you lose the baseline).

---

## 2. Target watchlist for Calm & Cozy

Brands sharing the wellness / cozy-ambient / aromatherapy
positioning Deguar is competing with:

| Brand | URL | Why watch |
|---|---|---|
| **Loftie** | `byloftie.com` | Direct sleep-focused ambient + lamp/sunrise-alarm overlap |
| **Hatch** | `hatch.co` | Premium sunrise-alarm + sleep, reference pricing |
| **Bearaby** | `bearaby.com` | Weighted blanket wellness — ad copy patterns transfer |
| **Brooklinen Home** | `brooklinen.com` | Bedroom aesthetic leader, watch collection structure |
| **Bloomscape** | `bloomscape.com` | Plant + ambient crossover, apps they install |
| **Vitruvi** | `vitruvi.com` | Direct aromatherapy diffuser competitor |
| **Pura Scents** | `pura.com` | Aromatherapy DTC, pricing + app stack |
| **The Cozy Shop** | `thecozyshop.co` | Direct aesthetic peer |
| **Magic Spoon** | `magicspoon.com` | CPG DTC — watch for Klaviyo / Loox / ReCharge patterns |
| **Warby Parker** | `warbyparker.com` | Premium brand reference |

Put these in a shell alias for weekly runs:

```bash
alias shopai-intel-weekly='shopai competitor-intel \
    byloftie.com hatch.co bearaby.com vitruvi.com pura.com \
    thecozyshop.co'
```

---

## 3. Reading the output

Each store's section shows:

```
═══ loftie.com ═══
  products: 14
  prices:   $99.00–$249.00 (median $149.00)
  currencies: USD
  top types:  Sleep, Lamp, Accessory
  top tags:   sleep, wellness, gift
  newest:
    - Loftie Clock 2
    - Loftie Lamp Pro
  theme:     Shopify Impulse 8.0
  apps:      Klaviyo (email/SMS), Meta Pixel, Loox (photo reviews)
  hero H1:   Sleep Tech That Doesn't Suck
  banner:    Free shipping over $100
  collections: 7
  diff:      products +2; median $+10.00; new apps: TikTok Pixel

  ── strategic take ──
  Loftie leads on sleep-tech premium positioning...
```

**What each field signals:**

| Field | What it tells you |
|---|---|
| `products` count | Catalog size — growing = aggressive launch cadence |
| `median` price | Their price anchor — ours should be 30-60% below if we want to win on price |
| `top tags` | What SEO/ad keywords they emphasise |
| `newest` | Which category they just launched into (signal for trend chasing) |
| `theme` | Impulse / Dawn / custom — theme budget correlates with ad spend |
| `apps` | Their marketing stack — see app-signal table below |

### App signal cheat sheet

| App detected | What it means |
|---|---|
| **Klaviyo** | Email-first brand — expect ≥25% revenue from email |
| **Meta Pixel** | Running Meta ads (always true for DTC scale) |
| **TikTok Pixel** | Running TikTok ads — if just appeared, they're scaling TikTok |
| **Loox / Judge.me** | Photo reviews — social proof priority |
| **Yotpo** | Reviews + loyalty combined — repeat-buyer focus |
| **Recharge** | Subscription — recurring revenue model |
| **Smile.io** | Loyalty programme — retention focus |
| **Gorgias** | Support ticketing — mature operation |
| **Shogun / GemPages** | Custom landing pages — higher CAC tolerance |
| **ReConvert / AfterSell** | Post-purchase upsell — AOV obsession |

### Diff interpretation

```
  diff:      products +2; median $+10.00; new apps: TikTok Pixel
```

Translation:
- **+2 products** — they launched 2 new SKUs since your last
  scrape. Check `--json` output for the handles.
- **median $+10** — sitewide price hike. Either margin move
  or cost-push (supplier prices rose). Don't follow blindly —
  check if your supplier costs moved too.
- **new apps: TikTok Pixel** — they just started TikTok ads.
  Expect them to push TikTok-native creatives. Watch for 4-6
  weeks then see which of their products is being pushed
  hardest (that's their TikTok winner).

Baseline message on first scrape:

```
  diff:      (first scrape — no baseline)
```

---

## 4. Weekly cadence (recommended)

```
Monday  08:00  — run the alias, eyeball the diffs
                 * Anything with "new apps" → investigate
                 * Any "+N products" > 3 → check what they launched
                 * Any median price move > 5% → assess margin impact
```

30-scrape cold-scan budget: **≈$0.02 total** (LLM synthesis
at ~$0.001/store × 30). Way under the $0.10/cycle cap.

Without `--no-llm`, the scrape writes a 200-word strategic
take per store. If you're just checking for changes, pass
`--no-llm` to skip the synthesis and save a few seconds.

---

## 5. MCP access (Claude Desktop / Code)

Same surface exposed as MCP tools:

| Tool | Purpose |
|---|---|
| `analyze_competitor` | Scrape one or more stores + diff. Auto-persists. |
| `competitor_history` | Return the last N scrapes for one store + latest diff. No re-scrape. |

Example prompts from Claude Desktop:

- *"Scrape loftie.com + hatch.co and tell me what they're
  doing differently from Deguar."*
- *"What changed on byloftie.com since my last scrape?"*
- *"Show me the last 5 scrapes of vitruvi.com — are they
  launching new SKUs?"*

Both tools are **read-flagged** in the MCP registry. They
write only to `data/competitor_intel/` — never to any
competitor's store, never use our Shopify token.

---

## 6. Storage layout

```
data/competitor_intel/
  byloftie-com.jsonl       # 1 JSON line per scrape
  hatch-co.jsonl
  vitruvi-com.jsonl
  ...
```

`.gitignore` already covers `/data/`, so history stays local.
Rotate or back up with a cron job if you want to keep a long
archive:

```bash
# Daily tarball
tar czf ~/backups/intel-$(date +%F).tgz data/competitor_intel/
```

---

## 7. What this is NOT

- **Not** a competitor ad spy. Meta Ads Library integration
  lives elsewhere (search ads_spy / campaigns), not here.
- **Not** a price scraper that triggers auto-match. Pricing
  decisions flow through `core/brain/revenue_strategy.py` —
  this tool *informs*, doesn't *decide*.
- **Not** a ToS violation risk. All scrapes hit endpoints
  Shopify documents as public and that Googlebot already
  fetches.

---

## 8. Known limits

- **JavaScript-rendered banners** won't appear. Only static
  HTML. Fine for Shopify default + Dawn/Impulse themes (which
  render most content server-side).
- **Password-protected dev stores** return 0 products. Report
  will show `(catalog empty or private)`.
- **Stores larger than 1250 SKUs** get truncated at 5 pages ×
  250. Covers ~99% of DTC brands.
- **Pure LLM synthesis** is optional and best-effort. If
  Groq/Gemini rate-limit, the raw scrape still returns
  cleanly — insights field just stays empty.

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `WARN: llm gateway unavailable` | `GROQ_API_KEY` or `GEMINI_API_KEY` missing in `.env`. Run with `--no-llm` while you set that up. |
| `(catalog empty or private)` | Store is password-protected or not Shopify. Verify in browser. |
| `errors: homepage: HTTP 403` | Some stores throttle non-browser user-agents. Retry or skip. |
| Diff shows nothing even after changes | Clock skew — two scrapes within the same second. Add `sleep 5` between runs. |

Source: `agents/competitor_intel/agent.py` + tests in
`tests/test_competitor_intel.py` + `tests/test_mcp_competitor_intel.py`.
