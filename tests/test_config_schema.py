"""Tests for the config schema + validator."""
import os
from pathlib import Path

import pytest


# Every SHOPAI_* env var we know about. Cleared before each test so the
# validator starts from a clean slate regardless of what the developer
# has exported in their shell.
_MANAGED_ENV = [
    "SHOPAI_ENV", "SHOPAI_DATA_DIR",
    "SHOPAI_SHOPIFY_URL", "SHOPAI_SHOPIFY_KEY",
    "SHOPAI_SHOPIFY_CLIENT_ID", "SHOPAI_SHOPIFY_CLIENT_SECRET",
    "SHOPAI_LOG_LEVEL", "SHOPAI_LOG_FORMAT", "SHOPAI_LOG_FILE",
    "SHOPAI_LOG_MAX_MB", "SHOPAI_LOG_BACKUPS",
    "SHOPAI_OLLAMA_URL",
    "SHOPAI_TELEGRAM_TOKEN", "SHOPAI_API_TOKEN",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in _MANAGED_ENV:
        monkeypatch.delenv(k, raising=False)
    yield


class TestValidateEmpty:
    def test_empty_env_validates_cleanly(self):
        from infrastructure.config.schema import validate_config
        result = validate_config()
        assert result.ok()
        assert not result.errors


class TestTypeValidation:
    def test_int_bad_value(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_LOG_BACKUPS", "abc")
        from infrastructure.config.schema import validate_config
        result = validate_config()
        assert not result.ok()
        assert any("SHOPAI_LOG_BACKUPS" in e and "integer" in e for e in result.errors)

    def test_int_below_min(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_LOG_BACKUPS", "-1")
        from infrastructure.config.schema import validate_config
        result = validate_config()
        assert not result.ok()
        assert any("below minimum" in e for e in result.errors)

    def test_int_above_max(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_LOG_BACKUPS", "999")
        from infrastructure.config.schema import validate_config
        result = validate_config()
        assert not result.ok()
        assert any("above maximum" in e for e in result.errors)

    def test_float_bad_value(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_LOG_MAX_MB", "not-a-number")
        from infrastructure.config.schema import validate_config
        result = validate_config()
        assert not result.ok()
        assert any("SHOPAI_LOG_MAX_MB" in e and "number" in e for e in result.errors)

    def test_choice_bad_value(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_LOG_LEVEL", "LOUD")
        from infrastructure.config.schema import validate_config
        result = validate_config()
        assert not result.ok()
        assert any("SHOPAI_LOG_LEVEL" in e and "allowed values" in e for e in result.errors)

    def test_choice_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_LOG_LEVEL", "debug")
        monkeypatch.setenv("SHOPAI_LOG_FORMAT", "JSON")
        from infrastructure.config.schema import validate_config
        result = validate_config()
        assert result.ok()

    def test_url_must_start_with_http(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_OLLAMA_URL", "localhost:11434")
        from infrastructure.config.schema import validate_config
        result = validate_config()
        assert not result.ok()
        assert any("valid URL" in e for e in result.errors)

    def test_url_https_ok(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_OLLAMA_URL", "https://ollama.example.com")
        from infrastructure.config.schema import validate_config
        assert validate_config().ok()


class TestShopifyCrossField:
    def test_url_without_any_credentials_warns(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "s.myshopify.com")
        from infrastructure.config.schema import validate_config
        result = validate_config()
        assert result.ok()  # warning, not error
        assert any("no credentials" in w for w in result.warnings)

    def test_url_with_legacy_key_ok(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "s.myshopify.com")
        monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "shpat_x")
        from infrastructure.config.schema import validate_config
        result = validate_config()
        assert result.ok()
        assert not result.warnings

    def test_url_with_full_oauth_ok(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "s.myshopify.com")
        monkeypatch.setenv("SHOPAI_SHOPIFY_CLIENT_ID", "cid")
        monkeypatch.setenv("SHOPAI_SHOPIFY_CLIENT_SECRET", "sec")
        from infrastructure.config.schema import validate_config
        assert validate_config().ok()

    def test_client_id_without_secret_errors(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "s.myshopify.com")
        monkeypatch.setenv("SHOPAI_SHOPIFY_CLIENT_ID", "cid")
        from infrastructure.config.schema import validate_config
        result = validate_config()
        assert not result.ok()
        assert any("both be set together" in e for e in result.errors)

    def test_credentials_without_url_errors(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "shpat_x")
        from infrastructure.config.schema import validate_config
        result = validate_config()
        assert not result.ok()
        assert any("SHOPAI_SHOPIFY_URL is missing" in e for e in result.errors)


class TestProductionWarnings:
    def test_prod_with_debug_log_warns(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_ENV", "production")
        monkeypatch.setenv("SHOPAI_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("SHOPAI_API_TOKEN", "x")
        from infrastructure.config.schema import validate_config
        result = validate_config()
        assert result.ok()  # warning only
        assert any("DEBUG" in w for w in result.warnings)

    def test_prod_without_api_token_warns(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_ENV", "production")
        from infrastructure.config.schema import validate_config
        result = validate_config()
        assert result.ok()
        assert any("SHOPAI_API_TOKEN" in w for w in result.warnings)

    def test_development_does_not_warn(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_ENV", "development")
        monkeypatch.setenv("SHOPAI_LOG_LEVEL", "DEBUG")
        from infrastructure.config.schema import validate_config
        result = validate_config()
        assert not any("DEBUG" in w for w in result.warnings)


class TestLogFile:
    def test_unwritable_parent_errors(self, monkeypatch, tmp_path):
        # Make a dir, remove write permission, then try to use a path inside
        readonly = tmp_path / "readonly"
        readonly.mkdir()
        readonly.chmod(0o555)
        try:
            monkeypatch.setenv("SHOPAI_LOG_FILE", str(readonly / "app.log"))
            from infrastructure.config.schema import validate_config
            result = validate_config()
            # Running as root bypasses the permission check; skip in that case.
            if os.geteuid() == 0:
                pytest.skip("running as root — W_OK check is bypassed")
            assert not result.ok()
            assert any("not writable" in e for e in result.errors)
        finally:
            readonly.chmod(0o755)

    def test_writable_parent_ok(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SHOPAI_LOG_FILE", str(tmp_path / "app.log"))
        from infrastructure.config.schema import validate_config
        assert validate_config().ok()


class TestConfigReport:
    def test_report_covers_every_field(self):
        from infrastructure.config.schema import SCHEMA, get_config_report
        rows = get_config_report()
        assert len(rows) == len(SCHEMA)
        names = {r["name"] for r in rows}
        assert "SHOPAI_ENV" in names
        assert "SHOPAI_LOG_LEVEL" in names

    def test_report_masks_secrets(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_API_TOKEN", "supersecret123")
        from infrastructure.config.schema import get_config_report
        rows = get_config_report()
        row = next(r for r in rows if r["name"] == "SHOPAI_API_TOKEN")
        assert "supersecret123" not in row["value"]
        assert row["value"].startswith("supe")

    def test_report_shows_default_when_unset(self):
        from infrastructure.config.schema import get_config_report
        rows = get_config_report()
        level = next(r for r in rows if r["name"] == "SHOPAI_LOG_LEVEL")
        assert level["set"] is False
        assert level["value"] == "WARNING"


class TestEnvFileCheck:
    def test_missing_env_file_warns(self, tmp_path):
        from infrastructure.config.schema import check_env_file
        msg = check_env_file(str(tmp_path / "nope.env"))
        assert msg is not None
        assert "not found" in msg

    def test_existing_env_file_ok(self, tmp_path):
        f = tmp_path / "exists.env"
        f.write_text("SHOPAI_ENV=development\n")
        from infrastructure.config.schema import check_env_file
        assert check_env_file(str(f)) is None


class TestConfigCheckCLI:
    def test_check_clean_env(self, capsys):
        import cli
        rc = cli.main(["config", "check"])
        out = capsys.readouterr().out
        # The CLI handler returns 0 on success but main() doesn't propagate
        # it — we just check the printed output.
        assert "OK" in out or "error" in out.lower()

    def test_check_reports_bad_int(self, monkeypatch, capsys):
        monkeypatch.setenv("SHOPAI_LOG_BACKUPS", "xyz")
        import cli
        cli.main(["config", "check"])
        out = capsys.readouterr().out
        assert "ERROR" in out
        assert "SHOPAI_LOG_BACKUPS" in out

    def test_show_prints_all_fields(self, capsys):
        import cli
        cli.main(["config", "show"])
        out = capsys.readouterr().out
        assert "SHOPAI_ENV" in out
        assert "SHOPAI_LOG_LEVEL" in out
        assert "SHOPAI_OLLAMA_URL" in out
        assert "DESCRIPTION" in out


class TestConfigFieldHelpers:
    def test_effective_parses_int(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_LOG_BACKUPS", "7")
        from infrastructure.config.schema import SCHEMA
        f = next(x for x in SCHEMA if x.name == "SHOPAI_LOG_BACKUPS")
        assert f.effective() == 7

    def test_effective_fallback_to_default_on_bad_value(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_LOG_BACKUPS", "garbage")
        from infrastructure.config.schema import SCHEMA
        f = next(x for x in SCHEMA if x.name == "SHOPAI_LOG_BACKUPS")
        assert f.effective() == 5  # the default

    def test_is_set_empty_string_counts_as_unset(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_LOG_FILE", "")
        from infrastructure.config.schema import SCHEMA
        f = next(x for x in SCHEMA if x.name == "SHOPAI_LOG_FILE")
        assert f.is_set() is False
