"""Niche-aware blog post starter generator + applier.

Every Shopify store benefits from a blog -- it drives organic
traffic, surfaces brand voice, and gives the operator
something to share. Most stores launch with an empty blog
section (or no blog at all) because nobody writes 3+ posts
before opening.

This module fills that gap. Generates 3 niche-aware article
drafts (~300 words each) ready to push via
``SHOPIFY_CREATE_ARTICLE``. Each article carries:

  * title (H1)
  * summary (article-card excerpt)
  * body_html (full body with H2/H3 sectioning)
  * tags (3-5 niche-aware tags)

The applier handles the blog dependency: if the caller
doesn't pass a ``blog_id``, the applier auto-creates a
"News" blog via ``SHOPIFY_CREATE_BLOG`` first, then writes
all articles to it. This keeps the autonomous flow truly
single-command.

Return shape from :func:`generate_blog_starter`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "articles": [
            {
                "title": "Your first ingredient deep-dive",
                "summary": "How to read a skincare label...",
                "body_html": "<h2>Why ingredients matter...",
                "tags": ["ingredients", "clean-beauty", ...],
            },
            ...
        ],
    }

Pattern Z: one writeback per article applied so the
autonomous learning loop sees per-article launch outcomes.
"""
from __future__ import annotations

import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# ── Article specs per niche (3 drafts each) ───────────────────


# Each entry: (title, summary, body_html, tags).
# Body HTML is ~250-350 words, structured with H2/H3.
_NICHE_ARTICLES: dict[
    str, list[tuple[str, str, str, list[str]]],
] = {
    "beauty": [
        (
            "How to read a skincare label",
            "Ingredient lists are sorted by concentration. "
            "Here's what to look for first.",
            "<h2>Why the label matters</h2>"
            "<p>A skincare ingredient list is sorted by "
            "concentration -- top 5 ingredients make up "
            "~80% of the product. If water is first, the "
            "formula is mostly hydration; if alcohol "
            "denat is in the top 3, expect a drying "
            "finish.</p>"
            "<h2>Active ingredients to recognise</h2>"
            "<p>Look for actives by name: niacinamide "
            "(brightening), salicylic acid (exfoliation), "
            "retinol (turnover), ceramides + hyaluronic "
            "acid (barrier). Percentages matter: 10% "
            "niacinamide is therapeutic; 0.1% is window "
            "dressing.</p>"
            "<h2>What to avoid (and when)</h2>"
            "<p>Fragrance is the #1 sensitive-skin "
            "trigger. \"Fragrance-free\" beats \"unscented\" "
            "-- unscented products often add masking "
            "fragrance. Sulfates are fine in body wash, "
            "drying in shampoo for color-treated hair.</p>"
            "<h2>The quick test</h2>"
            "<p>Read the first 5 ingredients out loud. If "
            "you can't pronounce most of them and they're "
            "near the top, the formula is mostly inactive. "
            "Save your money for products where the "
            "actives are above the preservatives.</p>",
            ["ingredients", "clean-beauty", "skincare",
             "education"],
        ),
        (
            "Building a 5-minute routine that actually works",
            "Most skincare routines are too long to stick "
            "to. Three steps will outperform ten.",
            "<h2>The three-step rule</h2>"
            "<p>Cleanse, treat, moisturise. That's it. "
            "Anything beyond those three steps is "
            "optional, and adding steps you skip 60% of "
            "the time is worse than not having them.</p>"
            "<h2>Morning: 90 seconds</h2>"
            "<p>Splash water (or a gentle cleanser if "
            "you slept in product). Apply a vitamin C "
            "serum (one pump). Finish with moisturiser + "
            "SPF 30+. Total: under two minutes once "
            "you've done it five times.</p>"
            "<h2>Evening: 3 minutes</h2>"
            "<p>Cleanser (gel for oily, cream for dry). "
            "An active 3-4 times a week (retinol or "
            "exfoliating acid -- never both same night). "
            "Moisturiser. The rest is bonus.</p>"
            "<h2>Why consistency beats complexity</h2>"
            "<p>A 3-step routine you do daily outperforms "
            "an 8-step routine you do twice a week. Build "
            "the habit first, layer in extras after a "
            "month.</p>",
            ["routine", "skincare", "tutorial",
             "minimalism"],
        ),
        (
            "The truth about \"clean\" beauty",
            "\"Clean\" isn't regulated. Here's what it "
            "actually means and what to verify.",
            "<h2>There's no FDA definition</h2>"
            "<p>The word \"clean\" on a beauty product "
            "has no legal meaning. Each retailer defines "
            "its own list of excluded ingredients (Sephora "
            "Clean, Credo Clean, Whole Foods Premium "
            "Body Care). The lists overlap but aren't "
            "identical.</p>"
            "<h2>What \"clean\" usually excludes</h2>"
            "<p>Parabens, phthalates, sulfates "
            "(SLS/SLES), formaldehyde + formaldehyde "
            "releasers, oxybenzone, hydroquinone, "
            "synthetic fragrance. Some lists add "
            "mineral oil, talc, silicones, or "
            "ethoxylates.</p>"
            "<h2>What it doesn't guarantee</h2>"
            "<p>\"Clean\" doesn't mean vegan, "
            "cruelty-free, organic, or "
            "sustainably-sourced. Check those "
            "certifications separately if they matter "
            "to you.</p>"
            "<h2>How we vet what we carry</h2>"
            "<p>Every product on our shelves clears the "
            "common-denominator clean list AND has a "
            "transparent supply chain. We email brands "
            "for ingredient sourcing details; if they "
            "won't share, we don't stock.</p>",
            ["clean-beauty", "ingredients", "transparency",
             "education"],
        ),
    ],
    "fashion": [
        (
            "How to read a size guide (and actually fit)",
            "Size charts vary by brand. Here's the "
            "two-measurement test that beats trying on.",
            "<h2>Brand sizing is a wild west</h2>"
            "<p>A size M at one brand fits like a size S "
            "at another. The garment-measurement table "
            "(usually in cm and inches) is the source of "
            "truth -- not the size letter.</p>"
            "<h2>Take two measurements</h2>"
            "<p>For tops: chest at the widest point + "
            "waist at the narrowest. For bottoms: waist + "
            "hip (8 inches below waist for jeans, at the "
            "widest for skirts). Compare to the garment "
            "measurements, not the body-fit chart.</p>"
            "<h2>What \"true to size\" usually means</h2>"
            "<p>Match your measurement to the garment "
            "measurement +/- 1 inch for woven fabrics; "
            "0 to -1 inch for stretch knits "
            "(they recover). Oversized fits add 4-6 "
            "inches; tailored fits hug.</p>"
            "<h2>When in doubt, size up</h2>"
            "<p>Especially for tailored jackets, denim, "
            "and structured pieces. A tailor can take in; "
            "letting out is rarely possible.</p>",
            ["sizing", "fit-guide", "tutorial",
             "education"],
        ),
        (
            "Building a capsule wardrobe -- 12 pieces",
            "A capsule is 12-15 pieces that mix into "
            "30+ outfits. Here's the starter list.",
            "<h2>What goes in the capsule</h2>"
            "<p>Three tops (white tee, black tee, "
            "neutral knit). Two bottoms (dark denim, "
            "neutral trouser). One dress. One blazer. "
            "One coat. Two shoes (sneakers + boots). "
            "Two accessories (belt + bag). That's 12 "
            "pieces, ~30 outfits.</p>"
            "<h2>Colour palette</h2>"
            "<p>Stick to 3 colours max in the first "
            "capsule: one neutral (black, navy, or "
            "cream), one mid-tone (camel, sage, "
            "burgundy), one accent. Every piece works "
            "with every other piece.</p>"
            "<h2>Fabric matters more than colour</h2>"
            "<p>Wool, cotton, linen, silk -- natural "
            "fibres last 5+ years if you care for them. "
            "Polyester-blend pieces pill and shrink. "
            "Spend on the natural fibres; cut corners "
            "on accessories.</p>"
            "<h2>What to skip</h2>"
            "<p>Trends, prints with limited mixing "
            "potential, anything labelled \"statement\" "
            "piece. The capsule is the everyday floor; "
            "trends are extras.</p>",
            ["capsule-wardrobe", "style-guide",
             "minimalism", "wardrobe-essentials"],
        ),
        (
            "Fabric care 101",
            "The labels are cryptic. Here's what they "
            "actually mean and when to ignore them.",
            "<h2>The symbols decoded</h2>"
            "<p>Tub = wash. Triangle = bleach (X = no "
            "bleach). Square = dry (with a circle = "
            "tumble dry). Iron = iron (dots = "
            "temperature). Circle = dry clean. A line "
            "under any symbol means \"gentle\".</p>"
            "<h2>Water temperature matters</h2>"
            "<p>Cold (30°C / 86°F) preserves colour + "
            "shape for almost everything. Hot is for "
            "bedding + heavy soiling. Modern detergents "
            "are formulated for cold -- you're not "
            "saving anything by going hot.</p>"
            "<h2>When to ignore \"dry clean only\"</h2>"
            "<p>Cotton, linen, polyester labelled "
            "\"dry clean\" usually means \"we don't "
            "want to test the home-wash claim\". Hand "
            "wash cold + lay flat to dry works. Silk + "
            "wool + structured tailoring really do need "
            "dry cleaning.</p>"
            "<h2>The trick that extends garment life "
            "5x</h2>"
            "<p>Wash less. Hang to air after wearing. "
            "Spot-clean stains immediately. Most modern "
            "fabrics survive 4-5 wears before needing "
            "a wash -- jeans 10+. Washing IS the wear.</p>",
            ["fabric-care", "garment-care", "tutorial",
             "education"],
        ),
    ],
    "tech": [
        (
            "The buyer's guide to [category]",
            "Spec sheets are designed to confuse. Here's "
            "the 3-spec test that picks the right unit.",
            "<h2>Most specs don't matter</h2>"
            "<p>Marketing pushes the spec that sounds "
            "best. For 90% of products, three specs "
            "actually determine performance: power "
            "rating, build quality, after-sales support. "
            "Everything else is noise.</p>"
            "<h2>How to read a spec sheet</h2>"
            "<p>Find the bench-test rating (not "
            "manufacturer claims). Cross-reference with "
            "two independent reviewers. If a unit "
            "underperforms its spec sheet by 15% in "
            "real-world tests, that's the actual "
            "performance.</p>"
            "<h2>Warranty signals quality</h2>"
            "<p>A 5-year warranty on a $50 product is "
            "rare; it means the manufacturer expects "
            "long life. Two-year is standard; one-year "
            "is a red flag for the price tier.</p>"
            "<h2>What to ignore</h2>"
            "<p>Marketing terms like \"premium\", "
            "\"pro\", \"advanced\". These are tier "
            "indicators within a brand, not absolute "
            "performance markers across brands.</p>",
            ["buying-guide", "tech-tips", "education",
             "specifications"],
        ),
        (
            "How to spot fake reviews",
            "AI-generated and incentivised reviews are "
            "everywhere. Here's the four-signal test.",
            "<h2>Signal 1: review velocity</h2>"
            "<p>Most legitimate products earn ~1-3 "
            "reviews per 100 sales. A product with "
            "1000+ reviews in its first month either "
            "incentivised aggressively or bought "
            "reviews. Check the curve.</p>"
            "<h2>Signal 2: language patterns</h2>"
            "<p>AI reviews often use identical sentence "
            "structures and praise the same 3 features "
            "in every review. Real reviews focus on "
            "what surprised the buyer -- specific "
            "details, not generic praise.</p>"
            "<h2>Signal 3: rating distribution</h2>"
            "<p>Genuine review distributions are "
            "J-shaped: lots of 5-stars, some 1-stars, "
            "few in the middle. Suspicious distributions "
            "are uniform (mass-manufactured) or "
            "perfectly 5-star (bought).</p>"
            "<h2>Signal 4: verified-purchase ratio</h2>"
            "<p>Below 70% verified-purchase is a yellow "
            "flag. Below 50% is a red flag. Filter by "
            "verified to see the truth.</p>",
            ["buying-guide", "consumer-rights",
             "education"],
        ),
        (
            "Why warranty length tells you everything",
            "Manufacturers know their products' "
            "failure curves. Warranty length is the "
            "honest signal.",
            "<h2>Warranty length = expected lifetime</h2>"
            "<p>Manufacturers price warranties to "
            "expire just before expected failure. A "
            "1-year warranty means most units fail in "
            "year 2; a 5-year warranty means most last "
            "6+.</p>"
            "<h2>What \"limited\" means</h2>"
            "<p>\"Limited\" warranties exclude common "
            "failure modes: motor, screen, battery, "
            "moisture damage. Read the exclusions list "
            "before the warranty period. A 10-year "
            "limited warranty that excludes the motor "
            "is a 1-year warranty.</p>"
            "<h2>Registered vs unregistered</h2>"
            "<p>Some warranties require registration "
            "within 30 days. Skip this and your "
            "warranty drops by half. Always register "
            "via the manufacturer's site, not the "
            "retailer's.</p>"
            "<h2>How we filter what we carry</h2>"
            "<p>Every product on our shelves carries "
            "at least the category-standard warranty. "
            "We don't stock items where the warranty "
            "is shorter than competitors at the same "
            "price.</p>",
            ["warranty", "buying-guide",
             "consumer-rights", "education"],
        ),
    ],
    "home": [
        (
            "Why \"built to last\" actually matters",
            "Disposable home goods are the real cost "
            "centre. Here's the long-life math.",
            "<h2>The replacement-cycle math</h2>"
            "<p>A $30 desk chair lasts 2 years. A $300 "
            "desk chair lasts 15. Over 30 years, the "
            "$30 chair costs $450 (replacements + "
            "disposal); the $300 chair costs $300. "
            "Cheaper IS more expensive.</p>"
            "<h2>How to spot longevity</h2>"
            "<p>Solid wood beats MDF. Metal joinery "
            "beats plastic. Replaceable parts beat "
            "sealed. Repair-friendly construction beats "
            "single-use. Heft (real weight) usually "
            "tracks materials honesty.</p>"
            "<h2>What we look for</h2>"
            "<p>Pieces with a published material list, "
            "named maker, and a serviceable design. We "
            "skip anything where the brand can't tell "
            "us where the wood was milled or the metal "
            "was sourced.</p>"
            "<h2>The 10-year rule</h2>"
            "<p>If a piece won't look good (or work "
            "well) in 10 years, don't buy it. Trend "
            "furniture ages; functional design lasts.</p>",
            ["sustainability", "buying-guide",
             "home-decor", "longevity"],
        ),
        (
            "Caring for natural materials",
            "Wood, linen, ceramic -- different rules, "
            "same principle: small care, long life.",
            "<h2>Wood</h2>"
            "<p>Dust weekly with a microfibre cloth. "
            "Oil once a year (linseed for raw, "
            "furniture polish for sealed). Keep away "
            "from radiators and direct sun -- both "
            "crack the grain. A water stain is fixable; "
            "a heat ring is forever.</p>"
            "<h2>Linen</h2>"
            "<p>Wash cold, hang to dry. Linen softens "
            "with washing -- 5+ washes is when it "
            "feels best. Iron damp, not dry. Wrinkles "
            "are a feature, not a defect.</p>"
            "<h2>Ceramic</h2>"
            "<p>Most ceramics are dishwasher-safe; "
            "hand-painted pieces aren't. Avoid "
            "thermal shock -- don't pour boiling water "
            "into a cold piece. Hairline cracks "
            "stabilise with a coat of beeswax.</p>"
            "<h2>Why this matters</h2>"
            "<p>A natural material that's cared for "
            "outlives several synthetic replacements. "
            "Two minutes of monthly care = decades of "
            "use.</p>",
            ["care-guide", "natural-materials",
             "home-care", "tutorial"],
        ),
        (
            "Lighting that actually changes a room",
            "Overhead light is the worst light. Here's "
            "the three-source rule.",
            "<h2>One light is never enough</h2>"
            "<p>A single overhead fixture creates "
            "shadows on faces and flat lighting on "
            "surfaces. Every room needs at least three "
            "sources: ambient (overall), task "
            "(reading / cooking), accent (mood).</p>"
            "<h2>Layering done right</h2>"
            "<p>Living room: ceiling fixture (ambient) "
            "+ floor lamp (task) + table lamp "
            "(accent). Kitchen: under-cabinet (task) "
            "+ pendant over island (focal) + "
            "recessed (ambient). Bedroom: bedside "
            "lamps (task) + small fixture (ambient).</p>"
            "<h2>Colour temperature matters</h2>"
            "<p>2700K (warm white) for living spaces "
            "+ bedrooms. 3000-3500K for kitchens + "
            "bathrooms. Above 4000K reads cold and "
            "office-like in residential spaces. Mix "
            "temperatures within a room only if it's "
            "intentional.</p>"
            "<h2>Dimmers are cheap, life-changing</h2>"
            "<p>$30 per switch. Lets the same fixture "
            "serve dinner-party mood and laundry-fold "
            "task light. Install on at least one "
            "fixture per room.</p>",
            ["lighting", "interior-design", "tutorial",
             "home-improvement"],
        ),
    ],
    "food": [
        (
            "Stocking the pantry: 12 essentials",
            "These twelve items + fresh produce = 80% "
            "of dinners. Here's the starter list.",
            "<h2>The Mediterranean baseline</h2>"
            "<p>Olive oil, sea salt, black pepper, "
            "garlic, dried pasta, canned tomatoes, "
            "anchovy paste, parmesan. With fresh greens "
            "+ a protein, these eight make 30+ dinners. "
            "Add lemons, capers, dried chillies, and "
            "good vinegar for the full kit.</p>"
            "<h2>The Asian-pantry overlay</h2>"
            "<p>Soy sauce, rice vinegar, sesame oil, "
            "miso, gochujang, fish sauce, rice "
            "noodles, jasmine rice. Five extra "
            "ingredients open up most of East + "
            "Southeast Asian cooking.</p>"
            "<h2>Quality matters here</h2>"
            "<p>Spend on the staples you use daily: "
            "olive oil + soy sauce + salt. A "
            "$25 olive oil makes everything taste "
            "better; a $25 truffle oil sits in the "
            "cupboard. Splurge on volume, not novelty.</p>"
            "<h2>Storage rules</h2>"
            "<p>Olive oil keeps 18 months in dark "
            "glass. Dried pasta keeps 2+ years. "
            "Spices lose potency in 1 year -- date "
            "your jars. Tomatoes + anchovies don't "
            "improve in the cupboard; rotate stock.</p>",
            ["pantry", "cooking", "essentials",
             "food-guide"],
        ),
        (
            "How to taste like a buyer",
            "Tasting professionally is a learnable "
            "skill. Here's the framework.",
            "<h2>The five-step tasting</h2>"
            "<p>1. Look (colour + clarity). 2. Smell "
            "(close your eyes; first impression). 3. "
            "Sip (sit on the tongue for 5 seconds). "
            "4. Swallow (note the finish length). 5. "
            "Reflect (10 seconds before notes).</p>"
            "<h2>Vocabulary that helps</h2>"
            "<p>Use comparisons: \"like rosemary\", "
            "\"like the smell of wet stone\". Specific "
            "comparisons beat abstract adjectives. "
            "Avoid \"smooth\" and \"complex\" -- "
            "they're filler.</p>"
            "<h2>What you'll start noticing</h2>"
            "<p>Within 5 sessions, you'll separate "
            "structure (acidity / sugar / tannin) from "
            "flavour (specific aromas). The two are "
            "independent: a wine can have great "
            "structure and boring flavour, or vice "
            "versa.</p>"
            "<h2>How to practice</h2>"
            "<p>Taste two of the same type side by "
            "side -- two olive oils, two dark "
            "chocolates, two coffees. Differences pop "
            "in pairs that're hard to spot in "
            "isolation.</p>",
            ["tasting", "tutorial", "education",
             "food-skills"],
        ),
        (
            "Sourcing transparency: what to ask",
            "\"Where is it from\" is the wrong "
            "question. Here are the four that get "
            "real answers.",
            "<h2>Ask: who is the maker?</h2>"
            "<p>\"Made in Italy\" is marketing. "
            "\"Made by [farmer name] in [village]\" "
            "is sourcing. A real producer has a "
            "name + a story; a fake one has a "
            "logo + a country.</p>"
            "<h2>Ask: what's the supply chain?</h2>"
            "<p>How many hands between maker and "
            "shelf? Direct trade = 1-2. \"Single "
            "origin\" usually = 3-4. Generic "
            "imports = 5-7+. Each hand takes margin "
            "+ adds opacity.</p>"
            "<h2>Ask: what's the harvest / "
            "production date?</h2>"
            "<p>Fresh-pressed olive oil should be "
            "under 6 months from harvest. Coffee "
            "should be under 6 months from "
            "roasting. \"Best before\" dates are "
            "compliance, not freshness.</p>"
            "<h2>Ask: can I see the certifications?</h2>"
            "<p>Real certs are auditable + dated. "
            "If a seller can't email you the cert "
            "PDF in 48 hours, the cert is decorative.</p>",
            ["sourcing", "transparency", "education",
             "food-guide"],
        ),
    ],
    "general": [
        (
            "Welcome to our store",
            "What we sell, why we started, and how "
            "to reach us.",
            "<h2>Why we're here</h2>"
            "<p>We started this store because the "
            "products we wanted at the prices that "
            "made sense didn't exist together. "
            "Existing stores sold quality at "
            "luxury prices, or budget at "
            "questionable quality. Neither was the "
            "right tradeoff for us.</p>"
            "<h2>What we curate for</h2>"
            "<p>Real quality (materials + "
            "construction we'd buy ourselves). "
            "Honest pricing (fair margin, not "
            "luxury markup). Transparent sourcing "
            "(we tell you where things come from). "
            "Fast support (a real person responds "
            "within 24 hours).</p>"
            "<h2>What you'll find here</h2>"
            "<p>Carefully chosen items in each "
            "category we cover, with the "
            "back-story on each. We don't carry "
            "1000s of SKUs; we carry the right "
            "ones.</p>"
            "<h2>How to reach us</h2>"
            "<p>Email or the contact form on the "
            "site. Most messages get a same-day "
            "response, every message gets a "
            "next-business-day response at the "
            "latest.</p>",
            ["about", "welcome", "company-story"],
        ),
        (
            "Our return policy in plain English",
            "30 days, no questions asked. Here's "
            "what that actually means.",
            "<h2>The short version</h2>"
            "<p>Return anything unused in its "
            "original packaging within 30 days. "
            "Refund processes within 5-10 "
            "business days to the original "
            "payment method. No restocking fees, "
            "no \"final sale\" loopholes on "
            "regular inventory.</p>"
            "<h2>Edge cases</h2>"
            "<p>Used-but-defective: covered as a "
            "warranty claim, not a return. "
            "Email us with photos + we'll route "
            "to the manufacturer.</p>"
            "<p>Gift returns: the gift recipient "
            "can return with the giver's email + "
            "order number. Refund goes to the "
            "original payment method.</p>"
            "<h2>What we don't do</h2>"
            "<p>We don't charge restocking. We "
            "don't require original-tags-only. "
            "We don't pre-screen returns for "
            "\"acceptable reasons\".</p>",
            ["returns", "customer-service",
             "policies"],
        ),
        (
            "Why we focus on fewer SKUs",
            "Most online stores carry too many "
            "products. We deliberately don't.",
            "<h2>The 10,000-SKU problem</h2>"
            "<p>A store with 10,000 SKUs can't "
            "have used each one. Buyers are "
            "either dropshipping (no quality "
            "control) or selecting on margin + "
            "marketing (not quality). Either "
            "way, you can't trust the curation.</p>"
            "<h2>What we do instead</h2>"
            "<p>Hundreds, not thousands. Every "
            "item passes through our hands. We "
            "test, we use, we keep what's worth "
            "keeping. Items get cut from the "
            "lineup when something better comes "
            "along.</p>"
            "<h2>What you trade away</h2>"
            "<p>Selection. If you want 50 "
            "options for X, we're the wrong "
            "store. If you want the 2-3 best, "
            "we're the right one.</p>"
            "<h2>What you get in return</h2>"
            "<p>Confidence. The thing you bought "
            "is genuinely something we'd buy. "
            "The return policy reflects that "
            "confidence -- 30 days, no questions.</p>",
            ["curation", "company-story",
             "philosophy"],
        ),
    ],
}


_DEFAULT_BLOG_TITLE: str = "News"


def generate_blog_starter(
    *,
    store_name: str,
    niche: str = "general",
    author_name: str | None = None,
) -> dict[str, Any]:
    """Build niche-aware article specs ready for SHOPIFY_CREATE_ARTICLE.

    Args:
        store_name: Display name (returned for context).
            Empty -> empty dict.
        niche: Lowercase niche key. Unknown -> general.
        author_name: Optional author byline. Threaded into
            the article when supplied.

    Returns:
        ``{store_name, niche, articles: [{title, summary,
        body_html, tags, author_name?}, ...]}``. The articles
        list has exactly 3 entries per niche.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    entries = _NICHE_ARTICLES.get(
        niche_n, _NICHE_ARTICLES["general"],
    )

    articles: list[dict[str, Any]] = []
    for title, summary, body_html, tags in entries:
        article: dict[str, Any] = {
            "title": title,
            "summary": summary,
            "body_html": body_html,
            "tags": list(tags),
        }
        if author_name and author_name.strip():
            article["author_name"] = author_name.strip()
        articles.append(article)

    return {
        "store_name": name,
        "niche": niche_n,
        "articles": articles,
    }


def apply_blog_starter(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
    blog_id: str | None = None,
    blog_title: str | None = None,
) -> dict[str, Any]:
    """Push each article spec via SHOPIFY_CREATE_ARTICLE.

    When ``blog_id`` is None, auto-creates a blog (titled
    ``"News"`` by default; override via ``blog_title``) via
    SHOPIFY_CREATE_BLOG first so the autonomous flow stays
    single-call.

    Args:
        spec: Dict from :func:`generate_blog_starter`.
        store_id: Optional per-store Pattern Z scope.
        blog_id: Optional Shopify GID for an existing blog.
            When None, auto-creates one.
        blog_title: Override the auto-created blog title.

    Returns:
        ``{applied_count, results, blog_id, blog_title}``.
        Each result entry: ``{title, ok, error, article_id}``.
    """
    if not isinstance(spec, dict):
        return {
            "applied_count": 0,
            "results": [],
            "blog_id": None,
            "blog_title": None,
        }
    articles = spec.get("articles") or []
    if not isinstance(articles, list) or not articles:
        return {
            "applied_count": 0,
            "results": [],
            "blog_id": None,
            "blog_title": None,
        }

    router = _get_router()
    if router is None:
        results = [
            {
                "title": a.get("title", ""),
                "ok": False,
                "error": "router_unavailable",
                "article_id": None,
            }
            for a in articles
        ]
        for r, art in zip(results, articles):
            _record(
                title=r["title"], success=False,
                error=r["error"], store_id=store_id,
                spec=art,
            )
        return {
            "applied_count": 0,
            "results": results,
            "blog_id": None,
            "blog_title": None,
        }

    create_blog_cap = _resolve_cap("SHOPIFY_CREATE_BLOG")
    create_article_cap = _resolve_cap("SHOPIFY_CREATE_ARTICLE")
    if create_article_cap is None:
        # Adapter layer missing the capability entirely.
        results = [
            {
                "title": a.get("title", ""),
                "ok": False,
                "error": "capability_unavailable",
                "article_id": None,
            }
            for a in articles
        ]
        return {
            "applied_count": 0,
            "results": results,
            "blog_id": None,
            "blog_title": None,
        }

    resolved_blog_id, resolved_blog_title = (
        _resolve_blog(
            router=router,
            create_blog_cap=create_blog_cap,
            blog_id=blog_id,
            blog_title=blog_title,
        )
    )
    if not resolved_blog_id:
        results = [
            {
                "title": a.get("title", ""),
                "ok": False,
                "error": "blog_unavailable",
                "article_id": None,
            }
            for a in articles
        ]
        for r, art in zip(results, articles):
            _record(
                title=r["title"], success=False,
                error="blog_unavailable",
                store_id=store_id, spec=art,
            )
        return {
            "applied_count": 0,
            "results": results,
            "blog_id": None,
            "blog_title": resolved_blog_title,
        }

    results: list[dict[str, Any]] = []
    applied = 0
    for article in articles:
        title = article.get("title", "")
        params = {
            "blog_id": resolved_blog_id,
            "title": title,
            "body_html": article.get("body_html", ""),
            "summary": article.get("summary", ""),
            "tags": article.get("tags") or [],
            "is_published": True,
        }
        if article.get("author_name"):
            params["author_name"] = article["author_name"]
        try:
            res = router.execute(create_article_cap, params)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "blog_starter create raised for %s: %s",
                title, exc,
            )
            results.append({
                "title": title,
                "ok": False,
                "error": f"adapter_raise: {exc}",
                "article_id": None,
            })
            _record(
                title=title, success=False,
                error=str(exc), store_id=store_id,
                spec=article,
            )
            continue
        ok = bool(getattr(res, "ok", False))
        err = getattr(res, "error", None)
        article_id = None
        if ok:
            data = getattr(res, "data", {}) or {}
            article_payload = data.get("article") or {}
            article_id = article_payload.get("id")
            applied += 1
        results.append({
            "title": title,
            "ok": ok,
            "error": None if ok else str(err or "rejected"),
            "article_id": article_id,
        })
        _record(
            title=title, success=ok,
            error=None if ok else str(err or "rejected"),
            store_id=store_id, spec=article,
        )

    return {
        "applied_count": applied,
        "results": results,
        "blog_id": resolved_blog_id,
        "blog_title": resolved_blog_title,
    }


# ── Helpers ───────────────────────────────────────────────────


def _resolve_blog(
    *,
    router: Any,
    create_blog_cap: Any | None,
    blog_id: str | None,
    blog_title: str | None,
) -> tuple[str | None, str | None]:
    """If a blog_id is supplied, use it. Otherwise create
    a new blog and return its id.
    """
    desired_title = (
        (blog_title or "").strip() or _DEFAULT_BLOG_TITLE
    )
    if blog_id and blog_id.strip():
        return blog_id.strip(), desired_title
    if create_blog_cap is None:
        return None, desired_title
    try:
        res = router.execute(
            create_blog_cap,
            {"title": desired_title},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "blog_starter create_blog raised: %s", exc,
        )
        return None, desired_title
    if not getattr(res, "ok", False):
        return None, desired_title
    data = getattr(res, "data", {}) or {}
    blog = data.get("blog") or {}
    return blog.get("id"), desired_title


def _record(
    *,
    title: str,
    success: bool,
    error: str | None,
    store_id: str | None,
    spec: dict[str, Any],
) -> None:
    params: dict[str, Any] = {
        "title": title,
        "tag_count": len(spec.get("tags") or []),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_blog_article",
            capability="SHOPIFY_CREATE_ARTICLE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "title": title,
                "tag_count": len(spec.get("tags") or []),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "blog_starter record_writeback raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "blog_starter router import failed: %s", exc,
        )
        return None


def _resolve_cap(name: str) -> Any | None:
    try:
        from core.adapters.base import Capability
        return getattr(Capability, name, None)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "blog_starter cap resolve failed for %s: %s",
            name, exc,
        )
        return None
