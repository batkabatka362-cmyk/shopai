"""Tests for engines.email_connect — W963-8."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from engines.email_connect import EmailConnectEngine
from engines.email_connect.connect import connect_provider
from engines.email_connect.sender import send_test_email
from engines.email_connect.status import (
    ProviderStatus,
    get_all_status,
    get_provider_status,
)


# ── Status diagnostic ──────────────────────────────────────


class TestStatus:
    def test_unknown_provider_returns_unknown_detail(self):
        s = get_provider_status("mailchimp")
        assert "unknown provider" in s.detail
        assert not s.ready

    def test_brevo_no_key_no_adapter_state(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BREVO_API_KEY", None)
            s = get_provider_status("brevo")
        assert not s.credentials_present
        assert "BREVO_API_KEY" in s.detail or "missing" in s.detail

    def test_all_status_returns_4_providers(self):
        all_s = get_all_status()
        assert set(all_s.keys()) == {
            "brevo", "resend", "sendgrid", "klaviyo",
        }

    def test_ready_property(self):
        s = ProviderStatus(
            provider="brevo", env_var="BREVO_API_KEY",
            adapter_wired=True,
            credentials_present=True,
        )
        assert s.ready
        s.credentials_present = False
        assert not s.ready


# ── Connect helper ─────────────────────────────────────────


class TestConnect:
    def test_unknown_provider(self, tmp_path):
        res = connect_provider(
            provider="mailchimp", api_key="K",
            env_path=str(tmp_path / ".env"),
        )
        assert not res.success
        assert "unknown provider" in res.detail

    def test_missing_key_rejected(self, tmp_path):
        res = connect_provider(
            provider="brevo", api_key="",
            env_path=str(tmp_path / ".env"),
        )
        assert not res.success

    def test_writes_to_env(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("OTHER=v\n")
        res = connect_provider(
            provider="brevo", api_key="abc-xyz",
            env_path=str(env),
        )
        assert res.success
        content = env.read_text()
        assert "BREVO_API_KEY=abc-xyz" in content
        assert "OTHER=v" in content

    def test_replaces_existing_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("BREVO_API_KEY=OLD\n")
        connect_provider(
            provider="brevo", api_key="NEW",
            env_path=str(env),
        )
        assert "BREVO_API_KEY=NEW" in env.read_text()
        assert "OLD" not in env.read_text()

    def test_sets_process_env(self, tmp_path):
        connect_provider(
            provider="resend", api_key="PROC_KEY",
            env_path=str(tmp_path / ".env"),
        )
        assert os.environ.get("RESEND_API_KEY") == "PROC_KEY"


# ── Send-test helper ──────────────────────────────────────


class TestSendTest:
    def test_invalid_to_rejected(self):
        res = send_test_email(to="not-an-email")
        assert not res.success
        assert "valid email" in res.detail

    def test_router_unavailable(self):
        with patch(
            "core.adapters.router.get_router",
            side_effect=Exception("nope"),
        ):
            res = send_test_email(to="ok@example.com")
        assert not res.success
        assert "router" in res.detail.lower()

    def test_successful_send(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True, data={"message_id": "abc-123"}, error="",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            res = send_test_email(to="ok@example.com")
        assert res.success
        assert res.message_id == "abc-123"

    def test_adapter_failure(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=False, data=None, error="provider unauthorized",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            res = send_test_email(to="ok@example.com")
        assert not res.success
        assert "unauthorized" in res.detail


# ── Engine Pattern Q envelope ──────────────────────────────


class TestEngineEnvelope:
    def test_empty_input_returns_status(self):
        result = EmailConnectEngine().run({})
        assert result["status"] == "success"
        assert result["data"]["action"] == "status"

    def test_none_input_success(self):
        result = EmailConnectEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_error(self):
        result = EmailConnectEngine().run("nope")
        assert result["status"] == "error"

    def test_fail_upstream_short_circuits(self):
        result = EmailConnectEngine().run({
            "status": "fail", "error": "broken",
        })
        assert result["status"] == "error"

    def test_unknown_action_error(self):
        result = EmailConnectEngine().run({
            "data": {"action": "delete"},
        })
        assert result["status"] == "error"


class TestEngineSendTest:
    def test_missing_to_field(self):
        result = EmailConnectEngine().run({
            "data": {"action": "send-test"},
        })
        assert result["status"] == "error"

    def test_send_succeeds(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True, data={"message_id": "m1"}, error="",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            result = EmailConnectEngine().run({
                "data": {
                    "action": "send-test",
                    "to": "x@example.com",
                },
            })
        assert result["data"]["sent"] is True
