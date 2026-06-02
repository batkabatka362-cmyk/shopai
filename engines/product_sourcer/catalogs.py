"""Curated niche -> product-candidate catalog.

5 niches × 20 candidates each = 100 templates. Each is a
domain-typical product with realistic naming, category, price
band, and tags. Future revisions can swap to AI generation or an
external supplier API; the deterministic baseline is here so the
engine works offline + tests are reproducible.

Each ProductCandidate carries:
    name:        SEO-typical title
    category:    Shopify-friendly category
    description: 1-2 sentence pitch
    price_min:   USD lower bound (operator can adjust)
    price_max:   USD upper bound
    tags:        4-6 tags (used by tag_management + SEO)
    vendor_hint: where this kind of product is typically sourced
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProductCandidate:
    name: str
    category: str
    description: str
    price_min: float
    price_max: float
    tags: list[str] = field(default_factory=list)
    vendor_hint: str = ""


SUPPORTED_NICHES = (
    "beauty", "fashion", "home", "tech", "food",
)


_BEAUTY = [
    ProductCandidate(
        "Vitamin C Brightening Serum 30ml", "Skincare",
        "Daily-use serum with 15% vitamin C + hyaluronic acid for radiant skin.",
        12.0, 28.0,
        ["skincare", "serum", "vitamin-c", "antiaging", "vegan"],
        "Cosmetic OEM / private-label",
    ),
    ProductCandidate(
        "Rose Hip Hydrating Toner 200ml", "Skincare",
        "Alcohol-free toner balances pH and preps skin for moisturizer.",
        10.0, 22.0,
        ["skincare", "toner", "rose-hip", "hydrating", "natural"],
        "Cosmetic OEM",
    ),
    ProductCandidate(
        "Matcha Antioxidant Face Mask (5-pack)", "Skincare",
        "Single-use sheet masks infused with matcha + green tea polyphenols.",
        14.0, 30.0,
        ["skincare", "mask", "matcha", "antioxidant"],
        "Cosmetic OEM",
    ),
    ProductCandidate(
        "Bamboo Charcoal Pore Strips (10ct)", "Skincare",
        "Deep-cleansing nose strips remove blackheads + impurities.",
        8.0, 16.0,
        ["skincare", "blackhead", "charcoal", "pore"],
        "Cosmetic OEM",
    ),
    ProductCandidate(
        "Velvet Matte Liquid Lipstick", "Makeup",
        "12-hour wear, transfer-proof matte finish in 12 universal shades.",
        9.0, 22.0,
        ["makeup", "lipstick", "matte", "longwear"],
        "Cosmetic OEM",
    ),
    ProductCandidate(
        "Magnetic False Eyelashes (3-pair)", "Makeup",
        "Reusable magnetic lashes — no glue, no mess. Natural to dramatic.",
        12.0, 25.0,
        ["makeup", "eyelashes", "magnetic", "reusable"],
        "Beauty wholesale",
    ),
    ProductCandidate(
        "12-Color Eyeshadow Palette", "Makeup",
        "Buttery shimmer + matte shades for everyday to glam looks.",
        18.0, 38.0,
        ["makeup", "eyeshadow", "palette"],
        "Cosmetic OEM",
    ),
    ProductCandidate(
        "Argan Oil Hair Mask 250ml", "Haircare",
        "Repairing mask with cold-pressed argan oil for damaged hair.",
        14.0, 28.0,
        ["haircare", "mask", "argan", "repair"],
        "Cosmetic OEM",
    ),
    ProductCandidate(
        "Silk Hair Bonnet Adjustable", "Haircare",
        "Mulberry-silk bonnet preserves curl pattern and reduces breakage overnight.",
        16.0, 32.0,
        ["haircare", "silk", "bonnet", "curls"],
        "Textile importer",
    ),
    ProductCandidate(
        "Vegan Castor Oil Lash Serum", "Eye Care",
        "Cold-pressed castor + vitamin E for longer-looking lashes.",
        9.0, 18.0,
        ["beauty", "lashes", "castor-oil", "vegan"],
        "Cosmetic OEM",
    ),
    ProductCandidate(
        "Konjac Sponge Facial Cleansing Set", "Skincare",
        "Plant-based sponges for gentle daily exfoliation.",
        7.0, 14.0,
        ["skincare", "konjac", "exfoliation", "natural"],
        "Beauty wholesale",
    ),
    ProductCandidate(
        "Wooden Comb + Bristle Brush Set", "Haircare",
        "Anti-static sandalwood comb + boar-bristle brush kit.",
        16.0, 30.0,
        ["haircare", "comb", "brush", "wooden"],
        "Beauty wholesale",
    ),
    ProductCandidate(
        "Aroma-Therapy Diffuser Necklace", "Wellness",
        "Stainless steel locket pendant holds essential oil pad — wear scent all day.",
        14.0, 28.0,
        ["wellness", "aromatherapy", "necklace", "essential-oil"],
        "Wellness wholesale",
    ),
    ProductCandidate(
        "Jade Roller + Gua Sha Set", "Skincare",
        "Hand-carved jade tools for lymphatic massage + de-puffing.",
        18.0, 35.0,
        ["skincare", "jade-roller", "gua-sha", "massage"],
        "Beauty wholesale",
    ),
    ProductCandidate(
        "Niacinamide 10% + Zinc Serum 30ml", "Skincare",
        "Pore-minimizing serum for oily / combination skin.",
        11.0, 22.0,
        ["skincare", "serum", "niacinamide", "oily-skin"],
        "Cosmetic OEM",
    ),
    ProductCandidate(
        "Lavender Body Butter 200ml", "Bodycare",
        "Whipped shea butter + lavender essential oil — non-greasy.",
        12.0, 24.0,
        ["bodycare", "lavender", "shea", "moisturizer"],
        "Cosmetic OEM",
    ),
    ProductCandidate(
        "Reusable Makeup Remover Pads (16ct)", "Skincare",
        "Bamboo-fiber rounds + laundry bag — zero-waste makeup removal.",
        14.0, 24.0,
        ["skincare", "reusable", "bamboo", "ecofriendly"],
        "Beauty wholesale",
    ),
    ProductCandidate(
        "Vegan Lip Balm Trio", "Lip Care",
        "Beeswax-free balms in vanilla / mint / coconut.",
        9.0, 16.0,
        ["lipcare", "vegan", "lip-balm"],
        "Cosmetic OEM",
    ),
    ProductCandidate(
        "Eye Mask Cooling Gel Sleep Pack", "Wellness",
        "Reusable gel mask soothes puffy eyes — freeze or microwave.",
        8.0, 16.0,
        ["wellness", "eye-mask", "cooling", "sleep"],
        "Wellness wholesale",
    ),
    ProductCandidate(
        "Sunscreen SPF50 PA++++ Light Fluid 50ml", "Skincare",
        "Korean-formula featherlight SPF for daily wear under makeup.",
        14.0, 28.0,
        ["skincare", "sunscreen", "spf", "korean-beauty"],
        "Cosmetic OEM",
    ),
]


_FASHION = [
    ProductCandidate(
        "Oversized Cotton Crewneck Hoodie", "Tops",
        "Heavyweight 100% cotton hoodie in earth-tone palette.",
        28.0, 58.0,
        ["fashion", "hoodie", "unisex", "cotton", "streetwear"],
        "Apparel manufacturer",
    ),
    ProductCandidate(
        "Linen-Blend Wide-Leg Trouser", "Bottoms",
        "Breathable linen mix with relaxed wide-leg silhouette.",
        38.0, 78.0,
        ["fashion", "trouser", "linen", "summer"],
        "Apparel manufacturer",
    ),
    ProductCandidate(
        "Silk-Touch Slip Midi Dress", "Dresses",
        "Bias-cut slip dress with adjustable straps in 6 colours.",
        42.0, 88.0,
        ["fashion", "dress", "slip", "satin"],
        "Apparel manufacturer",
    ),
    ProductCandidate(
        "Faux Leather Crossbody Mini Bag", "Bags",
        "Vegan leather with adjustable chain strap.",
        24.0, 48.0,
        ["fashion", "bag", "vegan-leather", "crossbody"],
        "Accessories wholesale",
    ),
    ProductCandidate(
        "Chunky Knit Beanie Hat", "Accessories",
        "Soft acrylic-wool blend in neutral tones.",
        14.0, 28.0,
        ["fashion", "beanie", "winter", "knit"],
        "Accessories wholesale",
    ),
    ProductCandidate(
        "Square-Toe Strappy Sandals", "Shoes",
        "Minimalist square-toe with adjustable ankle strap.",
        38.0, 68.0,
        ["fashion", "sandals", "summer", "square-toe"],
        "Footwear manufacturer",
    ),
    ProductCandidate(
        "Cropped Denim Jacket — Vintage Wash", "Outerwear",
        "Classic trucker fit, cropped length, vintage-wash distress.",
        38.0, 72.0,
        ["fashion", "denim", "jacket", "vintage"],
        "Apparel manufacturer",
    ),
    ProductCandidate(
        "Wool-Blend Long Coat", "Outerwear",
        "Tailored single-breasted coat with notched lapel.",
        78.0, 168.0,
        ["fashion", "coat", "wool", "fall-winter"],
        "Apparel manufacturer",
    ),
    ProductCandidate(
        "Statement Gold Hoop Earrings", "Jewelry",
        "Lightweight 18k-plated chunky hoops — hypoallergenic.",
        18.0, 38.0,
        ["fashion", "earrings", "gold", "hoops"],
        "Jewelry wholesale",
    ),
    ProductCandidate(
        "Layered Pearl Choker Necklace", "Jewelry",
        "Freshwater pearl + gold chain layered choker.",
        24.0, 48.0,
        ["fashion", "necklace", "pearl", "layered"],
        "Jewelry wholesale",
    ),
    ProductCandidate(
        "Bucket Hat — Waterproof Nylon", "Accessories",
        "Packable bucket hat for outdoor + festival days.",
        16.0, 32.0,
        ["fashion", "bucket-hat", "outdoor"],
        "Accessories wholesale",
    ),
    ProductCandidate(
        "Cropped Ribbed Tank — 3-pack", "Tops",
        "Soft modal-blend ribbed tanks in basic colours.",
        24.0, 42.0,
        ["fashion", "tank", "basics", "modal"],
        "Apparel manufacturer",
    ),
    ProductCandidate(
        "Pleated Tennis Skort", "Bottoms",
        "Athletic-style pleated skort with built-in shorts.",
        28.0, 52.0,
        ["fashion", "skort", "athleisure", "tennis"],
        "Apparel manufacturer",
    ),
    ProductCandidate(
        "Convertible Backpack Tote Bag", "Bags",
        "Dual carry-mode bag — backpack or tote — durable canvas.",
        38.0, 72.0,
        ["fashion", "backpack", "tote", "convertible"],
        "Accessories wholesale",
    ),
    ProductCandidate(
        "Silk Hair Scrunchie — 5-pack", "Accessories",
        "Mulberry-silk hair ties in mixed jewel tones.",
        14.0, 24.0,
        ["fashion", "hair-accessory", "silk", "scrunchie"],
        "Beauty wholesale",
    ),
    ProductCandidate(
        "Minimalist Watch — Mesh Strap", "Watches",
        "Slim case with mesh stainless strap, quartz movement.",
        48.0, 98.0,
        ["fashion", "watch", "minimalist", "mesh"],
        "Watch wholesale",
    ),
    ProductCandidate(
        "Oversized Sunglasses — Cat-Eye", "Eyewear",
        "Retro cat-eye frame with UV400 polarised lenses.",
        18.0, 38.0,
        ["fashion", "sunglasses", "cat-eye", "uv-protection"],
        "Eyewear wholesale",
    ),
    ProductCandidate(
        "Embroidered Floral Belt", "Accessories",
        "Hand-embroidered cotton belt with leather buckle.",
        22.0, 42.0,
        ["fashion", "belt", "embroidery", "boho"],
        "Accessories wholesale",
    ),
    ProductCandidate(
        "Wool-Cashmere Scarf — Plaid", "Accessories",
        "Soft brushed plaid scarf in oversize wrap size.",
        32.0, 62.0,
        ["fashion", "scarf", "wool", "plaid"],
        "Accessories wholesale",
    ),
    ProductCandidate(
        "Chunky Platform Sneakers", "Shoes",
        "Trend-forward platform sole sneakers in white / cream.",
        48.0, 92.0,
        ["fashion", "sneakers", "platform", "y2k"],
        "Footwear manufacturer",
    ),
]


_HOME = [
    ProductCandidate(
        "Bamboo 3-Tier Spice Rack", "Kitchen",
        "Counter-top bamboo organizer for jars + bottles.",
        18.0, 38.0,
        ["home", "kitchen", "bamboo", "organizer"],
        "Houseware wholesale",
    ),
    ProductCandidate(
        "Ceramic Stoneware Dinnerware (16pc Set)", "Tableware",
        "Speckled stoneware dinnerware for 4 — dishwasher-safe.",
        78.0, 168.0,
        ["home", "tableware", "ceramic", "dinnerware"],
        "Tableware importer",
    ),
    ProductCandidate(
        "Soy Wax Candle — Eucalyptus & Mint", "Decor",
        "Clean-burn soy candle in amber glass, 45hr burn time.",
        14.0, 28.0,
        ["home", "candle", "soy", "fragrance"],
        "Candle wholesale",
    ),
    ProductCandidate(
        "Linen Throw Blanket 130×170cm", "Bedding",
        "Stonewashed European linen throw in 5 muted shades.",
        58.0, 118.0,
        ["home", "throw", "linen", "blanket"],
        "Textile importer",
    ),
    ProductCandidate(
        "Marble + Wood Cutting Board Trio", "Kitchen",
        "Charcuterie-friendly board set: small / medium / large.",
        38.0, 78.0,
        ["home", "kitchen", "cutting-board", "marble"],
        "Houseware wholesale",
    ),
    ProductCandidate(
        "Velvet Cushion Cover Pair 45×45cm", "Decor",
        "Plush velvet covers in jewel tones — inserts sold separately.",
        18.0, 38.0,
        ["home", "cushion", "velvet", "decor"],
        "Textile importer",
    ),
    ProductCandidate(
        "Cast Iron Stovetop Kettle", "Kitchen",
        "1.5L enameled cast iron kettle with whistle.",
        38.0, 78.0,
        ["home", "kitchen", "kettle", "castiron"],
        "Houseware wholesale",
    ),
    ProductCandidate(
        "Reed Diffuser — Vanilla + Sandalwood", "Decor",
        "200ml essential-oil reed diffuser, 8-week throw.",
        18.0, 32.0,
        ["home", "decor", "diffuser", "fragrance"],
        "Wellness wholesale",
    ),
    ProductCandidate(
        "Acacia Wood Salad Bowl Set", "Tableware",
        "Hand-finished acacia bowls with serving utensils.",
        38.0, 78.0,
        ["home", "tableware", "wood", "serving"],
        "Houseware wholesale",
    ),
    ProductCandidate(
        "Macrame Wall Hanging — Boho", "Decor",
        "Handmade cotton-rope wall art in 4 sizes.",
        24.0, 58.0,
        ["home", "decor", "macrame", "boho"],
        "Decor wholesale",
    ),
    ProductCandidate(
        "Bamboo Kitchen Roll Holder", "Kitchen",
        "Heavy-base bamboo holder — one-handed tear.",
        18.0, 32.0,
        ["home", "kitchen", "bamboo", "organizer"],
        "Houseware wholesale",
    ),
    ProductCandidate(
        "Ceramic Pour-Over Coffee Dripper", "Kitchen",
        "Single-cup dripper with filter starter pack.",
        18.0, 38.0,
        ["home", "kitchen", "coffee", "ceramic"],
        "Houseware wholesale",
    ),
    ProductCandidate(
        "Glass Storage Jar Trio with Cork Lid", "Kitchen",
        "Airtight food jars — set of 3.",
        14.0, 28.0,
        ["home", "kitchen", "storage", "glass"],
        "Houseware wholesale",
    ),
    ProductCandidate(
        "Bamboo Bath Tray with Adjustable Arms", "Bath",
        "Caddy fits any tub — book + glass + phone slots.",
        38.0, 68.0,
        ["home", "bath", "bamboo", "selfcare"],
        "Houseware wholesale",
    ),
    ProductCandidate(
        "Rattan Pendant Light Shade", "Lighting",
        "Hand-woven rattan dome shade for warm filtered light.",
        38.0, 78.0,
        ["home", "lighting", "rattan", "decor"],
        "Decor wholesale",
    ),
    ProductCandidate(
        "Indoor Plant Pot — Concrete Mid", "Decor",
        "Modern concrete planter with drainage tray, 4 sizes.",
        18.0, 48.0,
        ["home", "decor", "planter", "concrete"],
        "Decor wholesale",
    ),
    ProductCandidate(
        "Brass Drawer Pulls — Set of 4", "Hardware",
        "Solid brass cabinet handles for kitchen / dresser refresh.",
        24.0, 48.0,
        ["home", "hardware", "brass", "renovation"],
        "Hardware wholesale",
    ),
    ProductCandidate(
        "100% Cotton Waffle Bath Towel Set", "Bath",
        "Plush waffle-weave towels — bath + hand + face.",
        38.0, 78.0,
        ["home", "bath", "towel", "cotton"],
        "Textile importer",
    ),
    ProductCandidate(
        "Wool Felt Slipper — Indoor", "Comfort",
        "Boiled-wool slippers with non-slip sole.",
        28.0, 58.0,
        ["home", "slipper", "wool", "comfort"],
        "Footwear manufacturer",
    ),
    ProductCandidate(
        "Wireless Doorbell — Battery Powered", "Tech",
        "300m range plug-in chime + battery push button.",
        24.0, 42.0,
        ["home", "doorbell", "wireless", "tech"],
        "Electronics wholesale",
    ),
]


_TECH = [
    ProductCandidate(
        "USB-C 100W GaN Fast Charger", "Charging",
        "Compact 3-port GaN wall charger for laptop + phone + tablet.",
        38.0, 78.0,
        ["tech", "charger", "usb-c", "gan", "100w"],
        "Electronics OEM",
    ),
    ProductCandidate(
        "Magnetic Wireless Power Bank 10000mAh", "Charging",
        "MagSafe-compatible portable battery with kickstand.",
        38.0, 72.0,
        ["tech", "powerbank", "wireless", "magsafe"],
        "Electronics OEM",
    ),
    ProductCandidate(
        "Bluetooth 5.3 Wireless Earbuds — ANC", "Audio",
        "True wireless earbuds with active noise cancellation.",
        38.0, 98.0,
        ["tech", "audio", "earbuds", "anc", "bluetooth"],
        "Electronics OEM",
    ),
    ProductCandidate(
        "Mechanical Keyboard — 60% Hot-Swap", "Computing",
        "Wired/wireless 60% keyboard with hot-swappable switches.",
        78.0, 168.0,
        ["tech", "keyboard", "mechanical", "hotswap"],
        "Electronics OEM",
    ),
    ProductCandidate(
        "Webcam Cover Sliding Privacy 3-pack", "Privacy",
        "Ultra-thin privacy slider for laptop + tablet.",
        7.0, 14.0,
        ["tech", "privacy", "webcam", "security"],
        "Electronics wholesale",
    ),
    ProductCandidate(
        "USB-C Hub 7-in-1 (HDMI / SD / PD)", "Connectivity",
        "Single-cable docking solution for MacBook / iPad.",
        28.0, 58.0,
        ["tech", "hub", "usb-c", "hdmi"],
        "Electronics OEM",
    ),
    ProductCandidate(
        "Laptop Stand — Aluminium Ergonomic", "Workspace",
        "Adjustable foldable laptop stand with cable channel.",
        38.0, 78.0,
        ["tech", "laptop-stand", "ergonomic", "aluminium"],
        "Electronics OEM",
    ),
    ProductCandidate(
        "Vertical Ergonomic Wireless Mouse", "Computing",
        "Reduces wrist strain — silent click, USB-C charging.",
        28.0, 52.0,
        ["tech", "mouse", "ergonomic", "vertical"],
        "Electronics OEM",
    ),
    ProductCandidate(
        "Smart Plug WiFi (4-pack)", "Smart Home",
        "Voice + app-controlled outlets with energy monitor.",
        28.0, 52.0,
        ["tech", "smart-home", "plug", "wifi"],
        "Smart-home OEM",
    ),
    ProductCandidate(
        "Tempered Glass Phone Screen Protector — iPhone", "Accessories",
        "9H hardness with installation frame, 2-pack.",
        9.0, 18.0,
        ["tech", "screen-protector", "iphone", "tempered-glass"],
        "Accessories wholesale",
    ),
    ProductCandidate(
        "Foldable Portable Bluetooth Speaker", "Audio",
        "IPX6 waterproof, 12hr battery, magnetic mount.",
        38.0, 78.0,
        ["tech", "speaker", "bluetooth", "waterproof"],
        "Electronics OEM",
    ),
    ProductCandidate(
        "RFID-Blocking Carbon Fiber Wallet", "Privacy",
        "Slim minimal wallet with RFID-shielding card cage.",
        24.0, 48.0,
        ["tech", "wallet", "rfid", "carbon-fiber"],
        "Accessories wholesale",
    ),
    ProductCandidate(
        "Smart LED Strip Light 5m WiFi", "Smart Home",
        "Music-sync RGB strip with phone app + voice.",
        28.0, 52.0,
        ["tech", "smart-home", "led", "lighting"],
        "Smart-home OEM",
    ),
    ProductCandidate(
        "Air Tag-Compatible Key Holder Wallet", "Accessories",
        "Slim leather wallet sized for Apple AirTag pocket.",
        24.0, 48.0,
        ["tech", "wallet", "airtag", "tracking"],
        "Accessories wholesale",
    ),
    ProductCandidate(
        "Gaming Mouse Pad XL with USB Wireless Charging", "Gaming",
        "900×400 desk mat with built-in wireless charge zone.",
        38.0, 78.0,
        ["tech", "mouse-pad", "gaming", "wireless-charging"],
        "Electronics OEM",
    ),
    ProductCandidate(
        "Studio Microphone USB Cardioid", "Audio",
        "Streamer / podcaster-grade USB mic with pop filter.",
        58.0, 128.0,
        ["tech", "microphone", "usb", "podcast"],
        "Electronics OEM",
    ),
    ProductCandidate(
        "Smart Coffee Mug — Temperature Controlled", "Smart Home",
        "Self-heating mug holds set temperature 60-90°F.",
        58.0, 118.0,
        ["tech", "smart-home", "coffee", "temperature"],
        "Smart-home OEM",
    ),
    ProductCandidate(
        "Mini Drone with 4K Camera", "Gadgets",
        "Foldable beginner-friendly drone with brushless motors.",
        78.0, 168.0,
        ["tech", "drone", "4k", "camera"],
        "Electronics OEM",
    ),
    ProductCandidate(
        "Bluetooth Anti-Lost Smart Tracker 4-pack", "Tracking",
        "Coin-cell trackers for keys / bags / pets.",
        24.0, 48.0,
        ["tech", "tracker", "bluetooth", "anti-lost"],
        "Electronics wholesale",
    ),
    ProductCandidate(
        "USB Rechargeable LED Reading Light Clip", "Accessories",
        "Adjustable 3-tone book light with built-in battery.",
        14.0, 28.0,
        ["tech", "reading-light", "led", "rechargeable"],
        "Electronics wholesale",
    ),
]


_FOOD = [
    ProductCandidate(
        "Single-Origin Cold Brew Coffee Concentrate 1L", "Coffee",
        "Slow-steeped 18hr cold brew — yields 16 cups.",
        18.0, 32.0,
        ["food", "coffee", "cold-brew", "concentrate"],
        "Specialty coffee roaster",
    ),
    ProductCandidate(
        "Loose-Leaf Matcha Powder Ceremonial Grade 30g", "Tea",
        "Ceremonial-grade Uji matcha — vibrant umami green.",
        24.0, 58.0,
        ["food", "matcha", "tea", "ceremonial"],
        "Tea importer",
    ),
    ProductCandidate(
        "Single-Origin 70% Dark Chocolate Bar 3-pack", "Chocolate",
        "Ethically-sourced cacao bars in 3 origin flavours.",
        18.0, 32.0,
        ["food", "chocolate", "dark", "ethical"],
        "Chocolate maker",
    ),
    ProductCandidate(
        "Cold-Pressed Olive Oil 500ml Tin", "Pantry",
        "EVOO from a single Mediterranean grove, early-harvest.",
        28.0, 58.0,
        ["food", "olive-oil", "pantry", "evoo"],
        "Olive importer",
    ),
    ProductCandidate(
        "Aged Balsamic Vinegar 250ml", "Pantry",
        "12-year aged Modena balsamic — IGP certified.",
        24.0, 48.0,
        ["food", "balsamic", "pantry", "italian"],
        "Pantry importer",
    ),
    ProductCandidate(
        "Artisan Hot Honey 350g — Chili Infused", "Pantry",
        "Wildflower honey infused with smoked chili.",
        14.0, 28.0,
        ["food", "honey", "spicy", "artisan"],
        "Specialty foods",
    ),
    ProductCandidate(
        "Wild Caught Sardines in Olive Oil 6-pack", "Pantry",
        "Sustainably-caught sardines packed in EVOO.",
        24.0, 48.0,
        ["food", "sardines", "tinned", "sustainable"],
        "Specialty foods",
    ),
    ProductCandidate(
        "Sicilian Sea Salt Flakes 250g", "Pantry",
        "Hand-harvested flake salt for finishing dishes.",
        12.0, 24.0,
        ["food", "salt", "sicilian", "finishing"],
        "Specialty foods",
    ),
    ProductCandidate(
        "Single-Origin Manuka Honey UMF15+", "Pantry",
        "New Zealand manuka with certified UMF rating.",
        38.0, 88.0,
        ["food", "honey", "manuka", "premium"],
        "Honey importer",
    ),
    ProductCandidate(
        "Organic Sumac + Za'atar Spice Pair", "Pantry",
        "Single-source Levantine spices in cork-stoppered jars.",
        18.0, 32.0,
        ["food", "spice", "zaatar", "sumac", "organic"],
        "Specialty foods",
    ),
    ProductCandidate(
        "Cold-Steeped Iced Tea Pyramid Bags (20ct)", "Tea",
        "Tropical fruit + green tea blend for cold infusion.",
        14.0, 24.0,
        ["food", "tea", "iced", "fruit"],
        "Tea importer",
    ),
    ProductCandidate(
        "Single-Estate Coffee Beans 250g — Light Roast", "Coffee",
        "Yirgacheffe Ethiopia — floral + citrus tasting notes.",
        18.0, 32.0,
        ["food", "coffee", "single-origin", "light-roast"],
        "Specialty coffee roaster",
    ),
    ProductCandidate(
        "Granola Crunch Bag 350g — Salted Caramel", "Snacks",
        "Small-batch oat granola with cashew + almond.",
        12.0, 22.0,
        ["food", "granola", "snack", "breakfast"],
        "Specialty foods",
    ),
    ProductCandidate(
        "Maple Syrup Grade-A Amber 500ml", "Pantry",
        "Pure Quebec amber-rich grade-A maple in glass bottle.",
        24.0, 48.0,
        ["food", "maple", "syrup", "grade-a"],
        "Pantry importer",
    ),
    ProductCandidate(
        "Heirloom Pasta — Bronze-Die 500g", "Pantry",
        "Italian heritage pasta — bronze-die for sauce adhesion.",
        14.0, 28.0,
        ["food", "pasta", "italian", "heirloom"],
        "Pantry importer",
    ),
    ProductCandidate(
        "Raw Cacao Nibs Organic 250g", "Pantry",
        "Stone-ground nibs from organic Ecuadorian cacao.",
        14.0, 28.0,
        ["food", "cacao", "raw", "organic"],
        "Specialty foods",
    ),
    ProductCandidate(
        "Smoked Sea Salt Trio Box", "Pantry",
        "Hickory + applewood + cherrywood smoked sea salt.",
        24.0, 42.0,
        ["food", "salt", "smoked", "gift"],
        "Specialty foods",
    ),
    ProductCandidate(
        "Artisan Tahini Stone-Ground 350g", "Pantry",
        "Single-source Ethiopian sesame, stone-milled.",
        14.0, 26.0,
        ["food", "tahini", "artisan", "vegan"],
        "Specialty foods",
    ),
    ProductCandidate(
        "Hot Sauce Sampler Pack (4×60ml)", "Pantry",
        "Small-batch craft hot sauces — mild to fire.",
        18.0, 32.0,
        ["food", "hot-sauce", "sampler", "craft"],
        "Specialty foods",
    ),
    ProductCandidate(
        "Single-Origin Vanilla Beans (10ct)", "Pantry",
        "Madagascar bourbon vanilla pods — Grade A.",
        18.0, 38.0,
        ["food", "vanilla", "madagascar", "baking"],
        "Pantry importer",
    ),
]


# Final catalog map. Frozen-tuple values to defend against
# in-place mutation by callers iterating + appending.
_CATALOG: dict[str, tuple[ProductCandidate, ...]] = {
    "beauty":  tuple(_BEAUTY),
    "fashion": tuple(_FASHION),
    "home":    tuple(_HOME),
    "tech":    tuple(_TECH),
    "food":    tuple(_FOOD),
}


def get_catalog(niche: str) -> list[ProductCandidate]:
    """Return a fresh list copy for the requested niche, or [] when
    the niche isn't recognised. Callers can mutate freely without
    leaking back into the module-level catalog."""
    if not isinstance(niche, str):
        return []
    key = niche.strip().lower()
    rows = _CATALOG.get(key)
    if rows is None:
        return []
    return list(rows)


def catalog_summary() -> dict[str, int]:
    """Per-niche candidate count — used by the CLI ``--list-niches``
    branch and by tests asserting catalog growth."""
    return {k: len(v) for k, v in _CATALOG.items()}
