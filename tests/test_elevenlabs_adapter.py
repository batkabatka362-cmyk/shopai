"""Tests for the ElevenLabs voice/TTS adapter.

Real HTTP calls are forbidden — every test patches
``_http_request`` to return canned responses.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterValidationError,
    Capability,
    get_config,
    get_registry,
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_elevenlabs(monkeypatch, *, key="el-test-key"):
    monkeypatch.setenv("ELEVENLABS_API_KEY", key)
    get_config().reload()


class TestElevenLabsMetadata:
    def test_metadata(self):
        from core.adapters.voice.elevenlabs import ElevenLabsAdapter
        a = ElevenLabsAdapter()
        assert a.name == "elevenlabs"
        assert a.category == AdapterCategory.VOICE
        assert Capability.VOICE_TEXT_TO_SPEECH in a.capabilities
        assert Capability.VOICE_LIST_VOICES in a.capabilities
        assert a.priority == 90

    def test_unconfigured_without_key(self):
        from core.adapters.voice.elevenlabs import ElevenLabsAdapter
        assert not ElevenLabsAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.voice.elevenlabs import ElevenLabsAdapter
        _configure_elevenlabs(monkeypatch)
        assert ElevenLabsAdapter().is_configured()


class TestElevenLabsAuth:
    def test_api_key_header(self, monkeypatch):
        from core.adapters.voice.elevenlabs import ElevenLabsAdapter
        _configure_elevenlabs(monkeypatch, key="my-key")
        a = ElevenLabsAdapter()
        headers = a._auth_headers()
        assert headers["xi-api-key"] == "my-key"


class TestElevenLabsTTS:
    def test_tts_requires_text(self, monkeypatch):
        from core.adapters.voice.elevenlabs import ElevenLabsAdapter
        _configure_elevenlabs(monkeypatch)
        a = ElevenLabsAdapter()

        result = a.execute(
            Capability.VOICE_TEXT_TO_SPEECH,
            {},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_tts_happy_path(self, monkeypatch):
        from core.adapters.voice.elevenlabs import ElevenLabsAdapter
        _configure_elevenlabs(monkeypatch)
        a = ElevenLabsAdapter()

        # Mock the streaming response
        mock_response = MagicMock()
        mock_response.content = b"fake-audio-bytes-1234"
        mock_response.status_code = 200

        with patch.object(a, "_http_request", return_value=mock_response):
            result = a.execute(
                Capability.VOICE_TEXT_TO_SPEECH,
                {"text": "Hello, welcome to our store!"},
            )

        assert result.ok
        assert result.data["characters"] == len("Hello, welcome to our store!")
        assert result.data["format"] == "mp3_44100_128"
        assert "audio_base64" in result.data


class TestElevenLabsListVoices:
    def test_list_voices(self, monkeypatch):
        from core.adapters.voice.elevenlabs import ElevenLabsAdapter
        _configure_elevenlabs(monkeypatch)
        a = ElevenLabsAdapter()

        raw = {
            "voices": [
                {"voice_id": "abc", "name": "Rachel", "category": "premade", "labels": {}, "preview_url": ""},
                {"voice_id": "def", "name": "Drew", "category": "premade", "labels": {}, "preview_url": ""},
            ],
        }

        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.VOICE_LIST_VOICES,
                {},
            )

        assert result.ok
        assert result.data["count"] == 2
        assert result.data["voices"][0]["name"] == "Rachel"


class TestElevenLabsBootstrap:
    def test_register_all(self):
        from core.adapters.voice.bootstrap import register_all
        status = register_all()
        assert "elevenlabs" in status

    def test_router_finds_elevenlabs(self, monkeypatch):
        from core.adapters.voice.bootstrap import register_all
        _configure_elevenlabs(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.VOICE_TEXT_TO_SPEECH)
        assert chosen.name == "elevenlabs"
