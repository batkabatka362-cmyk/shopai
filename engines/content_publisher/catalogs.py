"""Curated niche → blog-post-candidate catalog.

5 niches × 10 templates each = 50 SEO-targeted blog post seeds.
Each template carries enough structure to be publishable as a
DRAFT article with minimal operator editing:

  title:        SEO-friendly H1 (Google snippet ~55-65 chars)
  meta_excerpt: 150-160 char summary for search snippets
  body_html:    fully-formed HTML body with H2 sub-sections,
                paragraphs, bullet lists
  tags:         3-5 SEO tags
  keyword:      primary search keyword the post targets

These templates are deterministic baselines. A future revision
can swap in LLM-generated bodies; the substrate stays the same.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BlogCandidate:
    title: str
    meta_excerpt: str
    body_html: str
    keyword: str
    tags: list[str] = field(default_factory=list)


SUPPORTED_NICHES = (
    "beauty", "fashion", "home", "tech", "food",
)


def _body(intro: str, sections: list[tuple[str, str]]) -> str:
    """Build a standardised body_html with H2 sections."""
    parts = [f"<p>{intro}</p>"]
    for h2, body in sections:
        parts.append(f"<h2>{h2}</h2>")
        parts.append(f"<p>{body}</p>")
    parts.append(
        "<p><em>Found this helpful? Browse our collection for "
        "everything mentioned above.</em></p>"
    )
    return "\n".join(parts)


_BEAUTY = [
    BlogCandidate(
        "5-Step Korean Skincare Routine for Glass Skin",
        "Learn the simplified Korean skincare routine that delivers radiant, glass-like skin without breaking the bank.",
        _body(
            "Glass skin — that lit-from-within Korean beauty look — is achievable with five thoughtfully chosen steps. Here's the streamlined routine that actually works.",
            [
                ("Step 1: Double Cleanse", "Start with an oil cleanser to dissolve makeup + sunscreen, follow with a gentle foam cleanser to lift residue. Twice-daily routine."),
                ("Step 2: Hydrating Toner", "Pat (don't wipe) a rose-hip or hyaluronic-acid toner with cool hands. Three thin layers beats one heavy layer."),
                ("Step 3: Serum + Essence", "Vitamin C in the morning for brightness, niacinamide at night for pore refinement. Layer thinnest-to-thickest."),
                ("Step 4: Lock-in Moisturizer", "Lightweight gel cream during the day, richer cream at night. Look for ceramides + fatty acids."),
                ("Step 5: SPF (morning only)", "Korean light-fluid SPF50 PA++++ — the non-negotiable step. Sun damage undoes everything above."),
            ],
        ),
        "korean skincare routine",
        ["skincare", "korean-beauty", "routine", "glass-skin", "seo"],
    ),
    BlogCandidate(
        "Vitamin C Serum: Does It Really Brighten Skin?",
        "The science behind vitamin C serum and how to choose the right concentration for your skin type.",
        _body(
            "Vitamin C serum promises brighter, more even-toned skin. Here's what the research actually says and how to pick one that works for your routine.",
            [
                ("How Vitamin C Works", "L-ascorbic acid neutralises free radicals from UV exposure + pollution, which is what causes dullness and dark spots over time."),
                ("Which Concentration?", "10-15% L-ascorbic acid is the sweet spot. Higher concentrations (20%+) can irritate without delivering proportionally better results."),
                ("When to Apply", "Morning, after toner + before moisturizer. Wait 60-90 seconds for absorption before the next layer."),
                ("Pair With Sunscreen", "Vitamin C amplifies SPF protection — they're a power couple. Never skip SPF on a vitamin C morning."),
                ("Storage Matters", "Light + heat degrade L-ascorbic acid. Store in a cool, dark place. If your serum turns brown, it's oxidized — toss it."),
            ],
        ),
        "vitamin c serum benefits",
        ["skincare", "vitamin-c", "serum", "brightening", "seo"],
    ),
    BlogCandidate(
        "How to Build a 5-Minute Daily Skincare Routine",
        "Short on time? Here's a dermatologist-approved 5-minute routine that covers all the essentials.",
        _body(
            "You don't need 12 steps to see real skin improvements. This 5-minute routine hits every essential function: cleanse, treat, hydrate, protect.",
            [
                ("Minute 1: Cleanse", "Gentle gel or cream cleanser. Massage 30 seconds — that's where the real cleaning happens."),
                ("Minute 2: Tone", "One-pump pat of hydrating toner. Skip alcohol-based astringents — they strip your barrier."),
                ("Minute 3: Treat", "One serum. Pick based on your top concern: vitamin C (brightness), niacinamide (pores), or hyaluronic acid (hydration)."),
                ("Minute 4: Moisturize", "Pea-sized amount, work outward from the center of your face."),
                ("Minute 5: SPF (AM only)", "Two-finger-length stripe spread evenly. The single highest-impact step in the routine."),
            ],
        ),
        "5 minute skincare routine",
        ["skincare", "routine", "beginner", "minimalist", "seo"],
    ),
    BlogCandidate(
        "Are Sheet Masks Worth It? An Honest Review",
        "We tested sheet masks for 30 days. Here's what actually works and what's a marketing gimmick.",
        _body(
            "Sheet masks line the checkout of every beauty store. Are they a real skincare upgrade or single-use waste?",
            [
                ("What Sheet Masks Actually Do", "They occlude the skin, forcing serum to absorb instead of evaporating. The mask itself is mostly delivery vehicle."),
                ("When They Work Best", "Pre-event (the next morning) — you'll see plumpness for 12-24 hours. Daily use is overkill and the cost-benefit isn't there."),
                ("Ingredients Worth Paying For", "Hyaluronic acid, niacinamide, peptides. Skip masks marketed solely on 'natural' or 'organic' — those terms aren't regulated."),
                ("DIY Alternative", "Damp face cloth + your usual serum can do 80% of the job at 5% of the cost."),
            ],
        ),
        "are sheet masks worth it",
        ["skincare", "sheet-mask", "review", "seo"],
    ),
    BlogCandidate(
        "The Best Order to Apply Skincare Products",
        "Skincare layering is the difference between effective and useless. Here's the simple rule that always works.",
        _body(
            "The rule: thinnest-to-thickest. But there are nuances. Here's the complete order from cleansing to SPF.",
            [
                ("Rule of Thumb", "Water-based products go on first (they need to absorb), oil-based products go on top (they create a seal)."),
                ("The Universal Order", "Cleanser → Toner → Essence → Serum → Eye Cream → Moisturizer → SPF (AM) / Sleeping mask (PM)."),
                ("Wait Times", "30-60 seconds between layers. The product needs to absorb before the next one creates a barrier."),
                ("Common Mistakes", "Applying retinol BEFORE moisturizer in sensitive skin (sandwich it). SPF as last step in AM, not first."),
            ],
        ),
        "order to apply skincare",
        ["skincare", "routine", "layering", "seo"],
    ),
    BlogCandidate(
        "Niacinamide Explained: The Underrated Power Ingredient",
        "Why niacinamide deserves a spot in every skincare routine — and which concentration is right for you.",
        _body(
            "Vitamin C gets the marketing dollars but niacinamide is the quiet workhorse. It tackles pores, oil, and uneven tone all at once.",
            [
                ("What It Is", "Vitamin B3 in topical form. It strengthens the skin barrier and regulates sebum production."),
                ("Best Concentrations", "5% for daily use, 10% for visible pore minimization. Higher doesn't mean better — irritation kicks in above 10%."),
                ("What It Won't Do", "Replace SPF, cure cystic acne, or work overnight. Most users see results at 6-8 weeks of consistent use."),
                ("Layering With Other Acids", "Safe with vitamin C, AHA/BHA, and retinol. Just space them throughout the day if your skin is sensitive."),
            ],
        ),
        "niacinamide benefits",
        ["skincare", "niacinamide", "ingredient", "seo"],
    ),
    BlogCandidate(
        "How Often Should You Actually Exfoliate?",
        "Over-exfoliation is the most common skincare mistake. Here's the right frequency for every skin type.",
        _body(
            "Glowing skin requires exfoliation — but too much causes the exact dullness you're trying to fix. Find your sweet spot.",
            [
                ("Dry / Sensitive Skin", "Once a week. PHA (polyhydroxy acid) is gentler than glycolic."),
                ("Normal / Combination", "Twice a week. Alternate AHA and BHA to target different concerns."),
                ("Oily / Acne-Prone", "Three times a week. Salicylic acid (BHA) clears pores at this frequency."),
                ("Signs You're Overdoing It", "Tightness, redness, stinging when applying serum, increased breakouts."),
            ],
        ),
        "how often to exfoliate",
        ["skincare", "exfoliation", "aha", "bha", "seo"],
    ),
    BlogCandidate(
        "Affordable Skincare That Actually Works",
        "You don't need to spend $200 on a serum. Here are budget-friendly products that deliver real results.",
        _body(
            "Effective skincare doesn't require a luxury price tag. These pharmacy-aisle staples are dermatologist favourites.",
            [
                ("Cleanser Under $15", "CeraVe Hydrating Cleanser or COSRX Low-pH Good Morning Gel. Both gentle, both effective."),
                ("Serum Under $20", "The Ordinary Niacinamide 10% or Naturium Vitamin C 12%. Same actives as luxury brands at 1/4 the price."),
                ("Moisturizer Under $20", "Vanicream Daily Facial or CeraVe PM Facial Moisturizing Lotion."),
                ("SPF Under $20", "EltaMD UV Clear or Cetaphil Sheer Mineral. The brands dermatologists actually use."),
            ],
        ),
        "affordable skincare",
        ["skincare", "budget", "drugstore", "seo"],
    ),
    BlogCandidate(
        "Retinol for Beginners: Where to Start",
        "Retinol is the gold-standard anti-aging ingredient. Here's how to introduce it without irritation.",
        _body(
            "Retinol increases cell turnover, smooths fine lines, and clears clogged pores — but starting wrong causes a week of peeling. Here's the gentle introduction.",
            [
                ("Start Low", "0.25% retinol or retinaldehyde. Anything stronger is overkill for week one."),
                ("Start Slow", "Twice per week for the first month. Increase to 3x in month two, daily by month four."),
                ("The Sandwich Method", "Moisturizer → wait → retinol → wait → moisturizer. This buffer reduces irritation by 50%."),
                ("Non-Negotiable: SPF", "Retinol thins the outer skin layer — sun damage hits faster. SPF50+ daily is mandatory."),
            ],
        ),
        "retinol for beginners",
        ["skincare", "retinol", "anti-aging", "beginner", "seo"],
    ),
    BlogCandidate(
        "How to Read Skincare Ingredient Labels",
        "Decode the back of the bottle and avoid marketing tricks with this simple guide.",
        _body(
            "Skincare ingredient lists follow strict rules. Once you know how to read them, you'll spot marketing gimmicks immediately.",
            [
                ("Order Matters", "Ingredients are listed by concentration, highest first. Active ingredients usually appear in the middle of the list."),
                ("The 1% Line", "Ingredients listed after preservatives (look for phenoxyethanol) are present at <1%. 'Featured' ingredients here are mostly marketing."),
                ("Watch Out For", "'Fragrance' or 'parfum' on sensitive-skin formulas — it's the #1 irritant. Drying alcohols (alcohol denat, isopropyl alcohol) as the first or second ingredient."),
                ("Don't Be Scared Of", "Long chemical names. 'Sodium hyaluronate' is just hyaluronic acid. 'Tocopherol' is vitamin E. Plain English ≠ better."),
            ],
        ),
        "how to read skincare labels",
        ["skincare", "ingredients", "education", "seo"],
    ),
]


_FASHION = [
    BlogCandidate(
        "How to Build a Capsule Wardrobe in 10 Pieces",
        "Less is more. Here's the minimalist capsule wardrobe formula that works for every season.",
        _body(
            "A capsule wardrobe gives you 30+ outfits from 10 well-chosen pieces. Here's the formula that fashion editors swear by.",
            [
                ("The 10-Piece Foundation", "2 jeans (one light, one dark), 1 trouser, 2 white tees, 1 button-down, 1 sweater, 1 blazer, 1 dress, 1 jacket."),
                ("Stick to a Neutral Palette", "Black, navy, cream, beige. Add ONE colour as your signature (rust, olive, burgundy)."),
                ("Quality Over Quantity", "Cost-per-wear math beats fast-fashion volume. A $200 trouser worn 100 times = $2/wear. A $30 trend piece worn 3 times = $10/wear."),
                ("Seasonal Swaps", "Keep the foundation 8 pieces year-round. Swap the jacket and 1 layer per season."),
            ],
        ),
        "capsule wardrobe essentials",
        ["fashion", "capsule-wardrobe", "minimalism", "seo"],
    ),
    BlogCandidate(
        "Linen Care: Wash, Dry, and Store the Right Way",
        "Linen lasts decades when cared for properly. Here's how to keep yours looking new.",
        _body(
            "Linen is a long-term investment fabric. Treat it well and it'll outlive every other piece in your closet.",
            [
                ("Wash in Cold", "Always cold water on gentle cycle. Hot water shrinks linen and breaks down the fibers."),
                ("Skip the Dryer", "Air dry flat or hang. The dryer is linen's enemy — it both shrinks and creates permanent creases."),
                ("Iron While Damp", "If you want crisp linen, iron when it's slightly damp at high heat. Steam-only for a softer hand."),
                ("Store Properly", "Hang trousers and dresses, fold tops with tissue paper between layers. Cedar (not mothballs) for moth prevention."),
            ],
        ),
        "how to wash linen",
        ["fashion", "linen", "care", "seo"],
    ),
    BlogCandidate(
        "Dressing for Your Body Shape: A Practical Guide",
        "Forget rules. Here's how to dress to feel your best at any body shape.",
        _body(
            "Body-shape guides usually feel restrictive. This one focuses on what feels good, not what 'flatters.'",
            [
                ("Find Your Waist", "If you have one, defining it elongates the torso. If you don't, embrace a column silhouette — equally chic."),
                ("Vertical Lines = Length", "Buttons, plackets, vertical pinstripes all add visual height regardless of shape."),
                ("Tailoring Is Magic", "A $40 tailoring job on a $50 jacket beats a $300 off-the-rack jacket every time. Hem, taper, dart."),
                ("Comfort First", "If you keep adjusting it, you'll never wear it. Easy-fit pieces in great fabric beat structured discomfort."),
            ],
        ),
        "how to dress your body shape",
        ["fashion", "styling", "body-shape", "seo"],
    ),
    BlogCandidate(
        "The Difference Between Mass-Market and Slow Fashion",
        "Why a $40 t-shirt costs $40 and what 'slow fashion' actually means.",
        _body(
            "Fast fashion is fast for a reason — and that reason isn't good for anyone. Here's what the slow fashion alternative actually delivers.",
            [
                ("Fabric Quality", "Slow fashion uses 200+ GSM cotton vs fast fashion's 120 GSM. The difference: 4-5 years of wear vs 4-5 washes."),
                ("Construction", "Reinforced seams, French seams, button-stitched buttons. Look at the inside of any garment to gauge quality."),
                ("Labour Standards", "Slow fashion brands publish their factories. If they don't say where the garment is made, that's the answer."),
                ("Cost Math", "A $120 shirt worn weekly for 5 years = $0.46/wear. A $20 fast fashion shirt worn 8 times before falling apart = $2.50/wear."),
            ],
        ),
        "slow fashion explained",
        ["fashion", "slow-fashion", "ethical", "sustainability", "seo"],
    ),
    BlogCandidate(
        "How to Match Belts, Bags, and Shoes",
        "The classic rule of three: do you have to match? Modern styling says no — but here's when matching wins.",
        _body(
            "The old rule said belt = bag = shoes. Modern styling is more nuanced. Here's when to match and when to break the rule.",
            [
                ("Old Rule", "Match leather tones across belt, bag, and shoes. Brown leather pieces only with other brown leather."),
                ("Modern Approach", "Match TONE (warm with warm, cool with cool) not exact colour. A cognac belt works with a chocolate bag if both are warm-toned."),
                ("When to Break Rules", "Casual outfits can mix entirely. A canvas tote with leather sneakers feels intentional, not sloppy."),
                ("The One Anchor", "Pick one piece to be your style anchor (usually shoes) and let everything else complement, not duplicate."),
            ],
        ),
        "match belt bag shoes",
        ["fashion", "accessories", "styling", "seo"],
    ),
    BlogCandidate(
        "Caring for Cashmere: Make It Last 10+ Years",
        "Cashmere is an investment. Here's how to keep yours soft and shape-retaining for a decade.",
        _body(
            "A $200 cashmere sweater can last 10 years with proper care — that's $20/year. Skip these care steps and you've thrown money in the wash.",
            [
                ("Hand Wash Only", "Lukewarm water, baby shampoo (not detergent). 5-minute soak, gentle squeeze (never wring), rinse twice."),
                ("Lay Flat to Dry", "Roll in a clean towel to remove water, then lay flat on a fresh towel. Never hang — it stretches out the shoulders."),
                ("Pilling Is Normal", "Use a cashmere comb to remove pills. NEVER pull them off with your fingers (you weaken the fibres)."),
                ("Storage", "Fold (don't hang) and use cedar blocks. Moths LOVE cashmere — and one moth can ruin a whole drawer."),
            ],
        ),
        "how to care for cashmere",
        ["fashion", "cashmere", "care", "seo"],
    ),
    BlogCandidate(
        "Jewelry 101: How to Layer Necklaces",
        "Layered necklaces look effortless when done right — and like a tangled mess when done wrong.",
        _body(
            "The trick to layered necklaces isn't more chains, it's the right LENGTH differences. Here's the formula.",
            [
                ("3-Length Rule", "Choker (14-16\"), princess (18-20\"), and matinee (22-24\"). At least 2 inches between layers to prevent tangling."),
                ("Style Mix", "Mix delicate chains with one statement piece. All-delicate looks washed out, all-statement is too much."),
                ("Metal Mixing Works", "Gold + silver is fine if done with intention. Pick a 'lead' metal (heavier presence) and a 'support' (one accent)."),
                ("Anti-Tangle Tip", "Connect the clasps when you take them off. Saves 10 minutes of detangling the next morning."),
            ],
        ),
        "how to layer necklaces",
        ["fashion", "jewelry", "styling", "seo"],
    ),
    BlogCandidate(
        "Shoe Materials: Real vs Vegan Leather",
        "Vegan leather has come a long way. Here's an honest comparison with traditional leather.",
        _body(
            "Real leather lasts 10+ years. Cheap vegan leather lasts 6 months. But premium vegan options (mushroom, cactus, apple) are closing the gap.",
            [
                ("Real Leather Pros", "Develops a patina, breathes, lasts decades, repairable. Cons: ethical concerns, water sensitivity, higher initial cost."),
                ("PU Vegan Pros", "Affordable, animal-free, consistent finish. Cons: cracks within 1-3 years, doesn't breathe, ends up in landfill."),
                ("New-Gen Vegan", "Mushroom leather (Mylo), cactus leather (Desserto), apple leather. Performance approaching real leather, plant-based."),
                ("Cost-Per-Wear", "A $300 leather boot worn 5 years = $60/year. A $80 PU boot worn 1 year = $80/year. Real leather often wins."),
            ],
        ),
        "real vs vegan leather",
        ["fashion", "leather", "vegan", "comparison", "seo"],
    ),
    BlogCandidate(
        "The Most Versatile Pieces to Invest In",
        "Build a wardrobe that works harder. These 5 pieces deserve your wardrobe-investment budget.",
        _body(
            "Most wardrobes are 80% pieces worn 20% of the time. Flip that ratio by investing in these high-versatility staples.",
            [
                ("White Button-Down", "Casual with jeans, professional with trousers, dressy under a blazer. Cotton-poplin lasts; silk needs babying."),
                ("Black Trouser", "High-rise, slight taper. Works for office, evening, errands. Look for wool or wool-blend for year-round wear."),
                ("Trench Coat", "Khaki or navy. Transitional season hero. Belted for shape, unbelted for casual. Match with everything."),
                ("Leather Loafers", "Black or oxblood. Dress them up with trousers, down with jeans + ankle socks. Comfortable AND versatile is rare."),
                ("Cashmere Crewneck", "Layer under blazers, alone with jeans, over a button-down. Black or camel — colour doesn't add versatility."),
            ],
        ),
        "wardrobe investment pieces",
        ["fashion", "wardrobe", "investment", "essentials", "seo"],
    ),
    BlogCandidate(
        "How to Style Wide-Leg Trousers",
        "Wide-leg trousers are back. Here's how to wear them without looking like you got lost in your fabric.",
        _body(
            "Wide-leg trousers can elongate or overwhelm depending on styling. Here's the rule of proportions that always works.",
            [
                ("Tuck The Top", "Fitted, tucked-in top + wide-leg bottom = balanced silhouette. Loose top + wide pants = puddle."),
                ("Footwear Choice", "Heels (any height) elongate the line. Sneakers work for casual but flat shoes need a slightly cropped pant."),
                ("The Cropped Hem", "If you're under 5'7, look for ankle-grazer wide-leg, not floor-length. They visually add 3 inches."),
                ("High-Rise Always", "Wide-leg trousers need a defined waist. Low-rise versions look like pajamas."),
            ],
        ),
        "how to style wide leg trousers",
        ["fashion", "trousers", "styling", "seo"],
    ),
]


_HOME = [
    BlogCandidate(
        "How to Create a Cozy Reading Nook in Any Space",
        "You don't need a library or a window seat. Here's how to carve out a cozy reading nook anywhere.",
        _body(
            "A reading nook is more about ambience than square footage. Here's the formula that works in studios as well as houses.",
            [
                ("Choose The Spot", "Any corner that gets natural light during your reading time. Even a 4x4 ft corner is enough."),
                ("Comfortable Seat", "A reading chair doesn't need to be expensive. A floor cushion + a wall to lean against beats a bad chair."),
                ("Soft Lighting", "Floor lamp with warm bulb (2700K). Reading is harder than people realize — your eyes need 800-1000 lumens close by."),
                ("The Side Surface", "Small side table for tea, glasses, current book. Doesn't need to be matched to your decor."),
                ("Layer Textures", "Blanket + textured cushion + nearby plant. Three layers of texture transforms any spot into a 'nook.'"),
            ],
        ),
        "cozy reading nook ideas",
        ["home", "decor", "reading-nook", "cozy", "seo"],
    ),
    BlogCandidate(
        "Indoor Plants for Beginners: 7 Hard-to-Kill Picks",
        "Want a leafy home but kill every plant you touch? Start with these seven that thrive on neglect.",
        _body(
            "Most plant failures aren't about your green thumb — they're about plant choice. These seven are practically indestructible.",
            [
                ("Snake Plant", "Tolerates low light, infrequent watering, and varying temperatures. Water every 2-3 weeks. Almost impossible to kill."),
                ("Pothos", "Trailing vine that thrives in any light. Water when topsoil is dry. Cuttings root in water — one plant becomes many."),
                ("ZZ Plant", "Glossy leaves, requires almost no light or water. Water every 3-4 weeks. The 'forgot you exist' plant."),
                ("Chinese Evergreen", "Tolerates low light, occasional underwatering. Air-purifying bonus."),
                ("Cast Iron Plant", "The name says it all. Survives offices, drafty rooms, and inconsistent watering."),
                ("Spider Plant", "Produces babies you can propagate. Bright indirect light + weekly water."),
                ("Rubber Plant", "Striking statement plant. Once-a-week water, indirect light. Wipes down leaves bring out the gloss."),
            ],
        ),
        "indoor plants for beginners",
        ["home", "plants", "beginner", "low-maintenance", "seo"],
    ),
    BlogCandidate(
        "Small Kitchen Organization Hacks That Actually Work",
        "Maximize a tiny kitchen with these tested organization strategies — no major renovations required.",
        _body(
            "Small kitchens require ruthless prioritization. These hacks come from real users who've squeezed function out of 80 sq ft.",
            [
                ("Vertical Storage", "Magnetic spice strips inside cabinet doors, over-the-sink dish racks, wall-mounted utensil rails. Your cabinets are bigger than you think."),
                ("Lazy Susan Everywhere", "In corner cabinets, under the sink, on top of the fridge. Anywhere 'dead corner' becomes accessible."),
                ("Drawer Dividers", "Bamboo organizers in your utensil drawer transform a junk pile into a clear inventory."),
                ("Open Shelving Above Counter", "Frees up cabinet space for less-used items. Display the daily-use mugs and bowls."),
                ("One-In-One-Out Rule", "For every new gadget, donate an old one. Small kitchens have no room for duplicates."),
            ],
        ),
        "small kitchen organization",
        ["home", "kitchen", "organization", "small-space", "seo"],
    ),
    BlogCandidate(
        "How to Style Throw Pillows on a Sofa",
        "Throw pillows can transform a sofa or make it look like a discount furniture store. Here's the formula.",
        _body(
            "Throw pillow styling follows a few simple rules. Most people break all of them. Here's the cheat sheet.",
            [
                ("Odd Numbers Look Better", "3 or 5 pillows on a 3-seat sofa. 2 on a loveseat. Even numbers look symmetrical and static."),
                ("Mix Sizes", "Layer a 24\" euro behind a 20\" square behind an 18\" lumbar. Same-size pillows lined up = boring."),
                ("Color Rule of Three", "Pick 3 colours from your existing room and use them across pillows. More colours = chaos."),
                ("Texture Mix", "Smooth velvet + nubby boucle + textured linen. Same-texture pillows feel flat."),
                ("Down vs Foam", "Down-filled pillows look styled even when slumped. Foam looks rigid and cheap. Invest in the inserts."),
            ],
        ),
        "how to style throw pillows",
        ["home", "decor", "styling", "pillows", "seo"],
    ),
    BlogCandidate(
        "The Perfect Cup of Coffee at Home — No Espresso Machine Required",
        "Skip the $1000 espresso machine. Here's how to brew café-quality coffee with $50 of equipment.",
        _body(
            "Most cafés use the same beans you can buy. The difference is the brewing technique. Here's how to match café quality at home.",
            [
                ("Buy Whole Beans", "Pre-ground coffee loses 60% of its flavor within an hour. A $30 burr grinder is the biggest single upgrade you can make."),
                ("Water Temp 195-205°F", "Boiling water burns coffee. Off-the-boil (let kettle sit 30 seconds after boil) hits the sweet spot."),
                ("Coffee:Water Ratio", "1:16 by weight for a balanced cup. Use a kitchen scale. Volume measurements are too inconsistent."),
                ("Method: Pour-Over", "A $20 ceramic dripper + paper filters produces better coffee than 90% of espresso machines. Bloom 30 seconds, slow pour for 3 minutes."),
                ("Storage", "Beans in an airtight container away from light. Buy what you'll drink in 2 weeks."),
            ],
        ),
        "how to brew coffee at home",
        ["home", "coffee", "brewing", "diy", "seo"],
    ),
    BlogCandidate(
        "How to Choose Bedding That'll Actually Help You Sleep",
        "The right bedding can improve sleep quality. Here's what matters and what's marketing.",
        _body(
            "Bedding marketing is full of buzzwords. Here's what actually matters for sleep quality, based on sleep research.",
            [
                ("Material Choice", "100% cotton, linen, or bamboo for breathability. Polyester traps heat — skip it unless allergies."),
                ("Thread Count Isn't Everything", "200-400 is plenty. Anything above 600 is marketing — manufacturers count plies, not threads."),
                ("Weight of The Duvet", "5-10% of your body weight is the comfort sweet spot. Heavier feels secure; lighter feels free."),
                ("Pillow Firmness", "Side sleepers: firm. Back sleepers: medium. Stomach sleepers: thin/soft. Replace pillows every 18-24 months."),
                ("The Sheet Test", "If new sheets feel rough, they have starch finishings. Two cold washes removes it — the softness improves dramatically."),
            ],
        ),
        "how to choose bedding for sleep",
        ["home", "bedding", "sleep", "seo"],
    ),
    BlogCandidate(
        "Modern Minimalist Decor on a Tight Budget",
        "Minimalist style looks expensive but doesn't have to be. Here's how to nail the look without the price tag.",
        _body(
            "Minimalist decor is about restraint, not cost. Here are budget-friendly ways to achieve the look.",
            [
                ("Declutter First", "Remove 30% of what's on your surfaces. Most minimalist rooms aren't expensive — they're empty."),
                ("Neutral Palette", "Stick to white, beige, and one accent (black or charcoal). Mixed colours sabotage minimalism."),
                ("Quality Over Quantity", "One $80 ceramic vase beats five $15 trinkets. Empty space is a design choice."),
                ("Natural Materials", "Wood, linen, stone, ceramic. Three different naturals beat one luxe material."),
                ("Hide The Tech", "Cable management + putting devices away when not in use transforms a room. Visible tech ruins minimalism."),
            ],
        ),
        "minimalist decor on a budget",
        ["home", "minimalist", "decor", "budget", "seo"],
    ),
    BlogCandidate(
        "How Often to Wash Your Linens (and Why It Matters)",
        "Skipped washing your sheets last week? Here's how often things should ACTUALLY get cleaned.",
        _body(
            "Most people don't wash their linens often enough. Here's the schedule that keeps things hygienic without overdoing it.",
            [
                ("Sheets: Weekly", "You spend 1/3 of your life in them. Skin cells, sweat, and dust mites accumulate fast."),
                ("Pillowcases: Twice Weekly", "Your face is on them 7-8 hours nightly. Especially important if you have acne."),
                ("Duvet Cover: Every 2-4 Weeks", "Less skin contact but still needs regular cleaning. Pull the duvet out of the cover before washing."),
                ("Pillows + Duvet Inserts: Twice Yearly", "Wash them at home if they're machine-safe, or take to dry cleaning."),
                ("Mattress: Vacuum Monthly", "Use the upholstery attachment. Spot clean stains immediately with cold water."),
            ],
        ),
        "how often to wash sheets",
        ["home", "cleaning", "bedding", "linens", "seo"],
    ),
    BlogCandidate(
        "Best Houseplants for Air Purification",
        "Some plants actively clean indoor air. Here are the most effective options backed by NASA research.",
        _body(
            "NASA's Clean Air Study identified plants that remove indoor pollutants. Here are the top performers + how many you need.",
            [
                ("Snake Plant", "Removes formaldehyde and benzene. 1-2 plants per 100 sq ft for noticeable air quality improvement."),
                ("English Ivy", "Removes mold spores and benzene. Best as a hanging plant in living spaces."),
                ("Spider Plant", "Removes formaldehyde from off-gassing furniture. Great for new homes/apartments."),
                ("Peace Lily", "Removes ammonia, benzene, formaldehyde, and trichloroethylene. The all-rounder."),
                ("Areca Palm", "Acts as a natural humidifier + removes toluene and xylene. Best in bright indirect light."),
            ],
        ),
        "air purifying houseplants",
        ["home", "plants", "air-quality", "wellness", "seo"],
    ),
    BlogCandidate(
        "How to Make Your Home Smell Naturally Wonderful",
        "Skip the artificial sprays. Here's how to make your home smell amazing using natural methods.",
        _body(
            "Synthetic air fresheners can trigger headaches and allergies. These natural alternatives are more effective and pleasant.",
            [
                ("Stovetop Simmer", "Citrus peels + cinnamon + cloves in 4 cups of water. Simmer for 1-2 hours. Refresh weekly."),
                ("Essential Oil Diffusers", "Lavender for relaxation, citrus for energy, peppermint for focus. 5-10 drops per session."),
                ("Beeswax Candles", "Burn cleaner than soy or paraffin. Natural honey scent without added fragrance."),
                ("Open Windows Daily", "Even 10 minutes of cross-ventilation transforms indoor air. Free + effective."),
                ("Plants Help", "Lavender, mint, and rosemary plants release fragrance constantly. Bonus: cooking herbs."),
            ],
        ),
        "natural home fragrance",
        ["home", "fragrance", "natural", "wellness", "seo"],
    ),
]


_TECH = [
    BlogCandidate(
        "USB-C Explained: Why It's Everywhere Now",
        "USB-C charges your laptop, phone, and tablet — finally one cable. Here's why it took over.",
        _body(
            "USB-C is winning the cable wars. Here's what it does, why it matters, and how to pick the right one.",
            [
                ("Universal Compatibility", "Charges laptops (100W+), phones, tablets, and Nintendo Switch. One cable for everything."),
                ("Reversible Design", "No more flipping the plug three times. The biggest UX win of any cable design ever."),
                ("Watch The Spec", "Not all USB-C cables are equal. Look for 'USB 3.2' or 'Thunderbolt' for fast data. 'USB-PD' for fast charging."),
                ("Power Delivery (PD)", "PD-certified chargers communicate with devices for safe high-wattage charging. A non-PD cable maxes out at 15W."),
            ],
        ),
        "usb c explained",
        ["tech", "usb-c", "charging", "guide", "seo"],
    ),
    BlogCandidate(
        "Wireless Earbuds: ANC vs Non-ANC — Which Do You Need?",
        "Active noise cancellation costs more. Here's when it's worth it and when standard buds work fine.",
        _body(
            "ANC adds $50-100 to wireless earbuds. Most users don't actually need it. Here's how to tell.",
            [
                ("When ANC Matters", "Plane travel, open-office work, loud commutes. ANC cuts environmental noise by 20-30dB."),
                ("When Standard Buds Win", "Walking outdoors (you need to hear traffic), conversations, exercise. ANC creates a 'pressure' feeling some find uncomfortable."),
                ("Transparency Mode", "ANC buds often include transparency mode for situational awareness. The best of both worlds."),
                ("Battery Trade-off", "ANC reduces battery life by 30-40%. If you're a heavy-listening user, factor this in."),
            ],
        ),
        "anc vs non anc earbuds",
        ["tech", "audio", "earbuds", "comparison", "seo"],
    ),
    BlogCandidate(
        "Mechanical Keyboard Switches Explained",
        "Linear, tactile, clicky — what's the difference and how do you choose?",
        _body(
            "Mechanical keyboard switches are personal. Here's how each type feels and which fits your typing style.",
            [
                ("Linear (Red switches)", "Smooth, no bump, no click. Best for gaming. Quiet enough for shared spaces."),
                ("Tactile (Brown switches)", "Bump in the middle of the press, no click. Best all-arounder for typing + light gaming."),
                ("Clicky (Blue switches)", "Loud click + tactile bump. Very satisfying but annoying to coworkers. Headphones not enough — they hear it across the room."),
                ("Silent variants", "Linear and tactile variants with rubber dampeners. 80% of the feel, 50% of the noise."),
                ("Try Before You Buy", "Switch testers ($15-20) let you feel each type. Worth it before a $150 keyboard purchase."),
            ],
        ),
        "mechanical keyboard switches",
        ["tech", "keyboard", "mechanical", "switches", "seo"],
    ),
    BlogCandidate(
        "Smart Home Starter Pack: What's Actually Useful",
        "Smart home tech is full of gimmicks. Here are the 5 devices that actually improve daily life.",
        _body(
            "After 5 years of smart home reviews, these are the only 5 categories worth the money.",
            [
                ("Smart Plugs", "$10-15 each. Schedule lamps, coffee maker, holiday lights. The single best ROI smart device."),
                ("Smart Speaker", "Alexa or Google Home. Hands-free timer, music, news, controlling other smart devices."),
                ("Smart Thermostat", "$150-250. Pays for itself in 2 years through energy savings. Programmable + learning."),
                ("Smart Doorbell", "Video doorbell with motion alerts. Security + package monitoring. Skip the subscription fees if possible."),
                ("Smart Light Bulbs", "For 2-3 rooms only — going whole-house gets pricey fast. Focus on bedroom + living room."),
            ],
        ),
        "smart home starter pack",
        ["tech", "smart-home", "iot", "seo"],
    ),
    BlogCandidate(
        "Webcam Quality: When to Upgrade From Built-In",
        "Your laptop's webcam is probably bad. Here's when an external webcam is worth it.",
        _body(
            "Laptop webcams haven't improved much in 10 years. If you're on video calls daily, an external webcam is a quick upgrade.",
            [
                ("Built-In Limits", "Most laptop webcams are 720p with weak low-light performance. Fine for casual calls, bad for professional impressions."),
                ("External Webcam Benefits", "1080p, better low-light, autofocus, replaceable lens. $40-100 upgrade transforms call quality."),
                ("Lighting > Webcam", "A $20 LED ring light improves call quality more than a $200 webcam upgrade. Light first, then upgrade hardware."),
                ("Mirrorless Camera as Webcam", "If you have a mirrorless camera, an HDMI capture card ($30) makes it a webcam. Best image quality, free if you already have the camera."),
            ],
        ),
        "external webcam upgrade",
        ["tech", "webcam", "video-call", "seo"],
    ),
    BlogCandidate(
        "Battery Life Hacks for Your Phone",
        "Extend your phone's battery life by hours with these simple settings adjustments.",
        _body(
            "Modern phones have 10-30% more battery life available — most users just don't know the right settings.",
            [
                ("Lower Display Brightness", "Auto-brightness on most phones is too high. Manual brightness at 40% in indoor light extends battery 20-30%."),
                ("Turn Off Always-On Display", "AOD costs 5-10% battery per day. If you don't actively use it, kill it."),
                ("Background App Refresh", "Disable for apps you don't need real-time updates from. Saves 10-15% daily."),
                ("Location Services", "Set most apps to 'while using' instead of 'always.' Massive battery saver."),
                ("Dark Mode (OLED phones)", "Dark mode saves 30-60% battery on OLED screens. Less impact on LCD."),
            ],
        ),
        "phone battery life tips",
        ["tech", "battery", "phone", "tips", "seo"],
    ),
    BlogCandidate(
        "Why Your Wi-Fi Is Slow (And How to Fix It)",
        "Slow Wi-Fi has 5 common causes — and 5 quick fixes that work.",
        _body(
            "Before buying a new router, try these troubleshooting steps. 80% of Wi-Fi problems have free fixes.",
            [
                ("Router Placement", "Central + elevated, away from metal and microwaves. A router in the corner of the house = dead zones everywhere."),
                ("Channel Congestion", "Use Wi-Fi Analyzer app to find the least-crowded channel. Apartment buildings are especially bad for channel overlap."),
                ("5GHz vs 2.4GHz", "5GHz is faster (close range), 2.4GHz reaches further. Separate the networks and connect accordingly."),
                ("Firmware Updates", "Routers need updates too. Most issues clear up after a firmware update + restart."),
                ("Mesh Network", "For homes >2000 sq ft, mesh systems ($150-300) outperform any single router. Worth it for big spaces."),
            ],
        ),
        "why is my wifi slow",
        ["tech", "wifi", "troubleshooting", "seo"],
    ),
    BlogCandidate(
        "Two-Factor Authentication: Everything You Need to Know",
        "2FA prevents 99% of account takeovers. Here's how to set it up the right way.",
        _body(
            "Two-factor authentication is the single biggest security upgrade you can make. Here's the rundown.",
            [
                ("What 2FA Does", "Adds a second verification step beyond your password. Even if your password leaks, attackers can't get in."),
                ("SMS 2FA: Better Than Nothing", "SMS is vulnerable to SIM-swap attacks but still better than no 2FA. Use as fallback only."),
                ("Authenticator Apps", "Google Authenticator, Authy, 1Password. Generate codes locally — can't be intercepted."),
                ("Hardware Keys", "YubiKey or similar. Highest security. Worth it for primary email + banking."),
                ("Backup Codes", "ALWAYS save backup codes. Lose your phone = lose access without them."),
            ],
        ),
        "two factor authentication setup",
        ["tech", "security", "2fa", "guide", "seo"],
    ),
    BlogCandidate(
        "Cleaning Your Electronics: The Right Way",
        "Misuse cleaners and you'll destroy your screens. Here's the safe way to clean every device.",
        _body(
            "Most electronics are damaged by cleaning, not by use. Here's the correct approach for each surface.",
            [
                ("Laptop/Phone Screens", "Microfiber cloth + 70% isopropyl alcohol (sprayed on cloth, not screen). Window cleaner damages coatings."),
                ("Keyboards", "Compressed air for crumbs. Cotton swab + isopropyl alcohol for sticky keys. Keycap puller for deep cleaning."),
                ("Phone Cases", "Dish soap + water for plastic/silicone. Leather conditioner for leather cases. Avoid abrasives."),
                ("Headphones/Earbuds", "Cotton swab + isopropyl alcohol for ear tips. Tooth pick + microfiber for mesh grilles. Replace ear tips every 6 months."),
            ],
        ),
        "how to clean electronics",
        ["tech", "cleaning", "maintenance", "seo"],
    ),
    BlogCandidate(
        "How to Choose a Power Bank: Watts, Hours, and Hidden Gotchas",
        "Power banks have specs that sound impressive but don't matter. Here's what to actually look for.",
        _body(
            "Choosing a power bank involves more than mAh numbers. Here's what matters for real-world use.",
            [
                ("mAh Is Just the Start", "10000 mAh charges most phones twice. 20000 mAh for tablets + multi-device. Don't overbuy."),
                ("Output Wattage", "20W minimum for fast-charge modern phones. 65W if you want to charge a laptop. 100W+ for power users."),
                ("Pass-Through Charging", "Lets you charge the power bank while it charges your device. Underrated feature for travel."),
                ("MagSafe / Qi Wireless", "Convenient for compatible phones. But less efficient — slower charge + more heat."),
                ("Travel Restrictions", "Anything over 100Wh (around 27000 mAh) requires airline approval. Most fall under this limit."),
            ],
        ),
        "how to choose a power bank",
        ["tech", "power-bank", "buying-guide", "seo"],
    ),
]


_FOOD = [
    BlogCandidate(
        "How to Brew the Perfect Cup of Tea",
        "Tea brewing varies by type. Here's the right water temperature + steep time for every variety.",
        _body(
            "Most people make tea wrong — water too hot, steeped too long, resulting in bitterness. Here's the right way for each type.",
            [
                ("Green Tea", "75-80°C, 2-3 minutes. Boiling water destroys the delicate flavor. Bitterness = overcooked."),
                ("Black Tea", "100°C, 3-5 minutes. Black tea can handle the heat. Strong but not bitter."),
                ("White Tea", "80-85°C, 4-5 minutes. Subtle flavor needs longer steep at lower heat."),
                ("Oolong", "85-90°C, 3-5 minutes. Multiple steeps possible — re-steep up to 4 times."),
                ("Herbal", "100°C, 5-10 minutes. Most herbals need long steep to extract flavor."),
            ],
        ),
        "how to brew tea",
        ["food", "tea", "brewing", "guide", "seo"],
    ),
    BlogCandidate(
        "Cooking with Olive Oil: What You Need to Know",
        "Extra virgin or regular? High heat or low heat? Here's the simple guide.",
        _body(
            "Olive oil is more nuanced than 'good for you.' Here's how to choose, store, and cook with it.",
            [
                ("Extra Virgin (EVOO)", "Cold-pressed, lowest acidity. Use for dressings, drizzling, finishing. Smoke point too low for high-heat cooking."),
                ("Regular Olive Oil", "Refined + blended. Higher smoke point (~390°F). Use for sautéing + roasting."),
                ("Storage", "Dark glass or metal container, cool place, away from heat. Light + heat oxidize olive oil within weeks."),
                ("Freshness Test", "Good olive oil smells grassy/peppery/fruity. Bad oil smells musty or like crayons. Trust your nose."),
                ("Health Note", "Polyphenols (the health-promoting compounds) degrade at high heat. Drizzle raw EVOO on finished dishes for maximum benefit."),
            ],
        ),
        "how to cook with olive oil",
        ["food", "olive-oil", "cooking", "guide", "seo"],
    ),
    BlogCandidate(
        "Cold Brew Coffee: How to Make It at Home",
        "Cold brew is smoother + less acidic than iced coffee. Here's the foolproof home method.",
        _body(
            "Cold brew is shockingly easy. The hard part is waiting — but the result is worth it.",
            [
                ("Coffee:Water Ratio", "1:8 by weight for concentrate, 1:16 for ready-to-drink. Concentrate keeps 2 weeks; finished cold brew 5 days."),
                ("Grind Coarse", "Coarse grind (like sea salt) prevents bitter over-extraction. Pre-ground from store is usually too fine."),
                ("Steep 12-18 Hours", "Room temperature for richer flavour. Refrigerator for cleaner profile."),
                ("Strain Twice", "Once through a fine mesh, then through a paper filter or cheesecloth. Removes all the sludge."),
                ("Serve", "Concentrate diluted 1:1 with water, milk, or coffee. Ice optional but recommended."),
            ],
        ),
        "how to make cold brew coffee",
        ["food", "coffee", "cold-brew", "diy", "seo"],
    ),
    BlogCandidate(
        "The Difference Between Real Maple Syrup and 'Pancake Syrup'",
        "Spoiler: most 'maple syrup' on supermarket shelves contains zero maple. Here's how to tell.",
        _body(
            "Real maple syrup costs more for a reason. Here's the difference and why it matters.",
            [
                ("Real Maple Syrup", "Made from boiled sap of maple trees. Ingredient list: 'Pure Maple Syrup.' Complex caramel-vanilla flavor."),
                ("Pancake Syrup", "Corn syrup + artificial flavor + caramel color. Ingredient list: 30+ items. Sweet but one-note flavor."),
                ("Grading", "Grade A Light = mild flavor. Grade A Dark = stronger flavor. Both are 'real' — preference, not quality."),
                ("Storage", "Refrigerate after opening. Real maple syrup will eventually grow mold; the artificial stuff won't (which says something)."),
                ("Cost Justified", "Real maple syrup is $0.50-1.00/oz. Pancake syrup is $0.10/oz. The real thing tastes 10x better — math works."),
            ],
        ),
        "real maple syrup vs pancake syrup",
        ["food", "maple-syrup", "comparison", "seo"],
    ),
    BlogCandidate(
        "How to Read Honey Labels (And Avoid Fakes)",
        "Up to 30% of honey is adulterated. Here's how to identify the real thing.",
        _body(
            "Honey adulteration is widespread — corn syrup or rice syrup added to stretch real honey. Here's how to spot it.",
            [
                ("Single-Source Honey", "Look for 'wildflower' (one region), 'manuka' (NZ), 'orange blossom' (FL/CA). Single-origin is harder to fake."),
                ("Cloudy = Real", "Real raw honey is cloudy from pollen + natural sugars. Crystal-clear honey has been ultra-filtered (which removes nutritional value)."),
                ("Crystallization Is Good", "Real honey crystallizes naturally over months. Liquid honey forever = likely heated to prevent crystallization (destroys enzymes)."),
                ("Bee Pollen Visible", "Look for tiny visible particles. Pure-filtered honey has none."),
                ("Local Beats Imported", "Local honey costs more but supports beekeepers and tends to be authentic. Bonus: may help with seasonal allergies."),
            ],
        ),
        "how to identify real honey",
        ["food", "honey", "labels", "buying-guide", "seo"],
    ),
    BlogCandidate(
        "Spices vs Herbs: The Difference (And Why It Matters)",
        "Knowing the difference makes you a better cook. Here's the simple rule + how to use each.",
        _body(
            "Most people use 'herbs' and 'spices' interchangeably. The distinction affects when and how to add them to dishes.",
            [
                ("Herbs", "Leaves of plants (fresh or dried). Basil, thyme, oregano, parsley. Add at the END of cooking — heat destroys delicate flavor."),
                ("Spices", "Seeds, roots, bark, fruits, flowers of plants. Cinnamon, cumin, ginger, peppercorn. Add at the BEGINNING — they need heat to bloom."),
                ("Toasting Spices", "Dry toast whole spices in a pan before grinding. Releases volatile oils. Transforms the flavor."),
                ("Fresh vs Dried", "Fresh herbs > dried herbs (always). Fresh spices ≠ relevant — most spices are sold dried."),
                ("Storage", "Whole spices last 4 years. Ground spices: 1-2 years max. If you can't smell it, throw it out."),
            ],
        ),
        "spices vs herbs difference",
        ["food", "cooking", "spices", "herbs", "seo"],
    ),
    BlogCandidate(
        "How to Build a Cheese Board That Wows",
        "Cheese boards are easier than they look. Here's the formula every dinner party host should know.",
        _body(
            "Great cheese boards balance variety, texture, and price. Here's the simple formula.",
            [
                ("The 3-3-3 Rule", "3 cheeses (one soft, one semi-hard, one hard) + 3 accompaniments (sweet, savory, briny) + 3 vehicles (crackers, bread, fruit)."),
                ("The Cheese Selection", "Soft: brie or camembert. Semi-hard: cheddar or gouda. Hard: parmesan or manchego. Variety > quantity."),
                ("Accompaniments", "Sweet: honey, fig jam. Savory: olives, prosciutto. Briny: cornichons, pickled onions."),
                ("Temperature Matters", "Take cheese out 30 minutes before serving. Cold cheese = muted flavor."),
                ("Cutting Style", "Soft cheese in wedges, semi-hard in slabs, hard in chunks. Match the cut to the texture."),
            ],
        ),
        "how to build a cheese board",
        ["food", "cheese", "entertaining", "guide", "seo"],
    ),
    BlogCandidate(
        "What 'Single Origin' Coffee Actually Means",
        "Single origin coffee costs more. Here's what you're actually paying for.",
        _body(
            "Single origin coffee is a craft-coffee buzzword with real meaning. Here's the breakdown.",
            [
                ("The Definition", "Coffee from a specific farm, region, or country — not a blend. Tracks all the way back to the grower."),
                ("Why It Costs More", "Smaller production batches, premium beans, direct trade relationships. Cost premium = quality premium."),
                ("Flavor Profile", "Each origin has distinct notes. Ethiopian Yirgacheffe = floral + citrus. Sumatra = earthy + chocolate. Colombian = balanced + nutty."),
                ("Brewing Recommendation", "Drip or pour-over to taste the nuances. Don't waste single-origin on milky lattes — the milk masks the flavor."),
                ("How to Try Variety", "Buy 4 oz bags from 3-4 different origins. Cheaper than committing to a 12oz bag of one. Find your favorite."),
            ],
        ),
        "what is single origin coffee",
        ["food", "coffee", "single-origin", "guide", "seo"],
    ),
    BlogCandidate(
        "How to Store Pantry Staples for Maximum Freshness",
        "Most pantry items last way longer with proper storage. Here's the rundown.",
        _body(
            "Pantry storage isn't 'set and forget.' Here's the right approach for each major staple.",
            [
                ("Olive Oil", "Dark glass + cool spot. 6 months for peak freshness, 18 months max."),
                ("Flour", "Airtight container, dark place. White flour: 1 year. Whole wheat: 3 months at room temp, 1 year frozen."),
                ("Spices", "Glass jars, away from stove (heat ruins them). Whole: 4 years. Ground: 1-2 years."),
                ("Rice", "Airtight container, cool dry place. White: indefinite. Brown: 6 months (oil in bran goes rancid)."),
                ("Pasta", "Sealed bag/container. Dry pasta: 2 years. Filled pasta (like ravioli): refrigerated, 5-7 days."),
            ],
        ),
        "pantry storage guide",
        ["food", "pantry", "storage", "seo"],
    ),
    BlogCandidate(
        "Vanilla Beans vs Vanilla Extract: When to Use Which",
        "Vanilla bean costs 10x what extract does. Here's when it's worth it.",
        _body(
            "Real vanilla is expensive. Here's how to maximize each form for the best results.",
            [
                ("Vanilla Beans", "For applications where you SEE the specks (panna cotta, ice cream, custards). The visual + bold flavor justify cost."),
                ("Pure Vanilla Extract", "For baking. Most flavor is masked by other ingredients anyway. Stick with reasonable price."),
                ("Vanilla Bean Paste", "Compromise: bean specks + paste form. $20/jar lasts months. Best for home bakers."),
                ("Imitation Vanilla", "Skip it. It's vanillin + alcohol. Tastes one-note synthetic compared to the real thing."),
                ("DIY Vanilla Extract", "1 bean + 1 cup vodka. Steep 8+ weeks. Cheapest way to get real vanilla flavor in bulk."),
            ],
        ),
        "vanilla bean vs extract",
        ["food", "vanilla", "baking", "comparison", "seo"],
    ),
]


# Final catalog map. Frozen-tuple values to defend against
# in-place mutation by callers.
_CATALOG: dict[str, tuple[BlogCandidate, ...]] = {
    "beauty":  tuple(_BEAUTY),
    "fashion": tuple(_FASHION),
    "home":    tuple(_HOME),
    "tech":    tuple(_TECH),
    "food":    tuple(_FOOD),
}


def get_catalog(niche: str) -> list[BlogCandidate]:
    """Return a fresh list copy for the requested niche, or []
    when the niche isn't recognised."""
    if not isinstance(niche, str):
        return []
    key = niche.strip().lower()
    rows = _CATALOG.get(key)
    if rows is None:
        return []
    return list(rows)


def catalog_summary() -> dict[str, int]:
    return {k: len(v) for k, v in _CATALOG.items()}
