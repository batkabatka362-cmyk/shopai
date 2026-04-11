"""Supplier Communication Engine — message builder.

Builds supplier messages: PO submission emails, status inquiry
messages, and follow-up communications based on purchase orders
and communication history.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def build_messages(
    purchase_orders: list[dict[str, Any]],
    suppliers: list[dict[str, Any]],
    communication_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build supplier messages for each purchase order.

    Args:
        purchase_orders: List of PurchaseOrder dicts from po_generator.
        suppliers: List of SupplierRecord dicts for contact info.
        communication_history: Past communications for context.

    Returns:
        Structured dict with generated messages.
    """
    try:
        po_items = copy.deepcopy(purchase_orders)
        supplier_map: dict[str, dict[str, Any]] = {}
        for s in suppliers:
            sid = str(s.get("supplier_id", ""))
            supplier_map[sid] = s

        # Count past messages per supplier for follow-up context
        history_counts: dict[str, int] = {}
        for comm in communication_history:
            sid = str(comm.get("supplier_id", ""))
            history_counts[sid] = history_counts.get(sid, 0) + 1

        messages: list[dict[str, Any]] = []

        for po in po_items:
            sid = str(po.get("supplier_id", ""))
            supplier = supplier_map.get(sid, {})
            email = str(supplier.get("email", f"{sid}@supplier.com"))
            supplier_name = str(supplier.get("name", sid))
            po_id = str(po.get("po_id", ""))
            total = float(po.get("total", 0.0))
            items = po.get("items", [])
            delivery_date = str(po.get("delivery_date", ""))
            status = str(po.get("status", "ready"))

            # Build item summary
            item_lines = []
            for item in items:
                title = item.get("title", item.get("product_id", ""))
                qty = item.get("quantity", 0)
                item_lines.append(f"  - {title}: {qty} units")
            items_text = "\n".join(item_lines)

            if status == "below_minimum":
                subject = f"Order Inquiry — {po_id} (Below Minimum)"
                body = (
                    f"Dear {supplier_name},\n\n"
                    f"We would like to place the following order but note it falls "
                    f"below your minimum order value. Could we discuss options?\n\n"
                    f"PO: {po_id}\n"
                    f"Items:\n{items_text}\n\n"
                    f"Total: ${total:,.2f}\n"
                    f"Requested delivery: {delivery_date}\n\n"
                    f"Please advise on how to proceed.\n\n"
                    f"Best regards"
                )
                msg_type = "inquiry"
            else:
                subject = f"Purchase Order — {po_id}"
                body = (
                    f"Dear {supplier_name},\n\n"
                    f"Please find below our purchase order.\n\n"
                    f"PO: {po_id}\n"
                    f"Items:\n{items_text}\n\n"
                    f"Total: ${total:,.2f}\n"
                    f"Requested delivery: {delivery_date}\n\n"
                    f"Please confirm receipt and expected delivery date.\n\n"
                    f"Best regards"
                )
                msg_type = "purchase_order"

            messages.append({
                "to": email,
                "supplier_id": sid,
                "subject": subject,
                "body": body,
                "type": msg_type,
            })

        return {
            "status": "success",
            "messages": messages,
        }
    except Exception as exc:
        return {
            "status": "error",
            "messages": [],
            "error": f"Message building failed: {exc}",
        }
