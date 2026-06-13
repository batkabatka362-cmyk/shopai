"""W963-149: brand identity composer tests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engines.brand_identity_composer import (
    BrandBrief,
    BrandIdentityComposerEngine,
    ColorPalette,
    Typography,
    build_brief,
    brief_to_markdown,
)
from engines.brand_identity_composer.composer import (
    _NICHE_TEMPLATES,
    _normalise_niche,
    _parse_llm_brand_json,
)


class TestNicheTemplate:
    def test_known_niches_unchanged(self):
        for n in (
            "beauty", "tech", "fashion", "home", "food",
            "general",
        ):
            assert _normalise_niche(n) == n

    def test_unknown_falls_back_to_general(self):
        assert (
            _normalise_niche("random_weird") == "general"
        )

    def test_empty_falls_back_to_general(self):
        assert _normalise_niche("") == "general"

    def test_case_insensitive(self):
        assert (
            _normalise_niche("BEAUTY") == "beauty"
        )

    def test_template_shape(self):
        for niche, t in _NICHE_TEMPLATES.items():
            assert "palette" in t
            assert "fonts" in t
            assert "voice" in t
            for k in (
                "primary", "secondary", "accent",
                "text", "background",
            ):
                assert k in t["palette"]


class TestParseLLMJson:
    def test_clean_json(self):
        out = _parse_llm_brand_json(
            '{"names": ["A", "B"], '
            '"tagline": "x", "voice": "y"}',
        )
        assert out["names"] == ["A", "B"]
        assert out["tagline"] == "x"

    def test_in_prose(self):
        out = _parse_llm_brand_json(
            "Sure! Here is the JSON:\n"
            '{"names": ["X"], "tagline": "y", '
            '"voice": "z"}'
        )
        assert out["names"] == ["X"]

    def test_no_json_returns_empty(self):
        assert _parse_llm_brand_json(
            "no JSON here at all",
        ) == {}

    def test_invalid_json_returns_empty(self):
        assert _parse_llm_brand_json(
            "{not valid json}",
        ) == {}


class TestBuildBrief:
    def test_requires_store_id(self):
        with pytest.raises(ValueError):
            build_brief("", niche="beauty")

    def test_seeds_template_even_without_llm(self):
        """When LLM is unavailable, palette + typography
        still come from the niche template."""
        with patch(
            "engines.brand_identity_composer."
            "composer._safe_llm_brand_brief",
            return_value={},
        ), patch(
            "engines.brand_identity_composer."
            "composer._safe_logo_concepts",
            return_value=[],
        ), patch(
            "engines.brand_identity_composer."
            "composer._safe_hero_candidates",
            return_value=[],
        ):
            brief = build_brief(
                "store_a", niche="beauty",
            )
        assert brief.palette is not None
        assert brief.palette.primary == "#E8B4BC"
        assert brief.typography is not None
        # LLM diagnostic note surfaces
        assert any(
            "LLM" in n for n in brief.notes
        )

    def test_unknown_niche_falls_back(self):
        with patch(
            "engines.brand_identity_composer."
            "composer._safe_llm_brand_brief",
            return_value={},
        ), patch(
            "engines.brand_identity_composer."
            "composer._safe_logo_concepts",
            return_value=[],
        ), patch(
            "engines.brand_identity_composer."
            "composer._safe_hero_candidates",
            return_value=[],
        ):
            brief = build_brief(
                "store_a", niche="nonexistent",
            )
        assert brief.niche == "general"
        assert any(
            "not in catalogue" in n
            for n in brief.notes
        )

    def test_llm_fills_names_tagline_voice(self):
        with patch(
            "engines.brand_identity_composer."
            "composer._safe_llm_brand_brief",
            return_value={
                "names": [
                    "Aurora", "Luxe", "Velvet",
                ],
                "tagline": (
                    "Beauty for the modern soul"
                ),
                "voice": (
                    "warm + aspirational + clean"
                ),
            },
        ), patch(
            "engines.brand_identity_composer."
            "composer._safe_logo_concepts",
            return_value=[],
        ), patch(
            "engines.brand_identity_composer."
            "composer._safe_hero_candidates",
            return_value=[],
        ):
            brief = build_brief(
                "store_a", niche="beauty",
            )
        assert brief.brand_name_suggestions == [
            "Aurora", "Luxe", "Velvet",
        ]
        assert "modern soul" in brief.tagline
        assert "warm" in brief.voice

    def test_logo_concepts_present_when_names_resolve(
        self,
    ):
        with patch(
            "engines.brand_identity_composer."
            "composer._safe_llm_brand_brief",
            return_value={"names": ["Aurora"]},
        ), patch(
            "engines.brand_identity_composer."
            "composer._safe_logo_concepts",
            return_value=[
                {
                    "brand_name": "Aurora",
                    "url": "https://x.com/logo.png",
                    "source": "image_gen",
                },
            ],
        ), patch(
            "engines.brand_identity_composer."
            "composer._safe_hero_candidates",
            return_value=[],
        ):
            brief = build_brief(
                "store_a", niche="beauty",
            )
        assert len(brief.logo_concepts) == 1


class TestBriefToMarkdown:
    def test_renders_palette_and_typo(self):
        brief = BrandBrief(
            store_id="store_a",
            niche="beauty",
            palette=ColorPalette(
                primary="#A",
                secondary="#B",
                accent="#C",
                text="#D",
                background="#E",
            ),
            typography=Typography(
                heading="Foo",
                body="Bar",
            ),
            brand_name_suggestions=["Aurora"],
        )
        md = brief_to_markdown(brief)
        assert "Aurora" in md
        assert "#A" in md
        assert "Foo" in md
        assert "Approve" in md
        assert "Reject" in md


class TestEnvelope:
    def test_requires_store_id(self):
        r = BrandIdentityComposerEngine().run({})
        assert r["status"] == "error"
        assert "store_id" in r["error"].lower()

    def test_envelope_carries_engine(self):
        with patch(
            "engines.brand_identity_composer."
            "composer._safe_llm_brand_brief",
            return_value={},
        ), patch(
            "engines.brand_identity_composer."
            "composer._safe_logo_concepts",
            return_value=[],
        ), patch(
            "engines.brand_identity_composer."
            "composer._safe_hero_candidates",
            return_value=[],
        ):
            r = BrandIdentityComposerEngine().run({
                "data": {
                    "store_id": "store_a",
                    "niche": "beauty",
                },
            })
        assert r["status"] == "success"
        assert r["meta"]["engine"] == (
            "brand_identity_composer"
        )

    def test_dry_run_no_queue(self):
        with patch(
            "engines.brand_identity_composer."
            "composer._safe_llm_brand_brief",
            return_value={"names": ["Aurora"]},
        ), patch(
            "engines.brand_identity_composer."
            "composer._safe_logo_concepts",
            return_value=[
                {
                    "brand_name": "Aurora",
                    "url": "u",
                },
            ],
        ), patch(
            "engines.brand_identity_composer."
            "composer._safe_hero_candidates",
            return_value=[],
        ):
            r = BrandIdentityComposerEngine().run({
                "data": {
                    "store_id": "store_a",
                    "niche": "beauty",
                    "submit_to_queue": False,
                },
            })
        assert r["data"]["approval_action_id"] == ""

    def test_submit_enqueues(self):
        fake_queue = MagicMock()
        fake_action = MagicMock()
        fake_action.id = "act_brand_1"
        fake_queue.enqueue.return_value = fake_action
        with patch(
            "engines.brand_identity_composer."
            "composer._safe_llm_brand_brief",
            return_value={"names": ["Aurora"]},
        ), patch(
            "engines.brand_identity_composer."
            "composer._safe_logo_concepts",
            return_value=[
                {
                    "brand_name": "Aurora",
                    "url": "u",
                },
            ],
        ), patch(
            "engines.brand_identity_composer."
            "composer._safe_hero_candidates",
            return_value=[],
        ), patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            r = BrandIdentityComposerEngine().run({
                "data": {
                    "store_id": "store_a",
                    "niche": "beauty",
                    "submit_to_queue": True,
                },
            })
        assert r["data"]["approval_action_id"] == (
            "act_brand_1"
        )
        kwargs = (
            fake_queue.enqueue.call_args.kwargs
        )
        assert kwargs["action_type"] == (
            "apply_brand_identity"
        )
        assert kwargs["store_id"] == "store_a"
