"""One-shot: dispatch 14 yesterday's beauty proposals with
W963-169/170 metadata injected (image_query + publish_on_approve)."""
from __future__ import annotations

import sys
from pathlib import Path

# Make the repo root importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from core.context import active_store
from core.adapters.shopify.bootstrap import (
    register_all as shopify_register,
)
from core.adapters.image.bootstrap import (
    register_all as image_register,
)
from core.approval import get_approval_queue
from core.approval.dispatchers import (
    _create_draft_product_dispatch,
)
from engines.product_sourcer.draft_creator import (
    _build_image_query,
)


def main() -> None:
    shopify_register()
    image_register()
    queue = get_approval_queue()
    from core.approval import ApprovalStatus
    pending = queue.list_by_status(
        ApprovalStatus.PENDING, limit=200,
    )
    beauty_proposals = [
        a for a in pending
        if a.action_type == "create_draft_product"
    ]
    print(
        f"Found {len(beauty_proposals)} pending "
        "product proposals",
    )

    with active_store("main"):
        for action in beauty_proposals:
            params = dict(action.params)
            metadata = dict(params.get("_metadata") or {})
            name = params.get("title", "")
            niche = metadata.get("niche", "beauty")
            metadata.setdefault(
                "image_query",
                _build_image_query(
                    {"name": name}, niche,
                ),
            )
            metadata.setdefault("image_count", 1)
            metadata["publish_on_approve"] = True
            params["_metadata"] = metadata

            try:
                queue.approve(
                    action.id,
                    decided_by="session_batch",
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  approve failed for {action.id}: {exc}")
                continue

            ok, result = _create_draft_product_dispatch(
                params,
            )

            try:
                queue.attach_result(
                    action.id,
                    success=ok,
                    result=(
                        result if isinstance(result, dict)
                        else {}
                    ),
                )
            except Exception:  # noqa: BLE001
                pass

            price = result.get("price_set_value", "")
            imgs = result.get("images_attached", 0)
            published = result.get("published", False)
            verdict = (
                "OK" if ok and published
                else "PARTIAL" if ok else "FAIL"
            )
            print(
                f"  {verdict} {name[:38]:<38} "
                f"${price} imgs={imgs} pub={published}"
            )


if __name__ == "__main__":
    main()
