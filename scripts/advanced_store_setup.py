"""Advanced store setup — redirects, navigation, draft orders, tracking."""
import os, json, urllib.request, sys, time

with open('.env') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ[k] = v

from core.auth.shopify_auth import ShopifyAuth
auth = ShopifyAuth(os.environ['SHOPAI_SHOPIFY_URL'],
                   os.environ['SHOPAI_SHOPIFY_CLIENT_ID'],
                   os.environ['SHOPAI_SHOPIFY_CLIENT_SECRET'])
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
    req = urllib.request.Request(
        'https://{}/admin/api/2024-01/{}'.format(shop, path), headers=h)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# ===== 1. URL REDIRECTS for SEO =====
print('=== 1. URL REDIRECTS ===')
redirects = [
    ('/sale', '/pages/special-offers-save-up-to-20'),
    ('/deals', '/pages/special-offers-save-up-to-20'),
    ('/discount', '/pages/special-offers-save-up-to-20'),
    ('/reviews', '/pages/customer-reviews'),
    ('/faq', '/pages/faq-frequently-asked-questions'),
    ('/about', '/pages/about-us-ai-powered-store'),
    ('/help', '/pages/faq-frequently-asked-questions'),
]
created = 0
for old, new in redirects:
    result = api_post('redirects.json', {
        'redirect': {'path': old, 'target': new}
    })
    if result.get('redirect'):
        created += 1
        print('  {} -> {}'.format(old, new))
    elif 'already exists' in str(result.get('error', '')):
        print('  {} already exists'.format(old))
    else:
        print('  Error {}: {}'.format(old, str(result.get('error', ''))[:50]))
print('Redirects created: {}'.format(created))

# ===== 2. DRAFT ORDER for testing learning system =====
print()
print('=== 2. DRAFT ORDER (test) ===')
products = api_get('products.json?limit=5')['products']
if products:
    p = products[0]
    vid = p['variants'][0]['id']
    draft = api_post('draft_orders.json', {
        'draft_order': {
            'line_items': [{'variant_id': vid, 'quantity': 1}],
            'note': 'AI test order - ShopAI system verification',
            'tags': 'shopai-test, ai-generated',
        }
    })
    if draft.get('draft_order'):
        print('  Draft order created: #{}'.format(draft['draft_order'].get('name', '?')))
        print('  Product: {}'.format(p['title'][:40]))
        print('  Total: ${}'.format(draft['draft_order'].get('total_price', '?')))
    else:
        print('  {}'.format(str(draft.get('error', ''))[:60]))

# ===== 3. NAVIGATION MENUS =====
print()
print('=== 3. NAVIGATION CHECK ===')
try:
    # Use GraphQL to check navigation
    query = '{ menu(handle: "main-menu") { id title items { title url } } }'
    payload = json.dumps({'query': query}).encode()
    req = urllib.request.Request(
        'https://{}/admin/api/2024-01/graphql.json'.format(shop),
        data=payload, headers=h)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
        menu = data.get('data', {}).get('menu', {})
        if menu:
            print('  Main menu: {}'.format(menu.get('title', '?')))
            for item in menu.get('items', []):
                print('    {} -> {}'.format(item.get('title', '?'), item.get('url', '?')[:40]))
        else:
            print('  No main menu found (or GraphQL access limited)')
            print('  Response: {}'.format(str(data)[:200]))
except Exception as e:
    print('  Navigation: {}'.format(str(e)[:80]))

# ===== 4. STORE POLICIES CHECK =====
print()
print('=== 4. STORE POLICIES ===')
try:
    policies = api_get('policies.json')
    for pol in policies.get('policies', []):
        has_body = bool(pol.get('body', '').strip())
        print('  {} (has content: {})'.format(pol.get('title', '?'), has_body))
except Exception as e:
    print('  {}'.format(e))

# ===== 5. SITEMAP INFO =====
print()
print('=== 5. SITEMAP ===')
print('  Shopify auto-generates sitemap at:')
print('  https://{}/sitemap.xml'.format(shop))
print('  Submit to Google Search Console for indexing')

# ===== FINAL SUMMARY =====
print()
print('=' * 50)
print('ADVANCED SETUP COMPLETE')
print('=' * 50)
