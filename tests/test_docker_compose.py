"""Tests for the docker-compose.yml structure.

These don't actually run docker — they verify the YAML schema so a
future edit can't accidentally drop the Ollama init container or
break the healthcheck on which the daemon depends.
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
        assert {"shopai-daemon", "shopai-api", "ollama", "ollama-init"}.issubset(names)

    def test_expected_volumes_present(self, compose):
        names = set(compose["volumes"].keys())
        assert {"shopai_data", "shopai_logs", "ollama_models"}.issubset(names)


# ── Ollama service ──────────────────────────────────────────


class TestOllamaService:
    def test_image(self, compose):
        ollama = compose["services"]["ollama"]
        assert ollama["image"] == "ollama/ollama:latest"

    def test_port_published(self, compose):
        ollama = compose["services"]["ollama"]
        ports = ollama.get("ports", [])
        assert any("11434" in str(p) for p in ports)

    def test_models_volume_mounted(self, compose):
        ollama = compose["services"]["ollama"]
        vols = ollama.get("volumes", [])
        assert any("ollama_models" in str(v) for v in vols)

    def test_has_healthcheck(self, compose):
        ollama = compose["services"]["ollama"]
        hc = ollama.get("healthcheck")
        assert hc is not None
        # Healthcheck must hit the /api/tags endpoint
        test = hc.get("test", [])
        joined = " ".join(str(t) for t in (test if isinstance(test, list) else [test]))
        assert "11434" in joined
        assert "api/tags" in joined

    def test_healthcheck_has_start_period(self, compose):
        # Pulling models on first boot is slow — start_period must be
        # generous enough that the daemon doesn't time out waiting.
        hc = compose["services"]["ollama"]["healthcheck"]
        assert hc.get("start_period") is not None
        # Parse "30s" or "1m" or just an int — accept any non-empty value
        assert str(hc["start_period"])


# ── Ollama init container ───────────────────────────────────


class TestOllamaInit:
    def test_init_service_exists(self, compose):
        assert "ollama-init" in compose["services"]

    def test_init_depends_on_ollama_healthy(self, compose):
        init = compose["services"]["ollama-init"]
        deps = init.get("depends_on", {})
        # Long form: { ollama: { condition: service_healthy } }
        if isinstance(deps, dict):
            assert "ollama" in deps
            assert deps["ollama"].get("condition") == "service_healthy"
        else:
            # Short form: just a list
            assert "ollama" in deps

    def test_init_uses_same_image_as_ollama(self, compose):
        init = compose["services"]["ollama-init"]
        assert init["image"] == "ollama/ollama:latest"

    def test_init_pulls_default_models(self, compose):
        init = compose["services"]["ollama-init"]
        # Either an env var with the default set
        env = init.get("environment", {})
        models_env = env.get("SHOPAI_OLLAMA_MODELS", "")
        # Default is set via ${VAR:-fallback} pattern
        assert "mistral" in str(models_env) or "${" in str(models_env)

    def test_init_does_not_restart(self, compose):
        # The init container is one-shot; it must not auto-restart
        init = compose["services"]["ollama-init"]
        assert init.get("restart", "no") == "no"

    def test_init_command_pulls_models(self, compose):
        init = compose["services"]["ollama-init"]
        cmd = init.get("command", [])
        joined = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
        assert "ollama pull" in joined
        assert "11434" in joined


# ── shopai-daemon ↔ ollama wiring ───────────────────────────


class TestDaemonOllamaWiring:
    def test_daemon_points_at_ollama_service(self, compose):
        daemon = compose["services"]["shopai-daemon"]
        env = daemon.get("environment", {})
        assert env.get("SHOPAI_OLLAMA_URL") == "http://ollama:11434"

    def test_daemon_depends_on_healthy_ollama(self, compose):
        daemon = compose["services"]["shopai-daemon"]
        deps = daemon.get("depends_on", {})
        assert isinstance(deps, dict), (
            "depends_on must use the long form {service: {condition: ...}} "
            "so the daemon waits for ollama to be healthy"
        )
        assert "ollama" in deps
        assert deps["ollama"]["condition"] == "service_healthy"

    def test_daemon_depends_on_init_completion(self, compose):
        daemon = compose["services"]["shopai-daemon"]
        deps = daemon.get("depends_on", {})
        assert "ollama-init" in deps
        assert deps["ollama-init"]["condition"] == "service_completed_successfully"

    def test_api_points_at_ollama_service(self, compose):
        api = compose["services"]["shopai-api"]
        env = api.get("environment", {})
        assert env.get("SHOPAI_OLLAMA_URL") == "http://ollama:11434"

    def test_api_depends_on_healthy_ollama(self, compose):
        api = compose["services"]["shopai-api"]
        deps = api.get("depends_on", {})
        assert isinstance(deps, dict)
        assert "ollama" in deps
        assert deps["ollama"]["condition"] == "service_healthy"


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
        # Should also document the model override
        assert "SHOPAI_OLLAMA_MODELS" in contents

    def test_env_example_mentions_remote_fallbacks(self):
        path = Path(__file__).resolve().parents[1] / ".env.example"
        if not path.exists():
            pytest.skip()
        contents = path.read_text()
        assert "OPENAI_API_KEY" in contents
        assert "ANTHROPIC_API_KEY" in contents
