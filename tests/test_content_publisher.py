"""Tests for engines.content_publisher — W963-6."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engines.content_publisher import ContentPublisherEngine
from engines.content_publisher.catalogs import (
    SUPPORTED_NICHES,
    catalog_summary,
    get_catalog,
)
from engines.content_publisher.draft_creator import (
    _candidate_to_params,
    enqueue_articles_for_approval,
)


# ── Catalog integrity ──────────────────────────────────────


class TestCatalogIntegrity:
    def test_all_niches_have_candidates(self):
        for niche in SUPPORTED_NICHES:
            rows = get_catalog(niche)
            assert len(rows) >= 10, (
                f"{niche} catalog too thin (got {len(rows)})"
            )

    def test_unknown_niche_empty(self):
        assert get_catalog("cars") == []
        assert get_catalog("") == []
        assert get_catalog(None) == []  # type: ignore[arg-type]

    def test_catalog_summary_lists_all(self):
        summary = catalog_summary()
        for n in SUPPORTED_NICHES:
            assert summary[n] >= 10

    def test_each_candidate_has_required_fields(self):
        for niche in SUPPORTED_NICHES:
            for c in get_catalog(niche):
                assert c.title
                assert c.body_html
                assert c.keyword
                assert isinstance(c.tags, list)
                assert "<p>" in c.body_html  # body is HTML

    def test_titles_within_seo_length(self):
        """SEO title sweet spot is < 65 chars for Google
        snippet preservation. Allow up to 80 for flexibility."""
        for niche in SUPPORTED_NICHES:
            for c in get_catalog(niche):
                assert len(c.title) <= 80, (
                    f"title too long: {c.title}"
                )


# ── Pattern Q envelope ─────────────────────────────────────


class TestPatternQEnvelope:
    def test_empty_input_success(self):
        result = ContentPublisherEngine().run({})
        assert set(result.keys()) == {
            "status", "data", "meta", "error",
        }
        assert result["status"] == "success"
        assert result["meta"]["engine"] == "content_publisher"

    def test_none_input_success(self):
        result = ContentPublisherEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_input_error(self):
        result = ContentPublisherEngine().run("not a dict")
        assert result["status"] == "error"

    def test_fail_upstream_short_circuits(self):
        result = ContentPublisherEngine().run({
            "status": "fail", "error": "upstream broke",
        })
        assert result["status"] == "error"


# ── Engine behaviour ──────────────────────────────────────


class TestEngineHappyPath:
    def test_beauty_default_returns_10(self):
        result = ContentPublisherEngine().run({
            "data": {"niche": "beauty"},
        })
        assert result["data"]["count_returned"] == 10

    def test_count_3_returns_3(self):
        result = ContentPublisherEngine().run({
            "data": {"niche": "tech", "count": 3},
        })
        assert result["data"]["count_returned"] == 3

    def test_each_candidate_has_body_html(self):
        result = ContentPublisherEngine().run({
            "data": {"niche": "home", "count": 2},
        })
        for c in result["data"]["candidates"]:
            assert "body_html" in c
            assert "<p>" in c["body_html"]
            assert "<h2>" in c["body_html"]


class TestEngineNiche:
    def test_unsupported_niche_error(self):
        result = ContentPublisherEngine().run({
            "data": {"niche": "automotive"},
        })
        assert result["status"] == "error"
        assert "unsupported niche" in (result["error"] or "")

    def test_uppercase_niche_normalised(self):
        result = ContentPublisherEngine().run({
            "data": {"niche": "TECH"},
        })
        assert result["status"] == "success"
        assert result["data"]["niche"] == "tech"

    def test_non_string_niche_error(self):
        result = ContentPublisherEngine().run({
            "data": {"niche": 42},
        })
        assert result["status"] == "error"


class TestEngineCount:
    def test_zero_count_error(self):
        result = ContentPublisherEngine().run({
            "data": {"niche": "food", "count": 0},
        })
        assert result["status"] == "error"

    def test_huge_count_capped(self):
        result = ContentPublisherEngine().run({
            "data": {"niche": "food", "count": 9999},
        })
        # Capped at MAX_COUNT or catalog size, whichever lower.
        assert result["data"]["count_returned"] <= 50


# ── draft_creator ──────────────────────────────────────────


class TestDraftCreatorParams:
    def test_required_fields_mapped(self):
        cand = {
            "title": "Test Post",
            "body_html": "<p>Body</p>",
            "meta_excerpt": "Summary",
            "keyword": "test",
            "tags": ["a", "b"],
        }
        params = _candidate_to_params(
            cand, niche="beauty", blog_id="gid://shopify/Blog/1",
        )
        assert params["title"] == "Test Post"
        assert params["body_html"] == "<p>Body</p>"
        assert params["blog_id"] == "gid://shopify/Blog/1"
        assert params["is_published"] is False
        assert params["author_name"] == "ShopAI Editorial"

    def test_metadata_block_carries_keyword(self):
        cand = {
            "title": "T", "body_html": "<p>B</p>",
            "meta_excerpt": "E", "keyword": "k",
        }
        params = _candidate_to_params(
            cand, niche="beauty", blog_id="b1",
        )
        meta = params["_metadata"]
        assert meta["niche"] == "beauty"
        assert meta["keyword"] == "k"

    def test_non_list_tags_become_empty(self):
        cand = {
            "title": "T", "body_html": "<p>B</p>",
            "meta_excerpt": "", "keyword": "",
            "tags": "not-a-list",
        }
        params = _candidate_to_params(
            cand, niche="beauty", blog_id="b1",
        )
        assert params["tags"] == []


class TestEnqueueArticles:
    def test_no_blog_id_returns_empty(self):
        cand = {
            "title": "T", "body_html": "<p>B</p>",
            "meta_excerpt": "", "keyword": "",
        }
        out = enqueue_articles_for_approval(
            [cand], niche="beauty", blog_id=None,
        )
        assert out == []

    def test_each_candidate_enqueued(self):
        fake_queue = MagicMock()
        fake_queue.enqueue.side_effect = [
            MagicMock(id="appr_a"), MagicMock(id="appr_b"),
        ]
        candidates = [
            {"title": "T1", "body_html": "<p>1</p>",
             "meta_excerpt": "", "keyword": ""},
            {"title": "T2", "body_html": "<p>2</p>",
             "meta_excerpt": "", "keyword": ""},
        ]
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            out = enqueue_articles_for_approval(
                candidates, niche="beauty",
                blog_id="gid://shopify/Blog/1",
            )
        assert len(out) == 2
        assert out[0]["pending_action_id"] == "appr_a"

    def test_missing_title_skipped(self):
        fake_queue = MagicMock()
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            out = enqueue_articles_for_approval(
                [{"title": ""}], niche="beauty", blog_id="b1",
            )
        assert out == []
        fake_queue.enqueue.assert_not_called()


# ── End-to-end via engine ──────────────────────────────────


class TestEngineApplyPath:
    def test_apply_without_blog_id_yields_empty_pending(self):
        result = ContentPublisherEngine().run({
            "data": {
                "niche": "beauty", "count": 3,
                "apply_candidates": True,
            },
        })
        # Engine succeeds but enqueue path returns [] because
        # no blog_id was supplied.
        assert result["status"] == "success"
        assert result["data"]["pending_actions"] == []

    def test_apply_with_blog_id_queues(self):
        fake_queue = MagicMock()
        fake_queue.enqueue.side_effect = lambda **kw: MagicMock(
            id="appr_" + kw["params"]["title"][:6].replace(" ", "_"),
        )
        with patch(
            "core.approval.get_approval_queue",
            return_value=fake_queue,
        ):
            result = ContentPublisherEngine().run({
                "data": {
                    "niche": "tech", "count": 2,
                    "apply_candidates": True,
                    "blog_id": "gid://shopify/Blog/123",
                },
            })
        assert len(result["data"]["pending_actions"]) == 2
        assert "enqueued" in result["data"]["next_action"]
