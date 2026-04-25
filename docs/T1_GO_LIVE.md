# T1 Go-Live Checklist

**Goal:** Development store шатнаас 7-хоногийн live operation руу шилжих.

**Branch:** `claude/update-shop-ai-docs-dVyQc`
**Дүрэм:** §4b.G paranoid mode — дуудлага бүрийг dry-run-аар урьдчилан харна.

---

## 0. Урьдчилсан шалгалт (30 мин)

### 0.1 Shopify store

Нэг дэвелопмент store байх ёстой:

```bash
# Browser-ээр: partners.shopify.com → Stores → Add store
# → Development store → "Build for the Shopify App Store" → Create
```

Store-оос эдгээрийг авах:
- `mystore.myshopify.com` (domain)
- Admin → Apps → Develop apps → Create an app → Configure scopes → Install → Reveal Admin API token → `shpat_...`

Шаардлагатай scope:
```
read_products, write_products, read_orders, read_customers,
write_customers, write_script_tags, write_content, write_themes,
write_discounts, write_price_rules, write_fulfillments
```

### 0.2 Meta Ads sandbox

```bash
# Browser-ээр: developers.facebook.com → My Apps → Create App
# → "Other" → "Business" → Create
# Sandbox ad account + Pixel ID get from Meta Ads Manager
```

Авах:
- `META_ACCESS_TOKEN` (long-lived)
- `META_AD_ACCOUNT_ID` (act_...)
- `META_PIXEL_ID` (тоотой)

### 0.3 Public webhook URL

ShopAI-ийн webhook receiver нь https URL шаарддаг. Free options:
- ngrok: `ngrok http 8080` → `https://abc123.ngrok-free.app`
- Cloudflare Tunnel: `cloudflared tunnel run shopai`
- Fly.io deploy

---

## 1. .env тохируулах

`.env.example`-оос `.env` хуулна:

```bash
cp .env.example .env
```

Заавал бөглөнө:

```bash
# Shopify
SHOPAI_SHOPIFY_URL=mystore.myshopify.com
SHOPAI_SHOPIFY_KEY=shpat_XXXXXXXXXXXXXX
# (or use OAuth: SHOPAI_SHOPIFY_CLIENT_ID + SHOPAI_SHOPIFY_CLIENT_SECRET)

# Webhooks (T1 prereq — store builder Phase 2d subscribes via this)
SHOPAI_WEBHOOK_CALLBACK_URL=https://abc123.ngrok-free.app/api/webhook/shopify
SHOPAI_WEBHOOK_SECRET=some_random_32_char_string

# Meta Ads
META_ACCESS_TOKEN=EAAxxxxxxxxxxxx
META_AD_ACCOUNT_ID=act_1234567890
META_PIXEL_ID=1234567890

# LLM chain (3-agent arch from CLAUDE.md §5)
GROQ_API_KEY=gsk_xxxxxxxxxxxxxx       # Model 1 (automation)
GOOGLE_API_KEY=AIzaxxxxxxxxxxxxxx     # Model 2 (data/memory)
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxx    # Model 3 (research)

# Keep OFF until validation done — §4b.G paranoid mode
SHOPAI_ENABLE_LIVE_EXECUTION=0
```

Шалгах:

```bash
PYTHONPATH=. python cli.py config check
# → Every required env var: present ✓ or missing ✗
```

Амжилттай check болмогц доош.

---

## 2. Тест ногоон

```bash
PYTHONPATH=. pytest tests/test_order_replay.py \
    tests/test_replay_synthesize.py \
    tests/test_rule_quality.py \
    tests/test_live_execution_gate.py \
    tests/test_live_health.py \
    tests/test_store_configurator.py -q
```

Expect: бүх тест ногоон. Улаан бол дараагийн алхам хийхгүй.

---

## 3. Doctor probe

Store + Meta credentials амьд уу шалгана:

```bash
PYTHONPATH=. python cli.py doctor
```

Expect:

```
Shopify  ready    latency=XXX ms   scope=read_products,...
Meta     ready    latency=XXX ms   token valid
fal      warn     key not set (optional for launch)
vault    ready    path exists
```

Fail бол credentials дахин шалгах.

---

## 4. Store configure (dry-run эхэндээ)

```bash
PYTHONPATH=. python cli.py store configure teststore --dry-run --niche beauty
```

Expect output:

```
Status: planned
Niche:  beauty

Feature results:
  collections     created=5, existing=0
  discounts       created=6 (WELCOME15, COMEBACK10, ...)
  shipping        current=0, recommended=3, 3 missing
  content         pages_created=1
  ...
  pages           created=3, skipped=0, errors=0
  policies        updated=4, errors=0
  menus           updated=2, errors=0
  brand           written=2 (brand, seo_defaults), errors=0
  redirects       created=7, skipped=0, errors=0
  blog            created=welcome-to-teststore, errors=0
  webhooks        skipped (SHOPAI_WEBHOOK_CALLBACK_URL not set…)

Planned writes (~60): …
```

Plan-ийг review хийгээд OK бол live run:

```bash
PYTHONPATH=. python cli.py store configure teststore --niche beauty
```

Store admin-д орж үр дүн үзэхэд:
- Collections shopAI-ийн нэмсэн 5
- Pages: About / Contact / FAQ
- Policies: Privacy / Refund / ToS / Shipping
- Menus: main-menu + footer updated
- 7 redirects (/shop, /store, etc.)
- 1 blog article
- Brand + SEO metafields

Webhooks skipped. Дараагийн алхам дээр заавал тохируулах.

---

## 5. Webhooks асаах

Public URL-аа ngrok эсвэл өөр tunnel-ээр эхлүүлнэ:

```bash
ngrok http 8080 &
# → noted https URL: https://abc123.ngrok-free.app
```

`.env`-д URL-аа бичих:

```bash
SHOPAI_WEBHOOK_CALLBACK_URL=https://abc123.ngrok-free.app/api/webhook/shopify
```

Store configure дахин — webhooks feature-тэй:

```bash
PYTHONPATH=. python cli.py store configure teststore --only webhooks
```

Expect:

```
webhooks   subscribed=5, existing=0, errors=0
```

Browser-оор Shopify admin → Settings → Notifications → Webhooks шалгахад 5 subscription байна.

---

## 6. Learning loop validation

**Real traffic-гүйгээр** webhook pipeline бодитоор туршина:

```bash
PYTHONPATH=. python cli.py replay-orders --synthesize 100 --seed 42
```

Expect:

```
Replayed 100 orders (100 ok, 0 failed, 0 skipped) in X.Xs
  revenue replayed:           $8,399.39
  deliberations back-filled:  N
```

Learning ledger populated эсэхийг шалгана:

```bash
PYTHONPATH=. python cli.py rule-quality
# → total_rules ≥ 1, PatternMiner rule proposed
```

Engine-level feedback:

```bash
# MCP tool via Claude Desktop эсвэл python:
PYTHONPATH=. python -c "
from mcp_server.tools import _engine_feedback_stats_handler
import json
print(json.dumps(_engine_feedback_stats_handler({}), indent=2))
"
# → order_webhook: 100 runs, completed=100, trend=stable
```

---

## 7. Live daemon ажиллуулах

**БҮХ дээр шалгасны дараа** л `SHOPAI_ENABLE_LIVE_EXECUTION=1`:

```bash
export SHOPAI_ENABLE_LIVE_EXECUTION=1
PYTHONPATH=. python scripts/run_daemon.py &
```

Эсвэл stack-аар (daemon + API + dashboard):

```bash
SHOPAI_ENABLE_LIVE_EXECUTION=1 python scripts/start_shopai.py &
```

---

## 8. Monitoring (1 цаг тутам)

```bash
PYTHONPATH=. python cli.py live-health
# → verdict: healthy / degrading / needs_attention
```

Цагийн ажиллагаа healthy үлдэх ёстой. Needs_attention бол:

```bash
PYTHONPATH=. python cli.py doctor
PYTHONPATH=. python cli.py cycles --limit 20
```

---

## 9. 7-хоногийн Т1 шалгуур

**Өдөр бүр:**

```bash
# Cycles green үргэлжилж байгаа эсэх
PYTHONPATH=. python cli.py cycles --limit 50 | grep -c '"error": ""'

# Live health бусад (degrading болж буй уу)
PYTHONPATH=. python cli.py live-health

# Rule quality хөдөлж эхэлсэн үү
PYTHONPATH=. python cli.py rule-quality
```

**7 хоногийн эцэст Т1 шалгуур хангагдана:**

1. `data/autopilot_loop.log` нь `mode:live` entry-тэй ≥ 100 cycle
2. `live-health verdict=healthy` нь 80%-аас дээш cycle-д
3. ≥ 1 real order webhook back-filled a Deliberation observation
4. Owner touch < 2/week (manual intervention-г логлох)

Хангагдмагц → T1 Done → T2 руу шилжинэ.

---

## 10. Emergency kill switch

Ямар нэг буруу явбал:

```bash
# MCP: emergency_halt (via Claude Desktop)
# Эсвэл:
PYTHONPATH=. python -c "
from core.system.crisis_state import engage_manual_halt
engage_manual_halt('owner requested T1 rollback')
"
```

Live writes зогсоно. Manual halt-ыг clear хийхдээ `emergency_resume`.

---

## 11. §4d cross-check

Live-ээ асаахын өмнө дараах **зургаа**ийг хариулж шалгах:

1. ☐ Tests бүгд ногоон уу? (Section 2)
2. ☐ Doctor бүгд ready уу? (Section 3)
3. ☐ Dry-run plan review хийгдсэн үү? (Section 4)
4. ☐ Store-д configure амжилттай явсан уу? (Section 4 live)
5. ☐ Webhooks subscribed уу? (Section 5)
6. ☐ Replay-аар learning loop fires хийгдсэн үү? (Section 6)

Бүгд ☑ → `SHOPAI_ENABLE_LIVE_EXECUTION=1`. Нэг ч ☐ → fix болгож дараа асаана.

**Mission alignment (§4c.K):** Т0→Т1 bridge. Dollar distance 0 (бид одоо хараад яг live-д орох цэг дээр).
