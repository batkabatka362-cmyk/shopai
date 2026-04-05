"""Add cross-sell to ALL products missing it."""
import os, json, urllib.request, sys

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

products = json.loads(urllib.request.urlopen(
    urllib.request.Request('https://{}/admin/api/2024-01/products.json?limit=50'.format(shop), headers=h),
    timeout=10).read())['products']

# Group by category
by_cat = {}
for p in products:
    cat = p.get('product_type', 'General')
    by_cat.setdefault(cat, []).append(p)

updated = 0
for p in products:
    pid = p['id']
    current = p.get('body_html', '') or ''

    if 'might also like' in current:
        continue

    cat = p.get('product_type', '')
    related = [r for r in by_cat.get(cat, []) if r['id'] != pid][:3]
    if not related:
        # Get from other categories
        all_others = [r for r in products if r['id'] != pid]
        related = all_others[:3]

    if not related:
        continue

    cross_html = '\n<hr>\n<h3>You might also like</h3>\n<ul>\n'
    for r in related:
        rname = r['title']
        rhandle = r.get('handle', '')
        rprice = r['variants'][0]['price'] if r.get('variants') else '0'
        cross_html += '<li><a href="/products/{}">{}</a> - ${}</li>\n'.format(
            rhandle, rname, rprice)
    cross_html += '</ul>\n'

    new_desc = current + cross_html
    url = 'https://{}/admin/api/2024-01/products/{}.json'.format(shop, pid)
    payload = json.dumps({'product': {'id': pid, 'body_html': new_desc}}).encode()
    req = urllib.request.Request(url, data=payload, method='PUT', headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10):
            updated += 1
            print('Cross-sell added: {}'.format(p['title'][:35]))
    except Exception as e:
        print('Error {}: {}'.format(pid, e))

print('\nTotal: {}/{} products now have cross-sell'.format(
    updated + sum(1 for p in products if 'might also like' in (p.get('body_html','') or '')),
    len(products)))
