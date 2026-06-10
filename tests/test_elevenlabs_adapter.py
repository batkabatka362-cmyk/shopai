"""Tests for ElevenLabsAdapter -- W963-106."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.adapters.base import Capability
from core.adapters.errors import (
    AdapterNotConfigured,
    AdapterValidationError,
)
from core.adapters.voice.elevenlabs import ElevenLabsAdapter


# ── Configuration ─────────────────────────────────────────


class TestElevenLabsConfiguration:
    def test_is_configured_returns_false_without_key(self):
        with patch(
            "core.adapters.voice._base.get_config"
        ) as mock_cfg:
            mock_cfg.return_value.get.return_value = ""
            adapter = ElevenLabsAdapter()
            assert adapter.is_configured() is False

    def test_is_configured_returns_true_with_key(self):
        with patch(
            "core.adapters.voice._base.get_config"
        ) as mock_cfg:
            mock_cfg.return_value.get.return_value = "el-key"
            adapter = ElevenLabsAdapter()
            assert adapter.is_configured() is True

    def test_config_alias_is_elevenlabs(self):
        adapter = ElevenLabsAdapter()
        assert adapter.config_alias == "elevenlabs"


# ── Metadata ───────────────────────────────────────────────


class TestElevenLabsMetadata:
    def test_name(self):
        assert ElevenLabsAdapter.name == "elevenlabs"

    def test_base_url(self):
        adapter = ElevenLabsAdapter()
        assert "elevenlabs.io" in adapter.base_url

    def test_capabilities(self):
        caps = ElevenLabsAdapter.capabilities
        assert Capability.VOICE_TEXT_TO_SPEECH in caps
        assert Capability.VOICE_LIST_VOICES in caps

    def test_category_is_voice(self):
        from core.adapters.base import AdapterCategory
        assert ElevenLabsAdapter.category == AdapterCategory.VOICE


# ── Auth headers ───────────────────────────────────────────


class TestElevenLabsAuth:
    """ElevenLabs uses xi-api-key header, not Bearer."""

    def test_auth_headers_use_xi_api_key(self):
        with patch(
            "core.adapters.voice._base.get_config"
        ) as mock_cfg:
            mock_cfg.return_value.get.return_value = "el-secret"
            adapter = ElevenLabsAdapter()
            headers = adapter._auth_headers()
        assert headers["xi-api-key"] == "el-secret"
        assert "Authorization" not in headers


# ── Validation ─────────────────────────────────────────────


class TestElevenLabsValidation:
    def test_tts_requires_text(self):
        adapter = ElevenLabsAdapter()
        try:
            adapter._validate_tts({})
            raise AssertionError("expected raise")
        except AdapterValidationError as exc:
            assert "text" in str(exc).lower()

    def test_tts_rejects_oversize_text(self):
        adapter = ElevenLabsAdapter()
        try:
            adapter._validate_tts({"text": "x" * 5001})
            raise AssertionError("expected raise")
        except AdapterValidationError as exc:
            assert "5000" in str(exc) or "cap" in str(exc).lower()

    def test_tts_rejects_non_string_voice_id(self):
        adapter = ElevenLabsAdapter()
        try:
            adapter._validate_tts({
                "text": "Hello",
                "voice_id": 123,  # int, not string
            })
            raise AssertionError("expected raise")
        except AdapterValidationError as exc:
            assert "voice_id" in str(exc).lower()


# ── TTS execution ──────────────────────────────────────────


class TestElevenLabsTTS:
    def _adapter(self):
        patcher = patch(
            "core.adapters.voice._base.get_config"
        )
        mock_cfg = patcher.start()
        mock_cfg.return_value.get.return_value = "el-key"
        self._patcher = patcher
        return ElevenLabsAdapter()

    def teardown_method(self, method):
        try:
            self._patcher.stop()
        except Exception:
            pass

    def test_tts_posts_to_voice_id_endpoint(self):
        adapter = self._adapter()
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.content = b"\x00\x01\x02" * 100

        with patch(
            "core.adapters.voice.elevenlabs._requests.post",
            return_value=fake_resp,
        ) as mock_post:
            adapter._do_tts(
                Capability.VOICE_TEXT_TO_SPEECH,
                {"text": "Hello world", "voice_id": "voice-xyz"},
            )

        args, kwargs = mock_post.call_args
        url = args[0]
        assert "/text-to-speech/voice-xyz" in url

    def test_tts_default_voice_used_when_omitted(self):
        adapter = self._adapter()
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.content = b"\x00" * 100

        with patch(
            "core.adapters.voice.elevenlabs._requests.post",
            return_value=fake_resp,
        ) as mock_post:
            adapter._do_tts(
                Capability.VOICE_TEXT_TO_SPEECH,
                {"text": "Hello"},
            )

        args, kwargs = mock_post.call_args
        url = args[0]
        # Default voice "Sarah" -- EXAVITQu4vr4xnSDxMaL
        assert "EXAVITQu4vr4xnSDxMaL" in url

    def test_tts_returns_audio_bytes(self):
        adapter = self._adapter()
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.content = b"\xff" * 200

        with patch(
            "core.adapters.voice.elevenlabs._requests.post",
            return_value=fake_resp,
        ):
            result = adapter._do_tts(
                Capability.VOICE_TEXT_TO_SPEECH,
                {"text": "Hello there"},
            )

        assert result.ok is True
        data = result.data
        assert data["audio_bytes"] == b"\xff" * 200
        assert data["audio_format"] == "mp3"
        assert data["char_count"] == len("Hello there")
        # Duration estimate: chars / 14
        assert data["duration_secs"] > 0

    def test_tts_passes_voice_settings(self):
        adapter = self._adapter()
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.content = b"\x00" * 10

        with patch(
            "core.adapters.voice.elevenlabs._requests.post",
            return_value=fake_resp,
        ) as mock_post:
            adapter._do_tts(
                Capability.VOICE_TEXT_TO_SPEECH,
                {
                    "text": "Hello",
                    "voice_settings": {
                        "stability": 0.8,
                        "similarity_boost": 0.6,
                    },
                },
            )
        args, kwargs = mock_post.call_args
        body = kwargs["json"]
        assert body["voice_settings"]["stability"] == 0.8

    def test_tts_default_voice_settings(self):
        """When voice_settings omitted, defaults apply."""
        adapter = self._adapter()
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.content = b"\x00" * 10

        with patch(
            "core.adapters.voice.elevenlabs._requests.post",
            return_value=fake_resp,
        ) as mock_post:
            adapter._do_tts(
                Capability.VOICE_TEXT_TO_SPEECH,
                {"text": "Hello"},
            )
        args, kwargs = mock_post.call_args
        body = kwargs["json"]
        assert body["voice_settings"]["stability"] == 0.5
        assert body["voice_settings"]["similarity_boost"] == 0.75

    def test_tts_unauth_response_raises_auth_error(self):
        from core.adapters.errors import AdapterAuthError
        adapter = self._adapter()
        fake_resp = MagicMock()
        fake_resp.status_code = 401
        fake_resp.text = '{"detail": "Unauthenticated"}'
        with patch(
            "core.adapters.voice.elevenlabs._requests.post",
            return_value=fake_resp,
        ):
            try:
                adapter._do_tts(
                    Capability.VOICE_TEXT_TO_SPEECH,
                    {"text": "Hello"},
                )
                raise AssertionError("expected AdapterAuthError")
            except AdapterAuthError:
                pass


# ── Bootstrap registration ─────────────────────────────────


class TestElevenLabsBootstrap:
    def test_register_all_includes_elevenlabs(self):
        from core.adapters.voice.bootstrap import (
            _VOICE_ADAPTER_CLASSES,
        )
        names = [cls.name for cls in _VOICE_ADAPTER_CLASSES]
        assert "elevenlabs" in names
