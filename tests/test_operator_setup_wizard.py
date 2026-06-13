"""W963-180: operator-setup wizard tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from engines._operator_setup import (
    CATEGORIES,
    EnvCategory,
    EnvVar,
    SetupReport,
    _validate_shopify_token,
    _validate_shopify_url,
    _validate_url,
    categorise_existing,
    parse_env_file,
    prompt_for_var,
    run_wizard,
    write_env_file,
)


class TestValidators:
    def test_shopify_url_strips_protocol(self):
        assert _validate_shopify_url(
            "https://acme.myshopify.com",
        ) == "acme.myshopify.com"

    def test_shopify_url_strips_trailing_slash(self):
        assert _validate_shopify_url(
            "acme.myshopify.com/",
        ) == "acme.myshopify.com"

    def test_shopify_url_rejects_custom_domain(self):
        with pytest.raises(ValueError):
            _validate_shopify_url("https://acme.com")

    def test_shopify_url_rejects_subpaths(self):
        with pytest.raises(ValueError):
            _validate_shopify_url(
                "store.acme.myshopify.com",
            )

    def test_shopify_token_format(self):
        # shpat_ prefix valid
        assert _validate_shopify_token(
            "shpat_" + "x" * 40,
        ) == "shpat_" + "x" * 40
        # shpca_ prefix valid (custom app)
        assert _validate_shopify_token(
            "shpca_" + "x" * 40,
        )
        # Wrong prefix
        with pytest.raises(ValueError):
            _validate_shopify_token("bearer_xxx")
        # Too short
        with pytest.raises(ValueError):
            _validate_shopify_token("shpat_short")

    def test_url_validator(self):
        assert _validate_url(
            "https://hooks.slack.com/abc",
        )
        assert _validate_url("http://localhost:8080")
        with pytest.raises(ValueError):
            _validate_url("not_a_url")


class TestParseEnv:
    def test_empty_file(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("", encoding="utf-8")
        assert parse_env_file(env) == {}

    def test_nonexistent_file(self, tmp_path):
        assert parse_env_file(
            tmp_path / "missing.env",
        ) == {}

    def test_basic_keys(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "KEY1=value1\nKEY2=value2\n",
            encoding="utf-8",
        )
        assert parse_env_file(env) == {
            "KEY1": "value1",
            "KEY2": "value2",
        }

    def test_ignores_comments_and_blanks(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "# header\n\nKEY=value\n# end\n",
            encoding="utf-8",
        )
        assert parse_env_file(env) == {"KEY": "value"}

    def test_strips_outer_quotes(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            'A=value\nB="quoted"\nC=\'singled\'\n',
            encoding="utf-8",
        )
        result = parse_env_file(env)
        assert result == {
            "A": "value",
            "B": "quoted",
            "C": "singled",
        }


class TestCategorise:
    def test_split_known_unknown(self):
        existing = {
            "SHOPAI_SHOPIFY_URL": "x.myshopify.com",
            "RANDOM_KEY": "value",
        }
        managed, others = categorise_existing(
            existing, CATEGORIES,
        )
        assert "SHOPAI_SHOPIFY_URL" in managed
        assert "RANDOM_KEY" not in managed
        assert "RANDOM_KEY=value" in others


class TestWriteEnv:
    def test_atomic_write(self, tmp_path):
        env = tmp_path / ".env"
        write_env_file(
            env, {"KEY1": "value1", "KEY2": "value2"},
        )
        assert "KEY1=value1" in env.read_text(
            encoding="utf-8",
        )
        # Ensures sorted output (deterministic)
        lines = env.read_text(
            encoding="utf-8",
        ).strip().split("\n")
        assert lines == ["KEY1=value1", "KEY2=value2"]

    def test_preserved_lines(self, tmp_path):
        env = tmp_path / ".env"
        write_env_file(
            env,
            {"KEY1": "value1"},
            preserved_lines=[
                "# operator's comment",
                "UNKNOWN_KEY=value",
            ],
        )
        text = env.read_text(encoding="utf-8")
        assert "# operator's comment" in text
        assert "UNKNOWN_KEY=value" in text
        assert "KEY1=value1" in text

    def test_quotes_values_with_spaces(self, tmp_path):
        env = tmp_path / ".env"
        write_env_file(
            env, {"KEY": "value with spaces"},
        )
        assert (
            'KEY="value with spaces"'
            in env.read_text(encoding="utf-8")
        )

    def test_round_trip_preserves_value(self, tmp_path):
        env = tmp_path / ".env"
        original = {
            "URL": "https://acme.myshopify.com",
            "TOKEN": "shpat_" + "x" * 40,
        }
        write_env_file(env, original)
        roundtrip = parse_env_file(env)
        assert roundtrip == original


class TestPromptFlow:
    def test_already_set_skips_prompt(self):
        var = EnvVar(
            key="K", description="d", required=True,
        )
        new_val, status = prompt_for_var(
            var,
            existing_value="existing",
            input_fn=lambda _: pytest.fail(
                "should not prompt",
            ),
            print_fn=lambda _: None,
        )
        assert new_val == "existing"
        assert status == "already_set"

    def test_newly_set_passes_validator(self):
        var = EnvVar(
            key="K", description="d",
            validator=_validate_shopify_url,
        )
        outputs: list[str] = []
        new_val, status = prompt_for_var(
            var,
            existing_value=None,
            input_fn=lambda _: "acme.myshopify.com",
            print_fn=lambda x: outputs.append(x),
        )
        assert new_val == "acme.myshopify.com"
        assert status == "newly_set"

    def test_skipped_when_optional_blank(self):
        var = EnvVar(
            key="K", description="d", required=False,
        )
        new_val, status = prompt_for_var(
            var,
            existing_value=None,
            input_fn=lambda _: "",
            print_fn=lambda _: None,
        )
        assert new_val is None
        assert status == "skipped"

    def test_invalid_retries_until_valid(self):
        var = EnvVar(
            key="K", description="d",
            validator=_validate_shopify_url,
        )
        responses = iter(
            ["not_valid", "still_bad", "acme.myshopify.com"],
        )
        outputs: list[str] = []
        new_val, status = prompt_for_var(
            var,
            existing_value=None,
            input_fn=lambda _: next(responses),
            print_fn=lambda x: outputs.append(x),
        )
        assert new_val == "acme.myshopify.com"
        assert status == "newly_set"
        # Two "invalid" messages emitted before success
        assert (
            sum(
                1 for o in outputs
                if "invalid" in o
            ) == 2
        )

    def test_force_rewrite_re_prompts(self):
        var = EnvVar(
            key="K", description="d",
        )
        new_val, status = prompt_for_var(
            var,
            existing_value="old",
            input_fn=lambda _: "new",
            print_fn=lambda _: None,
            force_rewrite=True,
        )
        assert new_val == "new"
        assert status == "newly_set"


class TestRunWizard:
    def test_revenue_ready_flag(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "SHOPAI_SHOPIFY_URL=acme.myshopify.com\n"
            "SHOPAI_SHOPIFY_KEY=shpat_" + "x" * 40 + "\n"
            "META_ADS_ACCESS_TOKEN=abc\n"
            "META_ADS_ACCOUNT_ID=123456789012345\n",
            encoding="utf-8",
        )
        # Auto-skip all prompts (every key returns empty)
        report = run_wizard(
            env_path=env,
            input_fn=lambda _: "",
            print_fn=lambda _: None,
        )
        assert report.revenue_ready is True

    def test_not_revenue_ready_without_ads(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "SHOPAI_SHOPIFY_URL=acme.myshopify.com\n"
            "SHOPAI_SHOPIFY_KEY=shpat_" + "x" * 40 + "\n",
            encoding="utf-8",
        )
        report = run_wizard(
            env_path=env,
            input_fn=lambda _: "",
            print_fn=lambda _: None,
        )
        assert report.revenue_ready is False

    def test_preserves_unknown_keys(self, tmp_path):
        env = tmp_path / ".env"
        # Include all required keys so the wizard doesn't loop
        # waiting for non-empty input. Test focus is the
        # preserved-keys path.
        env.write_text(
            "SHOPAI_SHOPIFY_URL=acme.myshopify.com\n"
            "SHOPAI_SHOPIFY_KEY=shpat_" + "x" * 40 + "\n"
            "MY_CUSTOM_KEY=preserved\n"
            "ANOTHER=also_preserved\n",
            encoding="utf-8",
        )
        report = run_wizard(
            env_path=env,
            input_fn=lambda _: "",
            print_fn=lambda _: None,
        )
        text = env.read_text(encoding="utf-8")
        assert "MY_CUSTOM_KEY=preserved" in text
        assert "ANOTHER=also_preserved" in text
        assert report.keys_preserved == 2
