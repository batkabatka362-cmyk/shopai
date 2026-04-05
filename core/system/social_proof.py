"""Social Proof Engine — boost conversions with urgency and trust signals.

Generates Shopify ScriptTag or theme snippets for:
  - "X people bought today" popups
  - "Only N left!" urgency
  - Trust badges
  - Recent purchase notifications
"""
from __future__ import annotations
import json
import time
import urllib.request
from typing import Any
from utils.logger import get_logger
logger = get_logger("social_proof")


class SocialProofEngine:
    """Generates and installs social proof elements."""

    def generate_proof_data(self, products: list[dict],
                            orders: list[dict]) -> dict[str, Any]:
        """Generate social proof data from real store data."""
        proofs = []

        # Low stock urgency
        for p in products:
            inv = int(p.get("inventory_quantity", 0))
            name = p.get("title", p.get("name", ""))
            if 0 < inv <= 10:
                proofs.append({
                    "type": "urgency",
                    "product_id": str(p.get("id", "")),
                    "message": "Only {} left in stock!".format(inv),
                    "product": name[:30],
                    "priority": "high" if inv <= 3 else "medium",
                })

        # Recent purchases (from orders)
        for o in orders[:5]:
            items = o.get("line_items", [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        proofs.append({
                            "type": "recent_purchase",
                            "message": "Someone just bought {}!".format(
                                item.get("title", item.get("name", "a product"))[:30]),
                            "priority": "medium",
                        })

        # Popularity signals
        total_products = len(products)
        if total_products > 0:
            proofs.append({
                "type": "trust",
                "message": "{} products in our curated collection".format(total_products),
                "priority": "low",
            })

        # Discount urgency
        proofs.append({
            "type": "urgency",
            "message": "Use WELCOME15 for 15% off — limited time!",
            "priority": "high",
        })

        return {
            "proofs": proofs,
            "total": len(proofs),
            "by_type": {
                "urgency": sum(1 for p in proofs if p["type"] == "urgency"),
                "recent_purchase": sum(1 for p in proofs if p["type"] == "recent_purchase"),
                "trust": sum(1 for p in proofs if p["type"] == "trust"),
            },
        }

    def generate_popup_script(self, proofs: list[dict]) -> str:
        """Generate JavaScript for social proof popups."""
        urgency = [p for p in proofs if p["type"] == "urgency"]
        purchases = [p for p in proofs if p["type"] == "recent_purchase"]

        messages_js = json.dumps([p["message"] for p in (urgency + purchases)[:10]])

        script = """
(function() {
  var messages = MSG;
  var idx = 0;
  function showPopup(msg) {
    var d = document.createElement('div');
    d.style.cssText = 'position:fixed;bottom:20px;left:20px;background:#1a1a2e;color:white;padding:16px 24px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.3);z-index:99999;font-family:sans-serif;font-size:14px;max-width:300px;animation:slideIn 0.5s ease';
    d.innerHTML = '<div style="display:flex;align-items:center;gap:8px"><span style="font-size:18px">ICON</span><span>' + msg + '</span></div>';
    document.body.appendChild(d);
    setTimeout(function() { d.remove(); }, 5000);
  }
  var style = document.createElement('style');
  style.textContent = '@keyframes slideIn{from{transform:translateX(-100%);opacity:0}to{transform:translateX(0);opacity:1}}';
  document.head.appendChild(style);
  setInterval(function() {
    if (idx < messages.length) { showPopup(messages[idx]); idx++; }
    else { idx = 0; }
  }, 15000);
  setTimeout(function() { showPopup(messages[0]); }, 3000);
})();
""".replace("MSG", messages_js).replace("ICON", "\ud83d\udd25")

        return script

    def install_script_tag(self, shop_url: str, token: str,
                           script_content: str) -> dict:
        """Install social proof script via Shopify ScriptTag API."""
        # Create a hosted script (inline via script tag)
        h = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

        # Store script as asset or use inline approach
        # For now, create a script tag pointing to our API
        payload = json.dumps({
            "script_tag": {
                "event": "onload",
                "src": "https://cdn.jsdelivr.net/npm/noop3@latest/index.js",  # placeholder
                "display_scope": "online_store",
            }
        }).encode()

        url = "https://{}/admin/api/2024-01/script_tags.json".format(shop_url)
        req = urllib.request.Request(url, data=payload, method="POST", headers=h)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            return {"error": str(exc)[:80]}

    def get_stats(self):
        return {"engine": "social_proof", "active": True}


_instance = None
def get_social_proof():
    global _instance
    if _instance is None:
        _instance = SocialProofEngine()
    return _instance
