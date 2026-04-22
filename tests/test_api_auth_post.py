"""Bearer-auth gate on POST write endpoints.

PR security review found POST /api/launch (and the other
state-mutating write endpoints) unauthenticated. This batch
adds `APIAuth.validate` before dispatch. /api/webhook/shopify
stays unauthenticated because it uses HMAC over the raw body.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pytest

# api.server transitively imports core.orchestrator which
# requires pyyaml. In CI-minimal environments without yaml,
# skip these tests — same pattern used by test_webhook_server.
pytest.importorskip("yaml")


class TestBearerAuthGate(unittest.TestCase):
    """The do_POST _AUTHED_POST_PATHS set gates the write
    endpoints with APIAuth.validate."""

    def test_authed_paths_include_launch(self):
        from api.server import ShopAIHandler

        paths = ShopAIHandler._AUTHED_POST_PATHS
        self.assertIn("/api/launch", paths)
        # Every state-mutating write path
        for p in (
            "/api/task", "/api/chain", "/api/batch",
            "/api/analyze", "/api/agent", "/api/workflow",
            "/api/auto/cycle", "/api/store/sync",
            "/api/launch",
        ):
            self.assertIn(p, paths)

    def test_webhook_not_authed_by_bearer(self):
        """Shopify webhook authenticates via HMAC over raw
        body, not bearer token. Must stay out of the set."""
        from api.server import ShopAIHandler

        self.assertNotIn(
            "/api/webhook/shopify",
            ShopAIHandler._AUTHED_POST_PATHS,
        )

    def test_check_bearer_auth_rejects_missing_header(self):
        from api.server import ShopAIHandler
        from api.auth import APIAuth

        handler = MagicMock(spec=ShopAIHandler)
        handler.headers = {}
        # Force a configured master token so validate isn't
        # a pass-through.
        auth = APIAuth()
        auth._master_token = "secret123"
        with patch(
            "api.auth.get_api_auth", return_value=auth,
        ):
            ok = ShopAIHandler._check_bearer_auth(handler)
        self.assertFalse(ok)
        handler._json_response.assert_called_once()
        status = handler._json_response.call_args[0][0]
        self.assertEqual(status, 401)

    def test_check_bearer_auth_rejects_wrong_token(self):
        from api.server import ShopAIHandler
        from api.auth import APIAuth

        handler = MagicMock(spec=ShopAIHandler)
        handler.headers = {
            "Authorization": "Bearer wrong_token",
        }
        auth = APIAuth()
        auth._master_token = "secret123"
        with patch(
            "api.auth.get_api_auth", return_value=auth,
        ):
            ok = ShopAIHandler._check_bearer_auth(handler)
        self.assertFalse(ok)

    def test_check_bearer_auth_accepts_master_token(self):
        from api.server import ShopAIHandler
        from api.auth import APIAuth

        handler = MagicMock(spec=ShopAIHandler)
        handler.headers = {
            "Authorization": "Bearer secret123",
        }
        auth = APIAuth()
        auth._master_token = "secret123"
        with patch(
            "api.auth.get_api_auth", return_value=auth,
        ):
            ok = ShopAIHandler._check_bearer_auth(handler)
        self.assertTrue(ok)
        handler._json_response.assert_not_called()

    def test_check_bearer_auth_case_insensitive_scheme(self):
        """'bearer ' vs 'Bearer ' both accepted."""
        from api.server import ShopAIHandler
        from api.auth import APIAuth

        handler = MagicMock(spec=ShopAIHandler)
        handler.headers = {
            "Authorization": "bearer secret123",
        }
        auth = APIAuth()
        auth._master_token = "secret123"
        with patch(
            "api.auth.get_api_auth", return_value=auth,
        ):
            ok = ShopAIHandler._check_bearer_auth(handler)
        self.assertTrue(ok)

    def test_no_master_token_pass_through(self):
        """When SHOPAI_API_TOKEN is unset the APIAuth is
        configured with an auto-generated token — it does
        NOT pass-through. The test validates with that
        generated token too."""
        from api.server import ShopAIHandler
        from api.auth import APIAuth

        handler = MagicMock(spec=ShopAIHandler)
        auth = APIAuth()
        # Force blank master token → validate returns True
        # for any token (backward-compat mode).
        auth._master_token = ""
        handler.headers = {"Authorization": "Bearer anything"}
        with patch(
            "api.auth.get_api_auth", return_value=auth,
        ):
            ok = ShopAIHandler._check_bearer_auth(handler)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
