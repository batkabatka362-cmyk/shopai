"""Free-text intent → engine routing.

Closes the AGI audit's #1 gap (Natural Language Intent Router).
Pre-fix the API required structured ``{"task_type": "<engine>",
"params": {...}}``; merchants who don't know engine names cannot
ask "increase my margins" and have the system pick
``discount_strategy`` or ``dynamic_pricing`` for them.

This module classifies free-form text into one of the registered
engine names. It is a *rule-based* matcher in this first cut — a
curated keyword / synonym index over the top engines, scored by
overlap with the tokenised input. An LLM fallback is intentionally
deferred to a follow-up PR so this lands without an Anthropic
SDK dependency or API key requirement.

Usage:

    from core.brain.intent_router import classify_intent

    result = classify_intent("Help me lower my product prices")
    # IntentResult(engine="dynamic_pricing", confidence=0.82,
    #              alternatives=[("discount_strategy", 0.41), ...],
    #              source="rules",
    #              explanation="matched 'lower' + 'price'")

The matcher is intentionally conservative: when nothing scores
above a floor, ``engine`` is ``None`` and the API surface tells
the caller to be more specific or pick from a list. Better to
admit "I don't know" than route to the wrong engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger

logger = get_logger("brain.intent_router")

# Confidence scale notes:
#   * Each engine scores in [0, 1] based on weighted keyword
#     overlap (specific multi-word phrases weight higher than
#     bare nouns).
#   * Above ``_HIGH_CONFIDENCE`` we surface ``confidence: high``
#     in the explanation and rank ``source: rules``.
#   * Below ``_NO_MATCH_FLOOR`` we return ``engine=None``.
_HIGH_CONFIDENCE = 0.65
_NO_MATCH_FLOOR = 0.18

_ALTERNATIVES_RETURNED = 3
_MAX_TEXT_LEN = 1000

# Curated (engine_name, [(weight, keywords)]) index.
#
# Each tuple is a phrase / keyword that signals the engine. Multi-
# word phrases get higher weight because they're less ambiguous
# than bare nouns. Mongolian terms live alongside English so a
# Mongolian-speaking merchant routes correctly without an explicit
# language switch.
#
# When two engines compete (e.g. "lower the price" matches both
# dynamic_pricing and discount_strategy), tie-breaking prefers
# the engine whose specific phrases matched, not the bare-noun
# overlap.
_INTENT_INDEX: dict[str, list[tuple[float, str]]] = {
    "dynamic_pricing": [
        (1.5, "raise price"), (1.5, "raise prices"),
        (1.5, "lower price"), (1.5, "lower prices"),
        (1.5, "increase price"), (1.5, "increase prices"),
        (1.5, "reduce price"), (1.5, "decrease price"),
        (1.5, "adjust price"), (1.5, "adjust pricing"),
        (1.5, "price strategy"), (1.5, "pricing strategy"),
        (1.5, "optimize price"), (1.5, "optimize pricing"),
        (1.2, "margin"), (1.2, "markup"), (1.2, "repricing"),
        (1.0, "price"), (1.0, "pricing"),
        # Mongolian
        (1.5, "үнэ нэмэх"), (1.5, "үнэ багасгах"),
        (1.2, "үнэ"), (1.2, "ашиг"), (1.2, "ашгийг"),
    ],
    "discount_strategy": [
        (1.5, "discount code"), (1.5, "promo code"),
        (1.5, "coupon code"), (1.5, "promotion"),
        (1.5, "create discount"), (1.5, "mint discount"),
        (1.5, "storewide sale"), (1.5, "flash sale"),
        (1.5, "percent off"), (1.2, "% off"),
        (1.2, "discount"), (1.2, "coupon"),
        (1.0, "sale"), (1.0, "promo"),
        # Mongolian
        (1.5, "хямдрал"), (1.5, "купон"),
        (1.2, "хямдр"), (1.2, "сэйл"),
    ],
    "loyalty": [
        (1.5, "loyalty program"), (1.5, "loyal customer"),
        (1.5, "vip reward"), (1.5, "tier reward"),
        (1.5, "reward customer"), (1.5, "thank loyal"),
        (1.2, "loyalty"), (1.2, "reward"), (1.2, "tier"),
        (1.0, "vip"),
        # Mongolian
        (1.5, "үнэнч хэрэглэгч"), (1.5, "шагнал өгөх"),
        (1.5, "урамшуулал"), (1.2, "шагнал"),
        (1.2, "үнэнч"),
    ],
    "affiliate": [
        (1.5, "affiliate commission"), (1.5, "pay commission"),
        (1.5, "partner payout"), (1.5, "affiliate program"),
        (1.5, "referral payout"), (1.2, "commission"),
        (1.2, "affiliate"), (1.2, "partner"), (1.0, "referral"),
        # Mongolian
        (1.5, "комисс олгох"), (1.5, "түнш төлөх"),
        (1.2, "комисс"), (1.2, "түнш"),
    ],
    "tag_management": [
        (1.5, "tag products"), (1.5, "auto tag"),
        (1.5, "product tag"), (1.5, "category tag"),
        (1.5, "organize products"), (1.2, "tagging"),
        (1.2, "tags"), (1.0, "tag"),
        # Mongolian
        (1.5, "бараа тэмдэглэх"), (1.5, "бараа ангилах"),
        (1.2, "тэмдэг"), (1.2, "ангилал"),
    ],
    "search_optimization": [
        (1.5, "seo title"), (1.5, "seo description"),
        (1.5, "search ranking"), (1.5, "seo optimize"),
        (1.5, "search optimize"), (1.5, "meta title"),
        (1.5, "meta description"), (1.2, "seo"),
        (1.2, "search rank"), (1.0, "search"),
        # Mongolian
        (1.5, "хайлт оновчлох"), (1.5, "хайлтанд гаргах"),
        (1.2, "хайлт"),
    ],
    "product_lifecycle": [
        (1.5, "archive product"), (1.5, "kill product"),
        (1.5, "retire product"), (1.5, "discontinue product"),
        (1.5, "declining product"), (1.5, "unpublish product"),
        (1.2, "lifecycle"), (1.2, "archive"),
        (1.0, "retire"), (1.0, "discontinue"),
        # Mongolian
        (1.5, "бараа архивлах"), (1.5, "зарагдахаа больсон"),
        (1.5, "буурсан бараа"), (1.2, "архив"),
    ],
    "content_generation": [
        (1.5, "product description"), (1.5, "generate description"),
        (1.5, "rewrite description"), (1.5, "content rewrite"),
        (1.5, "improve copy"), (1.5, "generate content"),
        (1.2, "description"), (1.2, "copywriting"),
        (1.0, "copy"), (1.0, "content"),
        # Mongolian
        (1.5, "бүтээгдэхүүний тайлбар"), (1.5, "тайлбар бичих"),
        (1.5, "агуулга бичих"), (1.2, "тайлбар"),
        (1.2, "агуулга"),
    ],
    "inventory": [
        (1.5, "stock level"), (1.5, "inventory level"),
        (1.5, "out of stock"), (1.5, "low stock"),
        (1.5, "restock"), (1.5, "inventory adjust"),
        (1.2, "inventory"), (1.2, "stock"), (1.0, "warehouse"),
        # Mongolian
        (1.5, "агуулах"), (1.2, "нөөц"),
    ],
    "cart_recovery": [
        (1.5, "abandoned cart"), (1.5, "cart abandonment"),
        (1.5, "recover cart"), (1.5, "cart recovery"),
        (1.2, "cart"), (1.0, "abandoned"),
        # Mongolian
        (1.5, "сагсаа орхисон"), (1.5, "сагс сэргээх"),
        (1.5, "орхисон сагс"), (1.2, "сагс"),
    ],
    "browse_recovery": [
        (1.5, "browse abandonment"), (1.5, "browse recovery"),
        (1.5, "browsed without buying"), (1.5, "viewed product"),
        (1.2, "browse"), (1.0, "viewer"),
        # Mongolian
        (1.5, "үзсэн бараа"), (1.5, "харсан хэрэглэгч"),
        (1.5, "худалдаагүй гарсан"), (1.2, "үзсэн"),
    ],
    "churn_prediction": [
        (1.5, "predict churn"), (1.5, "churn risk"),
        (1.5, "customer churn"), (1.5, "lapsing customer"),
        (1.2, "churn"), (1.2, "retention"),
        (1.0, "lapsing"), (1.0, "win back"),
        # Mongolian
        (1.5, "хэрэглэгч алдах"), (1.5, "хэрэглэгч буцаах"),
        (1.5, "буцаан татах"), (1.2, "алдах эрсдэл"),
    ],
    "cohort_analysis": [
        (1.5, "customer cohort"), (1.5, "cohort analysis"),
        (1.5, "ltv analysis"), (1.5, "lifetime value"),
        (1.2, "cohort"), (1.2, "ltv"), (1.0, "lifetime"),
        # Mongolian
        (1.5, "хэрэглэгчийн бүлэг"), (1.5, "насан туршийн үнэ"),
        (1.2, "бүлэглэл"),
    ],
    "bundle": [
        (1.5, "product bundle"), (1.5, "create bundle"),
        (1.5, "bundle deal"), (1.5, "bundle products"),
        (1.2, "bundle"), (1.0, "package"),
        # Mongolian
        (1.5, "багц үүсгэх"), (1.5, "хослуулсан багц"),
        (1.5, "бараа нийлүүлэх"), (1.2, "багц"),
    ],
    "upsell": [
        (1.5, "upsell offer"), (1.5, "cross sell"),
        (1.5, "cross-sell"), (1.5, "post purchase"),
        (1.5, "buy with"), (1.2, "upsell"),
        (1.0, "upgrade"),
        # Mongolian
        (1.5, "нэмэлт зарах"), (1.5, "хамт зарах"),
        (1.5, "дээшлүүлэх санал"), (1.2, "нэмэлт"),
    ],
    "competitor_analysis": [
        (1.5, "competitor analysis"), (1.5, "compare competitor"),
        (1.5, "competitor price"), (1.5, "monitor competitor"),
        (1.2, "competitor"), (1.2, "competition"),
        (1.0, "rival"),
        # Mongolian
        (1.5, "өрсөлдөгч судлах"), (1.5, "өрсөлдөгчийн үнэ"),
        (1.2, "өрсөлдөгч"),
    ],
    "ads_spy": [
        (1.5, "winning ad"), (1.5, "ad spy"),
        (1.5, "spy on ad"), (1.5, "competitor ad"),
        (1.5, "facebook ad"), (1.5, "tiktok ad"),
        (1.2, "ad creative"), (1.0, "ads"),
        # Mongolian
        (1.5, "шилдэг зар"), (1.5, "зар тагнах"),
        (1.5, "өрсөлдөгчийн зар"), (1.2, "зар"),
    ],
    "creative": [
        (1.5, "ad creative"), (1.5, "generate creative"),
        (1.5, "video script"), (1.5, "ad copy"),
        (1.5, "image generation"), (1.5, "creative asset"),
        (1.2, "creative"), (1.0, "asset"),
        # Mongolian
        (1.5, "зар бүтээх"), (1.5, "видео скрипт"),
        (1.5, "зар сурталчилгаа"), (1.2, "сурталчилгаа"),
    ],
    "roas_guardrails": [
        (1.5, "roas guardrail"), (1.5, "ad spend"),
        (1.5, "kill underperforming"), (1.5, "scale winning"),
        (1.5, "roas threshold"), (1.2, "roas"),
        (1.2, "guardrail"),
        # Mongolian
        (1.5, "зарын зардал"), (1.5, "ROAS хязгаар"),
        (1.5, "зарыг зогсоох"), (1.2, "хязгаар"),
    ],
    "fraud_detection": [
        (1.5, "fraud detection"), (1.5, "suspicious order"),
        (1.5, "chargeback risk"), (1.5, "risky order"),
        (1.2, "fraud"), (1.2, "chargeback"),
        (1.0, "suspicious"),
        # Mongolian
        (1.5, "луйврын эрсдэл"), (1.5, "сэжигтэй захиалга"),
        (1.5, "залилан илрүүлэх"), (1.2, "луйвар"),
        (1.2, "сэжигтэй"),
    ],
    "shipping": [
        (1.5, "shipping rate"), (1.5, "shipping cost"),
        (1.5, "shipping zone"), (1.5, "shipping label"),
        (1.2, "shipping"), (1.2, "delivery"), (1.0, "freight"),
        # Mongolian
        (1.5, "хүргэлтийн үнэ"), (1.5, "хүргэлтийн бүс"),
        (1.5, "тээврийн зардал"), (1.2, "хүргэлт"),
        (1.2, "тээвэр"),
    ],
    "tax": [
        (1.5, "tax calculation"), (1.5, "tax compliance"),
        (1.5, "vat"), (1.5, "sales tax"),
        (1.2, "tax"),
        # Mongolian
        (1.5, "татварын тооцоо"), (1.5, "татвар тооцох"),
        (1.5, "НӨАТ"), (1.2, "татвар"),
    ],
    "checkout_optimizer": [
        (1.5, "checkout optimization"), (1.5, "checkout flow"),
        (1.5, "improve checkout"), (1.2, "checkout"),
        # Mongolian
        (1.5, "төлбөрийн урсгал"), (1.5, "чекаут сайжруулах"),
        (1.2, "чекаут"), (1.2, "төлбөрийн хуудас"),
    ],
    "wholesale_b2b": [
        (1.5, "b2b pricing"), (1.5, "wholesale price"),
        (1.5, "bulk discount"), (1.5, "trade pricing"),
        (1.2, "wholesale"), (1.2, "b2b"),
        # Mongolian
        (1.5, "бөөний үнэ"), (1.5, "оптын үнэ"),
        (1.5, "B2B үнэ"), (1.2, "бөөний"),
        (1.2, "оптом"),
    ],
    # ── Coverage expansion (PR #74) — 25 additional engines ─
    "accounting": [
        (1.5, "profit and loss"), (1.5, "p and l"), (1.5, "p&l"),
        (1.5, "balance sheet"), (1.5, "monthly report"),
        (1.5, "financial report"), (1.2, "accounting"),
        (1.2, "ledger"), (1.0, "books"),
        # Mongolian
        (1.5, "санхүүгийн тайлан"), (1.5, "орлого зарлага"),
        (1.5, "ашиг алдагдал"), (1.2, "санхүү"),
    ],
    "cash_flow": [
        (1.5, "cash flow"), (1.5, "cash reserves"),
        (1.5, "working capital"), (1.5, "money in money out"),
        (1.2, "liquidity"), (1.2, "burn rate"),
        # Mongolian
        (1.5, "мөнгөн гүйлгээ"), (1.5, "бэлэн мөнгө"),
        (1.5, "эргэлтийн хөрөнгө"), (1.2, "гүйлгээ"),
    ],
    "campaign_strategy": [
        (1.5, "marketing campaign"), (1.5, "campaign plan"),
        (1.5, "ad campaign"), (1.5, "launch campaign"),
        (1.2, "campaign"), (1.0, "marketing plan"),
        # Mongolian
        (1.5, "маркетингийн төлөвлөгөө"),
        (1.5, "кампанит ажил"), (1.5, "сурталчилгааны төлөвлөгөө"),
        (1.2, "кампанит"),
    ],
    "email_marketing": [
        (1.5, "email blast"), (1.5, "email campaign"),
        (1.5, "newsletter"), (1.5, "drip campaign"),
        (1.5, "automated email"), (1.2, "email"),
        (1.0, "mailing"),
        # Mongolian
        (1.5, "имэйл маркетинг"), (1.5, "имэйл явуулах"),
        (1.5, "мэдээллийн товхимол"), (1.2, "имэйл"),
    ],
    "catalog": [
        (1.5, "product catalog"), (1.5, "organize catalog"),
        (1.5, "category structure"), (1.5, "product collection"),
        (1.2, "catalog"), (1.0, "categories"),
        # Mongolian
        (1.5, "бүтээгдэхүүний каталог"), (1.5, "каталог зохион"),
        (1.5, "бүтээгдэхүүний цуглуулга"), (1.2, "каталог"),
    ],
    "chatbot": [
        (1.5, "live chat"), (1.5, "chatbot"),
        (1.5, "ai assistant"), (1.5, "support bot"),
        (1.2, "messenger"), (1.0, "automated reply"),
        # Mongolian
        (1.5, "чат бот"), (1.5, "AI туслах"),
        (1.5, "автомат хариулт"), (1.2, "чатбот"),
    ],
    "customer_service": [
        (1.5, "customer support"), (1.5, "support ticket"),
        (1.5, "help desk"), (1.5, "service request"),
        (1.2, "customer service"), (1.0, "ticket"),
        # Mongolian
        (1.5, "харилцагчийн үйлчилгээ"), (1.5, "хэрэглэгчийн үйлчилгээ"),
        (1.5, "тусламжийн хүсэлт"), (1.2, "үйлчилгээ"),
    ],
    "customer_segmentation": [
        (1.5, "customer segment"), (1.5, "segment customers"),
        (1.5, "customer group"), (1.5, "audience segment"),
        (1.2, "segmentation"), (1.0, "buyer persona"),
        # Mongolian
        (1.5, "хэрэглэгчийн ангилал"), (1.5, "хэрэглэгчийг ангилах"),
        (1.5, "хэрэглэгчийн бүлэг"), (1.2, "ангилал"),
    ],
    "competitor_monitor": [
        (1.5, "monitor competitor"), (1.5, "track competitor"),
        (1.5, "watch rival"), (1.5, "competitor alert"),
        (1.2, "competitive intel"),
        # Mongolian
        (1.5, "өрсөлдөгч ажиглах"), (1.5, "өрсөлдөгчийг хянах"),
        (1.5, "өрсөлдөгчийн мэдээ"), (1.2, "хяналт"),
    ],
    "conversion_tracking": [
        (1.5, "conversion rate"), (1.5, "track conversion"),
        (1.5, "funnel analysis"), (1.5, "conversion funnel"),
        (1.2, "conversions"), (1.0, "ctr"),
        # Mongolian
        (1.5, "хөрвүүлэлтийн хувь"), (1.5, "конверсын хувь"),
        (1.5, "юүлүүрийн шинжилгээ"), (1.2, "хөрвүүлэлт"),
    ],
    "dropshipping": [
        (1.5, "dropship supplier"), (1.5, "dropshipping"),
        (1.5, "fulfilled by supplier"), (1.5, "no inventory"),
        (1.2, "third party fulfillment"),
        # Mongolian
        (1.5, "дропшиппинг"), (1.5, "нийлүүлэгч хүргэх"),
        (1.5, "нөөцгүй худалдаа"), (1.2, "нийлүүлэгч"),
    ],
    "forecasting": [
        (1.5, "sales forecast"), (1.5, "demand forecast"),
        (1.5, "predict sales"), (1.5, "revenue projection"),
        (1.2, "forecast"), (1.0, "predict"),
        # Mongolian
        (1.5, "борлуулалт таамаглах"), (1.5, "эрэлт таамаглах"),
        (1.5, "орлогын төсөөлөл"), (1.2, "таамаглал"),
    ],
    "gift_card": [
        (1.5, "gift card"), (1.5, "store credit"),
        (1.5, "voucher"), (1.5, "issue gift card"),
        (1.2, "gift voucher"),
        # Mongolian
        (1.5, "бэлгийн карт"), (1.5, "дэлгүүрийн кредит"),
        (1.5, "ваучер"), (1.2, "бэлэг"),
    ],
    "image_optimization": [
        (1.5, "optimize images"), (1.5, "compress photos"),
        (1.5, "resize image"), (1.5, "image quality"),
        (1.2, "image optimization"), (1.0, "photos"),
        # Mongolian
        (1.5, "зураг оновчлох"), (1.5, "зураг шахах"),
        (1.5, "зургийн чанар"), (1.2, "зураг"),
    ],
    "landing_page": [
        (1.5, "landing page"), (1.5, "campaign page"),
        (1.5, "lead capture page"), (1.5, "promo page"),
        (1.2, "landing"),
        # Mongolian
        (1.5, "ландинг хуудас"), (1.5, "кампанит хуудас"),
        (1.5, "лэндинг пэйж"), (1.2, "буух хуудас"),
    ],
    "ltv_cac_dashboard": [
        (1.5, "lifetime value"), (1.5, "customer ltv"),
        (1.5, "ltv cac"), (1.5, "cac payback"),
        (1.5, "acquisition cost"), (1.2, "ltv"), (1.2, "cac"),
        # Mongolian
        (1.5, "хэрэглэгчийн насан туршийн үнэ"),
        (1.5, "хэрэглэгч татах зардал"),
        (1.2, "LTV CAC"),
    ],
    "market_research": [
        (1.5, "market research"), (1.5, "industry analysis"),
        (1.5, "market size"), (1.5, "tam sam som"),
        (1.2, "market analysis"),
        # Mongolian
        (1.5, "зах зээл судлах"), (1.5, "зах зээлийн судалгаа"),
        (1.5, "салбарын шинжилгээ"), (1.2, "зах зээл"),
    ],
    "nps_engine": [
        (1.5, "nps score"), (1.5, "net promoter"),
        (1.5, "satisfaction survey"), (1.5, "csat"),
        (1.2, "nps"), (1.0, "survey"),
        # Mongolian
        (1.5, "сэтгэл ханамжийн судалгаа"),
        (1.5, "сэтгэл ханамж"), (1.5, "хэрэглэгчийн санал асуулга"),
        (1.2, "санал асуулга"),
    ],
    "order_management": [
        (1.5, "manage orders"), (1.5, "order status"),
        (1.5, "order fulfillment"), (1.5, "order processing"),
        (1.5, "order management"), (1.2, "fulfillment"),
        # Mongolian
        (1.5, "захиалга удирдах"), (1.5, "захиалгын статус"),
        (1.5, "захиалга боловсруулах"), (1.2, "захиалга"),
    ],
    "payment_optimization": [
        (1.5, "payment method"), (1.5, "checkout payment"),
        (1.5, "payment options"), (1.5, "payment processor"),
        (1.2, "payments"),
        # Mongolian
        (1.5, "төлбөрийн арга"), (1.5, "төлбөрийн сонголт"),
        (1.5, "төлбөрийн систем"), (1.2, "төлбөр"),
    ],
    "product_research": [
        (1.5, "find products"), (1.5, "winning products"),
        (1.5, "product discovery"), (1.5, "trending products"),
        (1.2, "product research"),
        # Mongolian
        (1.5, "шилдэг бараа олох"), (1.5, "бараа судлах"),
        (1.5, "трэнд бараа"), (1.2, "бараа судалгаа"),
    ],
    "profit_optimization": [
        (1.5, "boost profit"), (1.5, "profit margin"),
        (1.5, "increase profit"), (1.5, "improve profitability"),
        (1.5, "profit optimization"), (1.2, "profitability"),
        # Mongolian
        (1.5, "ашгийг өсгөх"), (1.5, "ашгийг нэмэх"),
        (1.5, "ашгийн хувь"), (1.5, "ашиг оновчлох"),
        (1.2, "ашигтай байдал"),
    ],
    "returns_management": [
        (1.5, "manage returns"), (1.5, "return policy"),
        (1.5, "rma process"), (1.5, "return label"),
        (1.2, "returns"), (1.0, "refund"),
        # Mongolian
        (1.5, "буцаалт удирдах"), (1.5, "буцаалтын бодлого"),
        (1.5, "мөнгө буцаах"), (1.2, "буцаалт"),
    ],
    "review_management": [
        (1.5, "product review"), (1.5, "review moderation"),
        (1.5, "respond to reviews"), (1.5, "rating management"),
        (1.2, "reviews"), (1.0, "ratings"),
        # Mongolian
        (1.5, "бүтээгдэхүүний сэтгэгдэл"), (1.5, "сэтгэгдэлд хариулах"),
        (1.5, "үнэлгээ удирдах"), (1.2, "сэтгэгдэл"),
        (1.2, "үнэлгээ"),
    ],
    "social_media": [
        (1.5, "social media"), (1.5, "instagram post"),
        (1.5, "facebook post"), (1.5, "tiktok content"),
        (1.5, "social campaign"), (1.2, "social"),
        # Mongolian
        (1.5, "сошиал медиа"), (1.5, "инстаграм пост"),
        (1.5, "фэйсбүүк пост"), (1.2, "сошиал"),
    ],
    "subscription": [
        (1.5, "subscription"), (1.5, "recurring billing"),
        (1.5, "subscription box"), (1.5, "monthly plan"),
        (1.2, "subscriber"), (1.0, "recurring"),
        # Mongolian
        (1.5, "сарын захиалга"), (1.5, "гишүүнчлэл"),
        (1.5, "тогтмол төлбөр"), (1.2, "захиалга төлөвлөгөө"),
    ],
    "trend_detection": [
        (1.5, "trending products"), (1.5, "trend detection"),
        (1.5, "viral product"), (1.5, "hot products"),
        (1.2, "trends"), (1.0, "viral"),
        # Mongolian
        (1.5, "трэнд илрүүлэх"), (1.5, "виралжсан бараа"),
        (1.5, "халуун бараа"), (1.2, "трэнд"),
    ],
    "wishlist": [
        (1.5, "wishlist"), (1.5, "save for later"),
        (1.5, "wish list"), (1.2, "favorites"),
        # Mongolian
        (1.5, "таалагдсан бараа"), (1.5, "хүслийн жагсаалт"),
        (1.5, "сонирхсон бараа"), (1.2, "хүсэл"),
    ],
    "workflow_builder": [
        (1.5, "automate workflow"), (1.5, "build automation"),
        (1.5, "workflow builder"), (1.5, "automation rule"),
        (1.2, "workflow"), (1.0, "automation"),
        # Mongolian
        (1.5, "автоматжуулалт"), (1.5, "автомат дүрэм"),
        (1.5, "процесс автоматжуулах"), (1.2, "процесс"),
    ],
}

_PHRASE_NORMALISE = re.compile(r"[^\w\s%]", re.UNICODE)


@dataclass
class IntentResult:
    """Outcome of an intent-classification request.

    ``engine`` is ``None`` when no candidate scored above
    ``_NO_MATCH_FLOOR``. ``alternatives`` is always present even
    on a no-match so the API can render "did you mean X?".
    """

    engine: str | None
    confidence: float
    alternatives: list[tuple[str, float]] = field(default_factory=list)
    source: str = "rules"
    explanation: str = ""
    matched_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "confidence": round(self.confidence, 3),
            "alternatives": [
                {"engine": e, "confidence": round(c, 3)}
                for e, c in self.alternatives
            ],
            "source": self.source,
            "explanation": self.explanation,
            "matched_keywords": self.matched_keywords,
        }


def classify_intent(
    text: str,
    *,
    language: str = "auto",
    available_engines: set[str] | None = None,
) -> IntentResult:
    """Map free-form ``text`` to the best-match engine name.

    Args:
        text: User input. Capped at ``_MAX_TEXT_LEN`` characters
            so a malformed request can't burn unbounded matcher
            time.
        language: Hint for future LLM fallback. Currently
            ignored — the rule-based path is language-agnostic
            because the index includes Mongolian and English
            keywords side-by-side.
        available_engines: Optional whitelist used by callers
            who only want to route within their slice of
            engines (e.g. integration tests). When ``None`` the
            full ``_INTENT_INDEX`` is consulted.

    Returns:
        :class:`IntentResult`. ``engine`` is ``None`` on a
        no-match; check ``alternatives`` for runner-ups.
    """
    if not isinstance(text, str) or not text.strip():
        return IntentResult(
            engine=None, confidence=0.0,
            source="rules",
            explanation="empty input",
        )
    text = text[:_MAX_TEXT_LEN]
    norm = _normalise(text)
    input_tokens = _stemmed_tokens(norm)

    scores: dict[str, float] = {}
    matched: dict[str, list[str]] = {}

    for engine, phrases in _INTENT_INDEX.items():
        if available_engines is not None and engine not in available_engines:
            continue
        engine_score = 0.0
        engine_matched: list[str] = []
        for weight, phrase in phrases:
            phrase_norm = _normalise(phrase)
            if not phrase_norm:
                continue
            # Tier 1 — contiguous substring (strongest signal).
            if phrase_norm in norm:
                engine_score += weight
                engine_matched.append(phrase)
                continue
            # Tier 2 — every phrase token (stemmed) appears in
            # the input. Catches "lower my product prices" vs
            # the phrase "lower price". Down-weighted to 70% so
            # contiguous matches still win.
            phrase_tokens = _stemmed_tokens(phrase_norm)
            if phrase_tokens and phrase_tokens.issubset(input_tokens):
                engine_score += weight * 0.7
                engine_matched.append(phrase)
        if engine_score > 0:
            scores[engine] = engine_score
            matched[engine] = engine_matched

    if not scores:
        # Zero rule matches — try the LLM fallback before
        # surrendering. Same opt-in semantics as the
        # below-floor branch below.
        llm_result = _try_llm_fallback(text)
        if llm_result is not None:
            return IntentResult(
                engine=llm_result.engine,
                confidence=llm_result.confidence,
                source="llm",
                explanation=llm_result.reasoning or (
                    "LLM-classified after rule-based pass had "
                    "no keyword match"
                ),
            )

        return IntentResult(
            engine=None, confidence=0.0,
            source="rules",
            explanation=(
                "no engine keyword matched — "
                "try 'increase prices' or 'create discount'"
            ),
        )

    # Convert raw weighted scores into a [0, 1] confidence by
    # comparing each engine's score to the theoretical max
    # (sum of its phrase weights). This way a partial match on
    # an engine with many phrases doesn't dominate a full match
    # on an engine with few.
    normalised: list[tuple[str, float]] = []
    for engine, raw in scores.items():
        max_possible = sum(w for w, _ in _INTENT_INDEX[engine])
        if max_possible == 0:
            confidence = 0.0
        else:
            # Square-root softens the curve so a single multi-
            # word match still produces a respectable confidence.
            confidence = min(1.0, (raw / max_possible) ** 0.5)
        normalised.append((engine, confidence))

    normalised.sort(key=lambda x: x[1], reverse=True)
    top_engine, top_confidence = normalised[0]

    if top_confidence < _NO_MATCH_FLOOR:
        # Rule-based pass gave up. Try the LLM fallback before
        # surrendering. The fallback is opt-in by deployment
        # (only fires when ANTHROPIC_API_KEY is set + the SDK
        # is importable) so production code without a key
        # behaves exactly as before.
        llm_result = _try_llm_fallback(text)
        if llm_result is not None:
            return IntentResult(
                engine=llm_result.engine,
                confidence=llm_result.confidence,
                alternatives=[
                    (e, c) for e, c in normalised[:_ALTERNATIVES_RETURNED]
                ],
                source="llm",
                explanation=llm_result.reasoning or (
                    f"LLM-classified after rule-based fallback "
                    f"(rules best: '{top_engine}' at "
                    f"{top_confidence:.2f})"
                ),
            )

        return IntentResult(
            engine=None,
            confidence=top_confidence,
            alternatives=[
                (e, c) for e, c in normalised[:_ALTERNATIVES_RETURNED]
            ],
            source="rules",
            explanation=(
                f"weak match — best candidate '{top_engine}' "
                f"scored {top_confidence:.2f} (floor "
                f"{_NO_MATCH_FLOOR})"
            ),
        )

    qualifier = "high" if top_confidence >= _HIGH_CONFIDENCE else "medium"
    return IntentResult(
        engine=top_engine,
        confidence=top_confidence,
        alternatives=[
            (e, c) for e, c in normalised[1:_ALTERNATIVES_RETURNED + 1]
        ],
        source="rules",
        explanation=(
            f"{qualifier} confidence — matched "
            f"{', '.join(matched[top_engine][:3])}"
        ),
        matched_keywords=matched[top_engine],
    )


def _try_llm_fallback(text: str):
    """Best-effort LLM classification when the rule-based pass
    yielded a below-floor match.

    Lazy-imports :mod:`core.brain.intent_llm` so a missing
    Anthropic SDK can't break the rule-based hot path. Returns
    ``LLMIntentResult`` on success, ``None`` on any failure
    (key missing / SDK absent / network / parse).
    """
    try:
        from core.brain.intent_llm import llm_classify
    except Exception as exc:  # noqa: BLE001
        logger.debug("intent_llm import failed: %s", exc)
        return None

    phrase_hints = {
        engine: [phrase for _, phrase in phrases][:6]
        for engine, phrases in _INTENT_INDEX.items()
    }
    try:
        return llm_classify(
            text,
            candidate_engines=list(_INTENT_INDEX.keys()),
            phrase_hints=phrase_hints,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("llm_classify raised: %s", exc)
        return None


def list_supported_engines() -> list[str]:
    """Engines the rule-based router currently knows.

    Surface for the API: a caller hitting the ``/api/intent``
    endpoint with no prior knowledge of which engines are
    routable can hit this list to see the menu.
    """
    return sorted(_INTENT_INDEX.keys())


def _normalise(text: str) -> str:
    """Lower-case + strip punctuation (keep ``%`` for ``%off``)."""
    cleaned = _PHRASE_NORMALISE.sub(" ", text)
    return " ".join(cleaned.lower().split())


def _stemmed_tokens(text: str) -> set[str]:
    """Word-level token set with naive trailing-``s`` stripping.

    The intent index speaks in either singular ("lower price") or
    plural ("raise prices") forms; the merchant might type either.
    Stripping a trailing ``s`` from any token of length ≥ 4
    collapses common pluralisation without bringing in a real
    stemmer. The 4-char floor keeps short tokens like "ads" intact.
    """
    out: set[str] = set()
    for word in text.split():
        if len(word) >= 4 and word.endswith("s") and not word.endswith("ss"):
            out.add(word[:-1])
        else:
            out.add(word)
    return out
