"""Publish social content + landing page + collection descriptions to Shopify."""
import os, json, urllib.request

# Load env
with open('.env') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ[k] = v

from core.auth.shopify_auth import ShopifyAuth
auth = ShopifyAuth(os.environ['SHOPAI_SHOPIFY_URL'], os.environ['SHOPAI_SHOPIFY_CLIENT_ID'], os.environ['SHOPAI_SHOPIFY_CLIENT_SECRET'])
token = auth.get_token()
shop = os.environ['SHOPAI_SHOPIFY_URL']
h = {'X-Shopify-Access-Token': token, 'Content-Type': 'application/json'}


def api_post(path, payload):
    url = 'https://{}/admin/api/2024-01/{}'.format(shop, path)
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method='POST', headers=h)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()[:200]
        return {'error': 'HTTP {} {}'.format(exc.code, body)}


def api_get(path):
    req = urllib.request.Request('https://{}/admin/api/2024-01/{}'.format(shop, path), headers=h)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# Get products + blog
products = api_get('products.json?limit=50')['products']
blogs = api_get('blogs.json')
blog_id = str(blogs.get('blogs', [{}])[0].get('id', ''))

# Sort by margin
by_margin = sorted(products, key=lambda p: (
    float(p.get('variants', [{}])[0].get('price', '0')) -
    float(p.get('cost', '0') or 0)
) / max(float(p.get('variants', [{}])[0].get('price', '1')), 1)
    if p.get('variants') else 0, reverse=True)

# 1. Social content blog posts
print('=== SOCIAL CONTENT BLOG POSTS ===')
from execution.content.social_content import get_social_content
sc = get_social_content()

published = 0
for p in by_margin[:3]:
    name = p['title']
    handle = p.get('handle', '')
    price = p['variants'][0]['price'] if p.get('variants') else '0'
    cat = p.get('product_type', '')

    content = sc.generate_for_product(p)
    ig = content['posts'].get('instagram', {}).get('caption', '')
    fb = content['posts'].get('facebook', {}).get('text', '')

    body = '<h2>{}</h2>'.format(name)
    body += '<p><strong>Price: ${}</strong></p>'.format(price)
    body += '<h3>Ready-to-use Social Media Posts</h3>'
    body += '<h4>Instagram</h4><pre>{}</pre>'.format(ig)
    body += '<h4>Facebook</h4><pre>{}</pre>'.format(fb)
    body += '<p><a href="/products/{}">Shop Now</a></p>'.format(handle)

    result = api_post('blogs/{}/articles.json'.format(blog_id), {
        'article': {
            'title': 'Marketing Kit: {}'.format(name[:40]),
            'body_html': body,
            'tags': 'social, marketing, {}'.format(cat.lower()),
            'published': True,
        }
    })
    if result.get('article'):
        published += 1
        print('  Published: {}'.format(name[:40]))
    else:
        print('  Error: {}'.format(str(result.get('error', ''))[:60]))

# 2. Discount landing page
print()
print('=== DISCOUNT LANDING PAGE ===')
page_html = """<h2>Exclusive Discount Codes</h2>
<div style="background:#f0f7ff;padding:20px;border-radius:8px;margin:15px 0;border:2px solid #007bff">
<h3 style="color:#007bff">WELCOME15</h3>
<p>15% off your first order. New customers only!</p>
</div>
<div style="background:#f0fff0;padding:20px;border-radius:8px;margin:15px 0;border:2px solid #28a745">
<h3 style="color:#28a745">SHOPAI10</h3>
<p>10% off any order. Use anytime!</p>
</div>
<div style="background:#fff8f0;padding:20px;border-radius:8px;margin:15px 0;border:2px solid #fd7e14">
<h3 style="color:#fd7e14">FREESHIP50</h3>
<p>Free shipping on orders over $50</p>
</div>
<p style="text-align:center;margin-top:20px">
<a href="/collections/all" style="background:#007bff;color:white;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold">Start Shopping</a>
</p>"""

page = api_post('pages.json', {
    'page': {
        'title': 'Special Offers - Save Up To 20%',
        'body_html': page_html,
        'published': True,
    }
})
if page.get('page'):
    print('  Published: Special Offers page')
else:
    print('  {}'.format(str(page.get('error', ''))[:60]))

# 3. Collection descriptions
print()
print('=== COLLECTION DESCRIPTIONS ===')
collections = api_get('smart_collections.json')
updated = 0
for col in collections.get('smart_collections', []):
    if not col.get('body_html'):
        title = col['title']
        desc = '<p>Explore our <strong>{}</strong> collection. Carefully curated products with premium quality and fast shipping.</p><p>Use code <strong>WELCOME15</strong> for 15% off your first order!</p>'.format(title)
        url = 'https://{}/admin/api/2024-01/smart_collections/{}.json'.format(shop, col['id'])
        payload = json.dumps({'smart_collection': {'id': col['id'], 'body_html': desc}}).encode()
        req = urllib.request.Request(url, data=payload, method='PUT', headers=h)
        try:
            with urllib.request.urlopen(req, timeout=10):
                updated += 1
                print('  Updated: {}'.format(title))
        except Exception:
            pass
print('  Collections updated: {}'.format(updated))

print()
print('=== SUMMARY ===')
print('Blog posts published: {}'.format(published))
print('Landing page: created')
print('Collections: {} descriptions added'.format(updated))
