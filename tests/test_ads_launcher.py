"""Tests for engines.ads_launcher — W963-7."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from engines.ads_launcher import AdsLauncherEngine
from engines.ads_launcher.connect import connect_platform
from engines.ads_launcher.launcher import (
    _default_campaign_name,
    _platform_next_url,
    launch_first_campaign,
)
from engines.ads_launcher.status import (
    PlatformStatus,
    get_all_status,
    get_platform_status,
)


# ── Status diagnostic ──────────────────────────────────────


class TestStatus:
    def test_unknown_platform_returns_unknown_detail(self):
        s = get_platform_status("twitter")
        assert "unknown platform" in s.detail
        assert not s.ready

    def test_meta_missing_credentials(self):
        with patch.dict(os.environ, {}, clear=False):
            for k in (
                "META_ADS_ACCESS_TOKEN",
                "META_ADS_ACCOUNT_ID",
            ):
                os.environ.pop(k, None)
            with patch(
                "engines.ads_launcher.status._check_adapter_registered",
                return_value=False,
            ):
                s = get_platform_status("meta")
            assert not s.credentials_present
            assert "META_ADS_ACCESS_TOKEN" in s.env_vars_needed

    def test_all_status_returns_both_platforms(self):
        all_s = get_all_status()
        assert set(all_s.keys()) == {"meta", "google"}

    def test_ready_property(self):
        s = PlatformStatus(
            platform="meta",
            adapter_registered=True,
            credentials_present=True,
            account_resolved=True,
        )
        assert s.ready
        s.account_resolved = False
        assert not s.ready


# ── Connect helper ─────────────────────────────────────────


class TestConnect:
    def test_unknown_platform_rejected(self, tmp_path):
        res = connect_platform(
            platform="twitter",
            access_token="t",
            account_id="a",
            env_path=str(tmp_path / ".env"),
        )
        assert not res.success
        assert "unknown platform" in res.detail

    def test_missing_token_rejected(self, tmp_path):
        res = connect_platform(
            platform="meta",
            access_token="",
            account_id="act_1",
            env_path=str(tmp_path / ".env"),
        )
        assert not res.success

    def test_writes_to_env_file(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("OTHER_KEY=value\n")
        res = connect_platform(
            platform="meta",
            access_token="EAAB_TOKEN",
            account_id="act_123",
            env_path=str(env),
        )
        assert res.success
        content = env.read_text()
        assert "META_ADS_ACCESS_TOKEN=EAAB_TOKEN" in content
        assert "META_ADS_ACCOUNT_ID=act_123" in content
        assert "OTHER_KEY=value" in content  # preserved

    def test_replaces_existing_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("META_ADS_ACCESS_TOKEN=OLD\n")
        connect_platform(
            platform="meta",
            access_token="NEW",
            account_id="act_X",
            env_path=str(env),
        )
        content = env.read_text()
        assert "META_ADS_ACCESS_TOKEN=NEW" in content
        assert "OLD" not in content

    def test_sets_process_env(self, tmp_path):
        env_path = str(tmp_path / ".env")
        connect_platform(
            platform="meta",
            access_token="PROCESS_TOKEN",
            account_id="act_proc",
            env_path=env_path,
        )
        assert (
            os.environ.get("META_ADS_ACCESS_TOKEN")
            == "PROCESS_TOKEN"
        )


# ── Launcher ───────────────────────────────────────────────


class TestLauncher:
    def test_unknown_platform(self):
        res = launch_first_campaign(platform="twitter")
        assert not res.success
        assert "unsupported platform" in res.error

    def test_zero_budget_rejected(self):
        res = launch_first_campaign(
            platform="meta", daily_budget_usd=0,
        )
        assert not res.success
        assert ">= 1.0" in res.error

    def test_huge_budget_rejected(self):
        res = launch_first_campaign(
            platform="meta", daily_budget_usd=10000,
        )
        assert not res.success
        assert "safety cap" in res.error

    def test_non_numeric_budget_rejected(self):
        res = launch_first_campaign(
            platform="meta",
            daily_budget_usd="cheap",  # type: ignore[arg-type]
        )
        assert not res.success

    def test_router_unavailable_error(self):
        with patch(
            "core.adapters.router.get_router",
            side_effect=Exception("nope"),
        ):
            res = launch_first_campaign(
                platform="meta", daily_budget_usd=10,
            )
        assert not res.success
        assert "router" in res.error.lower()

    def test_successful_launch_returns_campaign_id(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True,
            data={"campaign_id": "12345"},
            error="",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            res = launch_first_campaign(
                platform="meta", daily_budget_usd=15,
            )
        assert res.success
        assert res.campaign_id == "12345"
        assert res.status == "PAUSED"
        assert res.daily_budget_usd == 15.0

    def test_adapter_failure_recorded(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=False, data=None, error="account not approved",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            res = launch_first_campaign(
                platform="meta", daily_budget_usd=10,
            )
        assert not res.success
        assert "account not approved" in res.error

    def test_default_campaign_name_format(self):
        name = _default_campaign_name("beauty")
        assert name.startswith("ShopAI-beauty-")
        assert len(name) >= len("ShopAI-beauty-20260101")

    def test_default_name_handles_missing_niche(self):
        name = _default_campaign_name(None)
        assert name.startswith("ShopAI-general-")

    def test_meta_next_url(self):
        url = _platform_next_url("meta", "12345")
        assert "business.facebook.com" in url
        assert "12345" in url

    def test_google_next_url(self):
        url = _platform_next_url("google", "C-X-1")
        assert "ads.google.com" in url

    def test_pause_is_always_set(self):
        """SAFETY: launched campaigns must always be PAUSED."""
        fake_router = MagicMock()
        fake_router.execute.return_value = MagicMock(
            ok=True, data={"campaign_id": "1"}, error="",
        )
        with patch(
            "core.adapters.router.get_router",
            return_value=fake_router,
        ), patch(
            "engines._writeback_recorder.record_writeback",
        ):
            launch_first_campaign(
                platform="meta", daily_budget_usd=10,
            )
        # Inspect the params the adapter saw.
        call_args = fake_router.execute.call_args
        params = call_args[0][1]
        assert params["status"] == "PAUSED"


# ── Engine Pattern Q envelope ──────────────────────────────


class TestEnginePatternQ:
    def test_empty_input_returns_status_action(self):
        result = AdsLauncherEngine().run({})
        assert result["status"] == "success"
        assert result["data"]["action"] == "status"
        assert "platforms" in result["data"]

    def test_none_input_returns_success(self):
        result = AdsLauncherEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_input_error(self):
        result = AdsLauncherEngine().run("nope")
        assert result["status"] == "error"

    def test_fail_upstream_short_circuits(self):
        result = AdsLauncherEngine().run({
            "status": "fail", "error": "broken",
        })
        assert result["status"] == "error"

    def test_unknown_action_error(self):
        result = AdsLauncherEngine().run({
            "data": {"action": "delete"},
        })
        assert result["status"] == "error"


class TestEngineLaunchAction:
    def test_launch_blocked_when_not_ready(self):
        with patch(
            "engines.ads_launcher.flow.get_platform_status",
            return_value=PlatformStatus(
                platform="meta",
                adapter_registered=False,
                detail="adapter not bootstrapped",
            ),
        ):
            result = AdsLauncherEngine().run({
                "data": {
                    "action": "launch",
                    "platform": "meta",
                    "daily_budget_usd": 10,
                },
            })
        data = result["data"]
        assert data["launched"] is False
        assert "bootstrapped" in data["blocked_reason"]

    def test_launch_proceeds_when_ready(self):
        ready_status = PlatformStatus(
            platform="meta",
            adapter_registered=True,
            credentials_present=True,
            account_resolved=True,
        )
        fake_res = MagicMock(
            success=True, campaign_id="12345",
            campaign_name="Test", daily_budget_usd=10.0,
            status="PAUSED",
            next_url="https://example.com/c/12345",
            error="",
        )
        with patch(
            "engines.ads_launcher.flow.get_platform_status",
            return_value=ready_status,
        ), patch(
            "engines.ads_launcher.flow.launch_first_campaign",
            return_value=fake_res,
        ):
            result = AdsLauncherEngine().run({
                "data": {
                    "action": "launch",
                    "platform": "meta",
                    "daily_budget_usd": 10,
                },
            })
        data = result["data"]
        assert data["launched"] is True
        assert data["campaign_id"] == "12345"
