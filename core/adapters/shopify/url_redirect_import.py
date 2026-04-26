"""ShopifyUrlRedirectImportAdapter — bulk-import redirects from CSV.

Companion to ``url_redirects.py`` (Phase 25.4 — single-redirect CRUD
+ bulk-delete by ids/search/saved-search/all). The IMPORT side handles
the other bulk write — bringing in N redirects at once from a CSV
file. Two-step flow:

  1. ``urlRedirectImportCreate(url: URL!)`` — Shopify fetches the
     CSV at the supplied URL, parses it, returns a
     ``UrlRedirectImport`` with a preview of the first few rows
     plus counts (total / would-create / would-update / would-fail).
     Nothing is applied yet.
  2. ``urlRedirectImportSubmit(id: ID!)`` — apply the parsed import.
     Returns an async Job. The actual writes happen in the
     background; callers poll status via the GET capability.

ShopAI's migration engine uses these whenever the merchant exports
their old shop's URL redirect table (or generates one from a sitemap
diff after a relaunch) and uploads it as CSV.

Capabilities:

  * ``SHOPIFY_CREATE_URL_REDIRECT_IMPORT`` — urlRedirectImportCreate.
    URL at field level. Returns the import id + preview rows.
  * ``SHOPIFY_SUBMIT_URL_REDIRECT_IMPORT`` — urlRedirectImportSubmit.
    Pattern A: id at field level. Returns the async Job.
  * ``SHOPIFY_GET_URL_REDIRECT_IMPORT``    — urlRedirectImport query.
    Poll the import for finished / counts / preview.

Friendly call shape (create)::

    {"url": "https://mybucket.s3.example.com/redirects.csv"}

Pattern A — id / url at field level on each mutation.
Pattern F — UrlRedirectImportUserError carries `code`.

Pattern E note: gated by ``write_online_store_navigation`` (same as
url_redirects.py).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_IMPORT_FIELDS = """
id
count
createdCount
updatedCount
failedCount
finished
finishedAt
previewRedirects {
  path
  target
}
""".strip()


_CREATE_MUTATION = f"""
mutation urlRedirectImportCreate($url: URL!) {{
  urlRedirectImportCreate(url: $url) {{
    urlRedirectImport {{
      {_IMPORT_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_SUBMIT_MUTATION = """
mutation urlRedirectImportSubmit($id: ID!) {
  urlRedirectImportSubmit(id: $id) {
    job {
      id
      done
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_GET_QUERY = f"""
query urlRedirectImport($id: ID!) {{
  urlRedirectImport(id: $id) {{
    {_IMPORT_FIELDS}
  }}
}}
""".strip()


class ShopifyUrlRedirectImportAdapter(ShopifyBaseAdapter):
    name = "shopify_url_redirect_import"
    capabilities = {
        Capability.SHOPIFY_CREATE_URL_REDIRECT_IMPORT,
        Capability.SHOPIFY_SUBMIT_URL_REDIRECT_IMPORT,
        Capability.SHOPIFY_GET_URL_REDIRECT_IMPORT,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_CREATE_URL_REDIRECT_IMPORT:
            return self._create(params)
        if capability == \
                Capability.SHOPIFY_SUBMIT_URL_REDIRECT_IMPORT:
            return self._submit(params)
        if capability == Capability.SHOPIFY_GET_URL_REDIRECT_IMPORT:
            return self._get(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        url = (
            params.get("url")
            or params.get("csv_url")
            or params.get("source_url")
        )
        if not isinstance(url, str) or not url.strip():
            raise AdapterValidationError(
                self.name,
                "'url' is required (publicly-accessible CSV with "
                "two columns: from-path, target-path)",
            )
        if not url.strip().startswith(("https://", "http://")):
            raise AdapterValidationError(
                self.name,
                "'url' must be an absolute http(s) URL",
            )
        data = self._gql(_CREATE_MUTATION, {"url": url.strip()})
        self._check_user_errors(data, "urlRedirectImportCreate")
        payload = data.get("urlRedirectImportCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_URL_REDIRECT_IMPORT,
            data={
                "import": self._normalise(
                    payload.get("urlRedirectImport") or {},
                ),
            },
        )

    # ── Submit ─────────────────────────────────────────────────────

    def _submit(self, params: dict[str, Any]) -> Any:
        import_id = self._extract_id(params)
        data = self._gql(_SUBMIT_MUTATION, {"id": import_id})
        self._check_user_errors(data, "urlRedirectImportSubmit")
        payload = data.get("urlRedirectImportSubmit") or {}
        job = payload.get("job") or {}
        return self._success(
            Capability.SHOPIFY_SUBMIT_URL_REDIRECT_IMPORT,
            data={
                "import_id": import_id,
                "job_id": (
                    job.get("id", "") if isinstance(job, dict) else ""
                ) or "",
                "job_done": bool(
                    job.get("done", False)
                    if isinstance(job, dict) else False
                ),
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        import_id = self._extract_id(params)
        data = self._gql(_GET_QUERY, {"id": import_id})
        node = data.get("urlRedirectImport") or {}
        return self._success(
            Capability.SHOPIFY_GET_URL_REDIRECT_IMPORT,
            data={
                "import": self._normalise(node),
                "found": bool(node),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_id(self, params: dict[str, Any]) -> str:
        import_id = (
            params.get("id")
            or params.get("import_id")
            or params.get("urlRedirectImportId")
        )
        if not isinstance(import_id, str) or not import_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the URL redirect import "
                "returned by create) is required",
            )
        return import_id.strip()

    @staticmethod
    def _normalise(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        previews_raw = node.get("previewRedirects") or []
        previews = []
        for p in previews_raw:
            if isinstance(p, dict):
                previews.append({
                    "path": p.get("path", "") or "",
                    "target": p.get("target", "") or "",
                })
        return {
            "id": node.get("id", "") or "",
            "count": int(node.get("count", 0) or 0),
            "created_count": int(node.get("createdCount", 0) or 0),
            "updated_count": int(node.get("updatedCount", 0) or 0),
            "failed_count": int(node.get("failedCount", 0) or 0),
            "finished": bool(node.get("finished", False)),
            "finished_at": node.get("finishedAt", "") or "",
            "preview_redirects": previews,
        }
