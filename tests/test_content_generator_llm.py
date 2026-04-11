"""Tests for the LLM-backed ContentGenerator wrappers."""
import pytest


# ── Helpers ──────────────────────────────────────────────────


class _FakeStructured:
    def __init__(self, ok=True, data=None, error=""):
        self.ok = ok
        self.data = data or {}
        self.error = error
        self.raw_text = ""


class _FakeLLM:
    def __init__(self, *, available=True, structured_data=None,
                 raise_on_call=False):
        self._available = available
        self._structured = structured_data
        self._raise = raise_on_call
        self.calls = []

    def is_available(self):
        return self._available

    def ask_structured(self, role="", prompt="", system_prompt="",
                       schema_hint="", **kw):
        self.calls.append({"role": role, "prompt": prompt})
        if self._raise:
            raise RuntimeError("LLM down")
        if self._structured is None:
            return _FakeStructured(ok=False, error="no data")
        return _FakeStructured(ok=True, data=self._structured)


def _cg(llm=None):
    from core.intelligence.content_generator import ContentGenerator
    return ContentGenerator(llm=llm)


_PRODUCT = {
    "name": "Cozy Wool Blanket",
    "category": "home",
    "price": 79.0,
    "features": ["100% merino", "machine washable", "queen size"],
}


# ── Heuristic always runs ────────────────────────────────────


class TestProductDescriptionHeuristicAlwaysRuns:
    def test_no_llm_returns_heuristic_only(self):
        cg = _cg()
        result = cg.product_description_with_llm(_PRODUCT)
        assert result["source"] == "heuristic_only"
        assert result["heuristic"] is not None
        assert result["heuristic"]["headline"]
        assert result["llm"] is None

    def test_unavailable_llm_returns_heuristic_only(self):
        cg = _cg(_FakeLLM(available=False))
        result = cg.product_description_with_llm(_PRODUCT)
        assert result["source"] == "heuristic_only"
        assert result["llm"] is None

    def test_llm_exception_returns_heuristic_only_with_error(self):
        cg = _cg(_FakeLLM(raise_on_call=True))
        result = cg.product_description_with_llm(_PRODUCT)
        # Heuristic still present
        assert result["heuristic"] is not None
        # LLM block carries the error
        assert result["llm"]["error"]


# ── product_description_with_llm happy path ────────────────


class TestProductDescriptionLLMHappyPath:
    def test_full_rewrite(self):
        llm = _FakeLLM(structured_data={
            "headline": "Wrap Yourself in Cozy Luxury",
            "subheadline": "Pure merino, ready to spoil you",
            "body": "Real merino wool, hand-finished edges, "
                    "queen-size — built for long winter nights.",
            "bullets": [
                "100% merino wool",
                "Hand-finished edges",
                "Machine washable",
                "Queen-size dimensions",
            ],
            "meta_description": "Premium merino wool queen blanket — "
                                 "machine washable, hand finished.",
        })
        cg = _cg(llm)
        result = cg.product_description_with_llm(_PRODUCT, tone="warm")
        assert result["source"] == "llm"
        rec = result["llm"]
        assert "Cozy Luxury" in rec["headline"]
        assert "merino" in rec["body"].lower()
        assert len(rec["bullets"]) == 4
        assert len(rec["meta_description"]) <= 160
        # Heuristic still preserved
        assert result["heuristic"]["headline"]

    def test_prompt_includes_product_data(self):
        llm = _FakeLLM(structured_data={
            "headline": "x", "subheadline": "x", "body": "x",
            "bullets": [], "meta_description": "x",
        })
        cg = _cg(llm)
        cg.product_description_with_llm(_PRODUCT, tone="playful")
        prompt = llm.calls[0]["prompt"]
        assert "Cozy Wool Blanket" in prompt
        assert "merino" in prompt
        assert "playful" in prompt


# ── product_description_with_llm defensive ────────────────


class TestProductDescriptionLLMDefensive:
    def test_unparseable_returns_error_block(self):
        cg = _cg(_FakeLLM(structured_data=None))
        result = cg.product_description_with_llm(_PRODUCT)
        assert result["source"] == "heuristic_only"
        assert "error" in result["llm"]

    def test_bullets_capped_at_6(self):
        llm = _FakeLLM(structured_data={
            "headline": "x", "subheadline": "x", "body": "x",
            "bullets": [f"bullet {i}" for i in range(20)],
            "meta_description": "x",
        })
        cg = _cg(llm)
        result = cg.product_description_with_llm(_PRODUCT)
        assert len(result["llm"]["bullets"]) == 6

    def test_meta_description_truncated_at_160(self):
        long_meta = "x" * 200
        llm = _FakeLLM(structured_data={
            "headline": "x", "subheadline": "x", "body": "x",
            "bullets": [], "meta_description": long_meta,
        })
        cg = _cg(llm)
        result = cg.product_description_with_llm(_PRODUCT)
        assert len(result["llm"]["meta_description"]) <= 160

    def test_missing_fields_default_to_heuristic_or_empty(self):
        llm = _FakeLLM(structured_data={})  # totally empty payload
        cg = _cg(llm)
        result = cg.product_description_with_llm(_PRODUCT)
        # Treated as ok=True but with empty fields → falls back to
        # heuristic headline
        rec = result["llm"]
        assert rec["headline"] == result["heuristic"]["headline"]


# ── ad_copy_with_llm ─────────────────────────────────────────


class TestAdCopyWithLLM:
    def test_no_llm_returns_heuristic_only(self):
        cg = _cg()
        result = cg.ad_copy_with_llm(_PRODUCT, platform="facebook")
        assert result["source"] == "heuristic_only"
        assert result["heuristic"] is not None

    def test_full_rewrite(self):
        llm = _FakeLLM(structured_data={
            "headline": "Wrap up the cold",
            "body": "Pure merino wool. Free shipping over $50.",
            "cta": "Shop the Blanket",
            "tags": ["winter", "merino", "cozy"],
        })
        cg = _cg(llm)
        result = cg.ad_copy_with_llm(_PRODUCT, platform="instagram")
        assert result["source"] == "llm"
        rec = result["llm"]
        assert "merino" in rec["body"].lower()
        assert rec["cta"] == "Shop the Blanket"
        assert "winter" in rec["tags"]

    def test_prompt_passes_platform(self):
        llm = _FakeLLM(structured_data={
            "headline": "x", "body": "x", "cta": "Buy", "tags": [],
        })
        cg = _cg(llm)
        cg.ad_copy_with_llm(_PRODUCT, platform="tiktok")
        assert "tiktok" in llm.calls[0]["prompt"]

    def test_tags_capped_at_8(self):
        llm = _FakeLLM(structured_data={
            "headline": "x", "body": "x", "cta": "Buy",
            "tags": [f"tag{i}" for i in range(20)],
        })
        cg = _cg(llm)
        result = cg.ad_copy_with_llm(_PRODUCT)
        assert len(result["llm"]["tags"]) == 8

    def test_unparseable_returns_error(self):
        cg = _cg(_FakeLLM(structured_data=None))
        result = cg.ad_copy_with_llm(_PRODUCT)
        assert "error" in result["llm"]


# ── Edge inputs ──────────────────────────────────────────────


class TestEdgeInputs:
    def test_empty_product_handled(self):
        cg = _cg()
        result = cg.product_description_with_llm({})
        assert result["heuristic"] is not None

    def test_product_with_no_features(self):
        cg = _cg()
        result = cg.product_description_with_llm({
            "name": "Mystery Box", "category": "home",
        })
        assert result["heuristic"]["headline"]


# ── Prompt library entries ───────────────────────────────────


class TestPromptsRegistered:
    def test_product_description_prompt_exists(self):
        from core.system.prompt_library import get_prompt
        p = get_prompt("content.product_description")
        assert p is not None
        assert "headline" in p.placeholders or "product_name" in p.placeholders
        assert p.role == "creative"

    def test_ad_copy_prompt_exists(self):
        from core.system.prompt_library import get_prompt
        p = get_prompt("content.ad_copy")
        assert p is not None
        assert "platform" in p.placeholders
