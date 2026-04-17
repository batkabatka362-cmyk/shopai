"""Tests for video_gen adapters (Pexels, Pixabay, Higgsfield, Replicate).

Real HTTP calls are forbidden — every test patches
``_http_request`` to return canned responses. The tests verify:

  * Metadata (category, capabilities, priority)
  * Configuration detection (env var → is_configured)
  * Request shape (correct URL, headers, params, body)
  * Response normalisation (vendor shape → unified clip record)
  * Capability dispatch (unsupported → AdapterValidationError)
  * Validation (missing query/prompt/job_id, out-of-range limits,
    too-long prompts)
  * Async-job status mapping (vendor statuses → ready/processing/
    failed)
  * Bootstrap registration (every adapter registers and is
    discoverable by capability)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterValidationError,
    Capability,
    get_config,
    get_registry,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "PEXELS_API_KEY", "PIXABAY_API_KEY",
        "HIGGSFIELD_API_KEY", "REPLICATE_API_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _cfg(monkeypatch, **kv):
    for k, v in kv.items():
        monkeypatch.setenv(k, v)
    get_config().reload()


# ── Pexels ───────────────────────────────────────────────────


class TestPexelsMetadata:
    def test_metadata(self):
        from core.adapters.video_gen.pexels import PexelsAdapter
        a = PexelsAdapter()
        assert a.name == "pexels"
        assert a.category == AdapterCategory.VIDEO_GEN
        assert Capability.VIDEO_STOCK_SEARCH in a.capabilities
        # Pexels does not implement AI generate
        assert Capability.VIDEO_GENERATE not in a.capabilities
        assert a.priority == 90
        assert a.kind == "stock"

    def test_unconfigured_without_key(self):
        from core.adapters.video_gen.pexels import PexelsAdapter
        assert not PexelsAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.video_gen.pexels import PexelsAdapter
        _cfg(monkeypatch, PEXELS_API_KEY="pk-test")
        assert PexelsAdapter().is_configured()


class TestPexelsSearch:
    def test_search_normalises_response(self, monkeypatch):
        from core.adapters.video_gen.pexels import PexelsAdapter
        _cfg(monkeypatch, PEXELS_API_KEY="pk-test")
        a = PexelsAdapter()
        raw = {
            "videos": [
                {
                    "id": 12345,
                    "url": "https://pexels.com/video/12345",
                    "image": "https://cdn.pexels.com/thumb.jpg",
                    "duration": 17,
                    "width": 1920,
                    "height": 1080,
                    "video_pictures": [{"picture": "https://cdn.px/pic.jpg"}],
                    "video_files": [
                        {"link": "https://cdn.px/sd.mp4", "file_type": "video/mp4",
                         "width": 640, "height": 360},
                        {"link": "https://cdn.px/hd.mp4", "file_type": "video/mp4",
                         "width": 1920, "height": 1080},
                        {"link": "https://cdn.px/m3u8", "file_type": "application/x-mpegURL",
                         "width": 1920, "height": 1080},
                    ],
                },
            ],
        }
        with patch.object(a, "_http_request", return_value=raw) as mock:
            out = a.execute(Capability.VIDEO_STOCK_SEARCH,
                            {"query": "kitchen", "limit": 5})
        # Request shape
        _, kwargs = mock.call_args[0], mock.call_args[1]
        assert kwargs["params"]["query"] == "kitchen"
        assert kwargs["params"]["per_page"] == 5
        # Response
        assert out.ok is True
        assert out.data["total"] == 1
        clip = out.data["clips"][0]
        assert clip["clip_id"] == "12345"
        assert clip["source"] == "pexels"
        assert clip["kind"] == "stock"
        assert clip["status"] == "ready"
        # Picked the HIGHEST-resolution MP4, skipped HLS.
        assert clip["video_url"] == "https://cdn.px/hd.mp4"
        assert clip["width"] == 1920
        assert clip["height"] == 1080
        assert clip["duration_seconds"] == 17
        assert clip["format"] == "mp4"
        assert clip["license"] == "pexels"
        assert clip["thumbnail_url"] == "https://cdn.px/pic.jpg"

    def test_auth_header_scheme(self, monkeypatch):
        from core.adapters.video_gen.pexels import PexelsAdapter
        _cfg(monkeypatch, PEXELS_API_KEY="pk-test")
        a = PexelsAdapter()
        headers = a._auth_headers()
        # Pexels passes the key raw, NOT as "Bearer <key>".
        assert headers["Authorization"] == "pk-test"
        assert "Bearer" not in headers["Authorization"]

    def test_missing_query_raises(self, monkeypatch):
        from core.adapters.video_gen.pexels import PexelsAdapter
        _cfg(monkeypatch, PEXELS_API_KEY="pk-test")
        a = PexelsAdapter()
        result = a.execute(Capability.VIDEO_STOCK_SEARCH, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_limit_out_of_range_raises(self, monkeypatch):
        from core.adapters.video_gen.pexels import PexelsAdapter
        _cfg(monkeypatch, PEXELS_API_KEY="pk-test")
        a = PexelsAdapter()
        result = a.execute(Capability.VIDEO_STOCK_SEARCH,
                           {"query": "x", "limit": 999})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_unsupported_capability_raises(self, monkeypatch):
        from core.adapters.video_gen.pexels import PexelsAdapter
        _cfg(monkeypatch, PEXELS_API_KEY="pk-test")
        a = PexelsAdapter()
        # Pexels declared only STOCK_SEARCH; GENERATE must fail.
        result = a.execute(Capability.VIDEO_GENERATE, {"prompt": "hello"})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_orientation_passthrough(self, monkeypatch):
        from core.adapters.video_gen.pexels import PexelsAdapter
        _cfg(monkeypatch, PEXELS_API_KEY="pk-test")
        a = PexelsAdapter()
        with patch.object(a, "_http_request", return_value={"videos": []}) as m:
            a.execute(Capability.VIDEO_STOCK_SEARCH, {
                "query": "test", "orientation": "portrait", "size": "large",
            })
        kwargs = m.call_args[1]
        assert kwargs["params"]["orientation"] == "portrait"
        assert kwargs["params"]["size"] == "large"

    def test_invalid_orientation_ignored(self, monkeypatch):
        from core.adapters.video_gen.pexels import PexelsAdapter
        _cfg(monkeypatch, PEXELS_API_KEY="pk-test")
        a = PexelsAdapter()
        with patch.object(a, "_http_request", return_value={"videos": []}) as m:
            a.execute(Capability.VIDEO_STOCK_SEARCH, {
                "query": "test", "orientation": "diagonal",
            })
        assert "orientation" not in m.call_args[1]["params"]


# ── Pixabay ──────────────────────────────────────────────────


class TestPixabay:
    def test_metadata(self):
        from core.adapters.video_gen.pixabay import PixabayAdapter
        a = PixabayAdapter()
        assert a.name == "pixabay"
        assert Capability.VIDEO_STOCK_SEARCH in a.capabilities
        assert Capability.VIDEO_GENERATE not in a.capabilities
        assert a.priority == 75

    def test_search_picks_largest_tier(self, monkeypatch):
        from core.adapters.video_gen.pixabay import PixabayAdapter
        _cfg(monkeypatch, PIXABAY_API_KEY="pb-test")
        a = PixabayAdapter()
        raw = {
            "hits": [
                {
                    "id": 99,
                    "pageURL": "https://pixabay.com/videos/99",
                    "duration": 12,
                    "videos": {
                        "large": {"url": "https://v/large.mp4",
                                  "width": 1920, "height": 1080,
                                  "thumbnail": "https://v/thumb.jpg"},
                        "medium": {"url": "https://v/medium.mp4",
                                   "width": 1280, "height": 720},
                    },
                },
            ],
        }
        with patch.object(a, "_http_request", return_value=raw):
            out = a.execute(Capability.VIDEO_STOCK_SEARCH,
                            {"query": "dog", "limit": 5})
        clip = out.data["clips"][0]
        assert clip["video_url"] == "https://v/large.mp4"
        assert clip["width"] == 1920
        assert clip["license"] == "pixabay"
        assert clip["source"] == "pixabay"

    def test_falls_back_through_tiers(self, monkeypatch):
        from core.adapters.video_gen.pixabay import PixabayAdapter
        _cfg(monkeypatch, PIXABAY_API_KEY="pb-test")
        a = PixabayAdapter()
        raw = {
            "hits": [
                {
                    "id": 10, "duration": 8,
                    "videos": {
                        "large": {"url": "", "width": 0, "height": 0},
                        "medium": {"url": "", "width": 0, "height": 0},
                        "small": {"url": "https://v/sm.mp4",
                                  "width": 640, "height": 360},
                    },
                },
            ],
        }
        with patch.object(a, "_http_request", return_value=raw):
            out = a.execute(Capability.VIDEO_STOCK_SEARCH, {"query": "dog"})
        assert out.data["clips"][0]["video_url"] == "https://v/sm.mp4"

    def test_key_passed_as_query_param(self, monkeypatch):
        from core.adapters.video_gen.pixabay import PixabayAdapter
        _cfg(monkeypatch, PIXABAY_API_KEY="pb-test")
        a = PixabayAdapter()
        with patch.object(a, "_http_request", return_value={"hits": []}) as m:
            a.execute(Capability.VIDEO_STOCK_SEARCH, {"query": "x"})
        assert m.call_args[1]["params"]["key"] == "pb-test"
        # Auth header does NOT carry the key.
        assert "Authorization" not in a._auth_headers()

    def test_per_page_minimum_enforced(self, monkeypatch):
        from core.adapters.video_gen.pixabay import PixabayAdapter
        _cfg(monkeypatch, PIXABAY_API_KEY="pb-test")
        a = PixabayAdapter()
        with patch.object(a, "_http_request", return_value={"hits": []}) as m:
            a.execute(Capability.VIDEO_STOCK_SEARCH, {"query": "x", "limit": 1})
        # Pixabay's minimum is 3; we clamp up.
        assert m.call_args[1]["params"]["per_page"] == 3


# ── Higgsfield (AI generator, async) ──────────────────────────


class TestHiggsfield:
    def test_metadata(self):
        from core.adapters.video_gen.higgsfield import HiggsfieldAdapter
        a = HiggsfieldAdapter()
        assert a.name == "higgsfield"
        assert Capability.VIDEO_GENERATE in a.capabilities
        assert Capability.VIDEO_GET_STATUS in a.capabilities
        assert Capability.VIDEO_STOCK_SEARCH not in a.capabilities
        assert a.kind == "ai"
        assert a.priority == 85

    def test_generate_request_shape(self, monkeypatch):
        from core.adapters.video_gen.higgsfield import HiggsfieldAdapter
        _cfg(monkeypatch, HIGGSFIELD_API_KEY="hf-test")
        a = HiggsfieldAdapter()
        raw = {"job": {"id": "job-1", "status": "processing"}}
        with patch.object(a, "_http_request", return_value=raw) as m:
            out = a.execute(Capability.VIDEO_GENERATE, {
                "prompt": "product on kitchen counter",
                "duration_seconds": 8,
                "aspect_ratio": "9:16",
                "style": "cinematic",
            })
        kwargs = m.call_args[1]
        assert kwargs["body"]["prompt"] == "product on kitchen counter"
        assert kwargs["body"]["duration"] == 8
        assert kwargs["body"]["aspect_ratio"] == "9:16"
        assert kwargs["body"]["style"] == "cinematic"
        # Response
        clip = out.data["clip"]
        assert clip["clip_id"] == "job-1"
        assert clip["status"] == "processing"
        assert clip["kind"] == "ai"
        assert clip["source"] == "higgsfield"
        assert clip["prompt"] == "product on kitchen counter"

    def test_status_ready_mapping(self, monkeypatch):
        from core.adapters.video_gen.higgsfield import HiggsfieldAdapter
        _cfg(monkeypatch, HIGGSFIELD_API_KEY="hf-test")
        a = HiggsfieldAdapter()
        raw = {
            "job": {
                "id": "job-9",
                "status": "succeeded",
                "output": {"video_url": "https://cdn.hf/job-9.mp4",
                           "thumbnail_url": "https://cdn.hf/job-9.jpg"},
                "duration": 6, "width": 1080, "height": 1920,
            },
        }
        with patch.object(a, "_http_request", return_value=raw):
            out = a.execute(Capability.VIDEO_GET_STATUS, {"job_id": "job-9"})
        clip = out.data["clip"]
        assert clip["status"] == "ready"
        assert clip["video_url"] == "https://cdn.hf/job-9.mp4"
        assert clip["thumbnail_url"] == "https://cdn.hf/job-9.jpg"
        assert clip["duration_seconds"] == 6

    def test_status_failed_mapping(self, monkeypatch):
        from core.adapters.video_gen.higgsfield import HiggsfieldAdapter
        _cfg(monkeypatch, HIGGSFIELD_API_KEY="hf-test")
        a = HiggsfieldAdapter()
        raw = {"job": {"id": "job-x", "status": "error"}}
        with patch.object(a, "_http_request", return_value=raw):
            out = a.execute(Capability.VIDEO_GET_STATUS, {"job_id": "job-x"})
        assert out.data["clip"]["status"] == "failed"

    def test_status_unknown_maps_to_processing(self, monkeypatch):
        from core.adapters.video_gen.higgsfield import HiggsfieldAdapter
        _cfg(monkeypatch, HIGGSFIELD_API_KEY="hf-test")
        a = HiggsfieldAdapter()
        raw = {"job": {"id": "job-q", "status": "queued"}}
        with patch.object(a, "_http_request", return_value=raw):
            out = a.execute(Capability.VIDEO_GET_STATUS, {"job_id": "job-q"})
        assert out.data["clip"]["status"] == "processing"

    def test_status_falls_back_to_job_id_when_payload_empty(self, monkeypatch):
        from core.adapters.video_gen.higgsfield import HiggsfieldAdapter
        _cfg(monkeypatch, HIGGSFIELD_API_KEY="hf-test")
        a = HiggsfieldAdapter()
        with patch.object(a, "_http_request", return_value={}):
            out = a.execute(Capability.VIDEO_GET_STATUS,
                            {"job_id": "backup-id"})
        assert out.data["clip"]["clip_id"] == "backup-id"

    def test_auth_header_scheme(self, monkeypatch):
        from core.adapters.video_gen.higgsfield import HiggsfieldAdapter
        _cfg(monkeypatch, HIGGSFIELD_API_KEY="hf-test")
        a = HiggsfieldAdapter()
        headers = a._auth_headers()
        assert headers["X-API-Key"] == "hf-test"
        assert "Authorization" not in headers

    def test_missing_prompt_raises(self, monkeypatch):
        from core.adapters.video_gen.higgsfield import HiggsfieldAdapter
        _cfg(monkeypatch, HIGGSFIELD_API_KEY="hf-test")
        a = HiggsfieldAdapter()
        result = a.execute(Capability.VIDEO_GENERATE, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_too_long_prompt_raises(self, monkeypatch):
        from core.adapters.video_gen.higgsfield import HiggsfieldAdapter
        _cfg(monkeypatch, HIGGSFIELD_API_KEY="hf-test")
        a = HiggsfieldAdapter()
        result = a.execute(Capability.VIDEO_GENERATE, {"prompt": "x" * 3000})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_missing_job_id_raises(self, monkeypatch):
        from core.adapters.video_gen.higgsfield import HiggsfieldAdapter
        _cfg(monkeypatch, HIGGSFIELD_API_KEY="hf-test")
        a = HiggsfieldAdapter()
        result = a.execute(Capability.VIDEO_GET_STATUS, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_duration_out_of_range_raises(self, monkeypatch):
        from core.adapters.video_gen.higgsfield import HiggsfieldAdapter
        _cfg(monkeypatch, HIGGSFIELD_API_KEY="hf-test")
        a = HiggsfieldAdapter()
        result = a.execute(Capability.VIDEO_GENERATE,
                           {"prompt": "x", "duration_seconds": 999})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── Replicate ────────────────────────────────────────────────


class TestReplicate:
    def test_metadata(self):
        from core.adapters.video_gen.replicate import ReplicateAdapter
        a = ReplicateAdapter()
        assert a.name == "replicate"
        assert Capability.VIDEO_GENERATE in a.capabilities
        assert Capability.VIDEO_GET_STATUS in a.capabilities
        assert a.priority == 70
        assert a.kind == "ai"

    def test_generate_extracts_version_from_model(self, monkeypatch):
        from core.adapters.video_gen.replicate import ReplicateAdapter
        _cfg(monkeypatch, REPLICATE_API_TOKEN="rp-test")
        a = ReplicateAdapter()
        raw = {"id": "pred-1", "status": "starting"}
        with patch.object(a, "_http_request", return_value=raw) as m:
            a.execute(Capability.VIDEO_GENERATE, {
                "prompt": "sunset beach",
                "model": "owner/model:abc123",
            })
        assert m.call_args[1]["body"]["version"] == "abc123"
        assert m.call_args[1]["body"]["input"]["prompt"] == "sunset beach"

    def test_status_succeeded_with_list_output(self, monkeypatch):
        from core.adapters.video_gen.replicate import ReplicateAdapter
        _cfg(monkeypatch, REPLICATE_API_TOKEN="rp-test")
        a = ReplicateAdapter()
        raw = {
            "id": "pred-2",
            "status": "succeeded",
            "output": ["https://cdn.rp/pred-2.mp4"],
        }
        with patch.object(a, "_http_request", return_value=raw):
            out = a.execute(Capability.VIDEO_GET_STATUS, {"job_id": "pred-2"})
        clip = out.data["clip"]
        assert clip["status"] == "ready"
        assert clip["video_url"] == "https://cdn.rp/pred-2.mp4"

    def test_status_succeeded_with_string_output(self, monkeypatch):
        from core.adapters.video_gen.replicate import ReplicateAdapter
        _cfg(monkeypatch, REPLICATE_API_TOKEN="rp-test")
        a = ReplicateAdapter()
        raw = {
            "id": "pred-3",
            "status": "succeeded",
            "output": "https://cdn.rp/pred-3.mp4",
        }
        with patch.object(a, "_http_request", return_value=raw):
            out = a.execute(Capability.VIDEO_GET_STATUS, {"job_id": "pred-3"})
        assert out.data["clip"]["video_url"] == "https://cdn.rp/pred-3.mp4"

    def test_status_failed_mapping(self, monkeypatch):
        from core.adapters.video_gen.replicate import ReplicateAdapter
        _cfg(monkeypatch, REPLICATE_API_TOKEN="rp-test")
        a = ReplicateAdapter()
        raw = {"id": "p", "status": "canceled"}
        with patch.object(a, "_http_request", return_value=raw):
            out = a.execute(Capability.VIDEO_GET_STATUS, {"job_id": "p"})
        assert out.data["clip"]["status"] == "failed"

    def test_auth_uses_token_not_bearer(self, monkeypatch):
        from core.adapters.video_gen.replicate import ReplicateAdapter
        _cfg(monkeypatch, REPLICATE_API_TOKEN="rp-test")
        a = ReplicateAdapter()
        headers = a._auth_headers()
        assert headers["Authorization"] == "Token rp-test"


# ── Normalisation safety ─────────────────────────────────────


class TestNormalisation:
    def test_missing_fields_default_to_empty(self, monkeypatch):
        from core.adapters.video_gen.pexels import PexelsAdapter
        _cfg(monkeypatch, PEXELS_API_KEY="pk-test")
        a = PexelsAdapter()
        raw = {"videos": [{"id": 1}]}
        with patch.object(a, "_http_request", return_value=raw):
            out = a.execute(Capability.VIDEO_STOCK_SEARCH, {"query": "x"})
        clip = out.data["clips"][0]
        # All fields must be present with safe defaults
        for key in (
            "clip_id", "source", "kind", "status",
            "video_url", "preview_url", "thumbnail_url",
            "duration_seconds", "width", "height", "format",
            "license", "cost_usd", "prompt", "raw_url",
        ):
            assert key in clip
        # Integer / float fields are not strings
        assert isinstance(clip["duration_seconds"], int)
        assert isinstance(clip["cost_usd"], float)

    def test_malformed_duration_survives(self, monkeypatch):
        from core.adapters.video_gen.pexels import PexelsAdapter
        _cfg(monkeypatch, PEXELS_API_KEY="pk-test")
        a = PexelsAdapter()
        raw = {"videos": [{"id": 1, "duration": "nonsense"}]}
        with patch.object(a, "_http_request", return_value=raw):
            out = a.execute(Capability.VIDEO_STOCK_SEARCH, {"query": "x"})
        assert out.data["clips"][0]["duration_seconds"] == 0

    def test_non_dict_records_skipped(self, monkeypatch):
        from core.adapters.video_gen.pexels import PexelsAdapter
        _cfg(monkeypatch, PEXELS_API_KEY="pk-test")
        a = PexelsAdapter()
        raw = {"videos": [{"id": 1}, "junk", 42, None, {"id": 2}]}
        with patch.object(a, "_http_request", return_value=raw):
            out = a.execute(Capability.VIDEO_STOCK_SEARCH, {"query": "x"})
        # Only dict records survive — non-dict in the raw response
        # shouldn't crash extraction; filter at normalisation time.
        assert out.data["total"] >= 1


# ── Bootstrap ────────────────────────────────────────────────


class TestBootstrap:
    def test_registers_all_four(self):
        from core.adapters.video_gen.bootstrap import register_all
        status = register_all()
        assert set(status.keys()) == {
            "pexels", "pixabay", "higgsfield", "replicate",
        }
        # None configured → all False
        assert all(v is False for v in status.values())

    def test_router_finds_adapter_by_capability(self, monkeypatch):
        from core.adapters.video_gen.bootstrap import register_all
        _cfg(monkeypatch, PEXELS_API_KEY="pk", HIGGSFIELD_API_KEY="hf")
        status = register_all()
        assert status["pexels"] is True
        assert status["higgsfield"] is True

        reg = get_registry()
        stock = reg.find_by_capability(Capability.VIDEO_STOCK_SEARCH)
        assert any(a.name == "pexels" for a in stock)
        gen = reg.find_by_capability(Capability.VIDEO_GENERATE)
        assert any(a.name == "higgsfield" for a in gen)

    def test_priority_ordering(self, monkeypatch):
        from core.adapters.video_gen.bootstrap import register_all
        _cfg(monkeypatch,
             PEXELS_API_KEY="pk",
             PIXABAY_API_KEY="pb",
             HIGGSFIELD_API_KEY="hf",
             REPLICATE_API_TOKEN="rp")
        register_all()

        reg = get_registry()
        stock = reg.find_by_capability(Capability.VIDEO_STOCK_SEARCH)
        # Pexels (90) before Pixabay (75) — registry orders by
        # priority descending among configured adapters.
        names = [a.name for a in stock if a.name in ("pexels", "pixabay")]
        assert names == ["pexels", "pixabay"]

        gen = reg.find_by_capability(Capability.VIDEO_GENERATE)
        names = [a.name for a in gen if a.name in ("higgsfield", "replicate")]
        assert names == ["higgsfield", "replicate"]
