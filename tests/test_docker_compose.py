"""Tests for the docker-compose.yml structure.

These don't actually run docker — they verify the YAML schema so a
future edit can't accidentally drop a service or break the
healthcheck semantics. Ollama is OPT-IN via --profile ollama;
the default stack runs shopai-daemon + shopai-api + cloudflared
only, with cloud LLMs (Groq / Gemini / DeepSeek) configured in
.env.
"""
import os
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def compose():
    """Load docker-compose.yml as a dict once for all tests."""
    pytest.importorskip("yaml")
    import yaml
    path = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    assert path.exists(), f"docker-compose.yml not found at {path}"
    return yaml.safe_load(path.read_text())


# ── Top-level structure ─────────────────────────────────────


class TestStructure:
    def test_has_services(self, compose):
        assert "services" in compose

    def test_has_volumes(self, compose):
        assert "volumes" in compose

    def test_expected_services_present(self, compose):
        names = set(compose["services"].keys())
        # Default stack — daemon + api + cloudflared
        assert {
            "shopai-daemon", "shopai-api", "cloudflared",
        }.issubset(names)
        # Ollama stays defined for opt-in profile use
        assert {"ollama", "ollama-init"}.issubset(names)

    def test_expected_volumes_present(self, compose):
        names = set(compose["volumes"].keys())
        assert {"shopai_data", "shopai_logs", "ollama_models"}.issubset(names)


# ── Ollama service (opt-in, profile) ────────────────────────


class TestOllamaService:
    def test_image(self, compose):
        ollama = compose["services"]["ollama"]
        assert ollama["image"] == "ollama/ollama:latest"

    def test_is_opt_in_via_profile(self, compose):
        """Ollama must carry a `profiles:` entry so default
        `docker compose up` does NOT start it — only the
        user running `--profile ollama up -d` does. This
        keeps first-run light (no 15 GB pull)."""
        ollama = compose["services"]["ollama"]
        profiles = ollama.get("profiles") or []
        assert "ollama" in profiles, (
            f"ollama service must be gated behind "
            f"profile 'ollama'; got profiles={profiles}"
        )

    def test_port_published(self, compose):
        ollama = compose["services"]["ollama"]
        ports = ollama.get("ports", [])
        assert any("11434" in str(p) for p in ports)

    def test_models_volume_mounted(self, compose):
        ollama = compose["services"]["ollama"]
        vols = ollama.get("volumes", [])
        assert any("ollama_models" in str(v) for v in vols)

    def test_has_healthcheck(self, compose):
        """Healthcheck uses `ollama list` — the CLI is
        guaranteed present in the image (wget/curl are NOT).
        The URL/port is implicit via OLLAMA_HOST default."""
        ollama = compose["services"]["ollama"]
        hc = ollama.get("healthcheck")
        assert hc is not None
        test = hc.get("test", [])
        joined = " ".join(
            str(t) for t in (test if isinstance(test, list) else [test])
        )
        assert "ollama" in joined.lower(), (
            f"healthcheck must invoke `ollama` CLI; got {joined!r}"
        )

    def test_healthcheck_has_start_period(self, compose):
        hc = compose["services"]["ollama"]["healthcheck"]
        assert hc.get("start_period") is not None
        assert str(hc["start_period"])


# ── Ollama init container ───────────────────────────────────


class TestOllamaInit:
    def test_init_service_exists(self, compose):
        assert "ollama-init" in compose["services"]

    def test_init_is_opt_in_via_profile(self, compose):
        """Init lives in the same opt-in profile as ollama.
        Owners not using local LLM never trigger the model
        pull."""
        init = compose["services"]["ollama-init"]
        profiles = init.get("profiles") or []
        assert "ollama" in profiles

    def test_init_depends_on_ollama_healthy(self, compose):
        init = compose["services"]["ollama-init"]
        deps = init.get("depends_on", {})
        if isinstance(deps, dict):
            assert "ollama" in deps
            assert deps["ollama"].get("condition") == "service_healthy"
        else:
            assert "ollama" in deps

    def test_init_uses_same_image_as_ollama(self, compose):
        init = compose["services"]["ollama-init"]
        assert init["image"] == "ollama/ollama:latest"

    def test_init_pulls_default_models(self, compose):
        init = compose["services"]["ollama-init"]
        env = init.get("environment", {})
        models_env = env.get("SHOPAI_OLLAMA_MODELS", "")
        assert "mistral" in str(models_env) or "${" in str(models_env)

    def test_init_does_not_restart(self, compose):
        init = compose["services"]["ollama-init"]
        assert init.get("restart", "no") == "no"

    def test_init_command_pulls_models(self, compose):
        init = compose["services"]["ollama-init"]
        cmd = init.get("command", [])
        joined = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
        assert "ollama pull" in joined


# ── Default stack: no Ollama dependency ─────────────────────


class TestDefaultStackCloudLLMFirst:
    """Default stack uses cloud LLMs (Groq / Gemini / DeepSeek
    per CLAUDE.md §5). shopai-daemon + shopai-api MUST NOT
    hard-depend on ollama — otherwise owners without the
    ollama profile can't start the stack at all."""

    def test_daemon_does_not_require_ollama(self, compose):
        daemon = compose["services"]["shopai-daemon"]
        deps = daemon.get("depends_on", {}) or {}
        # Either no depends_on, or depends_on doesn't include
        # ollama/ollama-init (because those live behind a
        # profile and would cause startup to fail when the
        # profile isn't active).
        deps_keys = (
            deps.keys() if isinstance(deps, dict) else deps
        )
        assert "ollama" not in deps_keys, (
            "shopai-daemon must not hard-depend on ollama "
            "(ollama is opt-in via --profile ollama)"
        )
        assert "ollama-init" not in deps_keys

    def test_api_does_not_require_ollama(self, compose):
        api = compose["services"]["shopai-api"]
        deps = api.get("depends_on", {}) or {}
        deps_keys = (
            deps.keys() if isinstance(deps, dict) else deps
        )
        assert "ollama" not in deps_keys, (
            "shopai-api must not hard-depend on ollama"
        )

    def test_daemon_still_points_at_ollama_host(self, compose):
        """When owner does activate the ollama profile, the
        daemon still needs to know where to reach it. The env
        var stays set (no-op when profile off)."""
        daemon = compose["services"]["shopai-daemon"]
        env = daemon.get("environment", {})
        assert env.get("SHOPAI_OLLAMA_URL") == "http://ollama:11434"

    def test_api_still_points_at_ollama_host(self, compose):
        api = compose["services"]["shopai-api"]
        env = api.get("environment", {})
        assert env.get("SHOPAI_OLLAMA_URL") == "http://ollama:11434"


# ── cloudflared tunnel (default stack) ─────────────────────


class TestCloudflaredTunnel:
    """Public https tunnel — Shopify webhooks reach
    shopai-api from the internet via this."""

    def test_service_exists(self, compose):
        assert "cloudflared" in compose["services"]

    def test_not_profile_gated(self, compose):
        """cloudflared is part of the default stack — owner
        always needs public webhook URL for Shopify."""
        tunnel = compose["services"]["cloudflared"]
        profiles = tunnel.get("profiles") or []
        assert profiles == [] or profiles is None, (
            "cloudflared should NOT be profile-gated — "
            "every live owner needs webhooks"
        )

    def test_points_at_shopai_api(self, compose):
        tunnel = compose["services"]["cloudflared"]
        cmd = tunnel.get("command", [])
        if isinstance(cmd, list):
            joined = " ".join(str(c) for c in cmd)
        else:
            joined = str(cmd)
        assert "shopai-api" in joined
        assert "8080" in joined


# ── Volumes ─────────────────────────────────────────────────


class TestVolumes:
    def test_data_volume_shared_between_daemon_and_api(self, compose):
        daemon_vols = compose["services"]["shopai-daemon"].get("volumes", [])
        api_vols = compose["services"]["shopai-api"].get("volumes", [])
        assert any("shopai_data" in str(v) for v in daemon_vols)
        assert any("shopai_data" in str(v) for v in api_vols)

    def test_logs_volume_shared(self, compose):
        daemon_vols = compose["services"]["shopai-daemon"].get("volumes", [])
        api_vols = compose["services"]["shopai-api"].get("volumes", [])
        assert any("shopai_logs" in str(v) for v in daemon_vols)
        assert any("shopai_logs" in str(v) for v in api_vols)


# ── .env.example sanity ─────────────────────────────────────


class TestEnvExample:
    def test_env_example_documents_ollama(self):
        path = Path(__file__).resolve().parents[1] / ".env.example"
        if not path.exists():
            pytest.skip(".env.example not present in this checkout")
        contents = path.read_text()
        assert "SHOPAI_OLLAMA_URL" in contents

    def test_env_example_documents_cloud_llm_chain(self):
        """Default stack relies on cloud LLM keys. .env.example
        must document the 3-agent chain (CLAUDE.md §5)."""
        path = Path(__file__).resolve().parents[1] / ".env.example"
        if not path.exists():
            pytest.skip()
        contents = path.read_text()
        # At least Groq + Gemini are required; DeepSeek optional
        assert "GROQ_API_KEY" in contents
        assert (
            "GEMINI_API_KEY" in contents
            or "GOOGLE_API_KEY" in contents
        )
