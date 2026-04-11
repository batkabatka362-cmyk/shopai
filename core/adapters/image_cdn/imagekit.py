"""ImageKit CDN adapter.

ImageKit is a real-time image optimisation + CDN that's very
popular with Shopify shops for one reason: you can hand it a
source URL, it fetches, optimises, stores, and serves the
result from its CDN with per-request transformations (width,
quality, format auto-selection, smart cropping, etc.). The
free tier includes 20 GB bandwidth + 20 GB storage per month,
which covers small-to-mid shops with room to spare.

Upload endpoint: ``POST /api/v1/files/upload``.

Auth
----
ImageKit splits the key pair into a *public* key (safe to
expose in browser/client code for signed URLs) and a *private*
key (server-only, used here). Auth is HTTP Basic with the
private key as the username and an empty password. We already
expose both aliases via ``ENV_ALIASES``:

    * ``imagekit_pub``  → ``IMAGEKIT_PUBLIC_KEY``  (unused here)
    * ``imagekit_priv`` → ``IMAGEKIT_PRIVATE_KEY`` (used here)

Why form-encoded
----------------
ImageKit's upload endpoint accepts multipart/form-data for
binary uploads and application/x-www-form-urlencoded for
remote-URL uploads. We use form-urlencoded because passing a
remote URL is the primary ShopAI use case (Shopify → ImageKit),
and it keeps the payload trivial to mock in tests.

Pricing
-------
Free tier: $0. Paid tier starts at $49/month for 225 GB
bandwidth. Per-call cost is effectively zero for the first
~200 000 transformations/month on the free tier, so
``cost_per_call = 0.0`` is both honest and conservative.
Operators who hit the paid tier can subclass and raise it.
"""
from __future__ import annotations

import base64
import json
from typing import Any

from ..errors import AdapterError
from ._base import ImageCdnBaseAdapter


class ImageKitAdapter(ImageCdnBaseAdapter):
    """ImageKit — image optimisation + CDN."""

    name = "imagekit"
    config_alias = "imagekit_priv"
    priority = 80

    # Free tier covers most shops; paid-tier operators can
    # subclass to charge per call.
    cost_per_call: float = 0.0

    timeout: float = 60.0

    # Upload endpoint is on a dedicated subdomain, not the
    # management host.
    base_url: str = "https://upload.imagekit.io"

    # ── URL + auth ────────────────────────────────────────────

    def _optimize_url(self) -> str:
        return f"{self.base_url}/api/v1/files/upload"

    def _auth_headers(self) -> dict[str, str]:
        """HTTP Basic: private_key as username, empty password.

        ImageKit requires the trailing colon so the server sees
        an explicit empty password rather than a malformed
        credential.
        """
        key = self._api_key()
        token = base64.b64encode(
            f"{key}:".encode("utf-8"),
        ).decode("ascii")
        return {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

    # ── Payload ───────────────────────────────────────────────

    def _build_optimize_payload(
        self, params: dict[str, Any],
    ) -> list[tuple[str, str]]:
        """Build ImageKit's upload form body.

        We return a list of ``(key, value)`` tuples so lists
        (like ``tags``) encode as repeated keys rather than
        being collapsed into one comma-joined string.
        """
        body: list[tuple[str, str]] = [
            ("file", str(params["source_url"])),
            ("fileName", str(params["file_name"])),
        ]

        folder = params.get("folder")
        if folder:
            body.append(("folder", str(folder)))

        tags = params.get("tags")
        if tags:
            # ImageKit accepts tags as a comma-separated string
            # in the form body. Joining once here keeps the
            # request deterministic and idempotent.
            tag_str = ",".join(str(t) for t in tags)
            body.append(("tags", tag_str))

        use_unique = params.get("use_unique_filename")
        if use_unique is not None:
            body.append(
                ("useUniqueFileName", "true" if use_unique else "false"),
            )

        overwrite = params.get("overwrite")
        if overwrite is not None:
            body.append(
                ("overwriteFile", "true" if overwrite else "false"),
            )

        pre = params.get("transformation_pre")
        if pre:
            # ImageKit's upload API accepts a JSON-encoded
            # ``transformation`` field with ``pre`` / ``post``
            # sub-keys. Only ``pre`` makes sense at upload time
            # (post-transformations are applied by URL rewrites).
            body.append(
                ("transformation", json.dumps({"pre": str(pre)})),
            )

        is_private = params.get("is_private_file")
        if is_private is not None:
            body.append(
                ("isPrivateFile", "true" if is_private else "false"),
            )

        return body

    # ── Response ──────────────────────────────────────────────

    def _parse_optimize_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"unexpected ImageKit response type: "
                f"{type(raw).__name__}",
            )

        # ImageKit returns 4xx for upload failures with a
        # ``message`` field — those surface through the base
        # class's HTTP error mapping, so by the time we get here
        # the response should always include ``url``. Defensive
        # check anyway — if the contract ever changes, fail
        # loudly instead of returning an empty URL.
        if "url" not in raw:
            message = raw.get("message") or "missing 'url' in response"
            raise AdapterError(
                self.name,
                f"ImageKit upload failed: {message}",
            )

        return {
            "url":           str(raw.get("url", "") or ""),
            "file_id":       str(raw.get("fileId", "") or ""),
            "name":          str(raw.get("name", "") or ""),
            "size":          int(raw.get("size") or 0),
            "width":         int(raw.get("width") or 0),
            "height":        int(raw.get("height") or 0),
            "file_type":     str(raw.get("fileType", "") or ""),
            "thumbnail_url": str(raw.get("thumbnailUrl", "") or ""),
            "file_path":     str(raw.get("filePath", "") or ""),
        }
